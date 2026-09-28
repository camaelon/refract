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
    def __init__(self, port: int, name: str):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.file = self.sock.makefile("rw", encoding="utf-8", newline="\n")
        self.say(f"hello {name}")

    def say(self, line: str) -> None:
        self.file.write(line + "\n")
        self.file.flush()

    def hear(self) -> str:
        return self.file.readline().strip()

    def close(self) -> None:
        self.sock.close()


class SyncServer(unittest.TestCase):
    def setUp(self):
        sync.STATE.__init__()
        self.server = sync.serve("127.0.0.1", 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

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
        c.say("ping")
        self.assertEqual(c.hear(), "pong")
        for x in (a, b, c):
            x.close()

    def test_nonsense_is_ignored(self):
        a = Client(self.port, "A")
        a.hear()
        a.say("slide x")
        a.say("dance")
        a.say("slide 2")
        self.assertEqual(a.hear(), "slide 2 1 A")
        a.close()


if __name__ == "__main__":
    unittest.main()
