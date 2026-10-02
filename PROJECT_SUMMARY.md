# TONYAgent — Project Summary

**Updated:** 2026-10-02 · **Tests:** Python 590 passed, 7 skipped
(Docker 꺼져 있으면: 589 passed + 1 failed), TypeScript 319 passed
**Build:** Tauri MSI + NSIS installers produced; app verified running end to end
(`decorations: false` — 시스템 타이틀 바를 빼고 앱이 직접 그리며, 우클릭/F10으로
**OS의 시스템 메뉴**를 열어 이동·크기 조절을 그대로 씁니다)

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
| 멀티 프로바이더 / Multi-Provider | ❌ | **OpenRouter 단일 provider** — Anthropic·Gemini dialect는 삭제(`fe1e470`). 프로바이더를 늘리기보다 실제로 쓰는 경로 하나를 확실히 두는 쪽을 택함 |
| 스트리밍 채팅 / Streaming Chat | ✅ | 토큰 단위 스트리밍, 도구 실행 표시 |
| thinking 패널 / Thinking panel | ✅ | 모델의 사고를 답변과 **별도 채널**(`reasoning.delta`/`reasoning.completed`)로 받아 별도 표시. 스트리밍 중 열림 → 완료 시 접힘. 읽는 사람이 직접 펼친 패널은 접히지 않음 |
| effort 선택 / Reasoning effort | ✅ | 모델별로 effort를 고르는 다이얼. **effort 목록이 있는 모델에만** 표시 — 조작할 수 없는 컨트롤은 장식이다 |
| 대화 목록·이름 변경 / Conversations | ✅ | 디스크에 저장되는 대화 목록, 인라인 이름 변경(빈 이름 거부), 복제, 우클릭/⋯ 메뉴 |
| 파일 도구 / File Tools | ✅ | read, write, edit, delete, list_dir, `sandbox_read_file`, `sandbox_list_files` |
| 검색 도구 / Search Tools | ✅ | grep (스트리밍, context_lines), glob (max_results) |
| 쉘 도구 / Shell | ✅ | execute_command — 샌드박스 미기동 시 fail-closed |
| 네트워크 도구 / Network | ✅ | http_request, SSRF 가드(내부 IP 차단) |
| 브라우저 도구 / Browser | ✅ | navigate, click, type, eval, screenshot, get_text, wait_for, scroll, snapshot |
| Docker 샌드박스 / Sandbox | ✅ | 단일 프로세스 RPC, pids/cap/tmpfs/ulimit 강화 |
| 헤드리스 코어 / Headless Core | ✅ | `AgentSession` + `EventBus`, GUI 무의존 |
| IPC 프로토콜 / Sidecar | ✅ | stdio JSONL, 25개 메서드, 16개 이벤트 |
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
python -m pytest tests -q                    # 590 passed, 7 skipped (Docker up)
python scripts/check_all.py --fast           # 3 checks
cd app && npm test                           # 319 passed (Rust 불필요)
python scripts/verify_composer_pass.py       # 패키징된 앱 DOM: 전송 아이콘, 첨부,
                                             # 모델 메뉴, tool call 예산
python scripts/verify_pass_b.py              # 패키징된 앱 실측: rail 정렬, 자체 타이틀
                                             # 바, 캡션 권한, 자유 입력 예산
python scripts/verify_system_menu.py         # 실제 키/마우스로 OS 시스템 메뉴를 열고
                                             # 항목과 Enable 상태를 화면에서 읽음
