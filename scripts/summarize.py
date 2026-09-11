#!/usr/bin/env python3
"""Generate AI summaries (article/service/day level) for a digest via an OpenCode agent."""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import yaml
except ImportError as exc:
    print("Missing dependency:", exc, file=sys.stderr)
    print("Run: pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(1) from exc

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FEEDS_FILE = ROOT / "feeds.yaml"
MODEL = "nvidia/nvidia/nemotron-3-super-120b-a12b"
AGENT = "summarizer"
CALL_TIMEOUT = 600
SNIPPET_LIMIT = 500
ERROR_LIMIT = 300
SLUG_RE = re.compile(r"[^a-z0-9]+")

SERVICE_PROMPT_TEMPLATE = """あなたは技術記事の要約アシスタントです。以下は本日「{source}」から収集した記事一覧です。

各記事について日本語で2〜5文の要約を書いてください。何がどう変わったのか・なぜ重要なのかを書き、raw または取得した記事本文に実際に書かれている数値・バージョン番号・手法名・ベンチマーク結果があれば、それを含めてください。rawだけでは内容が分からない場合は、linkの記事ページを実際に取得して確認してください(件数の上限は設けません。必要なだけ取得してください)。
【重要】取得したページがエラー・アクセス拒否・本文なし・無関係な内容だった場合、あるいは本文に具体的な数値や技術的詳細が書かれていない場合は、title と raw から分かる範囲だけを1〜2文で書いてください。ソースに無い数値・CVE番号・パラメータ数・ベンチマーク値・バージョン番号を推測や創作で補うことは絶対に禁止です。詳しく見える要約より、短くても正確な要約を優先してください。
特に CVE 番号やバージョン番号などの識別子は、関連する内容が事実であっても、その番号自体が実際に確認した文章に明記されている場合のみ書いてください。番号を確認できない場合は、番号を書かずに内容だけを説明してください。
また、この一覧全体から「{source}」の今日の傾向をまとめた日本語3〜4文のサービス要約も書いてください。件数の羅列ではなく、技術的にどのようなテーマ・方向性が見られるかを具体的に書いてください。

出力のlinkは、下記の記事一覧に記載された文字列を1文字も変更せずそのままコピーしてください(クエリパラメータの削除・正規化は禁止です)。

出力は次のJSON形式のみとして `{output_path}` に新規作成してください。説明文やコードフェンスは含めないでください:
{{"service_summary": "string", "articles": [{{"link": "string", "summary": "string"}}]}}

記事一覧:
{article_list}
"""

DAY_PROMPT_TEMPLATE = """以下は本日のRSSダイジェストを構成する各サービスの要約です。全体を俯瞰した日本語4〜6文の日次要約を書いてください。個々の話題を羅列するのではなく、複数のサービスにまたがる技術的なテーマ・傾向・注目すべき変化を、具体例を挙げながら書いてください。

出力は次のJSON形式のみとして `{output_path}` に新規作成してください。説明文やコードフェンスは含めないでください:
{{"day_summary": "string"}}

サービス別要約:
{service_list}
"""


def slugify(text: str) -> str:
    return SLUG_RE.sub("-", text.lower()).strip("-") or "service"


def strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", cleaned)).strip()


def clean_snippet(raw: str, limit: int = SNIPPET_LIMIT) -> str:
    return strip_html(raw)[:limit]


def build_service_prompt(source: str, items: list[dict[str, Any]], output_path: Path) -> str:
    lines: list[str] = []
    for item in items:
        snippet = clean_snippet(item.get("summary", ""))
        lines.append(f"- title: {item['title']}")
        lines.append(f"  link: {item['link']}")
        if snippet:
            lines.append(f"  raw: {snippet}")
    return SERVICE_PROMPT_TEMPLATE.format(
        source=source, output_path=output_path.relative_to(ROOT), article_list="\n".join(lines),
    )


def build_day_prompt(service_summaries: dict[str, str], output_path: Path) -> str:
    lines = [f"- {name}: {summary}" for name, summary in service_summaries.items()]
    return DAY_PROMPT_TEMPLATE.format(
        output_path=output_path.relative_to(ROOT), service_list="\n".join(lines),
    )


def call_opencode(prompt: str) -> str | None:
    cmd = [
        "opencode", "run",
        "--dir", str(ROOT),
        "--agent", AGENT,
        "-m", MODEL,
        "--format", "json",
        prompt,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=CALL_TIMEOUT, cwd=ROOT)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"opencode timed out after {CALL_TIMEOUT}s") from exc

    if result.returncode != 0:
        raise RuntimeError(f"opencode exited {result.returncode}: {result.stderr.strip()[:ERROR_LIMIT]}")

    last_text: str | None = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "error":
            message = event.get("error", {}).get("data", {}).get("message") or event.get("error")
            raise RuntimeError(f"opencode error: {str(message)[:ERROR_LIMIT]}")
        part = event.get("part", {})
        if event.get("type") == "text" and part.get("type") == "text":
            last_text = part.get("text")
    return last_text


