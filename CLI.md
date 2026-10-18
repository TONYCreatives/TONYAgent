# The `tony` terminal frontend

Two frontends over one core. `tonyagent.window` draws it in a webview;
`tonyagent.cli` draws it in a terminal, either as a full-screen interface or as
lines. Neither owns the agent — the 41 tools, the gates and the event bus all
live in `tonyagent.core`, and both reach them the same way, over newline-
delimited JSON on a pipe.

```bash
python3 -m tonyagent.cli              # from a checkout, no install
tony                                   # if it is installed
```

## Starting on Windows

The desktop shortcut runs `Start TONYAgent (Prebuilt).bat`, and that file's
**default frontend is this one**. Double-clicking `TONYAgent.lnk` opens the
terminal interface in a `cmd` window.

```
Start TONYAgent (Prebuilt).bat           the terminal interface   (default)
Start TONYAgent (Prebuilt).bat window    the webview desktop app
```

Two things about the terminal path, both of them consequences of it being a
full-screen interface rather than a window:

- **It runs in the console you launched it from, not a new one.** `start ""`
  hands a program a fresh console and returns immediately, which is right for
  a GUI app that detaches and wrong here: the interface draws into the console
  it is attached to, so starting one detached opened a second window and closed
  the first — taking the interface down before it drew a frame.
- **It never rebuilds.** The desktop app needs a frontend bundle and a GUI
  toolkit; this needs neither and is pure Python from the checkout, so there is
  nothing to be behind. Only the `window` path asks `scripts\build_state.ps1`
  what is stale.

A default `cmd` window is often 80 columns, which is the compact sidebar tier.
Widen the window past 108 columns for the full panel; the status line carries
the context meter and the permission level either way.

## Starting

| Command | What it does |
|---|---|
| `tony` | Full-screen interface on a terminal; line mode when piped |
| `tony "fix the failing test"` | Opens the interface and sends that turn first |
| `tony -C ~/project` | Work in that folder |
| `tony --plain` | Line mode even on a terminal |
| `tony --tui` | Force the interface, even when redirected |
| `tony --raw` | The JSONL protocol on stdout, no rendering |
| `tony --hide-reasoning` | Do not print the model's thinking |

**`tony` picks its interface by whether stdout is a terminal.** Piped, it uses
line mode, which is what makes `tony "..." > out.txt` produce a readable file
rather than a screenful of escape codes.

## Keys

| Key | Does |
|---|---|
| `Enter` | Send the turn / confirm the highlighted option |
| `Esc` | Decline a question · close a picker or the inline list |
| `↑` `↓` | Move through the inline list · recall a prompt you already sent, when the field is empty |
| `PageUp` `PageDown` | Scroll the transcript |
| `Ctrl-C` | **Twice** to interrupt a turn, or twice at an idle prompt to quit |
| `Ctrl-D` | Quit |
| `Ctrl-Q` | Quit |
| `Ctrl-Shift-P` | The command palette · `Ctrl-P` is Textual's |
| `Ctrl-1` | Mode picker |
| `Ctrl-2` | Model picker — type to filter; grouped by provider, with price and context size |
| `Ctrl-3` | Permission picker |
| `Ctrl-4` | Refresh the context meter |

**`Ctrl-C` takes two presses.** The first says what the second will do --
*"press ctrl+c again to interrupt the turn"* or *"...to quit"* -- and the
second has five seconds to arrive. A terminal hands `Ctrl-C` out for a dozen
unrelated reasons, and losing a turn to one of them is not a good trade for
the keystroke.

While a confirmation is open the dialog has the keyboard. **Any key that is not
`y`, `a` or `n` is a decline** — "no" is the only safe reading of a key pressed
while a destructive tool is waiting.

`↑` is the shell's, not the list's, once the field is empty: it walks back
through the prompts you have already sent, and `↓` walks forward again, landing
on the empty field when you pass the newest. A field with something in it keeps
its own keys — a recall must not overwrite a line you are still typing.

## Mouse

| Where | Does |
|---|---|
| The `+` in the top bar | Start a new chat |
| A sidebar row's value | `mode` and `permission` open their pickers, `Chat` opens the chat list, the meter re-measures |
| A part of the status line | The same, for the model, the permission and the meter — and the only route at all below 80 columns, where there is no sidebar |
| A tool call's line | Unfold the output behind it, or fold it back |

