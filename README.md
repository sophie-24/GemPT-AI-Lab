# GemPT-AI-Lab

듀얼 LLM 기반 문제 풀이 검증 서비스 GemPT를 출발점으로, Agent 실행 흐름과 도구 사용, 평가 방법을 단계적으로 실험하는 프로젝트입니다.

> **현재 상태:** 기존 Flask GemPT에 LangGraph 실행 경로, SQLite 체크포인트, 이미지 참조 저장소, 오프라인 평가 데이터와 집계기가 추가되었습니다. LangGraph 경로와 라이브 모델 성능은 검증 전이며, 아래에서 구현 파일과 실제 확인 결과를 구분합니다.

## 프로젝트 소개

생성형 AI의 답변이 서로 다르거나 틀릴 때 학습자가 판단 근거를 확인하기 어렵다는 문제에서 시작했습니다. 기존 GemPT는 GPT를 문제 해결사(Solver), Gemini를 검증자(Verifier)로 나누고, 이미지 속 문제를 분석해 답안을 교차 검증합니다.

GemPT-AI-Lab의 고도화 방향은 기존 문제 풀이 흐름에 Agent 상태 관리, 제한된 도구 호출, 재현 가능한 평가 하네스를 더하는 것입니다. 목표는 정답을 보장한다고 주장하는 것이 아니라, 실행 단계와 도구 결과, 실패 원인을 확인하고 개선할 수 있는 구조를 만드는 것입니다.

## 현재 구현된 기능

- 문제 이미지를 업로드하고 질문과 함께 풀이를 요청합니다.
- GPT-4o 비전 계획기가 이미지·질문을 분류하고 검색과 calculator 사용 여부를 선택합니다.
- 검색이 필요하다고 판단된 경우에만 SerpAPI를 최대 3회 호출합니다. 수학 계산 문제는 기본적으로 검색을 생략합니다.
- GPT-4o Solver가 MCP calculator를 호출하면 결과를 대화 상태에 돌려받고, 그 값을 반영해 풀이를 이어갑니다. 계획상 계산기 사용이 필요하면 첫 호출에서 calculator 사용을 요구합니다.
- Gemini가 최종 풀이를 구조화된 형식으로 검증합니다. Gemini 장애 시 검증 오류를 기록하고 추가 토론 호출은 중단합니다.
- 의견이 다르면 최대 5회까지 반박·수정 과정을 진행합니다.
- 최종 답변, 모델 점수, 단계별 처리 내용을 응답으로 반환합니다.
- 프로젝트별 GPT·Gemini 점수를 로컬 JSON 파일에 저장합니다.
- GPT가 선택한 산술 계산을 Flask의 MCP Client가 제한된 calculator 도구로 전달하고, 결과를 기존 풀이 흐름에 포함합니다. MCP 실행 이벤트는 `process`에 기록됩니다.
- `POST /api/solve`는 LangGraph 실행 경로를 사용합니다. 기존 순차 실행 경로는 비교 기준선인 `run_analysis_logic_legacy`로 보존했습니다.
- 그래프 실행은 `run_id`별 SQLite 체크포인트를 사용하고, 이미지 파일은 `/data/uploads`에 저장해 그래프 상태에는 `image_ref`만 둡니다.
- 오프라인 평가 데이터와 집계기는 기준선·LangGraph 관측치를 구현별로 나눠 답 일치율, 검색·calculator 계획 정확도, 실제 도구 사용, Verifier 판정, 응답 구조, 지연과 실패를 요약합니다.
- `GET /healthz`, API/MCP 컨테이너 및 Docker Compose 설정, 로컬 Kubernetes 매니페스트가 준비되어 있습니다. Compose 이미지 빌드와 두 컨테이너의 헬스 상태, API 컨테이너에서 MCP calculator까지의 호출은 확인했습니다.

