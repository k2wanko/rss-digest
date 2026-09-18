import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import summarize  # noqa: E402


class FormatBroadcastDateTest(unittest.TestCase):
    def test_drops_zero_padding(self) -> None:
        self.assertEqual(summarize.format_broadcast_date("2026-09-18"), "9月18日")

    def test_keeps_double_digit_month(self) -> None:
        self.assertEqual(summarize.format_broadcast_date("2026-12-01"), "12月1日")


class BuildDayPromptTest(unittest.TestCase):
    def test_asks_for_newscaster_broadcast(self) -> None:
        output = summarize.DATA_DIR / "2026-09-18.summary.day.json"
        items = [
            {
                "title": "Bonsai 2 27B",
                "source": "Hacker News (front page)",
                "ai_summary": "三重値重みでモデルを圧縮した。",
            }
        ]
        prompt = summarize.build_day_prompt(
            {"AWS What's New": "Bedrock の発表"},
            output,
            "2026-09-18",
            items,
        )
        self.assertIn("読み上げ原稿", prompt)
        self.assertIn("9月18日", prompt)
        self.assertIn('"broadcast"', prompt)
        self.assertIn("AWS What's New", prompt)
        self.assertIn("Bonsai 2 27B", prompt)
        self.assertIn("1段落1本", prompt)


class BuildBroadcastPromptTest(unittest.TestCase):
    def test_uses_headlines_and_forbids_catalog_style(self) -> None:
        output = summarize.DATA_DIR / "2026-09-18.summary.broadcast.json"
        prompt = summarize.build_broadcast_prompt(
            {"Hacker News (front page)": "小型化が話題"},
            [
                {
                    "title": "Bonsai 2 27B",
                    "source": "Hacker News (front page)",
                    "ai_summary": "三重値重みでモデルを圧縮した。",
                }
            ],
            output,
            "2026-09-18",
        )
        self.assertIn("Bonsai 2 27B", prompt)
        self.assertIn("今日もAI関連の動きが目立ちます", prompt)
        self.assertIn("4本", prompt)


class SelectHeadlinesTest(unittest.TestCase):
    def test_prefers_one_per_source_first(self) -> None:
        items = [
            {"title": "A1", "source": "S1", "ai_summary": "a1"},
            {"title": "A2", "source": "S1", "ai_summary": "a2"},
            {"title": "B1", "source": "S2", "ai_summary": "b1"},
        ]
        picked = summarize.select_headlines(items, limit=2)
        self.assertEqual([item["title"] for item in picked], ["A1", "B1"])

    def test_defers_changelog_sources(self) -> None:
        items = [
            {"title": "NLB tip", "source": "AWS What's New", "ai_summary": "ip"},
            {"title": "Bonsai", "source": "Hacker News (front page)", "ai_summary": "model"},
        ]
        picked = summarize.select_headlines(items, limit=1)
        self.assertEqual(picked[0]["title"], "Bonsai")


if __name__ == "__main__":
    unittest.main()
