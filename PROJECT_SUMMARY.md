# TONYAgent — Project Summary

**Updated:** 2026-09-30 · **Tests:** Python 404 passed, TypeScript 54 passed
**Build:** Tauri MSI + NSIS installers produced; app verified running end to end

---

## 프로젝트 개요 / Project Overview

### English

**TONYAgent** is a local-first desktop AI agent. It connects to user-provided LLM
API keys, operates on a selected project folder inside a hardened Docker
sandbox, and exposes a rich toolset (file operations, shell, search, network,
browser automation) for autonomous programming tasks.

The architecture is now **core / UI separated**: the agent core is a headless
Python package that imports no GUI toolkit, and the UI is a client of it. A
Tauri + React frontend is being built against that boundary; the existing
Tkinter UI is a second client of the same core.

### 한국어

**TONYAgent**은 로컬 퍼스트 데스크톱 AI 에이전트입니다. 사용자가 제공한 LLM API
키에 연결하고, 강화된 Docker 샌드박스 안에서 선택한 프로젝트 폴더를 대상으로
작동하며, 자율 프로그래밍 작업을 위한 도구 세트(파일, 쉘, 검색, 네트워크,
브라우저 자동화)를 제공합니다.

아키텍처는 **코어와 UI를 분리**했습니다. 에이전트 코어는 GUI 툴킷을 전혀
import하지 않는 헤드리스 Python 패키지이고, UI는 그 코어의 클라이언트입니다.
Tauri + React 프론트엔드가 이 경계에 맞춰 개발 중이며, 기존 Tkinter UI는 같은
코어의 두 번째 클라이언트입니다.

---

## 핵심 기능 / Core Features

| 기능 / Feature | 상태 | 설명 |
|---|---|---|
| 멀티 프로바이더 / Multi-Provider | ✅ | OpenAI, Anthropic, Gemini, Mistral, Groq, OpenRouter, Ollama, Custom |
| 스트리밍 채팅 / Streaming Chat | ✅ | 토큰 단위 스트리밍, 도구 실행 표시 |
| 파일 도구 / File Tools | ✅ | read, write, edit, delete, list_dir, `sandbox_read_file`, `sandbox_list_files` |
| 검색 도구 / Search Tools | ✅ | grep (스트리밍, context_lines), glob (max_results) |
| 쉘 도구 / Shell | ✅ | execute_command — 샌드박스 미기동 시 fail-closed |
| 네트워크 도구 / Network | ✅ | http_request, SSRF 가드(내부 IP 차단) |
| 브라우저 도구 / Browser | ✅ | navigate, click, type, eval, screenshot, get_text, wait_for, scroll, snapshot |
| Docker 샌드박스 / Sandbox | ✅ | 단일 프로세스 RPC, pids/cap/tmpfs/ulimit 강화 |
| 헤드리스 코어 / Headless Core | ✅ | `AgentSession` + `EventBus`, GUI 무의존 |
| IPC 프로토콜 / Sidecar | ✅ | stdio JSONL, 11개 메서드, 16개 이벤트 |
| Tauri 프론트엔드 / Tauri UI | ✅ | 빌드됨, 사이드카 스폰, 전체 왕복 경로 검증 |
| 테마 / Theme | ✅ | 라이트/다크/시스템, 토큰 기반 |
| 마크다운 렌더링 / Markdown | ✅ | 어시스턴트 텍스트를 토큰 트리로 파싱해 React 엘리먼트로 렌더 (HTML 문자열 없음, 위험 URL/원격 이미지 차단) |
| 커스텀 모델·엔드포인트 / Custom model + endpoint | ✅ | 모델 필드 자유 입력(`<datalist>` 제안 + 임의 id 허용), `bind_provider`의 선택적 `base_url` — `custom` provider를 UI에서 사용 가능하게 함 |
| 키링 보안 / Keyring | ✅ | OS 키링, 정확한 키 길이 검증 |

---

## 아키텍처 / Architecture

```
┌──────────────┐   ┌──────────────┐
│  Tkinter UI  │   │  Tauri + React│
└──────┬───────┘   └──────┬───────┘
       │  EventBus        │  JSONL over stdio
       └────────┬─────────┘
                ▼
      ┌───────────────────┐
      │   AgentSession    │  core/session.py
      │  history · tools  │
      │  provider · sandbox│
      └─────────┬─────────┘
                │
   ┌────────────┼─────────────┐
   ▼            ▼             ▼
 LLMClient   orchestrator   SandboxManager
  api/        tools/        sandbox/
```

### 왜 이 구조인가 / Why

Tkinter는 단일 스레드 강제 모델이라 UI 갱신을 전부 큐로 밀어넣어야 하고, 그
결과 `schedule_on_ui` 같은 간접 계층이 생겼습니다. 이 계층은 Tk 루프가 없으면
**모든 콜백을 조용히 버립니다** — 헤드리스 실행에서는 확인 요청이 사라지고
도구가 60초 타임아웃됩니다.

코어를 UI에서 분리하면 이 문제가 구조적으로 사라지고, 동시에 두 번째 프론트엔드
(Tauri)를 코드 변경 없이 붙일 수 있게 됩니다.

---

## 최근 해결한 버그 / Recent Critical Fixes

