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

## 고도화 계획

### MVP: Agent 실행과 도구 사용

1. 기존 Flask 구조와 API를 유지하면서 Agent 실행 로직을 분리합니다.
2. 실행 단위 상태와 단계 이벤트, 종료 사유를 명시적으로 관리합니다.
3. function calling으로 제한된 계산기 도구를 연결하고, 도구명·인자·호출 횟수를 서버에서 검증합니다.
4. Solver와 Verifier의 구조화된 출력 및 프롬프트 버전을 기록합니다.
5. 고정 시나리오 하네스로 완료율, 합의율, 도구 호출 수, 오류율, 지연 시간, 토큰/비용을 측정합니다.
6. 실행 ID가 포함된 로그로 단계별 실패를 찾을 수 있도록 합니다.

### 후속 단계

- 도구 인터페이스가 안정된 뒤 계산 도구를 MCP 서버로 제공
- OpenTelemetry 호환 추적과 Langfuse 또는 Phoenix 중 하나를 연결
- Dockerfile과 Docker Compose로 재현 가능한 실행 환경 구성
- GitHub Actions로 의존성 설치, 정적 검사, 테스트, 이미지 빌드 자동화
- 로컬 Kubernetes에서 Deployment, Service, probe, Secret/ConfigMap, 파드 로그 확인

MCP, 분산 실행, 장기 사용자 기억, Docker/Kubernetes 배포, GitHub Actions는 현재 구현된 기능이 아닙니다. 평가 기준과 기준선 측정 결과를 확인한 뒤 단계별로 진행합니다.

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