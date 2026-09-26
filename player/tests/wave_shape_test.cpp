// The presenter's waveform.
//
// A wav is built in memory the way a recorder would write it — RIFF, a fmt chunk, a data
// chunk — in each sample layout the parser claims to read, and the shape that comes out is
// checked for its length and where the loud part is. The malformed cases matter as much:
// a file that is not a wav, or is cut short, must come back as "no shape", never a crash.
//
// Returns 0 on success, 1 on any failed assertion.

#include "WaveShape.h"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

namespace {

void put16(std::vector<uint8_t>& b, unsigned v) { b.push_back(v & 0xFF); b.push_back((v >> 8) & 0xFF); }
void put32(std::vector<uint8_t>& b, unsigned v) { put16(b, v & 0xFFFF); put16(b, (v >> 16) & 0xFFFF); }
void tag(std::vector<uint8_t>& b, const char* t) { b.insert(b.end(), t, t + 4); }

// A wav of `data`, in the given format. `extensible` wraps the format the way WAVE_FORMAT_
// EXTENSIBLE does (the real format in the sub-format GUID's low word). `junkBefore` puts
// an odd-length chunk before the data, which the walk must step over word-aligned.
std::vector<uint8_t> wav(unsigned format, unsigned channels, unsigned rate, unsigned bits,
                         const std::vector<uint8_t>& data, bool extensible = false,
                         bool junkBefore = false) {
    std::vector<uint8_t> b;
    tag(b, "RIFF"); put32(b, 0); tag(b, "WAVE");
    tag(b, "fmt ");
    put32(b, extensible ? 40 : 16);
    put16(b, extensible ? 0xFFFE : format);
    put16(b, channels); put32(b, rate);
    put32(b, rate * channels * bits / 8); put16(b, channels * bits / 8); put16(b, bits);
    if (extensible) {
        put16(b, 22); put16(b, bits); put32(b, 0);
        put16(b, format);                         // the GUID's first word is the real format
        for (int i = 0; i < 14; i++) b.push_back(0);
    }
    if (junkBefore) {
        tag(b, "LIST"); put32(b, 3); b.push_back(1); b.push_back(2); b.push_back(3); b.push_back(0);
    }
    tag(b, "data"); put32(b, static_cast<unsigned>(data.size()));
    b.insert(b.end(), data.begin(), data.end());
    const unsigned riffLen = static_cast<unsigned>(b.size() - 8);
    b[4] = riffLen & 0xFF; b[5] = (riffLen >> 8) & 0xFF; b[6] = (riffLen >> 16) & 0xFF; b[7] = (riffLen >> 24) & 0xFF;
    return b;
}

// 16-bit mono: `frames` samples, silent but for a full-scale burst in the last quarter.
std::vector<uint8_t> burst16(unsigned frames, unsigned channels = 1) {
    std::vector<uint8_t> d;
    for (unsigned i = 0; i < frames; i++)
        for (unsigned c = 0; c < channels; c++)
            put16(d, i >= frames * 3 / 4 ? (c == 0 ? 0x7FFF : 0x4000) : 0);
    return d;
}

bool near(double a, double b, double eps = 1e-6) { return std::fabs(a - b) < eps; }

}  // namespace

static void testSixteenBit() {
    refract::WaveShape shape;
    CHECK(refract::parseWaveShape(wav(1, 1, 8000, 16, burst16(16000)), 8, &shape), "16-bit mono parses");
    CHECK(near(shape.duration, 2.0), "two seconds of 8 kHz");
    CHECK(shape.envelope.size() == 8, "asked for eight bins");
    CHECK(near(shape.envelope[0], 0.0f) && near(shape.envelope[5], 0.0f), "the quiet part is quiet");
    CHECK(near(shape.envelope[6], 32767 / 32768.0f) && near(shape.envelope[7], 32767 / 32768.0f),
          "the burst fills the last quarter's bins");
}

static void testStereoTakesThePeakChannel() {
    refract::WaveShape shape;
    CHECK(refract::parseWaveShape(wav(1, 2, 8000, 16, burst16(8000, 2)), 4, &shape), "stereo parses");
    CHECK(near(shape.duration, 1.0), "frames, not samples, make the duration");
    CHECK(near(shape.envelope[3], 32767 / 32768.0f), "the louder channel is the peak");
}

