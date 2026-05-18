#!/usr/bin/env python3
"""Discover and score targeted jobs for Sandip Career Ops.

The script avoids logging into job boards or scraping private sessions. It uses:
- public company career pages as a no-key fallback;
- optional search APIs when keys are provided.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[0]
CONFIG_PATH = ROOT / "config" / "job_sources.json"
DISCOVERED_DIR = ROOT / "jobs" / "discovered"
RAW_DIR = ROOT / "jobs" / "raw"
SEEN_PATH = DISCOVERED_DIR / "seen_urls.json"

sys.path.insert(0, str(SCRIPT_DIR))
from career_ops import append_tracker, evaluate_job, slugify, write_report  # noqa: E402


@dataclass
class JobLead:
    company: str
    title: str
    location: str
    salary: str
    url: str
    source: str
    text: str
    found_at: str


@dataclass
class ScoredLead:
    lead: JobLead
    recommendation: str
    track: str
    score: float
    report_path: str
    raw_path: str
    evaluation: Any


@dataclass
class CareerPageStats:
    companies_checked: int = 0
    pages_loaded: int = 0
    pages_failed: int = 0
    links_found: int = 0
    candidate_links: int = 0
    detail_pages_loaded: int = 0
    detail_pages_failed: int = 0
    leads_found: int = 0
    company_rows: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.company_rows is None:
            self.company_rows = []


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def load_seen() -> set[str]:
    if not SEEN_PATH.exists():
        return set()
    try:
        data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return set(data if isinstance(data, list) else data.get("urls", []))


def save_seen(urls: set[str]) -> None:
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(sorted(urls), indent=2), encoding="utf-8")


def clean_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    query = [(k, v) for k, v in query if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
    cleaned_query = urllib.parse.urlencode(query)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), cleaned_query, ""))


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def fetch_url(url: str, timeout: int = 15) -> tuple[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    }
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            raw = response.read(2_000_000)
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace"), content_type
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            try:
                context = ssl._create_unverified_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    content_type = response.headers.get("content-type", "")
                    raw = response.read(2_000_000)
                    charset = response.headers.get_content_charset() or "utf-8"
                    return raw.decode(charset, errors="replace"), content_type
            except (urllib.error.URLError, TimeoutError, ValueError, OSError):
                return "", ""
        return "", ""
    except (TimeoutError, ValueError, OSError):
        return "", ""


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    text = re.sub(r"(?is)<(script|style|noscript|svg|canvas).*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def title_from_url(url: str) -> str:
    path = urllib.parse.urlsplit(url).path
    last = path.rstrip("/").split("/")[-1]
    last = re.sub(r"[-_]+", " ", last)
    last = re.sub(r"\s+", " ", last).strip()
    return last.title() if last else "Unknown title"


def extract_page_title(raw: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    if not match:
        return ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", match.group(1)))).strip()


def extract_anchor_links(raw: str, base_url: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for match in re.finditer(r"(?is)<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>", raw):
        href_match = re.search(r"""href\s*=\s*["'](?P<href>[^"']+)["']""", match.group("attrs"), flags=re.I)
        if not href_match:
            continue
        href = href_match.group("href").strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = clean_url(urllib.parse.urljoin(base_url, href))
        if not url.startswith(("http://", "https://")):
            continue
        label = html_to_text(match.group("body"))[:250]
        links.append((url, label))
    return links


def is_probably_job_link(url: str, label: str, source_text: str, priority_keywords: list[str]) -> bool:
    blob = normalize(f"{url} {label} {source_text[:1000]}")
    if any(bad in blob for bad in ["facebook.com", "twitter.com", "instagram.com", "youtube.com", ".pdf", "privacy", "cookie"]):
        return False

    job_terms = [
        "job",
        "jobs",
        "career",
        "careers",
        "opening",
        "opportunity",
        "position",
        "requisition",
        "req",
        "apply",
    ]
    role_terms = [
        "engineer",
        "scientist",
        "research",
        "postdoc",
        "postdoctoral",
        "materials",
        "mechanical",
        "simulation",
        "modeling",
        "modelling",
        "finite element",
        "cae",
        "crash",
        "fracture",
        "metallurgy",
    ]
    role_terms.extend(priority_keywords)
    return any(term in blob for term in job_terms) and any(term in blob for term in role_terms)


def relevant_enough(text: str, priority_keywords: list[str], company_queries: list[str]) -> bool:
    blob = normalize(text)
    role_terms = [
        "engineer",
        "scientist",
        "research",
        "postdoc",
        "postdoctoral",
        "materials",
        "mechanical",
        "simulation",
        "modeling",
        "modelling",
        "finite element",
        "cae",
        "crash",
        "fracture",
        "metallurgy",
    ]
    if any(term in blob for term in priority_keywords):
        return True
    if any(term in blob for term in company_queries) and any(term in blob for term in role_terms):
        return True
    return False


def extract_location(text: str) -> str:
    locations = [
        "Canada",
        "Ontario",
        "Toronto",
        "Waterloo",
        "Kitchener",
        "Ottawa",
        "Montreal",
        "Vancouver",
        "Calgary",
        "United States",
        "USA",
        "Michigan",
        "California",
        "Ohio",
        "Texas",
        "Massachusetts",
        "Tennessee",
        "Remote",
    ]
    found = [loc for loc in locations if re.search(r"\b" + re.escape(loc) + r"\b", text, flags=re.I)]
    return ", ".join(dict.fromkeys(found[:4])) if found else ""


def extract_salary(text: str) -> str:
    pattern = re.compile(
        r"((?:USD|CAD|US\$|C\$|\$)\s?\d{2,3}(?:,\d{3})?(?:\s?[-–]\s?(?:USD|CAD|US\$|C\$|\$)?\s?\d{2,3}(?:,\d{3})?)?)",
        flags=re.I,
    )
    match = pattern.search(text)
    return match.group(1) if match else ""


def collect_career_page_leads(
    config: dict[str, Any],
    limit: int,
    no_detail: bool,
    company_filter: str,
) -> tuple[list[JobLead], CareerPageStats]:
    priority_keywords = [term.lower() for term in config["priority_keywords"]]
    leads: list[JobLead] = []
    stats = CareerPageStats()
    found_at = dt.datetime.now().isoformat(timespec="seconds")
    company_filter_low = company_filter.lower().strip()

    for company in config["company_watchlist"]:
        if company_filter_low and company_filter_low not in company["name"].lower():
            continue
        if len(leads) >= limit:
            break
        stats.companies_checked += 1
        row = {
            "company": company["name"],
            "loaded": False,
            "links": 0,
            "candidates": 0,
            "leads": 0,
            "reason": "",
        }
        raw, _ = fetch_url(company["career_url"])
        if not raw:
            stats.pages_failed += 1
            row["reason"] = "page did not load or blocked request"
            stats.company_rows.append(row)
            continue
        stats.pages_loaded += 1
        row["loaded"] = True
        page_text = html_to_text(raw)
        links = extract_anchor_links(raw, company["career_url"])
        stats.links_found += len(links)
        row["links"] = len(links)
        company_queries = [term.lower() for term in company.get("queries", [])]
        seen_on_page: set[str] = set()

        for url, label in links:
            if len(leads) >= limit:
                break
            if url in seen_on_page:
                continue
            seen_on_page.add(url)
            if not is_probably_job_link(url, label, page_text, priority_keywords):
                continue
            stats.candidate_links += 1
            row["candidates"] += 1

            detail_raw = ""
            detail_text = ""
            page_title = ""
            if not no_detail:
                time.sleep(0.25)
                detail_raw, _ = fetch_url(url)
                if detail_raw:
                    stats.detail_pages_loaded += 1
                    detail_text = html_to_text(detail_raw)
                    page_title = extract_page_title(detail_raw)
                else:
                    stats.detail_pages_failed += 1

            combined = "\n".join(
                part
                for part in [
                    f"Company: {company['name']}",
                    f"Source career page: {company['career_url']}",
                    f"Link label: {label}",
                    page_title,
                    detail_text,
                ]
                if part
            )
            if not relevant_enough(combined or label, priority_keywords, company_queries):
                continue

            title = label or page_title or title_from_url(url)
            title = re.sub(r"\s+", " ", title).strip()[:160] or "Unknown title"
            text = combined if combined else f"{title}\n{url}"
            row["leads"] += 1
            leads.append(
                JobLead(
                    company=company["name"],
                    title=title,
                    location=extract_location(text),
                    salary=extract_salary(text),
                    url=url,
                    source="career_page",
                    text=text[:25000],
                    found_at=found_at,
                )
            )

        if row["links"] == 0:
            row["reason"] = "loaded, but no normal HTML job links found; likely JavaScript-rendered career site"
        elif row["candidates"] == 0:
            row["reason"] = "loaded, but links did not look like relevant job postings"
        elif row["leads"] == 0:
            row["reason"] = "candidate links found, but none matched your technical filters"
        else:
            row["reason"] = "leads found"
        stats.company_rows.append(row)

    stats.leads_found = len(leads)
    return leads, stats


def google_cse_search(query: str, limit: int) -> list[dict[str, str]]:
    api_key = os.getenv("GOOGLE_API_KEY")
    cse_id = os.getenv("GOOGLE_CSE_ID")
    if not api_key or not cse_id:
        return []
    params = urllib.parse.urlencode({"key": api_key, "cx": cse_id, "q": query, "num": min(limit, 10)})
    raw, _ = fetch_url(f"https://www.googleapis.com/customsearch/v1?{params}")
    if not raw:
        return []
    data = json.loads(raw)
    return [
        {"title": item.get("title", ""), "url": item.get("link", ""), "snippet": item.get("snippet", "")}
        for item in data.get("items", [])
    ]


def bing_search(query: str, limit: int) -> list[dict[str, str]]:
    api_key = os.getenv("BING_SEARCH_KEY")
    if not api_key:
        return []
    endpoint = "https://api.bing.microsoft.com/v7.0/search"
    params = urllib.parse.urlencode({"q": query, "count": min(limit, 50), "responseFilter": "Webpages"})
    request = urllib.request.Request(f"{endpoint}?{params}", headers={"Ocp-Apim-Subscription-Key": api_key})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
        return []
    return [
        {"title": item.get("name", ""), "url": item.get("url", ""), "snippet": item.get("snippet", "")}
        for item in data.get("webPages", {}).get("value", [])
    ]


def serpapi_google_jobs(query: str, limit: int) -> list[dict[str, str]]:
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        return []
    params = urllib.parse.urlencode({"engine": "google_jobs", "q": query, "api_key": api_key, "hl": "en"})
    raw, _ = fetch_url(f"https://serpapi.com/search.json?{params}")
    if not raw:
        return []
    data = json.loads(raw)
    results = []
    for item in data.get("jobs_results", [])[:limit]:
        apply_options = item.get("apply_options") or []
        url = apply_options[0].get("link", "") if apply_options else item.get("share_link", "")
        results.append(
            {
                "title": item.get("title", ""),
                "company": item.get("company_name", ""),
                "location": item.get("location", ""),
                "url": url,
                "snippet": item.get("description", ""),
            }
        )
    return results


def collect_api_leads(config: dict[str, Any], provider: str, limit: int, no_detail: bool) -> list[JobLead]:
    leads: list[JobLead] = []
    found_at = dt.datetime.now().isoformat(timespec="seconds")
    per_query = max(1, min(10, limit))
    for item in config["search_queries"]:
        if len(leads) >= limit:
            break
        if provider == "google-cse":
            results = google_cse_search(item["query"], per_query)
        elif provider == "bing":
            results = bing_search(item["query"], per_query)
        elif provider == "serpapi":
            results = serpapi_google_jobs(item["query"], per_query)
        else:
            results = []

        for result in results:
            if len(leads) >= limit:
                break
            url = clean_url(result.get("url", ""))
            if not url:
                continue
            detail_text = ""
            if not no_detail:
                time.sleep(0.25)
                detail_raw, _ = fetch_url(url)
                detail_text = html_to_text(detail_raw)
            text = "\n".join(
                part
                for part in [
                    f"Search query: {item['query']}",
                    result.get("snippet", ""),
                    detail_text,
                ]
                if part
            )
            leads.append(
                JobLead(
                    company=result.get("company", "") or company_from_url(url),
                    title=result.get("title", "") or title_from_url(url),
                    location=result.get("location", "") or extract_location(text),
                    salary=extract_salary(text),
                    url=url,
                    source=provider,
                    text=text[:25000],
                    found_at=found_at,
                )
            )
    return leads


def company_from_url(url: str) -> str:
    host = urllib.parse.urlsplit(url).netloc.lower()
    host = host.removeprefix("www.")
    parts = host.split(".")
    return parts[0].replace("-", " ").title() if parts else "Unknown company"


def full_lead_text(lead: JobLead) -> str:
    return "\n".join(
        [
            f"Title: {lead.title}",
            f"Company: {lead.company}",
            f"Location: {lead.location}",
            f"Salary: {lead.salary}",
            f"Source: {lead.source}",
            f"URL: {lead.url}",
            "",
            lead.text,
        ]
    ).strip()


def write_raw_lead(lead: JobLead) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    date = dt.date.today().strftime("%Y%m%d")
    name = f"{date}-{slugify(lead.company, 'company')}-{slugify(lead.title, 'role')}-{short_hash(lead.url)}.txt"
    path = RAW_DIR / name
    path.write_text(full_lead_text(lead), encoding="utf-8")
    return path


def score_lead(lead: JobLead, raw_path: Path) -> ScoredLead:
    args = SimpleNamespace(
        file=str(raw_path),
        text=None,
        company=lead.company,
        title=lead.title,
        location=lead.location,
        salary=lead.salary,
        url=lead.url,
        no_track=True,
    )
    evaluation = evaluate_job(args)
    write_report(evaluation)
    return ScoredLead(
        lead=lead,
        recommendation=evaluation.recommendation,
        track=evaluation.track,
        score=evaluation.overall_score,
        report_path=str(evaluation.report_path.relative_to(ROOT)),
        raw_path=str(raw_path.relative_to(ROOT)),
        evaluation=evaluation,
    )


def write_discovery_csv(scored: list[ScoredLead]) -> Path:
    DISCOVERED_DIR.mkdir(parents=True, exist_ok=True)
    path = DISCOVERED_DIR / f"{dt.date.today().strftime('%Y%m%d')}-job-leads.csv"
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(
                [
                    "found_at",
                    "source",
                    "company",
                    "title",
                    "location",
                    "salary",
                    "score",
                    "track",
                    "recommendation",
                    "url",
                    "raw_path",
                    "report_path",
                ]
            )
        for item in scored:
            writer.writerow(
                [
                    item.lead.found_at,
                    item.lead.source,
                    item.lead.company,
                    item.lead.title,
                    item.lead.location,
                    item.lead.salary,
                    f"{item.score:.2f}",
                    item.track,
                    item.recommendation,
                    item.lead.url,
                    item.raw_path,
                    item.report_path,
                ]
            )
    return path


def md_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def build_summary_markdown(
    scored: list[ScoredLead],
    providers: list[str],
    min_score: float,
    scanned_count: int,
    career_page_stats: CareerPageStats | None,
    csv_path: Path | None,
) -> str:
    now = dt.datetime.now().isoformat(timespec="seconds")
    lines = [
        "# Daily Job Discovery Summary",
        "",
        f"- Run time: `{now}`",
        f"- Providers: `{', '.join(providers)}`",
        f"- Minimum score kept: `{min_score:.2f}`",
        f"- New leads scanned: `{scanned_count}`",
        f"- Leads kept: `{len(scored)}`",
    ]
    if csv_path:
        lines.append(f"- Discovery CSV: `{csv_path.relative_to(ROOT)}`")
    if career_page_stats:
        lines.extend(
            [
                "",
                "## Career Page Scan",
                "",
                f"- Companies checked: `{career_page_stats.companies_checked}`",
                f"- Pages loaded: `{career_page_stats.pages_loaded}`",
                f"- Pages failed: `{career_page_stats.pages_failed}`",
                f"- Links found: `{career_page_stats.links_found}`",
                f"- Candidate job links: `{career_page_stats.candidate_links}`",
                f"- Relevant leads before scoring: `{career_page_stats.leads_found}`",
            ]
        )

    lines.append("")
    if not scored:
        lines.extend(
            [
                "## Result",
                "",
                "No strong leads were kept in this run.",
                "",
                "Most likely causes:",
                "",
                "- no search API key was configured;",
                "- career pages were blocked or JavaScript-rendered;",
                "- found links were category pages rather than full job descriptions;",
                "- found jobs scored below the threshold.",
            ]
        )
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "## Ranked Leads",
            "",
            "| Score | Track | Recommendation | Company | Title | Location | Report |",
            "|---:|---|---|---|---|---|---|",
        ]
    )
    for item in sorted(scored, key=lambda row: row.score, reverse=True):
        lines.append(
            "| "
            f"{item.score:.2f} | "
            f"{md_escape(item.track)} | "
            f"{md_escape(item.recommendation)} | "
            f"{md_escape(item.lead.company)} | "
            f"[{md_escape(item.lead.title)}]({item.lead.url}) | "
            f"{md_escape(item.lead.location or 'Not specified')} | "
            f"`{item.report_path}` |"
        )
    return "\n".join(lines) + "\n"


def write_summary_file(path_text: str, content: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def print_api_key_hint(provider: str) -> None:
    if provider == "google-cse":
        print("google-cse skipped: set GOOGLE_API_KEY and GOOGLE_CSE_ID to enable Google Programmable Search.")
    elif provider == "bing":
        print("bing skipped: set BING_SEARCH_KEY to enable Bing Web Search.")
    elif provider == "serpapi":
        print("serpapi skipped: set SERPAPI_KEY to enable SerpAPI Google Jobs search.")


def print_career_page_stats(stats: CareerPageStats, debug: bool) -> None:
    print(
        "Career-page scan: "
        f"{stats.companies_checked} companies checked, "
        f"{stats.pages_loaded} pages loaded, "
        f"{stats.pages_failed} failed, "
        f"{stats.links_found} links found, "
        f"{stats.candidate_links} candidate job links, "
        f"{stats.leads_found} relevant leads."
    )
    if not debug:
        return

    print()
    print(f"{'Company':<32} {'Load':<6} {'Links':>5} {'Cand':>5} {'Leads':>5}  Reason")
    print("-" * 110)
    for row in stats.company_rows or []:
        print(
            f"{row['company'][:32]:<32} "
            f"{'yes' if row['loaded'] else 'no':<6} "
            f"{row['links']:>5} "
            f"{row['candidates']:>5} "
            f"{row['leads']:>5}  "
            f"{row['reason']}"
        )


def discover(args: argparse.Namespace) -> int:
    config = load_json(CONFIG_PATH)
    min_score = args.min_score if args.min_score is not None else float(config.get("min_score_to_report", 3.0))
    providers = args.provider
    if "all" in providers:
        providers = ["career-pages", "google-cse", "bing", "serpapi"]

    all_leads: list[JobLead] = []
    career_page_stats: CareerPageStats | None = None
    for provider in providers:
        if provider == "career-pages":
            career_leads, career_page_stats = collect_career_page_leads(
                config,
                args.limit,
                args.no_detail,
                args.company,
            )
            all_leads.extend(career_leads)
            continue

        if provider == "google-cse" and not (os.getenv("GOOGLE_API_KEY") and os.getenv("GOOGLE_CSE_ID")):
            print_api_key_hint(provider)
            continue
        if provider == "bing" and not os.getenv("BING_SEARCH_KEY"):
            print_api_key_hint(provider)
            continue
        if provider == "serpapi" and not os.getenv("SERPAPI_KEY"):
            print_api_key_hint(provider)
            continue
        all_leads.extend(collect_api_leads(config, provider, args.limit, args.no_detail))

    seen = load_seen()
    unique: list[JobLead] = []
    urls_in_run: set[str] = set()
    for lead in all_leads:
        lead.url = clean_url(lead.url)
        if not lead.url:
            continue
        if lead.url in urls_in_run:
            continue
        if lead.url in seen and not args.rescan:
            continue
        urls_in_run.add(lead.url)
        unique.append(lead)

    scored: list[ScoredLead] = []
    for lead in unique[: args.limit]:
        raw_path = write_raw_lead(lead)
        scored_lead = score_lead(lead, raw_path)
        if args.include_low_score or scored_lead.score >= min_score:
            scored.append(scored_lead)
            if args.track:
                append_tracker(scored_lead.evaluation)
        else:
            raw_path.unlink(missing_ok=True)
            scored_lead.evaluation.report_path.unlink(missing_ok=True)
        seen.add(lead.url)

    save_seen(seen)
    csv_path = write_discovery_csv(scored) if scored else None
    summary_md = build_summary_markdown(
        scored=scored,
        providers=providers,
        min_score=min_score,
        scanned_count=len(unique[: args.limit]),
        career_page_stats=career_page_stats,
        csv_path=csv_path,
    )
    if args.summary_file:
        summary_path = write_summary_file(args.summary_file, summary_md)
    else:
        summary_path = None

    if career_page_stats:
        print_career_page_stats(career_page_stats, args.debug)
    print(f"New leads scanned: {len(unique[: args.limit])}")
    print(f"Leads kept above threshold: {len(scored)}")
    if csv_path:
        print(f"Discovery CSV: {csv_path}")
    if summary_path:
        print(f"Summary: {summary_path}")
    if not scored:
        print("No strong leads found.")
        print("Meaning: the tool either found no new job URLs, or found URLs that scored below your threshold.")
        print("Best fix: use a search API key, especially SERPAPI_KEY, because many company career pages hide jobs behind JavaScript.")
        return 0

    print()
    print(f"{'Score':>5}  {'Track':<9}  {'Recommendation':<24}  {'Company':<28}  Title")
    print("-" * 105)
    for item in sorted(scored, key=lambda row: row.score, reverse=True):
        print(
            f"{item.score:>5.2f}  {item.track:<9}  {item.recommendation[:24]:<24}  "
            f"{item.lead.company[:28]:<28}  {item.lead.title[:80]}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover targeted jobs and score them with Sandip Career Ops.")
    parser.add_argument(
        "--provider",
        nargs="+",
        default=["career-pages"],
        choices=["career-pages", "google-cse", "bing", "serpapi", "all"],
        help="Discovery source. Default: career-pages.",
    )
    parser.add_argument("--limit", type=int, default=30, help="Maximum new leads to scan.")
    parser.add_argument("--min-score", type=float, default=None, help="Minimum score to keep in discovery CSV.")
    parser.add_argument("--include-low-score", action="store_true", help="Keep all scored leads in the discovery CSV.")
    parser.add_argument("--track", action="store_true", help="Append kept evaluations to jobs/tracker.csv.")
    parser.add_argument("--rescan", action="store_true", help="Rescan URLs even if they were seen before.")
    parser.add_argument("--no-detail", action="store_true", help="Do not fetch detail pages; faster but less accurate.")
    parser.add_argument("--company", default="", help="Only scan companies whose name contains this text.")
    parser.add_argument("--debug", action="store_true", help="Print detailed source diagnostics.")
    parser.add_argument("--summary-file", default="", help="Write a Markdown summary for GitHub Actions or daily review.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return discover(args)


if __name__ == "__main__":
    raise SystemExit(main())
