"""Prompts, schemas, and small pure helpers for the GemPT workflow."""

from __future__ import annotations

import json
from typing import Any


PROMPT_SUBJECT_CLASSIFIER = """
당신은 전문적인 학문 분야 분류기입니다. 사용자의 이미지와 질문을 분석하여 특정 학문 분야를 식별하세요.
이미지의 기호, 다이어그램, 텍스트와 사용자의 질문을 분석하고 가장 관련성이 높은 학문 분야의 이름만 출력하세요.
""".strip()

PROMPT_KNOWLEDGE_CRAWLER_QUERIES = """
당신은 연구 보조원입니다. 식별된 주제를 바탕으로 배경 지식을 수집할 Google 검색어 3-4개를 생성하세요.
주제: {subject}
핵심 정의, 공식, 기본 정리에 대한 검색어를 한 줄에 하나씩 출력하세요.
""".strip()

PROMPT_KNOWLEDGE_PACKAGE_GENERATOR = """
검색 결과를 바탕으로 단일 JSON 지식 패키지를 한국어로 작성하세요.
주제: {subject}
검색 결과:
---
{search_results}
---
필드는 field, symbols, formulas, definitions, examples, context_text입니다.
""".strip()

PROMPT_SOLVER_INIT = """
당신은 전문 교수입니다. 제공된 지식을 활용해 문제를 한국어로 명확하고 단계적으로 풀이하세요.
이미지는 문제 내용에만 사용하세요. 신뢰할 수 있는 정리나 공식의 출처를 인용하세요.
수학 표기는 인라인 \\( ... \\), 블록 $$ ... $$를 사용하고 \\[ ... \\]는 사용하지 마세요.
명확한 최종 답변으로 마무리하세요.

사전 지식 패키지:
---
{knowledge_package}
---
필요하면 허용된 calculator 도구를 사용해 산술을 확인하세요.
""".strip()

PROMPT_VERIFIER = """
당신은 엄격한 학술 검증자입니다. 이미지와 질문을 바탕으로 해결책의 논리와 계산을 검토하세요.
JSON 응답 스키마에 맞춰 verdict를 correct, correction_needed, uncertain 중 하나로 정하고,
근거(critique)와 검증한 답(answer)을 제공하세요. 사소한 표현 차이는 오류로 보지 마세요.
""".strip()

PROMPT_SOLVER_DEFENSE = """
Gemini 검증자가 다음과 같이 지적했습니다:
{critique}

비판을 검토하고 한국어로 답변하세요. 비판이 맞으면 수정 풀이를, 틀리면 근거를 들어 방어하세요.
필요하면 calculator 도구를 사용하세요.
""".strip()

PROMPT_VERIFIER_REBUTTAL = """
GPT가 다음과 같이 방어했습니다:
{defense}

이미지와 원래 질문을 다시 확인하고 JSON 응답 스키마에 맞춰 평가하세요.
verdict는 correct, correction_needed, uncertain 중 하나입니다. correction_needed이면 올바른 답을 answer에 작성하세요.
""".strip()

PROMPT_DEBATE_SUMMARY = """
다음 풀이를 한국어로 요약하고 JSON으로 응답하세요.
[GPT 초기 답변]
{initial_answer}
[Gemini 검증]
{critique}
최상위 필드 calculation_summary, gpt_errors, gemini_verification을 포함하세요.
""".strip()

PROMPT_DEBATE_CONCLUSION = """
다음 AI 토론 결론을 2-3개의 완결된 한국어 문장으로 요약하세요.
토론 승자: {winner}
최종 결론: {final_answer}
""".strip()


VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["correct", "correction_needed", "uncertain"]},
        "critique": {"type": "string"},
        "answer": {"type": "string"},
    },
    "required": ["verdict", "critique", "answer"],
    "additionalProperties": False,
}

CALCULATOR_TOOLS = [{
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Evaluate a simple arithmetic expression when an exact calculation is useful.",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "Arithmetic expression"}},
            "required": ["expression"],
            "additionalProperties": False,
        },
    },
}]


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse provider JSON, allowing a surrounding Markdown code fence."""
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[-1]
        if value.endswith("```"):
            value = value[:-3].strip()
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result


def normalize_verdict(value: Any) -> dict[str, str]:
    """Validate structured verifier output; malformed output becomes uncertain."""
    if not isinstance(value, dict):
        return {"verdict": "uncertain", "critique": "검증 결과 형식이 올바르지 않습니다.", "answer": ""}
    verdict = value.get("verdict")
    if verdict not in {"correct", "correction_needed", "uncertain"}:
        verdict = "uncertain"
    return {
        "verdict": verdict,
        "critique": value.get("critique") if isinstance(value.get("critique"), str) else "",
        "answer": value.get("answer") if isinstance(value.get("answer"), str) else "",
    }


def initial_scores(value: Any) -> dict[str, int]:
    """Return a normalized copy of the legacy project score structure."""
    if not isinstance(value, dict):
        value = {}
    return {name: int(value.get(name, 0)) for name in ("GPT", "Gemini")}


def score_delta(winner: str, debate_round: int) -> dict[str, int]:
    """Preserve the existing geometric score policy for resolved debates."""
    loop = max(1, int(debate_round))
    if winner == "GPT":
        return {"GPT": (2 ** (2 * loop)) - 1, "Gemini": 0}
    if winner == "Gemini":
        return {"GPT": 0, "Gemini": (2 ** (2 * loop - 1)) - 1}
    return {"GPT": 0, "Gemini": 0}


def process_event(model: str, content: str, step: str) -> dict[str, str]:
    """Create the legacy-compatible process event shape."""
    return {"model": model, "content": str(content), "step": step}
