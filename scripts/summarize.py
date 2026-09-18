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
from urllib.parse import urlsplit
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
CHANGELOG_SOURCES = {
    "AWS What's New",
    "Cloudflare Changelog",
    "Google Cloud Release Notes",
    "Google Cloud Status",
}

SERVICE_PROMPT_TEMPLATE = """あなたは技術記事の要約アシスタントです。以下は本日「{source}」から収集した記事一覧です。

各記事について日本語で2〜5文の要約を書いてください。何がどう変わったのか・なぜ重要なのかを書き、raw または取得した記事本文に実際に書かれている数値・バージョン番号・手法名・ベンチマーク結果があれば、それを含めてください。rawだけでは内容が分からない場合は、linkの記事ページを実際に取得して確認してください(件数の上限は設けません。必要なだけ取得してください)。linkの取得がエラーやJavaScript必須などで失敗した場合、rawにコメント欄など別のURLが記載されていればそちらも取得を試してください。
【重要】取得したページがエラー・アクセス拒否・本文なし・無関係な内容だった場合、あるいは本文に具体的な数値や技術的詳細が書かれていない場合は、title と raw から分かる範囲だけを1〜2文で書いてください。ソースに無い数値・CVE番号・パラメータ数・ベンチマーク値・バージョン番号を推測や創作で補うことは絶対に禁止です。詳しく見える要約より、短くても正確な要約を優先してください。
特に CVE 番号やバージョン番号などの識別子は、関連する内容が事実であっても、その番号自体が実際に確認した文章に明記されている場合のみ書いてください。番号を確認できない場合は、番号を書かずに内容だけを説明してください。
【重要】学習済みの一般知識で内容を補完することも禁止です。特に、タイトルが似た名前の別のプロジェクト・製品・技術(例: 同じ名前だが無関係な別のOSSプロジェクト)を思い出して、それについて説明してしまうミスに注意してください。raw や実際に取得したページの内容と一致しない知識は、たとえ事実として正しくても書かないでください。
英語の million・billion・trillion は万・億・兆に変換せず、"60 billion" のように元の英語表記のまま書いてください(billionを億に変換する際の桁間違いが起きやすいため)。
また、この一覧全体から「{source}」の今日の傾向をまとめた日本語3〜4文のサービス要約も書いてください。件数の羅列ではなく、技術的にどのようなテーマ・方向性が見られるかを具体的に書いてください。

出力のlinkは、下記の記事一覧に記載された文字列を1文字も変更せずそのままコピーしてください(クエリパラメータの削除・正規化は禁止です)。

元記事が英語など日本語以外であっても、summaryとservice_summaryは必ず日本語で書いてください。英語のまま書くことは禁止です。

出力は次のJSON形式のみとして `{output_path}` に新規作成してください。説明文やコードフェンスは含めないでください:
{{"service_summary": "string", "articles": [{{"link": "string", "summary": "string"}}]}}

記事一覧:
{article_list}
"""

BROADCAST_RULES = """
broadcast は夜のテックニュース番組の読み上げ原稿です。耳だけで追える話し言葉にしてください。
- です・ます調。一文は短くする
- 冒頭の行は「{broadcast_date}、本日のテックダイジェストです。」
- その次の段落からニュース本文。カタログや「今日も〜が目立ちます」「各所で注目」で始めない
- 取り上げるニュースは4本。1段落1本、各2文まで。2本目以降は「一方」「続いて」「このほか」で入る
- 「Aでは〜、Bでは〜、Cでは〜」とサービスや製品を横並びにしない。製品名・機能名を1段落に3つ以上並べない
- 1本目は今日いちばん大きい具体的なニュース（誰が何をしたか）
- リリースノートや What's New の細かい機能追加（送信元IP保存、インスタンス削除、リージョン追加など）は選ばない。人が聞いてニュースだと分かる出来事を選ぶ
- 各ニュースの2文は同じ段落に続けて書き、文のあいだは空行にしない
- 読み上げにくい記号・数式・英語の括弧注釈は残さない。パーセントは「パーセント」と書く
- 締めは独立した最終行で「以上、本日のダイジェストでした。」
- 空行で段落を分ける。箇条書き・マークダウン・括弧注釈の羅列は禁止
- 450〜650文字。650文字を超えない
- 見出しとサービス要約に無い事実・数値・固有名詞を補わない
- 英語の million・billion・trillion は変換せず元の英語表記のまま書く
- 必ず日本語。英語のまま書くことは禁止
"""

