#!/usr/bin/env python3
"""Score recorded GemPT runs against a small, offline case set.

This tool reads JSONL only. It never calls an LLM, MCP server, or network API.
"""

from __future__ import annotations

import argparse
import json
import re
import string
import sys
from pathlib import Path
from typing import Any


REQUIRED_CASE_FIELDS = {
    "id", "problem_type", "prompt", "expected_answer", "grading_criteria",
    "calculator_expected", "verifier_probe", "expected_verifier_verdict",
}
VERDICTS = {"correct", "correction_needed", "uncertain"}
API_FIELDS = {"winner", "final_answer", "scores", "process"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: each record must be an object")
            records.append(value)
    return records


def validate_cases(cases: list[dict[str, Any]]) -> None:
    ids: set[str] = set()
    for index, case in enumerate(cases, 1):
        missing = REQUIRED_CASE_FIELDS - case.keys()
        if missing:
            raise ValueError(f"case row {index} missing fields: {', '.join(sorted(missing))}")
        if not isinstance(case["id"], str) or not case["id"]:
            raise ValueError(f"case row {index} has invalid id")
        if case["id"] in ids:
            raise ValueError(f"duplicate case id: {case['id']}")
        ids.add(case["id"])
        if not isinstance(case["calculator_expected"], bool):
            raise ValueError(f"case {case['id']}: calculator_expected must be boolean")
        if case["expected_verifier_verdict"] not in VERDICTS:
            raise ValueError(f"case {case['id']}: unsupported expected_verifier_verdict")


def normalize_answer(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return re.sub(r"\s+", " ", text)


def extract_final_answer(value: Any) -> str:
    """Extract the answer section from the legacy-compatible formatted reply."""
    text = str(value or "")
    start_marker = "[1] 최종 답안"
    end_marker = "[2] 계산 근거 요약"
    if start_marker in text:
        text = text.split(start_marker, 1)[1]
        if end_marker in text:
            text = text.split(end_marker, 1)[0]
    return text.strip()


def api_response_valid(response: Any) -> bool:
    if not isinstance(response, dict) or not API_FIELDS.issubset(response):
        return False
    scores = response.get("scores")
    if not isinstance(scores, dict) or not {"GPT", "Gemini"}.issubset(scores):
        return False
    if any(not isinstance(scores[key], (int, float)) for key in ("GPT", "Gemini")):
        return False
    return isinstance(response.get("winner"), str) and isinstance(
        response.get("final_answer"), str
    ) and isinstance(response.get("process"), list)


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def evaluate(cases: list[dict[str, Any]], observations: list[dict[str, Any]]) -> dict[str, Any]:
    case_by_id = {case["id"]: case for case in cases}
    observed_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for observation in observations:
        case_id = observation.get("id")
        if case_id not in case_by_id:
            raise ValueError(f"observation references unknown case id: {case_id}")
        variant = observation.get("variant", "unspecified")
        if not isinstance(variant, str) or not variant:
            raise ValueError(f"observation {case_id}: variant must be a non-empty string")
        key = (variant, case_id)
        if key in observed_by_key:
            raise ValueError(f"duplicate observation for variant={variant}, case={case_id}")
        observed_by_key[key] = observation

    answer_count = answer_correct = tool_count = tool_correct = 0
    tool_tp = tool_fp = tool_fn = 0
    verifier_count = verifier_correct = false_accept_count = false_accept_denominator = 0
    response_count = response_valid = 0
    graph_invocations = 0
    step_durations: dict[str, list[float]] = {}
    failed_steps: dict[str, int] = {}
    by_variant: dict[str, dict[str, Any]] = {}

    for (variant, case_id), observation in observed_by_key.items():
        case = case_by_id[case_id]
        variant_stats = by_variant.setdefault(variant, {
            "answer_observed": 0, "answer_correct": 0,
            "tool_observed": 0, "tool_correct": 0,
            "tool_tp": 0, "tool_fp": 0, "tool_fn": 0,
            "verifier_observed": 0, "verifier_correct": 0,
            "false_accepts": 0, "non_correct_verifiers": 0,
            "response_observed": 0, "response_valid": 0,
            "latencies": [], "failures": 0,
        })
        if "final_answer" in observation:
            answer_count += 1
            is_correct = normalize_answer(extract_final_answer(observation["final_answer"])) == normalize_answer(case["expected_answer"])
            answer_correct += is_correct
            variant_stats["answer_observed"] += 1
            variant_stats["answer_correct"] += is_correct

        calls = observation.get("calculator_calls")
        if isinstance(calls, list):
            used = len(calls) > 0
            expected = case["calculator_expected"]
            tool_count += 1
            is_tool_correct = used == expected
            tool_correct += is_tool_correct
            variant_stats["tool_observed"] += 1
            variant_stats["tool_correct"] += is_tool_correct
            tp = used and expected
            fp = used and not expected
            fn = not used and expected
            tool_tp += tp
            tool_fp += fp
            tool_fn += fn
            variant_stats["tool_tp"] += tp
            variant_stats["tool_fp"] += fp
            variant_stats["tool_fn"] += fn

        verdict = observation.get("verifier_verdict")
        if verdict in VERDICTS:
            verifier_count += 1
            is_verdict_correct = verdict == case["expected_verifier_verdict"]
            verifier_correct += is_verdict_correct
            variant_stats["verifier_observed"] += 1
            variant_stats["verifier_correct"] += is_verdict_correct
            if case["expected_verifier_verdict"] != "correct":
                false_accept_denominator += 1
                false_accept = verdict == "correct"
                false_accept_count += false_accept
                variant_stats["non_correct_verifiers"] += 1
                variant_stats["false_accepts"] += false_accept

        if "api_response" in observation:
            response_count += 1
            is_response_valid = api_response_valid(observation["api_response"])
            response_valid += is_response_valid
            variant_stats["response_observed"] += 1
            variant_stats["response_valid"] += is_response_valid

        invocation_count = observation.get("graph_invocations")
        if isinstance(invocation_count, int) and invocation_count >= 0:
            graph_invocations += invocation_count

        steps = observation.get("steps", [])
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict) or not isinstance(step.get("name"), str):
                    continue
                name = step["name"]
                duration = step.get("duration_ms")
                if isinstance(duration, (int, float)) and duration >= 0:
                    step_durations.setdefault(name, []).append(float(duration))
                    variant_stats["latencies"].append(float(duration))
                if step.get("failed") is True:
                    failed_steps[name] = failed_steps.get(name, 0) + 1
                    variant_stats["failures"] += 1

    variant_report = {}
    variants = sorted(by_variant)
    for variant, stats in sorted(by_variant.items()):
        variant_report[variant] = {
            "final_answer_exact_accuracy": ratio(stats["answer_correct"], stats["answer_observed"]),
            "final_answers_observed": stats["answer_observed"],
            "calculator_usage_accuracy": ratio(stats["tool_correct"], stats["tool_observed"]),
            "tool_cases_observed": stats["tool_observed"],
            "calculator_call_precision": ratio(stats["tool_tp"], stats["tool_tp"] + stats["tool_fp"]),
            "calculator_call_recall": ratio(stats["tool_tp"], stats["tool_tp"] + stats["tool_fn"]),
            "verifier_expected_verdict_accuracy": ratio(stats["verifier_correct"], stats["verifier_observed"]),
            "verifier_cases_observed": stats["verifier_observed"],
            "false_acceptance_rate": ratio(stats["false_accepts"], stats["non_correct_verifiers"]),
            "non_correct_verifier_cases_observed": stats["non_correct_verifiers"],
            "structured_api_response_validity": ratio(stats["response_valid"], stats["response_observed"]),
            "api_responses_observed": stats["response_observed"],
            "step_latency_ms_mean": round(sum(stats["latencies"]) / len(stats["latencies"]), 3) if stats["latencies"] else None,
            "step_failures": stats["failures"],
        }

    return {
        "case_count": len(cases),
        "observation_count": len(observed_by_key),
        "unobserved_case_ids": sorted(set(case_by_id) - {case_id for _, case_id in observed_by_key}),
        "unobserved_case_ids_by_variant": {
            variant: sorted(set(case_by_id) - {case_id for seen_variant, case_id in observed_by_key if seen_variant == variant})
            for variant in variants
        },
        "by_variant": variant_report,
        "metrics": {
            "final_answer_exact_accuracy": {
                "correct": answer_correct, "observed": answer_count,
                "value": ratio(answer_correct, answer_count),
            },
            "calculator_usage_accuracy": {
                "correct": tool_correct, "observed": tool_count,
                "value": ratio(tool_correct, tool_count),
                "necessary_call_precision": ratio(tool_tp, tool_tp + tool_fp),
                "necessary_call_recall": ratio(tool_tp, tool_tp + tool_fn),
            },
            "verifier_expected_verdict_accuracy": {
                "correct": verifier_correct, "observed": verifier_count,
                "value": ratio(verifier_correct, verifier_count),
                "misjudgments": verifier_count - verifier_correct,
                "false_acceptance_rate": ratio(false_accept_count, false_accept_denominator),
                "non_correct_cases_observed": false_accept_denominator,
            },
            "structured_api_response_validity": {
                "valid": response_valid, "observed": response_count,
                "value": ratio(response_valid, response_count),
            },
            "graph_invocations_total": graph_invocations,
            "steps": {
                name: {
                    "observed": len(durations),
                    "duration_ms_total": round(sum(durations), 3),
                    "duration_ms_mean": round(sum(durations) / len(durations), 3),
                    "failures": failed_steps.get(name, 0),
                }
                for name, durations in sorted(step_durations.items())
            } | {
                name: {
                    "observed": 0,
                    "duration_ms_total": 0,
                    "duration_ms_mean": None,
                    "failures": count,
                }
                for name, count in sorted(failed_steps.items()) if name not in step_durations
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.jsonl"))
    parser.add_argument(
        "--observations", type=Path,
        help="JSONL of recorded runs; omit to validate/load cases without claiming metrics",
    )
    args = parser.parse_args()
    try:
        cases = read_jsonl(args.cases)
        validate_cases(cases)
        observations = read_jsonl(args.observations) if args.observations else []
        report = evaluate(cases, observations)
        report["mode"] = "recorded_observations" if args.observations else "cases_only"
        report["source"] = {
            "cases": str(args.cases),
            "observations": str(args.observations) if args.observations else None,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(f"evaluation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
