# 조건부 Agent 검증 실행서

이 문서는 `sophie-24` 브랜치의 조건부 검색·calculator 흐름을 로컬에서 확인하고 평가하는 절차입니다. PowerShell 명령을 기준으로 합니다. 실행 시 실제 OpenAI·Gemini·SerpAPI 요청과 비용이 발생할 수 있습니다.

## 0. 현재 평가 코드가 할 수 있는 것과 없는 것

현재 `evals/run_live_eval.py`는 각 case에 대해 `legacy`와 `langgraph`를 실제 실행하고 요청 전체 지연, 최종 답, calculator MCP 이벤트, planner의 검색·계산기 선택을 저장합니다. `evals/run_eval.py`는 reference 답 정확도, planner 선택 정확도, 실제 calculator 사용, API 응답 구조 등을 집계합니다.

아래 항목은 별도 구현이나 데이터를 더해야 측정할 수 있습니다.

- **계산기 결과 반영/교정률:** 그래프는 calculator 호출을 마친 뒤 GPT가 최종 풀이를 만들며, 도구 호출 직전의 답안 초안은 현재 `process`에 기록하지 않습니다. 따라서 “도구 결과로 기존 답을 고친 비율”을 직접 계산하는 지표는 없습니다. 우선 같은 문제를 calculator 사용 허용/비허용으로 비교해 정답률 변화를 볼 수 있습니다. 진짜 교정률을 측정하려면 도구 전 초안과 도구 후 답을 별도 기록하거나, 잘못된 산술 초안을 주입하는 통제 평가를 추가해야 합니다.
- **비용:** live runner는 토큰 사용량이나 요청별 비용을 저장하지 않습니다. 정확한 비용 비교에는 OpenAI 및 Gemini 응답의 token usage 계측과 검색 호출 수를 관측 JSONL에 추가해야 합니다. 공급자별 현재 단가표를 사용하고 평가 날짜와 모델을 함께 기록하세요.
- **Verifier probe 정확도:** live runner는 workflow가 만든 답의 verdict를 `workflow_verifier_verdict`로 기록합니다. 고정 `verifier_probe`에 대한 독립 verdict는 실행하지 않으므로 `verifier_expected_verdict_accuracy`를 현재 결과만으로 주장하지 마세요.
- **단계별 latency:** 현재 live runner의 시간은 요청 전체입니다. planner/search/solver/MCP/verifier별 지연 비교를 하려면 노드별 시작·종료 시간을 수집해야 합니다.
- **이미지 인식 정확도:** text-only 사례는 이미지 읽기 성능을 측정하지 않습니다. 실제 이미지와 사람이 확인한 기준 답안이 필요합니다.

## 1. API 컨테이너 재빌드와 한 건의 `/api/solve`

저장소 루트에서 실행합니다.

```powershell
docker compose up -d --build --force-recreate api
docker compose ps
Invoke-RestMethod http://127.0.0.1:5000/healthz
```

`api`와 `mcp-tools`가 실행 중인지 확인하고 health 응답이 `status = ok`인지 봅니다. 새 코드가 들어간 API 이미지가 만들어졌는지 보려면 `docker compose images`도 확인합니다.

한 건의 이미지 요청 예시:

```powershell
$image = Get-Item .\assets\math-01.png
$form = @{
    image = $image
    question = "이미지의 문제를 풀어줘."
    project_id = "sophie-24-smoke"
}
$result = Invoke-RestMethod `
    -Uri "http://127.0.0.1:5000/api/solve" `
    -Method Post `
    -Form $form

