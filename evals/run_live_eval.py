#!/usr/bin/env python3
"""Run paired legacy/LangGraph observations for the fixed evaluation cases.

This command makes real provider and MCP calls. It is intentionally separate
from run_eval.py, which only aggregates already-recorded observations.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def make_text_image(text: str) -> bytes:
    """Render a simple synthetic prompt image for pipeline smoke evaluation."""
    text = text.replace("×", "x").replace("÷", "/")
    font = ImageFont.load_default()
    lines = text.splitlines() or [text]
    width = max(640, max(int(font.getlength(line)) for line in lines) + 48)
    height = max(180, len(lines) * 28 + 48)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    y = 24
    for line in lines:
        draw.text((24, y), line, fill="black", font=font)
        y += 28
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def verifier_label(process: list[dict[str, Any]], variant: str) -> str | None:
    for event in process:
        if event.get("model") != "Gemini" or event.get("step") not in {"검증", "라운드 1 재평가"}:
            continue
        content = str(event.get("content", ""))
        if variant == "langgraph":
            try:
                verdict = json.loads(content).get("verdict")
                if verdict in {"correct", "correction_needed", "uncertain"}:
                    return verdict
            except (json.JSONDecodeError, AttributeError):
                pass
        if "따라서 모델 01의 답변이 올바릅니다." in content:
            return "correct"
        if "모델 01의 해결책에는 다음과 같은 오류가 있습니다." in content:
            return "correction_needed"
    return None


def load_cases(path: Path) -> list[dict[str, Any]]:
    from run_eval import read_jsonl, validate_cases

    cases = read_jsonl(path)
    validate_cases(cases)
    return cases


def run(args: argparse.Namespace) -> int:
    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("GOOGLE_API_KEY"):
        raise ValueError("Set OPENAI_API_KEY and GOOGLE_API_KEY in this terminal first.")

    cases_path = args.cases.resolve()
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_dir = output_path.parent / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    # Keep this evaluation's score/checkpoint/upload artifacts isolated from
    # the normal development data directory.
    os.environ["PROJECT_DB_FILE"] = str(runtime_dir / "project_db.json")
    os.environ["LANGGRAPH_CHECKPOINT_DB"] = str(runtime_dir / "langgraph.sqlite")
    os.environ["UPLOAD_DIR"] = str(runtime_dir / "uploads")

    from app import run_analysis_logic, run_analysis_logic_legacy

    cases = load_cases(cases_path)
    with output_path.open("w", encoding="utf-8") as out:
        for case in cases:
            question = case.get("question") or case["prompt"]
            image_path = case.get("image_path")
            if image_path:
                resolved_image = (cases_path.parent / image_path).resolve()
                image_bytes = resolved_image.read_bytes()
                input_mode = "labeled_image"
            else:
                image_bytes = make_text_image(case["prompt"])
                input_mode = "synthetic_text_image"

            for variant, function in (
                ("legacy", run_analysis_logic_legacy),
                ("langgraph", run_analysis_logic),
            ):
                started = time.perf_counter()
                response = function(
                    f"eval-{variant}-{case['id']}",
                    io.BytesIO(image_bytes),
                    question,
                )
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                process = response.get("process", [])
                calculator_calls = []
                for event in process:
                    if event.get("step") == "MCP 도구 실행":
                        try:
                            payload = json.loads(event.get("content", "{}"))
                        except json.JSONDecodeError:
                            payload = {}
                        calculator_calls.append(payload)
                observation = {
                    "id": case["id"],
                    "variant": variant,
                    "input_mode": input_mode,
                    "final_answer": response.get("final_answer", ""),
                    "calculator_calls": calculator_calls,
                    # This is the verdict on the workflow's generated answer.
                    # The fixed verifier_probe is a separate evaluation task.
                    "workflow_verifier_verdict": verifier_label(process, variant),
                    "api_response": response,
                    "duration_ms": duration_ms,
                    "steps": [{"name": "request_total", "duration_ms": duration_ms, "failed": False}],
                    "run_config": {
                        "openai_model": os.environ.get("OPENAI_MODEL_NAME", "gpt-4o"),
                        "gemini_model": os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-pro"),
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    },
                }
                out.write(json.dumps(observation, ensure_ascii=False) + "\n")
                out.flush()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.jsonl"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("observations.live.jsonl"))
    args = parser.parse_args()
    try:
        return run(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"live evaluation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
