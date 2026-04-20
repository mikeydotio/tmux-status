"""Unit tests for the Claude model-ID shortener."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from tmux_claude_model import format_model


class TestFormatModel(unittest.TestCase):

    def test_opus_4_7_preserves_minor(self):
        self.assertEqual(format_model("claude-opus-4-7"), "Opus 4.7")

    def test_opus_4_7_with_1m_marker(self):
        self.assertEqual(format_model("claude-opus-4-7[1m]"), "Opus 4.7 1M")

    def test_opus_4_6(self):
        self.assertEqual(format_model("claude-opus-4-6"), "Opus 4.6")

    def test_opus_4_1_with_release_date(self):
        self.assertEqual(format_model("claude-opus-4-1-20250805"), "Opus 4.1")

    def test_sonnet_4_with_release_date(self):
        self.assertEqual(format_model("claude-sonnet-4-20250514"), "Sonnet 4")

    def test_sonnet_4_6(self):
        self.assertEqual(format_model("claude-sonnet-4-6"), "Sonnet 4.6")

    def test_haiku_4_5_with_release_date(self):
        self.assertEqual(format_model("claude-haiku-4-5-20250805"), "Haiku 4.5")

    def test_two_digit_minor(self):
        self.assertEqual(format_model("claude-haiku-4-10"), "Haiku 4.10")

    def test_1m_marker_non_opus(self):
        self.assertEqual(format_model("claude-sonnet-5-0[1m]"), "Sonnet 5.0 1M")

    def test_opus_without_1m_marker_no_suffix(self):
        self.assertEqual(format_model("claude-opus-4-6"), "Opus 4.6")

    def test_unknown_model_returns_raw(self):
        self.assertEqual(format_model("gpt-4-turbo"), "gpt-4-turbo")

    def test_empty_input(self):
        self.assertEqual(format_model(""), "")

    def test_uppercase_input(self):
        self.assertEqual(format_model("CLAUDE-OPUS-4-7"), "Opus 4.7")

    def test_uppercase_1m_marker(self):
        self.assertEqual(format_model("claude-opus-4-7[1M]"), "Opus 4.7 1M")


if __name__ == "__main__":
    unittest.main()