Agent 계획기가 검색 필요 여부와 calculator 사용 필요 여부를 결정합니다. 검색 실행은 최대 3개 질의로 제한됩니다. 계산 결과는 Solver의 대화 상태로 전달되지만, 결과를 무시하지 않았는지와 답이 실제로 교정되었는지는 평가 데이터로 별도 측정해야 합니다. 실행은 Flask 요청 안에서 동기적으로 진행됩니다. 체크포인트는 저장되지만 실행 상태 조회·재개 API는 제공하지 않습니다. 평가 사례는 text-only이므로 이미지 인식 성능을 측정하지 않습니다.

## 현재 처리 흐름

    문제 이미지와 질문
      → Flask POST /api/solve
      → GPT-4o Agent 계획 (주제·문제 유형·검색·계산기 분기)
      → [검색 필요 시] 최대 3개 SerpAPI 검색
      → GPT-4o 풀이 ↔ [계산 필요 시] MCP calculator 결과 반영
      → Gemini 구조화 검증
      → 최대 5회 토론 및 프로젝트 점수 갱신
      → 답변, 점수, 단계별 process 반환

## API

| Method | Endpoint | 설명 |
| --- | --- | --- |
| GET | / | 웹 애플리케이션 제공 |
| GET | /healthz | API 상태 확인 |
| POST | /api/solve | multipart/form-data로 image, 선택 질문 question, 선택 project_id를 받아 풀이 |
| GET | /api/scores/{project_id} | 프로젝트별 모델 점수 조회 |

POST /api/solve는 현재 winner, final_answer, scores, process 필드를 반환합니다. 자세한 계약은 [기존 API 명세서](docs/api_spec.md)를 참고하세요.

## 기술 스택

- **Backend:** Python, Flask, Pillow
- **LLM:** OpenAI API (GPT-4o), Google Gemini API (Gemini 2.5 Pro)
- **검색:** SerpAPI
- **Frontend:** React, Tailwind CSS, MathJax
- **현재 저장:** 프로젝트 점수용 로컬 JSON 파일

## MCP·LangGraph·Kubernetes 실행 구조

현재 구현은 기존 Flask API, LangGraph 실행 흐름, 별도 MCP 계산기 서비스와 컨테이너·Kubernetes 리소스를 연결하는 구조입니다. Compose 경로는 일부 확인했으며, LangGraph 전체 실행과 Kubernetes 배포 상태는 아래 제한 사항에 구분해 기록합니다.

### 목표 구조

    사용자
      → Flask GemPT API
      → LLM의 도구 호출 판단
      → MCP Client
      → MCP Server (계산 도구)
      → 도구 결과를 LLM 검증 흐름에 반영
      → 답변과 실행 이벤트 반환

Flask 애플리케이션은 MCP Client 역할을 합니다. LLM이 계산 도구 호출을 요청하면 서버가 허용된 도구와 입력을 확인하고 MCP Server에 전달합니다. LLM이 MCP 서버에 직접 연결되는 구조는 아닙니다.

### 구현 범위와 검증 상태

1. **MCP 도구:** 별도 MCP Server의 제한된 calculator를 Flask MCP Client가 호출합니다.
2. **안전한 호출:** 허용 목록·입력 검사·시간 제한·호출 수 제한·구조화 결과를 적용합니다.
3. **LangGraph:** 계획·조건부 검색·풀이·MCP 도구 실행·검증·토론·종료 단계를 그래프 상태와 분기로 관리합니다.
4. **영속성:** `run_id` 기반 SQLite 체크포인트와 별도 이미지 파일 저장을 사용합니다.
5. **평가 준비:** 고정 text-only 사례와 `legacy`/`langgraph` 관측치를 나눠 집계하는 오프라인 평가기를 둡니다.
6. **컨테이너·Kubernetes:** Compose 파일과 Kubernetes Deployment·Service·PVC 등 매니페스트를 제공합니다.
7. **API 호환성:** `/api/solve`의 `winner`, `final_answer`, `scores`, `process` 필드를 유지합니다.

현재 점수 파일이 로컬 JSON이므로 MVP에서는 API 파드 한 개로 실행하고 데이터 파일 보존 방식을 명시합니다. 여러 API 파드로 확장하거나 운영 수준의 가용성을 주장하지 않습니다.

