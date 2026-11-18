"""Typed state contract for the GemPT LangGraph workflow.

Only references and text are persisted in graph state. Image bytes, PIL images,
and base64 encodings are loaded transiently by workflow nodes and never enter
this mapping (or a checkpointer).
"""

from __future__ import annotations

from typing import Any, TypedDict


class ProcessEvent(TypedDict):
    model: str
    content: str
    step: str


class GemPTState(TypedDict, total=False):
    # Required invocation input.
    run_id: str
    project_id: str
    question: str
    image_ref: str
    process: list[ProcessEvent]
    debate_round: int
    tool_calls_used: int

    # Workflow data. These values are safe to persist/checkpoint as text/JSON.
    subject: str
    search_queries: list[str]
    knowledge_package: str
    initial_answer: str
    current_answer: str
    verifier_result: dict[str, Any]
    critique: str
    defense: str
    corrected_answer: str
    winner: str
    final_answer: str
    scores: dict[str, int]
    solver_history: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]]
    defense_pending: bool
    failure_reason: str
    is_correct: bool
