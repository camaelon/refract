#include "Sync.h"

#include <cctype>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <iostream>
#include <sstream>
#include <algorithm>

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
    if (kind == "slide" || kind == "blank") {
        if (!(in >> out->value >> out->seq)) return false;
        in >> out->by;
        if (out->value < 0 || out->seq < 0) return false;
        if (kind == "blank" && out->value > 2) return false;
    } else if (kind == "laser") {
        std::string first;
        if (!(in >> first)) return false;
        if (first == "off") {
            out->laserOn = false;
        } else {
            out->laserX = std::strtof(first.c_str(), nullptr);
            if (!(in >> out->laserY)) return false;
            out->laserOn = true;
        }
        in >> out->by;
    } else if (kind == "peers") {
        if (!(in >> out->peers) || out->peers < 0) return false;
    } else if (kind == "bye") {
        in >> out->by;
        if (out->by.empty()) return false;
    } else if (kind != "pong") {
        return false;
    }
    out->kind = kind;
    return true;
}

std::string syncHelloLine(const std::string& name, const std::string& key) {
    return "hello " + syncNameFrom(name) + (key.empty() ? std::string() : " " + syncNameFrom(key)) + "\n";
}
std::string syncSlideLine(int slide) { return "slide " + std::to_string(slide) + "\n"; }
std::string syncBlankLine(int blank) { return "blank " + std::to_string(blank) + "\n"; }
std::string syncLaserLine(float x, float y) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "laser %.4f %.4f\n", x, y);
    return buf;
}
std::string syncLaserOffLine() { return "laser off\n"; }

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

void Sync::start(const std::string& host, int port, const std::string& name, const std::string& key) {
    stop();
    mHost = host;
    mPort = port;
    mName = syncNameFrom(name);
    mKey = key.empty() ? std::string() : syncNameFrom(key);
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

void Sync::announceBlank(int blank) {
    if (!mConnected) return;
    sendLine(syncBlankLine(blank));
}

void Sync::announceLaser(float x, float y) {
    if (!mConnected) return;
    sendLine(syncLaserLine(x, y));
}

void Sync::announceLaserOff() {
    if (!mConnected) return;
    sendLine(syncLaserOffLine());
}

bool Sync::takeRemote(int* slide) {
    std::lock_guard<std::mutex> lock(mMutex);
    if (mRemote < 0) return false;
    *slide = mRemote;
    mRemote = -1;
    return true;
}

bool Sync::takeRemoteBlank(int* blank) {
    std::lock_guard<std::mutex> lock(mMutex);
    if (mRemoteBlank < 0) return false;
    *blank = mRemoteBlank;
    mRemoteBlank = -1;
    return true;
}

bool Sync::takeRemoteLaser(bool* on, float* x, float* y) {
    std::lock_guard<std::mutex> lock(mMutex);
    if (!mLaserChanged) return false;
    mLaserChanged = false;
    *on = mLaserOn;
    *x = mLaserX;
    *y = mLaserY;
    return true;
}

std::string Sync::refused() const {
    std::lock_guard<std::mutex> lock(mMutex);
    return mRefused;
}

std::string Sync::status() const {
    if (!refused().empty()) return "sync · refused";
    if (!mConnected) return "sync · connecting…";
    const int n = mPeers;
    return "sync · " + std::to_string(n) + (n == 1 ? " player" : " players");
}

void Sync::handleLine(const std::string& line) {
    SyncMessage m;
    if (!parseSyncLine(line, &m)) return;
    if (m.kind == "slide" || m.kind == "blank") {
        std::lock_guard<std::mutex> lock(mMutex);
        long& last = (m.kind == "slide") ? mLastSlideSeq : mLastBlankSeq;
        if (m.seq <= last) return;          // older than what we have seen
        last = m.seq;
        if (m.kind == "slide") mRemote = m.value; else mRemoteBlank = m.value;
    } else if (m.kind == "laser") {
        std::lock_guard<std::mutex> lock(mMutex);
        if (m.by == mName) return;          // our own dot, relayed back
        mLaserChanged = true;
        mLaserOn = m.laserOn;
        mLaserX = m.laserX;
        mLaserY = m.laserY;
    } else if (m.kind == "peers") {
        mPeers = m.peers;
    } else if (m.kind == "bye") {
        // Not wanted back: say why, once, and stop trying.
        std::lock_guard<std::mutex> lock(mMutex);
        mRefused = m.by;
        std::cerr << "sync: " << mHost << " refused this player: "
                  << (m.by == "key" ? "wrong --sync-key" : m.by == "full" ? "no room" : m.by) << "\n";
        mRunning = false;
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
        sendLine(syncHelloLine(mName, mKey));

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
                if (buffer.size() > kSyncMaxLine) break;    // not the protocol: drop the link
            }
            sincePing += 0.25;
            if (sincePing >= 5.0) { sincePing = 0.0; if (!sendLine("ping\n")) break; }
        }
        mConnected = false;
        const int had = mSocket.exchange(-1);
        if (had >= 0) ::close(had);
        if (mRunning) {
            // A moment before trying again, so a host that hangs up on us is not hammered.
            std::cerr << "sync: link to " << mHost << " lost, reconnecting\n";
            for (int i = 0; i < 20 && mRunning; i++) ::usleep(100000);
        }
    }
}