def parse_json_text(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in agent's text reply")
    return json.loads(cleaned[start : end + 1])


def load_ai_result(output_path: Path, fallback_text: str | None) -> dict[str, Any]:
    if output_path.exists():
        parsed = json.loads(output_path.read_text(encoding="utf-8"))
    elif fallback_text:
        # Agent answered in chat instead of writing the file - still usable.
        parsed = parse_json_text(fallback_text)
    else:
        raise RuntimeError(f"{output_path.name} was not created and no text reply to fall back on")
    if not isinstance(parsed, dict):
        raise ValueError("summary result is not a JSON object")
    return parsed


def summarize_with_retry(prompt: str, output_path: Path, attempts: int, base_delay: float) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        output_path.unlink(missing_ok=True)
        try:
            text = call_opencode(prompt)
            return load_ai_result(output_path, text)
        except (RuntimeError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                delay = base_delay * (2**attempt)
                print(f"    attempt {attempt + 1}/{attempts} failed: {exc}; retrying in {delay:.0f}s", file=sys.stderr)
                time.sleep(delay)
    assert last_error is not None
    raise last_error


def load_timezone() -> ZoneInfo:
    with FEEDS_FILE.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    return ZoneInfo(config.get("timezone", "UTC"))


def default_run_date() -> str:
    return datetime.now(load_timezone()).strftime("%Y-%m-%d")


def summarize_file(path: Path, *, force: bool, attempts: int, base_delay: float) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    run_date = payload["report"]["run_date"]

    if payload.get("day_summary") and not force:
        print(f"{path.name}: already summarized, skipping (use --force to redo)")
        return True

    items = payload.get("items", [])
    if not items:
        print(f"{path.name}: no items, skipping")
        return True

    by_source: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_source.setdefault(item["source"], []).append(item)

    print(f"{path.name}: summarizing {len(items)} items across {len(by_source)} services...")

    articles_by_link: dict[str, str] = {}
    service_summaries: dict[str, str] = {}
    had_failure = False

    for i, (source, source_items) in enumerate(by_source.items()):
        if i > 0:
            time.sleep(base_delay)
        output_path = DATA_DIR / f"{run_date}.summary.{slugify(source)}.json"
        prompt = build_service_prompt(source, source_items, output_path)
        print(f"  [{source}] {len(source_items)} items...")
        try:
            result = summarize_with_retry(prompt, output_path, attempts, base_delay)
        except Exception as exc:  # noqa: BLE001 - one service failing shouldn't stop the rest
            print(f"  [{source}] failed: {exc}", file=sys.stderr)
            had_failure = True
            continue
        finally:
            output_path.unlink(missing_ok=True)

        for article in result.get("articles", []):
            if article.get("link"):
                articles_by_link[article["link"]] = article.get("summary", "")
        if result.get("service_summary"):
            service_summaries[source] = result["service_summary"]

    day_summary = ""
    if service_summaries:
        day_output = DATA_DIR / f"{run_date}.summary.day.json"
        try:
            time.sleep(base_delay)
            day_result = summarize_with_retry(
                build_day_prompt(service_summaries, day_output), day_output, attempts, base_delay,
            )
            day_summary = day_result.get("day_summary", "")
        except Exception as exc:  # noqa: BLE001 - best-effort, never fail the pipeline
            print(f"  [day rollup] failed: {exc}", file=sys.stderr)
            had_failure = True
        finally:
            day_output.unlink(missing_ok=True)

    for item in items:
        summary = articles_by_link.get(item["link"])
        if summary:
            item["ai_summary"] = summary
    payload["day_summary"] = day_summary
    payload["service_summaries"] = service_summaries
    if had_failure:
        payload["report"]["summary_error"] = "one or more services failed; see workflow logs"
    elif "summary_error" in payload["report"]:
        del payload["report"]["summary_error"]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    latest_path = DATA_DIR / "latest.json"
    if latest_path.exists():
        latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))
        if latest_payload.get("report", {}).get("run_date") == run_date:
            latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{path.name}: done ({len(articles_by_link)} article summaries, {len(service_summaries)} services)")
    return not had_failure


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="run_date to summarize (default: today per feeds.yaml timezone)")
    parser.add_argument("--force", action="store_true", help="re-summarize even if already done")
    parser.add_argument("--backfill", action="store_true", help="summarize all data/*.json files missing summaries")
    parser.add_argument("--attempts", type=int, default=3, help="retry attempts per call (default: 3)")
    parser.add_argument("--delay", type=float, default=10.0, help="base backoff delay in seconds (default: 10)")
    args = parser.parse_args()

    if args.backfill:
        paths = sorted(DATA_DIR.glob("????-??-??.json"))
    else:
        run_date = args.date or default_run_date()
        paths = [DATA_DIR / f"{run_date}.json"]

    ok = True
    for i, path in enumerate(paths):
        if not path.exists():
            print(f"{path.name}: not found", file=sys.stderr)
            ok = False
            continue
        if i > 0:
            time.sleep(args.delay)
        if not summarize_file(path, force=args.force, attempts=args.attempts, base_delay=args.delay):
            ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
