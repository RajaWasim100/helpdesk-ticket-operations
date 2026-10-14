# Help Desk Ticket Operations Analysis

**Portfolio lab based on genuine published help-desk records. Not employment experience or the portfolio owner's service-desk work.**

A reproducible, standard-library Python analysis of version 3 of the [Mendeley Help Desk Tickets dataset](https://doi.org/10.17632/btm76zndnt.3), sourced from a production helpdesk at an international software company. The dataset page says the curated records span January 2007–March 2023; the linked FEATURES.md describes `issues.csv` as January 2016–March 2023. The actual downloaded file includes created timestamps from April 2007, so this release contains a documentation inconsistency that this analysis preserves rather than conceals. Some fields are masked. This project uses issue and change-history exports to demonstrate careful ticket intake, prioritization, workflow, service-quality, and data-validation analysis.

## Why this shows Tier 1-relevant capability

- Builds a ticket-volume and triage profile by source priority, issue type, status, resolution, and month.
- Measures elapsed time from creation to resolution separately from source-calculated workflow time.
- Reviews waiting/workflow-state duration, processing-step counts, contributor counts, comment volume, elapsed time by priority/type, reopen counts by priority, and handoff patterns from assignment history.
- Adds input validation, source file hashing, explicit metric definitions, and aggregate-only reporting.
- Calls out unknowns: source priority is not mapped to a local P1–P4 model, elapsed time is not staffed time or an SLA, and contributors are not necessarily handoffs.

## Quick start

Python 3.10+; no external packages.

1. Download the **published** version 3 files `issues.csv` and `issues_change_history.csv` from the [dataset record](https://data.mendeley.com/datasets/btm76zndnt/3). The change-history file supports status/assignment transition analysis; no utterances or comment text are needed.
2. Put downloads under `data/raw/` (the directory is Git-ignored).
3. Run:

```bash
python analyze.py data/raw/issues.csv --history data/raw/issues_change_history.csv --out reports/operations-summary.json
python -m unittest discover -s tests -v
```

The analyzer streams the ticket file and writes aggregate JSON only; rare labels with fewer than five rows are pooled in full-size datasets to reduce disclosure risk. Small synthetic fixtures used by tests retain their labels. With `--history`, it summarizes status-change values, history coverage, events per ticket, and adjacent assignee changes as a cautious handoff proxy without exposing ticket IDs or assignee values. The history `issueid` matches the internal `id` in the ticket export (not the project-scoped `issue_num`); the pipeline joins on the matching field after normalizing its numeric CSV formatting. History IDs outside the current ticket file and tickets without any history records are counted separately, not silently dropped. It refuses missing required columns, duplicate ticket IDs, invalid timestamps, and negative elapsed intervals. Raw identifiers are used only for local uniqueness/join checks and never serialized.

## Data provenance and privacy

- **Citation:** Abdellatif, Mohammad (2026): *Help Desk Tickets*, version 3. Mendeley Data. https://doi.org/10.17632/btm76zndnt.3
- **License:** DataCite lists [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); preserve attribution for source data and derivatives.
- **Privacy limit:** The publisher says some fields are masked to protect the provider. Masking is not proof that all data is anonymous. Do not publish raw rows, comment text, exact user/project/assignee values, or small-group cuts. Raw downloads are ignored by Git.
- **Scope honesty:** This is secondary analysis of public operational data. It does not represent the author's employment, customer interactions, production tenant access, or personally resolved tickets.

## Metrics and interpretation

- `created_to_resolution_elapsed_hours` is `issue_resolution_date - issue_created`, calendar elapsed time. It is not first response, staffed time, SLA attainment, or a response quality measure.
- `published_workflow_total_seconds` and per-state `wf_*` fields are reported separately; the export's workflow calculation may not equal wall-clock elapsed time.
- `tickets_with_multiple_contributors` is a potential coordination indicator, not confirmed reassignment or avoidable escalation. `wfe_reopened` indicates source-recorded workflow reopens and is not necessarily an operational reopen rate under a current employer's definition.
- The source contains issue priority labels but no support contract or local impact/urgency matrix. We do not infer an SLA or declare any ticket incorrectly prioritized.
- Resolution outcome and statuses are source labels, not a judgment of analyst performance.

## Deliverables

- `analyze.py` — validated, privacy-preserving CLI analysis.
- `tests/` — repeatable behavior and data-quality checks.
- `reports/operations-summary.json` — generated aggregate report (after data download).
- `data/raw/` — local-only original source exports; never commit.

This project demonstrates data-driven service-desk operations thinking. It is distinct from hands-on device troubleshooting; pair it with a personally controlled Windows support lab and describe each accurately on a resume.
