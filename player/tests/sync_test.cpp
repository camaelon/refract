// The sync protocol's lines, read and written.
//
// Returns 0 on success, 1 on any failed assertion.

#include "Sync.h"

#include <cstdio>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static void testParse() {
    refract::SyncMessage m;
    CHECK(refract::parseSyncLine("slide 12 7 laptop", &m) && m.kind == "slide" && m.value == 12 && m.seq == 7 && m.by == "laptop",
          "a slide line: slide, sequence, who");
    CHECK(refract::parseSyncLine("slide 0 1", &m) && m.value == 0 && m.by.empty(), "the name is optional");
    CHECK(refract::parseSyncLine("blank 2 9 desk", &m) && m.kind == "blank" && m.value == 2 && m.seq == 9, "a blank line");
    CHECK(!refract::parseSyncLine("blank 3 9 desk", &m), "blank is 0, 1 or 2");
    CHECK(refract::parseSyncLine("laser 0.25 0.5 desk", &m) && m.kind == "laser" && m.laserOn
          && m.laserX == 0.25f && m.laserY == 0.5f && m.by == "desk", "a laser position, as fractions");
    CHECK(refract::parseSyncLine("laser off desk", &m) && m.kind == "laser" && !m.laserOn && m.by == "desk", "a laser gone");
    CHECK(!refract::parseSyncLine("laser 0.5", &m), "a laser needs both fractions");
    CHECK(refract::parseSyncLine("peers 2", &m) && m.kind == "peers" && m.peers == 2, "a peer count");
    CHECK(refract::parseSyncLine("pong\r", &m) && m.kind == "pong", "pong, with a stray CR");
    CHECK(!refract::parseSyncLine("slide x 1", &m), "not a slide number");
    CHECK(!refract::parseSyncLine("slide 3", &m), "no sequence");
    CHECK(!refract::parseSyncLine("slide -1 4", &m), "no negative slide");
    CHECK(!refract::parseSyncLine("hello there", &m), "a client's line is not a server's");
    CHECK(!refract::parseSyncLine("", &m), "nothing");
}

static void testWrite() {
    CHECK(refract::syncSlideLine(4) == "slide 4\n", "a move");
    CHECK(refract::syncBlankLine(1) == "blank 1\n", "a blank");
    CHECK(refract::syncLaserLine(0.5f, 0.25f) == "laser 0.5000 0.2500\n", "a laser position, four places");
    CHECK(refract::syncLaserOffLine() == "laser off\n", "a laser gone");
    CHECK(refract::syncHelloLine("Nico's MacBook Pro") == "hello Nicos_MacBook_Pro\n", "a hello, name made line-safe");
    CHECK(refract::syncNameFrom("") == "player", "no name is player");
    CHECK(refract::syncNameFrom(std::string(60, 'a')).size() == 40, "a name is kept short");
}

static void testAddress() {
    std::string host; int port = 0;
    CHECK(refract::parseSyncAddress("10.0.0.5", &host, &port) && host == "10.0.0.5" && port == 7333, "a host, default port");
    CHECK(refract::parseSyncAddress("mac.local:8000", &host, &port) && host == "mac.local" && port == 8000, "host and port");
    CHECK(refract::parseSyncAddress(":9000", &host, &port) && host == "localhost" && port == 9000, "a port alone means here");
    CHECK(refract::parseSyncAddress("", &host, &port) && host == "localhost" && port == 7333, "nothing means here, default port");
    CHECK(!refract::parseSyncAddress("mac:", &host, &port), "an empty port");
    CHECK(!refract::parseSyncAddress("mac:port", &host, &port), "not a port");
    CHECK(!refract::parseSyncAddress("mac:70000", &host, &port), "out of range");
}

int main() {
    testParse();
    testWrite();
    testAddress();
    if (failures) { std::fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    std::printf("sync: all passed\n");
    return 0;
}
