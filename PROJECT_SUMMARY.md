# TONYAgent — Project Summary

**Updated:** 2026-09-27 · **Tests:** Python 197 passed, TypeScript 13 passed

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
| Tauri 프론트엔드 / Tauri UI | 🚧 | 스캐폴드 완료, **빌드 블로커 (§ Blocker)** |
| 테마 / Theme | ✅ | 라이트/다크/시스템, 토큰 기반 |
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

> 도구 실행 버그는 프로젝트 내내 한 번도 실행된 적이 없던 상태였습니다.
> 이전 문서에서 "미검증"으로 남아 있던 항목이 실제로는 실재하던 버그였습니다.

---

## Blocker: MSVC 빌드 도구

Rust는 설치됨 (`rustc 1.98.1`, `~/.cargo/bin` PATH 등록). WebView2 런타임도
있음 (154.0.4258.37).

하지만 **`link.exe`가 없어 Tauri 빌드가 불가능**합니다:

```
error: linker `link.exe` not found
  = note: please ensure that Visual Studio 2017 or later, or Build Tools for
          Visual Studio were installed with the Visual C++ option
```

**해결:** Visual Studio Build Tools for VS 2022 — "데스크톱 개발을 위한 C++"
워크로드. 상세 절차는 `NEXT_SESSION.md` §4 참고.

---

## 검증 / Verification

```bash
python -m compileall -q src
python -m pytest tests -q                    # 197 passed
python scripts/check_all.py --fast           # 3 checks
cd app && npm test                           # 13 passed (Rust 불필요)
```

TypeScript 프로토콜 테스트가 Rust·Tauri·Python 없이 도는 것은 의도된 설계입니다.
`LineTransport` 인터페이스로 전송 계층을 주입하므로 계약은 빌드 도구가 없어도
검증됩니다.

---

## 다음 단계 / Next Steps

**MSVC 설치 완료 후**
1. `cargo build` 스모크 테스트
2. `app/src-tauri/` 작성
3. PyInstaller로 sidecar 번들링
4. React UI 작성 → `npm run tauri dev`

**대기 없이 가능**
- `read_file` offset/limit, `edit_file` replace_all
- timeout `timeout_ms` 단위 통일
- `http_request` 파일 다운로드
- 스키마/레지스트리 단일 소스화
- 턴별 출력 예산
- **채팅 버블 폭 수정** (미완료 — 픽셀 측정 필요)
