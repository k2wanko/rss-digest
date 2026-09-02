#!/usr/bin/env python3
"""Build a static GitHub Pages site from collected digest JSON files."""

from __future__ import annotations

import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "site"
ASSETS_SRC = SITE_DIR / "assets"
DISPLAY_TZ = ZoneInfo("Asia/Tokyo")
REPO_URL = "https://github.com/k2wanko/rss-digest"


def strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", cleaned)).strip()


def format_time(iso: str | None) -> str:
    if not iso:
        return "日時不明"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M JST")


def load_digests() -> list[tuple[str, dict[str, Any]]]:
    digests: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(DATA_DIR.glob("????-??-??.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        digests.append((path.stem, payload))
    return digests


def collect_tags(items: list[dict[str, Any]]) -> list[str]:
    tags: set[str] = set()
    for item in items:
        tags.update(item.get("tags", []))
    return sorted(tags)


def page_shell(title: str, body: str, active: str = "latest") -> str:
    nav_latest = "aria-current=\"page\"" if active == "latest" else ""
    nav_archive = "aria-current=\"page\"" if active == "archive" else ""
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} · RSS Digest</title>
  <link rel="stylesheet" href="/rss-digest/assets/style.css">
</head>
<body>
  <div class="container">
    <header class="site-header">
      <h1><a href="/rss-digest/">RSS Digest</a></h1>
      <nav>
        <a href="/rss-digest/" {nav_latest}>Latest</a>
        <a href="/rss-digest/archive.html" {nav_archive}>Archive</a>
        <a href="{REPO_URL}">GitHub</a>
      </nav>
    </header>
    {body}
    <footer class="site-footer">Auto-updated daily via GitHub Actions</footer>
  </div>
</body>
</html>
"""


def copy_json_files(output_root: Path) -> None:
    data_out = output_root / "data"
    data_out.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in sorted(DATA_DIR.glob("*.json")):
        shutil.copy2(path, data_out / path.name)
        copied += 1
    print(f"Copied {copied} JSON file(s) to {data_out.relative_to(ROOT)}")


def json_links(run_date: str) -> str:
    return f"""<div class="json-links">
  <span>JSON:</span>
  <a href="/rss-digest/data/{html.escape(run_date)}.json">{html.escape(run_date)}.json</a>
  <a href="/rss-digest/data/latest.json">latest.json</a>
</div>"""


def render_digest_page(run_date: str, payload: dict[str, Any], *, active: str) -> str:
    report = payload["report"]
    items = payload["items"]
    tags = collect_tags(items)

    by_source: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_source.setdefault(item["source"], []).append(item)

    errors_html = ""
    if report.get("errors"):
        error_items = "".join(
            f"<li><strong>{html.escape(err['name'])}</strong>: {html.escape(err['error'])}</li>"
            for err in report["errors"]
        )
        errors_html = f'<div class="errors"><strong>Feed errors</strong><ul>{error_items}</ul></div>'

    filter_buttons = ['<button type="button" class="filter-btn active" data-filter="all">All</button>']
    for tag in tags:
        filter_buttons.append(
            f'<button type="button" class="filter-btn" data-filter="{html.escape(tag)}">{html.escape(tag)}</button>'
        )

    sections: list[str] = []
    for source, source_items in by_source.items():
        rows: list[str] = []
        for item in source_items:
            tag_attr = " ".join(html.escape(tag) for tag in item.get("tags", []))
            summary = strip_html(item.get("summary", ""))
            summary_html = f'<p class="item-summary">{html.escape(summary)}</p>' if summary else ""
            rows.append(
                f"""<li class="item" data-tags="{tag_attr}">
  <a class="item-title" href="{html.escape(item['link'])}" target="_blank" rel="noopener noreferrer">{html.escape(item['title'])}</a>
  <div class="item-meta">
    <span>{html.escape(format_time(item.get('published_at')))}</span>
    {''.join(f'<span class="tag">{html.escape(tag)}</span>' for tag in item.get('tags', []))}
  </div>
  {summary_html}
</li>"""
            )
        sections.append(
            f"""<section class="section">
  <h2>{html.escape(source)}</h2>
  <ul class="item-list">{''.join(rows)}</ul>
</section>"""
        )

    body = f"""
    <article>
      <div class="meta-card">
        <dl class="meta-grid">
          <div><dt>Date</dt><dd>{html.escape(run_date)}</dd></div>
          <div><dt>Items</dt><dd>{report.get('item_count', len(items))}</dd></div>
          <div><dt>Feeds</dt><dd>{report.get('feeds_ok', '?')} / {report.get('feeds_total', '?')}</dd></div>
          <div><dt>Generated</dt><dd>{html.escape(format_time(report.get('generated_at')))}</dd></div>
        </dl>
        {json_links(run_date)}
        {errors_html}
      </div>
      <div class="filters">{''.join(filter_buttons)}</div>
      {''.join(sections)}
    </article>
    <script>
      const buttons = document.querySelectorAll('.filter-btn');
      const items = document.querySelectorAll('.item');
      buttons.forEach((button) => {{
        button.addEventListener('click', () => {{
          buttons.forEach((btn) => btn.classList.remove('active'));
          button.classList.add('active');
          const tag = button.dataset.filter;
          items.forEach((item) => {{
            const tags = item.dataset.tags.split(' ').filter(Boolean);
            item.classList.toggle('hidden', tag !== 'all' && !tags.includes(tag));
          }});
        }});
      }});
    </script>
    """
    return page_shell(f"Digest {run_date}", body, active=active)


def render_archive_page(digests: list[tuple[str, dict[str, Any]]]) -> str:
    rows: list[str] = []
    for run_date, payload in reversed(digests):
        count = payload["report"].get("item_count", len(payload["items"]))
        rows.append(
            f"""<li>
  <div class="archive-row">
    <a href="/rss-digest/digest/{html.escape(run_date)}.html">{html.escape(run_date)}</a>
    <span class="count">{count} items</span>
  </div>
  <div class="json-links">
    <a href="/rss-digest/data/{html.escape(run_date)}.json">{html.escape(run_date)}.json</a>
  </div>
</li>"""
        )
    body = f"""
    <article>
      <div class="meta-card">
        <p>過去のダイジェスト一覧です。</p>
        <div class="json-links">
          <span>Latest JSON:</span>
          <a href="/rss-digest/data/latest.json">latest.json</a>
        </div>
      </div>
      <ul class="archive-list">{''.join(rows) or '<li>No digests yet.</li>'}</ul>
    </article>
    """
    return page_shell("Archive", body, active="archive")


def main() -> int:
    digests = load_digests()
    if not digests:
        print("No digest files found in data/", flush=True)
        return 1

    output_root = SITE_DIR / "output"
    digest_dir = output_root / "digest"
    assets_dir = output_root / "assets"

    if output_root.exists():
        shutil.rmtree(output_root)
    digest_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)
    shutil.copytree(ASSETS_SRC, assets_dir, dirs_exist_ok=True)
    copy_json_files(output_root)

    latest_date, latest_payload = digests[-1]
    for run_date, payload in digests:
        page = render_digest_page(run_date, payload, active="latest")
        (digest_dir / f"{run_date}.html").write_text(page, encoding="utf-8")

    index_page = render_digest_page(latest_date, latest_payload, active="latest")
    (output_root / "index.html").write_text(index_page, encoding="utf-8")
    (output_root / "archive.html").write_text(render_archive_page(digests), encoding="utf-8")

    print(f"Built site for {len(digests)} digest(s); latest={latest_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
