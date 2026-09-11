# rss-digest

Public, near-zero-cost RSS collector powered by GitHub Actions.

Every day the workflow fetches configured feeds, writes JSON + Markdown digests under `data/`, generates AI summaries (article/service/day level) via an OpenCode agent, and commits the result back to this repo. No servers, no database.

## Cost

| Item | Cost |
|------|------|
| GitHub Actions (public repo) | Free |
| RSS feeds | Free |
| Storage (small JSON/MD files) | Free |
| AI summaries (NVIDIA API via OpenCode) | A few cents/day (depends on how much the agent researches) |

## Layout

```
feeds.yaml            # sources and settings
opencode.json         # summarizer agent + tool permissions
scripts/collect.py    # fetch + normalize + write
scripts/summarize.py  # AI summaries via an OpenCode agent
scripts/build_site.py # static site for GitHub Pages
site/assets/          # CSS
data/
  YYYY-MM-DD.json     # machine-readable snapshot (items + ai_summary/day_summary/service_summaries)
  YYYY-MM-DD.md       # human-readable digest (raw, no AI summaries)
  latest.json
  latest.md
```

## Site

GitHub Pages publishes a readable digest after each run:

**https://k2wanko.github.io/rss-digest/**

Features: source grouping, tag filters, archive of past days.

Raw JSON is published alongside the HTML:

- https://k2wanko.github.io/rss-digest/data/latest.json
- https://k2wanko.github.io/rss-digest/data/YYYY-MM-DD.json

## Customize feeds

Edit `feeds.yaml`:

```yaml
timezone: Asia/Tokyo
lookback_hours: 48
max_items_per_feed: 30

feeds:
  - name: Example Blog
    url: https://example.com/feed.xml
    tags: [example]
```

## AI summaries

After each collection run, `scripts/summarize.py` asks an OpenCode agent (model: `nvidia/nvidia/nemotron-3-ultra-550b-a55b`, NVIDIA's Nemotron 3 Ultra) to read that day's `data/YYYY-MM-DD.json` and write back three tiers of Japanese summaries in one pass:

- **Article-level**: `items[].ai_summary`, one sentence per article
- **Service-level**: `service_summaries[<source name>]`, the day's trend per feed
- **Day-level**: `day_summary`, an overview across all feeds

The agent reads the digest and can fetch an article's actual page (`webfetch`) when the raw RSS snippet is too thin to summarize (e.g. Hacker News' metadata-only entries). It writes its result to a temporary `data/YYYY-MM-DD.summary.json`, which `summarize.py` merges into the real digest and then deletes.

Requires a `NVIDIA_API_KEY` repository secret (free tier at [build.nvidia.com](https://build.nvidia.com)). The `summarizer` agent (defined in `opencode.json`) has `webfetch` and file `edit` permission but no `bash` — RSS content is untrusted third-party text, so this caps a prompt-injected feed entry to reading/writing files and fetching URLs, not running commands.

Summarization is best-effort: if it fails (rate limits, bad output) after retrying with exponential backoff, the digest still ships without AI summaries for that day (`report.summary_error` records why), falling back to the raw RSS blurb on the site.

To (re)generate summaries locally:

```bash
export NVIDIA_API_KEY=...       # https://build.nvidia.com
python scripts/summarize.py                 # today's digest
python scripts/summarize.py --date 2026-09-05
python scripts/summarize.py --backfill       # every data/*.json missing a summary
python scripts/summarize.py --date 2026-09-05 --force  # redo even if already summarized
```

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/collect.py
python scripts/summarize.py   # optional, needs opencode + NVIDIA_API_KEY
python scripts/build_site.py
# open site/output/index.html
```

## Manual trigger

GitHub → Actions → **Collect RSS** → **Run workflow**

## Schedule

Daily at 06:00 JST (`0 21 * * *` UTC).

## Notes

- Public repos get unlimited Actions minutes for standard jobs.
- Some feeds block datacenter IPs or time out; errors are recorded in each digest's report section.
