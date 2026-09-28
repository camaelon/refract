#include "Sync.h"

#include <cctype>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <sstream>

#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>

namespace refract {

// ── Protocol ─────────────────────────────────────────────────────────

bool parseSyncLine(const std::string& line, SyncMessage* out) {
    *out = SyncMessage();
    std::istringstream in(line);
    std::string kind;
    if (!(in >> kind)) return false;
    if (kind == "slide") {
        if (!(in >> out->slide >> out->seq)) return false;
        in >> out->by;
        if (out->slide < 0 || out->seq < 0) return false;
    } else if (kind == "peers") {
        if (!(in >> out->peers) || out->peers < 0) return false;
    } else if (kind != "pong") {
        return false;
    }
    out->kind = kind;
    return true;
}

std::string syncHelloLine(const std::string& name) { return "hello " + syncNameFrom(name) + "\n"; }
std::string syncSlideLine(int slide) { return "slide " + std::to_string(slide) + "\n"; }

std::string syncNameFrom(const std::string& raw) {
    std::string out;
    for (unsigned char c : raw) {
        if (std::isalnum(c) || c == '-' || c == '_' || c == '.') out += static_cast<char>(c);
        else if (c == ' ') out += '_';
    }
    if (out.size() > 40) out.resize(40);
    return out.empty() ? "player" : out;
}

bool parseSyncAddress(const std::string& spec, std::string* host, int* port) {
    *host = "localhost";
    *port = 7333;
    const size_t colon = spec.rfind(':');
    std::string h = colon == std::string::npos ? spec : spec.substr(0, colon);
    if (!h.empty()) *host = h;
    if (colon != std::string::npos) {
        const std::string p = spec.substr(colon + 1);
        if (p.empty()) return false;
        for (unsigned char c : p) if (!std::isdigit(c)) return false;
        *port = std::atoi(p.c_str());
        if (*port <= 0 || *port > 65535) return false;
    }
    return true;
}

// ── Client ───────────────────────────────────────────────────────────

Sync::~Sync() { stop(); }

void Sync::start(const std::string& host, int port, const std::string& name) {
    stop();
    mHost = host;
    mPort = port;
    mName = syncNameFrom(name);
    mRunning = true;
    mThread = std::thread([this] { run(); });
}

void Sync::stop() {
    mRunning = false;
    const int fd = mSocket.exchange(-1);
    if (fd >= 0) { ::shutdown(fd, SHUT_RDWR); ::close(fd); }
    if (mThread.joinable()) mThread.join();
    mConnected = false;
}

bool Sync::sendLine(const std::string& line) {
    const int fd = mSocket;
    if (fd < 0) return false;
    std::lock_guard<std::mutex> lock(mMutex);
    return ::send(fd, line.data(), line.size(), 0) == static_cast<ssize_t>(line.size());
}

void Sync::announce(int slide) {
    if (!mConnected) return;
    sendLine(syncSlideLine(slide));
}

bool Sync::takeRemote(int* slide) {
    std::lock_guard<std::mutex> lock(mMutex);
    if (mRemote < 0) return false;
    *slide = mRemote;
    mRemote = -1;
    return true;
}

std::string Sync::status() const {
    if (!mConnected) return "sync · connecting…";
    const int n = mPeers;
    return "sync · " + std::to_string(n) + (n == 1 ? " player" : " players");
}

void Sync::handleLine(const std::string& line) {
    SyncMessage m;
    if (!parseSyncLine(line, &m)) return;
    if (m.kind == "slide") {
        std::lock_guard<std::mutex> lock(mMutex);
        if (m.seq <= mLastSeq) return;      // older than what we have seen
        mLastSeq = m.seq;
        mRemote = m.slide;
    } else if (m.kind == "peers") {
        mPeers = m.peers;
    }
}

void Sync::run() {
    bool said = false;
    while (mRunning) {
        // Resolve and connect. A failure is retried every couple of seconds, quietly after
        // the first time: the server may simply not be up yet.
        addrinfo hints{};
        hints.ai_family = AF_UNSPEC;
        hints.ai_socktype = SOCK_STREAM;
        addrinfo* res = nullptr;
        int fd = -1;
        if (::getaddrinfo(mHost.c_str(), std::to_string(mPort).c_str(), &hints, &res) == 0) {
            for (addrinfo* a = res; a && fd < 0; a = a->ai_next) {
                const int s = ::socket(a->ai_family, a->ai_socktype, a->ai_protocol);
                if (s < 0) continue;
                if (::connect(s, a->ai_addr, a->ai_addrlen) == 0) fd = s; else ::close(s);
            }
            ::freeaddrinfo(res);
        }
        if (fd < 0) {
            if (!said) { std::cerr << "sync: waiting for " << mHost << ":" << mPort << "\n"; said = true; }
            for (int i = 0; i < 20 && mRunning; i++) ::usleep(100000);
            continue;
        }
        int one = 1;
        ::setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
        mSocket = fd;
        mConnected = true;
        said = false;
        std::cerr << "sync: connected to " << mHost << ":" << mPort << " as " << mName << "\n";
        sendLine(syncHelloLine(mName));

        std::string buffer;
        double sincePing = 0.0;
        while (mRunning && mSocket >= 0) {
            fd_set set;
            FD_ZERO(&set);
            FD_SET(fd, &set);
            timeval tv{0, 250000};
            const int ready = ::select(fd + 1, &set, nullptr, nullptr, &tv);
            if (ready < 0) break;
            if (ready > 0) {
                char chunk[512];
                const ssize_t n = ::recv(fd, chunk, sizeof(chunk), 0);
                if (n <= 0) break;                 // closed, or gone
                buffer.append(chunk, static_cast<size_t>(n));
                size_t end;
                while ((end = buffer.find('\n')) != std::string::npos) {
                    handleLine(buffer.substr(0, end));
                    buffer.erase(0, end + 1);
                }
            }
            sincePing += 0.25;
            if (sincePing >= 5.0) { sincePing = 0.0; if (!sendLine("ping\n")) break; }
        }
        mConnected = false;
        const int had = mSocket.exchange(-1);
        if (had >= 0) ::close(had);
        if (mRunning) std::cerr << "sync: link to " << mHost << " lost, reconnecting\n";
    }
}

}  // namespace refract
