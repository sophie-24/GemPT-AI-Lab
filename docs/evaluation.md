# Run persistence and offline evaluation

This document describes LangGraph run persistence and the offline evaluator.
The Flask solve path invokes LangGraph. The included observations are synthetic
plumbing examples; they are not live model measurements.

## Checkpoint lifecycle

`backend/checkpoint_store.py` provides a synchronous SQLite saver factory:

```python
from checkpoint_store import checkpoint_config, open_checkpointer

run_id = "a-unique-run-id"  # Generate once for this request/execution.
with open_checkpointer() as checkpoint:
    runnable_graph = graph_builder.compile(
        checkpointer=checkpoint.checkpointer,
    )
    result = runnable_graph.invoke(
        state,
        config=checkpoint_config(run_id),
    )
```

The context manager closes the per-invocation SQLite connection after `invoke`,
including when graph execution raises. `close_checkpointer(handle)` is
available for explicit lifecycle management. `checkpoint_config` uses
`run_id` as `configurable.thread_id`; do not substitute `project_id`, which
continues to identify score aggregation only.

The SQLite path comes from `LANGGRAPH_CHECKPOINT_DB` and defaults to
`/data/langgraph.sqlite`. The helper creates the parent directory and enables
WAL plus a 30-second busy timeout. SQLite is a local/lightweight saver. The
Kubernetes demo therefore remains at one API replica with an RWO PVC. This
configuration does not establish safe multi-replica or multi-node checkpoint
storage; a shared database service is a separate future design. The score file
at `PROJECT_DB_FILE` remains its own JSON persistence mechanism and is not
replaced by the checkpoint DB.

The graph state should contain `image_ref`, never raw image bytes. The
`backend/image_store.py` interface is:

```python
from image_store import delete_image, open_image, save_image

image_ref = save_image(run_id, image_bytes)  # "gempt-upload://<run_id>"
image_bytes_for_node = open_image(image_ref)
delete_image(run_id)
```

Uploads use `UPLOAD_DIR`, default `/data/uploads`, and a validated run ID as the
storage filename; client filenames are not used. Writes are atomic. A
maintenance task may call `cleanup_expired(ttl_seconds)` to remove aged files.
No automatic deletion is coupled to a graph error: a failed execution may be
resumed from its checkpoint, so retain the upload for the chosen retry window
and remove it with the checkpoint when the run expires. The Kubernetes volume
must mount the same RWO claim at `/data` so both paths persist across pod
restarts. Do not increase API replicas while using this local SQLite/file
arrangement.