DAY_PROMPT_TEMPLATE = """以下は{broadcast_date}のRSSダイジェストです。次の2つを日本語で書いてください。

1. day_summary: 全体を俯瞰した日本語4〜6文の日次要約。技術的なテーマ・傾向・注目すべき変化を、複数のサービスにまたがる形でまとめてください。テーマを述べるときは抽象的な言葉だけで終わらせず、「AWSでは〜」「Cloudflareでは〜」のように具体的なサービス名とその内容をセットで挙げてください。ただし全サービスを機械的に列挙するのではなく、関連するテーマごとにグルーピングして書いてください。

2. broadcast:{broadcast_rules}

出力は次のJSON形式のみとして `{output_path}` に新規作成してください。説明文やコードフェンスは含めないでください:
{{"day_summary": "string", "broadcast": "string"}}

今日の見出し:
{headline_list}

サービス別要約:
{service_list}
"""

BROADCAST_PROMPT_TEMPLATE = """あなたは夜のテックニュース番組のキャスターです。以下の材料だけを使って読み上げ原稿を書いてください。
{broadcast_rules}

悪い例(禁止): 「今日もAI関連の動きが目立ちます。Hacker Newsでは〜。一方Googleでは〜。続いてAWSでは〜。」
良い例の型: 「PrismMLは、大きな言語モデルを約9分の1の大きさに圧縮する手法を発表しました。性能の大半を保ったまま、手元のGPUでも動かしやすくなったということです。」

出力は次のJSON形式のみとして `{output_path}` に新規作成してください。説明文やコードフェンスは含めないでください:
{{"broadcast": "string"}}

今日の見出し:
{headline_list}

サービス別の補足:
{service_list}
"""


def slugify(text: str) -> str:
    return SLUG_RE.sub("-", text.lower()).strip("-") or "service"


def normalize_link(link: str) -> str:
    parts = urlsplit(link)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


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


def format_broadcast_date(run_date: str) -> str:
    parsed = datetime.strptime(run_date, "%Y-%m-%d")
    return f"{parsed.month}月{parsed.day}日"


def select_headlines(items: list[dict[str, Any]], limit: int = 16) -> list[dict[str, Any]]:
    with_summary = [item for item in items if (item.get("ai_summary") or "").strip()]
    news_items = [item for item in with_summary if item.get("source") not in CHANGELOG_SOURCES]
    changelog_items = [item for item in with_summary if item.get("source") in CHANGELOG_SOURCES]
    picked: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for item in news_items:
        source = item.get("source", "")
        if source in seen_sources:
            continue
        picked.append(item)
        seen_sources.add(source)
        if len(picked) >= limit:
            return picked
    for item in news_items:
        if item in picked:
            continue
        picked.append(item)
        if len(picked) >= limit:
            return picked
    for item in changelog_items:
        if item in picked:
            continue
        picked.append(item)
        if len(picked) >= limit:
            break
    return picked


