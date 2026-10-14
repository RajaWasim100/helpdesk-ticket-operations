#!/usr/bin/env python3
"""Analyze Mendeley Help Desk Tickets without exporting ticket-level identifiers."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

SOURCE_DOI = "10.17632/btm76zndnt.3"
LABEL = "REAL PUBLISHED MASKED OPERATIONAL DATA — NOT THE PORTFOLIO OWNER'S WORK HISTORY"
REQUIRED = {
    "id", "issue_type", "issue_priority", "issue_created",
    "issue_resolution_date", "issue_resolution", "issue_status",
    "issue_comments_count", "issue_contr_count", "wf_total_time", "processing_steps",
}
HISTORY_REQUIRED = {"id", "issueid", "field", "value", "created"}


def summarize_history(path: Path, ticket_ids: set[str]) -> dict[str, object]:
    """Summarize status transitions and history coverage without exporting record IDs."""
    if not path.is_file():
        raise FileNotFoundError(path)
    transitions: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    ticket_events: Counter[str] = Counter()
    assignment_by_ticket: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    status_changes = 0
    matched_tickets: set[str] = set()
    unmatched_history_ids: set[str] = set()
    total_rows = 0
    timestamps: list[datetime] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = sorted(HISTORY_REQUIRED - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"{path.name}: missing required fields: {', '.join(missing)}")
        for row_num, row in enumerate(reader, start=2):
            total_rows += 1
            issue_id = (row.get("issueid") or "").strip().removesuffix(".0")
            if not issue_id:
                raise ValueError(f"{path.name}:{row_num}: missing issueid")
            if issue_id in ticket_ids:
                matched_tickets.add(issue_id)
                ticket_events[issue_id] += 1
            else:
                unmatched_history_ids.add(issue_id)
            field = (row.get("field") or "").strip().lower() or "(not recorded)"
            value = (row.get("value") or "").strip().lower() or "(not recorded)"
            event_counts[field] += 1
            if field == "status":
                status_changes += 1
                transitions[value] += 1
            created = parse_time(row.get("created") or "", row_num, "history.created")
            if created:
                timestamps.append(created)
                if field == "assignee" and issue_id in ticket_ids:
                    assignee = (row.get("value") or "").strip()
                    if assignee:
                        assignment_by_ticket[issue_id].append((created, assignee))
    handoffs_per_ticket: list[float] = []
    teams_per_ticket: list[float] = []
    for events in assignment_by_ticket.values():
        ordered = sorted(events, key=lambda item: item[0])
        distinct_assignees = [assignee for _, assignee in ordered]
        handoffs_per_ticket.append(float(sum(a != b for a, b in zip(distinct_assignees, distinct_assignees[1:]))))
        teams_per_ticket.append(float(len(set(distinct_assignees))))
    return {
        "history_rows": total_rows,
        "history_rows_matching_current_ticket_export": sum(ticket_events.values()),
        "history_issue_ids_not_in_current_ticket_export": len(unmatched_history_ids),
        "ticket_records_with_history_pct": round(len(matched_tickets) * 100 / len(ticket_ids), 2) if ticket_ids else None,
        "ticket_records_without_history": max(0, len(ticket_ids) - len(matched_tickets)),
        "history_events_per_ticket_with_history": quantiles([float(n) for n in ticket_events.values()]),
        "history_event_fields": distribution(event_counts, total_rows),
        "status_change_count": status_changes,
        "status_values_in_history": distribution(transitions, status_changes),
        "assignment_history": {
            "tickets_with_assignment_events": len(assignment_by_ticket),
            "assignee_change_events_per_ticket": quantiles(handoffs_per_ticket),
            "distinct_assignees_per_ticket": quantiles(teams_per_ticket),
            "note": "Adjacent changed-to assignee values are counted as handoffs; first assignment is not a handoff. A change in assignee is not necessarily a team escalation.",
        },
        "history_timestamp_coverage": {
            "first": min(timestamps).isoformat() if timestamps else None,
            "last": max(timestamps).isoformat() if timestamps else None,
        },
    }


def parse_time(value: str, row_number: int, field: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"row {row_number}: invalid {field} timestamp {value!r}") from exc


def number(value: str, row_number: int, field: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"row {row_number}: invalid numeric {field} value {value!r}") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"row {row_number}: non-finite {field} value")
    return parsed


def quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "p90": None}
    ordered = sorted(values)
    return {
        "median": round(statistics.median(ordered), 2),
        "p90": round(ordered[math.ceil(0.9 * len(ordered)) - 1], 2),
    }


def distribution(counter: Counter[str], total: int, minimum_cell: int = 5) -> list[dict[str, object]]:
    """Aggregate rare labels to reduce disclosure risk from provider-masked records."""
    # Small fixtures remain readable for tests and local experiments; production-sized
    # datasets use pooling to avoid publishing rare label combinations.
    threshold = minimum_cell if total >= 100 else 1
    visible = [(label, count) for label, count in counter.items() if count >= threshold]
    suppressed = sum(count for _, count in counter.items() if count < threshold)
    if suppressed:
        visible.append((f"Suppressed (labels with fewer than {minimum_cell} records)", suppressed))
    return [
        {"label": label, "count": count, "share_pct": round(count * 100 / total, 2) if total else 0}
        for label, count in sorted(visible, key=lambda pair: (-pair[1], pair[0]))
    ]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def summarize(source: Path, history_path: Path | None = None) -> dict[str, object]:
    if not source.is_file():
        raise FileNotFoundError(source)
    categories: dict[str, Counter[str]] = {
        name: Counter() for name in ("issue_type", "issue_priority", "issue_status", "issue_resolution", "created_month")
    }
    durations: list[float] = []
    workflow_seconds: list[float] = []
    contributors: list[float] = []
    comments: list[float] = []
    steps: list[float] = []
    workflow_by_state: dict[str, list[float]] = defaultdict(list)
    elapsed_by_priority: dict[str, list[float]] = defaultdict(list)
    elapsed_by_type: dict[str, list[float]] = defaultdict(list)
    reopened_by_priority: Counter[str] = Counter()
    created_dates: list[datetime] = []
    resolved_dates: list[datetime] = []
    missing_resolution = 0
    invalid_negative_duration = 0
    duration_workflow_differences = 0
    contributors_gt_one = 0
    ids_seen: set[str] = set()
    history_join_ids: set[str] = set()
    duplicate_ids = 0
    row_count = 0

    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = set(reader.fieldnames or [])
        missing = sorted(REQUIRED - fields)
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")
        state_fields = sorted(
            field for field in fields
            if field.startswith("wf_") and not field.startswith("wfe_") and field != "wf_total_time"
        )
        for row_number, row in enumerate(reader, start=2):
            row_count += 1
            # IDs are used only to detect duplicate records; they are never serialized.
            record_id = (row.get("id") or "").strip()
            if not record_id:
                raise ValueError(f"row {row_number}: missing issue id")
            if record_id in ids_seen:
                duplicate_ids += 1
            ids_seen.add(record_id)
            # History issueid matches issues.csv internal id; issue_num is project-scoped.
            history_join_ids.add(record_id.removesuffix(".0"))

            created = parse_time(row.get("issue_created") or "", row_number, "issue_created")
            resolved = parse_time(row.get("issue_resolution_date") or "", row_number, "issue_resolution_date")
            if created:
                created_dates.append(created)
                categories["created_month"][created.strftime("%Y-%m")] += 1
            if resolved:
                resolved_dates.append(resolved)
            elapsed = None
            if created and resolved:
                elapsed = (resolved - created).total_seconds()
                if elapsed < 0:
                    invalid_negative_duration += 1
                else:
                    elapsed_hours = elapsed / 3600
                    durations.append(elapsed_hours)
                    elapsed_by_priority[(row.get("issue_priority") or "").strip() or "(not recorded)"].append(elapsed_hours)
                    elapsed_by_type[(row.get("issue_type") or "").strip() or "(not recorded)"].append(elapsed_hours)
            elif not resolved:
                missing_resolution += 1

            wf_total = number(row.get("wf_total_time") or "", row_number, "wf_total_time")
            if wf_total is not None and wf_total >= 0:
                workflow_seconds.append(wf_total)
            if elapsed is not None and elapsed >= 0 and wf_total is not None and wf_total >= 0:
                if abs(elapsed - wf_total) > max(300, elapsed * 0.1):
                    duration_workflow_differences += 1

            user_count = number(row.get("issue_contr_count") or "", row_number, "issue_contr_count")
            if user_count is not None:
                if user_count < 0:
                    raise ValueError(f"row {row_number}: negative issue_contr_count")
                contributors.append(user_count)
                contributors_gt_one += user_count > 1
            comment_count = number(row.get("issue_comments_count") or "", row_number, "issue_comments_count")
            if comment_count is not None and comment_count >= 0:
                comments.append(comment_count)
            processing_steps = number(row.get("processing_steps") or "", row_number, "processing_steps")
            if processing_steps is not None and processing_steps >= 0:
                steps.append(processing_steps)

            for field in ("issue_type", "issue_priority", "issue_status", "issue_resolution"):
                value = (row.get(field) or "").strip() or "(not recorded)"
                categories[field][value] += 1
            for field in state_fields:
                seconds = number(row.get(field) or "", row_number, field)
                if seconds is not None and seconds >= 0:
                    workflow_by_state[field[3:].replace("_", " ")].append(seconds / 3600)
            reopened_count = number(row.get("wfe_reopened") or "", row_number, "wfe_reopened")
            if reopened_count is not None and reopened_count > 0:
                reopened_by_priority[(row.get("issue_priority") or "").strip() or "(not recorded)"] += 1

    if row_count == 0:
        raise ValueError("input has a header but no ticket records")
    if invalid_negative_duration:
        raise ValueError(f"found {invalid_negative_duration} negative created-to-resolution intervals")
    if duplicate_ids:
        raise ValueError(f"found {duplicate_ids} duplicate issue IDs; refusing ambiguous ticket counts")

    def bounds(values: list[datetime]) -> dict[str, str | None]:
        if not values:
            return {"first": None, "last": None}
        return {"first": min(values).isoformat(), "last": max(values).isoformat()}

    multiple_contributors = contributors_gt_one
    def grouped_duration(groups: dict[str, list[float]]) -> list[dict[str, object]]:
        return [
            {"label": label, "resolved_ticket_count": len(values), **quantiles(values)}
            for label, values in sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0]))
        ]

    state_summary = [
        {"workflow_state": state, "median_hours": quantiles(values)["median"], "tickets_with_time": len(values)}
        for state, values in workflow_by_state.items() if values
    ]
    state_summary.sort(key=lambda item: (-(item["median_hours"] or 0), item["workflow_state"]))
    resolved_count = len(durations)
    report: dict[str, object] = {
        "title": "Help Desk Ticket Operations Analysis",
        "label": LABEL,
        "provenance": {
            "dataset": "Help Desk Tickets, version 3",
            "creator": "Mohammad Abdellatif",
            "doi": SOURCE_DOI,
            "url": f"https://doi.org/{SOURCE_DOI}",
            "license": "CC BY 4.0 (attribution required)",
            "source_sha256": sha256_file(source),
            "source_size_bytes": source.stat().st_size,
            "privacy_note": "The publisher says certain fields are masked, not that all data is anonymous. Only aggregate outputs are generated; identifiers, project codes, and utterance text are never exported.",
        },
        "scope": {
            "ticket_records": row_count,
            "created_coverage": bounds(created_dates),
            "resolved_coverage": bounds(resolved_dates),
            "unresolved_or_missing_resolution_timestamp": missing_resolution,
        },
        "triage_profile": {
            "issue_type": distribution(categories["issue_type"], row_count),
            "priority": distribution(categories["issue_priority"], row_count),
            "current_status": distribution(categories["issue_status"], row_count),
            "resolution_outcome": distribution(categories["issue_resolution"], row_count),
            "monthly_created_tickets": distribution(categories["created_month"], row_count),
        },
        "workflow_metrics": {
            "created_to_resolution_elapsed_hours": quantiles(durations),
            "published_workflow_total_seconds": quantiles(workflow_seconds),
            "processing_steps": quantiles(steps),
            "contributing_users_per_ticket": quantiles(contributors),
            "tickets_with_multiple_contributors": multiple_contributors,
            "tickets_with_multiple_contributors_pct": round(multiple_contributors * 100 / row_count, 2),
            "mean_comments_per_ticket": round(statistics.mean(comments), 2) if comments else None,
            "created_vs_workflow_total_large_difference_count": duration_workflow_differences,
            "workflow_state_median_hours": state_summary,
            "elapsed_hours_by_priority": grouped_duration(elapsed_by_priority),
            "elapsed_hours_by_issue_type": grouped_duration(elapsed_by_type),
            "reopened_tickets_by_priority": distribution(reopened_by_priority, row_count),
        },
        "metric_definitions": {
            "elapsed_time": "issue_resolution_date minus issue_created; calendar elapsed time, not staffed hours, first response, or SLA attainment.",
            "workflow_total": "Dataset-provided wf_total_time in seconds; separately reported and not assumed equivalent to elapsed time.",
            "multiple_contributors": "issue_contr_count > 1. This indicates multiple contributors, not a direct count of assignment changes or avoidable handoffs.",
            "assignment_handoffs": "Distinct adjacent assignee values in timestamp-sorted assignment history are counted; initial assignment is not counted as a handoff. This is not a team escalation count.",
            "priority": "Source priority labels are reported as-is; no local P1/P2 mapping or SLA target is inferred.",
            "small_cells": "Labels with fewer than 5 records are combined to reduce disclosure risk; this is not a missing-data category.",
            "monthly_created_tickets": "Ticket record counts by issue_created calendar month; no user/project identifiers are included.",
        },
        "change_history": summarize_history(history_path, history_join_ids) if history_path else {
            "notice": "Not computed: provide --history to analyze assignment/status event history.",
        },
        "quality_checks": {
            "duplicate_issue_ids": duplicate_ids,
            "negative_created_to_resolution_intervals": invalid_negative_duration,
            "tickets_with_elapsed_vs_workflow_difference_over_5m_or_10pct": duration_workflow_differences,
            "note": "The elapsed-time comparison is a data-quality diagnostic; divergent values may reflect different workflow semantics, not necessarily bad records.",
        },
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Path to the published issues.csv file")
    parser.add_argument("--history", type=Path, help="Optional issues_change_history.csv source")
    parser.add_argument("--out", type=Path, default=Path("reports/operations-summary.json"))
    args = parser.parse_args()
    result = summarize(args.source, args.history)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote aggregate report: {args.out} ({result['scope']['ticket_records']} ticket records)")


if __name__ == "__main__":
    main()