// ── Server ───────────────────────────────────────────────────────────

struct SyncServer::Client {
    int fd = -1;
    std::string name = "player";
    std::string buffer;
    bool admitted = false;        // said hello (with the key, when there is one)
    bool gone = false;
    // The laser rate: lines in the current second.
    time_t laserSecond = 0;
    int laserLines = 0;
};

// The comparison takes as long whatever the difference, so timing says nothing.
static bool sameKey(const std::string& a, const std::string& b) {
    unsigned diff = static_cast<unsigned>(a.size() ^ b.size());
    for (size_t i = 0; i < a.size() && i < b.size(); i++) diff |= static_cast<unsigned>(a[i] ^ b[i]);
    return diff == 0;
}

SyncServer::SyncServer() = default;
SyncServer::~SyncServer() { stop(); }

bool SyncServer::start(int port, const std::string& bind, const std::string& key) {
    stop();
    mKey = key.empty() ? std::string() : syncNameFrom(key);
    int listenFd = -1;
    bool bound = false;
    int one = 1;
    if (!bind.empty()) {
        // One address, as given: v4 or v6, whichever it names.
        addrinfo hints{};
        hints.ai_family = AF_UNSPEC;
        hints.ai_socktype = SOCK_STREAM;
        hints.ai_flags = AI_PASSIVE | AI_NUMERICHOST;
        addrinfo* res = nullptr;
        if (::getaddrinfo(bind.c_str(), std::to_string(port).c_str(), &hints, &res) != 0) return false;
        for (addrinfo* a = res; a && !bound; a = a->ai_next) {
            listenFd = ::socket(a->ai_family, a->ai_socktype, a->ai_protocol);
            if (listenFd < 0) continue;
            ::setsockopt(listenFd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
            bound = ::bind(listenFd, a->ai_addr, a->ai_addrlen) == 0;
            if (!bound) ::close(listenFd);
        }
        ::freeaddrinfo(res);
        if (!bound) return false;
    }
    const bool v6 = !bound && (listenFd = ::socket(AF_INET6, SOCK_STREAM, 0)) >= 0;
    if (v6) {
        ::setsockopt(listenFd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
        int off = 0;
        ::setsockopt(listenFd, IPPROTO_IPV6, IPV6_V6ONLY, &off, sizeof(off));   // v4 too
        sockaddr_in6 addr{};
        addr.sin6_family = AF_INET6;
        addr.sin6_addr = in6addr_any;
        addr.sin6_port = htons(static_cast<uint16_t>(port));
        bound = ::bind(listenFd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0;
    }
    if (!bound) {
        ::close(listenFd);
        listenFd = ::socket(AF_INET, SOCK_STREAM, 0);
        if (listenFd < 0) return false;
        ::setsockopt(listenFd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = htonl(INADDR_ANY);
        addr.sin_port = htons(static_cast<uint16_t>(port));
        bound = ::bind(listenFd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0;
    }
    if (!bound || ::listen(listenFd, 16) != 0) { ::close(listenFd); return false; }
    {
        sockaddr_storage got{};
        socklen_t len = sizeof(got);
        if (::getsockname(listenFd, reinterpret_cast<sockaddr*>(&got), &len) == 0) {
            mPort = ntohs(got.ss_family == AF_INET6 ? reinterpret_cast<sockaddr_in6*>(&got)->sin6_port
                                                    : reinterpret_cast<sockaddr_in*>(&got)->sin_port);
        } else {
            mPort = port;
        }
    }
    mListen = listenFd;
    mRunning = true;
    mThread = std::thread([this] { run(); });
    return true;
}

void SyncServer::stop() {
    mRunning = false;
    const int fd = mListen.exchange(-1);
    if (fd >= 0) { ::shutdown(fd, SHUT_RDWR); ::close(fd); }
    if (mThread.joinable()) mThread.join();
    for (auto& c : mClients) if (c->fd >= 0) ::close(c->fd);
    mClients.clear();
}

void SyncServer::broadcast(const std::string& line, const Client* except) {
    for (auto& c : mClients) {
        if (c.get() == except || c->fd < 0) continue;
        if (::send(c->fd, line.data(), line.size(), 0) != static_cast<ssize_t>(line.size())) c->gone = true;
    }
}

void SyncServer::handleLine(Client& from, const std::string& line) {
    std::istringstream in(line);
    std::string kind;
    if (!(in >> kind)) return;
    if (kind == "hello") {
        std::string name, key;
        in >> name >> key;
        if (!mKey.empty() && !sameKey(syncNameFrom(key), mKey)) {
            std::cerr << "sync: " << syncNameFrom(name) << " refused: wrong key\n";
            const std::string l = "bye key\n";
            ::send(from.fd, l.data(), l.size(), 0);
            from.gone = true;
            return;
        }
        from.name = syncNameFrom(name);
        from.admitted = true;
        if (mSlide >= 0) {
            const std::string l = "slide " + std::to_string(mSlide) + " " + std::to_string(mSlideSeq) + " " + mSlideBy + "\n";
            ::send(from.fd, l.data(), l.size(), 0);
        }
        if (mBlank >= 0) {
            const std::string l = "blank " + std::to_string(mBlank) + " " + std::to_string(mBlankSeq) + " " + mBlankBy + "\n";
            ::send(from.fd, l.data(), l.size(), 0);
        }
        broadcast("peers " + std::to_string(mClients.size()) + "\n");
        std::cerr << "sync: " << from.name << " joined\n";
    } else if (!from.admitted) {
        // Nothing counts before a hello; with a key, the connection is already over.
        if (!mKey.empty()) from.gone = true;
    } else if (kind == "slide" || kind == "blank") {
        int value = -1;
        if (!(in >> value) || value < 0 || (kind == "blank" && value > 2)) return;
        mSeq++;
        if (kind == "slide") { mSlide = value; mSlideBy = from.name; mSlideSeq = mSeq; }
        else { mBlank = value; mBlankBy = from.name; mBlankSeq = mSeq; }
        const std::string l = kind + " " + std::to_string(value) + " " + std::to_string(mSeq) + " " + from.name + "\n";
        broadcast(l);
        if (kind == "slide") std::cerr << "sync: slide " << value + 1 << " (" << from.name << ")\n";
    } else if (kind == "laser") {
        // Relayed to the others as it came, with who it is from; not kept. A flood ends it.
        const time_t now = ::time(nullptr);
        if (now != from.laserSecond) { from.laserSecond = now; from.laserLines = 0; }
        if (++from.laserLines > kSyncMaxLaserPerSec) {
            std::cerr << "sync: " << from.name << " dropped: laser flood\n";
            from.gone = true;
            return;
        }
        std::string rest;
        std::getline(in, rest);
        while (!rest.empty() && rest.back() == '\r') rest.pop_back();
        broadcast("laser" + rest + " " + from.name + "\n", &from);
    } else if (kind == "ping") {
        const std::string l = "pong\n";
        ::send(from.fd, l.data(), l.size(), 0);
    }
}

void SyncServer::run() {
    while (mRunning) {
        const int listenFd = mListen;
        if (listenFd < 0) break;
        fd_set set;
        FD_ZERO(&set);
        FD_SET(listenFd, &set);
        int maxFd = listenFd;
        for (auto& c : mClients) { FD_SET(c->fd, &set); maxFd = std::max(maxFd, c->fd); }
        timeval tv{0, 250000};
        const int ready = ::select(maxFd + 1, &set, nullptr, nullptr, &tv);
        if (ready < 0) { if (mRunning) continue; else break; }
        if (ready == 0) continue;
        if (FD_ISSET(listenFd, &set)) {
            const int fd = ::accept(listenFd, nullptr, nullptr);
            if (fd >= 0 && mClients.size() >= kSyncMaxClients) {
                std::cerr << "sync: a player turned away: " << kSyncMaxClients << " already here\n";
                const std::string l = "bye full\n";
                ::send(fd, l.data(), l.size(), 0);
                ::close(fd);
            } else if (fd >= 0) {
                int one = 1;
                ::setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
                auto c = std::make_unique<Client>();
                c->fd = fd;
                mClients.push_back(std::move(c));
            }
        }
        for (auto& c : mClients) {
            if (!FD_ISSET(c->fd, &set)) continue;
            char chunk[512];
            const ssize_t n = ::recv(c->fd, chunk, sizeof(chunk), 0);
            if (n <= 0) { c->gone = true; continue; }
            c->buffer.append(chunk, static_cast<size_t>(n));
            size_t end;
            while (!c->gone && (end = c->buffer.find('\n')) != std::string::npos) {
                const std::string line = c->buffer.substr(0, end);
                c->buffer.erase(0, end + 1);
                if (line.size() > kSyncMaxLine) { c->gone = true; break; }
                handleLine(*c, line);
            }
            if (c->buffer.size() > kSyncMaxLine) c->gone = true;    // no newline in sight
        }
        // The ones that hung up, and the count for those still here.
        bool left = false;
        for (size_t i = 0; i < mClients.size();) {
            if (mClients[i]->gone) {
                if (mClients[i]->admitted) std::cerr << "sync: " << mClients[i]->name << " left\n";
                ::close(mClients[i]->fd);
                mClients.erase(mClients.begin() + static_cast<long>(i));
                left = true;
            } else {
                i++;
            }
        }
        if (left) broadcast("peers " + std::to_string(mClients.size()) + "\n");
    }
}

}  // namespace refract