def format_headlines(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        lines.append(f"- {item['title']} ({item.get('source', '')})")
        summary = (item.get("ai_summary") or "").strip()
        if summary:
            lines.append(f"  {summary}")
    return "\n".join(lines) or "- (no headlines)"


def format_service_list(service_summaries: dict[str, str]) -> str:
    return "\n".join(f"- {name}: {summary}" for name, summary in service_summaries.items())


def build_day_prompt(
    service_summaries: dict[str, str],
    output_path: Path,
    run_date: str,
    items: list[dict[str, Any]] | None = None,
) -> str:
    broadcast_date = format_broadcast_date(run_date)
    return DAY_PROMPT_TEMPLATE.format(
        output_path=output_path.relative_to(ROOT),
        service_list=format_service_list(service_summaries),
        headline_list=format_headlines(select_headlines(items or [])),
        broadcast_date=broadcast_date,
        broadcast_rules=BROADCAST_RULES.format(broadcast_date=broadcast_date),
    )


def build_broadcast_prompt(
    service_summaries: dict[str, str],
    items: list[dict[str, Any]],
    output_path: Path,
    run_date: str,
) -> str:
    broadcast_date = format_broadcast_date(run_date)
    return BROADCAST_PROMPT_TEMPLATE.format(
        output_path=output_path.relative_to(ROOT),
        service_list=format_service_list(service_summaries),
        headline_list=format_headlines(select_headlines(items)),
        broadcast_date=broadcast_date,
        broadcast_rules=BROADCAST_RULES.format(broadcast_date=broadcast_date),
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


def write_digest(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    latest_path = DATA_DIR / "latest.json"
    if not latest_path.exists():
        return
    latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))
    if latest_payload.get("report", {}).get("run_date") == payload.get("report", {}).get("run_date"):
        latest_path.write_text(text, encoding="utf-8")


def rollup_day(
    service_summaries: dict[str, str],
    run_date: str,
    *,
    items: list[dict[str, Any]],
    attempts: int,
    base_delay: float,
) -> tuple[str, str]:
    day_output = DATA_DIR / f"{run_date}.summary.day.json"
    try:
        result = summarize_with_retry(
            build_day_prompt(service_summaries, day_output, run_date, items),
            day_output,
            attempts,
            base_delay,
        )
    finally:
        day_output.unlink(missing_ok=True)
    return result.get("day_summary", "") or "", result.get("broadcast", "") or ""


def generate_broadcast(
    service_summaries: dict[str, str],
    items: list[dict[str, Any]],
    run_date: str,
    *,
    attempts: int,
    base_delay: float,
) -> str:
    output_path = DATA_DIR / f"{run_date}.summary.broadcast.json"
    try:
        result = summarize_with_retry(
            build_broadcast_prompt(service_summaries, items, output_path, run_date),
            output_path,
            attempts,
            base_delay,
        )
    finally:
        output_path.unlink(missing_ok=True)
    return result.get("broadcast", "") or ""


def fill_broadcast(path: Path, payload: dict[str, Any], *, attempts: int, base_delay: float) -> bool:
    run_date = payload["report"]["run_date"]
    service_summaries = payload.get("service_summaries") or {}
    items = payload.get("items") or []
    if not service_summaries and not items:
        print(f"{path.name}: no material, cannot generate broadcast")
        return True

    print(f"{path.name}: generating newscaster broadcast...")
    try:
        broadcast = generate_broadcast(
            service_summaries, items, run_date, attempts=attempts, base_delay=base_delay,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort, never fail the pipeline
        print(f"  [broadcast] failed: {exc}", file=sys.stderr)
        payload["report"]["summary_error"] = "broadcast generation failed; see workflow logs"
        write_digest(path, payload)
        return False

    payload["broadcast"] = broadcast
    if (
        broadcast
        and payload.get("report", {}).get("summary_error")
        == "broadcast generation failed; see workflow logs"
    ):
        del payload["report"]["summary_error"]
    write_digest(path, payload)
    print(f"{path.name}: broadcast done")
    return True


def summarize_file(
    path: Path, *, force: bool, attempts: int, base_delay: float, broadcast_only: bool = False,
) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    run_date = payload["report"]["run_date"]

    if broadcast_only:
        return fill_broadcast(path, payload, attempts=attempts, base_delay=base_delay)

    has_day = bool(payload.get("day_summary"))
    has_broadcast = bool(payload.get("broadcast"))
    if has_day and has_broadcast and not force:
        print(f"{path.name}: already summarized, skipping (use --force to redo)")
        return True
    if has_day and not force:
        return fill_broadcast(path, payload, attempts=attempts, base_delay=base_delay)

    items = payload.get("items", [])
    if not items:
        print(f"{path.name}: no items, skipping")
        return True

    by_source: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_source.setdefault(item["source"], []).append(item)

    print(f"{path.name}: summarizing {len(items)} items across {len(by_source)} services...")

    articles_by_link: dict[str, str] = {}
    articles_by_normalized_link: dict[str, str] = {}
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
            link = article.get("link")
            if link:
                summary = article.get("summary", "")
                articles_by_link[link] = summary
                articles_by_normalized_link.setdefault(normalize_link(link), summary)
        if result.get("service_summary"):
            service_summaries[source] = result["service_summary"]

    day_summary = ""
    broadcast = ""
    if service_summaries:
        try:
            time.sleep(base_delay)
            day_summary, broadcast = rollup_day(
                service_summaries,
                run_date,
                items=items,
                attempts=attempts,
                base_delay=base_delay,
            )
        except Exception as exc:  # noqa: BLE001 - best-effort, never fail the pipeline
            print(f"  [day rollup] failed: {exc}", file=sys.stderr)
            had_failure = True

    for item in items:
        summary = articles_by_link.get(item["link"]) or articles_by_normalized_link.get(
            normalize_link(item["link"])
        )
        if summary:
            item["ai_summary"] = summary
    payload["day_summary"] = day_summary
    payload["broadcast"] = broadcast
    payload["service_summaries"] = service_summaries
    if had_failure:
        payload["report"]["summary_error"] = "one or more services failed; see workflow logs"
    elif "summary_error" in payload["report"]:
        del payload["report"]["summary_error"]
    write_digest(path, payload)

    print(
        f"{path.name}: done ({len(articles_by_link)} article summaries, "
        f"{len(service_summaries)} services, broadcast={'yes' if broadcast else 'no'})"
    )
    return not had_failure


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="run_date to summarize (default: today per feeds.yaml timezone)")
    parser.add_argument("--force", action="store_true", help="re-summarize even if already done")
    parser.add_argument(
        "--broadcast-only",
        action="store_true",
        help="regenerate only the newscaster broadcast from existing service summaries",
    )
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
        if not summarize_file(
            path,
            force=args.force,
            attempts=args.attempts,
            base_delay=args.delay,
            broadcast_only=args.broadcast_only,
        ):
            ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