**Every one of these also has a key**, because a click must never be the only way
to reach a feature and a terminal is not always a mouse: `Ctrl-1`, `Ctrl-2`,
`Ctrl-3`, `Ctrl-4`, `Ctrl-N`, `/conversations`. The sidebar draws each of those
keys beside the row it changes — `Model    Ctrl-2` — because the footer lists
what `BINDINGS` holds and these are handled further down, so nothing on screen
said the mode picker existed until they were written there. On a console that
does not report the mouse at all, that key is the whole feature.

Nothing else is clickable. The chrome is one row above and one row below
everything, so a click there was always aimed at it; the transcript is a body of
text, where a click is just as likely to be a selection, and it is left to the
terminal.

## Commands

### In the interface

**Typing `/` opens the list inline**, above the composer, and keeps filtering as
you type. `Enter` completes the highlighted command; `Enter` again runs it.
`Esc` closes the list and leaves the text alone. Only a *leading* `/` opens it,
so `read /etc/hosts` is still a path rather than a command.

`Ctrl-Shift-P` opens a palette of all of them, filterable by typing. Every
command below is in it. There is no longer a difference between the two
frontends' command sets.

| Command | Does |
|---|---|
| `/mode` | Mode picker · `/mode plan` to set it directly |
| `/model` | Model picker — search, grouped by provider, with price and context size · `/model <id>` to set directly |
| `/permission` | Permission picker · `/permission high` to set it directly |
| `/project` | Project folder picker · `/project <path>` to set it directly |
| `/plan` | Show the task list |
| `/state` | What the core reports about itself |
| `/trajectory` | Frames captured this turn |
| `/usage` | What this app has spent |
| `/tools` | The per-turn tool call budget |
| `/reasoning` | Thinking effort |
| `/sandbox` | Sandbox status |
| `/conversations` | The chat list: grouped by folder, `↑`/`↓` move · `enter` open · `ctrl+t` new · `ctrl+r` rename · `ctrl+y` duplicate · `ctrl+x` delete (twice) |
| `/new` | Start a conversation |
| `/key` | Provider keys in the OS keyring |
| `/help` | The palette |
| `/quit`, `/exit` | Leave |

### In line mode

The same commands, typed. Line mode has one extra: `/key <provider <secret>`
*adds* a key. In the interface `/key` lists them, because typing a secret into
a full-screen app is a worse place to do it than at a shell prompt.

| Command | Does |
|---|---|
| `/state` | Everything the core reports about itself |
| `/key` | Set, replace or remove a provider key: `enter` edit · `tab` name · `ctrl+r` remove (confirmed) |
| `/delegate [model]` | Run turns through `opencode` itself, which is the only way to reach its free models |
| `/plan` | The task list, as the model is shown it |
| `/tools [n]` | The per-turn tool call budget · `/tools 20` to set it |
| `/new [title]` | Start a conversation |
| `/conversations` | The chat list: grouped by folder, `↑`/`↓` move · `enter` open · `ctrl+t` new · `ctrl+r` rename · `ctrl+y` duplicate · `ctrl+x` delete (twice) |
| `/usage` | What this app has spent |
| `/reasoning` | Thinking effort |
| `/sandbox` | Sandbox status |
| `/mode` `/model` `/permission` `/project` | As above |
| `/help` `/quit` `/exit` | As above |

