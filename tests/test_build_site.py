import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_site  # noqa: E402


class RenderParagraphsTest(unittest.TestCase):
    def test_splits_blank_lines(self) -> None:
        html = build_site.render_paragraphs("第一段\n\n第二段")
        self.assertEqual(html, "<p>第一段</p><p>第二段</p>")

    def test_escapes_html(self) -> None:
        html = build_site.render_paragraphs("<script>alert(1)</script>")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class RenderOverviewTest(unittest.TestCase):
    def test_prefers_broadcast(self) -> None:
        html = build_site.render_overview(
            {
                "broadcast": "9月18日、本日のテックダイジェストです。\n\n以上、本日のダイジェストでした。",
                "day_summary": "書面の俯瞰要約",
            }
        )
        self.assertIn("キャスター要約", html)
        self.assertIn("data-broadcast", html)
        self.assertIn("読み上げる", html)
        self.assertIn("本日のテックダイジェストです。", html)
        self.assertNotIn("書面の俯瞰要約", html)

    def test_falls_back_to_day_summary(self) -> None:
        html = build_site.render_overview({"day_summary": "俯瞰した要約"})
        self.assertIn("AI要約", html)
        self.assertIn("俯瞰した要約", html)
        self.assertIn("data-broadcast", html)

    def test_empty_without_summaries(self) -> None:
        self.assertEqual(build_site.render_overview({}), "")


class PageShellTest(unittest.TestCase):
    def test_includes_broadcast_script(self) -> None:
        page = build_site.page_shell("Digest", "<p>body</p>")
        self.assertIn("/rss-digest/assets/broadcast.js", page)


if __name__ == "__main__":
    unittest.main()