static void testOtherDepths() {
    // 8-bit is unsigned: 128 is silence, 255 nearly full scale.
    std::vector<uint8_t> d8(100, 128);
    d8[99] = 255;
    refract::WaveShape shape;
    CHECK(refract::parseWaveShape(wav(1, 1, 100, 8, d8), 2, &shape), "8-bit parses");
    CHECK(near(shape.envelope[0], 0.0f) && near(shape.envelope[1], 127 / 128.0f), "8-bit centred on 128");

    // 24-bit: a full-scale negative sample in the last frame, three bytes, no fourth to read.
    std::vector<uint8_t> d24(99 * 3, 0);
    d24.push_back(0x00); d24.push_back(0x00); d24.push_back(0x80);
    CHECK(refract::parseWaveShape(wav(1, 1, 100, 24, d24), 2, &shape), "24-bit parses");
    CHECK(near(shape.envelope[1], 1.0f), "24-bit full scale, read from three bytes at the very end");

    // 32-bit integer.
    std::vector<uint8_t> d32;
    for (int i = 0; i < 100; i++) put32(d32, i == 50 ? 0x40000000u : 0u);
    CHECK(refract::parseWaveShape(wav(1, 1, 100, 32, d32), 2, &shape), "32-bit parses");
    CHECK(near(shape.envelope[1], 0.5f) && near(shape.envelope[0], 0.0f), "32-bit half scale");

    // 32-bit float, in an extensible header.
    std::vector<uint8_t> df;
    for (int i = 0; i < 100; i++) {
        const float v = i == 10 ? -0.25f : 0.0f;
        uint8_t raw[4]; std::memcpy(raw, &v, 4);
        df.insert(df.end(), raw, raw + 4);
    }
    CHECK(refract::parseWaveShape(wav(3, 1, 100, 32, df, true), 2, &shape), "float in an extensible header parses");
    CHECK(near(shape.envelope[0], 0.25f) && near(shape.envelope[1], 0.0f), "float samples read as floats");
}

static void testChunkWalk() {
    refract::WaveShape shape;
    CHECK(refract::parseWaveShape(wav(1, 1, 8000, 16, burst16(8000), false, true), 4, &shape),
          "an odd-length chunk before the data is stepped over");
    CHECK(near(shape.duration, 1.0), "and the data after it is read whole");
}

static void testRejects() {
    refract::WaveShape shape;
    shape.duration = 7.0;
    std::vector<uint8_t> notWav = {'R', 'I', 'F', 'X', 0, 0, 0, 0, 'W', 'A', 'V', 'E'};
    CHECK(!refract::parseWaveShape(notWav, 4, &shape), "not RIFF");
    CHECK(!refract::parseWaveShape({}, 4, &shape), "empty");
    std::vector<uint8_t> headerOnly = wav(1, 1, 8000, 16, {});
    CHECK(!refract::parseWaveShape(headerOnly, 4, &shape), "no samples is no shape");
    std::vector<uint8_t> cut = wav(1, 1, 8000, 16, burst16(8000));
    cut.resize(30);
    CHECK(!refract::parseWaveShape(cut, 4, &shape), "cut inside the fmt chunk");
    CHECK(!refract::parseWaveShape(wav(1, 1, 8000, 12, burst16(10)), 4, &shape), "a depth it does not read");
    CHECK(!refract::parseWaveShape(wav(85, 1, 8000, 16, burst16(10)), 4, &shape), "a compressed format");
    CHECK(near(shape.duration, 7.0), "a rejected file leaves the shape alone");

    // Cut inside the data: what is there is read, and the duration is what is there.
    std::vector<uint8_t> partial = wav(1, 1, 8000, 16, burst16(8000));
    partial.resize(partial.size() - 8000);
    CHECK(refract::parseWaveShape(partial, 4, &shape), "a truncated data chunk still reads");
    CHECK(near(shape.duration, 0.5), "as long as the samples that are there");
    CHECK(!refract::parseWaveShape(wav(1, 1, 8000, 16, burst16(10)), 0, &shape), "zero bins is a caller error");
}

static void testReadFile() {
    const std::string path = "wave_shape_test.tmp.wav";
    const std::vector<uint8_t> bytes = wav(1, 1, 8000, 16, burst16(4000));
    if (FILE* f = std::fopen(path.c_str(), "wb")) { std::fwrite(bytes.data(), 1, bytes.size(), f); std::fclose(f); }
    refract::WaveShape shape;
    CHECK(refract::readWaveShape(path, 4, &shape), "a wav on disk reads");
    CHECK(near(shape.duration, 0.5), "with its length");
    std::remove(path.c_str());
    CHECK(!refract::readWaveShape(path, 4, &shape), "a missing file is no shape");
}

int main() {
    testSixteenBit();
    testStereoTakesThePeakChannel();
    testOtherDepths();
    testChunkWalk();
    testRejects();
    testReadFile();
    if (failures) { std::fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    std::printf("wave_shape: all passed\n");
    return 0;
}
