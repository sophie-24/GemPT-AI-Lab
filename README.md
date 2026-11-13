# GemPT-AI-Lab

듀얼 LLM 기반 문제 풀이 검증 서비스 GemPT를 출발점으로, Agent 실행 흐름과 도구 사용, 평가 방법을 단계적으로 실험하는 프로젝트입니다.

> **현재 상태:** 저장소에는 기존 GemPT 기능이 구현되어 있습니다. Agent 고도화 항목은 계획이며, 아래에서 구현 상태와 계획을 구분해 설명합니다.

## 프로젝트 소개

생성형 AI의 답변이 서로 다르거나 틀릴 때 학습자가 판단 근거를 확인하기 어렵다는 문제에서 시작했습니다. 기존 GemPT는 GPT를 문제 해결사(Solver), Gemini를 검증자(Verifier)로 나누고, 이미지 속 문제를 분석해 답안을 교차 검증합니다.

GemPT-AI-Lab의 고도화 방향은 기존 문제 풀이 흐름에 Agent 상태 관리, 제한된 도구 호출, 재현 가능한 평가 하네스를 더하는 것입니다. 목표는 정답을 보장한다고 주장하는 것이 아니라, 실행 단계와 도구 결과, 실패 원인을 확인하고 개선할 수 있는 구조를 만드는 것입니다.

## 현재 구현된 기능

- 문제 이미지를 업로드하고 질문과 함께 풀이를 요청합니다.
- Gemini가 이미지의 과목을 분류하고 검색 질의를 생성합니다.
- SerpAPI 검색 결과를 바탕으로 배경 지식 패키지를 생성합니다.
- GPT-4o가 초기 풀이를 만들고 Gemini 2.5 Pro가 검증합니다.
- 의견이 다르면 최대 5회까지 반박·수정 과정을 진행합니다.
- 최종 답변, 모델 점수, 단계별 처리 내용을 응답으로 반환합니다.
- 프로젝트별 GPT·Gemini 점수를 로컬 JSON 파일에 저장합니다.

현재 검색은 Agent가 선택하는 도구 호출이 아니라 고정된 처리 단계입니다. 실행은 Flask 요청 안에서 동기적으로 진행되며, 실행 상태 조회나 재개 API는 없습니다.

## 현재 처리 흐름

    문제 이미지와 질문
      → Flask POST /api/solve
      → Gemini 과목 분류 및 검색 질의 생성
      → SerpAPI 검색, Gemini 지식 패키지 구성
      → GPT-4o 초기 풀이
      → Gemini 2.5 Pro 검증
      → 최대 5회 토론 및 프로젝트 점수 갱신
      → 답변, 점수, 단계별 process 반환

## API

| Method | Endpoint | 설명 |
| --- | --- | --- |
| GET | / | 웹 애플리케이션 제공 |
| POST | /api/solve | multipart/form-data로 image, 선택 질문 question, 선택 project_id를 받아 풀이 |
| GET | /api/scores/{project_id} | 프로젝트별 모델 점수 조회 |

POST /api/solve는 현재 winner, final_answer, scores, process 필드를 반환합니다. 자세한 계약은 [기존 API 명세서](docs/api_spec.md)를 참고하세요.

## 기술 스택

- **Backend:** Python, Flask, Pillow
- **LLM:** OpenAI API (GPT-4o), Google Gemini API (Gemini 2.5 Pro)
- **검색:** SerpAPI
- **Frontend:** React, Tailwind CSS, MathJax
- **현재 저장:** 프로젝트 점수용 로컬 JSON 파일

## MVP 고도화: MCP와 Kubernetes

이번 MVP의 중심은 MCP 도구 연동과 Kubernetes 운영입니다. 기존 Flask 문제 풀이 서비스를 컨테이너화하고, MCP 도구 서버와 연결해 로컬 Kubernetes 환경에 배포하는 end-to-end 흐름을 만듭니다. 현재 이 항목들은 계획 단계이며 구현 완료 기능이 아닙니다.

### 목표 구조

    사용자
      → Flask GemPT API
      → LLM의 도구 호출 판단
      → MCP Client
      → MCP Server (계산 도구)
      → 도구 결과를 LLM 검증 흐름에 반영
      → 답변과 실행 이벤트 반환

Flask 애플리케이션은 MCP Client 역할을 합니다. LLM이 계산 도구 호출을 요청하면 서버가 허용된 도구와 입력을 확인하고 MCP Server에 전달합니다. LLM이 MCP 서버에 직접 연결되는 구조는 아닙니다.

### 2일 MVP 범위

1. **MCP 도구:** 별도 MCP Server에 제한된 산술 계산 도구 한 개를 구현하고, Flask 앱에서 MCP Client로 검색·호출합니다.
2. **안전한 호출:** 도구 허용 목록, 인자 스키마, 식 복잡도, 호출 시간·횟수를 제한하고 성공·실패 결과를 기록합니다.
3. **컨테이너 실행:** Flask API와 MCP Server를 별도 이미지로 만들고 Docker Compose로 함께 실행합니다.
4. **Kubernetes 배포:** 로컬 클러스터에 API와 MCP Server를 각각 Deployment와 Service로 배포합니다. Secret/ConfigMap, readiness/liveness probe, 파드 로그 확인 절차를 포함합니다.
5. **동작 시연:** 한 문제 요청에서 LLM 도구 호출 → MCP Server 실행 → 결과 반영 → 최종 응답까지 확인합니다. 실행 단계와 종료 사유를 로그에서 식별할 수 있게 합니다.
6. **기존 호환성:** 현재 /api/solve 응답 필드를 유지하고, 기존 이미지 풀이·토론 동작이 계속 가능한 방법을 문서화합니다.

현재 점수 파일이 로컬 JSON이므로 MVP에서는 API 파드 한 개로 실행하고 데이터 파일 보존 방식을 명시합니다. 여러 API 파드로 확장하거나 운영 수준의 가용성을 주장하지 않습니다.

### 2일 작업 순서

- **1일차:** 인터페이스 확정, MCP Server와 계산 도구 구현, Flask MCP Client 연결, Docker Compose에서 두 서비스 실행
- **2일차:** Kubernetes 매니페스트 작성, 로컬 클러스터 배포, 서비스 연결·헬스 상태·로그 확인, 전체 시연과 문서 정리

### MVP 이후 확장

- Agent 실행 상태와 대화별 지속 저장
- 평가 하네스와 프롬프트·도구 설명 버전 비교
- OpenTelemetry 기반 trace와 Langfuse 또는 Phoenix 시각화
- 여러 MCP 도구, LangGraph 등 Agent 프레임워크 평가
- GitHub Actions에서 품질 검사와 컨테이너 빌드 자동화

MCP Server, Kubernetes, Docker Compose, 실행 상태·평가 하네스는 현재 구현된 기능이 아닙니다. 구현 후 동작과 측정 결과를 확인해 상태를 갱신합니다.
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