$result.process | Format-Table step, content -Wrap
$result.winner
$result.final_answer
$result.scores | ConvertTo-Json
```

새 조건부 실행이면 `process`에 다음 중 관련 단계가 보여야 합니다.

- `Agent 실행 계획`: `problem_type`, `needs_search`, `calculator_required`가 담긴 JSON
- `검색 생략` 또는 `지식 수집`: plan이 선택한 분기
- `MCP 도구 실행`: calculator 호출 결과 `{ok, result}` 또는 구조화된 오류
- `계산 결과 반영` 또는 `검산 미완료`
- `검증`, `워크플로 오류`, `점수 저장`

계산기 필요 케이스라면 `calculator_required=true`인지, 실제 `MCP 도구 실행`에서 `ok=true`인지, 도구 결과 이후 GPT 풀이가 기록되는지 차례로 봅니다. 검색 불필요 케이스에서는 `검색 생략`이 있고 `지식 수집`은 없어야 합니다. `process` 첫 이벤트의 실행 ID와 해당 요청을 같은 키로 취급합니다.

Gemini가 429/503으로 실패해도 planner·검색·GPT·MCP 이벤트가 검증 전에 남을 수 있습니다. 검증 오류가 발생한 요청을 전체 Agent 경로 성공으로 세지 말고, `winner` 및 `final_answer`의 “미검증” 안내와 `워크플로 오류`를 같이 기록합니다.

최근 API 로그는 다음으로 확인합니다. 키나 `.env` 내용을 출력하지 마세요.

```powershell
docker compose logs --tail 100 api
docker compose logs --tail 100 mcp-tools
```

### 합격 기준

- `/healthz`는 성공 응답
- `/api/solve`는 기존 필드 `winner`, `final_answer`, `scores`, `process`를 모두 반환
- 문제 유형에 맞는 계획과 분기가 `process`에 표시
- 계산기 필요 case는 calculator 이벤트가 있고, 결과가 Solver 다음 응답보다 먼저 기록
- Gemini 오류는 토론 성공으로 오인하지 않고, 미검증 실패로 드러남

## 2. Planner의 검색·계산기 선택 정확도

### 2.1 라벨이 있는 사례 준비

현재 `evals/cases.jsonl`은 12개 소규모 text-only 사례입니다. `search_expected`의 양성 사례가 1개뿐이므로 현재 수치로 planner의 검색 능력을 결론 내리지 마세요. 새 사례는 다음 축을 균형 있게 포함합니다.

- 검색: 검색이 명확히 불필요한 계산/대수 문제, 외부 사실 확인이 유용한 과학/개념/사실 문제
- 계산기: 단순 암산 수준, 여러 단계 산술, 계산이 핵심이 아닌 개념 문제
- 난이도·표현: 짧은 문장, 장문, 기호, 이미지 표·도형
- 어려운 경계 사례: 검색해도 도움이 안 되는 문제, 질문이 불충분한 문제

각 row에는 사람이 미리 판단한 `search_expected`, `calculator_expected`를 기록합니다. 기대값은 모델의 예측을 보고 사후에 정하지 말고, 평가 전에 정합니다. 첫 smoke set은 각 조합을 포함한 12~20개, 비교 가능한 파일럿은 유형별로 수십 개 이상을 목표로 확장합니다. 데이터 수가 적으면 비율과 함께 분자·분모를 제시합니다.

현재 JSONL 필수 구조의 예:

```json
{"id":"factual-001","problem_type":"factual","modality":"text_only","prompt":"What is the chemical symbol for gold?","expected_answer":"Au","grading_criteria":"State that gold's chemical symbol is Au.","calculator_expected":false,"search_expected":true,"verifier_probe":"Gold's chemical symbol is Au.","expected_verifier_verdict":"correct"}
```

`expected_answer`는 정답 기준이며 `grading_criteria`는 설명 평가용입니다. 현재 자동 채점은 답 부분의 정규화 exact match를 중심으로 하므로, 서술형 해설 품질은 별도 사람 rubric 검토가 필요합니다.

### 2.2 live paired evaluation

`.env`에 올바른 `OPENAI_API_KEY`, `GOOGLE_API_KEY`가 있어야 합니다. 검색 기대가 true인 케이스를 검색까지 완주하려면 `SERPAPI_API_KEY`도 필요합니다. Compose가 `.env`를 컨테이너 환경으로 전달하는지 확인하되 값 자체는 출력하지 않습니다.

```powershell
docker compose up -d --build
docker compose exec -T api python -c "import os; print({k: bool(os.getenv(k)) for k in ['OPENAI_API_KEY','GOOGLE_API_KEY','SERPAPI_API_KEY']})"
```

각 case에 대해 legacy와 LangGraph 경로를 모두 호출합니다. 라이브 호출은 비용이 발생합니다.

```powershell
docker compose exec -T api python /app/evals/run_live_eval.py `
    --cases /app/evals/cases.jsonl `
    --output /data/sophie-24/observations.jsonl

