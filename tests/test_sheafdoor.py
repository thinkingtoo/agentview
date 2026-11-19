"""The door's rewrite of a request head (sheafdoor.py): what passes to the hub, what is refused."""
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sheafdoor

DOOR = ("https://laptop.tailnet.ts.net:8446", "laptop.tailnet.ts.net:8446", "laptop.tailnet.ts.net")


def head(*fields):
    return b"\r\n".join([b"POST /_/doc HTTP/1.1", *fields, b"", b""])


class Rewrite(unittest.TestCase):
    def test_host_and_origin_become_the_hub_s_own_and_the_rest_passes(self):
        got = sheafdoor.rewrite(head(b"Host: laptop.tailnet.ts.net:8446", b"Origin: https://laptop.tailnet.ts.net:8446",
                                     b"Cookie: sheaf_27419=x", b"Connection: keep-alive"), DOOR, hub=27419)
        self.assertEqual(got, head(b"Host: 127.0.0.1:27419", b"Origin: http://127.0.0.1:27419",
                                   b"Cookie: sheaf_27419=x", b"Connection: close"))

    def test_another_host_another_origin_or_no_host_is_refused(self):
        for fields in ((b"Host: 127.0.0.1:8792",),
                       (b"Host: laptop.tailnet.ts.net:8446", b"Origin: http://127.0.0.1:27419"),
                       (b"Host: laptop.tailnet.ts.net:8446", b"Host: 127.0.0.1:27419"),
                       (b"Cookie: x",)):
            with self.subTest(fields=fields):
                self.assertIsNone(sheafdoor.rewrite(head(*fields), DOOR))

    def test_the_door_origin_must_be_https_with_a_port(self):
        for value, ok in (("https://laptop.tailnet.ts.net:8446/", True), ("http://laptop.tailnet.ts.net:8446", False),
                          ("https://laptop.tailnet.ts.net", False), ("", False)):
            with self.subTest(value=value):
                with unittest.mock.patch.dict("os.environ", {sheafdoor.DOOR: value}):
                    self.assertEqual(sheafdoor.door_origin() is not None, ok)



if __name__ == "__main__":
    unittest.main()