python scripts/mutate_pass_b.py              # 결함을 되살려 테스트가 빨개지는지 확인
```

TypeScript 프로토콜 테스트가 Rust·Tauri·Python 없이 도는 것은 의도된 설계입니다.
`LineTransport` 인터페이스로 전송 계층을 주입하므로 계약은 빌드 도구가 없어도
검증됩니다.

`npm test`는 `tsc -p tsconfig.test.json && node --test ".tmp/**/*.test.js"` 한 줄입니다.
`tsconfig.test.json`은 앱의 `tsconfig.json`을 상속하므로 **테스트도 앱과 같은 규칙으로
타입 체크**되며(미사용 변수를 넣으면 빌드가 실패합니다 — 확인함), 테스트 파일 이름은
`package.json`에 적혀 있지 않아도 자동으로 실행됩니다.

컴포넌트 테스트는 jsdom 위에서 도는데 두 가지 전제가 있습니다. `test-dom.ts`는
react-dom보다 **먼저** import되어야 하고(react-dom이 import 시점에 브라우저 여부를
결정합니다), 컴포넌트의 상대 import에는 `.js` 확장자가 있어야 합니다(Vite는 없어도
되지만 Node는 안 됩니다).

**Docker 테스트 하나는 항상 실패합니다.** Docker 데몬이 필요한 것이지 버그가
아닙니다.

---

## 다음 단계 / Next Steps

**Tauri UI에서 완료** (Phase 1–10)
1. ~~프로젝트 폴더 선택기~~ ✅ (`sandbox.start`의 `path`)
2. ~~provider/model 설정 패널~~ ✅ (`bind_provider`)
3. ~~샌드박스 시작/중지 버튼~~ ✅
4. ~~어시스턴트 텍스트 마크다운 렌더링~~ ✅ (`markdown.ts` 파서 + `MarkdownText.tsx`)
5. ~~커스텀 모델 + 커스텀 엔드포인트(base_url)~~ ✅ (모델 자유 입력 + `bind_provider{base_url}`)
6. ~~대화 목록~~ ✅ (`conversations.*`)
7. ~~thinking 패널 + effort 선택~~ ✅ (`reasoning.*`)
8. ~~대화 이름 변경·복제~~ ✅
9. ~~전송 아이콘·파일 첨부·모델 선택·턴당 tool call 한도~~ ✅ (`send`의 content parts, `models.list`, `tools.get`/`tools.set`)

**남은 것 (우선순위 순)**
- **실제 호스팅 모델로 성공하는 end-to-end 턴 1회** — 턴 경로는 라이브로 검증됨(OpenRouter가 제공자 오류를 그대로 반환, 로컬 mock 엔드포인트로 성공 턴 완주). 남은 건 호스팅 모델의 성공 응답뿐: OpenRouter 키 한도 상향/교체 필요
- **thinking 패널·effort 다이얼의 실앱 확인** — jsdom 테스트로는 통과했지만, 패키징된 앱에서 실제로 접히고 펴지는지는 아직 눈으로 안 봤습니다
- `App.tsx`가 여전히 창 전체를 담고 있습니다. 프로토콜 상태 훅과 대화 목록 로직을 떼어내야 컴포넌트 단위 테스트가 쉬워집니다
- ~~composer의 model 칩 / Attach 버튼~~ ✅ (model 칩 = `models.list` 기반 필터 메뉴, Attach = 멀티모달 첨부). 남음: `/`·`@` 힌트 처리
- Files 트리에 디렉터리 그룹화 (`TreeEntry.kind`는 이미 `"dir"` 지원)
- **Tkinter UI** — 10개 단계 동안 한 번도 손대지 않았습니다. 성숙한 경로이고 여전히 유효합니다

**대기 없이 가능**
- `read_file` offset/limit, `edit_file` replace_all
- timeout `timeout_ms` 단위 통일
- `http_request` 파일 다운로드
- 스키마/레지스트리 단일 소스화
- 턴별 출력 예산
- **Tkinter 채팅 버블 폭 수정** — React UI는 `fit-content`로 이미 해결됨

---

## 최근 추가분: composer pass

네 개의 "coming soon" 플레이스홀더를 실제 기능으로 교체했습니다. 기능별로 커밋
`698b022` (전송 아이콘) · tool budget · model picker · attachments.

| 기능 | 코어 계약 | 비고 |
|---|---|---|
| 전송 아이콘 | — | `"Continue"` 텍스트 버튼 → `aria-label="Send"` 아이콘. Stop은 텍스트 유지 |
| 파일 첨부 | `send {text, attachments}` | **바이트가 메시지 안으로**. 이미지는 `image_url` 데이터 URL, 텍스트는 파일명이 붙은 part |
| 모델 선택 | `models.list` | 레지스트리 시드 5개가 아니라 **제공자의 실제 목록**(실측 462개) |
| tool call 한도 | `tools.get` / `tools.set` | 라운드가 아니라 **개별 호출** 기준, 기본 10, `Tool call 3/10` |

### 조용히 깨질 뻔했던 것 두 가지

**토큰 추정이 멈췄습니다.** `ChatMessage.content`를 `str | list[dict]`로 넓히면
`estimate_tokens`의 `len(m.content or "")`가 *문자 수*가 아니라 *part 개수*를
세게 됩니다. 첨부된 4000자 문서가 토큰 0이 됩니다. 예외가 나지 않으니 로그에도
아무것도 안 남습니다 — 그냥 budget이 계산을 멈춥니다. 유니온이 된 필드에 `len()`이
붙어 있으면 스택 트레이스 없는 실패가 된다는 점을 기억해 둘 만합니다.

**`[object Object]`가 사용자의 기록에 찍힙니다.** 첨부가 있는 대화는 content
parts로 저장·복원되고, 이를 문자열을 기대하는 컴포넌트에 그대로 넘기면 됩니다.
`app/src/attachments.ts`의 `textFromContent`만 이 사실을 알고 있습니다.

### 400을 유발하는 지뢰

예산이 거절한 tool call은 **버리지 않습니다.** 바로 위 assistant 메시지가 이미
`tool_calls` 배열에 선언했기 때문에, 대응하는 결과가 없으면 OpenAI 계열
엔드포인트가 **다음** 메시지를 400으로 거절합니다. 즉 거절을 조용히 처리하는
"깔끔한" 구현이 보이는 실패를, 사용자가 볼 수 없는 한 요청 뒤로 미룹니다.
거절 자체도 "error"가 아니라 현재 한도와 함께 모델에게 설명합니다.

### live에서 확인한 것과 하지 않은 것

패키징된 앱의 실제 DOM을 읽어 네 컨트롤이 모두 배선되어 있음을 확인했습니다
(모델 462개, 필터, 예산 프리셋 5개, 활성 첨부 버튼과 그 뒤의 숨겨진 input,
"Send" 아이콘). 콘솔 에러 0건.

의도적으로 live에서 하지 않은 것: **모델 전환과 예산 변경**은 사용자의
`config.toml`을 덮어쓰므로 단위 테스트로 증명했습니다.

### 이번에 만난 함정

- **패치 스크립트로 소스 파일을 덮어씀.** `write_file`의 대상 경로가
  `src/tonyagent/providers/base.py`인데 내용이 Python 패처였습니다. `git status`로
  잡아 `git checkout --`로 복구했습니다. 패치 스크립트는 항상 `scripts/`에.
- **게터를 구조분해하면 한 번만 읽힙니다.** 모델 선택기 테스트 하네스가 `loads`를
  getter로 돌려줬는데, `const { loads } = harness`는 **구조분해하는 그 시점에**
  값을 읽습니다. 클릭 이후의 모든 단언이 클릭 이전의 숫자를 봤고, 컴포넌트가
  로딩에 실패한 것처럼 보였습니다. 하네스의 카운터는 값이 아니라 함수입니다.
- **렌더 중 setState.** `ToolBudgetControl`이 파생 상태를 만들려고
  `useState` + `if (value !== shown) setShown(value)`를 썼더니, 테스트 스위트가
  4초에서 121초로 늘고 `RangeError`로 죽었습니다. prop을 그대로 읽는 게 정답이었고
  파생 상태는 애초에 필요 없었습니다.
- **jsdom에 `DataTransfer`가 없습니다.** `FileReader`도 `test-dom.ts`의 전역 목록에
  없어서 첨부 테스트 전부가 "FileReader is not defined"로 죽었는데, 이게 마치
  기능이 깨진 것처럼 보입니다. 둘 다 이제 목록에 있습니다.
- **CSS 한 줄에 리터럴 `\n`.** 개행 이스케이프가 섞인 패치 문자열 때문에 두
  selector가 한 줄에 붙고 빌드가 "Unclosed block"으로 죽었습니다. 파일은 CRLF인데
  그 한 줄만 LF여서 `\r\n`으로 만든 앵커가 통째로 misses — 문자열 매칭 대신 줄
  번호로 고쳤습니다.
- **`audit_reduced_motion.py`가 두 번 값을 잡아냈습니다.** 새 표면 두 개
  (`.budget-popover`, `.modelpicker`) 모두 reduced-motion 취소를 `.thing`이 아니라
  `.thing[data-state="open"]` 형태로 써야 했습니다. 한 클래스짜리는 명시도가
  낮아서 모션이 계속 돕니다. 둘 다 배포 전에 잡혔습니다.
- **`ModelPicker`의 fetch 가드는 중요해 보이지 않습니다.** 효과가 `onLoad`에
  의존하고, 호출부의 `onLoad`는 매 렌더 새 인라인 arrow입니다. `loaded` ref를
  지우면 fetch → 재렌더 → 새 arrow → 다시 fetch로 영원히 돕니다. 뮤테이션
  테스트는 실패하지 않았습니다 — 테스트가 끝나지 않았습니다.

---

## 최근 추가분: pass B — 팝오버 · 커스텀 한도 · 자체 타이틀 바

사용자가 실제로 겪은 네 가지입니다. 커밋은 둘: `16edd40`(팝오버 + 자유 입력),
`08b3bfb`(타이틀 바 + rail 정렬). **단언이 아니라 측정**으로 확인했습니다.

| 항목 | 무엇이 틀렸는가 | 무엇을 바꿨는가 | 실측 |
|---|---|---|---|
| 사이드바 다시 열기 버튼 | `.rail-toggle`의 `align-self: flex-start`가 rail의 `align-items: center`를 덮어씀. 펼친 상태에서는 버튼이 `width: 100%`라 보이지 않고, 접힌 상태에서만 드러남 | 규칙을 `.rail.rail-expanded .rail-toggle { align-self: stretch }`로 좁힘 | 접힌 rail: 토글 x=0 → **x=16** (아이콘과 일치) |
| 모델 검색창을 누르면 창이 닫힘 | 캡처 단계 `pointerdown`이 **누가 눌렸는지 확인하지 않고** 항상 닫음. 캡처는 DOM보다 먼저 firing | 규칙을 `useDismiss.ts` 한 곳으로. 질문을 "누른 곳이 이 표면 안인가"로 바꿈 | 필터 눌러도 `data-state="open"` 유지 |
| tool call 한도 커스텀 입력 | 프리셋 5개뿐 | 프리셋 옆에 1–200 자유 입력(Enter 또는 `Set`), **입력 중에는 클램프하지 않고 거절** | 0 입력 → 팝오버 안에 사유 표시, 아무것도 적용 안 됨 |
| 시스템 기본 title bar | 시스템 캡션 위에 이미 topbar가 있어서 이중 바 | `decorations: false` + 자체 캡션 3버튼, `topbar`가 `.app`의 첫 자식으로 전체 폭 | `is_decorated() === false`, 버튼 우측 1108/1154/1200 |

### 조용히 실패하던 것 세 가지

- **`core:window:default`는 getter만 줍니다.** `minimize` / `toggle_maximize` /
  `close` / `start_dragging`은 `capabilities/default.json`에 각각 명시해야
  합니다. 빠지면 캡션은 콘솔에 로그만 남기는 죽은 버튼 3개가 되고, 창은
  움직이지 않습니다.
- **`data-tauri-drag-region="deep"`** 가 필요합니다. `"true"`나 속성만 있는
  형태는 **직접 누른 곳**에서만 발동하므로 사실상 빈 여백에서만 창이
  움직입니다. 구현은 `tauri-2.12.0/src/window/scripts/drag.js`.
- **`.topbar`는 `.main`을 벗어났습니다.** 이제 `.app`의 첫 자식이고
  `grid-column: 1 / -1`이라 캡션이 **창**의 오른쪽 끝에 붙습니다. transcript
  열에 두면 Files 패널이 그 열을 덮는 순간 캡션이 통째로 가려집니다. `.app`은
  2행 grid이고 **나머지 in-flow 자식은 전부 `grid-row: 2`를 명시**해야 합니다 —
  자동 배치면 Files 패널이 없는 빌드에서 rail이 타이틀 바 행에 들어가 창 전체가
  42px 아래로 밀립니다.

### 이번에 만난 함정

- **캡처 단계 `pointerdown`은 DOM이 "누가 눌렸는지" 알기 전에 발동합니다.**
  그래서 "창 안인지" 검사 하나가 없으면, 메뉴를 *열어 주는* 클릭이 메뉴를 닫습니다.
  표면을 감싸는 ref는 패널이 아니라 **wrapper**여야 합니다 — 칩과 버튼이 안에
  있기 때문입니다.
- **`align-self` 하나가 테스트로는 안 잡힙니다.** CSS 텍스트로는 멀쩡하고
  캐스케이드에서만 어긋납니다. 그래서 `layout.test.ts`는 텍스트 매칭이 아니라
  **해소된 규칙**을 읽습니다.
- **스타일시트를 읽는 테스트는 reduced-motion 블록도 벗겨야 합니다.**
  `audit_reduced_motion.py`가 모든 애니메이션의 취소를 요구하므로
  `.sidebar`의 마지막 선언은 `animation: none`입니다. 주석만 지우면
  `.sidebar`가 애니메이션으로 해소되어 `top` 단언이 전부 실패합니다.
- **Windows에서 TypeScript 스위트에 flaky 테스트 하나.** `ComposerAttach`
  strip 테스트 4개가 전체 실행 5회 중 1회 정도 `0 !== 1`로 떨어집니다. 지난
  두 패스의 변경을 전부 stash한 상태에서도 재현되므로 **기존 문제**입니다.
  믿기 전에 다시 실행하고, 쫓지 마세요.
- **대소문자만 다른 파일명.** `windowControls.ts`와 `WindowControls.tsx`가
  나란히 있으면 Windows에서만 TS1149/TS1261입니다. 훅은 `useWindowControls.ts`.
- **앱이 떠 있으면 빌드가 `PermissionDenied`로 죽습니다**(`tauri-build`
  `lib.rs:164`). 빌드 **전에** `tonyagent-app.exe`와 `msedgewebview2.exe`를
  먼저 죽이세요.
- **두 검증기가 같은 칩을 누릅니다.** `verify_pass_b.py`는 모델 메뉴를 열어둔
  채로 끝나고, `verify_composer_pass.py`는 그 칩을 눌러 토글하므로
  `send_is_icon`/`model_menu`이 근거 없이 실패합니다. 중간에
  `location.reload()`을 한 번 돌리세요.

---

## 최근 추가분: 창 시스템 메뉴 (F10 · 우클릭)

`decorations: false`는 타이틀 바만 없앤 게 아니었습니다. **Alt+Space 메뉴, 우클릭
메뉴, 그리고 Move·Size**를 함께 가져갔습니다. 뒤의 둘은 **OS가 돌리는 드rag
루프**라서, 이게 없으면 창을 놓지도 크기도 못합니다 — React 컴포넌트로 대체할
수 없습니다.

tao는 `WS_SYSMENU`를 **지우지 않습니다**(창 스타일은 유지하고 `WM_NCCALCSIZE`로
클라이언트 영역만 확장). 즉 올바른 메뉴는 OS가 이미 갖고 있고, 우리는
**달라고 하기만 하면 됩니다** — `GetSystemMenu` + `TrackPopupMenu` 두 호출
([system_menu.rs](app/src-tauri/src/system_menu.rs)).

### Alt+Space이 아닌 F10

이 컴퓨터의 Alt+Space은 **Copilot의 전역 핫키**입니다. OS가 창에 닿기 전에
먹어버리므로, 거기 묶으면 **절대 실행되지 않는 코드**가 됩니다. Windows가 같은
메뉴에 부여한 다른 이름이 F10이고, 실측 기준으로 페이지에 도달하는 키는
F10 하나입니다(F9·F11·M·Space·Escape는 WebView2가 가로챕니다).

> 부수 발견: WebView2는 **`event.code`를 빈 문자열로** 줍니다. `code`만 읽는
> 훅은 아무것도 못 봅니다. `code` 또는 `key`를 모두 봐야 합니다.

### 메뉴를 화면에서 읽는 법 (틀린 예세 가지)

검증기는 실제 키/마우스를 보내고, 추적 중인 메뉴를 `#32768` 클래스 top-level
윈도우로 찾아 항목과 Enable 상태를 읽습니다. 여기서 세 번 틀렸고, 매번
**화면에 분명히 있는 메뉴를 "없음"으로 보고**했습니다:

