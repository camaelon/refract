#include "WaveShape.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>

namespace refract {

namespace {

// A little-endian reader that never runs off the end: an out-of-range read is 0, and the
// chunk walk below checks lengths before it trusts anything.
struct Bytes {
    const std::vector<uint8_t>& b;
    unsigned u16(size_t o) const { return o + 2 <= b.size() ? b[o] | (b[o + 1] << 8) : 0u; }
    unsigned u32(size_t o) const { return o + 4 <= b.size() ? u16(o) | (u16(o + 2) << 16) : 0u; }
    bool tag(size_t o, const char* t) const { return o + 4 <= b.size() && std::memcmp(b.data() + o, t, 4) == 0; }
};

constexpr unsigned kPcm = 1, kFloat = 3, kExtensible = 0xFFFE;

}  // namespace

bool parseWaveShape(const std::vector<uint8_t>& bytes, size_t bins, WaveShape* shape) {
    if (!shape || bins == 0) return false;
    const Bytes in{bytes};
    if (!in.tag(0, "RIFF") || !in.tag(8, "WAVE")) return false;

    unsigned format = 0, channels = 0, rate = 0, bits = 0;
    size_t dataAt = 0, dataLen = 0;
    for (size_t o = 12; o + 8 <= bytes.size();) {
        const size_t len = in.u32(o + 4);
        if (in.tag(o, "fmt ")) {
            format = in.u16(o + 8); channels = in.u16(o + 10); rate = in.u32(o + 12); bits = in.u16(o + 22);
            if (format == kExtensible && len >= 26) format = in.u16(o + 8 + 24);   // the sub-format's low word
        } else if (in.tag(o, "data")) {
            dataAt = o + 8;
            dataLen = std::min(len, bytes.size() - dataAt);
            break;
        }
        o += 8 + len + (len & 1);          // chunks are word-aligned
    }
    if (!dataAt || !channels || !rate || !bits) return false;
    const bool known = (format == kPcm && (bits == 8 || bits == 16 || bits == 24 || bits == 32))
                    || (format == kFloat && bits == 32);
    if (!known) return false;
    const size_t frameBytes = channels * bits / 8;
    const size_t frames = dataLen / frameBytes;
    if (!frames) return false;

    WaveShape out;
    out.duration = static_cast<double>(frames) / rate;
    out.envelope.assign(bins, 0.0f);
    for (size_t i = 0; i < frames; i++) {
        float peak = 0.0f;
        for (unsigned c = 0; c < channels; c++) {
            const size_t o = dataAt + i * frameBytes + c * bits / 8;
            float v = 0.0f;
            if (format == kFloat) { float x; std::memcpy(&x, bytes.data() + o, 4); v = x; }
            else if (bits == 16) v = static_cast<int16_t>(in.u16(o)) / 32768.0f;
            else if (bits == 24) v = static_cast<int32_t>((in.u16(o) | (bytes[o + 2] << 16)) << 8) / 2147483648.0f;
            else if (bits == 32) v = static_cast<int32_t>(in.u32(o)) / 2147483648.0f;
            else v = (static_cast<int>(bytes[o]) - 128) / 128.0f;      // 8-bit wav is unsigned
            peak = std::max(peak, std::fabs(v));
        }
        float& bin = out.envelope[std::min(bins - 1, i * bins / frames)];
        bin = std::max(bin, peak);
    }
    *shape = std::move(out);
    return true;
}

bool readWaveShape(const std::string& path, size_t bins, WaveShape* shape) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return false;
    f.seekg(0, std::ios::end);
    const std::streamoff size = f.tellg();
    if (size <= 0) return false;
    std::vector<uint8_t> bytes(static_cast<size_t>(size));
    f.seekg(0);
    f.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    return parseWaveShape(bytes, bins, shape);
}

}  // namespace refract
