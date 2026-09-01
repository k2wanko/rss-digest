#!/usr/bin/env python3
"""Fetch configured RSS feeds and write daily digest files."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

try:
    import feedparser
    import yaml
except ImportError as exc:
    print("Missing dependency:", exc, file=sys.stderr)
    print("Run: pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(1) from exc

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FEEDS_FILE = ROOT / "feeds.yaml"
USER_AGENT = "rss-digest/1.0 (+https://github.com/k2wanko/rss-digest)"


def load_config() -> dict[str, Any]:
    with FEEDS_FILE.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def parse_published(entry: dict[str, Any]) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    for key in ("published", "updated"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def fetch_feed(url: str, timeout: int = 20) -> feedparser.FeedParserDict:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        payload = response.read()
    return feedparser.parse(payload)


def normalize_entry(feed_meta: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    published = parse_published(entry)
    link = entry.get("link") or entry.get("id") or ""
    return {
        "title": (entry.get("title") or "(no title)").strip(),
        "link": link.strip(),
        "published_at": published.isoformat() if published else None,
        "summary": (entry.get("summary") or entry.get("description") or "").strip()[:500],
        "source": feed_meta["name"],
        "source_url": feed_meta["url"],
        "tags": feed_meta.get("tags", []),
    }


def within_lookback(published_at: str | None, cutoff: datetime) -> bool:
    if not published_at:
        return True
    try:
        published = datetime.fromisoformat(published_at)
    except ValueError:
        return True
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return published >= cutoff


def render_markdown(run_date: str, items: list[dict[str, Any]], report: dict[str, Any]) -> str:
    lines = [
        f"# RSS digest — {run_date}",
        "",
        f"- Generated (UTC): {report['generated_at']}",
        f"- Items: {len(items)}",
        f"- Feeds OK: {report['feeds_ok']} / {report['feeds_total']}",
        "",
    ]

    if report["errors"]:
        lines.extend(["## Feed errors", ""])
        for err in report["errors"]:
            lines.append(f"- **{err['name']}**: {err['error']}")
        lines.append("")

    by_source: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_source.setdefault(item["source"], []).append(item)

    for source, source_items in by_source.items():
        lines.extend(["", f"## {source}", ""])
        for item in source_items:
            published = item["published_at"] or "unknown date"
            lines.append(f"- [{item['title']}]({item['link']}) — `{published}`")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    config = load_config()
    tz = ZoneInfo(config.get("timezone", "UTC"))
    lookback_hours = int(config.get("lookback_hours", 48))
    max_items = int(config.get("max_items_per_feed", 30))

    now_local = datetime.now(tz)
    run_date = now_local.strftime("%Y-%m-%d")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    items: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    errors: list[dict[str, str]] = []
    feeds_ok = 0

    for feed in config.get("feeds", []):
        meta = {
            "name": feed["name"],
            "url": feed["url"],
            "tags": feed.get("tags", []),
        }
        try:
            parsed = fetch_feed(feed["url"])
            if getattr(parsed, "bozo", False) and not parsed.entries:
                raise ValueError(getattr(parsed, "bozo_exception", "parse error"))
            feeds_ok += 1
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            errors.append({"name": feed["name"], "url": feed["url"], "error": str(exc)})
            continue

        for entry in parsed.entries[:max_items]:
            normalized = normalize_entry(meta, entry)
            if not within_lookback(normalized["published_at"], cutoff):
                continue
            link = normalized["link"]
            if not link or link in seen_links:
                continue
            seen_links.add(link)
            items.append(normalized)

    def sort_key(item: dict[str, Any]) -> tuple[int, str]:
        if item["published_at"]:
            return (0, item["published_at"])
        return (1, item["title"].lower())

    items.sort(key=sort_key, reverse=True)

    report = {
        "run_date": run_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timezone": str(tz),
        "lookback_hours": lookback_hours,
        "feeds_total": len(config.get("feeds", [])),
        "feeds_ok": feeds_ok,
        "item_count": len(items),
        "errors": errors,
    }

    payload = {"report": report, "items": items}

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    day_json = DATA_DIR / f"{run_date}.json"
    day_md = DATA_DIR / f"{run_date}.md"
    latest_json = DATA_DIR / "latest.json"
    latest_md = DATA_DIR / "latest.md"

    for path in (day_json, latest_json):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    markdown = render_markdown(run_date, items, report)
    for path in (day_md, latest_md):
        path.write_text(markdown, encoding="utf-8")

    print(f"Wrote {len(items)} items to {day_json.relative_to(ROOT)}")
    if errors:
        print(f"Feed errors: {len(errors)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
