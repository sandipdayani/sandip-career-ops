# GitHub Actions Setup

## Recommendation

Use a private GitHub repository for this project. The files contain your resume strategy, salary targets, application tracker, and job-search history.

## Push This Project To GitHub

Create a new **private** GitHub repository named something like:

```text
sandip-career-ops
```

Then run these commands from your Mac:

```bash
cd /Users/sandipdayani/Documents/Codex/2026-05-15/https-github-com-sandipdayani-sandipdayani-github/sandip-career-ops

git remote add origin https://github.com/sandipdayani/sandip-career-ops.git
git push -u origin main
```

If Git asks for a password, do not use your GitHub account password. Use a GitHub personal access token or GitHub CLI authentication.

## What The Workflow Does

The workflow in `.github/workflows/daily-job-discovery.yml` runs every day at 12:00 UTC, which is 8:00 AM Toronto time during daylight saving time.

It can also be run manually from the GitHub Actions tab.

Each run:

1. checks out the repository;
2. validates the Python scripts and JSON config;
3. runs targeted job discovery using `serpapi` plus career-page fallback;
4. scores jobs using your rubric;
5. writes a daily summary to `jobs/discovered/latest-summary.md`;
6. updates `jobs/tracker.csv`;
7. commits new discovery results back to the repository.

## Required Secret

For useful discovery, add this repository secret:

```text
SERPAPI_KEY
```

GitHub path:

```text
Repository -> Settings -> Secrets and variables -> Actions -> New repository secret
```

Optional secrets:

```text
GOOGLE_API_KEY
GOOGLE_CSE_ID
BING_SEARCH_KEY
```

The workflow can run without these keys, but it will mostly rely on public company career pages, which are less reliable.

## Required Workflow Permission

Because the workflow commits new job results back to the repo, enable write permission:

```text
Repository -> Settings -> Actions -> General -> Workflow permissions -> Read and write permissions
```

Then save.

## First Manual Test

After pushing the repo to GitHub:

1. Open the repository on GitHub.
2. Go to `Actions`.
3. Select `Daily Job Discovery`.
4. Click `Run workflow`.
5. Use:

```text
min_score: 2.5
limit: 20
```

For the real daily run, use:

```text
min_score: 3.2
limit: 60
```

## Important Notes

- GitHub scheduled workflows use UTC cron time.
- Scheduled runs can start a few minutes late depending on GitHub load.
- This does not log into LinkedIn or scrape your LinkedIn account.
- Keep the repo private unless you intentionally want your search tracker public.
