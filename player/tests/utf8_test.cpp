// Making arbitrary bytes safe to draw.
//
// This exists because of a crash: the include menu's preview cut a line of an asset at sixty
// *bytes*, which fell inside a multi-byte character, and Skia — asked to measure a run it
// cannot count the code points of — sized a glyph buffer from -1 and called abort(). The
// player died mid-edit. Half a character is the case to get right here; everything else is
// the neighbourhood around it.
//
// Returns 0 on success, 1 on any failed assertion.

#include "Utf8.h"

#include <cstdio>
#include <string>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

// "héllo wörld" and an emoji, as the bytes a file actually holds.
static const std::string kTwoByte  = "h\xC3\xA9llo";          // é
static const std::string kThreeByte = "\xE2\x86\x92 next";    // →
static const std::string kFourByte = "\xF0\x9F\x91\x8B hi";   // 👋

static void testPlainText() {
    CHECK(refract::validUtf8(""), "empty is valid");
    CHECK(refract::validUtf8("just ascii 123 !@#"), "ascii is valid");
    CHECK(refract::displayable("just ascii") == "just ascii", "and passes through unchanged");
}

static void testWholeSequences() {
    for (const std::string& text : {kTwoByte, kThreeByte, kFourByte}) {
        CHECK(refract::validUtf8(text), "a whole multi-byte character is valid");
        CHECK(refract::displayable(text) == text, "and is left alone");
    }
}

static void testACharacterCutInHalf() {
    // The crash. Every truncation of a multi-byte character, from one byte short to one
    // byte of it, has to be caught — that is what a byte-counting substr() produces.
    for (const std::string& text : {kTwoByte, kThreeByte, kFourByte}) {
        for (size_t cut = 1; cut < text.size(); cut++) {
            const std::string half = text.substr(0, cut);
            const bool wholeSoFar = refract::validUtf8(half);
            const std::string safe = refract::displayable(half);
            CHECK(refract::validUtf8(safe), "what comes back is always valid");
            if (!wholeSoFar) {
                CHECK(safe.find('?') != std::string::npos, "a cut character becomes a ?");
            }
        }
    }
}

static void testStrayBytes() {
    CHECK(!refract::validUtf8("a\x80z"), "a lone continuation byte is not valid");
    CHECK(refract::displayable("a\x80z") == "a?z", "and is replaced");
    CHECK(!refract::validUtf8("a\xFFz"), "0xFF is never a lead byte");
    CHECK(refract::displayable("a\xFF\xFEz") == "a??z", "each bad byte becomes one ?");
    // Latin-1 text read as UTF-8: every accented letter is a stray byte.
    CHECK(refract::displayable("caf\xE9") == "caf?", "latin-1 is made drawable");
}

static void testABrokenLeadWithGoodTextAfterIt() {
    // The repair has to resynchronise rather than give up: the rest of the line is fine.
    const std::string text = "\xE2\x86 then " + kTwoByte;
    const std::string safe = refract::displayable(text);
    CHECK(refract::validUtf8(safe), "the result is valid");
    CHECK(safe.find("then") != std::string::npos, "and keeps what followed the bad bytes");
    CHECK(safe.find("llo") != std::string::npos, "including a good character further along");
}

static void testBoundaries() {
    // Cutting "h é l l o" — byte 1 starts é, byte 2 is inside it.
    CHECK(refract::utf8Boundary(kTwoByte, 1) == 1, "a lead byte is already a boundary");
    CHECK(refract::utf8Boundary(kTwoByte, 2) == 1, "inside a character, back off to its lead");
    CHECK(refract::utf8Boundary(kTwoByte, 3) == 3, "the byte after it is a boundary again");
    CHECK(refract::utf8Boundary(kTwoByte, 0) == 0, "the start is a boundary");

    // A four-byte emoji: bytes 1, 2 and 3 are all inside it.
    for (size_t at = 1; at <= 3; at++) {
        CHECK(refract::utf8Boundary(kFourByte, at) == 0, "every byte of it backs off to 0");
    }
    CHECK(refract::utf8Boundary(kFourByte, 4) == 4, "and the space after it is a boundary");

    CHECK(refract::utf8Boundary("abc", 99) == 3, "past the end is the end");
    CHECK(refract::utf8Boundary("", 0) == 0, "an empty string has one boundary");
}

static void testCuttingAtABoundaryIsAlwaysSafe() {
    // The property the preview depends on: cut anywhere via utf8Boundary and what is left
    // is drawable without repair.
    const std::string mixed = kTwoByte + " " + kThreeByte + " " + kFourByte;
    for (size_t at = 0; at <= mixed.size(); at++) {
        const std::string head = mixed.substr(0, refract::utf8Boundary(mixed, at));
        CHECK(refract::validUtf8(head), "a cut at a boundary leaves valid text");
    }
}

// The crash itself. `ellipsize` trims a string until it fits, and used to do it by popping
// single bytes and stopping at the first non-continuation byte — which leaves the *lead* byte
// of a multi-byte character behind. One em-dash in a line long enough to need trimming was
// enough to abort the process.
static void testDroppingAWholeCharacter() {
    CHECK(refract::dropLastChar("abc") == "ab", "an ascii character comes off");
    CHECK(refract::dropLastChar("") == "", "and nothing comes off nothing");

    for (const std::string& text : {kTwoByte, kThreeByte, kFourByte}) {
        // Trim the whole string away one character at a time. Every intermediate state has
        // to be valid: each one is measured, and one bad state is an abort().
        std::string s = text;
        int steps = 0;
        while (!s.empty()) {
            s = refract::dropLastChar(s);
            CHECK(refract::validUtf8(s), "every trimmed state is valid UTF-8");
            CHECK(++steps < 64, "trimming terminates");
        }
    }
}

static void testDroppingTakesExactlyOneCharacter() {
    // "h" + é: dropping once leaves "h", not "h" plus a dangling lead byte.
    CHECK(refract::dropLastChar("h\xC3\xA9") == "h", "a two-byte character goes whole");
    CHECK(refract::dropLastChar("\xE2\x86\x92") == "", "so does a three-byte one");
    CHECK(refract::dropLastChar("\xF0\x9F\x91\x8B") == "", "and a four-byte one");
    // The state the old code produced: a lead byte with its continuations gone.
    CHECK(!refract::validUtf8("h\xC3"), "a dangling lead byte is exactly what was invalid");
}

// The line the preview cuts at sixty bytes, then hands to ellipsize. The em-dash in a JSON
// contentDescription is the one that found this.
static void testATrimmedLineStaysDrawable() {
    const std::string line = "    \"contentDescription\": \"Friendly Aliens \xE2\x80\x94 a card\"";
    for (size_t cut = 0; cut <= line.size(); cut++) {
        const std::string head = line.substr(0, refract::utf8Boundary(line, cut));
        CHECK(refract::validUtf8(head), "cut at a boundary, the line is valid");
        std::string s = head;
        while (!s.empty()) {
            s = refract::dropLastChar(s);
            CHECK(refract::validUtf8(s), "and stays valid however far it is trimmed");
        }
    }
}

int main() {
    testPlainText();
    testWholeSequences();
    testACharacterCutInHalf();
    testStrayBytes();
    testABrokenLeadWithGoodTextAfterIt();
    testBoundaries();
    testCuttingAtABoundaryIsAlwaysSafe();
    testDroppingAWholeCharacter();
    testDroppingTakesExactlyOneCharacter();
    testATrimmedLineStaysDrawable();
    if (failures == 0) std::printf("utf8: ok\n");
    return failures == 0 ? 0 : 1;
}