In line mode, a leading `\` sends a turn that starts with a slash:
`\/mode is a bug` reaches the agent as `/mode is a bug`.

## What the interface shows

- **Your own message**, on a `--raised` chip above the agent's answer. The
  window calls it a bubble; a terminal has none, so the fill is what marks it.
- **The open tab**, at the very top: the chat's name in the accent bar, the
  mode dimmed beside it, and a **`+` you can click** to start a new chat
  (`Ctrl-N` or `/new` do the same). The chat leads because it is the tab -- it
  identifies what is on screen, where the mode says what the agent may do.
- **The open chat**, named in the sidebar too, so it is visible whether you are
  looking up or across — and the row is the mouse's way into the chat list.
- **The panel on the right, in three sizes**: full at 108 columns, written out
  from 80 — each row with its key (`Model    Ctrl-2`), the meter as
  `314,139 / 1M  31%` over a twenty-cell bar — and gone below that, where the
  status line carries the same facts. **108 is wider than a plain console
  window**: 1920 pixels at a readable font is about 106 columns, so a rule that
  needed 108 hid the panel from exactly the people who never resize.
- **A fenced turn.** The accent rule on the left marks where one exchange
  begins and ends. The footer sits *outside* it, because it is metadata about
  the turn rather than part of the answer.
- **One line per tool call**, dimmed while it runs, then a tick or a cross. A
  tool's output longer than twelve lines is truncated from the *front*, because
  the error in a failed command is at the end. **Click the line** to unfold the
  tail of that output underneath it, and click again to fold it back. A call
  with nothing behind the line draws no `▸` and does not open, because a marker
  over nothing is a promise the click cannot keep.
- **Diffs**, in `--traj-add` / `--traj-del`, on the changed lines only.
- **The context meter** — real numbers from the core: the input side of your
  most recent request, against the model's own published `context_window`. It
  says *unknown*, and which of the two numbers is missing, rather than drawing
  a bar at 0%.
- **Mode, model and permission level**, always on screen.

## OpenCode Go and OpenCode Zen are two different services

They are easy to confuse and they do not share a bill.

| | Go | Zen |
|---|---|---|
| Endpoint | `opencode.ai/zen/go/v1` | `opencode.ai/zen/v1` |
| Key | your subscription | a separate API key |
| Catalogue | 37 models | 86 models |
| `space-bunny` | yes | no |
| `space-bunny-free` | no | yes — **but unusable here, see below** |

**A Go key does not pay for Zen.** Sending it authenticates, loads the
catalogue, and then every turn answers `402 Insufficient account funds`,
because the balance lives on the Zen account. That looks like a bug in here
rather than an empty balance, which is why it is written down.

**Zen's `-free` models refuse to run outside OpenCode.** `space-bunny-free`,
`cat-jam-free`, `longcat-2.5-preview-free` and the rest answer:

```
403 FreeTierError: OpenCode's free tier can only be used from within OpenCode.
```

Not a missing header, not an absent key — the same with no credentials at all,
and the same with a valid one. The free tier is a funnel into OpenCode's own
client, so those ids stay in the catalogue and the provider's own refusal
stands, rather than being hidden here behind a list that looks complete and
cannot deliver.

## Reaching OpenCode's free models: `/delegate`

The `-free` models refuse to run outside the OpenCode client (see above), and
that is the server deciding — no header set here changes it. The one thing that
*is* OpenCode is the OpenCode binary, so:

Works on Windows as well as Linux: npm installs `opencode.cmd`, not
`opencode.exe`, and the delegate goes through `COMSPEC /c` to reach it.

```
/delegate                               # pick a model, from opencode's list
/delegate opencode/space-bunny-free     # or name one and skip the picker
```

**It asks which model, because the default is the problem.** With no
`--model`, `opencode run` uses whatever OpenCode has configured -- not a free
model unless you made it one -- and the free tier is the entire reason to be
here. The list comes from `opencode models`; the `-free` ones are marked.

**`/model` is one list, aligned by service.** It shows the core's catalogue
*and* `opencode models` in a single picker, under service headings:

```
current
  opencode-go/kimi-k3            ·  262K ctx  Free  ·  also via opencode
OpenCode Go
  opencode-go/deepseek-v4-pro    163K ctx  $1 in · $3 out  ·  also via opencode
  opencode-go/cat-jam-free                    opencode only
OpenCode Zen
  opencode-zen/claude-sonnet-5-5 1M ctx  $3 in · $15 out
OpenCode free (client only)
  opencode/space-bunny-free                   opencode only
OpenRouter
  openrouter/auto
```

Three things that list gets right, each of which was wrong first:

- **Aligned, not concatenated.** `opencode models` returns both `opencode-go/…`
  and `opencode/…`, and `opencode-go` is *also* a core provider. Appending one
  list to the other put the same heading twice, one subscription looking like
  two. Rows are grouped first and flattened second.
- **One row per model, not one per route.** A model both routes serve gets one
  row with its price and context, annotated `also via opencode` -- rather than a
  priced row and an unpriced one, which reads as two models.
- **Choosing a row starts the route it names.** Picking a client-only model
  starts the delegate; picking a core model turns the delegate off. A model
  that is chosen and then ignored by every turn is worse than one never offered.

The top bar says `opencode · <model> · --auto` while it is on. **Two backends, not two
providers** — and the distinction matters: OpenCode executes its own tools, so a
provider adapter carrying its tool calls would make TONYAgent run every one of
them a second time.

What changes, plainly:

- **OpenCode's agent does the work.** TONYAgent's tools, permission levels and
  sandbox are not in the loop.
- **`--auto` is passed, so OpenCode's tools are approved without asking.**
  `opencode run` is non-interactive and cannot answer a permission prompt, so
  without it a turn that reads a file dies. This is a real loosening of your
  guardrails, which is why the bar spells it out rather than implying it.
- **Ctrl-C twice kills the process.** There is no socket to ask politely
  through.
- **The context meter is a low-water mark.** OpenCode does not close its last
  step, so the final token count is never sent; the newest real figure is from
  the step before.

What stays: your top bar, chat list, transcripts, `/trajectory`, `/usage`.

## Using an OpenCode Go key

TONYAgent already speaks to **OpenCode Go** — `https://opencode.ai/zen/go/v1`,
OpenAI-compatible, with the `x-opencode-session` header it requires. There is
nothing to link or integrate. Its key goes in like any other:

```
/key                      # the provider list
enter                     # pick opencode-go
paste oc_sk_…             # masked, never echoed
enter                     # saved to the OS keyring
```

Then `/model` lists what the subscription actually serves — the picker reads
the live catalogue, so the TUI-only models such as `space-bunny` appear
alongside everything else without being seeded in the source.

Two things worth knowing:

- **The typed key is never rendered.** Not masked-with-a-placeholder, not
  shown-on-reveal: the core's rule is that a value on stdout is a value in a
  log strip and a screenshot, and `key.reveal` is deliberately not wired here.
- **`ctrl+r` removes, and confirms first.** `ctrl+x` was the first choice and it
  is the filter field's `cut`.

## Permission levels

| Level | What it permits |
|---|---|
| `low` | Read, search, browse. Nothing in the project changes |
| `medium` | The above, plus edit and write. Shell commands are **refused** |
| `high` | Everything, including any command, still sandboxed, still asks |
| `full` | Everything, without asking, **no sandbox** — commands run as you |

`a` on a confirmation raises the session's level one step, and says so first. It
cannot remember a single tool: `confirm.respond` takes a bool and the protocol
has no per-tool allowlist.

## The `unknown` in the context meter

Two different reasons, and they look the same unless it says which:

- **no usage reported yet** — normal on a fresh install; there is no request
  to have measured
- **model publishes no window** — the provider's `/models` response had no
  `context_length`, so there is no denominator and there never will be

## Piping

```bash
tony "summarise this repo" > summary.txt     # line mode, readable file
tony --raw < requests.jsonl                  # drive the protocol directly
```

`--raw` prints every event as JSON and reads one request object per line, so
the whole protocol is drivable from a shell:

```json
{"method": "state"}
{"method": "mode.set", "params": {"mode": "plan"}}
{"method": "context.get"}
{"method": "models.catalog"}
{"method": "update.check"}
```

`models.catalog` answers each model with the provider's own `context_length`
and `pricing`, in dollars per million tokens. An entry with **no** `pricing`
object is not the same as one priced at zero: the first means the gateway said
nothing, so the picker draws no label, and only the second reads `Free`.

`update.check` answers whether a newer release exists, and **it answers rather
than raising** — unlike every other method here. It is a question the app asks
on its own behalf at startup, so an offline machine must not produce an error
about a feature nobody invoked. The reply carries a `reason` instead:

```json
{"current": "0.1.0", "latest": "v0.2.0", "available": true, "reason": ""}
```

`reason` is empty when the question was answered, and otherwise one of
`offline`, `rate_limited`, `not_found`, `server` or `malformed`. **A non-empty
reason is not "up to date"** — a check that could not reach GitHub has not
learned that this version is the newest. `force` skips the day-long cache:

```json
{"method": "update.check", "params": {"force": true}}
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| Interface looks like plain lines | stdout is not a terminal — it was piped or redirected. `--tui` forces it |
| `ModuleNotFoundError: textual` | Install the extra: `pip install -e ".[terminal]"` |
| Box characters are `?` | The terminal's locale is not UTF-8 |
| No colours | `NO_COLOR` is set, or `TERM=dumb` |
| The sidebar is missing | Terminal narrower than 80 columns — it is dropped, not squeezed. Written out below 108, too |

## The window's palette

Every colour is read from `app/src/styles/tokens.css`, value for value, so the
interface and the window are one product. The rule that decides it is the
window's own:

> Every one of those is achromatic — r === g === b, with no tint. … Here the
> accent is the only chroma on screen, so it means "this application" rather
> than "something coloured".

So there is no violet heading here, however good it looked in another terminal
application. `#6393f0` is the accent, plus `--ok`, `--danger`, `--warn` and the
diff pair. Truecolor where the terminal has it; the 256-colour cube where it
does not.