# Career Ops Workflow

## Daily Search Loop

1. Find 5 to 10 roles from LinkedIn, company career pages, university pages, national labs, and research institutes.
2. Save each posting as a text file under `jobs/raw/`.
3. Run `scripts/career_ops.py evaluate` on each role.
4. Apply only to roles marked `Strong apply` or high-quality `Apply selectively`.
5. Use the generated report to tailor the resume, cover letter, and interview angles.

## Weekly Review

1. Open `jobs/tracker.csv`.
2. Check which roles are stuck at `evaluated`, `applied`, `screening`, `interview`, or `follow-up`.
3. Follow up after 7 to 10 days if there is no response.
4. Update search queries if too many roles score below 3.6.
5. Keep rejected roles in the tracker so the system learns what is not worth your time.

## Decision Rules

- Industry roles below 125,000 USD in the USA or 100,000 CAD in Canada need a clear reason: equity, immigration value, rare technical fit, or strong brand leverage.
- Academic roles are not judged only by salary. Judge them by publication value, supervisor/lab fit, funding stability, immigration path, and long-term leverage.
- Avoid roles that are mostly CAD drafting, technician work, maintenance, sales, production supervision, or generic mechanical design unless they lead directly to a better R&D path.
- Do not auto-apply. Quality matters more than volume for your profile.

## Status Values

Use these in `jobs/tracker.csv`:

- `evaluated`
- `tailoring`
- `applied`
- `recruiter_screen`
- `technical_interview`
- `onsite`
- `offer`
- `rejected`
- `paused`

## Confidentiality Rule

It is acceptable to say the GM-sponsored CPDM framework was retained as GM trade-secret IP if you are authorized to say that. Do not share equations, parameters, source code, internal data structures, unpublished validation details, or anything from internal GM systems.
