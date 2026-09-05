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
#include <condition_variable>
#include <cstdio>
#include <deque>
#include <mutex>
#include <thread>
#include <utility>
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

// A still being built, entirely on the worker thread. Member order matters: the paint
// context refers to the remote context, which refers to the document, so they must be
// destroyed in reverse.
struct Job {
    Key key;
    std::vector<uint8_t> bytes;   // read on the main thread — see enqueue
    std::string mediaPath;        // a real file for AVFoundation, when the still is a video
    bool mediaTemp = false;       // ...and it was spilled out of a zip
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
sk_sp<SkImage> renderMedia(const std::string& ext, const std::vector<uint8_t>& bytes,
                           const std::string& path, int width, int height) {
    auto surface = SkSurfaces::Raster(SkImageInfo::MakeN32Premul(width, height));
    if (!surface) return nullptr;
    SkCanvas* canvas = surface->getCanvas();
    canvas->clear(SK_ColorBLACK);

    if (rcplayer::isCodecVideoExt(ext)) {
        if (bytes.empty()) return nullptr;
        auto player = rcplayer::WebpPlayer::LoadFromData(bytes);
        if (!player) return nullptr;
        player->paint(canvas, 0.0, width, height);
        return surface->makeImageSnapshot();
    }

    if (path.empty()) return nullptr;
    auto frame = AvfVideoPlayer::ExtractFirstFrame(path);
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
    if (job.bytes.empty()) return false;

    job.doc = std::make_unique<rccore::CoreDocument>();
    rccore::WireBuffer buffer(job.bytes.data(), job.bytes.size());
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

bool sameKey(const Key& a, const Key& b) {
    return a.entry == b.entry && a.w == b.w && a.h == b.h;
}

// ── The worker ───────────────────────────────────────────────────────
//
// One thread, one queue. A still is a full document render — parse, lay out, compile the
// shaders, then step through eight frames of the opening animation — and on a heavy slide
// that is over a second. Doing it on the main thread meant the deck froze for exactly as
// long, at exactly the moment somebody had scrolled or pressed a key, which is the worst
// possible time. So it happens over here, and the main thread only ever picks up finished
// pictures.
//
// What crosses the boundary is deliberately small: bytes in, an SkImage out. Every request is
// read from disk on the main thread (a zip archive is one shared handle and cannot be read
// from two threads), and the raster SkImage that comes back is immutable.
struct Queue {
    std::mutex mutex;
    std::condition_variable wake;
    std::deque<Job> pending;
    std::vector<std::pair<Key, sk_sp<SkImage>>> done;
    // Bumped by clearThumbCache. Anything a worker finishes from an older generation is
    // dropped: the deck it was rendering no longer exists.
    uint64_t generation = 0;
    bool stopping = false;
    bool started = false;
    std::thread thread;
};

Queue& queue() {
    static Queue q;
    return q;
}

void renderJob(Job& job, sk_sp<SkImage>* out) {
    const std::string ext = rcplayer::getExt(job.key.entry);
    if (!rcplayer::isRcExt(ext)) {
        *out = renderMedia(ext, job.bytes, job.mediaPath, job.key.w, job.key.h);
        // A clip spilled out of a zip so AVFoundation could open it has served its purpose.
        if (job.mediaTemp) std::remove(job.mediaPath.c_str());
        return;
    }
    if (!startRcJob(job)) {
        *out = nullptr;                       // a failure is cached, not retried every frame
        return;
    }
    while (!advanceRcJob(job)) {}
    *out = job.surface->makeImageSnapshot();
}

void workerLoop() {
    Queue& q = queue();
    for (;;) {
        Job job;
        uint64_t generation = 0;
        {
            std::unique_lock<std::mutex> lock(q.mutex);
            q.wake.wait(lock, [&q] { return q.stopping || !q.pending.empty(); });
            if (q.stopping) return;
            job = std::move(q.pending.front());
            q.pending.pop_front();
            generation = q.generation;
        }
        sk_sp<SkImage> image;
        renderJob(job, &image);
        {
            std::lock_guard<std::mutex> lock(q.mutex);
            // Dropped rather than delivered when the deck was reloaded underneath it.
            if (generation == q.generation) q.done.push_back({job.key, std::move(image)});
        }
    }
}

void ensureWorker() {
    Queue& q = queue();
    if (q.started) return;
    q.started = true;
    q.thread = std::thread(workerLoop);
}

// Queue a still unless it is cached or already queued. `urgent` moves an existing request to
// the front: the caller is looking at that pane now, and what was queued before it is
// speculative.
void enqueue(const Key& key, bool urgent) {
    if (key.entry.empty() || key.w <= 0 || key.h <= 0) return;
    if (cache().count(key)) return;

    Queue& q = queue();
    {
        std::lock_guard<std::mutex> lock(q.mutex);
        for (size_t i = 0; i < q.pending.size(); i++) {
            if (!sameKey(q.pending[i].key, key)) continue;
            if (urgent && i > 0) {
                Job job = std::move(q.pending[i]);
                q.pending.erase(q.pending.begin() + i);
                q.pending.push_front(std::move(job));
            }
            return;
        }
    }

    // Read here, on the main thread. The bytes may come from a zip archive, which is one
    // shared handle with a read cursor — the one thing in this path that cannot be touched
    // from two threads at once.
    Job job;
    job.key = key;
    const std::string ext = rcplayer::getExt(key.entry);
    if (rcplayer::isRcExt(ext) || rcplayer::isCodecVideoExt(ext)) {
        if (!rcplayer::readFileBytes(key.entry, job.bytes) || job.bytes.empty()) {
            cache()[key] = nullptr;
            return;
        }
    } else {
        // AVFoundation needs a real file, so a clip inside a zip is spilled to a temp path
        // before the worker ever sees it.
        job.mediaPath = key.entry;
        if (rcplayer::g.zip) {
            job.mediaPath = "/tmp/refractplayer_thumb_" + rcplayer::baseName(key.entry);
            if (!rcplayer::g.zip->extractToFile(key.entry, job.mediaPath)) {
                cache()[key] = nullptr;
                return;
            }
            job.mediaTemp = true;
        }
    }

    ensureWorker();
    {
        std::lock_guard<std::mutex> lock(q.mutex);
        if (urgent) q.pending.push_front(std::move(job));
        else        q.pending.push_back(std::move(job));
    }
    q.wake.notify_one();
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

void collectThumbs() {
    Queue& q = queue();
    std::vector<std::pair<Key, sk_sp<SkImage>>> finished;
    {
        std::lock_guard<std::mutex> lock(q.mutex);
        if (q.done.empty()) return;
        finished.swap(q.done);
    }
    for (auto& [key, image] : finished) cache()[key] = std::move(image);
}

bool thumbsPending() {
    Queue& q = queue();
    std::lock_guard<std::mutex> lock(q.mutex);
    return !q.pending.empty() || !q.done.empty();
}

void clearThumbCache() {
    Queue& q = queue();
    cache().clear();
    std::lock_guard<std::mutex> lock(q.mutex);
    q.pending.clear();
    q.done.clear();
    // Whatever the worker is rendering right now belongs to the deck that just went away.
    q.generation++;
}

void stopThumbs() {
    Queue& q = queue();
    if (!q.started) return;
    {
        std::lock_guard<std::mutex> lock(q.mutex);
        q.stopping = true;
    }
    q.wake.notify_all();
    if (q.thread.joinable()) q.thread.join();
    q.started = false;
}

}  // namespace refract
