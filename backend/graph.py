"""LangGraph implementation of the GemPT solve, verify, and MCP workflow."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from langgraph.graph import END, StateGraph

from graph_state import GemPTState
from model_clients import GeminiModelClient
from workflow_services import (
    CALCULATOR_TOOLS,
    PROMPT_DEBATE_CONCLUSION,
    PROMPT_DEBATE_SUMMARY,
    PROMPT_KNOWLEDGE_CRAWLER_QUERIES,
    PROMPT_KNOWLEDGE_PACKAGE_GENERATOR,
    PROMPT_SOLVER_DEFENSE,
    PROMPT_SOLVER_INIT,
    PROMPT_SUBJECT_CLASSIFIER,
    PROMPT_VERIFIER,
    PROMPT_VERIFIER_REBUTTAL,
    VERDICT_SCHEMA,
    initial_scores,
    normalize_verdict,
    parse_json_object,
    process_event,
    score_delta,
)


class MCPClientLike(Protocol):
    def call_tool(self, name: str, arguments: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]: ...


@dataclass
class GraphDependencies:
    """Injected I/O dependencies for one compiled workflow.

    ``image_loader`` must return a PIL image or raw image bytes for ``image_ref``.
    Score functions are grouped by project_id; run_id is never used as a score key.
    ``mcp_client_factory`` defaults to the repository MCPClient.from_env adapter.
    """

    openai_client: Any
    gemini_client: GeminiModelClient
    image_loader: Callable[[str], Any]
    search_fn: Callable[[str], str]
    load_scores: Callable[[str], dict[str, int]]
    save_scores: Callable[[str, dict[str, int]], None]
    mcp_client_factory: Callable[[], MCPClientLike] | None = None
    max_tool_calls: int = 3
    max_debate_rounds: int = 5


def _image_for_gemini(deps: GraphDependencies, image_ref: str) -> Any:
    image = deps.image_loader(image_ref)
    if isinstance(image, (bytes, bytearray)):
        from io import BytesIO
        from PIL import Image

        with Image.open(BytesIO(bytes(image))) as opened:
            return opened.copy()
    return image


def _image_data_url(deps: GraphDependencies, image_ref: str) -> str:
    image = deps.image_loader(image_ref)
    if isinstance(image, (bytes, bytearray)):
        raw = bytes(image)
        mime = "image/png"
    elif hasattr(image, "save"):
        from io import BytesIO

        stream = BytesIO()
        image.save(stream, format="PNG")
        raw = stream.getvalue()
        mime = "image/png"
    else:
        raise TypeError("image_loader must return a PIL image or image bytes")
    # The image payload is used only in this transient provider request and is
    # never returned as a state update.
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _openai_response(deps: GraphDependencies, messages: list[dict[str, Any]], *, tools: bool) -> Any:
    kwargs: dict[str, Any] = {"model": "gpt-4o", "messages": messages}
    if tools:
        kwargs.update(tools=CALCULATOR_TOOLS, tool_choice="auto")
    return deps.openai_client.chat.completions.create(**kwargs)


def _plain_message(message: Any) -> dict[str, Any]:
    dump = message.model_dump(exclude_none=True) if hasattr(message, "model_dump") else {}
    clean: dict[str, Any] = {"role": "assistant"}
    if isinstance(dump.get("content"), str):
        clean["content"] = dump["content"]
    calls = dump.get("tool_calls")
    if isinstance(calls, list):
        clean["tool_calls"] = calls
    return clean


def _history_messages(state: GemPTState, system_prompt: str, deps: GraphDependencies) -> list[dict[str, Any]]:
    history = list(state.get("solver_history", []))
    image_url = _image_data_url(deps, state["image_ref"])
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": state["question"]},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        },
    ]
    messages.extend(history)
    return messages


def build_gempt_graph(dependencies: GraphDependencies, *, checkpointer: Any = None):
    """Build a bounded GemPT graph with injected provider and storage clients.

    Example::

        deps = GraphDependencies(
            openai_client=OpenAI(), gemini_client=GeminiModelClient(),
            image_loader=load_image_ref, search_fn=perform_google_search,
            load_scores=load_project_scores, save_scores=save_project_scores,
        )
        graph = build_gempt_graph(deps)
        result = graph.invoke({"run_id": rid, "project_id": pid, "question": q,
                               "image_ref": ref, "process": [],
                               "debate_round": 0, "tool_calls_used": 0})

    ``run_id`` remains ordinary state data. This factory does not choose or
    rewrite a checkpointer's thread_id policy.
    """
    if dependencies.max_tool_calls < 0 or dependencies.max_debate_rounds < 0:
        raise ValueError("workflow limits cannot be negative")

    def append_event(state: GemPTState, model: str, content: str, step: str, **updates: Any) -> dict[str, Any]:
        events = list(state.get("process", []))
        events.append(process_event(model, content, step))
        return {**updates, "process": events}

    def classify_and_knowledge(state: GemPTState) -> dict[str, Any]:
        try:
            image = _image_for_gemini(dependencies, state["image_ref"])
            subject = dependencies.gemini_client.generate_text([PROMPT_SUBJECT_CLASSIFIER, state["question"], image]).strip()
            queries_text = dependencies.gemini_client.generate_text(PROMPT_KNOWLEDGE_CRAWLER_QUERIES.format(subject=subject))
            queries = [line.strip().lstrip("-• ") for line in queries_text.splitlines() if line.strip()][:4]
            search_results = []
            for query in queries:
                try:
                    search_results.append(f"'{query}' 검색 결과:\n{dependencies.search_fn(query)}")
                except Exception as exc:
                    search_results.append(f"'{query}' 검색 실패: {type(exc).__name__}")
            raw = "\n\n".join(search_results)
            package = dependencies.gemini_client.generate_text(
                PROMPT_KNOWLEDGE_PACKAGE_GENERATOR.format(subject=subject, search_results=raw)
            ).strip()
            # Require well-shaped JSON, but preserve readable fallback text if a
            # provider returns an invalid package.
            try:
                package = json.dumps(parse_json_object(package), ensure_ascii=False)
            except (ValueError, json.JSONDecodeError):
                pass
            updates = {"subject": subject, "search_queries": queries, "knowledge_package": package}
            event = append_event(state, "System", f"인식된 주제: {subject}", "주제 분류", **updates)
            event["process"].append(process_event("System", raw, "지식 수집"))
            event["process"].append(process_event("System", package, "지식 패키지 생성"))
            return event
        except Exception as exc:
            reason = f"분류/지식 수집 실패 ({type(exc).__name__})"
            return append_event(state, "System", reason, "워크플로 오류", failure_reason=reason,
                                winner="Draw (Timeout)", final_answer="문제 분석 중 서비스 오류가 발생했습니다.")

    def solve(state: GemPTState) -> dict[str, Any]:
        try:
            prompt = PROMPT_SOLVER_INIT.format(knowledge_package=state.get("knowledge_package", ""))
            response = _openai_response(
                dependencies,
                _history_messages(state, prompt, dependencies),
                tools=state.get("tool_calls_used", 0) < dependencies.max_tool_calls,
            )
            message = response.choices[0].message
            calls = getattr(message, "tool_calls", None) or []
            if calls:
                history = list(state.get("solver_history", []))
                history.append(_plain_message(message))
                pending = [{
                    "id": call.id,
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                } for call in calls]
                return {"solver_history": history, "pending_tool_calls": pending}
            answer = getattr(message, "content", None) or "계산 도구 호출 후 풀이가 완성되지 않았습니다."
            history = list(state.get("solver_history", []))
            history.append({"role": "assistant", "content": answer})
            return append_event(state, "GPT", answer, "초기 해결책", initial_answer=answer,
                                current_answer=answer, solver_history=history, pending_tool_calls=[])
        except Exception as exc:
            reason = f"GPT 풀이 실패 ({type(exc).__name__})"
            return append_event(state, "System", reason, "워크플로 오류", failure_reason=reason,
                                initial_answer="", current_answer="", winner="Draw (Timeout)",
                                final_answer="문제 풀이 중 서비스 오류가 발생했습니다.")

    def call_mcp_tools(state: GemPTState) -> dict[str, Any]:
        history = list(state.get("solver_history", []))
        events = list(state.get("process", []))
        used = int(state.get("tool_calls_used", 0))
        try:
            client = dependencies.mcp_client_factory() if dependencies.mcp_client_factory else _default_mcp_client()
        except Exception as exc:
            client = None
            client_init_error = type(exc).__name__
        else:
            client_init_error = ""

        for call in state.get("pending_tool_calls", []):
            name = call.get("name")
            raw_arguments = call.get("arguments", "")
            result: dict[str, Any]
            if used >= dependencies.max_tool_calls:
                result = {"ok": False, "error": {"code": "call_limit", "message": "Calculator call limit reached."}}
            else:
                used += 1
                try:
                    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                    if name != "calculator":
                        result = {"ok": False, "error": {"code": "tool_not_allowed", "message": "Tool is not allow-listed."}}
                    elif not isinstance(arguments, dict) or set(arguments) != {"expression"} or not isinstance(arguments.get("expression"), str):
                        result = {"ok": False, "error": {"code": "invalid_arguments", "message": "calculator requires exactly one string expression."}}
                    elif client is None:
                        result = {"ok": False, "error": {"code": "mcp_unavailable", "message": client_init_error}}
                    else:
                        # This is the only MCP invocation path. The repository
                        # client enforces the calculator allow-list and timeout.
                        result = client.call_tool("calculator", arguments, timeout=5.0)
                        if not isinstance(result, dict):
                            result = {"ok": False, "error": {"code": "invalid_tool_response", "message": "MCP returned a non-object result."}}
                except Exception as exc:
                    result = {"ok": False, "error": {"code": "client_error", "message": type(exc).__name__}}
            rendered = json.dumps(result, ensure_ascii=False)
            events.append(process_event("System", json.dumps({"tool": name, "result": result}, ensure_ascii=False), "MCP 도구 실행"))
            history.append({"role": "tool", "tool_call_id": str(call.get("id", "")), "content": rendered})

        return {"solver_history": history, "process": events, "tool_calls_used": used, "pending_tool_calls": []}

    def verify(state: GemPTState) -> dict[str, Any]:
        try:
            prompt = f"{PROMPT_VERIFIER}\n\n사용자 질문: {state['question']}\n\n해결책:\n{state.get('current_answer', '')}"
            raw = dependencies.gemini_client.generate_text(
                [prompt, _image_for_gemini(dependencies, state["image_ref"])],
                response_schema=VERDICT_SCHEMA,
            )
            verdict = normalize_verdict(parse_json_object(raw))
        except Exception as exc:
            verdict = {"verdict": "uncertain", "critique": f"구조화 검증 실패 ({type(exc).__name__})", "answer": ""}
        updates: dict[str, Any] = {"verifier_result": verdict}
        if state.get("debate_round", 0) == 0:
            if verdict["verdict"] == "correct":
                updates.update(winner="Draw (Agreement)", final_answer=state.get("current_answer", ""), is_correct=True)
            else:
                updates.update(critique=verdict["critique"], corrected_answer=verdict["answer"], is_correct=False)
        else:
            if verdict["verdict"] == "correct":
                updates.update(winner="GPT", final_answer=state.get("defense", ""), is_correct=True)
            elif verdict["verdict"] == "correction_needed":
                corrected = verdict["answer"] or state.get("corrected_answer", "")
                updates.update(winner="Gemini", final_answer=corrected, corrected_answer=corrected, is_correct=False)
            else:
                updates.update(critique=verdict["critique"], corrected_answer=verdict["answer"] or state.get("corrected_answer", ""), is_correct=False)
        return append_event(state, "Gemini", json.dumps(verdict, ensure_ascii=False),
                            "검증" if state.get("debate_round", 0) == 0 else f"라운드 {state.get('debate_round')} 재평가",
                            **updates)

    def defend(state: GemPTState) -> dict[str, Any]:
        next_round = int(state.get("debate_round", 0)) + 1
        try:
            prompt = PROMPT_SOLVER_DEFENSE.format(critique=state.get("critique", ""))
            response = _openai_response(dependencies, [
                {"role": "system", "content": prompt},
                {"role": "user", "content": state.get("current_answer", "")},
            ], tools=False)
            message = response.choices[0].message
            if getattr(message, "tool_calls", None):
                defense = "방어 응답에서 허용되지 않은 도구 호출이 반환되었습니다."
            else:
                defense = getattr(message, "content", None) or ""
        except Exception as exc:
            defense = f"GPT 방어 생성 실패 ({type(exc).__name__})"
        return append_event(state, "GPT", defense, f"라운드 {next_round} 방어",
                            debate_round=next_round, defense=defense, current_answer=defense,
                            defense_pending=False)

    def finalize(state: GemPTState) -> dict[str, Any]:
        winner = state.get("winner", "")
        answer = state.get("final_answer", "")
        if not answer:
            if winner == "Gemini" or (winner == "Draw (Timeout)" and state.get("corrected_answer")):
                answer = state.get("corrected_answer") or state.get("current_answer", "")
            else:
                answer = state.get("initial_answer") or state.get("current_answer", "") or "풀이를 완료하지 못했습니다."
        if not winner:
            winner = "Draw (Timeout)"
        try:
            scores = initial_scores(dependencies.load_scores(state["project_id"]))
        except Exception:
            scores = {"GPT": 0, "Gemini": 0}
        delta = score_delta(winner, int(state.get("debate_round", 0)))
        scores = {key: scores[key] + delta[key] for key in scores}
        try:
            dependencies.save_scores(state["project_id"], scores)
        except Exception as exc:
            event = process_event("System", f"점수 저장 실패 ({type(exc).__name__})", "점수 저장")
        else:
            event = process_event("System", json.dumps(scores, ensure_ascii=False), "점수 저장")

        # Keep the legacy multi-part answer presentation. Summary provider calls
        # are optional and failure cannot invalidate a completed solve.
        summary_data = {"calculation_summary": "토론 결과를 최종 답안에 반영했습니다.",
                        "gpt_errors": [], "gemini_verification": []}
        if state.get("critique"):
            try:
                summary_data.update(parse_json_object(dependencies.gemini_client.generate_text(
                    PROMPT_DEBATE_SUMMARY.format(initial_answer=state.get("initial_answer", ""), critique=state.get("critique", ""))
                )))
            except Exception:
                summary_data["gemini_verification"] = [state.get("critique", "검증 내용을 요약하지 못했습니다.")]
        try:
            conclusion = dependencies.gemini_client.generate_text(
                PROMPT_DEBATE_CONCLUSION.format(winner=winner, final_answer=answer)
            )
        except Exception:
            conclusion = "교차검증이 종료되었습니다. 상세 결과는 위 최종 답안과 실행 로그를 확인하세요."
        formatted = (
            f"[1] 최종 답안\n{answer}\n\n"
            f"[2] 계산 근거 요약\n{summary_data.get('calculation_summary', '')}\n\n"
            f"[3] GPT 초기 답변의 오류 포인트\n- {'; '.join(summary_data.get('gpt_errors', [])) or '추출된 항목이 없습니다.'}\n\n"
            f"[4] Gemini의 검증 근거\n- {'; '.join(summary_data.get('gemini_verification', [])) or '추가 항목이 없습니다.'}\n\n"
            f"[5] 교차검증 결론 요약\n{conclusion}"
        )
        events = list(state.get("process", []))
        events.append(event)
        updates = {"winner": winner, "final_answer": formatted, "scores": scores, "process": events}
        return updates

    def after_solve(state: GemPTState) -> str:
        if state.get("failure_reason"):
            return "finalize"
        if state.get("pending_tool_calls"):
            return "mcp_tools"
        if state.get("initial_answer"):
            return "verify"
        return "finalize"

    def after_tools(state: GemPTState) -> str:
        return "solve"

    def after_verify(state: GemPTState) -> str:
        if state.get("winner"):
            return "finalize"
        if int(state.get("debate_round", 0)) >= dependencies.max_debate_rounds:
            return "timeout"
        return "defend"

    def timeout(state: GemPTState) -> dict[str, Any]:
        return append_event(state, "System", "최대 토론 횟수에 도달했습니다.", "토론 종료",
                            winner="Draw (Timeout)", final_answer=state.get("corrected_answer") or state.get("initial_answer", ""))

    graph = StateGraph(GemPTState)
    graph.add_node("classify_and_knowledge", classify_and_knowledge)
    graph.add_node("solve", solve)
    graph.add_node("mcp_tools", call_mcp_tools)
    graph.add_node("verify", verify)
    graph.add_node("defend", defend)
    graph.add_node("finalize", finalize)
    graph.add_node("timeout", timeout)
    graph.set_entry_point("classify_and_knowledge")
    graph.add_conditional_edges("classify_and_knowledge", lambda s: "finalize" if s.get("failure_reason") else "solve",
                               {"finalize": "finalize", "solve": "solve"})
    graph.add_conditional_edges("solve", after_solve, {"mcp_tools": "mcp_tools", "verify": "verify", "finalize": "finalize"})
    graph.add_conditional_edges("mcp_tools", after_tools, {"defend": "defend", "solve": "solve"})
    graph.add_conditional_edges("verify", after_verify, {"finalize": "finalize", "defend": "defend", "timeout": "timeout"})
    graph.add_edge("defend", "verify")
    graph.add_edge("timeout", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def _default_mcp_client() -> MCPClientLike:
    from mcp_client import MCPClient

    return MCPClient.from_env()