1. **`GW_OWNER`로 구분하면 안 됩니다.** 이 앱의 시스템 메뉴는 owner가 **0**으로
   읽힙니다. 메뉴 윈도우는 `TrackPopupMenu`을 호출한 스레드가 만드므로 **프로세스**
   로 구분해야 합니다(웹뷰 컨텍스트 메뉴는 `msedgewebview2.exe` 것).
2. **인식하지 못한 메뉴는 그냥 남습니다.** 타이틀 바를 덮고 다음 우클릭을
   삼켜서, 그 다음 케이스가 "메뉴 없음"을 보고합니다. 해제는 `EndMenu`
   (Escape는 포커스를 가진 곳으로 갑니다).
3. **항목은 7개이고, 회색 규칙은 반대로 보입니다.** index 5가 구분선이고,
   **비활성인 항목은 "아무것도 하지 않을" 쪽**입니다 — 일반 창에서는
   **Restore**, 최대화 창에서는 **Maximize**. 라벨은 지역화되고 니모닉이 붙으니
   **위치로** 검증하고, `maximized`는 **창의 `WS_MAXIMIZE`**로 읽습니다
   (창이 얼마나 큰지로 추정하지 말 것 — 이 창은 work area를 넘겨 dragged된
   상태인데 maximization은 아니고, 메뉴도 그에 동의합니다).