docker compose exec -T api python /app/evals/run_eval.py `
    --cases /app/evals/cases.jsonl `
    --observations /data/sophie-24/observations.jsonl
```

첫 명령이 실제 관측치를 만들고, 두 번째 명령이 보고서를 stdout에 출력합니다. 결과를 로컬에 보관하려면:

```powershell
New-Item -ItemType Directory -Force .\evals\results\sophie-24 | Out-Null
docker compose cp api:/data/sophie-24/observations.jsonl .\evals\results\sophie-24\observations.jsonl
```

보고서에서 `calculator_plan_accuracy`, `search_route_accuracy`, 각 precision/recall, `calculator_usage_accuracy`, `final_answer_exact_accuracy`를 봅니다. 구분은 다음과 같습니다.

- **plan accuracy:** 모델이 도구가 필요한지 선택한 판단과 사전 라벨 비교
- **tool usage accuracy:** 실제 MCP 호출이 사전 라벨과 일치하는지 비교
- **answer accuracy:** 도구 선택이 최종 정답에 도움이 됐는지 reference와 비교

이 지표들을 하나로 합치지 마세요. 예를 들어 plan은 맞았지만 MCP 서버가 실패할 수 있고, 도구를 호출하지 않아도 우연히 답을 맞힐 수 있습니다.

### 2.3 Gemini 장애와 재실행

paired runner는 두 구현을 실제 호출하므로 Gemini가 계속 503을 반환하면 비교가 중단되거나 검증 지표가 유효하지 않을 수 있습니다. 이런 실행은 `provider failure`로 분류하고, 답 품질 비교의 성공 표본처럼 포함하지 않습니다. 실패 건수는 별도 분모로 보고합니다. `run_eval.py`는 동일 `(variant, case_id)` 중복을 허용하지 않으므로 현재는 반복별로 서로 다른 output 경로를 사용하고 각 보고서를 따로 보관합니다. 여러 반복을 통합한 신뢰구간을 내려면 `replicate_id`를 평가 키에 추가하는 코드 변경이 필요합니다.

## 3. MCP 계산 결과가 답을 교정하는지 확인하기

먼저 용어를 정확히 합니다. 현재 그래프는 계획 단계에서 calculator가 필요하다고 하면 Solver가 최종 풀이를 만들기 **전에** calculator를 호출하도록 합니다. 따라서 정상 경로는 “틀린 답을 만든 뒤 계산기가 그것을 교정했다”라기보다 “풀이 중 계산 결과를 받아 답을 생성했다”입니다. 현재 로그에는 도구 전 candidate answer가 없어서 직접적인 correction rate는 계산할 수 없습니다.

### 현재 구조에서 할 수 있는 실험

1. reference answer가 있는 계산 문제 집합을 준비하고 calculator 필요 여부를 사전 라벨링합니다.
2. `run_live_eval.py`로 기존 legacy와 LangGraph를 실행합니다.
3. LangGraph 관측치의 `calculator_calls` 및 API `process`의 `MCP 도구 실행`을 검사합니다.
4. 각 calculator 결과가 성공했는지, 최종 답이 reference와 맞는지, 도구 실패인데 답이 검증됐다고 표현되지는 않았는지를 집계합니다.
5. 같은 케이스에서 calculator를 비활성화한 ablation을 추가하면 도구가 답 정확도를 바꿨는지 비교할 수 있습니다. 현재 CLI에는 calculator disable 옵션이 없으므로, 이 대조 실험을 위해서는 그래프 설정 옵션을 코드에 추가해야 합니다.

이 실험은 **tool-assisted answer accuracy**를 측정합니다. 엄밀한 correction rate와는 다릅니다.

### 실제 correction rate를 측정하려면 필요한 추가 구현

한 평가용 경로에서 다음을 관측하도록 바꿉니다.

```text
solver draft (도구 호출 전)
    → 계산식 후보 추출/검사
    → MCP calculator 결과
    → solver revision (도구 결과를 받은 뒤)
