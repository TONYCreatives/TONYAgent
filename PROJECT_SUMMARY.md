# TONYAgent — Project Summary

**Current architecture (2026-10-13):** Python `pywebview` desktop host + React/Vite frontend + separate headless Python core (JSONL over stdio). The core currently registers **41 tools** and **2 providers** (OpenRouter and OpenCode Go).

**Verification note:** Historical test totals and build observations below refer to the dated snapshots in their entries; they are not a current test report. See the latest handoff section at the end before using any historical counts.

---

## 프로젝트 개요 / Project Overview

### English

**TONYAgent** is a local-first desktop AI agent. It connects to user-provided LLM
API keys, works in a selected project folder, and exposes tools for file
operations, shell, search, network and browser automation. Docker and WSL provide
the supported isolated execution backends; local mode refuses sandbox-required
execution, and Windows Sandbox is currently an unimplemented stub.

The current desktop app uses a **Python `pywebview` host**, a **React/Vite UI**,
and a separate headless Python core. The host serves the frontend, exposes a
narrow JavaScript bridge and owns the core child process. The UI and core
communicate through the host using JSONL over stdio. There is no current Tauri or
Tkinter frontend.

### 한국어

**TONYAgent**은 로컬 퍼스트 데스크톱 AI 에이전트입니다. 사용자가 제공한 LLM API
키를 사용하고, 선택한 프로젝트 폴더에서 파일·쉘·검색·네트워크·브라우저 도구를
실행합니다. 격리 실행은 Docker와 WSL을 지원합니다. 로컬 모드는 샌드박스가 필요한
실행을 거부하며 Windows Sandbox는 아직 동작하지 않는 스텁입니다.

현재 데스크톱 앱은 **Python `pywebview` 호스트**, **React/Vite UI**, 별도 헤드리스
Python 코어로 구성됩니다. 호스트가 프론트엔드를 서빙하고 제한된 JS 브리지를
제공하며 코어 자식 프로세스를 소유합니다. UI와 코어는 호스트를 통해 stdio의
JSONL로 통신합니다. 현재 Tauri 또는 Tkinter 프론트엔드는 없습니다.

---

## 핵심 기능 / Core Features

| 기능 / Feature | 상태 | 설명 |
|---|---|---|
| Multi-provider | ✅ | OpenRouter and OpenCode Go are registered provider adapters |
| 스트리밍 채팅 / Streaming Chat | ✅ | 토큰 단위 스트리밍, 도구 실행 표시 |
| thinking 패널 / Thinking panel | ✅ | 모델의 사고를 답변과 **별도 채널**(`reasoning.delta`/`reasoning.completed`)로 받아 별도 표시. 스트리밍 중 열림 → 완료 시 접힘. 읽는 사람이 직접 펼친 패널은 접히지 않음 |
| effort 선택 / Reasoning effort | ✅ | 모델별로 effort를 고르는 다이얼. **effort 목록이 있는 모델에만** 표시 — 조작할 수 없는 컨트롤은 장식이다 |
| 대화 목록·이름 변경 / Conversations | ✅ | 디스크에 저장되는 대화 목록, 인라인 이름 변경(빈 이름 거부), 복제, 우클릭/⋯ 메뉴 |
| 파일 도구 / File Tools | ✅ | read, write, edit, delete, list_dir, `sandbox_read_file`, `sandbox_list_files` |
| 검색 도구 / Search Tools | ✅ | grep (스트리밍, context_lines), glob (max_results) |
| 쉘 도구 / Shell | ✅ | execute_command — 샌드박스 미기동 시 fail-closed |
| 네트워크 도구 / Network | ✅ | http_request, SSRF 가드(내부 IP 차단) |
| 브라우저 도구 / Browser | ✅ | navigate, click, type, eval, screenshot, get_text, wait_for, scroll, snapshot |
| Sandbox | ✅ | Docker and WSL isolation backends; local mode is fail-closed for isolated execution; Windows Sandbox remains an unimplemented stub |
| 헤드리스 코어 / Headless Core | ✅ | `AgentSession` + `EventBus`, GUI 무의존 |
| IPC 프로토콜 / Sidecar | ✅ | stdio JSONL, 41개 메서드(`headless/server.py`의 핸들러 표 기준, `plan.get`만 프런트엔드 타입에 없음), 19개 이벤트(`core/events.py::EventType`) |
| 데스크톱 UI / Desktop UI | ✅ | React/Vite frontend hosted in a native `pywebview` window; Python host owns the headless core process |
| Theme | ✅ | Current desktop UI is dark-only and uses shared CSS design tokens |
| 마크다운 렌더링 / Markdown | ✅ | 어시스턴트 텍스트를 토큰 트리로 파싱해 React 엘리먼트로 렌더 (HTML 문자열 없음, 위험 URL/원격 이미지 차단) |
| 커스텀 모델·엔드포인트 / Custom model + endpoint | ✅ | 모델 필드 자유 입력(`<datalist>` 제안 + 임의 id 허용), `bind_provider`의 선택적 `base_url` — `custom` provider를 UI에서 사용 가능하게 함 |
| 키링 보안 / Keyring | ✅ | OS 키링, 정확한 키 길이 검증 |

---

## 아키텍처 / Architecture (current overview above; implementation history below)

```
┌──────────────────────────────┐
│ React + Vite desktop UI      │
└──────────────┬───────────────┘
               │ pywebview bridge
┌──────────────▼───────────────┐
│ Python window host           │── serves app/dist/
│ owns the core child process  │
└──────────────┬───────────────┘
               │ JSONL over stdio
┌──────────────▼───────────────┐
│ Headless AgentSession        │
│ conversations · events · tools│
└──────┬────────────────┬──────┘
       │                │
┌──────▼───────┐ ┌──────▼─────────┐
│ OpenRouter / │ │ Docker / WSL   │
│ OpenCode Go  │ │ sandbox backends│
└──────────────┘ └────────────────┘
```

### 왜 이 구조인가 / Why

코어를 별도 프로세스로 분리해 UI와 에이전트 세션의 lifecycles 및 failures를
독립적으로 관리합니다. stdio JSONL은 포트 충돌 없이 요청·응답과 이벤트를
전달하고, React UI는 host bridge를 통해 필요한 좁은 API만 사용합니다.
이 경계 덕분에 Python GUI toolkit을 코어에서 불러올 필요가 없습니다.

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

## 창: Tauri → pywebview (2026-10-10, historical)

이 섹션은 Tauri에서 `pywebview`로 옮긴 당시의 기록이며, 현재 상태를 설명하는 문서가 아닙니다. 지금 앱은 아래의 현행 아키텍처 요약을 따릅니다.

| 예전 | 지금 |
|---|---|
| `app/src-tauri/` (Rust 셸) | `src/tonyagent/window/host.py` |
| Tauri shell 플러그인이 사이드카를 스폰 | 호스트가 코어를 자식 프로세스로 소유 (`core.py`) |
| Tauri가 `dist/`를 바이너리에 임베드 | `assets.py`가 `app/dist/`를 127.0.0.1에서 서빙 |
| `invoke` + `@tauri-apps/plugin-*` | `window.pywebview.api` (`bridge.py`) |
| `data-tauri-drag-region="deep"` | `pywebview-drag-region` |
| CSP가 `tauri.conf.json`에 | CSP가 `index.html`의 `<meta>`에 |
| 아이콘이 `src-tauri/icons/`에 | 아이콘이 `app/icons/`에 (런타임에 읽음) |

**프로토콜은 그대로입니다.** JSONL, 요청 id, 응답 라우팅, `backend.ts`의
프레이밍과 `carriesSecret`은 한 줄도 바뀌지 않았습니다. 바뀐 것은 그 아래
전송 계층뿐이고, `LineTransport` 인터페이스가 그 경계입니다.

### 조용히 실패하던 것 세 가지

1. **문서가 준비되기 전의 `evaluate_js`는 실패하지 않고 교착됩니다.** 결과
   콜백이 오지 않아 기다리는 세마포어가 풀리지 않습니다. 펌프가 별도
   스레드라면 창이 뜨고 나서 영원히 말을 하지 않습니다. `Bridge.ready()`가
   그 문이고, 그 전까지 프레임은 버퍼에 쌓입니다.
2. **pywebview는 `dir(js_api)`를 훑어 공개 속성을 *평가*하고, 메서드가 아닌
   것은 재귀합니다.** `maximized`를 프로퍼티로 둔 것이 GUI 스레드 밖에서
   WinForms 핸들을 건드려 창을 교착시켰습니다. 이제 `Bridge`의 상태는 전부
   비공개이고, 공개 메서드가 곧 페이지의 API입니다.
3. **Tauri의 `"deep"`과 pywebview의 드래그 영역은 같지 않습니다.** pywebview는
   누른 요소에서 위로 올라가며 클래스를 찾으므로, 그대로 두면 캡션 버튼과
   모델 피커도 드래그 손잡이가 됩니다. 호스트가
   `DRAG_REGION_DIRECT_TARGET_ONLY = True`를 켜서 "클래스가 붙은 요소 자체를
   눌렀을 때만"으로 좁혔고, 그래서 클래스가 타이틀 바와 그 배경 영역에만
   있습니다. 그 집합은 `TopBar.test.tsx`가 고정합니다.

### 빌드

단계가 하나입니다: `app/dist`. `build_state.ps1`은 이제 프론트엔드만
판단하고, `Build TONYAgent.bat`도 스테이지가 하나입니다. 파이썬 파일을
고쳐도 프론트엔드는 다시 빌드되지 않습니다 — 창이 런타임에 `dist/`를 읽기
때문이고, 그 사실 자체가 테스트로 고정되어 있습니다
(`test_the_python_core_is_not_an_input_any_more`).

`Start TONYAgent (Tauri).bat`은 없어졌습니다. 두 런처의 차이는 "어느
스테이지를 건너뛸 수 있는가"였고, 스테이지가 하나면 그 차이도 없습니다.

### 바로가기, 그리고 창이 둘이던 것 (2026-10-10)

`scripts/make_shortcut.ps1`이 저장소 폴더에 `TONYAgent.lnk`를 만듭니다.
`Start TONYAgent (Prebuilt).bat`을 가리키고, `app/icons/icon.ico`를 아이콘으로
달고, 설명을 답니다. `-Destination "$env:USERPROFILE\Desktop"`을 주면 바탕화면에
만듭니다. `.lnk`는 gitignore 대상입니다 — 이 체크아웃의 절대 경로를 담고 있어서
그 기계에 대한 사실이지 프로젝트에 대한 사실이 아니고, 다른 기계로 가져갈 것은
파일이 아니라 스크립트입니다.

바로가기를 만들면서 "이걸 누르면 뭐가 열리지"를 확인했고, 답은 **창 두 개**였습니다.
`start "" python -m tonyagent.window`는 앱에 콘솔을 하나 더 줍니다 — `python`은
콘솔 서브시스템 프로그램이라 `start`가 *새 콘솔*을 할당합니다. 앱의 최상위 창을
열거해서 실제로 확인했습니다:

    1 console window(s): the app does have one beside its window.

`pythonw`는 콘솔이 없는 같은 인터프리터입니다. 런처가 이제 그것으로 시작하고,
같은 프로브가 `0 console window(s)`를 보고합니다 — 폼은 그대로, 제목도 그대로
`TONYAgent`입니다.

그 대가로 호스트는 stderr를 잃습니다. 호스트 자신의 로그 줄은 기동 실패가 이유를
말하는 곳이라, `host.has_console()`이 OS에 묻고(`GetConsoleWindow`) 콘솔이 없으면
`config.toml` 옆 `window.log`로 옮깁니다. 그 과정에서 측정한 두 가지는 그 전까지
반대로 가정하고 있던 것입니다:

1. **`pythonw`에서 `sys.stderr`는 `None`이 아닙니다.** 파이썬 3.13은 쓰기가 아무
   데도 닿지 않는 `TextIOWrapper`를 그냥 돌려줍니다. 뻔해 보이는 검사는 "콘솔이
   있다"고 결론 내고 로그를 아무도 읽지 않는 스트림에 남겨둡니다.
2. **Microsoft Store 파이썬은 `%APPDATA%`를 리디렉션합니다.** 파이썬은
   `%APPDATA%\TONYAgent\window.log`에 쓰고 `os.path.exists`는 `True`인데, 그
   경로를 보는 셸은 아무것도 찾지 못합니다 — 실제 파일은
   `AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\Roaming\TONYAgent\`
   에 있습니다. 앱 컨테이너 리디렉션이고 이 코드의 버그는 아니지만, 로그가 바깥
   프로세스가 찾을 자리에 없다는 뜻입니다.

`host.py`는 `sys`를 임포트한 적도 없었습니다. 그래서 이 함수의 첫 버전은 실패를
보이게 하려고 만든 함수 안에서 `NameError`를 냈고, 창이 뜨기 전에 프로세스가
죽었습니다. `python -m tonyagent.window --help` 테스트가 그걸 잡았습니다.

새 로그는 곧바로 경고를 하나 보고했는데, 코너가 `value=2`로 둥근 기동에서 나온
것이었습니다. `_startup`은 폼보다 먼저 도니 핸들이 없는 것이 정상이고, 일을 하는
것은 `shown`에서의 두 번째 시도입니다. 첫 시도는 이제 `debug`로 남기고 두 번째만
경고합니다.

### 레일의 마크를 없앴습니다 (2026-10-10)

앱의 글리프가 세 곳에 있었습니다: 작업 표시줄(`icon.svg`), 제목 표시줄의
모서리(`.topbar-mark`, 22px), 그리고 레일의 머리(`.rail-logo`, 32px). 앞의 둘이
앱의 마크입니다. 셋째는 남은 것이었습니다 — 마크가 모서리로 옮겨갔는데 이
복사본이 따라가지 않아서, 창이 같은 그림을 64px 떨어뜨려 두 번 그리고 있었고,
레일의 것이 두 번째 로고로 읽혔습니다.

- `IconRail.tsx`는 더 이상 그것을 그리지 않고 `AppMark`를 임포트하지도 않습니다.
  그 자리에는 왜 없는지에 대한 주석이 남아 있습니다. 아이콘 줄에서 비어 있는
  자리는 실수와 구별되지 않으니까요.
- `.rail-logo`는 `rail.css`에서 규칙째로 빠졌습니다. 아무도 그리지 않는 클래스는
  다음 사람이 실수로 재사용하는 클래스입니다.
- `IconRail.test.tsx`는 레일이 마크를 *그린다*고 단언하고 있었습니다 —
  `MARK_RECTS`와 위치까지 대조하면서요. 창이 로고를 두 개 그리고 있는 동안 내내
  통과하던 테스트가 바로 그것입니다. 이제는 음성 단언입니다: `.rail-logo` 없음,
  `.rail` 안에 `rect` 없음, 스트립의 첫 자식은 `.rail-btn`.

`rect` 쪽은 따로 짚을 만합니다: 레일이 그리는 글리프는 전부 `path`입니다 —
토글·검색·정지는 스트로크 외곽선이고 톱니는 채워진 실루엣 하나입니다 — 그러니
스트립 안의 `rect`는 마크의 두 획일 수밖에 없습니다.

**실행 중인 창에서 측정했습니다.** `scripts/verify_window.py`에 검사를 넣었고:

    the mark's corner: box 0,0 64x51 / glyph 22px at 21
    the rail draws no mark: corner 2 rects, first-run 2, rail 0 rects in 0 .rail-logo box(es)

모서리는 여전히 두 획을, 첫 화면도 여전히 두 획을 그리고, 레일은 상자도 없이
아무것도 그리지 않습니다.

**바로가기는 옮겨져도 됩니다.** `TONYAgent.lnk`는 저장소 폴더에 만들어졌다가
바탕화면으로 옮겨졌습니다. 바로가기는 상대 경로가 아니라 절대 대상과 자기
"시작 위치"를 들고 있으므로, 파일을 옮겨도 여는 것이 달라지지 않습니다.
`-Destination`은 처음부터 원하는 자리에 만들기 위한 것입니다.

### 사이드바의 발치 (2026-10-10)

레일이 열리는 패널 안의 두 가지입니다. 첫째는 읽은 것이 아니라 잰 것이고, 둘째는
보이는 것과 다른 일을 하던 버튼입니다.

#### 설정 버튼이 바닥에 없던 것

대화 목록이 비어 있을 때 — 새 창이 그렇습니다 — 발치를 아래로 밀 수 있는 유일한
요소가 렌더되지 않았기 때문입니다. `ConversationList`는 대화가 없으면
`.chatlist-rows` 대신 `.chatlist-empty`를 그리는데, `flex: 1`은 rows에만 있었습니다.
발치 위에서 남는 높이를 가져가는 것이 없었으니, 발치는 내용이 끝나는 자리에 그대로
앉았습니다.

**스타일시트만 읽으면 맞아 보입니다.** 패널은 `top: var(--topbar-h); bottom: 0`,
발치는 마지막 자식, rows는 `flex: 1`을 선언하고 있습니다. 그래서 실제 창에서
상자를 재었습니다:

    chats pane : panel 0,52 288x712 | rows MISSING | foot 0,218 287x55 | acts Clear conversation@227 Search project@227 Settings@227

`rows MISSING`이 답입니다 — 712px 패널 안의 218px. 이제 `.chatlist-empty`도
`flex: 1`이라 두 상태 중 정확히 하나가 자랍니다: 대화가 있으면 rows, 없으면 빈 상자.
고친 뒤:

    chats pane : panel 0,52 288x712 | rows MISSING | foot 0,709 287x55 | acts Search project@718 Settings@718

709 + 55 = 764, 패널의 아래 모서리입니다. `layout.test.ts`가 두 선언을 모두
단언하고, `scripts/verify_window.py`가 그 간격을 잽니다 — 렌더된 상자에 대한
사실이고, 스타일시트 테스트로는 볼 수 없기 때문입니다.

#### Clear를 없앴습니다

발치에서 Search·Settings 옆에 있던 휴지통 글리프였고, "이 대화 삭제"로 읽혔습니다
— 하는 일은 그것이 아니었지만요. 보고 있던 대화록을 비우고, 대화는 목록에 그대로
남겼습니다. 대화 삭제는 행 메뉴의 Delete이고, 그건 어느 행에 작용하는지 말합니다.

컴포넌트에서, `Props`에서, `App.tsx`에서(그것만 호출하던 `clear` 콜백과 그것의
disabled 상태만 먹이던 `messageCount`까지), 테스트 픽스처에서 빠졌습니다.
`ConversationList.test.tsx`는 발치가 정확히 `["Search project", "Settings"]`임을
단언합니다.

**코어의 `clear` 메서드는 그대로 있고, 이제 창에서 부르는 곳이 없습니다.** 정리
차원이 아니라 실제 결과입니다: 대화의 메시지를 비우는 조작이 이제 어디에도 없습니다.
대화를 통째로 지우는 것은 있고, New chat은 다른 대화를 시작합니다 — 하지만 비우기가
다른 자리에 속한다면, 그것은 조용히 남겨둘 버튼이 아니라 정해야 할 결정입니다.

### 폴더 하나씩 (2026-10-10)

폴더 체계가 모양을 바꿨습니다. 한 번에 프로젝트 폴더 하나, 대화는 자기가 말하는
폴더에 묶이고, **폴더를 바꾸면 열려 있는 대화가 따라옵니다** — 대화와 그 대화가
말하는 폴더가 서로 어긋날 수 없게요.

**사이드바는 이제 평평한 목록 하나입니다.** 예전에는 프로젝트마다 접히는 헤더
아래로 대화를 묶고 활성 프로젝트를 맨 위에 고정했습니다 — 프로젝트가 여럿 동시에
놀고 있었으니까요. 폴더가 하나면 묶을 것이 없습니다: `groupByProject`는 사라졌고,
테스트할 수 있게 내보낸 규칙 `rowsForFolder`가 지금 폴더의 대화만 그립니다. 다른
폴더에 파일된 대화는 **지워진 것이 아닙니다** — 다른 곳에 있을 뿐이고, 그 폴더로
돌아가면 다시 나옵니다. 필터가 필터인 이유가 그것입니다.

**폴더가 없으면 목록은 전부입니다.** 아직 기준이 될 것이 없으니까요. 대안 — 폴더
없는 대화만 보여주기 — 은 첫 실행을 빈 목록으로 맞이하면서 사용자의 진짜 대화를
아직 고르지 않은 폴더 뒤에 숨겨둡니다.

**헤더가 곧 폴더이고, 버튼입니다.** 목록의 범위를 말하고, 피커를 엽니다: 피커는
사라진 프로젝트 그룹 헤더에 매달려 있었으므로, 이게 없으면 채팅 페인에서 폴더를
바꿀 방법이 아예 없었습니다. 행이 있든 없든 그려집니다 — 처음엔 행에 매달았는데,
대화가 아직 없는 폴더가 헤딩도 피커도 그리지 않았고 창은 그것을 `MISSING`으로
보고했습니다.

**`conversations.move`가 생겼습니다**, 끝에서 끝까지: `ConversationStore.move`
(필드 하나, 쓰기 하나 — 대화는 무슨 폴더에 관한 것이든 파일 하나이므로 복사도
없고 id도 바뀌지 않습니다), 핸들러, 그리고 프론트엔드가 `chooseFolder`에서 폴더가
바인딩된 **뒤에** 부릅니다. 순서가 중요하고 단언되어 있습니다: 먼저 보내면 그
선택이 닿지 않은 폴더에 대화가 파일됩니다. 옮긴 대화가 열려 있는 것이면 핸들러가
코어 자신의 프로젝트도 따라 옮깁니다.

#### 그 기능이 찾은 버그, 기능보다 훨씬 큰

**코어의 응답이 창에 한 번도 닿은 적이 없었습니다.** `CoreProcess._read_stdout`이
모든 줄에서 종결자를 떼어내므로 호스트는 페이지에 *줄* 목록을 건네고,
`CoreBackend.ingest`는 개행으로 프레이밍합니다. 그대로 통과시키면 모든 응답이
버퍼에 쌓이고 잘리지 않아, 어떤 요청도 resolve되지 않았습니다.

그 모습: 창은 그려지고, "connected"라고 말하고, 멈춥니다. 모델 피커는 비어 있고,
상태 바는 "no provider", 첫 화면은 "No project folder", 그리고 보낸 요청은 응답을
기다리지 않는 셋뿐이었습니다(`state`, `tools.get`, `reasoning.list`). pywebview
이전 이후로 그랬고, 모든 테스트는 통과했습니다 — `backend.test.ts`의 가짜
트랜스포트가 *종결자가 붙은 날 stdout*을 밀어 넣기 때문입니다. 실제 호스트가 하지
않는 단 하나의 일이죠.

이 기능의 증상에서 출발해 찾았습니다: 새 헤딩이 `All chats`라고 말하는데 코어는
`project: ...\WebAIAgent`를 보고하고 있었습니다. 자취는 응답이 브리지에
도착하고(`[core] {"id": 1, "result": {...}}`), 푸시 경로가 페이지에 전달하고,
요청 목록이 `reasoning.list` 뒤에서 뚝 끊기는 것이었습니다. `backend.ts`의 한 줄이
종결자를 되돌려 놓고, `backend.test.ts`가 이제 호스트가 밀어 넣는 것과 똑같은 것 —
종결자 없는 줄 하나 — 을 밀어 넣으므로 이 이음매는 다시 썩지 않습니다.

그 뒤: 부팅 시 요청이 셋에서 **여덟**으로, 바에 모델과 provider가, 화면에 복원된
대화록이, 새 헤딩은 `WebAIAgent`.

### 탭, 그리고 대화를 지웠을 때 남던 것 (2026-10-10)

#### 탭이 이제 브라우저 탭입니다

레퍼런스의 칩이었습니다: 바 한가운데 떠 있는 30px 스타디움 — *컨트롤*의 모양이죠.
이제 브라우저가 자기가 보여주는 페이지에 주는 모양입니다 — 자기가 잘려 나온 띠의
높이, 위는 둥글고 **아래는 각지게** — 그래서 거기 있는 알약이 아니라 창의 위쪽에
붙어 있는 것으로 읽힙니다.

아래가 각진 것이 전부입니다. 아래 두 모서리에 반경을 주면 탭이 자기가 붙어 있는
변에서 떨어져 나오고, 다른 숫자가 들어간 칩이 됩니다. 위 두 모서리에 `--radius-xs`를
쓰고 더 큰 단계는 쓰지 않습니다: 브라우저 자신의 탭은 몇 픽셀만 둥글립니다. 모양이
일을 하고 반경은 모서리를 깎을 뿐이니까요.

실행 중인 창에서 쟀습니다, `verify_window.py`에 검사를 넣어서요:

    the tab's box: tab 72,0 233x51 in bar ..52: 1px from the bottom, radius 6px 6px 0px 0px

바 전체 높이, 아래 모서리는 바 자신의 것 위에(1px은 바의 테두리), 그리고 계산된
반경이 두 모서리가 0임을 보여줍니다 — 아래 두 짝이 `0`이라는 것을 볼 수 있는 유일한
방법입니다.

#### 대화를 지우면 창이 대화 없는 상태로 남았습니다

앱에서 보고된 것: 열려 있는 대화를 지우고 빈 상태로 오면, 바가 더 이상 존재하지 않는
대화의 이름을 계속 말합니다.

**제목이 버그가 아니었습니다.** 제목은 열려 있는 대화의 id로 목록에서 읽습니다.
그러니 지워진 대화의 이름을 말하는 바는 창이 아직 그 id를 들고 있다는 뜻인데 — 들고
있지 않았습니다. *아무것도* 들고 있지 않았습니다: `deleteConversation`이
`conversation`을 `""`로 두고 멈췄고, `""`로 찾으면 아무것도 없으니 탭은 앱 이름으로
돌아갔습니다.

진짜 피해는 한 걸음 더 나갔습니다. 대화 id가 없으면 `_persist`가 일찍 돌아서
(`if not self.conversations or not self.conversation_id`) 그 빈 상태에 타이핑한
메시지가 **어디에도 저장되지 않았습니다** — 그리고 코어의 delete 핸들러는 처음부터
무엇이 일어나야 하는지 말하고 있었습니다:

> 보고 있는 대화를 지우면 아무것도 안 보게 되는데, 그건 의도한 결과가 아니라 실패로
> 읽힙니다. 그래서 창을 새 대화로 옮깁니다.

그 옮김이 구현된 적이 없었습니다. 이제 `deleteConversation`이 새 대화를 만듭니다.
코어의 주석이 말하는 자리가 거기입니다: 코어에서 대화를 만들어내면 창이 한 번도
들어본 적 없는 대화가 되고 — "이제 다른 대화에 있습니다"라는 푸시가 없으니 — 응답이
그것을 실어 나르고 모든 호출자가 채택해야 합니다. `conversations.create`는 이미 있고,
창이 자기가 있는 폴더에 파일하며, 창에 직접 답합니다. 코어의 주석은 이제 그것을
약속하는 대신 그렇게 말합니다.

`App.test.tsx`의 두 테스트가 양쪽을 고정합니다: 열려 있는 대화를 지우면 새 대화가
시작되고 탭이 그 이름을 말합니다, 그리고 **보고 있지 않은** 행을 지우면 아무것도
옮기지 않고 아무것도 시작하지 않습니다.

### 컴포저의 파란 사각형 (2026-10-10)

"채팅 패널을 클릭하면 파란 사각형이 보인다"로 보고된 것. 전역 포커스 링이었고, 앱에서
그것을 피할 수 없는 유일한 컨트롤에 붙고 있었습니다.

**`tokens.css`에는 포커스 가능한 모든 것에 대한 규칙이 하나 있고**, 그것은 일부러
`:focus-visible`입니다 — "클릭마다 링이 뜨면 사람들이 링을 무시하게 된다"고요. 그건
텍스트 필드를 빼고 어디서나 통합니다. 왜냐하면 **텍스트 입력은 마우스 클릭에서도
`:focus-visible`에 매칭**되기 때문입니다. 그건 브라우저의 휴리스틱이지 앱의 것이
아니고, 컴포저가 유일한 텍스트 필드입니다.

그래서 사이드바에서 채팅을 클릭하면 — 컴포저가 포커스됩니다, 캐럿이 타이핑할 자리에
있도록요 — 이미 자기가 포커스됐다고 말하고 있는 카드 *안에* 링이 그려졌습니다. 그
카드는 테두리를 `--accent`로 바꿔서 말합니다. 창에서 쟀습니다: 758x63 사각형이
`outline-offset: 2px`로 `--accent-bright`에, 그리고 테두리가 `--accent`가 된 카드
안에. 같은 것을 말하는 파란 상자 둘.

`.composer textarea:focus-visible { outline: none }`이 수정의 전부이고,
`layout.test.ts`에 그것을 안전하게 만드는 가드가 있습니다. 예전 가드는
`assert.doesNotMatch(SOURCE, /outline:\s*none/)` — *아무것도* 링을 억제하지 않는다 —
였는데, 좋은 규칙이되 정당한 예외가 하나 있어서, 이제 억제의 정확한 집합을 단언합니다:

    [".composer textarea:focus-visible"]

그리고 그 필드가 정말 다른 말을 한다는 것도요. 링을 억제하고 아무 말도 안 하는 필드는
색만 바꾼 원래 버그니까요.

**그 검사에는 중간에 `time.sleep`이 있고, 그건 load bearing입니다.** 필드에 포커스를
주고 카드 테두리를 같은 `evaluate_js`에서 읽으면 `rgba(255, 255, 255, 0.1)` —
*포커스 안 된* 테두리 — 를 보고했습니다, 곧 올바른 테두리가 될 카드에서요. 왜냐하면
`border-color`는 트랜지션되니까요. 두 번의 호출로 반 초 사이를 두면
`rgb(99, 147, 240)`, 즉 `--accent`를 보고합니다. 이 검사의 첫 버전은 수정이 깨졌다고
말했을 것입니다.

### 탭 스트립 (2026-10-10)

제목 표시줄이 이제 브라우저처럼 탭 스트립입니다: 열어 둔 채팅마다 탭 하나, 각각에 X,
그 뒤에 `+`. 탭을 오른쪽 클릭하면 Rename과 Close tab.

**탭은 열린 대화이지, 대화의 복사본이 아닙니다.** 코어는 세션 하나를 들고 있으므로
탭 선택은 `conversations.switch`이고 대화록을 다시 읽습니다. 복사되는 것이 없고,
두 탭이 같은 대화에 대해 다른 말을 할 수 없습니다 — 하나뿐이니까요. 이미 열려 있는
채팅을 클릭하면 새 탭을 만드는 대신 그 채팅의 탭을 활성화합니다. 스트립이 뻔한 것을
거부하는 유일한 자리인데, 한 대화에 탭 둘은 한 세션의 두 뷰이고, 둘이 어긋날 수 있는
것이라면 사용자가 어느 쪽을 의미했는지뿐이기 때문입니다.

**탭을 닫는 것은 채팅을 지우는 것이 아닙니다.** 대화는 사이드바에 그대로 있습니다;
없어지는 것은 그것을 보는 뷰 하나입니다. 지우기는 행 메뉴의 Delete이고, 일부러 다른
단어입니다. 보고 있는 탭을 닫으면 그 자리를 이어받은 탭으로, 없으면 앞의 탭으로
넘어가고, 유일한 탭이었다면 새 대화를 시작합니다 — "아무것도 없음"은 두 절 전에
메시지를 잃던 그 상태니까요.

**스트립 안의 어떤 것도 드래그 영역이 아닙니다.** 탭이 라벨이던 시절에는 탭과 그
제목에 클래스가 붙어 있었는데, 이제 탭은 컨트롤이고 호스트는 누른 요소가 *자신이*
클래스를 들고 있을 때만 드래그합니다 — 그대로 두었으면 탭을 클릭할 때마다 창이
끌렸을 것입니다. 창을 옮기는 것은 스트립 양옆의 바 배경이고, `TopBar.test.tsx`가
개수가 아니라 정확한 클래스 집합을 단언합니다 — 그것이 이걸 잡았습니다.

**메시지가 없는 채팅은 이름 바꾸기가 거부됩니다**, 두 메뉴 모두에서요. 그리고 그
항목은 사라지지 않고 메뉴에 남습니다: 메뉴는 이름 바꾸기가 존재한다는 것을 알게 되는
곳이고, 빈 채팅은 정확히 그걸 찾아볼 때니까요. 이유는 `title`에 있습니다. 취향이
아닙니다 — 코어는 첫 사용자 메시지로 제목을 다시 짓는데, 그건 이름이 아직 "New chat"일
때만입니다. 그래서 빈 채팅에 타이핑한 이름은 그 채팅이 절대 벗어날 수 없는 이름입니다.

**`TopBar`에서 `title` 프롭이 사라졌습니다.** 스트립이 있으면 되돌아갈 단일 제목이
없습니다: 빈 스트립은 마크와 `+`, 그뿐입니다 — 탭이 하나도 없는 브라우저가 보여주는
것이죠. `"TONYAgent"` 폴백은 채팅에 대한 질문에 앱 이름으로 답하던 것이었습니다.

실행 중인 창에서 쟀습니다:

    the tab strip: 1 tab(s), first 72,0 228x51 in bar ..52: 1px from the bottom, radius 6px 6px 0px 0px, 1 close(s), 1 new

#### 플레이크는 테스트 잘못이었습니다

`ComposerPaste.test.tsx`의 붙여넣기 헬퍼는 첨부나 에러가 나타나는 즉시 기다리기를
끝냈습니다. 한도를 넘는 붙여넣기는 *둘 다* 만듭니다: `acceptFiles`는 읽기 전에 에러를
설정하고, 첨부는 `readFile`이 끝난 뒤 도착합니다. 그래서 루프가 에러에서 멈출 수 있고
호출자는 파일 0개를 셉니다. 이 세션에서 세 번 봤고(`0 !== 5`, "the paste ignored the
limit"), 한도가 무시된 것처럼 읽혔습니다.

이제 붙여넣기가 *멎을* 때까지 기다립니다: 첨부 개수와 에러가 연속 두 틱 동안 그대로일
때. 한 틱으로는 부족합니다 — 에러가 파일보다 정확히 한 틱 앞서니까요.

#### 스트립이 시작하는 자리

쟀습니다, 왜냐하면 "사이드바의 오른쪽"이 200px 떨어진 세 가지 답을 갖기 때문입니다:
레일은 **64**에서 끝나고, 사이드바 패널은 **288**, 대화록의 텍스트 칸은 83에서
시작합니다. 스트립은 **72**에 있었습니다 — `--rail-w` 더하기 바 자신의 8px 갭.

이제 **288**, 패널의 오른쪽 모서리에서 시작합니다. 탭이 사이드바의 칸 위가 아니라
사이드바 옆의 대화록 위에 앉도록요: 72에서는 스트립이 패널을 가로질러 지나가면서 패널
자신의 헤더처럼 읽혔습니다. 규칙은 `calc(var(--list-w) - var(--rail-w) - 8px)` — 토큰
둘과 바가 선언한 갭, 갭은 되돌려 받고 — 이고, `--list-w`만은 아닙니다. 그러면 창
가장자리에서 재게 되어 마크가 이미 거기 있으므로 패널보다 64px 더 오른쪽에 앉습니다.

패널이 열리고 닫혀도 움직이지 않습니다. `:has()`로 따라가게 할 수 있지만, 패널이 열릴
때 옆으로 미끄러지는 스트립은 탭을 포인터 아래에서 옮겨버립니다.

---

## 검증 / Verification (historical snapshots)

The commands and counts in this section are preserved as dated historical notes; they are not a current verification report. Re-run checks against the current checkout before relying on these numbers.

```bash
python -m compileall -q src
python -m pytest tests/unit -q               # historical: 635 passed, 8 skipped
python scripts/check_all.py --fast           # historical: 3 checks
cd app && npm test                           # historical: 513 passed
python scripts/verify_window.py              # historical desktop-host smoke check
python scripts/verify_core.py                # historical core-process check
python scripts/audit_reduced_motion.py       # current-purpose audit command; verify on this checkout
```

The TypeScript protocol tests use an injected transport; they do not need a Rust shell, Tauri, or Python runtime.
`LineTransport` 인터페이스로 전송 계층을 주입하므로 계약은 빌드 도구가 없어도
검증됩니다.

`npm test`는 `.tmp`를 지우고 `tsc -p tsconfig.test.json && node --test ".tmp/**/*.test.js"`입니다. 지우는 이유는 `tsc`가 자기 출력물을 정리하지 않아서, 소스가 사라진 테스트가 그대로 실행되기 때문입니다 (`.tmp/dbg.test.js` 두 개가 411개짜리 Suite에 assert 없이 섞여 있었습니다).
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

## 다음 단계 / Next Steps (historical snapshot, 2026-10-11)

**Completed UI capabilities** (historical implementation checklist)

The entries below record implementation work as it landed. They are not a current backlog; use the dated notes below as implementation history.

1. ~~프로젝트 폴더 선택기~~ ✅ (`sandbox.start`의 `path`)
2. ~~provider/model 설정 패널~~ ✅ (`bind_provider`)
3. ~~샌드박스 시작/중지 버튼~~ ✅
4. ~~어시스턴트 텍스트 마크다운 렌더링~~ ✅ (`markdown.ts` 파서 + `MarkdownText.tsx`)
5. ~~커스텀 모델 + 커스텀 엔드포인트(base_url)~~ ✅ (모델 자유 입력 + `bind_provider{base_url}`)
6. ~~대화 목록~~ ✅ (`conversations.*`)
7. ~~thinking 패널 + effort 선택~~ ✅ (`reasoning.*`)
8. ~~대화 이름 변경·복제~~ ✅
9. ~~전송 아이콘·파일 첨부·모델 선택·턴당 tool call 한도~~ ✅ (`send`의 content parts, `models.list`, `tools.get`/`tools.set`)

**Open items as recorded on 2026-10-11 (not verified against the current checkout)**
- (Historical, 2026-10-11) One successful end-to-end turn against a hosted model was blocked by the API key's quota; the local mock-provider path had completed successfully.
- (Historical, 2026-10-11) Packaged-app visual verification of the thinking panel and effort dial remained outstanding; tests covered the component behavior.
- (Historical, 2026-10-11) `App.tsx` was identified as a future extraction candidate for protocol and conversation-list hooks.
- ~~composer의 model 칩 / Attach 버튼~~ ✅ (model 칩 = `models.list` 기반 필터 메뉴, Attach = 멀티모달 첨부). 남음: `/`·`@` 힌트 처리
- (Historical, 2026-10-11) Group directories in the Files tree (`TreeEntry.kind` already supported `"dir"`).
- Refresh this handoff when a new implementation pass lands; current architecture and feature status belong in the overview above

**Ideas from that historical snapshot (not a current backlog)**
- `read_file` offset/limit, `edit_file` replace_all
- timeout `timeout_ms` 단위 통일
- `http_request` 파일 다운로드
- 스키마/레지스트리 단일 소스화
- 턴별 출력 예산
- (Removed from current work list) Tkinter chat bubble sizing; the current React transcript uses `fit-content` bubbles.

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
- **스타일시트는 `stylesheet.ts`로 읽으세요.** `styles.css`는 더 이상 규칙이
  아니라 `app/src/styles/`의 모듈 21개를 `@import`하는 **엔트리**입니다. 직접
  읽으면 import 목록만 나오고 규칙은 하나도 나오지 않습니다. `readStylesheet()`가
  캐스케이드 순서로 이어 붙이고, `readStylesheetSource()`가 거기서 주석을 뺍니다.
  리더는 이 둘뿐이고, 읽는 곳 다섯 군데가 전부 이쪽을 씁니다. 모듈 안에서 다른
  모듈을 `@import`하면 브라우저만 따라가고 리더는 못 따라가므로, 그렇게 하지 않는
  것도 테스트가 지킵니다.

- **스타일시트를 읽는 테스트는 reduced-motion 블록도 벗겨야 합니다.**
  `audit_reduced_motion.py`가 모든 애니메이션의 취소를 요구하므로
  `.sidebar`의 마지막 선언은 `animation: none`입니다. 주석만 지우면
  `.sidebar`가 애니메이션으로 해소되어 `top` 단언이 전부 실패합니다.
- ~~**Windows에서 TypeScript 스위트에 flaky 테스트 하나.**~~ **해결됨.**
  `ComposerAttach`의 strip 테스트가 전체 실행 5회 중 1회 정도 `0 !== 1`로
  떨어지던 것은 컴포넌트가 아니라 **테스트**의 문제였습니다. `click()`이 이벤트만
  보내고 React가 상태를 반영하기 전에 반환해서, 단언이 갱신 전 트리를 읽었습니다.
  `test-render.ts`의 `click()`이 이제 `act` 안에서 플러시를 끝냅니다. 연속 4회
  전체 실행이 444/444입니다.
- **테스트가 로드하는 파일은 import에 `.js`가 붙습니다.** Node의 ESM
  리졸버는 확장자를 추측하지 않습니다. `App.tsx`를 jsdom에서 렌더하려고
  처음 시도했을 때, 확장자 없는 specifier 19개 때문에 모듈 그래프 자체가
  로드되지 않았습니다. 다른 파일은 이미 전부 `.js`를 쓰고 있었습니다 — 예전에는
  테스트가 로드하는 파일만 그럴 필요가 있었기 때문입니다. Vite는 `.js` → `.ts`로
  그대로 해석하므로 번들에는 영향이 없습니다.
- **대소문자만 다른 파일명.** `windowControls.ts`와 `WindowControls.tsx`가
  나란히 있으면 Windows에서만 TS1149/TS1261입니다. 훅은 `useWindowControls.ts`.
- **앱이 떠 있으면 빌드가 `PermissionDenied`로 죽습니다**(`tauri-build`
  `lib.rs:164`). 빌드 **전에** `tonyagent-app.exe`와 `msedgewebview2.exe`를
  먼저 죽이세요.
- **두 검증기가 같은 칩을 누릅니다.** 그 패스의 두 검증기는 각각
  `verify_pass_b.py`(모델 메뉴를 열어둔 채로 종료)와 `verify_composer_pass.py`
  (그 칩을 눌러 토글)였으므로
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


---

## 최근 추가분: 비주얼 디자인 스윕 (6개 섹션)

레퍼런스 캡처에서 값을 빌려오던 상태를 끝냈습니다. 아래 수치는 **전부 이번에
현재 트리에서 다시 읽은 값**이고, 각 값이 왜 그런지는 `app/src/styles.css`
헤더와 각 토큰 옆 주석이 원본입니다. 문서가 숫자를 다시 적는 순간 두 번째
소유자가 생기므로, 여기서는 값과 **어떤 종류의 근거인지**만 적습니다.

### 값과 근거

| 값 | 현재 | 근거 |
|---|---|---|
| `--bg` ~ `--border-strong` 12단계 | 무채색 램프 | **이 앱의 선택.** 예전 값은 Freebuff 캡처의 warm green-grey였고, chroma가 3~4만 있어도 두 창이 같은 창으로 읽혔습니다 |
| `--fg-mute` | `#8a8a8a` — `--bg` 위 **5.04:1** | **대비 계산.** 옛 값 `#7c807a`는 4.21:1 — 이 토큰은 11px 이하에 쓰이는데 4.5:1 미달이었습니다 |
| `--accent` | `#6393f0` — `--bg` 위 **5.77:1** | **아트워크에서 읽음.** `icons/*.png`의 불투명 픽셀 87%가 `#2f6feb` 본체이고, 그 안티에일리어스 램프에서 4.5:1을 넘는 가장 어두운 스텝 |
| `--accent-bright` | `#97b7f5` — `--chip` 위 **5.38:1** | 같은 램프 한 스텝 위. 칩 위의 작은 글씨용 |
| `--accent-fg` | `#0b1020` — `--accent` 위 **6.28:1** | 같은 PNG에 이미 있던 잉크 |
| `--focus-ring` | `var(--accent-bright)` | 전용 이름. 링과 배지가 우연히 한 스텝을 공유하지만 요구조건이 다르므로 같이 움직이지 않습니다 |
| 위계 | 7단, 10 → 20px | **이 앱의 선택.** 리터럴 14개를 토큰으로. `--text-2xs` 10px는 모양·배지용이고 본문 인접 최소는 `--text-xs` 11px |
| 라디우스 | 5단, **6 / 12 / 16 / 24 / 999** (리스타일에서 한 칸씩) | **이 앱의 선택.** `calc(var(--radius-sm) - Npx)` 리터럴 10개를 규칙 이름으로 |
| 모션 | `--motion-fast` 110ms, `--motion-base` 160ms | **이 앱의 선택.** 상태 전환(110)과 surface 도착(160)의 두 축. 미사용이던 `--motion-slow`은 삭제 |
| 그림자 | `--shadow-1` / `--shadow-2` | **이 앱의 선택.** 1px inset 하이라인이 레퍼런스에는 없는 추가이고, `--shadow-2`는 창 모서리에 붙은 패널이므로 그림자 방향을 `--panel-cast`에서 받습니다 |
| `--rail-w` / `.rail-btn` | 56px / 40×40 | 40px은 최소 클릭 타깃, 56은 양옆 8px를 남기기 위한 값 — **레일 폭을 버튼이 정합니다** |
| `--topbar-h` | 44px | **내용 기준**: 13px 텍스트 한 줄 + 그 높이를 채우는 캡션 버튼 |
| `--list-w` | 260px | 레퍼런스 255 + 5. 제목이 한 글자 덜 잘리는 문제. 레퍼런스가 아니라 이 앱의 판단 |
| `--measure` | 680px | **이 앱의 선택.** 트랜스크립트·컴포저·힌트·배너가 공유. 예전엔 860px 트랜스크립트 위에 720px 컴포저 |

