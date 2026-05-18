#!/usr/bin/env python3
"""Sandip Career Ops CLI.

Local, dependency-free evaluator for job descriptions.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "profile"
RUBRIC_PATH = ROOT / "rubrics" / "scoring_model.json"
PREFERENCES_PATH = PROFILE_DIR / "preferences.json"
TRACKER_PATH = ROOT / "jobs" / "tracker.csv"
EVALUATED_DIR = ROOT / "jobs" / "evaluated"


@dataclass
class Evaluation:
    company: str
    title: str
    location: str
    salary: str
    url: str
    text: str
    category_scores: dict[str, float]
    matched_terms: dict[str, list[str]]
    industry_score: float
    academic_score: float
    hybrid_score: float
    salary_location_score: float
    salary_signal: str
    location_signal: str
    negative_score: float
    overall_score: float
    track: str
    recommendation: str
    risks: list[str]
    gaps: list[str]
    proof_points: list[str]
    report_path: Path


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def slugify(value: str, fallback: str = "job") -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return value or fallback


def find_terms(text: str, terms: list[str]) -> list[str]:
    low = normalize(text)
    found = []
    for term in terms:
        pattern = r"\b" + re.escape(term.lower()).replace(r"\ ", r"\s+") + r"\b"
        if re.search(pattern, low):
            found.append(term)
    return sorted(set(found), key=str.lower)


def score_category(found_count: int, target: int) -> float:
    if target <= 0:
        return 0.0
    return round(min(5.0, (found_count / target) * 5.0), 2)


def parse_salary(salary_text: str, job_text: str) -> tuple[float | None, str | None]:
    text = f"{salary_text} {job_text}"
    low = text.lower()
    currency = None
    if "cad" in low or "canadian" in low or "c$" in low:
        currency = "CAD"
    elif "usd" in low or "us$" in low or "$" in low:
        currency = "USD"

    candidates: list[float] = []
    for match in re.finditer(r"(?<!\d)(\d{2,3})(?:,?(\d{3}))?\s*(k)?(?!\d)", low):
        whole = match.group(1)
        thousands = match.group(2)
        k_suffix = match.group(3)
        value = float(whole)
        if thousands:
            value = float(f"{whole}{thousands}")
        elif k_suffix:
            value *= 1000
        elif value < 1000 and 60 <= value <= 350:
            value *= 1000
        if 40000 <= value <= 400000:
            candidates.append(value)

    if not candidates:
        return None, currency
    return max(candidates), currency


def salary_score(salary_text: str, job_text: str, preferences: dict[str, Any], track: str) -> tuple[float, str]:
    salary, currency = parse_salary(salary_text, job_text)
    if salary is None:
        return 3.0, "unknown salary"

    if currency == "CAD":
        floor = preferences["salary_targets"]["canada_industry_cad"]
        label = "CAD"
    else:
        floor = preferences["salary_targets"]["usa_industry_usd"]
        label = "USD"

    if track != "industry":
        if salary >= floor:
            return 5.0, f"{salary:,.0f} {label}, strong even for non-industry"
        return 3.2, f"{salary:,.0f} {label}, acceptable only if academic/hybrid value is strong"

    if salary >= floor:
        return 5.0, f"{salary:,.0f} {label}, meets target"
    if salary >= 0.85 * floor:
        return 2.5, f"{salary:,.0f} {label}, below target but close"
    return 1.0, f"{salary:,.0f} {label}, below industry target"


def location_score(location: str, job_text: str, preferences: dict[str, Any]) -> tuple[float, str]:
    text = normalize(f"{location} {job_text[:1200]}")
    padded = f" {text} "
    canada_terms = ["canada", "ontario", "toronto", "waterloo", "kitchener", "ottawa", "montreal", "vancouver", "calgary"]
    usa_terms = ["usa", "united states", "u.s.", "u.s.a.", "michigan", "california", "ohio", "texas", "massachusetts", "tennessee"]
    found_canada = any(term in text for term in canada_terms)
    found_usa = any(term in text for term in usa_terms) or " us " in padded
    if found_canada and found_usa:
        return 5.0, "USA/Canada target location"
    if found_canada:
        return 5.0, "Canada target location"
    if found_usa:
        return 5.0, "USA target location"
    if "remote" in text:
        return 4.0, "remote role, location needs verification"
    return 2.0, "location not clearly Canada/USA"


def weighted_score(track: str, category_scores: dict[str, float], salary_location: float, rubric: dict[str, Any]) -> float:
    weights = rubric["track_weights"][track]
    total = 0.0
    for category, weight in weights.items():
        if category == "salary_location":
            total += salary_location * weight
        else:
            total += category_scores.get(category, 0.0) * weight
    return round(total, 2)


def make_recommendation(overall: float, negative: float, track: str, salary_signal: str, rubric: dict[str, Any]) -> str:
    thresholds = rubric["recommendation_thresholds"]
    if negative >= 3.5:
        return "Reject / low priority: too many off-track signals"
    if "below industry target" in salary_signal and track == "industry" and overall < thresholds["strong_apply"]:
        return "Maybe: technical fit must be exceptional to justify below-target industry salary"
    if overall >= thresholds["strong_apply"]:
        return "Strong apply"
    if overall >= thresholds["apply"]:
        return "Apply selectively"
    if overall >= thresholds["maybe"]:
        return "Maybe / monitor"
    return "Reject / low priority"


def identify_gaps(category_scores: dict[str, float], track: str) -> list[str]:
    gaps = []
    if category_scores.get("technical_core", 0) < 2.5:
        gaps.append("Job does not strongly mention computational mechanics, constitutive modeling, crystal plasticity, or FEA.")
    if category_scores.get("steel_failure", 0) < 2.0 and track == "industry":
        gaps.append("Limited direct connection to AHSS, failure prediction, crash, forming, or fracture.")
    if category_scores.get("implementation", 0) < 2.0:
        gaps.append("Implementation stack is unclear; verify whether Fortran/Python/FEA/model development matters.")
    if category_scores.get("validation", 0) < 2.0:
        gaps.append("Experimental validation component is weak or not stated.")
    if track == "academic" and category_scores.get("academic_alignment", 0) < 2.5:
        gaps.append("Academic research expectations are not clear; check publication, mentoring, and funding context.")
    return gaps or ["No major gaps detected from the job description."]


def identify_risks(category_scores: dict[str, float], negative: float, salary_signal: str, location_signal: str) -> list[str]:
    risks = []
    if negative >= 2.0:
        risks.append("Role contains low-priority signals such as technician, maintenance, sales, CAD-only, or entry-level language.")
    if "below" in salary_signal:
        risks.append("Salary appears below target for industry roles.")
    if "not clearly" in location_signal:
        risks.append("Location is not clearly in Canada or USA.")
    if category_scores.get("technical_core", 0) < 2.0:
        risks.append("May not use Sandip's strongest PhD-level modeling advantage.")
    return risks or ["No obvious red flags from the text."]


def select_proof_points(matched_terms: dict[str, list[str]], rubric: dict[str, Any]) -> list[str]:
    proof_map = rubric["proof_point_map"]
    selected = []
    all_terms = " ".join(term.lower() for terms in matched_terms.values() for term in terms)
    for trigger, proof in proof_map.items():
        if trigger in all_terms:
            selected.append(proof)
    if not selected:
        selected.append("GM trade-secret CPDM, IJP paper, and EBSD/DIC/IR validation loop")
    return sorted(set(selected))


def evaluate_job(args: argparse.Namespace) -> Evaluation:
    rubric = load_json(RUBRIC_PATH)
    preferences = load_json(PREFERENCES_PATH)
    job_text = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
    if not job_text:
        raise SystemExit("Provide --file or --text.")

    full_text = "\n".join([args.company or "", args.title or "", args.location or "", args.salary or "", job_text])
    matched_terms = {}
    category_scores = {}
    for category, terms in rubric["keywords"].items():
        found = find_terms(full_text, terms)
        matched_terms[category] = found
        category_scores[category] = score_category(len(found), rubric["category_targets"].get(category, 5))

    negative_score = category_scores.get("negative", 0.0)
    loc_score, loc_signal = location_score(args.location or "", job_text, preferences)

    provisional_track_scores = {}
    for track in ("industry", "academic", "hybrid"):
        sal_score, _ = salary_score(args.salary or "", job_text, preferences, track)
        salary_location = round((sal_score + loc_score) / 2, 2)
        provisional_track_scores[track] = weighted_score(track, category_scores, salary_location, rubric)

    track = max(provisional_track_scores, key=provisional_track_scores.get)
    sal_score, sal_signal = salary_score(args.salary or "", job_text, preferences, track)
    salary_location = round((sal_score + loc_score) / 2, 2)
    industry_score = weighted_score("industry", category_scores, salary_location, rubric)
    academic_score = weighted_score("academic", category_scores, salary_location, rubric)
    hybrid_score = weighted_score("hybrid", category_scores, salary_location, rubric)
    scores = {"industry": industry_score, "academic": academic_score, "hybrid": hybrid_score}
    track = max(scores, key=scores.get)
    overall = round(max(scores.values()) - min(0.8, negative_score * 0.12), 2)
    recommendation = make_recommendation(overall, negative_score, track, sal_signal, rubric)
    gaps = identify_gaps(category_scores, track)
    risks = identify_risks(category_scores, negative_score, sal_signal, loc_signal)
    proof_points = select_proof_points(matched_terms, rubric)

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    stem = f"{timestamp}-{slugify(args.company, 'company')}-{slugify(args.title, 'role')}"
    report_path = EVALUATED_DIR / f"{stem}.md"

    return Evaluation(
        company=args.company or "Unknown company",
        title=args.title or "Unknown title",
        location=args.location or "Unknown location",
        salary=args.salary or "",
        url=args.url or "",
        text=job_text,
        category_scores=category_scores,
        matched_terms=matched_terms,
        industry_score=industry_score,
        academic_score=academic_score,
        hybrid_score=hybrid_score,
        salary_location_score=salary_location,
        salary_signal=sal_signal,
        location_signal=loc_signal,
        negative_score=negative_score,
        overall_score=overall,
        track=track,
        recommendation=recommendation,
        risks=risks,
        gaps=gaps,
        proof_points=proof_points,
        report_path=report_path,
    )


def markdown_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def top_matched_terms(evaluation: Evaluation) -> str:
    lines = []
    for category, terms in evaluation.matched_terms.items():
        if category == "negative":
            continue
        if terms:
            lines.append(f"- **{category.replace('_', ' ').title()}:** {', '.join(terms[:12])}")
    return "\n".join(lines) or "- No strong technical keyword matches."


def generate_resume_bullets(evaluation: Evaluation) -> list[str]:
    bullets = []
    text = normalize(evaluation.text)
    if any(t in text for t in ["crystal plasticity", "constitutive", "damage", "fracture", "failure"]):
        bullets.append("Developed a CPDM framework for GM-sponsored AHSS failure prediction, later retained as a GM trade secret; integrated rate-dependent crystal plasticity, damage evolution, thermo-mechanical coupling, and EBSD/DIC/IR-based validation.")
    if any(t in text for t in ["fortran", "python", "subroutine", "umat", "vumat", "finite element", "fea"]):
        bullets.append("Implemented crystal-plasticity and damage-model routines in Fortran/Python-supported workflows for finite element material response prediction.")
    if any(t in text for t in ["automotive", "crash", "forming", "ahss", "steel"]):
        bullets.append("Supported automotive AHSS failure prediction by linking microstructure, strain localization, temperature rise, and damage evolution to engineering-scale stress-strain response.")
    if any(t in text for t in ["postdoc", "research scientist", "publication", "university", "grant"]):
        bullets.append("Published first-author research in the International Journal of Plasticity and developed a PhD research program in microstructure-sensitive failure modeling.")
    if not bullets:
        bullets.append("Built multiphysics simulation experience across steel failure, geothermal heat exchangers, additive manufacturing flow, composite RVEs, thermal aerospace manufacturing, and combustion CFD.")
    return bullets


def generate_cover_seed(evaluation: Evaluation) -> str:
    return (
        f"I am interested in the {evaluation.title} role at {evaluation.company} because it aligns with my PhD work in "
        "crystal-plasticity damage modeling, finite element simulation, and experimentally validated failure prediction. "
        "My strongest relevant experience is developing a GM-sponsored CPDM framework for AHSS failure prediction, later "
        "retained as GM trade-secret IP, and validating model behavior using EBSD, DIC, IR thermography, and strain-rate-dependent testing. "
        "I would position myself as someone who can connect material physics, implementation, and engineering decision-making."
    )


def write_report(evaluation: Evaluation) -> None:
    evaluation.report_path.parent.mkdir(parents=True, exist_ok=True)
    bullets = generate_resume_bullets(evaluation)
    content = f"""# Job Evaluation: {evaluation.title}