```

관측 JSONL에 `draft_answer`, `calculator_result`, `revised_answer`, `reference_answer`를 저장합니다. 이후 다음을 별도로 계산합니다.

- **오류 검출률:** draft가 틀린 사례 중 calculator 결과가 오류를 드러낸 비율
- **교정 성공률:** 오류가 발견된 draft 중 revised answer가 reference와 맞은 비율
- **회귀율:** draft가 맞았는데 도구 결과 반영 후 틀린 비율
- **계산기 실행 성공률:** MCP 응답에서 `ok=true`인 비율

초안과 revision의 비교는 값이 단순히 바뀌었는지만 보면 안 됩니다. 모델이 표현을 바꿔도 정답은 그대로일 수 있고, 정답이 아닌 숫자로 바뀔 수도 있으므로 reference와 rubric을 사용해야 합니다. 의도적으로 잘못된 산술 초안을 주는 고정 challenge set은 verifier/revision capability를 별도로 재현하기 좋습니다. 다만 이 테스트는 일반 `/api/solve` 사용자 흐름의 정확도와 구별해서 보고합니다.

## 4. 새 경로와 legacy의 정확도·비용·지연 비교

### 4.1 공정한 입력과 설정

- 같은 case ID, 이미지 바이트, 질문, project ID 정책을 사용합니다.
- 같은 OpenAI/Gemini 모델명, API 키 project, 가능한 한 같은 시간대와 네트워크 조건을 사용합니다.
- 이미지와 검색 결과가 달라질 수 있으므로 case와 실행 시간, provider/model, prompt 버전, 검색 query를 관측치에 보관합니다.
- legacy와 새 그래프는 프롬프트 및 검색 정책이 달라서, 현재 paired evaluation은 **전체 워크플로 변화** 비교입니다. LangGraph 라이브러리 효과만 분리한 실험이 아닙니다.

실행 명령은 2.2의 paired evaluation과 같습니다. `run_eval.py`는 각 구현별 exact answer accuracy, calculator usage/plan metrics, search route metrics 및 API 응답 유효성 등을 반환합니다. 현재 답변 채점은 exact match이므로 다양한 자연어 답변의 동치 표현은 오판할 수 있습니다. 중요한 subset은 rubric으로 사람이 검토합니다.

### 4.2 비용 비교

현재 관측치에는 provider별 토큰 usage가 없습니다. 다음 중 하나를 선택하세요.

1. **가장 정확한 방법:** `backend/graph.py`의 OpenAI 호출 응답 usage, `GeminiModelClient.generate_text`의 Gemini usage metadata, SerpAPI 호출 수를 관측 레코드에 추가합니다. API key나 프롬프트 원문은 기록하지 않습니다. 이후 호출 당시의 단가표와 곱해 case별 비용을 산정합니다.
2. **거친 외부 확인:** 각 공급자 Usage/Billing 화면의 전체 사용량 차이를 실험 전후로 기록합니다. 다른 앱 호출이 섞이면 case별 비용이라고 주장하지 않습니다.

요청별 비용 필드 예: `openai_input_tokens`, `openai_output_tokens`, `gemini_input_tokens`, `gemini_output_tokens`, `serpapi_calls`, `calculator_calls`, `estimated_cost_usd`. 집계에는 계산 시 적용한 단가와 날짜를 같이 둡니다.

### 4.3 지연 비교

현재 live runner의 `duration_ms`는 요청 전체 시간입니다. 첫 보고서는 legacy와 langgraph의 평균만 보지 말고 관측 수, 실패 건수, 중앙값 및 p95를 함께 계산합니다. 실제 분포 지표를 만들려면 별도 집계 스크립트나 runner 개선이 필요합니다.

반복할 때는 현재 evaluator의 duplicate case 제한 때문에 run마다 다른 output 경로를 사용합니다.

```powershell
docker compose exec -T api python /app/evals/run_live_eval.py --cases /app/evals/cases.jsonl --output /data/repeat-01/observations.jsonl
docker compose exec -T api python /app/evals/run_live_eval.py --cases /app/evals/cases.jsonl --output /data/repeat-02/observations.jsonl
```

반복별 report를 따로 보관하세요. 현 evaluator는 `replicate_id` 기반으로 여러 run을 하나의 통계 분석에 합치지 않습니다. 정식 보고서가 필요하면 evaluator를 확장해 case×variant×replicate를 키로 관리하고, 평균·분산 또는 bootstrap interval을 계산합니다. 각 반복은 실제 모델 호출이므로 비용 예산을 먼저 정합니다.

## 5. Labeled real-image 평가 만들기

### 5.1 데이터 구성

```text
evals/
  cases.real.jsonl
  images/
    math-001.png
    geometry-001.jpg