`--ok` `#a3c48a`는 값을 바꾸지 않았습니다. 액센트가 파랑으로 바뀌자 색상환
**125°** 떨어졌고(옛 63°), "성공"과 "이 앱의 색"이 더는 같은 이름이 아닙니다.

### 마크

`icon.svg`의 캐럿-위에-기준선 하나에서 17개 래스터가 나오고, 앱 안 **두 곳**
(제목 표시줄, 첫 화면)도 **같은 경로 데이터**를 씁니다 — 둘 다 `AppMark.tsx`를
통해서요. 그 컴포넌트와 `icon.svg`를 `AppMark.test.tsx`가 바이트 단위로
대조하므로 세 벌이 갈라질 수 없습니다. (이 문장은 "레일, 첫 화면"이었습니다.
마크가 제목 표시줄로 옮겨간 뒤에도 레일의 복사본이 남아 있어서, 같은 그림을
22px과 32px로 두 번 그리고 있었습니다 — 아래 "레일의 마크를 없앴습니다"를
보세요.)
`viewBox 0 0 512 512`, 스트로크 72(16px에서 2.25px로 남는 값), 라운드 조인.
miter였으면 16px에서 두 개의 끊어진 점선으로 보였습니다.

### 포커스 링

`:focus-visible` 규칙 **하나**만 있고, `outline: none`은 파일 전체에 0개입니다
(예전엔 5개). 링 색은 `--focus-ring` 토큰이고 오프셋 2px가 함께 들어갑니다 —
오프셋이 없으면 링이 컨트롤 자신의 채움 위에 그려져 `--accent` 대비 1.49:1이
됩니다. 대조는 토큰 계산, 스톱 수는 패키징드 빌드를 CDP로 실제 탭해서
2026-10-04에 다시 잰 값입니다:

