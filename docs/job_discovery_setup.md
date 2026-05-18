# Job Discovery Setup

## What This Tool Can Do

`scripts/discover_jobs.py` watches targeted companies and search queries, saves new leads, scores them with your career rubric, and writes ranked reports.

It supports four discovery sources:

- `career-pages`: no API key, scans public company career pages. This is free but limited because many career pages are JavaScript-heavy.
- `serpapi`: best option for Google Jobs-style discovery. Requires `SERPAPI_KEY`.
- `google-cse`: Google Programmable Search. Requires `GOOGLE_API_KEY` and `GOOGLE_CSE_ID`.
- `bing`: Bing Web Search API. Requires `BING_SEARCH_KEY`.

## Recommended Setup

Use `serpapi` first if you want the least friction. It is usually better for job discovery than raw company-page scraping.

Free company-page scan:

```bash
python3 scripts/discover_jobs.py \
  --provider career-pages \
  --limit 30 \
  --min-score 3.0 \
  --debug
```

If this prints `0 pages loaded`, the career pages are blocked or your local Python cannot read them. The tool retries common certificate failures, but some company sites still block simple programmatic access.

If it prints leads scanned but `0 kept`, the scanner found URLs but they scored below your threshold. This is common when public career pages expose category pages such as `Engineering` instead of real job-description pages.

```bash
export SERPAPI_KEY="your_key_here"

python3 scripts/discover_jobs.py \
  --provider serpapi \
  --limit 40 \
  --min-score 3.2 \
  --track
```

To inspect everything, including weak or noisy results:

```bash
python3 scripts/discover_jobs.py \
  --provider career-pages \
  --limit 20 \
  --include-low-score \
  --debug \
  --rescan
```

Use that only for debugging. Normal runs keep only roles above your score threshold.

For Google Programmable Search:

```bash
export GOOGLE_API_KEY="your_key_here"
export GOOGLE_CSE_ID="your_search_engine_id_here"

python3 scripts/discover_jobs.py \
  --provider google-cse \
  --limit 40 \
  --min-score 3.2 \
  --track
```

For Bing:

```bash
export BING_SEARCH_KEY="your_key_here"

python3 scripts/discover_jobs.py \
  --provider bing \
  --limit 40 \
  --min-score 3.2 \
  --track
```

You can combine sources:

```bash
python3 scripts/discover_jobs.py \
  --provider serpapi career-pages \
  --limit 60 \
  --min-score 3.2 \
  --track
```

## Daily Run

Create a log folder:

```bash
mkdir -p logs
```

Then add this to `crontab -e` if you want a local daily run at 8:00 AM:

```cron
0 8 * * * cd /Users/sandipdayani/Documents/Codex/2026-05-15/https-github-com-sandipdayani-sandipdayani-github/sandip-career-ops && /usr/bin/python3 scripts/discover_jobs.py --provider serpapi career-pages --limit 60 --min-score 3.2 --track >> logs/job_discovery.log 2>&1
```

## Outputs

- Raw job text: `jobs/raw/`
- Scored reports: `jobs/evaluated/`
- Discovery CSV: `jobs/discovered/YYYYMMDD-job-leads.csv`
- Application tracker: `jobs/tracker.csv`
- Seen URLs: `jobs/discovered/seen_urls.json`

## What Not To Do

Do not build a bot that logs into LinkedIn and scrapes your account. Use saved search emails, public URLs, company pages, and approved search APIs instead.
