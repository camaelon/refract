"""The sync server: two players, one slide."""
import importlib.util
import os
import socket
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location("sync", os.path.join(HERE, "..", "player", "tools", "sync.py"))
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class Client:
    def __init__(self, port: int, name: str, key: str = "", hello: bool = True):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.file = self.sock.makefile("rw", encoding="utf-8", newline="\n")
        if hello:
            self.say(f"hello {name} {key}".rstrip())

    def say(self, line: str) -> None:
        try:
            self.file.write(line + "\n")
            self.file.flush()
        except OSError:
            pass                    # the server hung up on us: closed() will say so

    def hear(self) -> str:
        return self.file.readline().strip()

    def closed(self) -> bool:
        """True when the server hung up on us (within the socket's timeout)."""
        try:
            while self.file.readline() != "":
                pass                # whatever it still said before hanging up
            return True
        except OSError:
            return True

    def close(self) -> None:
        self.sock.close()


class Fixture(unittest.TestCase):
    KEY = ""

    def setUp(self):
        sync.STATE.__init__()
        self.server = sync.serve("127.0.0.1", 0, self.KEY)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()


class SyncServer(Fixture):
    def test_a_move_reaches_everyone_and_a_late_joiner(self):
        a = Client(self.port, "A")
        self.assertEqual(a.hear(), "peers 1", "a joiner is told who is here")
        b = Client(self.port, "B")
        self.assertEqual(b.hear(), "peers 2")
        self.assertEqual(a.hear(), "peers 2", "and so is everyone already here")
        a.say("slide 4")
        self.assertEqual(a.hear(), "slide 4 1 A", "the mover hears it back, with the sequence")
        self.assertEqual(b.hear(), "slide 4 1 A", "and so does the other player")
        b.say("slide 9")
        self.assertEqual(a.hear(), "slide 9 2 B", "either player may move")
        self.assertEqual(b.hear(), "slide 9 2 B")
        c = Client(self.port, "C")
        self.assertEqual(c.hear(), "slide 9 2 B", "a late joiner is sent where everybody is")
        self.assertEqual(c.hear(), "peers 3")
        a.hear(); b.hear()   # peers 3
        c.say("ping")
        self.assertEqual(c.hear(), "pong")
        a.say("blank 1")
        self.assertEqual(b.hear(), "blank 1 3 A", "a blanking travels like a move")
        a.say("laser 0.25 0.5")
        self.assertEqual(b.hear(), "laser 0.25 0.5 A", "a laser dot is relayed to the others")
        self.assertEqual(c.hear(), "blank 1 3 A")
        self.assertEqual(c.hear(), "laser 0.25 0.5 A")
        a.say("laser off")
        self.assertEqual(b.hear(), "laser off A")
        d = Client(self.port, "D")
        self.assertEqual(d.hear(), "slide 9 2 B", "a late joiner is sent the slide")
        self.assertEqual(d.hear(), "blank 1 3 A", "and the screen")
        for x in (a, b, c, d):
            x.close()

    def test_nonsense_is_ignored(self):
        a = Client(self.port, "A")
        a.hear()
        a.say("slide x")
        a.say("dance")
        a.say("slide 2")
        self.assertEqual(a.hear(), "slide 2 1 A")
        a.close()


    def test_a_move_before_hello_does_not_count(self):
        a = Client(self.port, "A")
        self.assertEqual(a.hear(), "peers 1")
        b = Client(self.port, "B", hello=False)
        b.say("slide 3")
        b.say("hello B")
        self.assertEqual(a.hear(), "peers 2", "nothing from B before its hello")
        a.close()
        b.close()

    def test_the_room_is_kept_out(self):
        d = Client(self.port, "D", hello=False)
        d.say("x" * 300)
        self.assertTrue(d.closed(), "a line over the limit ends the connection")
        e = Client(self.port, "E")
        e.hear()
        for _ in range(2 * sync.MAX_LASER_PER_SEC + 5):   # straddling a second boundary, one side is still over
            e.say("laser 0.1 0.1")
        self.assertTrue(e.closed(), "a laser flood ends the connection")
        room = [Client(self.port, f"P{i}") for i in range(sync.MAX_CLIENTS)]
        for c in room:
            c.hear()
        extra = Client(self.port, "extra")
        self.assertEqual(extra.hear(), "bye full", "one player over the cap is told so")
        self.assertTrue(extra.closed(), "and turned away")
        for c in room:
            c.close()


class KeyedSyncServer(Fixture):
    KEY = "open-sesame"

    def test_only_the_key_gets_in(self):
        wrong = Client(self.port, "W", key="nope")
        self.assertEqual(wrong.hear(), "bye key", "the wrong key is told so")
        self.assertTrue(wrong.closed(), "and the connection ends")
        none = Client(self.port, "N", hello=False)
        none.say("slide 2")
        self.assertTrue(none.closed(), "so does anything before a hello")
        right = Client(self.port, "R", key="open-sesame")
        self.assertEqual(right.hear(), "peers 1", "the right key is in")
        right.close()


if __name__ == "__main__":
    unittest.main()
