# rss-digest

Public, zero-cost RSS collector powered by GitHub Actions.

Every day the workflow fetches configured feeds, writes JSON + Markdown digests under `data/`, and commits the result back to this repo. No servers, no API keys, no database.

## Cost

| Item | Cost |
|------|------|
| GitHub Actions (public repo) | Free |
| RSS feeds | Free |
| Storage (small JSON/MD files) | Free |

## Layout

```
feeds.yaml            # sources and settings
scripts/collect.py    # fetch + normalize + write
scripts/build_site.py # static site for GitHub Pages
site/assets/          # CSS
data/
  YYYY-MM-DD.json     # machine-readable snapshot
  YYYY-MM-DD.md       # human-readable digest
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

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/collect.py
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
