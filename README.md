# Sandip Career Ops

Personal job-search operating system for Sandip Dayani.

This is not a generic spray-and-pray application tool. It is a local decision system for evaluating high-value roles in Canada and the USA across industry, academic, and hybrid research tracks.

## Positioning

**Computational materials researcher specializing in crystal plasticity, damage mechanics, and failure prediction of advanced high-strength steels.**

Primary leverage:

- PhD research in crystal-plasticity damage modeling for AHSS failure prediction.
- GM-sponsored CPDM work for HSLA, DP, and Q&P steels, retained as GM trade-secret IP.
- Experimental validation using EBSD, DIC, IR thermography, and strain-rate-dependent testing.
- Fortran/Python/material-model implementation and finite element simulation experience.
- Prior Fraunhofer, DLR, ANSYS/CFD/FEA, and composite/geothermal modeling experience.

## Salary and Location Filters

- USA industry target: **125,000+ USD**
- Canada industry target: **100,000+ CAD**
- Academic roles are evaluated separately and are not automatically rejected by salary.
- Target countries: **Canada and USA**
- Relocation: **Yes**

## Tracks

1. **Industry R&D / Engineering**
   - Automotive, aerospace, nuclear, defense, materials, CAE, simulation software.
2. **Academic / Research**
   - Postdoc, research scientist, research associate, lecturer, university research engineer.
3. **Hybrid Research**
   - National labs, government labs, university-industry consortia, applied research institutes, corporate research centers.

## Quick Start

Evaluate a pasted job description saved to a file:

```bash
python3 scripts/career_ops.py evaluate \
  --file jobs/raw/example_job.txt \
  --company "Example Company" \
  --title "Computational Materials Scientist" \
  --location "Michigan, USA" \
  --salary "130000 USD"
```

The tool will:

- score the job across industry, academic, and hybrid tracks;
- identify fit, gaps, risks, and proof points;
- recommend apply / maybe / reject;
- write a markdown evaluation report to `jobs/evaluated/`;
- append the role to `jobs/tracker.csv`.

Discover jobs automatically from targeted sources:

```bash
python3 scripts/discover_jobs.py \
  --provider career-pages \
  --limit 30 \
  --min-score 3.0 \
  --debug
```

For serious automatic discovery, use a search API key:

```bash
export SERPAPI_KEY="your_key_here"

python3 scripts/discover_jobs.py \
  --provider serpapi \
  --limit 40 \
  --min-score 3.2 \
  --track
```

Print your profile summary:

```bash
python3 scripts/career_ops.py profile
```

## Structure

```text
sandip-career-ops/
├── profile/
│   ├── master_profile.md
│   ├── interview_story_bank.md
│   ├── proof_points.md
│   └── preferences.json
├── resumes/
│   ├── industry_master.md
│   ├── academic_cv_master.md
│   └── research_scientist_master.md
├── rubrics/
│   └── scoring_model.json
├── jobs/
│   ├── raw/
│   ├── evaluated/
│   ├── discovered/
│   └── tracker.csv
├── config/
│   └── job_sources.json
├── docs/
│   ├── job_discovery_setup.md
│   ├── search_strategy.md
│   └── workflow.md
├── outputs/
│   ├── tailored_resumes/
│   ├── cover_letters/
│   └── interview_prep/
├── scripts/
│   ├── career_ops.py
│   └── discover_jobs.py
└── templates/
    ├── application_pack_prompt.md
    ├── job_description_template.txt
    ├── negotiation_scripts.md
    └── recruiter_messages.md
```

## First Files To Open

- `docs/search_strategy.md` for search queries and target companies.
- `docs/job_discovery_setup.md` for automatic discovery setup.
- `docs/github_actions_setup.md` for daily GitHub automation.
- `resumes/industry_master.md` for industry R&D applications.
- `resumes/academic_cv_master.md` for postdoc, research scientist, and academic roles.
- `profile/interview_story_bank.md` for interview answers.
- `templates/negotiation_scripts.md` before discussing salary.

## Important Rule

The system can generate recommendations and drafts. You still review every output before sending it to an employer, university, lab, or recruiter.