```
--accent-bright 대조(계산)   --bg 8.63:1   --chrome 7.50:1
                            --raised 6.26:1   --chip 5.38:1
기본 화면 탭 스톱(실측)      서로 다른 스톱 8개, 전부 outline 2px solid
                            rgb(151,183,245), offset 2px, :focus-visible true
링 뒤 실제 배경 대비 최소값  7.02:1,   링 없는 스톱 0
포인터 클릭 시              :focus-visible 일치 0개 — 링은 키보드 전용
```

이전 패스에서 대화 패널과 설정 대화까지 열어 잰 45스톱 walks도 전부
링이 있었습니다. 45라는 수는 그때의 것이고, **기본 화면만 보면 8**입니다 —
첫 화면 패널이 포커스 가능한 것을 하나도 추가하지 않는다는 사실과 같은
결과입니다.

### 로고: T, 단말을 각지게 (2026-10-04)

**이전 패스의 stadium을 각지게(rect rx=0)로 바꿨습니다.** ground 색(#2f6feb)과
래스터 수는 그대로고, `rx`만 0으로 내렸습니다. T에는 blunt할 mitre도 라운드할
팔도 없으므로 stadium은 T에 어울리지 않습니다.

```
crossbar   700 x 176, rx 0      x=162   (16px에서 11px)
stem       204 x 512, rx 0      x=410   (16px에서 3.19px, 32px에서 6.4px)
ground     1024, rx 139
```

후보 6개를 그려서 16/20/24/32/48/96px로 읽어 보고 고른 것입니다. **옛 stadium은
stem이 흐려져서 진 게 아니라, 그 지오메트리가 그림에서 지는 것으로 밀렸습니다.**

**제가 적어 둔 이유 중 일부는 반대로 틀렸습니다.** "stem이 hairline으로 사라진다"
는 설명이었는데 163/1024 = 2.55px는 16px에서 solid 2px core로 살아남습니다.
실제로 문제였던 건 따로였습니다: 132셀 지름이 `rx 66`을 쓰면 **양 끝이 각져서
안내의 상자가 아니라 정리되고**, 16px에서 bar가 lozenge로 보입니다. 장대를
2.55px에서 204로 올린 것은 위 지오메트리가 자고로여서가 아니라, 그 위에 얹으면서
공짜였기 때문입니다.

**`--accent`는 움직이지 않았습니다.** ramp의 *가장 어두운 단계*이며 ramp step
이하라 배수입니다. `#2f6feb`이 88.7% -> **99.25%**로 바뀌었지만, 그것은 바닥이
래스터 안에서 차지하는 몫이 늘었다는 뜻일 뿐 토큰 값은 그대로입니다. 15개
래스터 전부 실측: `#6393f0` 5.77:1 / `--bg` `#1a1a1a`, `--accent-fg` 6.28:1.
(이전 문서의 3.70:1은 다른 `--bg`를 재서 **처음부터 틀린** 값이었습니다.)

### 가운데 폴더 버튼 (2026-10-04)

**요청**: "새 채팅에서 폴더 바꾸는 버튼이 화면 가운데에 있게. 바꾸지 않으면
이전에 했던 폴더를 그대로."

빈 화면(`.empty`)이 이미 가운데 정렬이므로 거기에 한 줄을 넣었습니다.
폴더가 있으면 `이름 + [Change...]`, 없으면 `No project folder + [Choose folder...]`.
경로는 `title`로.

```
.empty-folder        flex, gap 10px, margin-top 4px
.empty-folder-name   --fg-dim, --text-sm, max-width 42ch + ellipsis
```

**"바꾸지 않으면 그대로"는 이미 참이었고, 이제 보입니다.** core는 마지막
폴더를 config.toml에 쓰고 되읽고, `state`가 그 경로를 보내므로 재시작 후에도
`project`는 채워집니다. `startNewChat`도 폴더가 있으면 묻지 않습니다. 고칠
것은 동작이 아니라 **표시**였고, 이제 시작 화면에 있습니다.

**빈 화면 규칙을 없애지 않고 좁혔습니다.** "포커스 가능한 것 0개"였고,
테스트가 강제했습니다. 지우지 않았습니다:

| | 이전 | 지금 |
|---|---|---|
| 포커스 가능 | 0개 | `button.btn` **정확히 1개**, 이름까지 |
| 태그 allowlist | `button` 없음 | 추가 + 개수 1개 확인 |
| 핸들러 스캔 | 0개 | `["onClick="]` **정확히 1개** |

"0개"와 "1개, 그 하나가 폴더"는 두 번째 컨트롤이 생겼을 때 똑같이 실패합니다.

**제가 틀린 것 두 개를 테스트가 잡았습니다.** 폴더 이름을 `<span>`으로 썼는데
`span`은 allowlist에 없습니다 — **맞습니다**(React 핸들러를 실을 수 있는
태그). allowlist를 넓히지 않고 `<p>`로 바꿨습니다. 클릭 테스트가 0번 호출된
것은 `canChooseFolder`를 안 넘겨서 **버튼이 제대로 disabled**였기 때문입니다.

```
npm test  exit 0   471 passed (462 -> 471, +9)
tsc       exit 0   pytest exit 0   592 passed / 7 skipped
CDP 실측  name "LiveProject" / btn "Change..." / centreOffset 0
          focusable ["button.btn"]
          새 채팅 클릭 -> 폴더 유지, LiveProject 그룹 아래에 생성됨
```

**못 한 것**: 사람이 마우스로 **진짜 OS 다이얼로그를 열어** 고르는 것.
배선 자체는 jsdom에서 검증했습니다(`App`의 `pickProject` 주입점) — 골랐을 때
`sandbox.start`가 불리는지, 취소하면 폴더가 유지되는지까지 셉니다.

### 측정하지 않으면 놓쳤을 버그

**exe에 묵은 아이콘이 남아 있었습니다.** `npm run tauri icon`은 바인딩 파일만
새로 만들고, `tauri build`가 exe에 넣을 때는 그때 그 파일을 읽습니다.
`target/release/build/*/out/resource.rc`의 타임스탬프가 멈춰 있고 `build.rs`의
`rerun-if`가 icon을 보지 않으므로, `icon.ico`만 바꿔도 exe는 **이전 생성을
계승**합니다. `touch src-tauri/build.rs` 후 빌드해야 합니다. 체크로 exe의
RT_GROUP_ICON/RT_ICON을 열어 256×256 PNG를 꺼내 바인딩 파일과 픽셀 단위로
맞춰봐야 합니다.

**`ios/` `android/` 아이콘 폴더도 아직 디스크에 있습니다** (untracked, 이전
패스 경유).

### 대화 패널 (실제 대화 2개, 2026-10-04)

패키징된 빌드에서 **실제 대화 파일 2개**를 만들어 선택 행을 확인했습니다.
provider나 Docker 없이 됩니다 — `conversations.create`는 core의 store 한 줄이고,
프로젝트 폴더는 `config.toml`에 이미 있었습니다.

```
background-image  linear-gradient(135deg, rgba(99,147,240,0.18) 0%,
                                             rgba(155,124,240,0.12) 100%)
background-color  rgba(0,0,0,0)          border  0px        radius  16px
픽셀 near→far     (40,47,63) (40,43,58) (40,41,56) (41,40,54)
색상환 near→far    221.7°  225.7°  230.0°  236.2°  244.3°
크로마             23 → 21 → 18 → 16 → 14
--fg 11.34:1 (near) / 12.51:1 (far)      --fg-dim 5.64:1 / 6.21:1
비활성 행 hover    rgb(56,56,56) = --hover, 무채색
```

**"wash는 hover가 될 수 없는 색조"라는 기존 주석은 절반이 틀렸습니다.**
선택된 행이 hover보다 *어둡고*(39,48,65 vs 56,56,56, 명도비 1.13:1),
그레이스케일로는 구분되지 않습니다. 구분하는 것은 색상환입니다. 테스트도
그래서 색인이 아니라 chroma(`>= 12`, hover는 0)를 봅니다.

우연한 수확: 기존 `gradStops()`가 `#[0-9a-f]{6}`만 찾다 보니 `--grad-wash`
(`rgb(r g b / a)` 선언)에 대해 **빈 배열을 반환하면서 통과**하고 있었습니다.
`maskedStops()`를 추가해 `(hex, alpha)`를 같이 읽습니다.

### Start 버튼 · Full은 호스트에서 (2026-10-04)

**Start 샌드박스 버튼.** 폴더를 고르는 동작만 샌드박스를 시작했는데,
폴더는 재시작하면 복원되므로 창은 `sandbox: stopped`인 채로 **누를 수 있는
것이 하나도 없었습니다.** Settings → Project folder에 `Start`가 들어갔고,
시작 중에는 `Starting...`(비활성)이 됩니다.

`Start`는 **경로 없이** `sandbox.start`를 보냅니다. core가 이미 그 폴더를
들고 있고, 다시 보내는 것은 창과 core가 다른 프로젝트를 말하게 만드는 것뿐.

```
부팅 직후      [Change...] [Start]   sandbox: stopped
Start 클릭 후   [Change...] [Stop]    sandbox: running   ← 실제 컨테이너
docker ps      24377b30ac12  tonyagent/sandbox:latest  Up 30 seconds
```

**`state`가 샌드박스 상태를 보고합니다** (`AgentSession.sandbox_status()`).
창은 `sandbox.status` 이벤트만 듣기 때문에 재시작하면 아무 것도 모르고,
이미 떠 있는 샌드박스 위에 `Start`를 그릴 수 있었습니다.

**여기서 세 번째 버그가 나왔습니다.** 라이브로 누르니
`name 'folder_manager' is not defined`. `AgentSession.start_sandbox`가
`folder_manager`를 **쓰고 있는데 import가 없었습니다.** 모든 호출자가
경로를 넘겼고 `project_path or ...`가 short-circuit 되었기 때문에 죽지
않았던 것이고, **경로 없는 호출이 이 함수를 처음 실행하는 경로**였습니다.

> 그 버그를 놓친 회귀 테스트가 하나 있었습니다 — `start_sandbox` 자체를
> stub 해서 고장 난 줄을 지나쳤고, 깨진 코드 위에서도 통과했습니다.
> **부위 대신 호출 경로를 fake** 해야 합니다.

**Full은 호스트에서.** `Permission.runs_on_host` — low/medium/high는 False,
full만 True. `ExecuteCommandTool.execute`가 런타임 조회 전에
`_execute_local`로 빠지고, `runtime_access`의 두 게이트도 호스트를 존중합니다.

```
Low      gain: —
Medium   gain: Can run shell commands
High     gain: Runs on this computer, outside the sandbox
Full     markers: ON THIS COMPUTER / ANY COMMAND / NO PROMPTS
```

High 행의 한 줄이 allow-list가 아니라 **기계**를 말합니다. 세 개 중 하나만
높게 띄울 수 있는데, High→Full에서 실제로 움직이는 경계는 이것이기 때문.

빌드된 `tonyagent-core.exe`에 직접 물어본 wire:

```
low/medium/high runs_on_host = False    full runs_on_host = True
permission.set {"permission":"full"} -> runs_on_host: True
state.permission = full                state.sandbox = stopped
```

### 첫 화면 (빈 대화)

`MessageList.tsx`의 `.empty`: 마크 · 워드마크 · 한 줄 안내 · **폴더 한 줄** ·
`/` `@` 힌트.

**클릭·포커스 가능한 것은 폴더 버튼 하나뿐입니다.** 이전에는 0개였고
`MessageList.test.tsx`가 0개를 세어 잡았는데, 2026-10-04에 가운데 폴더
버튼(위 "가운데 폴더 버튼")이 생기면서 좁혔습니다. `button.btn` **정확히 1개**,
태그 allowlist에 `button`을 넣되 개수까지 확인하고, 핸들러 스캔은 0개 대신
`["onClick="]` 1개를 봅니다 — 패널 자신까지 세므로 재귀자가 붙어도 통과하지
않습니다. `AppMark.test.tsx`는 마크 한 개가 어느 자리에서도 포커스될 수 없음을
따로 잡습니다. 뮤테이션 3건(두 번째 버튼 / 워드마크 핸들러 / `.empty`의
`tabIndex`)이 모두 잡히는 것을 확인했습니다.
힌트는 컴포저의 placeholder에 있던 `/`와 `@`를 그대로 위로 올린 것이고,
회전색을 `--accent`으로 그립니다 — `--bg` 위 5.77:1, 그래픽 기준 3:1을 넘습니다.

### 스타일시트 분할 (이번 패스)

`styles.css` 3708줄은 `app/src/styles/`의 모듈 21개로 쪼개졌습니다. 각 파일은
**섹션의 연속 구간**이고 순서는 원본 파일과 같아서, 캐스케이드가 그대로입니다.
`tokens` · `shell` · `conversation-list` · `rail` · `topbar` · `transcript` ·
`tool-calls` · `thinking` · `composer` · `banner-log` · `statusbar` ·
`confirm-modal` · `settings` · `search` · `scrollbars` · `sidebar` · `markdown` ·
`motion` · `surfaces` · `arriving` · `reduced-motion`.

검증: 모듈을 이어 붙인 결과가 분할 전 파일과 **바이트 단위로 같음**을
확인했습니다(줄바꿈 끝 공백만 제거 후 비교, 21개 전부). 패키징된 빌드에서도
같은 확인을 했습니다 — 문서가 실제로 해석한 선택자 335개가 선언된 선택자
340개에서 키프레임 스텝(`from`/`to`/`50%` 등) 5개를 뺀 것과 정확히 일치하고,
문서에 있는데 선언되지 않은 선택자는 0개, `@keyframes` 16개도 16개 그대로
들어와 있었습니다.

분할이 실제로 깨질 수 있는 방식은 조용한 것들이라 테스트가 네 개 있습니다:
모듈을 만들고 import를 빠뜨림 / 같은 모듈을 두 번 import / 엔트리에 규칙을
직접 씀 / 존재하지 않는 모듈을 import / 모듈이 다른 모듈을 import /
비어 있는 모듈을 styles/에 방치. 6개 돌린 결과 6개 전부 각자 다른 단언에서
잡혔습니다.

한 가지 실제 발견: `.sidebar-filter input:focus`가 **빈 규칙**으로 남아 있었습니다.
포커스 패스에서 `outline: none`을 지울 때 마지막 선언이 사라진 것이고, 브라우저는
빈 규칙을 조용히 버리므로 그 선택자는 문서에서 해석되지 않는 유일한 선택자였습니다.
삭제했고, "빈 규칙 없음"을 테스트로 지킵니다.

### 테스트

```
npx tsc --noEmit                 클린
npm test                         471 tests / 75 suites
                                ComposerAttach flake 수정됨, 연속 4회 통과
                                471 = 분할 4개 + 리스타일 3개 + 레일 1개 + wash 2개
                                + 로고 2개 + sandbox/permission 추가
python -m pytest tests/unit -q   592 passed, 7 skipped, 0 failed
                                (test_build_scripts.py 제외 — 매번 서로 다른
                                 4/24 실패하며, 원본 HEAD의 worktree에서도 실패)
scripts/audit_reduced_motion.py  모든 애니메이션 선택자가 취소 목록에 있음
```

`npm test`의 수치는 항상 백센 폴우고 그 수치로 대체한 것입니다. 이전 문서의 415/426/441은
`.tmp/`에 남아 있던 assert 없는 디버그 테스트 2개(`dbg.test.js`,
`dbg2.test.js`)를 세고 있었고, `build:proto`가 이제 `.tmp`를 지우므로 다시
생기지 않습니다.

`pytest tests -q`(Docker 데몬 필요)는 이번에 돌리지 않았습니다 — 이전 문서의
590/501 수치는 재현하지 않았으므로 그대로 옮기지 않습니다.

---

## 이번 패스: 리스타일 (그라디언트 · 스타디움 · 여백)

디자인 스윕은 정확성·구조 작업이었고 리스타일이 아니었습니다. 눈에 보이는 변화가
셋뿐이었던 이유입니다. 이번 패스는 **보이는 것만** 건드립니다.

가져온 것은 **문법**이고 색은 가져오지 않았습니다 — 그라디언트의 시작점은 우리
아이콘에서 읽은 `--accent #6393f0`이고, 둘째 스톱은 그 색상환을 36° 돌린 `#9b7cf0`입니다.

| 값 | 현재 | 근거 |
|---|---|---|
| `--grad-accent` | `#6393f0 → #9b7cf0` | **아트워크 파생.** 두 스톱 모두 `--bg` 위 5.77:1 / 5.41:1 — 워드마크가 이걸 글자로 쓰기 때문 |
| `--grad-wash` | 같은 색 alpha 0.18 / 0.12 | 선택된 표면용. 위에 텍스트가 앉으므로 alpha 상한이 있음 |
| 라디우스 | **6 / 12 / 16 / 24 / 999** | 한 칸씩 올림. 래더가 없었으면 25개 규칙 수정 |
| 선택 상태 | 행·탭 = wash, 모드 알약 = `--chip` | `--chip`은 컨테이너, 상태는 그라디언트. 실제 대화 2개로 라이브 확인 — near`(40,47,63)`→far`(41,40,54)`, hue 221.7°→244.3°, `--fg` 11.34:1 / `--fg-dim` 5.64:1. **선택 wash가 `--hover`보다 어둡다**(명도비 1.13:1) — 구분되는 것은 색상환이라 chroma로 테스트 |
| 레일 활성 | 40×32 그라디언트 스타디움 | 타깃은 40×40 그대로 |
| 테스트 | **471 tests / 75 suites** | 이전 462 |

---

## 이번 패스: 스크린샷 도구 + 붙여넣기 미리보기 (+ CSP 버그 수정)

| 항목 | 내용 |
|---|---|
| **새 도구** | `take_screenshot` — 전체 화면 또는 영역을 PNG로 줄여 모델에게 돌려줍니다(`ToolResult.images`) |
| **허용 모드** | Full, 그리고 Build + High 이상 (`_HOST_SCREEN_TOOLS`, 두 축 교차) |
| **저장 정책** | `strip_images` — 대화를 저장할 때 `image_url` 파트를 텍스트 한 줄로 바꿉니다 |
| **붙여넣기** | `imagesFromClipboard` + `Composer.acceptFiles` — 이미지 붙여넣기가 대기 첨부로 |
| **버그 수정** | `tauri.conf.json`에 `img-src 'self' data: blob:` 추가 — **모든 data: 미리보기가 깨져 있었습니다** |
| **테스트** | TS **492 passed / 78 suites**, Python **623 passed / 8 skipped** |

CSP 버그는 붙여넣기 검증 도중 패키징된 앱에서 `naturalWidth: 0`(깨진 그림
아이콘)으로 드러났습니다. jsdom은 CSP를 강제하지 않아 어떤 테스트도
잡지 못했고, 그래서 `tauri.conf.json`을 직접 읽는 `app/src/webviewPolicy.test.ts`를
추가했습니다(변이로 확인).

자세한 내용은 `NEXT_SESSION.md`의 "스크린샷 도구, 붙여넣기 미리보기, 그리고
깨져 있던 CSP" 절을 보십시오.

## 최근 추가분: 레이아웃 스윕 (2026-10-05)

"설정 부분 레이아웃이 깔끔하지 않다"는 지적에서 시작해, 앱 전체를 CDP로 실측하고
**같은 것을 두 곳에 선언해 어긋난 자리**만 고쳤습니다. 스캐너(수평 오버플로 /
부모 밖으로 나간 자식 / 행 중심 어긋남 / 블록 왼쪽 끝 어긋남)는 수정 전에도
수정 후에도 clean이었고, 실제 결함은 전부 선언이 두 벌이던 곳에서 나왔습니다.

| 항목 | 내용 |
| --- | --- |
| **읽기 칼럼** | `--column-inset: 19px` 신설. 트랜스크립트는 `max-width: var(--measure)` + `padding: 0 28px`라 메시지가 624px, 컴포저는 같은 680px에 글자가 19px 안쪽 — 컴포저가 메시지보다 23px 밖에 있었습니다. 이제 트랜스크립트·메시지·힌트·배너·로그 스트립이 모두 글자선 `290..932`에 섭니다 |
| **스크롤바 점프** | `.transcript`에 `scrollbar-gutter: stable both-edges` — 대화가 길어져 스크롤바가 생길 때 칼럼이 5px 움직이던 것 |
| **설정 패널** | 필드 인셋 13/8/9px → 12px 하나; 알약이던 Permission/Thinking 트리거를 12px 라운드 필드로(아래 셀렉트와 같은 모양); 셀렉트는 `appearance: none` + 자체 `▾` 캐럿 |
| **provider 행** | `flex: 1` 두 개로는 셀렉트 172.8px 대 입력 198.8px로 갈렸습니다(`1 1 0%`·`min-width: 0`인데도). 그 행만 `grid-template-columns: 1fr 1fr auto` → 실측 **185.8 / 185.8** |
| **상태바 구분자** | 아무것도 그리지 않던 0×0 `<span class="sep">`(효과는 gap을 16px로 벌리는 것뿐) → 1px × 12px `--border` 괘선 |
| **Logs 바** | `margin: 0 28px`(폭 1054px)로 창의 어느 선과도 정렬되지 않던 것 → 컴포저와 같은 칼럼, 같은 19px 인셋 |
| **검증** | `npm test` **492 passed / 78 suites**, `npx tsc --noEmit` exit 0, `pytest tests/unit -q` 623 passed / 8 skipped, `tauri:build` MSI + NSIS 재생성 후 CDP로 실측 |

새 테스트 3개는 `app/src/layout.test.ts`에 있습니다: 토큰이 컴포저의 실제 인셋인지
(+ 밴드 검사), 모든 규칙이 그 토큰을 쓰는지, 그리고 provider 행이 그리드인지
(플렉스로 "정리"되면 26px 비대칭이 조용히 돌아오기 때문입니다).

하지 못한 것: 좁은 창(≤760px)은 이 WebView2에서 `Emulation`이 먹지 않아 실측하지
못했고, JS 전체 스위트에서 `ComposerPaste` 한 테스트가 병렬 부하에서 한 번
흔들렸습니다(재실행 통과, 그 스위트 5회 연속 통과). 커밋하지 않았습니다.

자세한 내용은 `NEXT_SESSION.md`의 "레이아웃 스윕: 읽기 칼럼 하나, 그리고 설정
패널" 절을 보십시오.
## 최근 추가분: 설정 패널 세로 리듬 (2026-10-05)

"Provider URL 입력창이랑 그 위에 드롭다운 메뉴랑 너무 딱 붙어있습니다"는 지적.
앞 패스가 provider 행의 가로(폭·인셋·모양)를 손본 자리에서 세로가 남아 있었습니다.

`.settings-row`에는 세로 리듬이 없었습니다(`gap: 8px`은 행 *안쪽* 거리이고,
그전까지 이 행이 두 개 포개진 적이 한 번도 없었습니다). 그래서 Model 그룹의
Base URL 행이 provider 행과 **0px** 떨어져 있었고 — 452px 폭의 필드 하나에 가로선
하나가 긋힌 것처럼 보이던 것을 실측으로 확인했습니다.

| 항목 | 내용 |
| --- | --- |
| **규칙** | `.settings-row ~ .settings-row { margin-top: 10px; }` — 하나뿐입니다 |
| **10의 근거** | `.settings-note`의 `margin-bottom`(10px)을 빌렸습니다. "설명문 → 필드" 간격과 "필드 → 필드" 간격을 같게. 행 안쪽 8px보다 넓어 두 필드가 하나로 읽히지도 않습니다 |
| **`~`인 이유** | `+`는 두 행 사이에 요소가 하나 끼면 0으로 조용히 돌아갑니다. 일반 형제는 그걸 버티고, 이 패널에서 포개진 행은 두 개뿐입니다 |
| **JSX** | 주석만 늘었습니다. Base URL이 별도 행인 이유(`1fr 1fr auto`의 세 번째 칸은 Apply 버튼의 64px) |
| **실측** | 두 행 사이 **10.00px**(수정 전 0). note → provider 행도 10.00, 힌트는 7.00, 행 안쪽 8.00. 다른 행은 그대로(Permission/Thinking은 `.settings-row`가 아님, Project folder·키 입력은 0) |
| **검증** | `getBoundingClientRect` + 스크린샷 픽셀 카운트(`--input` 두 밴드 사이 `--surface` 20 device px) 두 가지. `margin-top: 0`을 강제로 끼우면 0으로 돌아오고 뺐더니 10 — 새 규칙에서 온다는 확인 |
| **테스트** | `layout.test.ts` "two fields stacked are two fields, not one with a line across it" — 숫자가 아니라 관계로 고정(0보다 큼 / 행 안쪽 gap 이상 / note의 margin-bottom과 같음 / `+` 규칙 없음). 규칙 삭제와 `~`→`+` 두 가지 변이 모두 실패시킵니다 |

`npm test` **493 passed / 78 suites**, `npx tsc --noEmit` exit 0,
`pytest tests/unit -q` 623 passed / 8 skipped, `tauri:build` MSI + NSIS 재생성.

하지 못한 것: 스크린샷을 눈으로 보지는 못했습니다(이 빌드에서 이미지 읽기가
BLOCKED이고 preview 브라우저가 프레임을 만들지 않아) — 픽셀 계측으로 대신했고,
좁은 창은 이전과 같이 `Emulation` 부재로 실측하지 못했습니다. 커밋하지 않았습니다.
## 최근 추가분: 모달 스크롤바가 둥근 모서리 밖으로 (2026-10-05)

"설정 모달에 스크롤바가 Overflow되는 느낌이 있네요"는 지적. `.modal`은 24px
라운드 박스인데 스크롤되는 컨테이너이고, 스크롤바는 모서리가 직각인 상자입니다.
Chromium은 스크롤바를 border box 위에 칠하면서 그라운드 라운디우스로 자르지
않아서, thumb가 이동을 끝내는 양 끝에서 마지막 몇 픽셀이 패널이 아니라 스크림
위에 그려졌습니다.

| 항목 | 내용 |
| --- | --- |
| **실측(수정 전)** | thumb x `841.75..845.75`(4px). 위쪽 7.0px(y 28.5..35.5), 아래쪽 7.0px(y 764.0..771.0)가 패널 실루엣 밖. 완전 대칭 |
| **규칙** | `.modal` 한정. `::-webkit-scrollbar-button:vertical:decrement/increment`에 `display:block; height:14px; background:transparent; border:none` |
| **왜 궤적을 줄이는가** | thumb가 아니라 이동 궤적을 당기면 thumb의 분모도 같이 줄어 비율을 거짓말하지 않습니다. 트랜스크립트는 모서리가 없어 적용하지 않음 |
| **실측(수정 후)** | 스크롤 양 끝 모두 패널 밖 **0행**. 버튼 구역은 `--surface`와 테두리뿐 — 화살표 글리프 없음(픽셀로 확인) |
| **대가** | thumb가 612.2px/750px(81.6%)에서 566.2px/750px(75.5%)로. 실제 가시 82.7% 대비 **오차 1.1% -> 7.2%**, 스크롤 끝에서 thumb가 32px 전에 멈춤 |
| **무효로 돌린 것** | 풋터 헤어라인의 10px 단절은 음수 마진으로 고칠 수 없음(배치만 바뀌고 픽셀 0). `--scrollbar-size` 토큰·`scrollbar-gutter: stable`·`overflow-x: hidden` 전부 되돌림. `gutter: stable`은 높이 10px를 먹어 풋터를 765로 올리는 새 결함을 만들기도 했음 |
| **측정 함정 두 가지** | ① 회색 창 판정이 모서리 안티알리어싱을 thumb로 오인 → "3 CSS px 이상 연속 구간"으로 교정. ② CDP로 주입한 스크롤바 의사 요소 스타일은 `getComputedStyle`에 반영되지만 **캡처 픽셀 0개 변화**(스크롤바는 생성 시 스타일이 확정). 변형 비교는 실제 빌드 없이는 무효 |
| **테스트** | `layout.test.ts` "the dialog's scrollbar stays inside the dialog's corners" — 양 끝 버튼 존재·`display:block`·px 높이·투명 배경·전역 규칙에 button 없음. 변이 2건(삭제/불투명화) 모두 실패 확인 |
| **검증** | `npm test` **494 passed / 79 suites**, `npx tsc --noEmit` exit 0, `pytest tests/unit -q` 623 passed / 8 skipped, `tauri:build` exit 0 |

하지 못한 것: 눈으로 확인하지 못했습니다(이 빌드는 이미지 읽기가 BLOCKED이고
preview가 프레임을 만들지 않아). 대안인 라운드 축소(24px -> 12px)는 계산상
0.79px만 밖으로 나가지만 빌드·측정을 하지 않았습니다. 커밋하지 않았습니다.

---

## 이번 패스: 문서 정렬 + 레이아웃 일관성 (2026-10-13)

**문서.** README와 이 문서가 실제 앱과 다른 것을 말하고 있었습니다 — Tauri MSI, 살아 있는
Tkinter 클라이언트, 32개 도구, 라이트/다크 테마, OpenRouter 단일 provider. 현행 아키텍처
요약(pywebview 호스트 + React/Vite + 헤드리스 코어, 도구 41개, provider 2개, 어두운 테마
전용)으로 다시 썼고, 지난 시점의 기록은 그 절 제목에 *historical*이라고 적었습니다. IPC 표의
숫자도 실측으로 바꿨습니다 — `headless/server.py`의 핸들러 **41개**, `core/events.py`의
`EventType` **19개** (문서는 25개/16개라고 적고 있었습니다). `app/vite.config.ts`에는 더 이상
없는 `src-tauri/`와 `binaries/`를 감시 제외 목록에 두고 그 이유를 설명하는 주석이 남아
있었습니다.

**레이아웃.** "디자인과 레이아웃이 일관적이지 않다"는 지적에서 시작해, 눈으로 고치지 않고
먼저 쟀습니다. 이번에도 결함은 전부 *같은 것을 두 곳에 선언해 어긋난 자리*에서 나왔습니다.

| 항목 | 실측(수정 전) | 수정 |
| --- | --- | --- |
| 읽기 칼럼 | 1280px 창에서 트랜스크립트 내부 상자와 컴포저 상자가 둘 다 292..1052(760px). **760px 창에서는 74..750(676) 대 96..728(632)** — 왼쪽 22px, 폭 44px 어긋남. 888px 위에서는 `--measure` 상한이 양쪽을 덮어 가려져 있었습니다 | `--column-air`(22) + `--column-edge`(air + `--scrollbar` = 32) 신설. 트랜스크립트는 air를, 스크롤러가 없는 세 표면(컴포저·배너·로그 스트립)은 edge를 씁니다. 888px 위에서는 아무것도 움직이지 않고 그 아래가 전부 맞습니다 |
| 메시지 폭 | 어시스턴트 본문 606.5px — `.bubble`의 `min(680px, 84%)`. 680은 `--measure`가 760으로 오기 전의 값이고, 84%는 토큰이 닿을 수 없는 단위로 창을 따라 줄어듭니다 | `.bubble`은 칼럼 그대로(`max-width: 100%`). 사용자 말풍선만 `min(560px, 100%)`로 남겨 칼럼을 넘지 못하게 |
| 브레이크포인트 | 720·680·560·540·430·390 — 한 창이 여섯 크기에서 상태를 바꿨습니다 | **720 / 560 / 420** 사다리 하나. `layout.test.ts`가 캐스케이드의 모든 `@media (max-width: Npx)`가 이 셋 중 하나인지 검사합니다 |
| 패널 인셋 | 10(채팅 머리·발), 12(그룹 라벨), 14(Files 필터·빈 상태), 18(모든 다이얼로그), `clamp(16px, 2.5vw, 32px)`(대시보드 — 창을 따라 움직인 유일한 표면) | `--pad-panel: 16px` 하나 + `--pad-row: 8px`. 행 카드는 8만큼 들어가고 8만큼 안쪽 여백을 가져 글자가 같은 16px 선에 섭니다 |
| 검증 | — | 실브라우저(Chromium)에서 1280 / 760 / 560 / 420 실측: 네 표면이 같은 상자, 가로 오버플로 0, 패널 텍스트 선 16px, 상태바는 560에서 provider/model과 Logs만 남김. `npm test` **820 passed / 127 suites**, `npx tsc --noEmit` exit 0, `pytest tests/unit -q -m "not docker"` **1377 passed / 15 skipped**, `scripts/audit_reduced_motion.py` clean |

부수적으로 고친 것: 상태바의 좁은 창 규칙이 `span:nth-of-type(2)`/`(5)`로 대상을 세고
있었는데, provider가 없을 때 그 자리는 `linkish` 버튼으로 바뀌어 span 번호가 밀립니다 —
즉 정확히 "무엇을 하라고 알려주는 상태"에서 다른 것을 숨기고 있었습니다. 이제 클래스로
가리킵니다(`.statusbar-state`, `.statusbar-sandbox`, `.sep`).

하지 못한 것 두 가지. ① 이번 세션 후반에 preview webview가 프레임을 만들지 않아(합성 중단)
**스크린샷을 눈으로 보지 못했습니다** — 기하 계측(`getBoundingClientRect`, `offsetLeft`,
`getComputedStyle`)으로 대신했습니다. ② 패널 쪽 검증은 개발 서버에 임시 스텁 호스트를 물린
스크래치 페이지로 했고, 측정 후 지웠습니다(저장소에 남지 않았습니다). 커밋하지 않았습니다.

---

## 이번 패스: 일반 채팅과 코드 어시스턴트 (2026-10-13)

**일반 채팅.** 컴포저는 코어의 Chat 모드를 첫 번째 알약으로 제공합니다. Chat은
프로젝트·브라우저·쉘·변경 도구가 없습니다. 읽거나 실행하거나 바꾸는 것이 없고,
읽기 전용 힌트는 해당 모드의 설명을 그대로 보여줍니다.

**코드 어시스턴트.** 코드 모드의 오른쪽 패널은 같은 대화와 같은 컴포저를
그대로 둡니다. 에이전트 모드의 복사본이 아니라 위치만 옮긴 하나의
`conversationView`이며, 한 번에 하나만 마운트됩니다. 패널을 접어도 헤더와
토글이 남아 돌아올 수 있고, 본문이 사라진 동안 숨은 컴포저가 남지 않습니다.

---

## 이번 패스: 읽기 전용 컴포저의 모서리 (2026-10-14)

Chat · Plan · Skills가 필드를 표시할 때 칠하는 색은 **텍스트영역 자신**의 것입니다.
`.composer-inner`는 자식을 클립할 수 없습니다 — `/` 메뉴가 필드 위쪽으로 삐져나오기
때문입니다(`.skills-menu`). 그래서 24px 테두리 안의 각진 채움 사각형이 필드의 위쪽
두 모서리를 각지게 만들었고, 아래 두 모서리는 컨트롤 줄에 채움이 없어 둥근 채로
남았습니다. 이것이 정확히 읽기 전용 세 모드에서만 보인 이유입니다(Build·Mission은
정상).

채움의 호를 테두리 **안쪽** 호로 맞췄습니다(`calc(var(--radius-lg) - 1px)`, 위 두
모서리에만). 두 호는 이제 같은 중심을 갖습니다 — 개발 서버에서 필드 위쪽 모서리
3px 안쪽 픽셀을 hit-test로 재었습니다. 수정 전 그 자리는 `TEXTAREA.is-readonly`,
수정 후에는 필드 자신입니다. `layout.test.ts`가 이 규칙과 그 이유(필드가 자식을
클립하지 않는다)를 함께 고정했습니다(그 채움은 다음 절에서 사라집니다): `npm test` **823 passed / 127 suites**,
`npx tsc --noEmit` exit 0, `scripts/audit_reduced_motion.py` clean.

개발용 `code-preview.html`의 스텁 코어는 모드를 Build·Plan 둘만 알고 있었습니다.
그래서 실제 창에는 있는 Chat·Skills가 이 페이지에는 없었고, 문제의 그 모서리도
여기서는 재현되지 않았습니다. 이제 코어의 `MODE_ORDER` 다섯 개를 코어의 문구
그대로 제공합니다.

---

## 이번 패스: 컴포저의 배경 하나 (2026-10-14)

읽기 전용 모드의 채움을 없앴습니다. Chat · Plan · Skills는 **텍스트영역**에
`color-mix(in srgb, var(--input) 70%, var(--bg))`를 칠했습니다 — 불투명한 회색이고,
브라우저는 이를 `color(srgb 0.148627 0.148627 0.148627)`로 계산합니다(Build의
텍스트영역은 `rgba(0, 0, 0, 0)`). 채움이 필드가 아니라 텍스트영역의 것이었기
때문에 컨트롤 줄에서 멈췄고, 그 세 모드는 유리 위에 회색 상자를 얹은 모양이었습니다.
앞 절의 모서리 수정은 그 이음매를 둥글게 만들 뿐이었습니다. 이제 다섯 모드 모두
투명한 텍스트영역 너머로 필드 자신의 `--glass-field`가 보입니다 — 어떤 모드든
하나의 면입니다.

상태는 여전히 두 곳에서 말합니다: 모드 그룹에서 켜져 있는 알약이 현재 모드이고,
필드 아래 힌트가 문장으로 설명합니다("Chat mode — Talk. Nothing is read, run or
changed."). `Composer.tsx`는 `is-readonly`를 스타일 훅이 아니라 마크업의 상태
표시로 남겨 두고, `layout.test.ts`의 "the field is one field in every mode"가 그
셀렉터에 대한 규칙이 스타일시트에 없음을 — 주석을 제거한 `SOURCE`로 읽으므로 삭제를
설명하는 주석이 셀렉터를 이름으로 불러도 안전합니다 — 그리고 `.composer textarea`가
`background: transparent`임을 고정합니다. 이 단언이 실제로 걸리는지도
확인했습니다: 지금 모듈들에서는 false, 옛 규칙을 다시 붙인 같은 텍스트에서는
true입니다.

채움과 함께 사라진 선언이 둘 있습니다. 둘 다 채움을 필드의 곡률 안에 붙잡아 두기
위한 것이었습니다 — 위 두 모서리의 `calc(var(--radius-lg) - 1px)`와
`border-color: var(--border)`입니다. 후자는 애초에 아무것도 칠하지 않았습니다:
`.composer textarea`가 `border: 0`이므로 너비 0, `none` 스타일 테두리의 색은 어떤
픽셀에도 닿지 않는 선언입니다. 검증: `npm test` **823 passed / 127 suites** exit 0,
`npx tsc --noEmit` exit 0, `scripts/audit_reduced_motion.py` clean, 그리고 개발
서버(`code-preview.html`, 실제 `App`)의 Chat 모드에서 텍스트영역은 `is-readonly`를
단 채 `rgba(0, 0, 0, 0)`이고 필드는 여전히 `rgba(46, 46, 46, 0.78)`입니다.

---

## 이번 패스: 스타디움 전면 적용 (2026-10-14)

모양 규칙은 이미 `tokens.css`에 적혀 있었습니다 — "테두리를 볼 수 있는 컨트롤은
스타디움, 그보다 짧은 모서리는 컨테이너". 문제는 창의 절반만 그 규칙을 따르고
있었다는 점입니다. 턴당 도구 호출 한도 팝오버가 그 증거였습니다: 알약 프리셋 여섯
개 아래에 6px 모서리의 `Set` 버튼과 같은 모서리의 숫자 필드가, 한 덩어리 컨트롤인
한 줄에 놓여 있었습니다.

판단 기준은 하나였습니다: *테두리를 그리는 컨트롤*(항상, 또는 호버·선택 시)은
스타디움입니다. 그래서 컴포저의 `+`·기어·예산 버튼이 Send와 같은 원판이 되고,
첨부 칩과 그 썸네일, 모델 선택기의 검색 필드, 서랍의 토글·뒤로·하단 동작·
New chat, 탭의 이름 필드와 닫기 글리프, 레일의 44px 버튼, 어시스턴트 토글,
코드 뷰어의 닫기, 설정 패널의 셀렉트·입력·24px 키 동작 둘, 권한 트리거가
스타디움이 되었습니다.

모서리를 지킨 것들도 각각 이유가 있습니다: 모든 패널·메뉴·카드·공지·코드
블록(표면), 상단 띠의 아래 모서리에 잘려 들어간 문서 탭, 컨트롤 더미를 담는
컴포저 필드와 권한 컨트롤의 열린 상태(필 위에 호를 그리면 첫 행과 끝 행을
가로지릅니다), 빈 화면의 키캡, 그리고 눌리기는 하지만 채움을 전혀 칠하지 않는
사이드바 폴더 제목(호버가 색 변화뿐이라 둥글릴 모양 자체가 없습니다).

### 행은 돌아왔습니다 (같은 패스)

같은 기준을 *행*에도 밀어붙였습니다 — `/` 메뉴 항목, 모델 선택기 행, 행 메뉴 항목,
권한 네 단계, 파일 트리, 대화 목록과 이름 바꾸기 필드 — 그리고 그 절반은 실행 중인
창을 한 번 본 것으로 틀린 것으로 판명됐습니다. 행은 컨트롤 하나가 아니라 한 열의
구성원입니다: 한두 줄 높이로 이웃과 맞붙어 쌓이므로 스타디움을 입히면 목록이
버튼의 열이 됩니다. 대화 행은 271x56 — 양 끝 28px의 캡슐에 선택 워시가 실려 창에서
가장 큰 컨트롤처럼 보였고 — `/` 메뉴 행은 712x31, 컴포저 폭을 가로지르는 막대였습니다.
대화 행은 `--radius-md`, 트리와 행 안의 이름 필드는 `--radius-sm`, 모든 메뉴 항목은
`--radius-xs`로 돌아왔습니다. 창이 긋는 선은 "테두리를 칠하는가"(행은 호버에서
칠합니다)가 아니라 "누르는 하나인가, 쌓인 여럿 중 하나인가"입니다.

권한 단계 행의 2px 왼쪽 색 경계도 이것으로 정리됐습니다. 알약 위에서는 왼쪽 호를
따라 그려져 초승달이 되었는데, 곧은 왼쪽 변이 그 표시의 절반이고 스타디움에는
곧은 왼쪽 변이 없습니다. 한 가지는 의도적으로 남겼습니다 — 모델 선택기의 행은
여전히 12px 안쪽에서 시작합니다. 위의 검색 필드가 텍스트를 12px에 두는
스타디움이고, 메뉴의 행은 맨 위 필드와 같은 텍스트 열을 쓰기 때문입니다. 반지름은
모양이고, 안쪽 여백은 열입니다.

`layout.test.ts`가 이제 세 목록을 고정합니다 — `no control has a corner`,
`no row is a stadium either`, `and no container wears a control's shape`.
셀렉터 모양만 보고 컨트롤을 추측하는 테스트는 자기 추측을 검증하는 셈이므로,
클래스 이름을 목록으로 적는 것이 이 단언의 유일한 형태입니다. 선택자가 가진 *모든*
블록을 읽습니다(`body`의 마지막 블록이 아니라): 첫 실행은 `.chatrow`에서
실패했는데, 그 클래스는 `arriving.css`에 모양과 무관한 등장 애니메이션 블록을
하나 더 갖고 있고, `border-radius`가 없는 블록은 덮어쓰기가 아니라 누락이기
때문입니다.

검증: `npm test` **826 passed / 127 suites** exit 0, `npx tsc --noEmit` exit 0,
`scripts/audit_reduced_motion.py` clean, `npm run build` exit 0. 스타일시트를 읽는
데서 그치지 않고 개발 서버(`code-preview.html`, 실제 `App`)에서 렌더된 결과를
재었습니다: 예산 팝오버의 `Set`은 47x26에 999px, 숫자 필드는 154x26에 999px,
프리셋은 66x26, 서랍의 New chat은 271x40에 999px, Files 필터 271x34에 999px,
검색 필드 999px. 행은 새 모서리로 나왔습니다 — 대화 행 271x56에 16px, 그 안의
버튼 245x56에 16px, 트리 행 271x26에 12px, 행 메뉴 항목 122x31에 6px. 사각형으로
남은 컨트롤은 보이는 박스가 부모인 둘뿐입니다(알약 `label` 안의 Files 필터
`input`, 24px 필드 안의 컴포저 텍스트영역). 남은 직사각형 둘은 문서 탭(30x51)과
키캡(20x21)입니다.

미리보기에서 재지 못한 것: 모델 선택기의 검색 필드와 행, 설정 Keys 탭의 셀렉트와
공개 버튼, 코드 뷰어의 닫기 버튼. 이 스텁 코어가 그 메서드들을 답하지 않습니다.
이 셋은 렌더된 박스가 아니라 테스트로 고정되어 있으며, 이번 패스에서 "보고
확인한" 것이 아니라 "읽고 확인한" 부분입니다.
