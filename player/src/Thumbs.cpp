#include "Thumbs.h"

#include "rcplayer/AvfVideoPlayer.h"
#include "rcplayer/MediaTypes.h"
#include "rcplayer/Player.h"
#include "rcplayer/StillHosts.h"
#include "rcplayer/WebpPlayer.h"

#include "rccore/CoreDocument.h"
#include "rccore/RemoteContext.h"
#include "rccore/TimeVariables.h"
#include "rccore/WireBuffer.h"
#include "rcskia/SkiaPaintContext.h"

#include "include/core/SkCanvas.h"
#include "include/core/SkColor.h"
#include "include/core/SkSurface.h"

#include <chrono>
#include <cstdio>
#include <deque>
#include <filesystem>
#include <map>
#include <memory>
#include <string>

namespace fs = std::filesystem;

namespace refract {

namespace {

// How far into its animation a still is taken. Far enough that a slide which animates in
// from the previous one has arrived.
constexpr double kSettleSec = 1.2;
// Steps used to get there. The document has to be walked through real frames — animation
// state is carried between them, and a single paint at the end time shows the *previous*
// slide, mid-transition. Eight is enough for the transitions refract emits to land;
// stepping at frame rate (36 steps) looks no different and costs four times as much.
constexpr int kSettleSteps = 8;

struct Key {
    std::string entry;
    int w = 0, h = 0;
    bool operator<(const Key& o) const {
        if (entry != o.entry) return entry < o.entry;
        if (w != o.w) return w < o.w;
        return h < o.h;
    }
};

// A still part-way through being built. Member order matters: the paint context refers to
// the remote context, which refers to the document, so they must be destroyed in reverse.
struct Job {
    Key key;
    std::unique_ptr<rccore::CoreDocument> doc;
    std::unique_ptr<rcplayer::StillHosts> hosts;
    std::unique_ptr<rccore::RemoteContext> ctx;
    std::unique_ptr<rcskia::SkiaPaintContext> paintCtx;
    sk_sp<SkSurface> surface;
    rccore::TimeVariables tv;
    int64_t baseWallMs = 0;
    float scale = 1, ox = 0, oy = 0;
    int step = 0;
};

std::map<Key, sk_sp<SkImage>>& cache() {
    static std::map<Key, sk_sp<SkImage>> c;
    return c;
}

std::deque<Job>& jobs() {
    static std::deque<Job> q;
    return q;
}

double nowSec() {
    return std::chrono::duration<double>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

// Videos and animated images contribute their first frame — enough to recognise the slide,
// and cheap enough to do in one go.
sk_sp<SkImage> renderMedia(const std::string& entry, const std::string& ext,
                           int width, int height) {
    auto surface = SkSurfaces::Raster(SkImageInfo::MakeN32Premul(width, height));
    if (!surface) return nullptr;
    SkCanvas* canvas = surface->getCanvas();
    canvas->clear(SK_ColorBLACK);

    if (rcplayer::isCodecVideoExt(ext)) {
        std::vector<uint8_t> bytes;
        if (!rcplayer::readFileBytes(entry, bytes)) return nullptr;
        auto player = rcplayer::WebpPlayer::LoadFromData(bytes);
        if (!player) return nullptr;
        player->paint(canvas, 0.0, width, height);
        return surface->makeImageSnapshot();
    }

    // AVFoundation needs a real file, so a clip inside a zip is spilled to a temp path.
    std::string path = entry;
    std::string temp;
    if (rcplayer::g.zip) {
        temp = "/tmp/refractplayer_thumb_" + rcplayer::baseName(entry);
        if (!rcplayer::g.zip->extractToFile(entry, temp)) return nullptr;
        path = temp;
    }
    auto frame = AvfVideoPlayer::ExtractFirstFrame(path);
    if (!temp.empty()) std::remove(temp.c_str());
    if (!frame) return nullptr;

    float scale = std::min(static_cast<float>(width) / frame->width(),
                           static_cast<float>(height) / frame->height());
    float w = frame->width() * scale, h = frame->height() * scale;
    SkRect dst = SkRect::MakeXYWH((width - w) * 0.5f, (height - h) * 0.5f, w, h);
    canvas->drawImageRect(frame, dst, SkSamplingOptions(SkFilterMode::kLinear));
    return surface->makeImageSnapshot();
}

// Set up an .rc job: parse the document and build its own engine instance. Deliberately
// private state — the live document has touch state, a bound canvas and running media, and
// none of that should move because a still was requested.
bool startRcJob(Job& job) {
    std::vector<uint8_t> bytes;
    if (!rcplayer::readFileBytes(job.key.entry, bytes) || bytes.empty()) return false;

    job.doc = std::make_unique<rccore::CoreDocument>();
    rccore::WireBuffer buffer(bytes.data(), bytes.size());
    if (!job.doc->initFromBuffer(buffer)) return false;

    const int docW = job.doc->getWidth()  > 0 ? job.doc->getWidth()  : job.key.w;
    const int docH = job.doc->getHeight() > 0 ? job.doc->getHeight() : job.key.h;

    job.surface = SkSurfaces::Raster(SkImageInfo::MakeN32Premul(job.key.w, job.key.h));
    if (!job.surface) return false;

    // Lay out at the document's design size and scale the whole thing down onto the still —
    // the same fit playback uses. Laying out at thumbnail size would re-flow the text and
    // give a preview that does not match the slide.
    job.scale = std::min(static_cast<float>(job.key.w) / docW,
                         static_cast<float>(job.key.h) / docH);
    job.ox = (job.key.w - docW * job.scale) * 0.5f;
    job.oy = (job.key.h - docH * job.scale) * 0.5f;

    job.ctx = std::make_unique<rccore::RemoteContext>();
    job.paintCtx = std::make_unique<rcskia::SkiaPaintContext>(*job.ctx,
                                                              job.surface->getCanvas());
    job.ctx->setPaintContext(job.paintCtx.get());
    job.ctx->setDocument(job.doc.get());
    // A slide's embedded content is drawn by custom hosts, and the live ones cannot serve an
    // off-screen render: the video host plays asynchronously and the web host needs a window.
    // Without these, a slide built around embedded demos previews as an empty frame — which
    // is the preview you most need to be right. Web embeds still come out blank; nothing can
    // paint a WKWebView into a raster surface.
    job.hosts = std::make_unique<rcplayer::StillHosts>(
        fs::path(job.key.entry).parent_path().string());
    job.hosts->installOn(*job.ctx);
    job.ctx->mWidth  = static_cast<float>(docW);
    job.ctx->mHeight = static_cast<float>(docH);
    job.ctx->loadFloat(rccore::RemoteContext::ID_TOUCH_POS_X, 0.0f);
    job.ctx->loadFloat(rccore::RemoteContext::ID_TOUCH_POS_Y, 0.0f);
    job.doc->registerListeners(*job.ctx);
    job.doc->applyDataOperations(*job.ctx);

    // The wall clock is pinned to the same schedule as the animation being stepped, or
    // clock-driven effects race ahead of the frames we walk through and the still stops
    // matching the slide.
    job.baseWallMs = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    return true;
}

// One settle step. Returns true when the job is finished.
bool advanceRcJob(Job& job) {
    const double step = kSettleSec / kSettleSteps;
    const double t = job.step * step;

    job.doc->setFixedTimeMs(job.baseWallMs + static_cast<int64_t>(t * 1000.0));
    job.tv.updateTime(*job.ctx, t, step);

    SkCanvas* canvas = job.surface->getCanvas();
    canvas->save();
    canvas->clear(SK_ColorBLACK);
    canvas->translate(job.ox, job.oy);
    canvas->scale(job.scale, job.scale);
    job.doc->paint(*job.ctx);
    canvas->restore();

    return ++job.step >= kSettleSteps;
}

// The most jobs worth keeping in flight. Scrolling the navigator asks for a still per row
// it passes, and building all of them would spend the machine on previews nobody stopped
// on. Beyond this, the ones that have not started yet are dropped from the back.
constexpr size_t kMaxJobs = 4;

bool sameKey(const Key& a, const Key& b) {
    return a.entry == b.entry && a.w == b.w && a.h == b.h;
}

// Queue a job for `key` unless the still is already cached. A job that is queued but has
// not started is moved to the front: the caller is asking for it now, and whatever was
// queued before it is speculative.
void enqueue(const Key& key, bool urgent) {
    if (key.entry.empty() || key.w <= 0 || key.h <= 0) return;
    if (cache().count(key)) return;
    for (size_t i = 0; i < jobs().size(); i++) {
        if (!sameKey(jobs()[i].key, key)) continue;
        if (urgent && i > 0 && jobs()[i].step == 0) {
            Job job = std::move(jobs()[i]);
            jobs().erase(jobs().begin() + i);
            jobs().push_front(std::move(job));
        }
        return;
    }

    const std::string ext = rcplayer::getExt(key.entry);
    if (!rcplayer::isRcExt(ext)) {
        // Media stills are one extract, not a settle loop — no point deferring them.
        cache()[key] = renderMedia(key.entry, ext, key.w, key.h);
        return;
    }

    Job job;
    job.key = key;
    if (!startRcJob(job)) {
        cache()[key] = nullptr;   // remember the failure so it isn't retried every frame
        return;
    }
    if (urgent) jobs().push_front(std::move(job));
    else        jobs().push_back(std::move(job));

    // Trim speculative work. Never drop the job at the front — it may be half-built, and
    // throwing that away would mean starting it over the next time it is asked for.
    while (jobs().size() > kMaxJobs) {
        auto victim = jobs().end();
        for (auto it = jobs().begin() + 1; it != jobs().end(); ++it) {
            if (it->step == 0) victim = it;
        }
        if (victim == jobs().end()) break;
        jobs().erase(victim);
    }
}

}  // namespace

sk_sp<SkImage> thumbIfReady(const std::string& entry, int width, int height) {
    Key key{entry, width, height};
    auto it = cache().find(key);
    if (it != cache().end()) return it->second;
    enqueue(key, /*urgent=*/true);   // somebody is looking at this pane right now
    return nullptr;
}

sk_sp<SkImage> thumbCached(const std::string& entry, int width, int height) {
    auto it = cache().find(Key{entry, width, height});
    return it != cache().end() ? it->second : nullptr;
}

void requestThumb(const std::string& entry, int width, int height) {
    enqueue(Key{entry, width, height}, /*urgent=*/false);
}

void pumpThumbs(double budgetSeconds) {
    if (jobs().empty()) return;
    const double deadline = nowSec() + budgetSeconds;
    do {
        Job& job = jobs().front();
        if (advanceRcJob(job)) {
            cache()[job.key] = job.surface->makeImageSnapshot();
            jobs().pop_front();
        }
    } while (!jobs().empty() && nowSec() < deadline);
}

void clearThumbCache() {
    cache().clear();
    jobs().clear();
}

}  // namespace refract
