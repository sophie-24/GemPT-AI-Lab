# GemPT-AI-Lab: Codex Agent Workflow

This is the reusable task setup for the two-day MCP and Kubernetes MVP. Codex reads the repository-level AGENTS.md as persistent guidance. You do not need to create or configure separate permanent agent profiles: open this repository in Codex and start one task with the activation prompt below. The main agent coordinates the specialists.

## Start the task

Open the folder C:\Users\20231\gempt-AI-Lab in Codex, start a new task, and paste:

> Read AGENTS.md, README.md, docs/api_spec.md, and docs/agent-workflow.md. Execute the two-day MCP and Kubernetes MVP in this repository. First inspect the working tree and local Docker/Kubernetes tools without changing anything. Report any existing modifications or blockers. Then create a working branch named codex/mcp-k8s-2day and coordinate exactly three subagents using the ownership and task briefs below: MCP Server/client, Docker Compose, and Kubernetes. You own the shared contract, backend/app.py integration, dependencies, API compatibility, final integration, and documentation review. Keep MCP and Kubernetes as core deliverables. Use only a local Kubernetes cluster; do not install or modify cluster software without asking me. Do not push or deploy to a public service. At the end, show the end-to-end path from /api/solve through the MCP calculator to the final response, and report which Kubernetes resources and logs you actually observed.

The agent has the repository context and responsibilities in AGENTS.md. It should share the agreed service contract with the specialists before they edit files. If one specialist’s work depends on an interface that is not yet defined, the main agent resolves that interface first.

## Shared contract

Use the defaults in AGENTS.md unless the repository preflight reveals a concrete incompatibility:

- Flask API: port 5000; GET /healthz.
- MCP Server: Streamable HTTP, port 8000, endpoint /mcp; GET /healthz.
- Compose services: api and mcp-tools.
- MCP_SERVER_URL=http://mcp-tools:8000/mcp.
- Images: gempt-api:dev and gempt-mcp-tools:dev.
- Kubernetes namespace: gempt; API replica count 1 because scores are stored in a local JSON file.
- Tool: calculator(expression: string), with safe parsing, allow-listed syntax, bounded execution, and structured errors.
- Score persistence: PROJECT_DB_FILE=/data/project_db.json, backed by a Compose volume and a Kubernetes PVC.
- API keys: OPENAI_API_KEY, GOOGLE_API_KEY, SERPAPI_API_KEY, injected through environment variables or Kubernetes Secret.

The MCP Client belongs in the Flask backend. The LLM requests a function/tool call; the backend validates it and invokes the MCP Server. Do not describe this as the model connecting directly to MCP.

## Specialist 1: MCP Server and Client

> Read AGENTS.md, README.md, docs/api_spec.md, and the shared contract in docs/agent-workflow.md. Implement the calculator MCP Server and a reusable MCP Client adapter. Own only backend/mcp_server/**, backend/mcp_client.py, and backend/tools/**. Use the current supported Python MCP SDK and Streamable HTTP transport. Expose calculator(expression: string), validate arguments, restrict expression syntax and complexity, apply an execution timeout, and return structured success/error results. Add a health endpoint at /healthz. Do not edit backend/app.py, backend/requirements.txt, Docker files, Kubernetes files, or README.md. Report required dependency names/versions, exact server command, endpoint behavior, and any unresolved compatibility issue to the root agent.

## Specialist 2: Docker and Compose

> Read AGENTS.md, README.md, docs/api_spec.md, and the shared contract in docs/agent-workflow.md. Configure reproducible containers for the existing Flask API and the MCP Server. Own only backend/Dockerfile, backend/mcp_server/Dockerfile, docker-compose.yml, and .dockerignore. Use image names gempt-api:dev and gempt-mcp-tools:dev, Compose service names api and mcp-tools, and MCP_SERVER_URL=http://mcp-tools:8000/mcp. Keep secrets out of image layers and committed files. Persist /data/project_db.json through a named volume. Do not edit application code, requirements, Kubernetes files, or README.md. Do not assume paths or commands: verify them against the implementation once the root agent shares the interface. Report build/run commands and remaining assumptions.

## Specialist 3: Kubernetes

> Read AGENTS.md, README.md, docs/api_spec.md, and the shared contract in docs/agent-workflow.md. Create local-learning Kubernetes resources for the Flask API and MCP Server. Own only deploy/k8s/** and docs/kubernetes.md. Use namespace gempt, separate Deployments and Services, one API replica, image names gempt-api:dev and gempt-mcp-tools:dev, MCP_SERVER_URL=http://mcp-tools:8000/mcp, health probes, Secret/ConfigMap references, and a PVC mounted at /data for the JSON score file. Expose only the API for local access. Document image loading for the available local cluster, apply/port-forward/log commands, and cleanup. First inspect whether a local cluster already exists; do not install or reconfigure one. Do not edit application, Docker, Compose, or README files. Clearly distinguish manifests prepared from resources actually deployed and observed.

## Two-day sequence

### Day 1: MCP path and local containers

- Freeze shared contracts and inspect current Flask request/response behavior.
- Implement the MCP Server and calculator tool.
- Add the MCP Client adapter and integrate function calls in the Flask request path.
- Build API/MCP images and run both services with Docker Compose.
- Confirm the existing /api/solve response fields remain available.

### Day 2: Kubernetes deployment and demonstration

- Build or load the two local images into the available local cluster.
- Apply resources in namespace gempt.
- Confirm pod readiness, API-to-MCP service connectivity, calculator invocation, final response, and logs.
- Persist the score file through the PVC.
- Update README/API/deployment docs only after observing actual behavior.

If the machine has no Docker or local Kubernetes cluster, stop before installation or host configuration changes. Complete safe repository artifacts and provide the exact setup steps that need the user.

## Completion report

The root agent reports:

1. Files changed by each workstream.
2. Whether MCP calculator invocation was observed end to end.
3. Compose build/run outcome.
4. Kubernetes context, deployed resources, pod readiness, and logs actually observed.
5. API compatibility and score persistence behavior.
6. Known limitations and any step blocked by missing local tooling.