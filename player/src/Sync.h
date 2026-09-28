// Keeping two players on the same slide.
//
// One small server (tools/sync.py) holds one fact — which slide is showing — and every
// player connected to it both follows that fact and may change it. So a talk can be
// presented from machine A while machine B advances or jumps, or the reverse; whoever
// moved last is where everybody is.
//
// The protocol is lines of text over one TCP connection, so it can be watched with `nc`
// and written by anything:
//
//   client → server   hello <name>        who is here
//                     slide <n>           this player moved to slide n (0-based)
//                     ping                every few seconds, so a dead link is noticed
//   server → client   slide <n> <seq> <by>   the slide showing; on joining, and on every change
//                     peers <k>           how many players are connected
//                     pong
//
// The sequence number is the server's, so a stale message can be told from a fresh one.
#pragma once

#include <atomic>
#include <mutex>
#include <string>
#include <thread>

namespace refract {

// One line from the server, parsed. `kind` is "slide", "peers", "pong" or empty.
struct SyncMessage {
    std::string kind;
    int slide = -1;
    long seq = -1;
    int peers = 0;
    std::string by;
};
bool parseSyncLine(const std::string& line, SyncMessage* out);

// The lines a player sends.
std::string syncHelloLine(const std::string& name);
std::string syncSlideLine(int slide);

// A name for this player, from the machine, with anything a line cannot carry removed.
std::string syncNameFrom(const std::string& raw);

// "host", "host:port" or ":port" → the two parts; the port defaults to 7333.
bool parseSyncAddress(const std::string& spec, std::string* host, int* port);

class Sync {
public:
    ~Sync();

    // Connect to the server (in the background, retrying for as long as the player runs)
    // and announce this player as `name`.
    void start(const std::string& host, int port, const std::string& name);
    void stop();

    // This player moved to `slide`. Sent when connected; a move while disconnected is not
    // replayed, since by the time the link is back the server's slide is the truer one.
    void announce(int slide);

    // A slide another player chose, once. False when there is nothing new.
    bool takeRemote(int* slide);

    bool connected() const { return mConnected; }
    int peers() const { return mPeers; }
    // One line for a status bar: "sync · 2 players" or "sync · connecting…".
    std::string status() const;

private:
    void run();
    void handleLine(const std::string& line);
    bool sendLine(const std::string& line);

    std::thread mThread;
    std::atomic<bool> mRunning{false};
    std::atomic<bool> mConnected{false};
    std::atomic<int> mPeers{0};
    std::atomic<int> mSocket{-1};
    std::string mHost, mName;
    int mPort = 0;
    mutable std::mutex mMutex;
    int mRemote = -1;            // a slide to apply, or -1
    long mLastSeq = -1;
};

}  // namespace refract
