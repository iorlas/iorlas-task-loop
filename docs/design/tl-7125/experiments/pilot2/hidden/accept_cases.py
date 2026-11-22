import unittest

from aa.duration import parse_duration

VALID = [
    ("1h30m", 5400), ("90s", 90), ("2d", 172800), ("30M1H", 5400), (" 2d 3s ", 172803), ("1.5h", 5400), ("01h", 3600),
    ("0s", 0), ("1.1h", 3960), ("0.1s", 0.1), ("0.1s0.2s".replace("s0.2s", "m"), 6), ("\t1h\n30m ", 5400), ("1h 1m1s", 3661),
    ("365d", 31536000), ("1d1h1m1s", 90061), ("0.25d", 21600), ("2.50m", 150),
]
INVALID = ["", "   ", "90", "1 h", ".5h", "1.h", "-1h", "+1h", "1e3s", "5w", "1h1h", "1h30", "h", "1h-5m", "abc", "1,5h",
           "366d", "365d1s", "1h 30", "1.5.5h", "1h30mx", "1__h",
           "\u0661h", "1\u0665h", "\uff11h", "1\uff48", "1\u017f", "1\u212a", "\xa01h", "1h\xa0", "\r1h", "1h\x0b", "1\u066b5h", "1h\u20030m"]


class Rules(unittest.TestCase):
    def test_valid(self) -> None:
        for text, expected in VALID:
            with self.subTest(text=text):
                got = parse_duration(text)
                self.assertEqual(got, expected)
                self.assertIsInstance(got, int if float(expected).is_integer() else float)

    def test_invalid(self) -> None:
        for text in INVALID:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_duration(text)