### 왜 Rust였나

앱 커맨드는 capability 파일이 있는 순간 ACL 검사를 받습니다. 이름이 세 곳에
일치해야 합니다: `lib.rs`의 `show_system_menu`, `build.rs`의
`AppManifest::new().commands(&[...])`( autogenerated 권한 파일 생성), 그리고
`capabilities/default.json`의 **`allow-show-system-menu`(하이픈)**. 셋 중 하나라도
틀리면 메뉴는 열리지 않고 이유만 콘솔에 남습니다.

`WM_SYSCOMMAND` + `SC_KEYMENU`는 **작동하지 않습니다.** OS가 Alt+Space에 대해
스스로 보내는 메시지라 가장 당연해 보이지만, 앱 밖에서 직접 포스트해도 아무 일도
없습니다. frameless tao 창은 그걸 `DefWindowProc`에 넘기지 않습니다.

### 실측 결과

```
[PASS] f10                          메뉴 열림, 7개 항목, 위치 = 커서
[PASS] right_click_on_the_bar       메뉴 열림, 위치 = 클릭 지점
[PASS] right_click_on_a_caption_button
[PASS] right_click_off_the_bar      앱 메뉴 없음 (웹뷰 것만)
[PASS] move_is_the_systems_own_loop  (-2887,-7) → (-2849, 0)  복구 완료
[PASS] size_is_the_systems_own_loop  세로 994 → 1026        복구 완료
[PASS] the_window_ends_up_where_it_started
```

Move와 Size는 F10 → 니모닉 → 화살표 6회 → Enter로 실제 구동해 사각형을 비교하고,
**사용자가 두 monitor 중 어느 쪽에 창을 두든 원래 자리로 되돌려 놓고** 끝냅니다.
포커스와 커서도 `finally`에서 원래대로 돌려놓습니다 — 다른 모니터에서 강의를
듣는 사람 컴퓨터에서 테스트할 수 있는 최소한의 예의입니다.