### 확인된 실행 결과와 남은 확인

- Compose 이미지 빌드, API/MCP health 상태, 기존 Flask MCP Client의 calculator 호출은 관측했습니다.
- LangGraph를 통한 실제 `/api/solve` 요청과 API 키가 필요한 평가 실행은 아직 관측하지 않았습니다.
- Kubernetes 매니페스트는 준비됐지만, 사용 가능한 kubectl context가 없어 클러스터 적용·Pod 준비 상태·로그는 관측하지 않았습니다.

### MVP 이후 확장

- Agent 실행 상태와 대화별 지속 저장
- 평가 하네스와 프롬프트·도구 설명 버전 비교
- OpenTelemetry 기반 trace와 Langfuse 또는 Phoenix 시각화
- 이미지 기반 평가 데이터와 풀이 설명 루브릭 채점
- 동시성 증가 시 JSON/SQLite 파일 저장소를 공유 DB로 교체
- GitHub Actions에서 품질 검사와 컨테이너 빌드 자동화

평가 사례는 현재 텍스트 입력만 포함하므로, 결과는 이미지 인식 성능을 나타내지 않습니다. 오프라인 fixture도 지표 집계 형식 예시이며 모델 품질 측정값이 아닙니다. 점수 저장은 로컬 JSON이며 API 복제본은 하나로 제한합니다. 실행·비교 세부사항은 [평가 안내](docs/evaluation.md), Kubernetes 절차와 관측 제한은 [Kubernetes 안내](docs/kubernetes.md)를 참고하세요.
## 로컬 실행

### 준비물

- Python 가상환경
- OpenAI API 키와 Google Gemini API 키
- 검색 기능을 사용할 경우 SerpAPI 키

### 설치

    git clone https://github.com/sophie-24/GemPT-AI-Lab.git
    cd GemPT-AI-Lab/backend
    python -m venv .venv

Windows PowerShell:

    .\.venv\Scripts\Activate.ps1

macOS/Linux:

    source .venv/bin/activate

의존성을 설치합니다.

    pip install -r requirements.txt

backend/.env.example을 backend/.env로 복사하고 키를 입력합니다. 현재 예제 파일에는 OpenAI와 Google 키가 있습니다. 검색 기능을 사용하려면 SERPAPI_API_KEY도 backend/.env에 추가하세요.

    OPENAI_API_KEY=your_openai_key
    GOOGLE_API_KEY=your_google_key
    SERPAPI_API_KEY=your_serpapi_key

백엔드 디렉터리에서 Flask 개발 서버를 실행합니다.

    flask run

기본 주소는 http://127.0.0.1:5000 입니다.

로컬 Compose 통합은 저장소 루트에서 `docker compose build` 후 `docker compose up`으로 실행합니다. `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `SERPAPI_API_KEY`는 환경 변수로 전달하고, 점수 파일은 `PROJECT_DB_FILE=/data/project_db.json`으로 설정된 named volume에 저장됩니다. 점수 JSON 파일을 사용하는 동안 API는 1개 인스턴스로 운영해야 합니다.

## 데이터 및 제한 사항

- 실제 API 키가 들어 있는 .env 파일은 커밋하지 마세요.
- 현재 점수 저장 파일은 로컬 개발용이며 다중 인스턴스 운영용 저장소가 아닙니다.
- LLM 응답이나 모델 간 합의는 정답을 보장하지 않습니다. 평가 결과와 도구의 적용 범위를 함께 확인해야 합니다.
- 프로젝트의 현재 API와 구조는 고도화 과정에서 변경될 수 있으며, 변경 시 이 문서와 API 명세를 함께 갱신합니다.

## 개발 원칙

- 기존 동작과 API 계약을 확인한 뒤 작은 단위로 변경합니다.
- 모델 호출, 도구 실행, 상태 전이, 사용자 응답을 구분해 기록합니다.
- 허용된 도구만 실행하고 입력 스키마, 횟수, 시간 제한을 적용합니다.
- 측정 전에는 정확도 향상이나 운영 성과를 주장하지 않습니다.
