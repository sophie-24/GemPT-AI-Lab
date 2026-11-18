# Local Kubernetes MVP

These manifests target an existing local Kubernetes cluster. They do not install or configure a cluster. The current preflight had no kubectl context selected, so these resources are prepared only; nothing has been applied or observed in Kubernetes.

## Contract and persistence

- Namespace: `gempt`.
- API: one replica, internal Service `api:5000`, exposed locally with port-forward only.
- MCP: Service `mcp-tools:8000`, Streamable HTTP endpoint `/mcp`; it is cluster-internal.
- The API reads `MCP_SERVER_URL=http://mcp-tools:8000/mcp` and `PROJECT_DB_FILE=/data/project_db.json` from a ConfigMap.
- A 1 GiB `ReadWriteOnce` PVC is mounted at `/data`. Keep the API at one replica because score updates use a local JSON file. PVC retention depends on the local cluster's storage provisioner and the PVC lifecycle.
- API key values are not stored in this repository. Supply them in the `gempt-api-keys` Secret. The manifest permits the Secret and individual keys to be absent, but LLM-backed solving then cannot authenticate.

## Build and load images

Build from the repository root:

```powershell
docker build -t gempt-api:dev -f backend/Dockerfile .
docker build -t gempt-mcp-tools:dev -f backend/mcp_server/Dockerfile .
```

Use the image-loading command for the local cluster already in use. For kind, for example:

```powershell
kind load docker-image gempt-api:dev
kind load docker-image gempt-mcp-tools:dev
```

For Minikube, build into its configured Docker daemon or use `minikube image load`. Do not install a cluster as part of this MVP. `imagePullPolicy: IfNotPresent` lets the kubelet use locally loaded images; both image names must be available to the selected cluster.

## Apply and verify

Create the Secret without putting values in a committed manifest (omit a key if that service is not configured):

```powershell
kubectl create namespace gempt
kubectl -n gempt create secret generic gempt-api-keys `
  --from-literal=OPENAI_API_KEY=$env:OPENAI_API_KEY `
  --from-literal=GOOGLE_API_KEY=$env:GOOGLE_API_KEY `
  --from-literal=SERPAPI_API_KEY=$env:SERPAPI_API_KEY
kubectl apply -f deploy/k8s/mvp.yaml
kubectl -n gempt rollout status deployment/mcp-tools
kubectl -n gempt rollout status deployment/api
kubectl -n gempt get deployments,pods,services,pvc
```

If the namespace or Secret already exists, create/apply it once rather than repeating those creation commands. Check readiness and service endpoints before forwarding:

```powershell
kubectl -n gempt get pods -o wide
kubectl -n gempt describe pod -l app=api
kubectl -n gempt logs deployment/mcp-tools
kubectl -n gempt logs deployment/api
kubectl -n gempt port-forward service/api 5000:5000
```

In another terminal, check `http://127.0.0.1:5000/healthz`. Submit an image to `/api/solve` with the configured LLM credentials to verify calculator use through the API and inspect both deployment logs for the observed tool call. A healthy pod alone does not prove end-to-end MCP invocation.

## Cleanup

```powershell
kubectl delete namespace gempt
```

Deleting the namespace also deletes its PVC claim and Secret. Whether the underlying local volume data is retained depends on the StorageClass reclaim policy; preserve/export data before cleanup if needed.