```

JSONL의 `image_path`는 **cases 파일이 있는 디렉터리를 기준으로 한 상대 경로**입니다. 예시:

```json
{"id":"image-math-001","problem_type":"algebra","modality":"image","image_path":"images/math-001.png","prompt":"이미지의 문제를 풀어줘.","expected_answer":"x = 5","grading_criteria":"문제의 식을 정확히 읽고 x=5와 등식 변형 근거를 제시한다.","calculator_expected":false,"search_expected":false,"verifier_probe":"x = 5","expected_verifier_verdict":"correct"}
```

사례별로 사람이 원본 이미지를 보고 기준 답안·조건·단위·허용 표기·부분점수 rubric을 확정합니다. planner 평가까지 하려면 `search_expected`, `calculator_expected`를 사람이 라벨링합니다. `expected_verifier_verdict`와 `verifier_probe`는 고정 verifier 시험용 필드이며, live runner가 이 probe를 실제 검증하지 않는 현재 한계를 기억하세요.

비식별·사용 허가가 확인된 이미지로 작게 시작합니다. 쉬운/어려운 문제, 수식/도형/표, 저해상도·기울어짐, OCR 혼동(1/l, 0/O), 다중 조건을 포함합니다. 결과를 본 뒤 case 문구나 정답을 사후 수정하면 leakage가 생기므로 평가 전 라벨을 고정합니다.

### 5.2 실행과 해석

이미지 경로가 존재하면 `run_live_eval.py`가 실제 바이트를 읽어 두 경로에 전달합니다. 경로가 없으면 runner가 text-only synthetic image를 만드므로 real-image 평가가 아닙니다.

```powershell
docker compose exec -T api python /app/evals/run_live_eval.py `
    --cases /app/evals/cases.real.jsonl `
    --output /data/real-image-pilot/observations.jsonl

docker compose exec -T api python /app/evals/run_eval.py `
    --cases /app/evals/cases.real.jsonl `
    --observations /data/real-image-pilot/observations.jsonl
