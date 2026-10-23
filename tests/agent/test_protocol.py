# SPDX-License-Identifier: GPL-3.0-or-later
import json
import unittest

from whittle import protocol
from whittle.protocol import LineDecoder, ProtocolError


class ProtocolTest(unittest.TestCase):
    def test_round_trip_with_non_ascii(self):
        msg = protocol.event("text", {"text": "naïve crate ✓\nnew line"})
        encoded = protocol.encode(msg)
        self.assertTrue(encoded.endswith(b"\n"))
        self.assertEqual(encoded.count(b"\n"), 1, "newlines inside strings are escaped")
        self.assertEqual(LineDecoder().feed(encoded), [msg])

    def test_split_across_every_byte_boundary(self):
        msgs = [protocol.call("a1", "exec", {"code": "print('é')"}), protocol.ok("a1", {"x": 1})]
        data = b"".join(protocol.encode(m) for m in msgs)
        for cut in range(1, len(data)):
            decoder = LineDecoder()
            got = decoder.feed(data[:cut]) + decoder.feed(data[cut:])
            self.assertEqual(got, msgs, f"cut at {cut}")

    def test_several_messages_in_one_chunk(self):
        msgs = [protocol.event("log", {"n": i}) for i in range(5)]
        self.assertEqual(LineDecoder().feed(b"".join(map(protocol.encode, msgs))), msgs)

    def test_lone_surrogates_survive_the_round_trip(self):
        # What os.fsdecode gives for a non-UTF-8 filename.
        text = "caf\udce9.png"
        msg = protocol.ok("a1", {"stdout": text})
        self.assertEqual(LineDecoder().feed(protocol.encode(msg)), [msg])

    def test_blank_lines_are_ignored(self):
        self.assertEqual(LineDecoder().feed(b"\n\n" + protocol.encode(protocol.welcome())), [protocol.welcome()])

    def test_over_long_line(self):
        decoder = LineDecoder(max_line=64)
        with self.assertRaises(ProtocolError):
            decoder.feed(b"x" * 100)
        with self.assertRaises(ProtocolError):
            LineDecoder(max_line=64).feed(b"y" * 80 + b"\n")

    def test_invalid_messages(self):
        for line in [b"{not json}\n", b"[1, 2]\n", b'{"type": "call"}\n',
                     b'{"v": 2, "type": "call"}\n', b'{"v": 1, "type": "shout"}\n', b"\xff\xfe\n"]:
            with self.subTest(line=line), self.assertRaises(ProtocolError):
                LineDecoder().feed(line)

    def test_constructors(self):
        self.assertEqual(protocol.err("b1", protocol.ErrorCode.BUSY, "no")["error"],
                         {"code": "busy", "message": "no", "detail": None})
        hello = protocol.hello("t", 12, "0.1.0", "fake")
        self.assertEqual((hello["type"], hello["protocol"], hello["mode"]), ("hello", 1, "fake"))
        json.dumps(hello)

    def test_id_counter(self):
        ids = protocol.IdCounter("b")
        self.assertEqual([ids.next(), ids.next()], ["b1", "b2"])

    def test_event_names(self):
        self.assertEqual(protocol.Event.AMEND_DELIVERED, "amend_delivered")