**Company:** {evaluation.company}  
**Location:** {evaluation.location}  
**Salary:** {evaluation.salary or "Not specified"}  
**URL:** {evaluation.url or "Not specified"}  
**Recommended track:** {evaluation.track}  
**Recommendation:** {evaluation.recommendation}  
**Overall score:** {evaluation.overall_score:.2f} / 5

## Scores

| Dimension | Score |
|---|---:|
| Industry | {evaluation.industry_score:.2f} |
| Academic | {evaluation.academic_score:.2f} |
| Hybrid | {evaluation.hybrid_score:.2f} |
| Salary/location | {evaluation.salary_location_score:.2f} |
| Negative/off-track signal | {evaluation.negative_score:.2f} |

## Signals

- Salary: {evaluation.salary_signal}
- Location: {evaluation.location_signal}

## Matched Terms

{top_matched_terms(evaluation)}

## Best Proof Points To Use

{markdown_list(evaluation.proof_points)}

## Risks

{markdown_list(evaluation.risks)}

## Gaps / Questions To Verify

{markdown_list(evaluation.gaps)}

## Resume Bullets To Consider

{markdown_list(bullets)}

## Cover Letter / Recruiter Message Seed

{generate_cover_seed(evaluation)}

## Interview Prep Angles

- GM trade-secret CPDM: explain business value without revealing confidential details.
- IJP paper: explain model novelty, validation, and what problem it solved.
- EBSD/DIC/IR loop: explain how experiments constrained model assumptions.
- Fortran/material model implementation: explain a hard technical implementation challenge.
- Cross-domain simulation: connect steel failure, composites, CFD, and thermal systems into one modeling identity.