```

최종 답 정확도는 이미지 읽기 오류와 수학 추론 오류가 섞인 end-to-end 수치입니다. 현재 graph가 별도의 OCR 문제 텍스트를 결과로 노출하지 않으므로 OCR 정확도만 분리하고 싶으면 이미지 transcription 단계와 labeled transcription field를 추가해야 합니다. 결과는 문제 유형별로 나누고 실패한 이미지도 분모에 남깁니다.

## 6. Kubernetes 배포와 persistence 관찰

### 6.1 기존 로컬 클러스터만 사용

먼저 현재 context와 노드를 확인합니다.

```powershell
kubectl config current-context
kubectl get nodes
```

명령이 실패하거나 context가 비어 있으면 여기서 중단합니다. 클러스터를 설치하거나 바꾸지 않습니다. 이 프로젝트 문서는 현재 클러스터 context가 준비되지 않은 상태를 전제로 하므로, manifest 작성만 된 상태와 실제 배포 상태를 구분합니다.

### 6.2 이미지 빌드·클러스터 로드

저장소 루트:

```powershell
docker compose build api mcp-tools
```

Compose가 생성한 `gempt-api:dev`, `gempt-mcp-tools:dev` 이미지를 **현재 context에 맞는 방법으로** 로드합니다.

```powershell
# kind context일 때만
kind load docker-image gempt-api:dev
kind load docker-image gempt-mcp-tools:dev

# Minikube context라면 kind 명령 대신 다음을 사용
minikube image load gempt-api:dev
minikube image load gempt-mcp-tools:dev
```

### 6.3 namespace·Secret·매니페스트 적용

Compose의 `.env` 파일을 `kubectl`이 자동으로 읽지는 않습니다. 현재 PowerShell 프로세스의 `$env:OPENAI_API_KEY`, `$env:GOOGLE_API_KEY`, `$env:SERPAPI_API_KEY`에 값을 설정하세요. 값을 `Write-Host`하거나 화면 캡처에 노출하지 않습니다. 검색이 필요한 평가를 하려면 SerpAPI 키도 설정합니다.

```powershell
if (-not $env:OPENAI_API_KEY -or -not $env:GOOGLE_API_KEY) {
    throw "현재 PowerShell 세션에 OPENAI_API_KEY와 GOOGLE_API_KEY를 설정해야 합니다."
}

kubectl create namespace gempt --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic gempt-api-keys -n gempt `
    --from-literal="OPENAI_API_KEY=$env:OPENAI_API_KEY" `
    --from-literal="GOOGLE_API_KEY=$env:GOOGLE_API_KEY" `
    --from-literal="SERPAPI_API_KEY=$env:SERPAPI_API_KEY" `
    --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f .\deploy\k8s\mvp.yaml
kubectl -n gempt rollout status deployment/mcp-tools --timeout=180s
kubectl -n gempt rollout status deployment/api --timeout=180s
kubectl -n gempt get deployments,pods,services,pvc -o wide
```

`SERPAPI_API_KEY`가 비어 있는데 Secret에 빈 값으로 넣으면 검색은 성공하지 않습니다. 검색을 검증할 때는 실제 키가 설정됐는지 Boolean으로만 확인합니다. Secret은 로컬 학습용이며 Kubernetes Secret만으로 production-grade secret management가 완성되는 것은 아닙니다.

PVC가 `Pending`이면:

```powershell
kubectl -n gempt describe pvc gempt-project-data
kubectl get storageclass
```

선택한 로컬 클러스터에 기본 StorageClass/provisioner가 있는지 확인합니다. PVC를 임의로 지우거나 클러스터를 재설정하지 않습니다.

### 6.4 readiness 및 API-to-MCP 검사

```powershell
kubectl -n gempt get pods -o wide
kubectl -n gempt describe deployment api
kubectl -n gempt logs deployment/mcp-tools --tail=100
kubectl -n gempt logs deployment/api --tail=100
```

MCP Service 연결만 직접 확인하려면:

```powershell
kubectl -n gempt exec deployment/api -- python -c "from mcp_client import MCPClient; print(MCPClient.from_env().call_tool('calculator', {'expression':'21 / 3'}))"
```

성공 응답에는 `ok: true`, `result: 7`이 있어야 합니다. 그 다음 실제 API 경로도 확인합니다. 별도 PowerShell 창에서 port-forward를 계속 실행합니다.

```powershell
kubectl -n gempt port-forward service/api 5000:5000
```

다른 창에서 앞서 소개한 `Invoke-RestMethod` 요청을 보내고 `process`에서 `MCP 도구 실행`을 확인합니다. 직접 MCP `exec` 성공은 네트워크/도구 계약 검증이고, `/api/solve` 성공은 planner→Solver→MCP→Verifier 경로를 확인하는 end-to-end 검증이므로 두 증거를 따로 기록합니다.

### 6.5 PVC persistence 증명

단순히 PVC가 `Bound`인 것만으로 점수 파일이 재시작 후 보존됐다고 증명할 수 없습니다. 실제 애플리케이션 파일의 데이터가 Pod 교체 전후에 유지되는지 확인합니다.

1. 고유 `project_id`로 `/api/solve`를 호출합니다.
2. 응답 `scores`를 확인하고, 승자에 따라 점수가 실제로 증가한 case인지 확인합니다. Gemini/API 실패나 합의로 점수가 그대로라면 persistence 검증 표본으로 사용할 수 없습니다.
3. 같은 API에서 `GET /api/scores/<project_id>` 결과를 저장합니다.
4. API Pod를 삭제해 Deployment가 새 Pod를 만들도록 합니다.
5. 새 Pod가 Ready가 된 뒤 같은 endpoint를 호출해 같은 점수가 조회되는지 비교합니다.

```powershell
$projectId = "pvc-check-20261119"
Invoke-RestMethod "http://127.0.0.1:5000/api/scores/$projectId" | ConvertTo-Json

