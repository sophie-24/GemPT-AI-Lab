# GemPT-AI-Lab Agent Instructions

## Project and source of truth

GemPT-AI-Lab starts from a Flask application that serves image-based questions and runs a GPT/Gemini verification loop. Read README.md and docs/api_spec.md before changing behavior. The current API contract is POST /api/solve and GET /api/scores/<project_id>.

The current application is Flask. Do not migrate to FastAPI as part of the planned MVP. README.md distinguishes implemented behavior from the planned upgrade; preserve that distinction.

For the two-day implementation scope, follow docs/agent-workflow.md. MCP integration and Kubernetes deployment are core MVP outcomes. Docker Compose is the local integration path that supports them; do not defer MCP or Kubernetes as optional stretch work.

## Coordination rules for the MCP/Kubernetes MVP

When the user asks to execute the two-day plan:

1. Perform a read-only preflight: inspect the branch, working tree, application entry point, requirements, existing API contract, Docker availability, kubectl availability, and current local Kubernetes context.
2. Report pre-existing changes and blockers before editing. Do not overwrite unrelated work.
3. Coordinate as a root agent and delegate three bounded workstreams: MCP server/client, Docker Compose, and Kubernetes manifests. Keep shared contracts and integration in the root agent.
4. Use the file ownership boundaries in docs/agent-workflow.md. Subagents share the repository workspace; do not let multiple agents edit the same files.
5. Keep the implementation local. Do not provision public cloud resources or install/change a Kubernetes cluster without user approval.
6. Preserve /api/solve response compatibility: winner, final_answer, scores, process.
7. Keep the API at one replica while project scores use a local JSON file. Make persistence behavior explicit.
8. Keep API keys out of source, image layers, committed manifests, and logs.
9. Report what was implemented separately from what remains planned. Do not claim deployment or successful MCP execution without observed evidence.

## Shared service contract

The root agent coordinates these defaults before implementation:

- Flask API: port 5000; health endpoint GET /healthz.
- MCP Server: Streamable HTTP transport, port 8000, endpoint /mcp; health endpoint GET /healthz.
- Compose service names: api and mcp-tools.
- API-to-MCP address inside Compose/Kubernetes: http://mcp-tools:8000/mcp, configured through MCP_SERVER_URL.
- Local development images: gempt-api:dev and gempt-mcp-tools:dev.
- Kubernetes namespace: gempt. API and MCP Server each have a Service; only the API is exposed for local access.
- Calculator tool name: calculator; input object has expression (string). Reject unsupported syntax and return structured errors.
- API keys: OPENAI_API_KEY, GOOGLE_API_KEY, SERPAPI_API_KEY. Inject via local environment or Kubernetes Secret.
- Score file path: PROJECT_DB_FILE, mounted at /data/project_db.json; use a local Compose volume and a Kubernetes PVC for the demo.

If repository constraints make a default incompatible, the root agent documents and agrees on a replacement before implementation.

## Ownership boundaries

- Root/integrator: backend/app.py, backend/requirements.txt, API compatibility, root documentation, integration, and final review.
- MCP specialist: backend/mcp_server/**, backend/mcp_client.py, backend/tools/**. It reports dependency requirements to the root agent and does not edit app.py, requirements.txt, Docker files, or Kubernetes manifests.
- Container specialist: backend/Dockerfile, backend/mcp_server/Dockerfile, docker-compose.yml, .dockerignore. It does not edit application code or Kubernetes manifests.
- Kubernetes specialist: deploy/k8s/** and docs/kubernetes.md. It does not edit application code, Docker files, compose, or README.md.

Subagents do not commit or push. The root agent owns integration and any Git operation explicitly requested by the user.