| 버그 | 증상 | 원인 |
|---|---|---|
| **도구가 실행되지 않음** | 모든 도구 호출이 조용히 무시됨 | `async` 함수에서 **동기** `execute_tool()` 호출 → `RuntimeError` → 광범위한 `except`가 삼킴 |
| **`CTkComboBox is not a valid model ID`** | OpenRouter 400, 상태줄에 `openrouter/CTkComboBox` | 미설정 콤보의 `get()`가 **자기 클래스 이름**을 반환 |
| **잘린 키 통과** | 35자 키가 `401 User not found` | `MIN_KEY_LENGTH = 20` 전역 상수. 실제 키는 73자 |
| **키 평문 노출** | `scripts/k2.log`에 키 본문 | 진단 스크립트가 `repr(key[7:])` 출력 |
| **키를 저장해도 무효** | OpenRouter 키 저장 후 첫 메시지가 `no provider configured` | 세션은 provider **이름**만 있고 객체는 없음. 설정 패널의 Apply만 `bind_provider`를 호출했고 시작/키 저장은 호출하지 않음 |
| **`No models provided`** | 모델을 고르지 않고 provider를 바인딩하면 빈 모델 id가 전송됨 | `ProviderRegistry.create`가 `model=""`를 명시 전달해 provider 생성자 기본값(`openrouter/auto` 등)을 덮어씀 |
| **`Request URL is missing an 'http://' or 'https://' protocol`** | 스킴 없는 Base URL이 첫 메시지에서 네트워크 오류처럼 표시됨(VPN·방화벽 안내 포함) | `LLMClient`는 base_url이 *빈* 경우에만 기본값을 쓰므로, `openrouter.ai/api/v1` 같은 값이 그대로 요청 URL이 됨 | `normalize_base_url()`이 바인딩 시점에 스킴을 검증하고 후행 슬래시를 제거 |

> 도구 실행 버그는 프로젝트 내내 한 번도 실행된 적이 없던 상태였습니다.
> 이전 문서에서 "미검증"으로 남아 있던 항목이 실제로는 실재하던 버그였습니다.

---

## Tauri 앱: 빌드된 상태

MSVC 블로커는 **해결됨** (Visual Studio Community 2026, VC tools 14.51.36231).
`cargo build`가 링크되고, `tauri build`가 MSI + NSIS 설치 파일을 만듭니다.

앱은 실제로 동작하며, 사이드카를 스폰한 뒤 완전한 왕복 경로까지 검증했습니다.
`NEXT_SESSION.md` §3에 Tauri v2 레이아웃 규칙 6개를 정리해 두었습니다.

주의할 점은 이 규칙들 중 여러 개가 **빌드는 성공하는데 런타임에서 조용히
실패한다**는 것입니다. 증상은 언제나 같습니다 — 창은 열리지만 "disconnected"라고만
표시됩니다. 사이드카의 stderr는 코어 오류가 나타나는 유일한 자리(stdout은
프로토콜 전용)이므로, UI에 로그 스트립을 두고 정확한 오류 메시지를 띄우는 것이
중요합니다.

---

## 검증 / Verification

```bash
python -m compileall -q src
python -m pytest tests -q                    # 238 passed
python -m pytest tests -q                    # 404 passed
python scripts/check_all.py --fast           # 3 checks
cd app && npm test                           # 54 passed (Rust 불필요)
```

TypeScript 프로토콜 테스트가 Rust·Tauri·Python 없이 도는 것은 의도된 설계입니다.
`LineTransport` 인터페이스로 전송 계층을 주입하므로 계약은 빌드 도구가 없어도
검증됩니다.

---

## 다음 단계 / Next Steps

**Tauri UI에서 완료** (Phase 1–5)
1. ~~프로젝트 폴더 선택기~~ ✅ (`sandbox.start`의 `path`)
2. ~~provider/model 설정 패널~~ ✅ (`bind_provider`)
3. ~~샌드박스 시작/중지 버튼~~ ✅
4. ~~어시스턴트 텍스트 마크다운 렌더링~~ ✅ (`markdown.ts` 파서 + `MarkdownText.tsx`)
5. ~~커스텀 모델 + 커스텀 엔드포인트(base_url)~~ ✅ (모델 자유 입력 + `bind_provider{base_url}`)

**남은 것 (우선순위 순)**
- **실제 호스팅 모델로 성공하는 end-to-end 턴 1회** — 턴 경로는 라이브로 검증됨(OpenRouter가 제공자 오류를 그대로 반환, 로컬 mock 엔드포인트로 성공 턴 완주). 남은 건 호스팅 모델의 성공 응답뿐: OpenRouter 키 한도 상향/교체 필요. 마크다운도 라이브 트랜스크립트로 1회 확인 필요
- composer의 model 칩 / Attach 버튼 활성화, `/`·`@` 힌트 처리
- Files 트리에 디렉터리 그룹화 (`TreeEntry.kind`는 이미 `"dir"` 지원)

**대기 없이 가능**
- `read_file` offset/limit, `edit_file` replace_all
- timeout `timeout_ms` 단위 통일
- `http_request` 파일 다운로드
- 스키마/레지스트리 단일 소스화
- 턴별 출력 예산
- **Tkinter 채팅 버블 폭 수정** — React UI는 `fit-content`로 이미 해결됨
