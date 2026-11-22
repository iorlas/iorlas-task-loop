import unittest

from aa.duration import parse_duration


class DurationRules(unittest.TestCase):
    def test_basic(self) -> None:
        self.assertEqual(parse_duration("1h30m"), 5400)
        self.assertEqual(parse_duration("90s"), 90)
        self.assertEqual(parse_duration("2d"), 172800)

    def test_case_insensitive(self) -> None:
        self.assertEqual(parse_duration("1H30M"), 5400)

    def test_whitespace(self) -> None:
        self.assertEqual(parse_duration("  1h 30m "), 5400)

    def test_decimals(self) -> None:
        self.assertEqual(parse_duration("1.5h"), 5400)
        self.assertEqual(parse_duration("0.5s"), 0.5)

    def test_any_order(self) -> None:
        self.assertEqual(parse_duration("30m1h"), 5400)

    def test_zero(self) -> None:
        self.assertEqual(parse_duration("0s"), 0)

    def test_invalid(self) -> None:
        for text in ("", "   ", "90", "-1h", "5w", "1h1h", "h", "1.h", "1h-5m", "abc"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_duration(text)