## Raw Job Description

```text
{evaluation.text.strip()}
```
"""
    evaluation.report_path.write_text(content, encoding="utf-8")


def append_tracker(evaluation: Evaluation) -> None:
    TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    exists = TRACKER_PATH.exists()
    with TRACKER_PATH.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow([
                "date_added",
                "company",
                "title",
                "location",
                "track",
                "recommendation",
                "overall_score",
                "industry_score",
                "academic_score",
                "hybrid_score",
                "salary_signal",
                "status",
                "url",
                "report_path",
                "notes",
            ])
        writer.writerow([
            dt.date.today().isoformat(),
            evaluation.company,
            evaluation.title,
            evaluation.location,
            evaluation.track,
            evaluation.recommendation,
            f"{evaluation.overall_score:.2f}",
            f"{evaluation.industry_score:.2f}",
            f"{evaluation.academic_score:.2f}",
            f"{evaluation.hybrid_score:.2f}",
            evaluation.salary_signal,
            "evaluated",
            evaluation.url,
            str(evaluation.report_path.relative_to(ROOT)),
            "",
        ])


def command_evaluate(args: argparse.Namespace) -> None:
    evaluation = evaluate_job(args)
    write_report(evaluation)
    if not args.no_track:
        append_tracker(evaluation)

    print(f"Recommendation: {evaluation.recommendation}")
    print(f"Track: {evaluation.track}")
    print(f"Overall score: {evaluation.overall_score:.2f}/5")
    print(f"Industry / Academic / Hybrid: {evaluation.industry_score:.2f} / {evaluation.academic_score:.2f} / {evaluation.hybrid_score:.2f}")
    print(f"Salary: {evaluation.salary_signal}")
    print(f"Location: {evaluation.location_signal}")
    print(f"Report: {evaluation.report_path}")


def command_profile(_: argparse.Namespace) -> None:
    profile = (PROFILE_DIR / "master_profile.md").read_text(encoding="utf-8")
    preferences = load_json(PREFERENCES_PATH)
    print("# Sandip Career Ops Profile")
    print()
    print("Target countries:", ", ".join(preferences["target_countries"]))
    print("USA industry target:", preferences["salary_targets"]["usa_industry_usd"], "USD")
    print("Canada industry target:", preferences["salary_targets"]["canada_industry_cad"], "CAD")
    print()
    print(profile[:1800].strip())
    if len(profile) > 1800:
        print("\n...")


def command_tracker(_: argparse.Namespace) -> None:
    if not TRACKER_PATH.exists():
        print("No tracker found yet.")
        return
    rows = list(csv.DictReader(TRACKER_PATH.open("r", encoding="utf-8")))
    if not rows:
        print("Tracker is empty.")
        return
    print(f"{'Score':>5}  {'Track':<9}  {'Status':<10}  {'Company':<24}  Title")
    print("-" * 90)
    for row in rows[-25:]:
        print(f"{row['overall_score']:>5}  {row['track']:<9}  {row['status']:<10}  {row['company'][:24]:<24}  {row['title']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sandip Career Ops")
    sub = parser.add_subparsers(dest="command", required=True)

    evaluate = sub.add_parser("evaluate", help="Evaluate a job description")
    evaluate.add_argument("--file", help="Path to job description text file")
    evaluate.add_argument("--text", help="Raw job description text")
    evaluate.add_argument("--company", default="Unknown company")
    evaluate.add_argument("--title", default="Unknown title")
    evaluate.add_argument("--location", default="Unknown location")
    evaluate.add_argument("--salary", default="")
    evaluate.add_argument("--url", default="")
    evaluate.add_argument("--no-track", action="store_true", help="Do not append to jobs/tracker.csv")
    evaluate.set_defaults(func=command_evaluate)

    profile = sub.add_parser("profile", help="Print profile summary")
    profile.set_defaults(func=command_profile)

    tracker = sub.add_parser("tracker", help="Show recent tracker entries")
    tracker.set_defaults(func=command_tracker)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
