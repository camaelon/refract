// The sync protocol's lines, read and written.
//
// Returns 0 on success, 1 on any failed assertion.

#include "Sync.h"

#include <cerrno>
#include <cstdio>
#include <memory>
#include <string>
#include <vector>

#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

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
    CHECK(refract::parseSyncLine("bye key", &m) && m.kind == "bye" && m.by == "key", "a goodbye, with the reason");
    CHECK(!refract::parseSyncLine("bye", &m), "a goodbye needs its reason");
    CHECK(refract::parseSyncLine("pong\r", &m) && m.kind == "pong", "pong, with a stray CR");
    CHECK(!refract::parseSyncLine("slide x 1", &m), "not a slide number");
    CHECK(!refract::parseSyncLine("slide 3", &m), "no sequence");
    CHECK(!refract::parseSyncLine("slide -1 4", &m), "no negative slide");
    CHECK(!refract::parseSyncLine("hello there", &m), "a client's line is not a server's");
    CHECK(!refract::parseSyncLine("", &m), "nothing");
}

static void testWrite() {
    CHECK(refract::syncHelloLine("desk") == "hello desk\n", "a hello");
    CHECK(refract::syncHelloLine("desk", "s3cret") == "hello desk s3cret\n", "a hello with the key");
    CHECK(refract::syncHelloLine("my desk", "a key!") == "hello my_desk a_key\n", "name and key are one token each");
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

// ── A live server, on a port of the system's choosing ──────────────

namespace {
struct Peer {
    int fd = -1;
    std::string buffer;
    explicit Peer(int port) {
        fd = ::socket(AF_INET, SOCK_STREAM, 0);
        sockaddr_in a{};
        a.sin_family = AF_INET;
        a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        a.sin_port = htons(static_cast<uint16_t>(port));
        if (::connect(fd, reinterpret_cast<sockaddr*>(&a), sizeof(a)) != 0) { ::close(fd); fd = -1; }
        timeval tv{2, 0};
        if (fd >= 0) ::setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    }
    ~Peer() { if (fd >= 0) ::close(fd); }
    void say(const std::string& line) { const std::string l = line + "\n"; ::send(fd, l.data(), l.size(), 0); }
    // The next line, or "" when the link closed or two seconds passed.
    std::string hear() {
        for (;;) {
            const size_t end = buffer.find('\n');
            if (end != std::string::npos) { std::string l = buffer.substr(0, end); buffer.erase(0, end + 1); return l; }
            char chunk[256];
            const ssize_t n = ::recv(fd, chunk, sizeof(chunk), 0);
            if (n <= 0) return "";
            buffer.append(chunk, static_cast<size_t>(n));
        }
    }
    bool closed() {     // true when the server hung up on us (within two seconds)
        char chunk[256];
        for (;;) {      // whatever it still said before hanging up
            const ssize_t n = ::recv(fd, chunk, sizeof(chunk), 0);
            if (n == 0) return true;
            // A reset counts too: a server that closes with our lines still unread sends one
            // instead of a clean end. Only the timeout means the link is still open.
            if (n < 0) return errno != EAGAIN && errno != EWOULDBLOCK;
        }
    }
};
}  // namespace

static void testServer() {
    refract::SyncServer server;
    CHECK(server.start(0, "127.0.0.1"), "listens on a port of the system's choosing, on loopback");
    const int port = server.port();
    CHECK(port > 0, "and says which");
    Peer a(port);
    a.say("hello A");
    CHECK(a.hear() == "peers 1", "the first player is told it is alone");
    Peer b(port);
    b.say("slide 3");
    b.say("hello B");
    CHECK(a.hear() == "peers 2" && b.hear() == "peers 2", "a move before hello does not count");
    a.say("slide 4");
    CHECK(a.hear() == "slide 4 1 A" && b.hear() == "slide 4 1 A", "a move reaches everyone");
    b.say("blank 1");
    CHECK(a.hear() == "blank 1 2 B", "so does a blanking");
    b.hear();
    a.say("laser 0.5 0.5");
    CHECK(b.hear() == "laser 0.5 0.5 A", "a laser is relayed to the others");
    Peer c(port);
    c.say("hello C");
    CHECK(c.hear() == "slide 4 1 A" && c.hear() == "blank 1 2 B", "a late joiner is sent slide and screen, each with its own sequence");
    Peer d(port);
    d.say(std::string(300, 'x'));
    CHECK(d.closed(), "a line over the limit ends the connection");
    Peer e(port);
    e.say("hello E");
    e.hear();
    // Twice the limit and a few: however the burst straddles a second boundary, one side is over.
    for (int i = 0; i < 2 * refract::kSyncMaxLaserPerSec + 5; i++) e.say("laser 0.1 0.1");
    CHECK(e.closed(), "a laser flood ends the connection");
    server.stop();
}

static void testServerKey() {
    refract::SyncServer server;
    CHECK(server.start(0, "127.0.0.1", "open-sesame"), "listens with a key");
    Peer wrong(server.port());
    wrong.say("hello W nope");
    CHECK(wrong.hear() == "bye key" && wrong.closed(), "the wrong key is told so, then the connection ends");
    Peer none(server.port());
    none.say("slide 2");
    CHECK(none.closed(), "so does anything before a hello");
    Peer right(server.port());
    right.say("hello R open-sesame");
    CHECK(right.hear() == "peers 1", "the right key is in");
    server.stop();
}

static void testServerCap() {
    refract::SyncServer server;
    CHECK(server.start(0, "127.0.0.1"), "listens");
    std::vector<std::unique_ptr<Peer>> room;
    for (size_t i = 0; i < refract::kSyncMaxClients; i++) {
        room.push_back(std::make_unique<Peer>(server.port()));
        room.back()->say("hello P" + std::to_string(i));
        room.back()->hear();
    }
    Peer extra(server.port());
    CHECK(extra.hear() == "bye full" && extra.closed(), "one player over the cap is told so and turned away");
    server.stop();
}

int main() {
    testServer();
    testServerKey();
    testServerCap();
    testParse();
    testWrite();
    testAddress();
    if (failures) { std::fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    std::printf("sync: all passed\n");
    return 0;
}
