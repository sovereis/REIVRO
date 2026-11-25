"""Aggregate benchmark rows without dropping abstentions or failed expectations."""
import csv
import json
import math
from pathlib import Path
from statistics import median


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def summarize(rows):
    scored = [row for row in rows if row["truth"] is not None]
    tp = sum(row["detected"] is True and row["truth"] for row in scored)
    fp = sum(row["detected"] is True and not row["truth"] for row in scored)
    tn = sum(row["detected"] is False and not row["truth"] for row in scored)
    fn = sum(row["detected"] is False and row["truth"] for row in scored)
    undecided = [row for row in scored if row["detected"] is None]
    latency = sorted(row["elapsed_ms"] for row in rows)
    return {
        "rows": len(rows), "classified_truth": len(scored),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "abstained_positive": sum(row["truth"] for row in undecided),
        "abstained_negative": sum(not row["truth"] for row in undecided),
        "inconclusive_rate": ratio(sum(row["status"] == "INCONCLUSIVE" for row in rows), len(rows)),
        "error_rate": ratio(sum(row["status"] in {"ERROR", "RETRYABLE", "HARNESS_ERROR"} for row in rows), len(rows)),
        "precision": ratio(tp, tp + fp), "recall_decided": ratio(tp, tp + fn),
        "recall_all_positives": ratio(tp, sum(row["truth"] for row in scored)),
        "regressions_detected": tp,
        "recurrences_detected": sum(row["detected"] is True and row["recurrence"] for row in scored),
        "protection_violations": sum(row["status"] == "VIOLATION" for row in rows),
        "prevention_exercised": False,
        "duplicate_effects": sum(row["duplicate_effects"] for row in rows),
        "latency_median_ms": median(latency),
        "latency_p95_ms": latency[math.ceil(0.95 * len(latency)) - 1],
        "verify_wall_ms": round(sum(row["verify_wall_ms"] for row in rows), 3),
        "verify_cpu_ms": round(sum(row["verify_cpu_ms"] for row in rows), 3),
    }


def write_reports(directory, metadata, scenarios, rows):
    targets = [(mode, case["id"]) for case in scenarios for mode in ("A", "B", "C")]
    if [(row["mode"], row["scenario"]) for row in rows] != targets:
        raise ValueError("Expected one ordered result for every scenario and mode")
    summaries = {mode: summarize([row for row in rows if row["mode"] == mode]) for mode in ("A", "B", "C")}
    profiled = [row for row in rows if row["mode"] == "C" and "database_ms" in row]
    if profiled:
        summaries["C"]["profile_total_ms"] = {
            key: round(sum(row[key] for row in profiled), 3)
            for key in ("database_ms", "agent_io_ms", "verify_wall_ms", "elapsed_ms")
        }
    integrity = all(
        row["status"] == row["expected"] == case["expected"]["ABC".index(row["mode"])]
        and row["truth"] is case["truth"] and row["recurrence"] is case["recurrence"]
        and not row["duplicate_effects"]
        for row, case in zip(rows, (case for case in scenarios for _ in range(3)))
    )
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    data = {**metadata, "integrity": integrity, "summary": summaries, "results": rows}
    (path / "results.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    with (path / "results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(dict.fromkeys(key for row in rows for key in row)))
        writer.writeheader()
        writer.writerows(rows)
    lines = [f"# REIVRO effectiveness benchmark v{metadata.get('scenario_version', 1)}", "", f"Code: `{metadata['code_sha']}`.",
             f"Integrity: {'PASS' if integrity else 'FAIL'}.", "",
             "| Mode | TP | FP | TN | FN | Undecided positive | Undecided negative | Median ms | P95 ms |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for mode, stats in summaries.items():
        columns = [stats[key] for key in ("tp", "fp", "tn", "fn", "abstained_positive", "abstained_negative",
                                          "latency_median_ms", "latency_p95_ms")]
        lines.append("| " + " | ".join(map(str, [mode, *columns])) + " |")
    lines += ["", "| Scenario | A | B | C |", "| --- | --- | --- | --- |"]
    for index, case in enumerate(scenarios):
        status = [row["status"] for row in rows[3 * index:3 * index + 3]]
        lines.append("| " + " | ".join([case["id"], *status]) + " |")
    lines += ["", "Synthetic public-PR responses, isolated local compiler and disposable PostgreSQL.",
              "A is simulated acceptance without verification. No merge blocking was exercised.",
              "See JSON for precision, recall, errors, CPU time, versions and row-level evidence."]
    (path / "summary.md").write_text("\n".join(lines) + "\n")
    return integrity
