#!/usr/bin/env python3
"""The sync point for players on different machines: which slide is showing.

    python3 player/tools/sync.py [--port 7333] [--host 0.0.0.0]

Every refractplayer started with `--sync <this machine>` connects here, follows the slide
the server holds, and may change it — so a talk can be presented from one machine while
another advances or jumps, and whoever moved last is where everybody is.

Lines of text over TCP, so it can be watched with `nc host 7333`:

    client -> server   hello <name>          who is here
                       slide <n>             this player moved to slide n (0-based)
                       ping
    server -> client   slide <n> <seq> <by>  the slide showing: on joining, and on every change
                       peers <k>             how many players are connected
                       pong

The sequence number is the server's, so a stale line can be told from a fresh one. The
server keeps nothing but the current slide; a player joining late is sent it and is there.
"""

import argparse
import socketserver
import sys
import threading


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.slide = -1
        self.seq = 0
        self.by = ""
        self.clients: set["Handler"] = set()

    def broadcast(self, line: str, log: bool = True) -> None:
        if log:
            print(line.rstrip(), file=sys.stderr, flush=True)
        for c in list(self.clients):
            c.send(line)


STATE = State()


class Handler(socketserver.StreamRequestHandler):
    name = "?"

    def send(self, line: str) -> None:
        try:
            self.wfile.write(line.encode("utf-8"))
            self.wfile.flush()
        except OSError:
            pass

    def handle(self) -> None:
        with STATE.lock:
            STATE.clients.add(self)
        try:
            for raw in self.rfile:
                line = raw.decode("utf-8", "replace").strip()
                parts = line.split()
                if not parts:
                    continue
                if parts[0] == "hello":
                    self.name = parts[1] if len(parts) > 1 else "player"
                    with STATE.lock:
                        if STATE.slide >= 0:
                            self.send(f"slide {STATE.slide} {STATE.seq} {STATE.by}\n")
                        STATE.broadcast(f"peers {len(STATE.clients)}\n", log=False)
                    print(f"{self.name} joined from {self.client_address[0]}", file=sys.stderr, flush=True)
                elif parts[0] == "slide" and len(parts) > 1 and parts[1].isdigit():
                    with STATE.lock:
                        STATE.seq += 1
                        STATE.slide = int(parts[1])
                        STATE.by = self.name
                        STATE.broadcast(f"slide {STATE.slide} {STATE.seq} {STATE.by}\n")
                elif parts[0] == "ping":
                    self.send("pong\n")
        finally:
            with STATE.lock:
                STATE.clients.discard(self)
                STATE.broadcast(f"peers {len(STATE.clients)}\n", log=False)
            print(f"{self.name} left", file=sys.stderr, flush=True)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(host: str, port: int) -> Server:
    """A server bound and ready; call serve_forever() (or run it on a thread)."""
    return Server((host, port), Handler)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--port", type=int, default=7333)
    ap.add_argument("--host", default="0.0.0.0", help="the address to listen on (default: all)")
    args = ap.parse_args()
    server = serve(args.host, args.port)
    print(f"sync: listening on {args.host}:{args.port} — start players with "
          f"--sync <this machine>:{args.port}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
