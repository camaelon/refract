// The shape of a recording, for drawing.
//
// The presenter shows each slide's narration as a strip: peak amplitude per bin, with a
// playhead running along it. This reads that shape out of a wav — the 16-bit PCM the
// recorder writes, and the 8/24/32-bit and float layouts a wav made elsewhere may have —
// without any audio library: a RIFF walk and a peak pass is all it takes.
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace refract {

struct WaveShape {
    std::vector<float> envelope;   // peak |sample| per bin, 0..1, left to right
    double duration = 0.0;         // seconds
};

// Fold the wav in `bytes` into `bins` peaks. False (and `shape` untouched) when it is not
// a wav this understands or holds no samples.
bool parseWaveShape(const std::vector<uint8_t>& bytes, size_t bins, WaveShape* shape);

// The same from a file. False when it cannot be read or parsed.
bool readWaveShape(const std::string& path, size_t bins, WaveShape* shape);

}  // namespace refract
