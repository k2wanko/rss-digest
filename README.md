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

After each collection run, `scripts/summarize.py` calls an OpenCode agent once per service (model: `nvidia/nvidia/nemotron-3-super-120b-a12b`, NVIDIA's Nemotron 3 Super — see "Model" below) plus one final rollup call, producing three tiers of Japanese summaries:

- **Article-level**: `items[].ai_summary`, 2-5 sentences per article, going into technical specifics (numbers, versions, benchmark results) when the source material actually supports them
- **Service-level**: `service_summaries[<source name>]`, the day's trend per feed
- **Day-level**: `day_summary`, an overview across all feeds, built from the service summaries

Each service's articles (title/link/raw snippet) are embedded directly in the prompt — the agent doesn't read the digest JSON file itself. It can fetch an article's actual page (`webfetch`) when the raw RSS snippet is too thin to summarize (e.g. Hacker News' metadata-only entries), and writes its result as JSON to a temporary `data/YYYY-MM-DD.summary.<service-slug>.json` (or `.summary.day.json` for the rollup), which `summarize.py` reads, merges into the real digest, and deletes. If the agent replies in chat instead of writing the file, `summarize.py` parses the JSON out of its reply as a fallback.

Requires a `NVIDIA_API_KEY` repository secret (free tier at [build.nvidia.com](https://build.nvidia.com)). The `summarizer` agent (defined in `opencode.json`) has `webfetch` and file `edit` permission but no `bash` — RSS content is untrusted third-party text, so this caps a prompt-injected feed entry to reading/writing files and fetching URLs, not running commands. In practice the agent has occasionally created small unrelated test files in `data/` on its own initiative; harmless so far, but worth knowing given the permission is this broad. It has also generally ignored the prompt's request to limit how many articles it fetches per service — research volume isn't reliably prompt-controllable.

Summarization is best-effort: each call retries with exponential backoff, a failing service doesn't block the others, and if everything fails the digest still ships without AI summaries for that day (`report.summary_error` records why), falling back to the raw RSS blurb on the site. Even on a normal run, an occasional article ends up without `ai_summary` when the agent's returned link doesn't exactly match the source RSS link — same fallback applies.

An earlier version of the article prompt asked for technical depth unconditionally, which led the model to invent plausible-looking specifics (a fake CVE number, invented parameter counts and benchmark scores) when the source page didn't actually contain them — confirmed by fetching the real source pages. The prompt now requires grounding: state a specific number, version, or identifier only when it's actually present in the raw snippet or a fetched page, and fall back to a short, general sentence otherwise. Spot-checks against primary sources came back clean after this change, but this is a prompt-level mitigation, not a guarantee — treat specific-looking claims in `ai_summary` with the same skepticism as any other unverified LLM output.

### Model

`nvidia/nvidia/nemotron-3-super-120b-a12b` is a temporary stand-in for `nvidia/nvidia/nemotron-3-ultra-550b-a55b` (NVIDIA's larger flagship), whose inference backend was unresponsive at the time this was built. Swap the `MODEL` constant in `scripts/summarize.py` back to Ultra once it's confirmed healthy.

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
