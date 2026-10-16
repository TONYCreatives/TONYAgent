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
| `↑` `↓` | Move through the inline list |
| `Ctrl-C` | Cancel the turn · decline a confirmation · quit at an empty prompt |
| `Ctrl-D` | Quit |
| `Ctrl-Q` | Quit |
| `Ctrl-Shift-P` | The command palette · `Ctrl-P` is Textual's |
| `Ctrl-1` | Mode picker |
| `Ctrl-2` | Model picker — type to filter; grouped by provider, with price and context size |
| `Ctrl-3` | Permission picker |
| `Ctrl-4` | Refresh the context meter |

While a confirmation is open the dialog has the keyboard. **Any key that is not
`y`, `a` or `n` is a decline** — "no" is the only safe reading of a key pressed
while a destructive tool is waiting.

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
| `/model` | Model picker · `/model <id>` to set it directly |
| `/permission` | Permission picker · `/permission high` to set it directly |
| `/plan` | Show the task list |
| `/state` | What the core reports about itself |
| `/trajectory` | Frames captured this turn |
| `/usage` | What this app has spent |
| `/tools` | The per-turn tool call budget |
| `/reasoning` | Thinking effort |
| `/sandbox` | Sandbox status |
| `/conversations` | Saved conversations |
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
| `/key [provider secret]` | List keys, or save one into the OS keyring |
| `/plan` | The task list, as the model is shown it |
| `/tools [n]` | The per-turn tool call budget · `/tools 20` to set it |
| `/new [title]` | Start a conversation |
| `/conversations` | Saved conversations |
| `/usage` | What this app has spent |
| `/reasoning` | Thinking effort |
| `/sandbox` | Sandbox status |
| `/mode` `/model` `/permission` | As above |
| `/help` `/quit` `/exit` | As above |

In line mode, a leading `\` sends a turn that starts with a slash:
`\/mode is a bug` reaches the agent as `/mode is a bug`.

## What the interface shows

- **A fenced turn.** The accent rule on the left marks where one exchange
  begins and ends. The footer sits *outside* it, because it is metadata about
  the turn rather than part of the answer.
- **One line per tool call**, dimmed while it runs, then a tick or a cross. A
  tool's output longer than twelve lines is truncated from the *front*, because
  the error in a failed command is at the end.
- **Diffs**, in `--traj-add` / `--traj-del`, on the changed lines only.
- **The context meter** — real numbers from the core: the input side of your
  most recent request, against the model's own published `context_window`. It
  says *unknown*, and which of the two numbers is missing, rather than drawing
  a bar at 0%.
- **Mode, model and permission level**, always on screen.

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
```

`models.catalog` answers each model with the provider's own `context_length`
and `pricing`, in dollars per million tokens. An entry with **no** `pricing`
object is not the same as one priced at zero: the first means the gateway said
nothing, so the picker draws no label, and only the second reads `Free`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Interface looks like plain lines | stdout is not a terminal — it was piped or redirected. `--tui` forces it |
| `ModuleNotFoundError: textual` | Install the extra: `pip install -e ".[terminal]"` |
| Box characters are `?` | The terminal's locale is not UTF-8 |
| No colours | `NO_COLOR` is set, or `TERM=dumb` |
| The sidebar is missing | Terminal narrower than 108 columns — it is dropped, not squeezed |

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