The recommended Python packages for integration are `langgraph` and
`langgraph-checkpoint-sqlite`. The official SQLite saver is intended for
lightweight synchronous use. Pin compatible versions when the graph dependency
set is integrated; this interface has not been run against the repository's
installed environment. See the [official SQLite checkpoint package README](https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-sqlite#readme)
and [SqliteSaver reference](https://reference.langchain.com/python/langgraph.checkpoint.sqlite/SqliteSaver).

## Evaluation input format

`evals/cases.jsonl` contains fixed text-only reasoning cases. Each row includes:

- `id`: stable case identifier
- `problem_type`: category such as arithmetic or algebra
- `modality`: currently `text_only`; these cases do not measure image reading
- `prompt`: text-only problem statement (no real user image)
- `expected_answer`: reference answer
- `grading_criteria`: human-readable rubric for explanation/partial credit
- `calculator_expected`: benchmark policy label for whether calculator use is expected
- `verifier_probe`: fixed candidate solution to present to the verifier
- `expected_verifier_verdict`: expected `correct`, `correction_needed`, or
  `uncertain` verdict for that probe

The evaluator accepts recorded run observations in a separate JSONL file. Each
row is keyed by case `id` and should include `variant` (`legacy` or `langgraph`)
so the report separates the implementations. Rows may include `final_answer`, `calculator_calls`
(list), `verifier_verdict`, `api_response`, `graph_invocations`, and `steps`.
Each step may contain `name`, `duration_ms`, and `failed`. `run_live_eval.py`
stores the end-to-end workflow's verifier label separately as
`workflow_verifier_verdict`. Populate `verifier_verdict` only when the recorded
verdict belongs to the fixed `verifier_probe`; otherwise verifier accuracy
would compare different answers. This captures
answer/tool/verifier/response metrics, graph call counts, and per-stage latency
and failure counts. The runner checks API response structure against the
existing `winner`, `final_answer`, `scores`, and `process` contract. It computes
normalized exact-match accuracy against the answer section of GemPT's formatted
response; nuanced explanations still require review against each case's rubric.

Example observation row:

```json
{"id":"arith-001","variant":"langgraph","final_answer":"[1] 최종 답안\n56\n\n[2] 계산 근거 요약\n...","calculator_calls":[{"name":"calculator","success":true}],"verifier_verdict":"correct","steps":[{"name":"solver","duration_ms":820,"failed":false}]}
```

For a fair comparison, record both variants with the same case IDs, provider
model names, prompt versions, image/question inputs, and runtime configuration.
The evaluator keys observations by `(variant, case_id)`, so a case may appear
once for `legacy` and once for `langgraph`. It also reports missing case IDs
separately for each variant. Report numerator and denominator with every
percentage. The current schema accepts one observation per case and variant;
repeated stochastic runs require adding a repetition field before aggregation.
The current legacy and LangGraph paths also differ in prompts, verifier output
format, and some debate decisions. Their comparison measures the whole workflow
change; it cannot attribute a result change to LangGraph alone. To isolate the
framework effect, hold prompts, model calls, tool policy, and termination policy
constant and change only the orchestration implementation.

Run cases-only validation without keys or network access:

```powershell
python evals/run_eval.py
```

Run the paired live comparison after installing requirements, setting provider
keys in the local terminal, and starting the MCP service:

```powershell
docker compose build
docker compose up -d
docker compose exec -T api python /app/evals/run_live_eval.py --cases /app/evals/cases.jsonl --output /data/observations.live.jsonl
docker compose exec -T api python /app/evals/run_eval.py --cases /app/evals/cases.jsonl --observations /data/observations.live.jsonl
docker compose cp api:/data/observations.live.jsonl evals/observations.live.jsonl
```

The API container can reach the Compose MCP service, and `evals/` is mounted
read-only into it. The live runner calls both implementations for every case
and makes real provider requests. Rows without `image_path` use an automatically rendered
text image while also sending the prompt as text. That is useful for checking
the upload and workflow path, but it is not a valid measure of visual
recognition. Add labeled `image_path` values to cases for image evaluation.
The runner isolates score, checkpoint, and upload files under the output
directory's `runtime` subdirectory; it does not alter the normal project score
file.

To exercise metric aggregation against the included **synthetic harness
fixture** (not model output or a performance result):

```powershell
python evals/run_eval.py --observations evals/fixtures/offline_observations.jsonl
```

For a live evaluation, `run_live_eval.py` calls the legacy and LangGraph
functions and writes actual outputs in the observation format. Store the case set and
observations with the model/prompt versions and run configuration. Do not
report accuracy from model self-evaluation alone: compare final answers with
the supplied reference and rubric, and review verifier disagreements against
that reference. Report unanswered cases and failures in the denominator. The
offline fixture only demonstrates how metrics are aggregated; it cannot show
that a model, graph, MCP tool, or verifier ran successfully.

## Metrics and limits

The JSON report includes:

- exact answer accuracy and observed denominator
- calculator usage accuracy, plus precision/recall for calculator-needed cases
- verifier expected-verdict accuracy and misjudgment count
- structured API response validity
- total graph invocations
- per-step observed durations, mean/total milliseconds, and failures
- per-variant answer/tool/verifier metrics, recorded step latency, and failures

The runner does not call providers, grade natural-language rubric criteria,
infer missing observations, or claim model quality. Cases that lack recorded
observations stay visible as unobserved. The fixture only demonstrates metric
aggregation. These text-only cases measure reasoning and tool policy, not image
perception; that requires a separately labeled image set. The
`run_analysis_logic_legacy` function is retained as the baseline entry point.
Record both implementations with identical case IDs and run configuration
before comparing them. A live model evaluation requires API credentials in the
local environment.
