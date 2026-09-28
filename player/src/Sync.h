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
//                     blank <n>           the screen: 0 showing, 1 black, 2 white
//                     laser <x> <y>       this player's laser dot, as fractions of the slide
//                     laser off
//                     ping                every few seconds, so a dead link is noticed
//   server → client   slide <n> <seq> <by>   the slide showing; on joining, and on every change
//                     blank <n> <seq> <by>   the screen, the same way
//                     laser <x> <y> <by>     another player's dot, relayed as it moves
//                     laser off <by>
//                     peers <k>           how many players are connected
//                     pong
//
// The sequence number is the server's, so a stale message can be told from a fresh one.
// Either side of the wire can be this player: `refractplayer --sync-serve` runs the server
// in the player itself (SyncServer below), the same protocol tools/sync.py speaks.
#pragma once

#include <atomic>
#include <mutex>
#include <string>
#include <thread>
#include <memory>
#include <vector>

namespace refract {

// One line from the server, parsed. `kind` is "slide", "blank", "laser", "peers", "pong"
// or empty. For "slide" and "blank" the value is `value`; for "laser", `laserOn` and the
// fractions.
struct SyncMessage {
    std::string kind;
    int value = -1;
    long seq = -1;
    int peers = 0;
    bool laserOn = false;
    float laserX = 0.0f, laserY = 0.0f;
    std::string by;
};
bool parseSyncLine(const std::string& line, SyncMessage* out);

// The lines a player sends.
std::string syncHelloLine(const std::string& name);
std::string syncSlideLine(int slide);
std::string syncBlankLine(int blank);
std::string syncLaserLine(float x, float y);
std::string syncLaserOffLine();

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
    void announceBlank(int blank);
    // The laser, as fractions of the slide's width and height; a stream while it moves.
    void announceLaser(float x, float y);
    void announceLaserOff();

    // A slide (or blank state) another player chose, once. False when there is nothing new.
    bool takeRemote(int* slide);
    bool takeRemoteBlank(int* blank);
    // Another player's laser: the latest position, or off. False when nothing changed.
    bool takeRemoteLaser(bool* on, float* x, float* y);

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
    int mRemoteBlank = -1;       // a blank state to apply, or -1
    bool mLaserChanged = false, mLaserOn = false;
    float mLaserX = 0.0f, mLaserY = 0.0f;
    long mLastSlideSeq = -1, mLastBlankSeq = -1;   // per kind: the two travel on their own
};

// The sync point itself, in the player: the same server tools/sync.py is, so a talk needs
// no Python on the machine that hosts it. One thread, one select loop over the listening
// socket and every client; it keeps the slide and the blank state and relays the lasers.
class SyncServer {
public:
    SyncServer();
    ~SyncServer();
    bool start(int port);            // false when the port cannot be bound
    void stop();
    bool running() const { return mRunning; }

private:
    void run();
    struct Client;
    void handleLine(Client& from, const std::string& line);
    void broadcast(const std::string& line, const Client* except = nullptr);

    std::thread mThread;
    std::atomic<bool> mRunning{false};
    std::atomic<int> mListen{-1};
    int mSlide = -1, mBlank = -1;
    long mSeq = 0, mSlideSeq = 0, mBlankSeq = 0;   // one counter; each state remembers its own
    std::string mSlideBy, mBlankBy;
    std::vector<std::unique_ptr<Client>> mClients;
};

}  // namespace refract