kubectl -n gempt delete pod -l app=api
kubectl -n gempt wait --for=condition=Ready pod -l app=api --timeout=180s
Invoke-RestMethod "http://127.0.0.1:5000/api/scores/$projectId" | ConvertTo-Json
```

port-forward가 Pod 교체 중 끊기면 해당 터미널에서 다시 실행합니다. PVC가 Bound인 상태, 새 Pod UID/생성 시각, 전후 GET 응답을 함께 기록합니다. API 점수가 증가하지 않았다면 실제 애플리케이션 데이터 보존을 입증하지 못했으므로, 임의로 성공이라고 결론 내리지 않습니다.

### 6.6 Kubernetes 완료 판정에 필요한 증거

- `kubectl config current-context`와 `kubectl get nodes` 결과
- API/MCP Deployment rollout 완료 및 두 Pod Ready
- `gempt-project-data` PVC `Bound`
- API Pod 안에서 MCP calculator 직접 호출 결과
- port-forward를 통한 `/api/solve` 응답의 MCP process 이벤트
- 실제 점수 값이 저장된 project ID의 Pod 교체 전후 조회 결과
- 관련 API/MCP 로그와 시각

이 증거가 없으면 “Kubernetes에 배포했다” 대신 “Kubernetes manifest를 준비했다”고 보고합니다.

## 7. 평가 결과 기록 템플릿

```text
브랜치/커밋:
평가 시각:
case 파일 및 버전:
OpenAI 모델 / Gemini 모델:
실행 반복 ID:
실행 환경 (Compose 또는 Kubernetes):

Legacy: 정답 수 / 관측 수, 실패 수, 요청 지연 통계, 호출 수, 비용(계측된 경우)
LangGraph: 정답 수 / 관측 수, 실패 수, 요청 지연 통계, 검색·계산 계획 지표,
           MCP 성공 수, 비용(계측된 경우)

이미지 subset 결과:
Gemini/provider 장애:
Kubernetes context 및 Ready 상태:
API→MCP direct check:
Pod 교체 전/후 PVC score 확인:
제한 및 해석:
```

평가 보고서에는 raw observation JSONL, case manifest, 모델명, 실행 날짜를 같이 보관합니다. API 키, 전체 `.env`, 원본 개인 이미지, 불필요한 prompt 전문은 artifact에 넣지 않습니다.
