# Whittle architecture

The implementation blueprint. `design.md` says *what* Whittle is, `decisions.md`
resolves its open questions, and this document says *how* it is built. Where they
disagree, `decisions.md` wins over `design.md`, and this document wins over both on
implementation detail (module names, wire formats, file formats). Every bpy and SDK
name used here was checked against Blender 5.2.2 and `claude-agent-sdk` 0.2.167; see
the [API notes](#appendix-api-notes) appendix.

---

## 1. Repository layout

```
whittle/                          repo root
├── whittle/                      the extension package (this dir is what gets built)
│   ├── blender_manifest.toml
│   ├── LICENSE                   GPL-3.0 text, so the built zip carries it
│   ├── __init__.py               bpy-free at import time; register()/unregister() delegate to .addon
│   ├── protocol.py               stdlib only: envelope, framing, ids, error codes, method/event names
│   ├── formats.py                stdlib only: request bundle + session folder read/write/validate
│   ├── tree.py                   stdlib only: history tree, session.json, the branching rule
│   ├── chats.py                  stdlib only: the chat index, packing a chat for the .blend (§14)
│   ├── caches.py                 stdlib only: each file's hidden chats cache, its id and cleanup (§14)
│   ├── markdown.py               stdlib only: Claude's Markdown (and its TeX, HTML) as Lines for the sidebar
│   ├── models.py                 stdlib only: model ids by family and version, the model list's cache (§15)
│   ├── venv.py                   stdlib only: venv status, setup commands, the VenvSetup state machine
│   ├── requirements.lock         byte-identical copy of agent_env/requirements.lock (packaging step)
│   ├── addon/                    Blender side; may import bpy everywhere
│   │   ├── __init__.py           register()/unregister() for every class, handler and timer
│   │   ├── paths.py              user dir, the open file, the cache and CLI config folders, agent python resolution
│   │   ├── prefs.py              AddonPreferences
│   │   ├── setup.py              the venv on the Blender side: checks, timer, install/cancel operators
│   │   ├── start.py              start points (existing, blank, primitive, asset) and their helpers
│   │   ├── refs.py               reference images: clearing sent ones, pinning, image empties
│   │   ├── props.py              Scene PropertyGroup (scene.whittle)
│   │   ├── process.py            AgentProcess: spawn, handshake, crash detection, shutdown
│   │   ├── bridge.py             Bridge: listening socket, framing, pending calls, tick()
│   │   ├── commands.py           handlers for agent→Blender calls (exec, inspect, render, …)
│   │   ├── execution.py          exec namespace, stdout capture, scene diff
│   │   ├── meshcheck.py          whittle.mesh_report / whittle.weld for agent code
│   │   ├── render.py             Workbench renders, view cameras, overlay compositing
│   │   ├── sketch.py             Whittle Sketch GP object, type layers, stroke tagging
│   │   ├── views.py              view capture from RegionView3D, camera.json
│   │   ├── bundle.py             gathers strokes/views/refs from bpy → formats.write_request
│   │   ├── snapshot.py           libraries.write / load for history nodes and checkpoints
│   │   ├── history.py            History: node snapshots, thumbnails, restore, branch
│   │   ├── chats.py              chats: the file's cache, save/load into the .blend, migration (§14)
│   │   ├── models.py             the model per chat: the list, the model menu and its operators (§15)
│   │   ├── compare.py            A/B compare against a node, the parent ghost
│   │   ├── turn.py               TurnController: submit/amend/interrupt/finish state machine
│   │   ├── stream.py             sidebar entries (tool calls merged with results), transcript.jsonl writer
│   │   ├── transcript.py         the session transcript as text, for the Whittle Transcript datablock
│   │   ├── targets.py            the target picker (object list + collection on scene.whittle)
│   │   ├── autotarget.py         Auto: the target list follows the selection
│   │   ├── conversation.py       the conversation the sidebar draws, built from the history and stream
│   │   ├── enter.py              Enter sends from the prompt box (the confirm window, the keymap)
│   │   ├── previews.py           render thumbnails (bpy.utils.previews)
│   │   ├── editors.py            showing an image or text in an editor from the sidebar
│   │   ├── operators.py          WHITTLE_OT_* operators
│   │   ├── shortcut.py           Shift+Alt+C: the sidebar plus a prompt popup, ready to type
│   │   └── ui.py                 WHITTLE_PT_* panels and plain draw functions
│   └── agent/                    agent process; NEVER imports bpy
│       ├── __init__.py
│       ├── __main__.py           `python -m whittle.agent --port N [--fake SCRIPT]`
│       ├── connection.py         asyncio bridge client (mirror of addon/bridge.py)
│       ├── dispatch.py           Runner protocol; checks Blender's call params and routes them
│       ├── runner.py             SdkRunner (the only module importing claude_agent_sdk)
│       ├── store.py              FolderSessionStore: a chat's SDK transcripts in its folder (§14)
│       ├── tools.py              MCP tool handlers (plain async functions) + server builders
│       ├── fake.py               FakeRunner: scripted agent for tests, stdlib only
│       ├── prompt.py             builds the system prompt from system_prompt.md + settings
│       ├── system_prompt.md      Whittle conventions and modeling practice (docs/modeling-practices.md)
│       └── plugin/               local plugin (Claude Code plugin format) carrying the recipe skills
│           ├── .claude-plugin/plugin.json      {"name": "whittle", "version": …, "description": …}
│           └── skills/<skill-name>/SKILL.md
├── agent_env/requirements.lock   pinned, hashed lock (never edited by hand)
├── tests/
│   ├── agent/                    unittest, run with .venv/bin/python
│   ├── blender/                  unittest, run inside `blender -b`; run.py is the entry point
│   ├── fixtures/                 crate request bundle (+ scene.py, make_bundle.py), fake agent scripts
│   └── screens/                  sidebar screenshots: catalog.py (scenarios), scenarios.py, harness.py
│                                 (runs inside each GUI Blender), run.py (drives them)
├── run_tests.sh                  the single test command
├── build.sh                      validates and builds the extension zip into build/ (gitignored)
├── screens.sh                    sidebar screenshots into build/screens/ (README)
├── README.md                     what it is, install, API key, use, privacy, development, tests
├── CONTRIBUTING.md               how to propose a change
├── LICENSE                       GPL-3.0 (the project is GPL-3.0-or-later)
└── docs/
```

Rules:

- Every source file starts with `# SPDX-License-Identifier: GPL-3.0-or-later` (after a
  shebang), and the manifest says `license = ["SPDX:GPL-3.0-or-later"]`.
- `whittle/__init__.py`, `protocol.py`, `formats.py`, `tree.py`, `chats.py`, `caches.py`, `models.py`, `venv.py` and everything under `agent/`
  import only the stdlib at module level. `agent/runner.py` imports `claude_agent_sdk`;
  nothing else does, so the fake agent and the formats code run under any Python 3.14,
  including Blender's.
- `addon/*` may import `bpy`, `bmesh`, `mathutils`, `gpu`, `numpy` (numpy ships with
  Blender). It never imports `whittle.agent`.
- Inside Blender the package is imported as `bl_ext.<repo>.whittle`; in tests it is
  imported as `whittle` from the repo root. Code uses relative imports only, and
  `__package__` for preference lookups.

### `whittle/__init__.py`

```python
def register():
    from . import addon
    addon.register()

def unregister():
    from . import addon
    addon.unregister()
```

This is what lets the agent process run `python -m whittle.agent` without bpy.

### System prompt

`agent/system_prompt.md` is read every turn, so it stays short: which tool to reach for,
scope, turn shape, writing to the user, steering and context, modeling practice, conventions
and stroke types. It is written to [prompting.md](prompting.md): practices with reasons,
one home per fact (what `exec` pre-imports, the `whittle` helpers and the bpy gotchas live
in the tool descriptions, not here), and `<whittle_context>` / `<user_amendment>` tags
for text Whittle adds to a turn. The modeling practice
(one closed shell for parts that belong together, no faked joins, what stays separate,
live or baked booleans, topology, shading, remeshing, a loose triangle budget) is written
as defaults with reasons rather than hard rules; the research behind it and its sources
are in [modeling-practices.md](modeling-practices.md). Long technique detail lives in the
skills. `prompt.build` fills `$self_check_rounds`, `$poly_budget`, `$render_size` and
`$style_notes`.

### Recipe skills

Skill names (directory names under `agent/plugin/skills/`, `name:` in frontmatter):
`mesh-check`, `fuse-parts`, `blockout-silhouette`, `extrude-along-stroke`,
`boolean-carve`, `bevel-crease`, `mirror-array`, `lathe-profile`, `vertex-colour-paint`,
`gn-scatter`. Each `SKILL.md` is self-contained (no scripts, no references to other
files), because the agent has no `Read` tool. They are enabled as
`skills=["whittle:<name>", …]`. `mesh-check` explains the numbers `whittle.mesh_report`
returns; `fuse-parts` grows parts from a surface, unions them in, or repairs overlapping
shells with a self-union.

---

## 2. Processes and lifecycle

```
Blender (main thread)                               Agent process (.venv python, asyncio)
─────────────────────                               ─────────────────────────────────────
listen 127.0.0.1:0  ──spawn argv --port, env token──▶ connect
                    ◀──────── hello{token} ───────── 
verify token        ───────── welcome ────────────▶
                    ── call start_session ────────▶ build ClaudeAgentOptions, ClaudeSDKClient.connect()
                    ── call submit ───────────────▶ client.query(...)
                    ◀── event text/tool_use … ────── receive_messages() loop
                    ◀── call exec/render/… ────────  MCP tool handler awaits the result
run on main thread  ── result ────────────────────▶
                    ◀── event turn_finished ───────  ResultMessage
                    ── call shutdown ─────────────▶ disconnect, exit 0
```

### Spawn

`addon/process.py` `AgentProcess.start(session_dir)`:

1. Resolve the agent Python (`paths.agent_python()`), first hit wins:
   env `WHITTLE_AGENT_PYTHON` → preference `agent_python` (dev override) →
   the private venv's `bin/python` (`Scripts/python.exe` on Windows), but only when
   `venv.status()` is `ready` (§9). Missing → state `needs_setup` with
   `paths.agent_python_problem()` (stale, broken, foreign) or "not set up yet" as the
   reason; the sidebar offers the venv install operator.
2. Resolve the API key (`prefs.api_key()`, see **Authentication** below). None, for
   a real agent → state `needs_key` with "Add an Anthropic API key in Preferences to
   run Claude"; nothing is spawned and the sidebar asks for a key. The fake agent
   needs none. Typing a key in the preferences clears `needs_key` (`clear_key`).
3. Refuse to spawn a real (non-fake) agent when `bpy.app.online_access` is False; show
   "Allow Online Access in Preferences → System". The fake agent ignores this.
4. Create a listening socket: `socket.create_server(("127.0.0.1", 0))`, `setblocking(False)`,
   backlog 1. Read the port back with `getsockname()[1]`.
5. Generate `token = secrets.token_hex(32)`.
6. `subprocess.Popen([python, "-s", "-P", "-m", "whittle.agent", "--port", str(port)] + extra,
   cwd=session_dir, env=env, stdin=DEVNULL, stdout=log, stderr=STDOUT)` where
   - `env` = `process.agent_environment(os.environ, api_key=…, config_dir=…)` plus
     `PYTHONPATH=<parent dir of the whittle package>` and `WHITTLE_TOKEN=<token>`: see
     **Authentication**. The token and the key travel in the environment, not argv, so
     they never show in `ps`.
   - `extra` is `["--fake", script_path]` for the fake agent.
   - `log` = `<user dir>/logs/agent-<YYYYmmdd-HHMMSS>.log`, opened for append. A file,
     not a pipe, so a chatty agent can never block on a full pipe buffer. Keep the 10
     newest logs.
7. State → `starting`, with a 30 s handshake deadline.

### Authentication

Whittle runs Claude only with the user's own Anthropic API key. Anthropic's terms for
products built on the Agent SDK ask for API key authentication and do not allow a
third-party product to offer claude.ai login or to route requests through a Free, Pro
or Max plan ([Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview),
[Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)).

- **Where the key comes from** (`prefs.api_key()` → `(key, source)`): the **Anthropic
  API Key** preference (`subtype="PASSWORD"`), stripped; else `ANTHROPIC_API_KEY` in
  Blender's own environment; else none. The preference wins: it is what the user typed
  for Whittle, while the environment may be a shell's key for something else. The
  preferences say which one is used and link to the Console's key page
  (`prefs.KEYS_URL`).
- **No key**: the agent does not start (`needs_key`, above). Send leaves the prompt in
  the box and the attention box asks for a key (`docs/ui.md` §3.2).
- **The agent's environment** (`agent_environment`): Blender's, minus every variable
  whose name starts with `ANTHROPIC_` or `CLAUDE` except `ANTHROPIC_BASE_URL` and
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` (the user's telemetry opt-out), plus
  `ANTHROPIC_API_KEY` (the resolved key) and `CLAUDE_CONFIG_DIR`. That drops
  `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, the Bedrock, Vertex and Foundry
  switches, key and token file descriptors, `CLAUDECODE` and the rest, so the bundled
  CLI has no way to sign in but the key.
- **The CLI's configuration folder**: `CLAUDE_CONFIG_DIR` = `paths.claude_config_dir()`,
  `<user dir>/claude/`. The CLI keeps its state and transcripts there and never reads
  the user's own Claude configuration: no login, settings (an `apiKeyHelper`), hooks,
  MCP servers or skills of theirs. (`setting_sources=[]` and `strict_mcp_config` already
  keep settings and MCP servers out.) The SDK's resume into a temporary config folder
  (§14) seeds it from this folder, so a resume finds no login either.
- **The binary is not modified**: Whittle only chooses the environment and the
  folder it runs the bundled CLI with.
- **The key is written nowhere else**: it is in Blender's preferences (`userpref.blend`)
  and in the agent process's environment. Logs, the session files and the controller
  keep at most its SHA-256 digest (`launch_settings`, to notice a changed key), and the
  CLI is never given it in argv. `tests/blender/test_auth.py` checks the user folder
  and the agent's log after a run hold no copy.
- **A refused key**: an error naming an invalid API key, `authentication_error`, HTTP
  401 or "not logged in" sets `TurnController.key_problem` ("The API key was
  refused"); the attention box links to the preferences and the Console.

### Handshake

The first line the agent sends must be `hello` with the right token
(`hmac.compare_digest`) and `protocol == protocol.VERSION`. Blender then accepts no
further connections (closes the listener) and answers `welcome`. Anything else — wrong
token, wrong version, a non-`hello` first line, a deadline miss — closes the
connection, kills the process and sets state `failed` with the reason.

### States (`AgentProcess.state`)

`stopped` → `starting` → `ready` ⇄ `busy` (a turn is running) → `stopping` → `stopped`;
any state → `crashed` or `failed`. `needs_setup` when no agent Python exists,
`needs_key` when there is no API key.

### Crash detection

Every bridge tick: `popen.poll()`; and a `recv` returning `b""` or raising
`ConnectionError` means EOF. Either one while not `stopping` → `crashed`:
- every pending Blender→agent call fails locally with `agent_crashed`;
- an `ask` waiting in the UI is cancelled;
- a running turn is finalised as a node with `status: "failed"` (the scene is left as
  it is; the user may restore the parent node);
- the sidebar shows the last 20 lines of the log and a **Restart agent** button.
  Restarting resumes the current node's SDK session (§6).

The agent exits with code 0 on socket EOF, so it never outlives Blender.

### Shutdown

`AgentProcess.stop()`: send `shutdown`, state `stopping`. The agent then closes its SDK
session, which can take a while (`__main__` gives `runner.close()` 15 s, the runner's
`STOP_TIMEOUT` is 10 s). Ticks wait for exit: 20 s after `shutdown` → SIGTERM; 5 s
later → SIGKILL. On Blender quit (`bpy.app.handlers.exit_pre`) and on `load_pre` the
same sequence runs synchronously with `popen.wait(timeout=…)`, since no more ticks will
come, with a shorter 10 s before the SIGTERM. `unregister()` does the same.

The agent runs in its own process group (`start_new_session=True`), and every terminate
or kill goes to the whole group (`os.killpg`), so the Claude Code CLI the SDK runs goes
with it, also when the bridge fails or the handshake times out. The agent handles
SIGTERM like `shutdown`: it still closes its session, so the SDK's temporary config
folder (which holds a copy of the credentials) is removed.

---

## 3. The bridge protocol

`whittle/protocol.py` holds every constant below; both sides import it.

### Framing

- TCP on `127.0.0.1`, one connection per agent process.
- UTF-8 **JSON lines**: one JSON object per line, `\n`-terminated,
  `json.dumps(obj, separators=(",", ":"), ensure_ascii=False)`. No embedded newlines
  (json escapes them).
- Maximum line length `MAX_LINE = 16 MiB`; a longer line is a protocol error that drops
  the connection. Images never travel over the socket: Blender writes PNGs to the
  session folder and sends paths; the agent reads the files.
- `protocol.encode(msg) -> bytes`, `protocol.LineDecoder.feed(bytes) -> list[dict]`
  (keeps the partial tail, raises `ProtocolError` on bad JSON or over-long lines).

### Envelope

Every message has `"v": 1` and `"type"`:

| type | fields | meaning |
|---|---|---|
| `hello` | `token`, `protocol`, `pid`, `agent_version`, `mode` (`"sdk"`/`"fake"`) | agent → Blender, first line only |
| `welcome` | `protocol` | Blender → agent, reply to hello |
| `call` | `id`, `method`, `params` (object) | request; either direction |
| `result` | `id`, `ok` (bool), `data` (object, when ok) or `error` (when not ok) | reply to a call with the same `id` |
| `event` | `name`, `data` (object) | one-way notification, agent → Blender only |

- **ids** are strings: the sender's prefix plus a per-connection counter — `"b1"`,
  `"b2"` from Blender, `"a1"`, `"a2"` from the agent. Each side keeps a dict of its
  pending ids. A `result` for an unknown id is logged and dropped.
- **error** shape: `{"code": str, "message": str, "detail": str | null}`. `detail`
  carries a traceback where useful. Codes (`protocol.ErrorCode`):

  | code | when |
  |---|---|
  | `bad_request` | params missing or of the wrong type |
  | `unknown_method` | no handler for `method` |
  | `not_found` | named object / view / checkpoint does not exist |
  | `busy` | `submit` while a turn is running |
  | `interrupted` | queued call dropped because the turn was interrupted; `ask` cancelled |
  | `no_session` | `submit`/`amend` before `start_session` |
  | `agent_crashed` | local failure of pending calls when the peer is gone |
  | `timeout` | the caller gave up waiting (agent side, §5) |
  | `internal` | unexpected exception in a handler (`detail` = traceback) |

  A failure *inside agent-supplied code* is not a bridge error: `exec` returns `ok: true`
  with an `error` field in `data` (below). Bridge errors are reserved for the protocol
  and the system.

### Blender → agent calls

| method | params | data on success |
|---|---|---|
| `start_session` | `session_dir`, `store_dir` (the chat's SDK transcript store or null, §14), `model`, `resume` (sdk session id or null), `fork` (bool), `resume_at` (message uuid or null: where a fork cuts the resumed conversation, §6), `settings` (`{self_check_rounds, poly_budget, style_notes, render_size}`, plus optional `max_turns`, `max_budget_usd` passed to the SDK) | `{}` — replaces any live SDK client; answered once the SDK client has connected |
| `submit` | `turn_id` (node id), `bundle_dir` (absolute), `prompt` (str), `context` ([str], optional, default []: lines from Whittle put before the prompt), `model` (str or null: the chat's model; a live session on another one is switched to it before the query, §15) | `{"accepted": true}` immediately; the turn then streams events |
| `amend` | `turn_id`, `amend` (int, the amendment number; optional for older callers), `text` (may be ""), `bundle_dir` (absolute amend bundle or null) | `{"queued": true}`; `no_session` before `start_session`, `not_found` when `turn_id` is not the running turn (it already finished) |
| `interrupt` | `turn_id` | `{}` |
| `ping` | `{}` | `{"time": float}` |
| `shutdown` | `{}` | `{}`; the agent disconnects the SDK client and exits 0 |

### Agent → Blender calls

| method | params | data on success |
|---|---|---|
| `exec` | `code` (str), `label` (str, short, for the UI) | `{"stdout": str, "error": {type, message, traceback} \| null, "diff": SceneDiff, "notes": [str]}` |
| `inspect` | `query` (`"summary"`, `"object"`, `"materials"`, `"node_groups"`, `"scene"`), `name` (str, for `"object"`) | query-specific JSON (see `commands.py`), always plain JSON, plus `"notes": [str]` |
| `render` | `view` (int or null; the request's views and those of the running turn's amendments), `camera` (`{location: [x,y,z], look_at: [x,y,z], lens_mm: float}` or null), `mode` (`"shaded"`, `"wireframe"`, `"matcap"`, `"overlay"`), `size` (int, default from settings, 16..1024) | `{"path": str, "strokes_path": str \| null, "width": int, "height": int, "ms": float, "notes": [str]}` |
| `checkpoint` | `label` | `{"checkpoint_id": str, "label": str, "restorable": true, "objects": [names], "notes": [str]}` — snapshots the turn's targets plus the objects it created to `nodes/<turn>/checkpoints/c<k>.blend`; ids `c1`, `c2`, … start again each turn; `bad_request` outside a turn |
| `restore_checkpoint` | `checkpoint_id` | `{"restored": [object names], "removed": [object names], "notes": [str]}` — puts the checkpoint back and removes the objects the agent made after it; `not_found` for an id not taken this turn, `bad_request` outside a turn |
| `ask` | `question`, `choices` (list of str, may be empty) | `{"answer": str, "notes": [str]}` — the result is sent when the user answers; `notes` carries any note that came up during the pause. In background Blender (nobody to answer) it returns at once with `{"answer": "", "unattended": true}` |

`render` needs exactly one of `view` / `camera`; `overlay` mode needs `view`.
`SceneDiff` = `{"added": [name], "removed": [name], "changed": [{"name": str, "fields": [str]}]}`
computed from a per-object summary (type, location/rotation/scale rounded to 1e-4,
mesh vert/edge/face counts, modifier names+types, material names, parent) taken before
and after the code runs.

`notes` carries one-off Blender-side messages for the model on the next `exec`,
`inspect`, `render`, `checkpoint`, `restore_checkpoint` or `ask` result. One is sent
today: `turn.UNDO_NOTE`, when the user presses Ctrl+Z during a turn (§8 of ui.md). The
agent prints them as `note: …` lines. Amendments travel separately (§5).

### Agent → Blender events

All carry `turn_id` (null outside a turn).

| name | data |
|---|---|
| `status` | `state` (`"idle"`, `"connecting"`, `"running"`, `"waiting_user"`, `"interrupting"`, `"session_ended"`), `detail` |
| `turn_started` | `turn_id` |
| `text` | `text` — one full assistant `TextBlock` |
| `thinking` | `text` |
| `tool_use` | `tool_use_id`, `tool` (short name, e.g. `exec`), `input` (dict) |
| `tool_result` | `tool_use_id`, `is_error`, `summary` (first 500 chars of text content), `images` (paths) |
| `turn_finished` | `session_id`, `subtype`, `is_error`, `interrupted` (bool), `cost_usd` (this turn), `session_cost_usd` (the SDK session's running total), `num_turns`, `duration_ms` (both summed over the turn's queries), `result_text`, `errors` (list of str), `amends_undelivered` ([int]: amendments queued but never delivered — interrupt, session end, CLI crash), `message_uuid` (str \| null: uuid of the turn's last `AssistantMessage`/`UserMessage`, where a later branch forks) |
| `amend_delivered` | `amend` (int), `via` (`"tool_result"` \| `"query"`) |
| `error` | `code`, `message` — non-fatal agent-side failure (e.g. SDK connect failed) |
| `log` | `level`, `message` |
| `models` | `models` ([str]: model ids the account offers), `source` (`"api"`: the Models API's list; `"cli"`: the CLI's own, when the Models API gave none) — once per agent process, after its first session connects (§15) |

`session_ended` means the SDK session stopped on its own (the CLI's message stream
ended) while the agent process lives on. Blender clears `session_ready` so the next
run starts a new one (resuming the conversation, §6). If a submit races ahead of that status and comes back
`no_session`, the `TurnController` starts a session and resends the same bundle under
the same node.

Partial streaming (`include_partial_messages`) is off: the sidebar shows whole text
blocks as they complete.

---

## 4. Blender side: the main-thread command queue

`addon/bridge.py` owns one `Bridge` per agent connection; `bpy.app.timers` drives it.

```python
class Bridge:
    def tick(self) -> float:          # timer callback; also called directly by tests
    def call(self, method, params, on_result) -> str   # Blender → agent, async
    handlers: dict[str, Handler]      # agent → Blender methods (commands.py)
```

`tick()` does, in order:

1. Accept/handshake while `starting`; check the handshake deadline.
2. `popen.poll()` and drain the socket with non-blocking `recv(65536)` until
   `BlockingIOError`; feed the `LineDecoder`.
3. Dispatch each decoded message:
   - `result` → pop the pending Blender call and run its `on_result(ok, data_or_error)`.
   - `event` → `stream.append(event)` and the `TurnController`; redraw VIEW_3D areas
     (`area.tag_redraw()` for every window's VIEW_3D area).
   - `call` → append `(id, method, params)` to `self.queue` (a `collections.deque`).
4. Run queued calls on the main thread: pop and run until the queue is empty or 30 ms
   have elapsed, but always at least one, and stop after any `render` (renders are slow;
   one per tick keeps the UI responsive). Each handler is wrapped: `BridgeError(code,
   message)` → error result; any other exception → `internal` with the traceback.
   A result that cannot be JSON-encoded is replaced by an `internal` error, and
   `protocol.encode` writes lone surrogates as `\uXXXX` escapes, so a reply is always
   sent.
5. Flush the outbound buffer with non-blocking `send`; keep the unsent tail for the next tick.
6. Return the next interval: `0.01` if the queue or outbound buffer is non-empty,
   `0.05` while `busy`, `0.2` while `ready`, `None` (unregister) once `stopped`.

The timer is registered with `persistent=True`; file loads are handled explicitly (§2).
Blender drops a timer whose callback raises, so the callback catches anything that
escapes `tick()`, logs it and crashes the agent process, rather than leaving the agent
connected to a socket nobody reads. Exceptions from `on_event` and `on_result`
callbacks are logged and do not stop the tick.

`stop()` before the handshake sets `stopping`; when the hello arrives the shutdown is
sent then, and the state stays `stopping`. Any state other than `starting`, `ready` or
`busy` drops a run that was waiting for the agent, and `run_bundle` raises when the
agent cannot be started, so the operator reports it.

**Deferred results.** `ask` returns `Deferred()` instead of data. The bridge records the
call id; the sidebar shows the question and the answer operator calls
`bridge.resolve(call_id, data)`. Interrupt and crash resolve every deferred call with
`interrupted`.

**Interrupt.** `TurnController.interrupt()` sends `interrupt`, and marks the bridge
interrupted: queued (not yet started) agent calls are answered `interrupted` without
running; the call currently executing always completes (it is atomic on the main
thread). The flag clears at `turn_finished`.

**Modal operations.** A call that changes the scene (`exec`, `restore_checkpoint`,
`render`, `checkpoint`) waits in the queue while some window runs a modal operator
(`bridge.modal_running()`: a transform, a stroke, the knife), since changing or freeing
data under one can crash Blender; calls behind it wait too, so the order holds. Some
add-ons keep a modal running all the time, so a call waits `MODAL_WAIT` (10 s) at most.
`inspect` and `ask` go at once.

**Edit Mode.** Before the turn-start snapshot and before each `exec`, a target in Edit
Mode (or another mode) leaves it (`snapshot.leave_edit_mode`): in Edit Mode the live
mesh is the edit mesh, so the snapshot and the code would read stale data, and what the
code wrote to `obj.data` would be lost on leaving. A mode on some other object, such as
the sketch being drawn on, is left alone.

### `exec` environment (`addon/execution.py`)

- One namespace dict per agent session, persisting across `exec` calls, pre-seeded with
  `bpy`, `bmesh`, `mathutils`, `math`, `Vector`, `Matrix`, and a `whittle` helper object:
  `whittle.targets()` (list of target objects), `whittle.view3d_override()` (context
  manager wrapping `bpy.context.temp_override(window=…, area=…, region=…)` for the first
  VIEW_3D area, for the operators that need one; raises `RuntimeError` when there is
  none, e.g. in background mode), `whittle.mesh_report(obj, evaluated=True)` and
  `whittle.weld(obj, dist=1e-4)` (both in `addon/meshcheck.py`).
- `mesh_report` measures the evaluated mesh in world space and returns a dict: `verts`,
  `faces`, `tris`, `quads`, `ngons`, `shells`, `open_edges`, `bad_verts`,
  `flipped_edges`, `duplicate_verts`, `tiny_faces`, `self_intersections` (BVH
  self-overlap, ignoring face pairs that share a vertex), signed `volume` and
  `watertight` (closed, consistently wound, positive volume). `watertight` is true for
  shells buried inside each other; `shells` and `self_intersections` show those. It
  raises `TypeError` for objects without mesh geometry. `weld` merges near-duplicate
  vertices, dissolves degenerate geometry, deletes loose vertices and recalculates
  normals on the object's own mesh, returning `{"removed_verts": n}`.
- `contextlib.redirect_stdout` into a `StringIO`; stdout is truncated to 20 000 chars.
- `compile(code, "<whittle exec N>", "exec")` (N counts the session's runs, and each
  run's source stays in `linecache`, so a traceback through a helper an earlier run
  defined shows that run's lines) then `exec`. Every exception, `SystemExit` and
  `KeyboardInterrupt` included, is caught and returned in `data.error` with
  `traceback.format_exc()` trimmed to frames from `<whittle exec …>`.
- There is no execution timeout: Python on the main thread cannot be pre-empted. The
  `exec` tool description says so, and the system prompt's turn shape asks for small
  steps for that reason.
- Undo: at the turn's start `Whittle: before <node>` (not while a modal operator runs),
  so Ctrl+Z during the turn goes back to the turn's start rather than past the user's
  last change; after `turn_finished`, `Whittle: <node> <label>`. Both only when a window
  exists. Ctrl+Z during a turn tells the agent with `UNDO_NOTE` on its next result.

### Render (`addon/render.py`)

All renders use **Workbench** (`scene.render.engine = "BLENDER_WORKBENCH"`), inside a
`render_settings()` context manager that snapshots and restores every setting it
touches (engine, resolution x/y/percentage, film_transparent, filepath, image format and
colour mode, `scene.camera`, `scene.display.shading.light/color_type/studio_light`,
`scene.view_settings.view_transform`, per-object `hide_render`). The user's scene is
never left changed.

- Resolution: `size` on the long side, the view's aspect kept (square for a `camera`
  param). `view_transform = "Standard"` so stroke colours stay flat. Renders are made with
  `film_transparent = True`, then every agent-facing PNG is flattened over a mid-grey
  backdrop (`render.BACKGROUND`), because a transparent background hides white strokes
  and pale materials. `strokes.png` stays transparent.
- Camera: a temporary object `"Whittle Render Camera"` with fresh camera data, built
  from `camera.json` (§8) or from the `camera` param, set as `scene.camera`, and removed
  (object and data) afterwards.
- Modes:
  - `shaded`: `shading.light = "STUDIO"`, `color_type = "MATERIAL"`.
  - `matcap`: `shading.light = "MATCAP"`.
  - `wireframe`: Workbench render ignores `display_type = "WIRE"`, so a temporary
    `WIREFRAME` modifier named `_whittle_wire` (thickness = 0.5 % of the target bounds
    diagonal) is added to each target mesh object, rendered shaded, and removed.
  - `overlay`: two renders — base (sketch object `hide_render = True`) and strokes-only
    (everything except the sketch object hidden) — then alpha-over in numpy
    (`out = s.rgb*s.a + base.rgb*(1-s.a)`), saved with `bpy.data.images.new(...,
    alpha=True)`, `pixels.foreach_set`, `filepath_raw`, `save()`. `strokes_path` is the
    strokes-only PNG.
- Render via `bpy.ops.render.render(write_still=True)` to a file, then
  `bpy.data.images.load` + `pixels.foreach_get` when numpy needs the pixels (the
  `Render Result` image has no readable pixels in background mode). Remove every image
  datablock loaded or created.
- Output: `<session>/nodes/<turn_id>/renders/<seq:03d>-v<view>-<mode>.png`
  (`-cam-` instead of `-v<view>-` for a `camera` render); overlay renders also write
  `<seq>-v<view>-overlay-strokes.png`. Pixels are read and written as Non-Color so the
  composite works on raw file values.
- Measured: ~0.43 s first render (shader compile), a few ms per 256 px render after
  that, so Workbench at 512 px is the path; `GPUOffScreen.draw_view3d` stays the
  documented fallback only.

---

## 5. Agent side

### Entry point (`agent/__main__.py`)

`python -m whittle.agent --port PORT [--fake SCRIPT]`: read `WHITTLE_TOKEN`, configure
`logging` to stderr (which is the log file), `asyncio.run(main())`. `main` opens the
`Connection`, sends `hello`, waits for `welcome` (10 s), then serves until `shutdown` or
EOF. Exit code 0 on both; 2 on handshake failure.

### `Connection` (`agent/connection.py`)

asyncio streams. `await call(method, params, timeout=300.0) -> dict` (raises
`BridgeCallError(code, message, detail)`), `send_event(name, data)`, and a dispatch
loop routing Blender's calls to the runner. `ask` uses `timeout=None` (it waits on a
person), and so do `exec` and `restore_checkpoint`: Blender cannot stop them once they
run, so a timeout would report as not done what may still complete.

### Runner (`agent/runner.py`, `agent/fake.py`)

```python
class Runner(Protocol):
    async def start_session(self, params: dict) -> None
    async def submit(self, turn_id: str, bundle_dir: str, prompt: str,
                     context: tuple[str, ...] = (), model: str | None = None) -> None
    async def amend(self, turn_id: str, text: str, bundle_dir: str | None) -> None
    async def interrupt(self, turn_id: str) -> None
    async def close(self) -> None
```

`SdkRunner(connection, client_factory=ClaudeSDKClient, list_models=None)` — the
factory is injectable so tests substitute a fake client; `list_models` reads the
Models API (`runner.list_api_models` in the real agent, §15, nothing in tests). Inside `start_session` it builds:

```python
ClaudeAgentOptions(
    system_prompt=prompt.build(settings),          # custom string, not the claude_code preset
    model=params["model"],
    tools=["Skill"],                               # every other built-in tool off
    allowed_tools=[*TOOL_NAMES],                   # the mcp__… names below
    permission_mode="dontAsk",                     # deny anything not pre-approved
    mcp_servers={"blender": blender_server, "whittle": whittle_server},
    strict_mcp_config=True,                        # ignore user/project MCP config
    setting_sources=[],                            # no user/project settings or CLAUDE.md
    plugins=[{"type": "local", "path": str(PLUGIN_DIR)}],
    skills=[f"whittle:{name}" for name in SKILLS],
    resume=params["resume"],
    fork_session=params["fork"],
    resume_session_at=params["resume_at"],         # --resume-session-at: cut the fork here
    cwd=params["session_dir"],
    env={"MCP_TOOL_TIMEOUT": "86400000",           # ask can wait on the user for a long time
         "CLAUDE_AGENT_SDK_CLIENT_APP": f"whittle/{VERSION}"},
    stderr=lambda line: log.debug("cli: %s", line),
)
```

`cli_path` is left unset: the SDK finds `claude_agent_sdk/_bundled/claude`. The API key,
when set, is already in the process environment, which the CLI inherits.

Because a `ClaudeSDKClient` must be used inside the task group it connected in, the
runner owns one long-lived **session task** per SDK client. That task connects, then runs
two children in one task group: a *reader* (`async for msg in client.receive_messages()`
→ events) and a *controller* that awaits an `asyncio.Queue` of commands
(`query`, `interrupt`, `stop`) and calls `client.query(...)` / `client.interrupt()` /
`client.disconnect()`. Public runner methods only enqueue commands. A submit whose
`model` differs from the session's (`SdkRunner.model`: `start_session`'s, then the
last switched to) queues its query with that model, and the controller calls
`client.set_model(model)` right before `client.query(...)`, in the same session: the
conversation carries on (§15). A failed switch fails the turn like a failed query.
`start_session` while a client is live stops the old task first.

**Turn accounting.** A Blender turn = one `submit` plus any amendments. The runner counts
queries sent and `ResultMessage`s received; `turn_finished` is emitted when they match
and no amendment is pending. `session_id` in `turn_finished` is the last
`ResultMessage.session_id`. `interrupted` = `terminal_reason in {"aborted_streaming",
"aborted_tools"}` or an interrupt was requested this turn. `num_turns` and
`duration_ms` are summed over the turn's results. `ResultMessage.total_cost_usd` is a
running total for the SDK session (checked live: a second turn's total included the
first's), so `cost_usd` is the last result's total less the total at the end of the
previous turn, and `session_cost_usd` is the total itself. The turn is cleared before
`turn_finished` is sent, so an amendment that arrives meanwhile gets `not_found`
instead of being lost. Each `ResultMessage` is also logged (`log` debug event) with
its total and turn count.

**Submit prompt.** The first user message of a turn is plain text:
the user's prompt, then a line `Request bundle: <bundle_dir>` and an instruction to call
`mcp__whittle__request` first. A request with no strokes and no views (a prompt-only
turn, valid like any other; `runner.sketch_size` reads the counts) gets a plain
statement that there is no sketch and no overlay images, and that the self-check
renders come from cameras the agent places; the request tool's summary repeats it
("Sketch: none"), and the system prompt's turn shape covers that case. The model sees the images via that tool. When the
submit carries `context` lines, they come first as a `<whittle_context>` block
(one `- line` each); the system prompt says they come from Whittle, not the user.

**Message uuid.** During a turn the reader keeps the `uuid` of the last
`AssistantMessage` or `UserMessage` (the SDK parses both; the CLI fills them, checked
live) and reports it as `turn_finished.message_uuid`.

**Amend.** `amend` queues an `Amendment(number, text, bundle_dir)` on the
`ToolContext`. Every tool result (errors included) goes through
`ToolContext.deliver_notes`, which appends one text block per queued amendment — a
`<user_amendment>` block holding `User amendment <n>: <text or (new strokes only)>`,
plus a line `New strokes: call mcp__whittle__request with amend=<n> to see them.` when
it has a bundle — and emits
`amend_delivered via tool_result`. If the turn's last `ResultMessage` arrives with
amendments still queued (and no interrupt, no error), they go as one follow-up
`client.query()` (the notes, then that the user sent them after the last reply and to fold
them into the current turn), the
query count goes up, `amend_delivered via query` is emitted and the Blender turn
continues. An interrupt, the session ending or a crash leaves them in
`turn_finished.amends_undelivered`. This is deterministic and testable with the fake
client, unlike injecting a user message mid-stream. Checked live: an amendment sent
right after `turn_started` rode on the first exec result and the model acted on it.

**Message → event mapping** (reader):

| SDK message | event(s) |
|---|---|
| `SystemMessage` subtype `init` | `status running`; remember `data["session_id"]` |
| `AssistantMessage` with `TextBlock` / `ThinkingBlock` / `ToolUseBlock` | `text` / `thinking` / `tool_use` (tool name stripped of `mcp__<server>__`) |
| `UserMessage` with `ToolResultBlock` | `tool_result` (image paths come from the tool handler's record, keyed by `tool_use_id` order) |
| `ResultMessage` | turn accounting; maybe `turn_finished` |
| anything else (`StreamEvent`, rate limit, task messages) | `log` at debug |

### MCP tools (`agent/tools.py`)

Two in-process servers built with `create_sdk_mcp_server` + `@tool`. Handlers are
module-level async functions taking `(ctx, args)` so tests can call them without the
SDK; `build_servers(ctx)` wraps them with `@tool` and binds `ctx` (connection, current
turn, pending notes).

| full name | server / tool | input schema | behaviour |
|---|---|---|---|
| `mcp__blender__exec` | blender / `exec` | `{code: str, label: str}` | bridge `exec`; text = stdout, error, diff, notes |
| `mcp__blender__inspect` | blender / `inspect` | `{query: str, name?: str}` | bridge `inspect`; JSON text |
| `mcp__blender__render` | blender / `render` | `{mode: str, view?: int, camera?: object, size?: int}` | bridge `render`; reads the PNG(s) and returns `{"type": "image", "data": <base64>, "mimeType": "image/png"}` blocks plus a text caption |
| `mcp__blender__checkpoint` | blender / `checkpoint` | `{label: str}` | bridge `checkpoint` |
| `mcp__blender__restore_checkpoint` | blender / `restore_checkpoint` | `{checkpoint_id: str}` | bridge `restore_checkpoint` |
| `mcp__whittle__request` | whittle / `request` | `{amend?: int}` | reads the bundle **from disk** (no bridge call): request.json + strokes.json as text, each view's `overlay.png` as an image |
| `mcp__whittle__ask` | whittle / `ask` | `{question: str, choices?: [str]}` | bridge `ask` with no timeout; emits `status waiting_user` |

Input schemas are full JSON Schema dicts (`{"type": "object", "properties": …,
"required": …}`) so optional fields are really optional, and every parameter has a
description (units, world space, what to leave out). Each tool description is a short
man page: what it does, when it fits, what it returns (`prompting.md`). Errors the model
reads say what to change: an unknown object name lists close matches and the targets, a
render without exactly one of `view` or `camera` lists the turn's view ids, and an
`amend` number with no strokes lists the amendments that have them. Image-returning tools use
`ToolAnnotations(maxResultSizeChars=4_000_000)` so results stay inline. A
`BridgeCallError` becomes `{"content": [text], "is_error": True}`.

### Fake agent (`agent/fake.py`)

`FakeRunner` implements `Runner` from a JSON script, imports nothing outside the stdlib
and the package, and runs under Blender's Python or the venv. Script format:

```json
{
  "turns": [
    {"steps": [
      {"say": "Blocking out the crate."},
      {"call": "exec", "params": {"code": "import bpy; bpy.ops.mesh.primitive_cube_add()", "label": "cube"}},
      {"call": "render", "params": {"view": 1, "mode": "overlay"}, "expect": "ok"},
      {"ask": "Bevel the edges?"},
      {"sleep": 0.1},
      {"end_session": "the CLI went away"},
      {"fail": "internal"}
    ],
    "finish": {"subtype": "success", "is_error": false}}
  ]
}
```

Each `submit` plays the next turn: `say` → `text` event; `call` → a real bridge call
followed by `tool_use`/`tool_result` events (with `expect: "error:<code>"` checked and a
mismatch reported as an `error` event); `ask` → bridge `ask`; `end_session` → forget the session and send `status
session_ended`, so the next submit answers `no_session`; `fail` → exit the process
with code 3 (crash tests); `finish` → `turn_finished` with a fake `session_id`
`"fake-<hex8>"` (new for a fresh session or a fork, kept for a plain resume) and a
`message_uuid` `"fake-msg-<hex8>"`. A top-level `"resume_fails": true` refuses every
`start_session` that has a `resume` with `internal`; a turn with `"refuse": "<code>"`
answers its submit with that error. `start_session` echoes `resume`/`fork`/`resume_at`
(and `store_dir`, §14) in its status detail and a `log` event, plus `session model: <id>`, and `submit` logs each `context` line as
`context: <line>`, and `model: <id>` when its `model` differs from the session's (the
switch), which the Blender tests read. A top-level `"models": {"models": [ids],
"source": …}` is sent as the `models` event when the process's first session starts. `interrupt` stops after the current step and finishes with
`interrupted: true`; `sleep` and `wait_amend` are cut short by it. Amendments ride on
the next `call`/`ask` result as `note: …` summary lines; any left when the steps run
out are delivered "by query" and the turn's `after_amend` steps play (default: one
`say` of the amendment text). `{"wait_amend": s}` waits for an amendment (an error
on timeout); `{"read_amend": n}` reads `<node>/amend-<n>` and says
`"amend n: k strokes, views [...]"`. `{"if_views": [...], "else": [...]}` plays the
first list when the request has sketch views and the second (default empty) when it
has none, and a call's `"view": "first"` becomes the request's lowest view id, so a
script that checks its work against the sketch also runs cleanly on a prompt-only
request. This exercises the real process, socket, handshake and Blender
handlers end to end at no cost.

---

## 6. History, sessions and branching

`whittle/tree.py` (stdlib: the tree, `session.json`, the branching rule),
`addon/history.py` (snapshots, restore, branch), `addon/compare.py` (compare and
ghost) and `addon/snapshot.py`, on top of `formats.SessionDir`.

- **Target identity**: every target object gets the custom property
  `whittle_uid` (`uuid4().hex`). Names can change; uids cannot.
- **Snapshot** (`snapshot.write(path, objects)`):
  `bpy.data.libraries.write(path, set(objects), path_remap="ABSOLUTE", fake_user=False,
  compress=True)` — indirect datablocks (meshes, materials, node groups, images) are
  expanded automatically. Beside it, the manifest `<name>.json` (§8). Only the target
  datablocks go in, never the whole file.
- **Restore** (`snapshot.restore(snap, remove=names, remove_uids=uids)`):
  1. Leave Edit Mode (or another mode) only when the active object is one being
     replaced or removed, so a sketch being drawn on stays in draw mode.
  2. Append the manifest's objects (`libraries.load(link=False)`, `dst.objects = names`;
     `dst.objects` keeps the requested order).
  3. Pair each appended datablock with the one it replaces. An object replaces the
     scene object with its manifest `uid`, whatever that is called now (of several
     with one uid, the namesake first, then one not being removed; none twice). Its
     data replaces that object's data, so linked duplicates follow; with no such
     object, only an unused block of the recorded data name is taken over. Slot
     materials (by slot order) and GN groups (by modifier order, nested groups by
     name) replace whatever has the recorded name now. Each replaced block
     `user_remap`s to the appended one and is removed, and the appended one takes
     the recorded name: an object with `ID.rename(mode="ALWAYS")`, so an unrelated
     object that took the name since (a user's) moves aside to a `.NNN` name instead
     of going; data that clashes keeps its suffix. `user_remap` carries collection
     membership, parenting and modifier, constraint and material references, so a
     shared material reverts for every user. A target that is gone is linked to its
     recorded collections (fallback: the scene collection).
  4. Anything else the append brought in (a boolean cutter, a modifier's collection,
     an action, a parent outside the target), in every `bpy.data` ID collection
     (`snapshot.id_collections()`, all but libraries, screens, window managers and
     workspaces; shape keys stay with their owner), is matched by name against the
     file's own name lists (`src.<type>`, stripping a `.NNN` clash suffix); when the
     file still has that datablock, the appended copy `user_remap`s to it and is
     removed.
  5. Remove the `remove` / `remove_uids` objects that are not replaced, and their data
     if unused; then appended datablocks nothing uses; then the `Library` the append
     added. Never a global purge.
- **Turn-start snapshot**: every submit writes `checkpoints/start.blend` + `start.json`
  of the bundle's targets. **Interrupt → Restore** restores it when `turn_finished`
  arrives; objects the agent created (named in `exec` diffs, with a `session_uid` that
  was not there at turn start) are removed. A restored turn keeps its strokes.

### The tree

- **Node 0** is written the first time a session folder runs a turn: a snapshot and
  thumbnail of the run's targets (an empty target writes an empty, valid file),
  status `complete`, label "Start".
- **Each turn** adds a node at submit (`History.begin`, status `running`, parent =
  `history.current`, which is also `request.parent`). When the turn ends,
  `History.finish` writes `target.blend` + `target.json` of the turn's targets plus the
  objects it created that still exist, a 128 px square `thumb.png` (Workbench shaded,
  only those objects, `render.frame_camera`: seen from the side of the bundle's first
  view, else from three-quarters, at the distance that just fits every corner of their
  world bounds with a 10 % margin; the view's own camera is not used, since the user may
  have sketched from far away or close up), and records the status, `agent_session_id`,
  `agent_message_uuid`, cost fields, `created_uids`, `kept_partial` and `restored`.
  An object the agent made that carries another object's `whittle_uid` (a copy keeps
  its original's custom properties) gets a fresh one first, so uids stay unique.
  `begin` records `continued_session`: the SDK session the turn carries on (the live
  client's, or the one a plain resume reopened; none for a fork or a fresh session).
  The node becomes current and `scene.whittle.history_node` mirrors it. Then one undo
  step, `Whittle: <node> <label>`. A snapshot that fails leaves `snapshot: false`
  (the node cannot be restored) without failing the turn.
- **Outcomes**: complete; `interrupted` with `kept_partial` (Interrupt → Keep) or
  `restored` (Interrupt → Restore: the snapshot is the turn start, the node is
  current, the live session carries on, and the next submit's context says the turn
  was interrupted and the target put back); `failed` for a crash or a session end (the
  snapshot is what the turn left, the session id may be null). A submit the agent
  refuses (and that is not retried after `no_session`) is discarded from the tree, and
  its node folder goes too (its strokes are pending again and its number is free), as
  for a submit that fails before it is sent (a write error, say): the controller is
  never left running a turn the agent did not get. A tree read back with a `running` node (Blender died mid-turn) marks it `failed`, and
  saves that.
- **Folded failures**: a turn that ends failed (not interrupted) without changing
  anything — no `exec` or `restore_checkpoint` call, failed ones included
  (`CommandContext.edits`), and no object it made — folds into its parent
  (`History.fold`). The node stays in `session.json` with `status: failed`,
  `folded: true`, its session fields and costs, but no snapshot or thumbnail; its
  folder keeps the request and transcript, and its number is never reused. The parent
  stays current, no undo step is pushed and the stream says the turn was not kept.
  Folded nodes are invisible to everything that shows or navigates the tree:
  `Tree.walk()` skips them (`walk(folded=True)` includes them),
  `Tree.visible_children`/`is_leaf` ignore them (so "Next submit branches" and the Start
  panel do not count them), and Restore, Branch and Compare refuse them. They still
  count for `latest_in_session`: the conversation went past the parent with the failed
  exchange, so the next submit from the parent forks at the parent's message
  (`live_node` is cleared) and the agent never sees the failure. `session.json`
  validation refuses a folded node that is current, not `failed`, or has children; an
  older file without the key reads as not folded. Why fold rather than delete: the
  node's SDK session must keep counting, or a later plan would resume a conversation
  that went past the scene; and its folder must stay so node ids remain unique.
- **Restore** (`History.restore(node)`): removes the objects that any node lists in
  `created_uids` and the restored node's manifest lacks, appends the node's objects,
  sets the target list to them, makes the node current and pushes one undo step.
  Objects the user added (even if later made targets) are never deleted; a node that
  contains them reverts them. A user copy of an agent object shares its uid, so first
  `History.separate_copies` keeps each shared created uid on the one object a node
  manifest recorded by name (then: the one in the target list) and re-stamps the
  others; a uid whose original is ambiguous is left out of the removal.
- **Branch** (the button) means "another take on this turn": it restores the node's
  parent and puts the node's prompt in the prompt box, its request strokes back on the
  sketch as pending ones (`sketch.add_strokes`, views merged by `views.merge_views`) and
  its references back in the list (`refs.add_back`), so the next Submit makes a
  sibling. Disabled on node 0. Restore + Submit from any non-leaf branches as well.
- **Compare** (`compare.start(history, node)`): writes `compare/live.blend` of the
  current targets, the objects any node created and those of the current and compared
  nodes, plus, as `loose`, the materials and node groups of those two nodes' names (the
  node's restore replaces them by name, and an object outside the snapshot may be all
  that uses one now), then shows the other node. If showing it fails, live comes back
  and the comparison never starts; if that fails too, the comparison stays so Swap or
  Done can try again. Toggle restores one side or the other. Showing the
  node removes what live has and the node lacks only when the agent made it (as a
  Restore), so the user's objects stay; going back to live removes everything the node
  brought in that live lacks (live.blend holds every object carrying one of the node's
  uids, so those were all appended). Coming back to live also puts back the target list
  as it was at the start, by `whittle_uid` (then name): showing the node may have
  removed a target, and the copy appended on the way back is a new object. Nothing is an undo step. End restores the live side (one undo step); Keep
  restores the other node as a Restore. `live.blend` goes only once that worked: a
  failed End or Keep leaves the comparison running with it. Submit, Restore, Branch and Compare wait for
  the comparison to end. Saving during a comparison saves what is shown.
- **Ghost** (`compare.show_ghost(history, node)`): the current node's parent appended
  from its `target.blend`, every appended datablock renamed `Ghost · <name>`, the
  objects linked into the "Whittle Ghost" collection with `display_type = "WIRE"`,
  `hide_select`, `hide_render`, `show_in_front`, no `whittle_uid` and `whittle_ghost =
  <node>`; `targets.eligible` refuses them. `clear_ghost()` removes the marked objects,
  then unused `Ghost · ` datablocks, the collection and any `target.blend` Library,
  from names and markers alone, so it also cleans a saved file. It runs at submit, on
  file load (`load_post`) and from the toggle.
- **Undo**: `scene.whittle.history_node` is saved in Blender's undo steps; an
  `undo_post`/`redo_post` handler (`history.sync_from_scene`) copies it back into
  `session.json`'s `current`. An empty mirror (a scene from before the first turn)
  means the root; a node the tree lacks changes nothing and logs a warning.
- **File load**: restores write `session.json` at once, but the mirror reaches disk only
  when the `.blend` is saved, so after `load_post` clears the cache it runs
  `sync_from_scene` too: the reopened scene decides the current node, and with it the
  next submit's parent and session plan.
- **Which History**: `history.get(root)` caches one per session folder;
  `history.active()` is the running controller's, else the current chat's
  `session.json` if there is one. `load_post` forgets the cache and any
  comparison.
  With chats (§14), the session folder is the current chat's `chats/<id>/` and
  `active` reads the current chat's.

### Sessions and branching

`tree.session_plan(tree, node, live)` decides, before each submit, how the agent's
conversation is made to match the node the scene reflects. `live` is the node the
running SDK client last finished on (`TurnController.live_node`, runtime only; cleared
on `session_ended`, a crash or a turn without a session id).

1. `live == node`: no restart, submit into the live client.
2. Find the nearest node on the path from `node` up to the root (itself first) with an
   `agent_session_id` (the anchor). None: a fresh session, with a "context lost" note
   unless `node` is the root.
3. The anchor is not `node` (a failed turn without a session): a note that the turns
   after the anchor are not in the conversation and that the target reflects `node`.
4. The anchor is `node` and is the newest node of its SDK session, counting nodes whose
   `continued_session` is it (a turn that never finished still moved the
   conversation on): a plain resume
   (`resume=S, fork=False`); this is the Blender-restart case.
5. Otherwise a fork at the anchor's last message: `resume=S, fork=True,
   resume_at=<agent_message_uuid>`, with the note "You are continuing from history
   node X (label). Changes made on other branches after it do not exist in the scene."
   Plain `resume + fork_session` is not enough: when the session went on past the node
   (n1 → n2 in one session), branching from n1 would carry n2's turn. A fork without
   a uuid forks the whole session and logs a warning.

The plan's notes and any pending context (the interrupt-restore note) go in the
submit's `context`, cleared once a submit is accepted. Every `start_session` sent is
recorded in `TurnController.session_starts`. **A failed resume** (the CLI cannot find
the session, e.g. the `.blend` moved and with it the session folder the CLI keys its
sessions by; or a resumed session that ends before its first turn) falls back once to
a fresh session with the note "The earlier conversation could not be resumed
(<message>); inspect the target before editing."; a second failure drops the run.

**Session resume after a Blender restart**: a new controller reads `session.json`
(`history.get(root, reload=True)`), so the first submit resumes the current node's
session, or forks it when the node is not the newest of its session.

### Checkpoints

`blender.checkpoint` snapshots the turn's targets plus the objects it created that
still exist to `nodes/<turn>/checkpoints/c<k>.blend` (`k` restarts each turn) and
remembers the `session_uid`s present then. `restore_checkpoint` restores it and
removes the objects named in this turn's `exec` diffs whose `session_uid` came after
the checkpoint. The appended copies have new `session_uid`s, so the controller's
`on_restored` hook carries "existed before the turn" over to them by their
`whittle_uid`; a later Interrupt → Restore still restores the turn start.
Python variables in the exec namespace that held replaced objects are stale, which
the tool's result says.


---

## 7. Sketching and views

Modules: `addon/sketch.py` (object, layers, tags, the sketch session), `addon/views.py`
(capture, comparison, storage), `addon/bundle.py` (the request-bundle writer).

- **Sketch object**: one GP object `"Whittle Sketch"` (`bpy.data.grease_pencils.new`,
  object type `GREASEPENCIL`). Strokes are read through `object.matrix_world @
  layer.matrix_local`, so a moved object or layer still gives world coordinates.
- **Layers**: `free`, `add`, `carve`, `crease`, `region`, `note`, created in that order
  with `layers.new(name, set_active=False)` and a frame at the scene's current frame
  (`ensure_sketch_layers`; `free` becomes active when no type layer is). Colour comes
  from `layer.tint_color` with `tint_factor = 1.0` over one shared white stroke material
  `"Whittle Stroke"` (`bpy.data.materials.create_gpencil_data`). Layers set
  `use_lights = False`: lit strokes render at about a quarter of their tint in Workbench
  (pure green read back as 0.25). The type buttons (`whittle.stroke_type`,
  `whittle.next_stroke_type`) set `grease_pencil.layers.active`. Hidden layers are left
  out of the bundle (and out of the renders, which honour `layer.hide`).
- **Region fill**: in Blender 5.2 a stroke is filled when its curve attribute `fill_id`
  is non-zero; strokes sharing an id are filled together. The material's `show_fill`
  is ignored by the renderer (and deprecated). Each region stroke gets its own id
  (`ensure_region_fills`, run by the watcher, `load_strokes` and before a bundle is
  written), and the shared material's `fill_color` alpha is 0.35, so regions render as
  translucent tinted areas. Other layers keep `fill_id = 0`, so they stay outlines.
- **Placement**: `whittle.sketch` (`SketchSession.enter`) makes the sketch active and
  selected, enters `PAINT_GREASE_PENCIL`, and sets
  `tool_settings.gpencil_stroke_placement_view3d = "SURFACE"` and
  `gpencil_surface_offset = 0.0`; `whittle.sketch_stop` restores the user's values, object
  mode and the previously active object. `load_pre`, `exit_pre` and `unregister` end the
  session too.
- **View capture** (`views.py`): a view is derived from `RegionView3D.view_matrix` /
  `window_matrix` and the region size only (never `SpaceView3D.lens`, see the appendix).
  `camera_spec` recovers the clip range from the projection
  (persp: `n = P23/(P22-1)`, `f = P23/(P22+1)`; ortho: `n = (P23+1)/P22`,
  `f = (P23-1)/P22`). An orthographic viewport's near plane is negative (it shows
  geometry behind its pivot), so the camera eye moves back along its view axis by
  `0.01 - near` and the clip range shifts with it; the parallel projection is unchanged.
  In camera view (`view_perspective == "CAMERA"`) the view is the scene camera's, sized
  by the render resolution × percentage so the overlay matches the camera frame:
  `view_matrix = camera.matrix_world.normalized().inverted()`, `window_matrix =
  calc_matrix_camera(depsgraph, x, y)`. Camera lens shift is not represented.
  `RegionView3D.update()` is never called (it segfaults in background mode); the
  matrices are only read.
- **New-view rule** (`substantially_different`): a new view is captured when the
  viewing direction turned by more than 15°, the view pivot (eye + view_distance along
  the line of sight, at the viewport's current `view_distance`) moved by more than 10 %
  of the view distance, the projection type changed, or the field of view (angle, or
  ortho scale) changed by more than 15 %. Measuring at the pivot means an orbit counts
  only through its angle (the eye of a 10° orbit at 2 m moves 0.35 m), while pans and
  dollies count as movement.
- **View storage**: views live on the GreasePencil datablock as ID properties:
  `whittle_views` (a JSON list of camera.json objects) and `whittle_next_view` (the id
  counter). They are saved with the file. Ids start at 1 and are never reused; 0 means
  untagged. The current view is always the latest one.
- **View tagging**: curve-domain INT attribute `whittle_view` on each drawing. While a
  sketch session is active, a 0.25 s timer (`SketchSession.poll`) looks for strokes
  with view 0; when there are some it builds a candidate view from the active viewport,
  stores it if it is substantially different from the current view (or there is none),
  and tags the untagged strokes with the current view. Tagging keys on `view == 0`, never
  on stroke counts or order, so draw-on-back insertion and erasing are harmless.
  **Capture View** (`whittle.capture_view`) first tags pending strokes with the old
  view, then stores a new one from the operator's own viewport; it works without a
  sketch session. Untagged strokes at submit get the latest view; with no view at all
  the submit fails and asks for one.
- **Active viewport**: a timer has no context, so the watcher picks the 3D viewport
  region whose view matrix changed most recently across polls, or the largest one when
  none has changed. With one viewport this is exact; with several, a stroke drawn in a
  still viewport just after orbiting another can be tagged with the wrong view.
- **Pressure**: GP v3 has no pressure attribute; pressure lands in point `radius` and
  `opacity`, which the bundle records. `radius`, `opacity` and `cyclic` exist as
  attributes only once something writes them; until then every point reads the
  defaults (radius 0.01, opacity 1.0, not cyclic).
- **On-surface flag + normal**: computed at bundle time with `scene.ray_cast`, which
  does not hit Grease Pencil objects, so the sketch never occludes itself. Perspective:
  from the eye towards the point. Orthographic: along the view axis from the render
  camera's eye plane (which lies in front of everything visible). A point is on a
  surface when it lies within 1 mm + 1 % of its depth of the first hit, measured along
  the hit's normal, and within ten times that along the ray; the normal (world space,
  4 dp) and object name are recorded only then. Measured across the surface because
  the real draw tool puts points short of an oblique surface along the line of sight
  (exact head-on; about 1 cm above the crate-sized cube's top, 5 cm along the ray, at
  2.5 m and an 11° grazing angle, growing with distance; `tests/gui`'s
  `blank_sketch`): along the ray alone, strokes drawn on a surface seen at a slant
  were sent as off it.
- **Submitted vs pending strokes**: curve-domain INT attribute `whittle_turn`, 0 for
  pending. `TurnController.run_sketch` writes the bundle, then stamps every visible
  stroke with the node number. Strokes drawn during the turn stay 0. When a sketch turn
  finishes without error or interrupt, the strokes stamped with its node are removed
  (`drawing.remove_strokes(indices=…)`) and views no remaining stroke uses are pruned
  (the latest is kept). A failed or interrupted turn leaves its strokes; the next run
  sends them again and re-stamps them.
- **Targets** (`addon/targets.py`): `scene.whittle.targets` (a list of object
  pointers) plus an optional `scene.whittle.target_collection`, resolved at submit to
  unique objects in the scene, never the sketch, cameras, lights, probes or speakers.
  The selection no longer decides anything; **From Selection** fills the list. An
  empty target means "make new objects". Objects the agent created during a turn (from
  the exec diffs) are added to the list when the turn completes or is kept partial.
- **Amendment strokes**: curve INT attribute `whittle_amend` (0 = the turn's own
  request or pending). An amendment with pending strokes writes
  `nodes/<id>/amend-<n>/` from the strokes with turn 0 (`write_bundle(amend=n,
  stroke_filter=…)`, overlays rendered with only those strokes), then stamps them
  `(turn, n)` with `stamp_pending`. They share the turn's stamp, so a finished turn
  removes them too. An amendment the agent never received is handed back with
  `unstamp_amend` before the turn's strokes are cleared. `stamp_strokes` resets the
  amend stamp, so a failed turn's strokes go out again as the next turn's own.
- **Pending strokes in turn renders**: the agent's overlay renders draw only the
  running turn's strokes (amendments included). `isolate_strokes(obj, keep)` sets the
  built-in `hide_stroke = True` and `fill_id = 0` on the others for the strokes-only
  pass, and puts both attributes back as they were (removing them when they were
  absent). Bundles from disk (Run Bundle) are not stamped, so nothing is hidden there.
- **No target lock.** Whittle used to watch the target with a depsgraph handler during a
  turn and warn the user and the agent about user edits. It fired far too often and is
  gone (decisions.md): user edits during a turn are neither watched nor reported.

---

## 8. On-disk formats

All JSON is UTF-8, written atomically (temp file + `os.replace`), with `"format"` and
`"version"` keys. Matrices are 4×4 row-major lists of floats. Paths inside JSON are
relative to the file's own folder. `formats.py` defines dataclasses plus
`to_json()/from_json()` and a `validate()` that checks required keys and types (no
jsonschema dependency on the Blender side).

### Session folder

With chats (§14) this is one chat's folder, `<user dir>/cache/<file id>/chats/<chat
id>/`, and the `.blend` stores it.

```
<session folder>/
  session.json
  compare/live.blend      the scene as it was while a comparison runs (removed at the end)
  nodes/<node id>/
    target.blend          snapshot of the target after this node
    target.json           manifest for restore
    thumb.png
    transcript.jsonl      one bridge event per line, as received
    request/              the request bundle that produced this node (none for node 0)
    amend-<n>/            amend bundles (same layout as request/, minus prompt)
    renders/
    checkpoints/start.blend, c<k>.blend + their .json manifests
```

Pinned references are not copied into the session folder: they stay in
`scene.whittle.refs` with `pinned` set (saved with the `.blend`), and each request copies
them into its own `request/refs/` like any other reference (§13).

Node ids: `n0000`, `n0001`, … (zero-padded counter, never reused once a node folder
exists; a sketch run dropped before reaching the agent leaves no folder, and its number
and stroke stamps are freed for the next run).

**session.json** (`tree.write_session` / `tree.read_session`, validated by
`tree.validate_session`, which names the file and key on a bad value; a node id that
is not `n` and four or more digits is refused, since ids name folders)

| field | type | meaning |
|---|---|---|
| `format` | `"whittle.session"` | |
| `version` | `1` | |
| `created` | ISO 8601 str | |
| `root` | str | `"n0000"` |
| `current` | str | node the scene currently reflects |
| `nodes` | {id: Node} | the tree |

Node ids come from the node folders on disk (never reused), so there is no counter in
the file; the live client's node is runtime state on the controller. Settings, pinned
references and pending views are not stored here.

**Node**

| field | type | meaning |
|---|---|---|
| `id`, `parent` | str, str \| null | |
| `children` | [str] | in creation order; each names this node as parent |
| `created` | ISO str | |
| `status` | `"running"`, `"complete"`, `"interrupted"`, `"failed"` | |
| `label` | str | first line of the prompt (60 chars), "(sketch only)", or "Start" |
| `prompt` | str | |
| `agent_session_id` | str \| null | SDK session id at completion |
| `agent_message_uuid` | str \| null | last transcript message of the turn: where a branch forks |
| `continued_session` | str \| null | SDK session the turn carried on, set at submit; optional when reading |
| `cost_usd`, `num_turns`, `duration_ms` | number \| null | from `turn_finished` |
| `kept_partial` | bool | interrupted turn whose partial edit was kept |
| `restored` | bool | interrupted turn whose target was put back as before it |
| `snapshot` | bool | `target.blend` was written (Restore needs it) |
| `created_uids` | [str] | `whittle_uid` of each object the agent made in this turn |
| `folded` | bool | failed turn that changed nothing, folded into its parent (§6); optional when reading |


**target.json** (also `checkpoints/<k>.json`): `{"format": "whittle.target", "version":
1, "objects": [{"uid", "name", "type", "data_name": str | null, "collections": [str]
("" = the scene's master collection), "parent": str | null, "parent_uid": str | null,
"materials": [str | null] (slot order), "node_groups": [str] (GN modifier order)}],
"datablocks": {"materials": [str], "node_groups": [str] (nested groups included),
"images": [str]}, "loose": {"materials": [str], "node_groups": [str]}}` (`loose` is
optional: materials and node groups written for their own sake, which no object in the
snapshot uses; a restore replaces the ones of those names the file has).
`formats.validate_target`, `write_target_manifest`, `read_target_manifest`.

**Amend bundles**: `nodes/<id>/amend-<n>/`, the request-bundle layout with
`request.amend = n`, `prompt` = the amendment text and only the amendment's strokes
(and the views they use). A text-only amendment writes none (`bundle_dir: null`).

**transcript.jsonl** holds the agent's events as received, plus Blender-side records
`{"v": 1, "type": "local", "name": …, "data": …}`: `submit` (node, prompt, bundle_dir,
targets, parent, context — the first line of each node), `amend` (amend, text, bundle_dir, strokes),
`amend_returned` (amend, reason), `answer` (question, answer), `interrupt` (mode
`keep` | `restore`), `restored` (objects) and `target_edited` (edits: [{name, kind}]).

### Request bundle

`nodes/<id>/request/` (design §3, moved under the node):

```
request.json
strokes.json
views/<view id>/camera.json
views/<view id>/overlay.png     shaded render from the view with strokes composited
views/<view id>/strokes.png     strokes only, transparent
refs/<name>.<ext>               copies of attached reference images
```

Written by `bundle.write_bundle` into a hidden sibling folder, validated with
`formats.read_bundle`, then renamed into place, so the folder is either a whole bundle or
absent. The writer only reads the sketch (it never tags strokes); the one change it
makes is giving target objects a `whittle_uid`. `views` holds the views the strokes use,
or just the latest view when there are no strokes (a prompt-only request), or none at
all with no views (no `views/` folder then). Strokes come in type order, then stroke
order, with untagged strokes on the latest view. Positions are rounded to 5 dp, radius to
5 and opacity to 3; `scale_length` to 7 significant digits. Reference images are copied
under unique sanitised names. Three views and 2 000 points at 512 px take about 0.3 s
after the first render's shader compile.

**request.json**

| field | type |
|---|---|
| `format`, `version` | `"whittle.request"`, `1` |
| `node`, `parent` | str, str |
| `prompt` | str |
| `amend` | int \| null (amend bundles only) |
| `target` | `[{"uid", "name", "type"}]` |
| `stroke_types` | [str] — layer types present |
| `views` | [int] — view ids with a folder under `views/` |
| `refs` | [str] — relative paths inside the bundle (absolute paths and `..` are refused) |
| `units` | `{"system": str, "scale_length": float}` from `scene.unit_settings` |
| `settings` | `{self_check_rounds, poly_budget, style_notes}` |
| `target_collection` | str \| null, optional — the collection new objects go in (`scene.whittle.target_collection`); a missing key reads as null, so older bundles stay valid |

**strokes.json**: `{"format": "whittle.strokes", "version": 1, "strokes": [Stroke]}`

| Stroke field | type |
|---|---|
| `index` | int, order within the bundle |
| `type` | layer name |
| `view` | int |
| `cyclic` | bool |
| `points` | [[x, y, z]] world space, metres × scene scale |
| `radius` | [float] |
| `opacity` | [float] |
| `on_surface` | [bool] |
| `normal` | [[x, y, z] \| null] |
| `hit_object` | [str \| null] object name under each point |

**camera.json** (a View)

| field | type |
|---|---|
| `id` | int |
| `view_matrix`, `window_matrix` | 4×4 — `RegionView3D.view_matrix` / `window_matrix` |
| `is_perspective` | bool |
| `width`, `height` | int — region size in pixels (render size in camera view) |
| `from_camera` | str \| null — scene camera name when captured in camera view |
| `camera` | `{"matrix_world", "type": "PERSP" \| "ORTHO", "angle": float, "ortho_scale": float, "sensor_fit": "HORIZONTAL" \| "VERTICAL", "clip_start", "clip_end"}` |

`camera` is derived at capture so the renderer never re-derives it: `matrix_world =
view_matrix.inverted()`; with `P = window_matrix` and the long side horizontal,
`angle = 2·atan(1/P[0][0])` (vertical: `2·atan(1/P[1][1])`), `ortho_scale = 2/P[0][0]`
(vertical: `2/P[1][1]`); clip start/end recovered from `P` (§7), with the eye moved
back for an orthographic viewport's negative near plane. A render camera built from it
at `width × height` reproduces `P` to about 2e-7. In camera view the matrices are the
scene camera's, and `width`/`height` are its render resolution × percentage (§7).

---

## 9. Packaging and the agent venv

- `whittle/blender_manifest.toml`: `schema_version = "1.0.0"`, `id = "whittle"`,
  `version` (equal to `whittle.__version__`, checked by a test), `name = "Whittle"`,
  `tagline`, `maintainer`, `type = "add-on"`, `blender_version_min = "5.2.0"` (Grease
  Pencil v3, and the lock's wheels are for Python 3.14),
  `license = ["SPDX:GPL-3.0-or-later"]`, `platforms = ["linux-x64"]`, and
  ```toml
  [permissions]
  network = "Runs a Claude agent that calls the Anthropic API"
  files = "Chat caches in its user folder and a private venv"
  ```
  The validator caps each permission text at 64 characters, hence the short `files` text.
  plus `[build] paths_exclude_pattern = ["__pycache__/", "/.git/", "/*.zip"]`.
- Build: `./build.sh [OUT]` checks that `whittle/requirements.lock` is byte-identical to
  `agent_env/requirements.lock` (it never copies it: a difference is reported), runs
  `blender --command extension validate whittle`, then `extension build --source-dir whittle
  --output-dir OUT` (default `build/`, gitignored), giving `whittle-<version>.zip`.

### The venv (`whittle/venv.py`, `addon/setup.py`)

`venv.py` is stdlib only, so the agent-side tests cover it without bpy or pip.

- **Folder**: `setup.venv_dir()` = the `venv_dir` preference (made absolute), else
  `<user dir>/venv`, where `<user dir>` = `bpy.utils.extension_path_user(__package__,
  create=True)` when running as an extension
  (`~/.config/blender/5.2/extensions/.user/user_default/whittle/`, which survives
  reinstalling the extension); env `WHITTLE_USER_DIR` overrides (tests always set it).
  The lock is the packaged `whittle/requirements.lock` (`setup.lock_path()`).
- **Marker**: `<venv>/whittle-venv.json`, `{"format": "whittle.venv", "version": 1,
  "complete": bool, "lock_sha256", "sdk", "base_python", "written"}`, written atomically.
  A setup writes it with `complete: false` as soon as it owns the folder (a folder it
  created, or right after `venv` ran), and with `complete: true` only after the verify
  step passed. It never goes over the wire.
- **Status** (`venv.status(venv, lock)`): `missing` (no folder or an empty one),
  `foreign` (a folder without the marker: never touched), `broken` (marker incomplete, or
  `bin/python` not an executable file — a dangling symlink after the base Python went
  away), `stale` (complete, but `lock_sha256` differs from the shipped lock: an extension
  update), `ready`. Only `ready` counts for `paths.agent_python()`; a stale venv is never
  upgraded on its own, the user presses Reinstall.
- **Steps** (`venv.plan(base, venv, lock, reinstall=)`), each with its own timeout:
  1. `create` (120 s): `[sys.executable, "-I", "-m", "venv", ("--clear",) venv]`;
     `--clear` for a reinstall, and for a stale or broken venv (Whittle's own).
  2. `install` (900 s): `[venv python, "-I", "-m", "pip", "install", "--isolated",
     "--disable-pip-version-check", "--no-input", "--require-hashes", "--only-binary",
     ":all:", "--no-deps", "-r", lock]`.
  3. `verify` (60 s): `[venv python, "-I", "-c", …]` imports `claude_agent_sdk` and prints
     `whittle-verify:{"sdk": <installed version>, "cli": <_bundled/claude is a file>}`;
     the setup requires the lock's pinned version and `cli: true`.
- **Environment**: `venv.subprocess_env` drops every variable starting with `PIP_`,
  `PYTHON`, `UV_`, `VIRTUAL_ENV` or `CONDA_` (no index or path redirection), and keeps the
  rest (`PATH`, `HOME`, proxies, `SSL_CERT_*`). stdin is `/dev/null`; stdout and stderr
  go to `<user dir>/logs/venv-<time>.log`, never a pipe.
- **`VenvSetup`**: `start()` then `tick()` every 0.25 s from a `bpy.app.timers` timer
  (tests call `tick()` themselves; `popen` and `clock` are injectable). State `idle` →
  `running` → `done` | `failed` | `cancelled`. A step past its deadline gets
  `terminate()`, then `kill()` 2 s later → `failed` "timed out in <step>". A nonzero exit
  fails with the log's last lines and stops the later steps. `cancel(wait=)` terminates
  (and kills after `wait`). `dry_run` only logs `$ <command>` per step: no process, no
  folder, no marker. `on_finish` runs once at the end.
- **Guard** (`setup.begin`): refuses, with a message for the user, when a setup is
  already running, a turn is running or waiting (`TurnController.busy`), `venv.compatible()`
  objects (Python 3.14, Linux, x86_64 only — the lock is manylinux x86_64), Blender's Python
  has no `ensurepip`, the folder is `foreign`, the venv is `ready` and this is not a
  reinstall, there is no online access, or Blender runs in the background. The last two
  do not apply to a dry run. When a real setup finishes, a controller in `needs_setup`
  goes back to `stopped`, so the next submit finds the venv.
- **Operators**: `whittle.venv_install` (`reinstall`, hidden `dry_run`): `poll` is false
  during a turn and while a setup runs, so an agent `exec` cannot start one; `invoke` is
  `wm.invoke_confirm(title=…, message=setup.install_summary(), confirm_text="Download and
  Install", icon="WARNING")`. An operator's `poll` cannot see its properties, so the
  background refusal lives in `begin()`. `whittle.venv_cancel`. `unregister()` cancels a
  running setup (2 s wait, then kill) and stops its timer.

---

## 10. Tests

One command, from the repo root:

```sh
./run_tests.sh          # add -v for verbose
```

which runs

```sh
timeout 300 .venv/bin/python -m unittest discover -s tests/agent -t .
timeout 900 blender -b --factory-startup --python-exit-code 1 --python tests/blender/run.py
```

- stdlib `unittest` only (pytest is not installed). Agent tests import `whittle.*` from
  the repo root; Blender tests do the same via `tests/blender/run.py`, which puts the repo
  root on `sys.path`, discovers `tests/blender/test_*.py` and exits non-zero on failure.
- `bpy.app.timers` never fire in a `-b --python` run, so Blender tests drive
  `Bridge.tick()` themselves: `pump(bridge, until=lambda: …, timeout=10)` loops `tick()`
  + `time.sleep(0.01)`, failing on timeout. No test can hang: every wait has a deadline,
  and every subprocess is spawned with a timeout and killed in `tearDown`.
- Blender tests that need an agent spawn the **fake agent** (`--fake script.json`) with
  `WHITTLE_AGENT_PYTHON` defaulting to the repo's `.venv/bin/python`, so the real
  process, socket, handshake and handlers are exercised.
- Agent tests use:
  - a **fake Blender**: an in-process asyncio server speaking the protocol, scripted with
    canned results per method, recording the calls it received;
  - a **fake SDK client** passed as `client_factory` to `SdkRunner`: same method subset
    (`connect`, `query`, `receive_messages`, `interrupt`, `disconnect`), yielding real
    `claude_agent_sdk` message dataclasses from a script and invoking the tool handlers
    the options registered.
- **Live tests** (`tests/blender/test_live.py`) skip unless `WHITTLE_LIVE=1`; they use model
  `claude-haiku-5-5` and a tiny prompt against headless Blender with the real agent
  process. `run_tests.sh` adds `--online-mode` to the Blender command when
  `WHITTLE_LIVE=1`, since Blender refuses to start the real agent without online access. They check what cannot be checked offline: plugin
  skills load with `setting_sources=[]`, `dontAsk` + `allowed_tools` permits the MCP
  tools, `MCP_TOOL_TIMEOUT` is honoured, and `test_live_fork` checks that a branch
  forks at the node's message uuid (the fork's transcript has the first turn's prompt
  and not the second's).
- `tests/blender/run.py` takes unittest-style `-k PATTERN` (and `-v`) after `--`, so one
  test can run alone: `blender -b --factory-startup --python tests/blender/run.py -- -k test_live_fork`.
  Like unittest, it exits 5 when no test ran; `run_tests.sh` treats 5 on one side as
  "nothing matched there" and fails only when both sides ran nothing.
- Every shell command in development and CI is wrapped in `timeout`.

---

## 11. Implementation notes

Details settled while building the agent and bridge, beyond the sections above.

- **Agent dispatch**: `agent/dispatch.py` checks the parameters of Blender's calls
  (`bad_request` on a wrong type), fills defaults (`model` defaults to
  `claude-opus-5-5`, `fork` to false, `settings` to `{}`) and routes them to the runner.
  Both runners share it.
- **Tool result images**: the render and request tools put each image path on its own
  `image: <path>` caption line. The runner reads those lines from the `ToolResultBlock`
  text to fill `tool_result.images`, so no bookkeeping is needed to pair tool calls with
  handler runs.
- **Session log**: on the `init` system message the runner sends a `log` event (level
  `info`) with the session id, model, tools and skills, then a `warning` if no
  `whittle:` skill is listed.
- **Skills**: plugin skills are the default and do load with `setting_sources=[]`
  (checked live). `WHITTLE_INLINE_SKILLS=1` in the agent's environment switches to
  appending every `SKILL.md` body to the system prompt, with `tools=[]` and no plugin.
  Each recipe's Python blocks are run headlessly by `tests/blender/test_skills.py`, which
  also checks that grown horns come out as one clean shell and that a self-union repairs
  a buried-base join. `tests/blender/test_meshcheck.py` covers `mesh_report` and `weld`.
- **Fake agent steps**: besides the steps in §5, `{"gather": [call steps]}` issues calls
  concurrently, which is how tests fill the bridge queue.
- **Crash reason**: socket EOF usually arrives just before the process exits, so on EOF
  the bridge waits up to 1 s for the exit code and reports "the agent exited with code N".
- **Unsaved files**: without a saved `.blend` (and for every bundle run in tests),
  the cache root is `<user dir>/cache/<fresh file id>/` (made with the first chat,
  §14), the session folder is its current chat's, and the bundle is copied to
  `nodes/n0001/request/` before submit. Saving keeps the cache where it is. `sketch.load_strokes` puts the
  bundle's strokes on the Whittle Sketch object so overlay renders work without sketch
  capture.
- **Sketch runs**: `TurnController.run_sketch(prompt, targets=…, refs=…)` starts (or
  checks) the agent first and raises when it cannot, so nothing is written for a run
  that cannot happen. It then reserves the next node, writes the bundle straight into
  `nodes/<id>/request/`, stamps the sent strokes and queues the run; `submit` takes the
  reserved node and uses the bundle in place. The parent is the current history node
  (§6). A run dropped before it reached the
  agent removes its node folder; its strokes stay for the next run. The `no_session`
  retry resubmits the same `(bundle, prompt, node, from_sketch)`, so the node is never
  re-counted. `load_strokes` runs only for bundles copied from disk: reloading a sketch
  bundle would wipe strokes drawn since.
- **Development UI**: `WHITTLE_PT_debug` is the "Development" sub-panel (closed by
  default, shown only with Developer Extras on): the bundle in use, `window_manager.whittle_fake_script` (used by Submit, Run Bundle
  and Start Agent when set), Run Bundle, Start/Stop Agent and the log tail after a crash.
- **Which controller** (`operators.controller(fake_script)`, called by every operator
  that runs the agent): a busy controller is always kept. An idle one with another
  fake script is closed and replaced. An idle one whose agent was started with other
  launch settings (`TurnController.launch_settings()`: the Python, fake script, a
  digest of the API key and the session settings, recorded at
  `start()`; `launch_changed`) has its agent stopped, so the next run starts a new
  process with the new settings and resumes the conversation from the history.
- **`whittle.view3d_override()`** raises in background Blender: the startup screen's
  areas still exist there, but operators run through them do nothing useful.
- **Live check results** (claude-haiku-5-5, one exec): `permission_mode="dontAsk"` with
  `allowed_tools` lets the MCP tools run; all ten `whittle:` skills load. The init
  skills list also shows the bundled CLI's own skills; they cannot be invoked
  (no `Skill(...)` allow rule under `dontAsk`) but do take context.

---

## 12. Sidebar

View3D sidebar, category "Whittle" (`addon/ui.py`), laid out as a chat; `docs/ui.md`
is the spec and has a mockup of every state. The draw code is plain functions of
`(layout, ctx)` (`ui.Ctx`: scene, history, controller, comparison, usable width, UI
scale) — `draw_main`, `draw_attention`, `draw_target_line`, `draw_comparison`,
`draw_start`, `draw_conversation`, `draw_sketch`, `draw_composer`, `draw_history`,
`draw_turn_menu`, `draw_ref_menu` — so tests drive them with a recording layout
(`tests/blender/ui_helpers.py`); panels cannot draw in background Blender. Draw code
never writes Blender data.

- **`WHITTLE_PT_main`**: no label of its own; the header's left side is the current
  chat's title opening the chat menu (`WHITTLE_PT_chats`, §14), its right side the
  agent indicator
  (an icon-only popover button for `WHITTLE_PT_agent`: state, model, session folder,
  Start/Stop Agent, Preferences). The body, top to bottom: an attention box only when
  the user must act (environment missing or broken → **Set Up…**, invoked with its
  confirmation; a setup running → progress and Cancel; a crashed or failed agent →
  **Restart**; no API key, or `TurnController.key_problem` → Preferences and Get a Key), the target line, the
  comparison bar while comparing, the start row (while `start.can_start()` allows a
  start and nothing was sent) or the conversation, the sketch strip, the composer.
- **Target line**: `targets.describe` (shortened) with `OBJECT_DATA`, `LOCKED` and the
  turn's own targets during a turn, and the **Auto** toggle
  (`scene.whittle.target_auto`). With Auto off: one plain row per target with its
  remove button (`whittle.target_remove`), **Add <selection>** (`whittle.target_add`),
  and the `WHITTLE_PT_targets` popover with the collection field, Replace With
  Selection and Clear.
- **Auto targets** (`addon/autotarget.py`): a `depsgraph_update_post` handler and a
  message-bus subscription on `LayerObjects.active` call `targets.sync_auto`, which
  makes the list `targets.auto_pick` (eligible selected objects, the active one first;
  else the active object; else nothing). It holds still during a turn or a waiting run,
  while comparing, while sketching and outside Object Mode; the list is written only
  when it differs. Whenever Whittle sets the list itself (a turn's end adopting created
  objects, Restore, Branch, a branch switch, Compare toggling back or ending, a start
  point) `targets.select_list` selects exactly those objects, so the next sync agrees.
  Turning Auto on syncs at once; a file load and the first timer tick after
  registration sync too.
- **Conversation** (`addon/conversation.py`, `conversation.build(history, controller)`):
  the turns on `tree.path(current)`, then a folded failure while it is the latest thing
  that happened (`TurnController.last_folded`, cleared by the next run), then the
  running or waiting turn (`TurnController.active_turn`: node and prompt, also while
  the agent or its session starts), then notes outside any turn. A running turn's
  entries are the live stream's; a finished turn is replayed from its
  `transcript.jsonl` (`stream.entries_from_records`, cached by file stamp), so a
  reopened file shows the same conversation. The request's stroke, view and reference
  counts come from `request/`. The start line names node 0 (a start point's label, or
  the objects its manifest recorded).
  - The last two turns of the path are expanded: a user bubble (box: the prompt; its
    last row ends with the branch switcher when the node has visible siblings, a ⇄
    mark on the compared turn, and ⋯ = `whittle.turn_menu`), Claude's text (whole), each run of tool calls and thinking as one
    closed `layout.panel` ("Used 4 tools", or the in-flight call's title with
    `SORTTIME`, "Running 2 tools" for several; inside, each call
    is its own panel with its code, result and render thumbnails; the last group of a
    finished turn ends with "4 steps · $0.0021"), notes (dim), warnings (`ERROR` icon,
    never red), amendments and answers as small boxes, the turn's picture (its
    last render, else `thumb.png`) and its end: "Stopped, changes kept / undone", or the
    reason (`stream.failure_reason`) as one red line with **Retry** beside it on the last
    turn (`ui.draw_failure`).
    A tool error the agent recovered from is never red.
  - Older turns are one closed `layout.panel(f"whittle_turn_{node}")` each, headed by
    the prompt; past six, the oldest go into "N earlier turns".
  - When the current node has children, "N later turns" with **Return to Latest**
    (`whittle.branch_switch` to the newest leaf).
  - The running turn ends with its phase ("Starting Claude…", "Working…" only while no
    call is in flight, "Stopping…") or Claude's question (a box with a button per
    choice).
- **Sketch strip**: the Sketch toggle, with Capture View beside it while sketching and
  the six stroke-type icon buttons on a row of their own (tooltips from
  `WHITTLE_OT_stroke_type.description`), then a panel headed by the stroke summary
  (`ui.stroke_summary`: "3 strokes · 2 views", "1 stroke sent · 1 view" for strokes a
  stopped or failed turn left, "1 view"; during a turn "3 sent · 1 new") with Clear;
  opened, the view list. Its open state is `WindowManager.whittle_show_views`
  (`layout.panel_prop`), so it can be set from Python.
- **Composer**: reference chips packed into rows (a chip is `whittle.ref_menu` with the
  name and preview icon; a pinned one has a pressed `whittle.ref_pin` beside it); the
  prompt field (`placeholder`) with 📎 (`whittle.ref_add`); **Send** (`whittle.submit`,
  "Send as Branch" off the end of a branch, disabled with a tooltip while
  comparing) and the history popover (`WHITTLE_PT_history`, `RECOVER_LAST`). During a turn the field is `amend_text` and the buttons are
  **Amend** and **Stop ▾** (`WHITTLE_MT_stop`: keep or undo); while Claude asks, the
  field is `ask_answer` and the button **Answer**. Send takes the prompt out of the box
  once the run is under way (`TurnController.hold_prompt`); a run that never starts,
  is refused, or folds puts it back.
- **Typing without the mouse** (`addon/shortcut.py`): `whittle.type_prompt`, an add-on
  keymap item on Shift+Alt+C in the Window keymap, opens the sidebar on the Whittle tab
  (`Region.active_panel_category`, retried on a timer until a hidden sidebar has
  listed its tabs) and `wm.call_panel` of `WHITTLE_PT_type_prompt` under the pointer: a
  one-line copy of the composer's field with `activate_init`, picked when the key is
  pressed. Enter confirms and closes the popup on its press; `addon/enter.py` sends on
  the release. See `ui.md` §3.12.
- **History popover** (`WHITTLE_PT_history`, a `HEADER` panel opened only as a
  popover, 24 units wide): Hide Ghost while a ghost shows, the comparison box, one row
  per `tree.walk()` node — indentation from `ui.branch_levels` (a node with one child
  continues its line; the children of a branch point step in by one unit and the first
  row of each branch has a dim ↳; a branch point says "2 branches"), the thumbnail, the
  title as the Restore button (the current one pressed) and ⋯ = `whittle.turn_menu` —
  and Open Transcript. The node id and full title are in the Restore button's tooltip.
- **Menus**: `whittle.turn_menu` and `whittle.ref_menu` are operators whose `invoke`
  opens `WindowManager.popup_menu` with a draw function closed over the node or index,
  since a menu class cannot take an argument. Turn menu: Edit & Resend, Go Back to This
  Turn, Compare With Current, Ghost of Previous Turn (current turn only), Open Render,
  Open Transcript (the start: Go Back to the Start and Compare With Current).
- **Operators**: `whittle.branch_switch` (`node`: restore the newest restorable leaf
  under it, one undo step "Whittle: switch to <node>"), `whittle.retry` (`node`: a
  folded failure is sent again as it is, a recorded one is branched first), plus
  `whittle.history_restore` / `history_branch` / `history_compare`,
  `whittle.compare_toggle`, `whittle.compare_end` (`keep`), `whittle.ghost_toggle`.
  Their bodies are the plain functions `switch_branch`, `retry`, `restore_node`,
  `branch_node`, `compare_node` and `toggle_ghost`; `can_restore`, `can_branch`,
  `can_compare`, `can_switch` and `can_retry` decide what is enabled.
- **`WHITTLE_PT_debug` "Development"** (closed by default, only with Preferences →
  Interface → Developer Extras), see §11.

**Steering** (`TurnController`): `amend(text)` works from Submit to the turn's end
(`can_amend`: busy and not interrupting; the Amend operator polls it and the composer
shows the amend field from Send on). Before the agent has accepted the turn (its
process or session still starting, or the submit on its way) the amendment is queued
(`queued_amends`, text and scene) and sent, in order, the moment the submit is
accepted, each with the strokes pending by then; a run that is dropped, refused or
ends first hands the queued text back to the prompt. Once accepted, it writes the
amendment bundle when there are pending strokes (sketch turns
only), records it and sends `amend`; an error answer hands it back. `interrupt(restore=)`
records the choice, sends `interrupt` before failing a pending question (so the agent
sees the interrupt first), and the choice is applied at `turn_finished`. `_finish`
order: hand back undelivered amendments (`amends_undelivered` ∪ sent but
never marked delivered: strokes pending again, bundle removed, text back in the prompt)
→ restore the turn start, or adopt created objects as targets → finish the history
node (snapshot, thumbnail, session id) → clear the sent strokes on success → one undo
push named `Whittle: <node> <label>`. "Stop at the next checkpoint" keeps its meaning: the running
call completes, queued calls are refused, the agent stops after its step; a long exec
cannot be pre-empted, so the panel shows "interrupting" until it ends.

## 13. Start points and references

`addon/start.py`. Every start writes node 0 through `History.start(objects, scene,
label=)`: with no tree it is `ensure_root`; with a root that has no children it rewrites
the root's `target.blend`, manifest, thumbnail (removed first, so a blank start leaves
none) and label; with children it raises `TreeError` (`StartError` to the user). The
first turn then finds the root and leaves it alone. Labels: "Start", "Blank",
"Primitive: Cube", "Asset: Barrel".

- **Existing**: the eligible selection becomes the target list (the picker is kept as it
  is when nothing eligible is selected); node 0 is `targets.resolve(scene)`.
- **Primitive**: `bmesh.ops` (`create_cube`, `create_cone` for cylinder and cone,
  `create_uvsphere`, `create_icosphere`, `create_grid`, `create_monkey`), scaled so its
  largest side is `size` and moved so its base is at z = 0 and its centre on the object
  origin; the object stands at the 3D cursor's x/y, in `Whittle Target`, as the sole
  target.
- **Asset**: OBJECT or COLLECTION only. From another file: `libraries.load(path,
  link=False, assets_only=True, clear_asset_data=True)`, then the `Library` the append
  leaves is removed. An appended object goes in `Whittle Target` at the cursor; a
  collection is linked under the scene and becomes `target_collection`, tagged
  `whittle_start` so a retaken start removes it (appended) or unlinks it (local). A
  local asset is used in place.
- **Blank**: adds nothing. It deselects everything, clears the active object and the
  targets (no `target_collection`) and records node 0 with no objects, so the first turn
  makes new objects, which `_adopt_created_objects` then makes the targets. Node 0 is an
  empty snapshot (restorable: `libraries.write(path, set())` is a valid file). (It used to add
  a `Whittle Target` collection, a ground grid and a scale reference; that read as clutter.)
  `REFERENCE_PROP = "whittle_reference"` marks the reference image empties in `Whittle
  References`, and `targets.eligible()` refuses anything carrying it. The system prompt's
  "Helpers in the scene" convention tells the agent never to edit them.
- **References** (`addon/refs.py`, `WhittleRef.pinned`): `run_sketch` remembers the
  reference paths it sent; a successful sketch turn calls `refs.clear_sent`, which removes
  the unpinned ones among them at the point the sent strokes are cleared. Failed and
  interrupted turns keep them all. `place_empty(scene, path, align=, size=, view=)` makes an
  IMAGE empty (`images.load(check_existing=True)`, `use_empty_image_alpha`, colour alpha
  0.5, `hide_render`, `REFERENCE_PROP = "image"`, `whittle_ref_path` = the source path) in
  `Whittle References`: FRONT faces -Y and stands 1 m behind the cursor (+Y), RIGHT faces
  +X 1 m to the cursor's -X, TOP lies just under it; VIEW takes the viewport's
  `view_rotation` and `view_location` and falls back to FRONT without a viewport. The
  chip's menu runs `whittle.ref_place` in the sidebar, whose `context.region_data` is
  None, so the view is found with `views.viewport_from_context` (the area's main region).


---

## 14. Chats and storage in the `.blend`

`ui.md` §3.11 is the sidebar's side. The storage choice and why is in `decisions.md`
(Chats).

A file holds any number of **chats**. A chat is what a session folder was until now:
one conversation, its history tree (§6) with every node's snapshot, thumbnail,
request, renders and transcript, and its SDK sessions. Exactly one chat is current;
the sidebar, `history.active()` and the `TurnController` all work on it, so
everything in §6 and §12 (branching, compare, ghost, transcripts) works per chat
unchanged.

The saved `.blend` is the store: every chat is packed into it, so the `.blend` alone
carries them. The working copy is a **hidden cache** in Whittle's user folder,
`<user dir>/cache/<file id>/`, named by an id the `.blend` stores; it is filled from the
`.blend` when the file opens, and where they disagree the `.blend` wins (crash recovery
aside, below). Nothing is ever written beside a `.blend`.

### Modules

- `whittle/chats.py`, stdlib only, so the agent tests cover all of it: the index
  (`Index`, `Entry`, `read_index`, `write_index`, `validate_index`),
  `title_for(prompt, target)`, `age_label(seconds)`, `size_label(bytes)`,
  `pack(folder) -> bytes`, `unpack(data, folder)`, `fingerprint(folder)`,
  `packed_size(folder)`, `new_chat_id()`, `config_dir()` and
  `cli_project_dir(cwd, config_dir)`: a port of the SDK's `project_key_for_directory`
  (realpath, NFC, non-alphanumerics to `-`, djb2 suffix past 200 characters), checked
  against the SDK's own function by an agent test. And `Chats(root)`, one per cache
  root: the index, `current`, `listed()`, `new()`, `ensure_current()`, `switch()`,
  `rename()`, `began()` and `refresh()` (the turn hooks' work), `to_delete(which)`,
  `delete()`, `folder(chat)`, `ensure_unpacked()`, `pack_all()` (for `save_pre`),
  `built_on()` and `reconcile()` (for `load_post`) and `migrate()`.
- `whittle/caches.py`, stdlib only: the caches themselves. `new_file_id()`,
  `state_stamp(index_json, packed)`, the record (`read_record`, `update_record`), the
  claim (`take`, `release`, `in_use_elsewhere`), `find(cache_dir, file_id, blend)`
  (which cache an opened file uses, with copy-on-conflict), `cleanup()` by age, and the
  earlier version's folders (`sidecar(blend)`, `replaced(blend)`, `migrate_sidecar()`,
  `cleanup_old_layout()`).
- `addon/chats.py`: which cache the open file uses (`file_id()`, `root()`, `get()`: its
  `Chats`, read once per file; `current_folder()`), the `save_pre` /
  `save_post` / `load_post` work (`before_save`, `after_save`, `after_load`, with the
  migration), `release()` and `cleanup()`, and the turn hooks `switch_note` /
  `turn_began` / `turn_ended`, which `TurnController` calls with its session folder (a folder that is
  not one of the file's chats, as in most tests, is left alone).
- `addon/paths.py`: `blend_path()` (None for an unsaved file), `cache_dir()` and
  `is_recovery_file()`.
- `agent/store.py`: `FolderSessionStore(folder)`, the SDK `SessionStore` adapter
  (below), stdlib only (the SDK finds its methods by name). `agent/runner.py` passes
  it; nothing else imports the SDK.
- Operators in `addon/operators.py` (`chat_new`, `chat_switch`, `chat_rename`,
  `chat_delete`, `chat_delete_many`, with plain-function bodies `new_chat`,
  `switch_chat`, `rename_chat`, `delete_chat`, `delete_chats`, and `chat_blocker`,
  `can_switch_chat`, `can_new_chat`, `can_delete_chat`); the menu is `WHITTLE_PT_chats`
  in `addon/ui.py`, drawn by `draw_chats(layout, ctx)`, and the header's title by
  `draw_chat_title`.

### The cache folder

```
<user dir>/cache/<file id>/                the cache root, saved file or not
  cache.json                               {"format": "whittle.cache", "version": 1, "id",
                                            "path": the .blend (null while unsaved),
                                            "used": seconds since the epoch,
                                            "base": state_stamp of what the .blend stores, or null}
  in-use.json                              {"pid", "host"}: the Blender that has the file open
  chats.json                               the index
  chats/<chat id>/                         one chat; also the agent's cwd for it
    chat.json                              {"format": "whittle.chat", "version": 1, "id", "title",
                                            "title_custom": bool, "created", "model": str | null}
    session.json, nodes/, compare/          the session folder of §8, unchanged
    sdk/<session id>.jsonl                 the chat's SDK transcripts (FolderSessionStore)
    sdk/<session id>/<subpath>.jsonl       subagent transcripts, if any
  packed/<chat id>.zip                     the chat as last written into the .blend
  packed/<chat id>.json                    {"digest": sha256 of the zip, "fingerprint", "size"}
```

Chat ids are `c` + 8 hex digits (`chats.new_chat_id()`), never reused in a file. File
ids are `f` + 16 hex digits (`caches.new_file_id()`).

**The file id** is a string ID property, `whittle_file_id`, on the holder Text below.
Unlike the payload it stays in the data: it is set when the file's cache is first made
(so an autosave carries it too; while Blender draws it cannot be, and the next save
writes it), and again at every save. The open file's id is kept in `addon/chats.py`,
so an undo that drops the Text changes nothing. Which cache an opened file uses
(`caches.find`):

| the file | its cache |
|---|---|
| stores an id whose cache records it, records nothing, or records a path that no longer exists (the file was moved or renamed) | that one; its `path` is updated |
| stores an id whose cache is claimed by a live Blender (`in-use.json`: a live process on this machine, or any on another), or records a different file that still exists (a copy) | the most recently used cache that records this file's path and is not in use, else a fresh id (**copy-on-conflict**), filled from the file. The copy keeps that cache on every open until it is saved with its new id, so a crash before that save keeps its work |
| stores no id (an earlier version's, or a file saved before its first chat) | the most recently used unclaimed cache that records its path, else none until a chat is made |
| unsaved (a new file) | none until its first chat, then a fresh id; any id its data has (from a startup file) is ignored. Saving keeps the cache: nothing moves |
| Blender's own recovery file (`quit.blend`, `*_autosave.blend`) | the id it stores, without the path check; its `path` stays the original's |

A file that never had a chat makes no cache. The claim is written when the cache is
found and removed on `load_pre`, `exit_pre` and unregister; a crashed Blender's claim
names a dead process and does not count.

**chats.json** (`chats.write_index`, atomic like every JSON file, §8):

| field | type | meaning |
|---|---|---|
| `format`, `version` | `"whittle.chats"`, `1` | |
| `current` | str \| null | the current chat |
| `chats` | {id: Entry} | every chat in the cache |

**Entry**: `title` (str), `created` (ISO str), `updated` (ISO str to the millisecond,
so two turns ending in one second still sort: the end of its last turn, else
`created`), `turns` (int: non-folded nodes other than the root), `size` (int: bytes it
adds to the `.blend`: `packed_size` of the folder when a turn ends, the zip's size once
saved), `digest` (str \| null: the sha256 of the zip the `.blend` last got), `model`
(str \| null: the chat's model, §15; optional, so an index from before it reads). The menu
draws from the index alone. The end of every turn (finished or folded) refreshes the
entry (`turn_ended`), and a save sets size and digest. A missing or unreadable index is
rebuilt from the chat folders (`chat.json` and `session.json`).

**Packed zip** (`chats.pack`): every file under the chat folder except `compare/`
(a comparison's scratch), `nodes/*/checkpoints/` (only used during their turn; 0.83 of
2.8 MB in the manual crate session) and partial files (`.tmp` names). `.png` and
`.blend` members are `ZIP_STORED` (already compressed: snapshots are written with
`compress=True`), the rest `ZIP_DEFLATED`. A `.jsonl` that is being appended to is
read up to its last newline. Member paths are relative and checked on unpack (no
`..`, no absolute paths): a `.blend` from someone else is data, not instructions.
Measured on the 12-turn manual crate session: 1.85 MB, packed in 12 ms; its SDK
transcript adds 0.31 MB (0.16 MB deflated).

**fingerprint**: a sha256 over the sorted `(relative path, size, mtime_ns)` of the
packed files: cheap to recompute at save, and different after any write.

### Storage in the `.blend`

The payload lives on a holder datablock, a Text named `.whittle` (`use_fake_user`;
a leading dot keeps it out of Blender's ID menus), and only **while the file is
being saved and just after it is loaded**:

- `save_pre` (`Chats.pack_all`): for each chat with a history (a `session.json`), if
  its `fingerprint` differs from `packed/<id>.json`'s, pack it again into
  `packed/<id>.zip` (atomically) and record digest, fingerprint and size; a chat not
  unpacked since the file opened goes back as its zip came; an empty chat is only its
  entry. Then set two ID properties on the holder: `whittle_chats_index` (the index as
  a JSON string, with `current`) and `whittle_chats` (a group, chat id → the zip's
  `bytes`). The holder is made only for a file that has chats; one that had them
  keeps it, so a file whose chats were all deleted says so. It also writes the current
  chat and its node into `scene.whittle.chat` / `history_node`, so the saved scene
  names them. A chat with a running turn is packed as it is (a reopened file marks
  that turn failed, §6).
  The handler gets the path being written; `before_save` keeps the stamp of what it
  stored (`caches.state_stamp`: the index string as written and every zip's digest).
  With the **Save Chats in the .blend** preference (`store_chats`) off, the holder gets
  only the file's id: the file carries no chat, and on opening it the cache is used as
  it is.
- `save_post`: deletes both properties (the holder stays, with the id). When the
  write fails Blender runs `save_post_fail` instead, which deletes them too and forgets
  the stamp (`chats.save_failed`); `load_post_fail` (another file failed to open, after
  `load_pre` let go of the cache) takes the open file's cache back (`chats.load_failed`). A save of the
  open file (the path Blender passes is `bpy.data.filepath`; a Save Copy's is not)
  records the file's path, the time and the stamp as `base` in `cache.json`, and removes
  an earlier version's folders for the file's name (Migration). The cache never moves,
  so a turn running through a Save As carries on.
- `load_post`: finds the file's cache (above), reads both properties, migrates an
  earlier version's folder, reconciles the cache (below), deletes the properties, then
  `history.sync_from_scene`. Without them (a file from before chats, one never saved
  with chats, or a recovery file) the cache is used as it is.

So between saves the payload is not in Blender's data at all: undo steps never copy
it, and undo can never roll it back. Measured (Blender 5.2.2, `docs/decisions.md`):
a 5 MB `bytes` property is assigned in 2 ms, adds exactly 5 MB to the file, saves in
3 ms and reads back byte-equal; 64 MB works; 400 nested entries take 1 ms; deleting
the property and saving again takes the file from 5.54 MB back to 0.54 MB. With 50 MB
kept in the data instead, every undo push cost 6 ms instead of 1 ms, every undo 15 ms
instead of 3, the payload sat in memory twice (data + undo memfile), and Ctrl+Z rolled
a change to the payload back with the scene. Load: reading and dropping 50 MB in
`load_post` took 5 ms, and later undo pushes were back to 1 ms.

A file opened in a Blender without Whittle keeps the payload in its data and saves it
back as it is, so nothing is lost by a round trip without the add-on. Blender's
autosave and crash recovery files do not run `save_pre`, so they carry no chats, only
the id; the file's cache still has them.

**Crash recovery**: when the cache's `base` equals the stamp of what the opened file
stores, the cache was in step with exactly this file and anything else in it is work
since that save (a crash, or closing without saving): `reconcile(keep_newer=True)` keeps
it all as it is. A cache migrated from an earlier version has no `base`; it counts as
built on the file when it has every chat the file has, each packed as the file's zip
(`Chats.built_on`). The `base` is then the file's stamp either way.

**Reconciling on load** (`Chats.reconcile`), otherwise, per chat, with `P` the
`.blend`'s entry and `C` the cache's:

| state | action |
|---|---|
| in `P` without a zip (an empty chat) | its folder with `chat.json`, if missing; a folder that has a `session.json` since differs from the file and is deleted first |
| in `P`, not in the cache | write the zip to `packed/<id>.zip`; unpack only when it becomes current (switching unpacks first) |
| in both, `P.digest == C.digest` and the folder's fingerprint is the packed one | in step: nothing to do |
| in both, otherwise (the cache changed after another save, or the file is another save) | the `.blend` wins: the chat folder is deleted, the zip is written and unpacked |
| in the cache, not in `P` | the `.blend` does not have it: deleted, with its packed copy |

The index is rebuilt from `P` (titles, times, `current`). Nothing is moved aside: the
cache is only ever a copy of a `.blend`, or work since that `.blend` was saved.

### Unsaved files, Save As, moving the file

An unsaved file's cache is made with a fresh id when its first chat is; the first save
writes that id into the file and records the path, so the cache, the controller and
the agent's cwd stay where they are. Save As records the new path; the file left
behind under the old name still stores the id, and opening it later finds the cache
recording the new name: it gets a fresh id and is filled from its own chats. Moving or
renaming the file outside Blender is found by the id (the recorded path is gone). A
`.blend` copied elsewhere, or to another machine, fills a cache there on load.

**Cleanup**: on every `load_post` (Blender loads a file after start-up too), and on
register when the add-on is enabled with a saved file open, `caches.cleanup` deletes every cache whose `used` (else its folder's
modification time) is 30 days old or more, with the CLI's transcripts of its chats'
folders, but never the open file's cache or one claimed by a live Blender on this
machine. `used` is set when the cache is found, at every save and at the end of every
turn. An earlier version's `<user dir>/dev-sessions/<time>/` and `caches/<sha1>/`
folders go by the same age (`cleanup_old_layout`).

### SDK session per chat

Each chat's folder is the agent's `cwd` (`start_session.session_dir`), so the CLI
keeps every chat's transcripts apart. `start_session` gains `store_dir` (absolute, the
chat's `sdk/`, or null). With it, the runner sets `ClaudeAgentOptions.session_store =
FolderSessionStore(store_dir)`: the SDK mirrors every transcript line the CLI writes
into the store (`append(key, entries)`, batched once per turn), and a `resume` loads
the session from the store (`load(key)`) into a temporary `CLAUDE_CONFIG_DIR` before
the CLI starts, so a chat resumes on another machine, or after the file moved, with
nothing in the CLI's configuration folder for it. (The SDK seeds that temporary folder
from the CLI's configuration folder, Whittle's private one, so it carries no login, and
removes it when the client disconnects.)
`FolderSessionStore` writes `<session id>.jsonl` (plus `<session id>/<subpath>.jsonl`)
by appending whole lines with one `write` per batch, implements `append`, `load` and
`list_subkeys`, refuses a session id or subpath that could leave its folder, and
ignores `project_key`: the key follows the cwd, which moves with the chat, and the
store is one chat's own (so the SDK's conformance contract on project isolation does
not apply). It never deletes: deleting a chat removes the folder.
`enable_file_checkpointing` must stay off with a store (the SDK refuses the
combination). The fake agent accepts `store_dir`, echoes it in its `start_session` log
with `stored_lines=N` for a resumed session, and appends one line per turn to
`<store_dir>/<session id>.jsonl`, so the store travels with a chat in the tests too.

The branching rule (§6) is per chat and unchanged: forks (`fork_session` with
`resume_session_at`) and plain resumes go through the store the same way. To check
live (`test_live_fork` with a store): a fork at a message uuid through a
store-materialized resume, and a resume after the chat folder moved.

### New chat, switching, renaming

- **New chat** (`operators.new_chat`): refused while `busy(ctl)`, while Claude asks or
  while comparing (`chat_blocker`), and when the current chat has no turns. Closes the
  controller (`ctl.close()`: the agent stops) and clears the ghost, makes
  `chats/<id>/` with `chat.json` (title `New chat`), makes it current in the index,
  drops the previous current chat if it had no turn (a start point or folded failures alone do
  not count: the menu would not list it, yet every save would carry it; a chat whose
  `session.json` cannot be read, that has a `session.json.bad-*` kept aside, or that is
  only packed so far is never taken for one without turns), and writes
  `scene.whittle.chat` (and an empty `history_node`). `turn.current()` is then None and
  the next run creates a controller on the new chat's folder
  (`operators.controller()` → `chats.current_folder(create=True)`). Its first submit
  finds no tree, so node 0 is written then (`ensure_root`, §6) from the scene as it is;
  `session_plan` on the root gives a fresh session with no note.
- **Switching** (`operators.switch_chat(context, chat)`): refused while `busy(ctl)` or
  comparing. Clears the ghost, closes the controller, unpacks the chat if its folder is
  not there, makes it current in the index, writes `scene.whittle.chat` and
  `history_node` (the chat's `current`) without an undo push, and invalidates the
  history cache. The scene is not touched. `Chats.switched` is set (for a chat with a
  history); the next submit of that chat (`switch_note`) adds the context line "This conversation was switched back to: the scene
  may have changed since its last turn (other chats or the user edited it). Inspect
  the target before editing.", cleared once the agent accepts the turn (`turn_began`). Otherwise the turn is a turn like any
  other: its parent is the chat's current node, and its start checkpoint and its node
  record the scene as it is, the same as after any edit the user made between turns.
  The plan resumes (or forks) the node's SDK session (§6).
- Restores in one chat only remove objects that chat's agent made
  (`created_uids` of its own tree): what another chat's agent made is the user's to
  that chat, and is never removed by it.
- **Rename**: sets `title` and `title_custom` in `chat.json` and the index; an empty
  title clears `title_custom` and puts back `chats.title_for` of the first turn.
- **Titles**: the agent accepting a chat's first turn (`turn_began` → `Chats.began`) sets
  the title from its prompt (or `Sketch of <first target>`) unless `title_custom`; a
  title, once set, never changes by itself.
- **Undo**: `history.sync_from_scene` applies `history_node` only when
  `scene.whittle.chat` is the current chat (an empty one counts as the current chat,
  for files from before chats); undo never switches chats.

### Deletion

`Chats.delete(chat)` (`whittle.chat_delete`, after its confirmation): refused for the
current chat while it cannot be left (`chat_blocker`: a turn runs in it, Claude asks,
or a comparison shows one of its nodes); any other chat can go at any time. It removes `chats/<id>/`, `packed/<id>.*` and the index entry,
and the CLI's project folder for that chat's cwd
(`chats.cli_project_dir(chat folder, paths.claude_config_dir())/`, which only ever
holds that chat's transcripts, since every chat has its own cwd); nothing else in that
folder is touched, and nothing outside Whittle's user folder. When it was current, the most recently `updated` remaining chat
becomes current as a switch, or a new empty chat when none is left. The `.blend` loses
the chat at the next save, because `save_pre` writes only the chats in the index.
`whittle.chat_delete_many` does the same for every chat the dialog's choice selects.

The saved file shrinks: a Blender test (`tests/blender/chats_file.py`) saves a file
with two chats, deletes one, saves again (uncompressed: zstd would also fold the
snapshots the two chats share) and checks the file is smaller by at least the deleted
chat's packed size less 1 %, and that reopening it lists one chat. Blender's `.blend1`
backup (Save Versions) keeps the previous save, chats included, until the save after.

### Migration

**From `<name>.whittle` beside the file** (an earlier version's cache): when the file is
opened (or saved, if it was opened before Whittle was enabled or updated), its
`<name>.whittle/` is moved into the file's cache once, if that has no chats yet
(`caches.migrate_sidecar`: a single-session layout first becomes a chat in place, so its
CLI transcripts are found by the old path; then `chats.json`, `chats/` and `packed/`
move), and rule 3 applies (`Chats.built_on` above). Then it and its
`<name>.whittle.replaced-<time>/` folders are deleted. Only folders that clearly belong
to that `.blend` are touched: the same stem, and Whittle's own markers (a `chats.json`
of format `whittle.chats` or a `session.json` of format `whittle.session`; a replaced
folder with a timestamp name holding one of those, or only `chats/<chat id>/`). The
earlier version's fallback for an unwritable folder, `<user dir>/caches/<sha1 of the
path>/`, is migrated the same way. A save of the open file also deletes such folders
beside its (new) name: the file just written is what they would be the cache of.

**From the single-session layout**: run once per cache root before anything reads a
history (`chats.get`, `Chats.migrate`), and idempotent:
a root with a `session.json` of its own (the single-session layout of §8) becomes one
chat. Its `session.json`, `nodes/` and `compare/` move into `chats/<id>/` (renames on
one filesystem), `chat.json` gets the title from the root's first turn (`chats.title_for`)
and `created` from `session.json`, and `chats.json` lists it as current. The CLI's
transcripts for the old cwd (`cli_project_dir(<root>)/<session id>.jsonl`, for every
session id in the tree) are copied into the chat's `sdk/`, so its conversation still
resumes from the new cwd. The old project folder is left to the CLI's own cleanup.
Development sessions migrate the same way. The file's first save then packs the chat
into the `.blend`.

### Tests

- Agent side (stdlib, `tests/agent/test_chats.py`, `test_store.py`): index round trip
  and validation, a lost index rebuilt; `title_for`, `age_label`, `size_label`;
  pack/unpack round trip, excluded folders, stored and deflated members, unsafe member
  paths refused, a partial last `.jsonl` line; `fingerprint` changes on a write;
  `project_key` equals the SDK's `project_key_for_directory` (a long path too); new,
  switch, rename, delete (the CLI folder of that chat only), bulk choices;
  `pack_all` repacking only what changed; `reconcile` for a missing cache, a cache in
  step, a cache that changed (deleted, the `.blend` wins), newer work kept, and an
  empty current chat; `built_on`; the migration with its CLI transcripts.
  `test_caches.py`: ids and stamps, the record, `find` (a moved file, a copy, a cache
  in use by a live, a dead or a foreign process, a file without an id), `cleanup` by
  age (never the open one or a live claim, the CLI's transcripts too), the earlier
  version's folders (only Whittle's own for that file) and their migration; `FolderSessionStore`
  append/load/subkeys and path safety, and the SDK materializing a resume from it;
  the fake agent's store lines.
- Blender side (`tests/blender/test_chats.py`): New Chat (a fresh session, its own
  node 0, the scene untouched, refused while a turn runs or when the chat is new);
  switching (the scene untouched, the context line on the next submit, the plan
  resumes that chat's session through its store, an old node of it restores); undo
  after a switch leaves the chat; delete another chat, the current one (→ the most
  recent, then an empty chat), and in bulk; the menu's rows, footer and Show N More;
  rename; the migration of a folder beside the file through `after_load`; the payload
  on the holder only between `before_save` and `after_save`. `chats_file.py`, in a
  fresh Blender: a real save, the cache deleted, the file opened without the add-on
  (both chats in its data) and with it (rebuilt: chats, titles, nodes, thumbnails, and
  an old node restored), then the delete shrink test above; the folder holds only the
  `.blend` and its `.blend1`. `test_session_folder.py`: an unsaved file's cache, the
  first save and Save As keeping it and the controller, a copy recording nothing, an
  earlier version's folders removed on save, and a real save and reopen.
  `test_cache.py` runs `cache_file.py` step by step in fresh Blenders: a new file
  saved twice, reopened and saved again (one cache throughout, nothing beside the
  file but its `.blend1`); moved and renamed; copied (its own cache, filled from it);
  opened while its cache is claimed by a live Blender; a crash after an unsaved turn
  (the turn is kept, the dead claim ignored); the older `.blend1` put in its place
  (the file wins); caches 31 days old deleted, 29 days old or claimed kept; and an
  earlier version's file with `old.whittle/` holding newer work and a replaced folder
  (migrated, newer work kept, Whittle's folders gone and nothing else touched).
- Screens: `ui.md` §10.

---

## 15. The model per chat

`ui.md` §3.13 is the sidebar's side.

**Which model a turn runs on.** `Entry.model` (also in `chat.json`, so a rebuilt index
and the `.blend` keep it) is the chat's model; null follows the add-on's **Model**
preference (`models.default_model()`), which is what a new chat starts on. A turn's
start, once the agent accepts it (`chats.turn_began(..., model)` → `Chats.began`), records the model it went with
on a chat that had none, so a later change to the preference leaves chats with turns
alone. `TurnController.chat_model()` is the controller's own `model` (tests), else the
chat's, else the default; `start_session.model` and every `submit.model` carry it. The
model is not part of `launch_settings()`: changing it never restarts the agent.

**Changing it.** `whittle.chat_model` (`models.set_chat_model`) writes the chat's entry
and `chat.json`; it is refused while a turn runs or Claude asks. The next submit names
the new model, and the runner switches the live SDK session with `client.set_model()`
before that turn's query (§5): the same session and transcript, so the chat stays
resumable and forkable (§6), and a branch or resume later starts its session on the
chat's model from the start. Switching chats closes the controller as before; the next
chat's session starts on its own model.

**The list.** `whittle/models.py` (stdlib):

- `parse(id) -> Model(id, family, version, date)` reads `claude-opus-5-5`,
  `claude-opus-5`, dated snapshots (`claude-opus-4-5-20251101`) and the old order
  (`claude-3-5-haiku-20241022`); an alias (`opus`), a `[1m]` variant or any other id
  is not one. `Model.name` is `Opus 5.5`; `short_name(id)` is the name, or the id
  itself for one it cannot read (the composer's button).
- `catalog(ids, source, fetched)` merges the reported ids with `KNOWN` (the models
  served when this version shipped, newest first per family), keeps the alias over a
  dated snapshot of the same version, and groups by family (`FAMILIES`: opus, sonnet,
  haiku, fable, then others by name), newest version first. `latest()` is the
  menu's first rows, `older()` the Older Models submenu.
- The cache: `<user dir>/models.json`, `{"format": "whittle.models", "version": 1,
  "source": "api" | "cli", "fetched": epoch seconds, "models": [ids]}`
  (`write_cache`, `read_cache`; a missing or unreadable file is the bundled list).

**Where the ids come from** (`SdkRunner._report_models`, once per agent process, a
task started when the first session connects, never on a turn's path):

- **The Models API**, with the agent's key (`ANTHROPIC_API_KEY` in its environment):
  `GET /v1/models` (`x-api-key`, `anthropic-version: 2023-06-01`, `limit=1000`,
  following `has_more`/`last_id` with `after_id`, at most 5 pages, 10 s timeout,
  honouring `ANTHROPIC_BASE_URL`), with plain `urllib` in a thread: the `anthropic`
  package is not in the lock. It lists every model the key can use, older versions
  included; the source is `api`. The listing uses no tokens.
- **Else the bundled CLI's initialize response**, when the Models API failed or listed
  nothing (`client.get_server_info()["models"]`, rows of `{value, resolvedModel?,
  displayName, description, disabled?}`: `value` is an alias like `default`, `opus`
  or an id; `resolvedModel` the id it stands for). Each row that is not `disabled`
  gives its id (`models.ids_from_server_info`): the newest of each family, no older
  versions (those come from `KNOWN`). It costs no request; the source is `cli`.
- The ids go to Blender as the `models` event (§3); `TurnController.on_event` hands
  them to `addon/models.received`, which writes the cache. `models.catalog()` reads
  it again only when the file changes. A failure on either source is a warning in the
  log; with no ids nothing is sent, and the menu keeps the last list (or the bundled
  one, `Built-in list until Claude starts`).

**Tests**: `tests/agent/test_models.py` (parsing, the catalog, the reports' ids, the
cache), `test_runner.py` `ModelTest` (`set_model` before the query and only on a
change, a failed switch, the Models API's list first and the CLI's only without it, once per process, with an injected
`list_models` and its paging through a mocked `urlopen`: no test calls the API),
`test_chats.py` `ModelTest`, `test_dispatch.py`, `test_fake_runner.py`;
`tests/blender/test_models.py` (the menu and submenu drawing, the composer button and
its hiding during a turn, the cache, and with the fake agent: the first turn keeping
the default, a switch between turns in the same session, a new chat on the default, a
switch back finding the chat's model). Screens: `model_menu`, `model_menu_older`.

---

## Appendix: API notes

Probed on Blender 5.2.2 LTS (a distribution-packaged build on Python 3.14.8) and
read from the installed `claude_agent_sdk` 0.2.167 (bundled CLI 2.1.300).

### Grease Pencil v3

- The datablock type is **`bpy.types.GreasePencil`** (there is no `GreasePencilv3` class;
  only the collections are named `GreasePencilv3Layers` / `GreasePencilv3LayerGroup`).
  `bpy.data.grease_pencils.new(name)`; the object's `type` is `"GREASEPENCIL"`.
- `gp.layers.new(name, set_active=True, layer_group=None) -> GreasePencilLayer`;
  `gp.layers.active`, `.remove`, `.move`.
- `GreasePencilLayer`: `frames`, `current_frame()`, `get_frame_at(n)`, `tint_color`,
  `tint_factor`, `opacity`, `hide`, `lock`, `matrix_local`, `matrix_parent_inverse`,
  `translation/rotation/scale`, `parent`.
- `layer.frames.new(frame_number) -> GreasePencilFrame`; `frame.drawing ->
  GreasePencilDrawing`.
- Strokes are hidden from a Workbench render by the curve attributes
  `hide_stroke = True` (BOOLEAN, created on demand) plus `fill_id = 0`: a strokes-only
  render of two isolated strokes went from 540 opaque pixels to none. Removing a
  created attribute afterwards (`drawing.attributes.remove`) leaves the drawing's
  attribute list as it was.
- `GreasePencilDrawing`: `strokes`, `attributes`, `curve_offsets`,
  `add_strokes(sizes)`, `remove_strokes(indices=None)`, `resize_strokes(sizes, indices=None)`,
  `reorder_strokes(new_indices)`, `set_types(type, indices)`, `tag_positions_changed()`.
- Stroke (`drawing.strokes[i]`): `points`, `cyclic`, `material_index`, `select`,
  `start_cap/end_cap`, `softness`, `time_start`, `fill_color/fill_opacity`,
  `add_points`, `remove_points`.
- Point: `position`, `radius`, `opacity`, `rotation`, `vertex_color`, `delta_time`,
  `select`. **No pressure field.**
- Built-in attributes: `position` (POINT, FLOAT_VECTOR), `curve_type` (CURVE, INT8),
  `radius`, `opacity` (POINT, FLOAT). Bulk read:
  `drawing.attributes["position"].data.foreach_get("vector", array)`;
  `curve_offsets[i].value` gives stroke start offsets.
- Custom attributes: `drawing.attributes.new(name, "INT", "CURVE")` (also `BOOLEAN`,
  `FLOAT_VECTOR` on `POINT`); values via `.data[i].value`; they survive save/reload.
- Stroke material: `bpy.data.materials.new(name)` then
  `bpy.data.materials.create_gpencil_data(mat)`; `mat.grease_pencil` has `color`,
  `show_stroke`, `show_fill`, `fill_color`, …; append to `gp.materials`.
- Tool settings (`scene.tool_settings`): `gpencil_stroke_placement_view3d` ∈
  `ORIGIN, CURSOR, SURFACE, STROKE`; `gpencil_surface_offset`;
  `use_gpencil_project_only_selected`; `gpencil_stroke_snap_mode` ∈ `NONE, ENDS, FIRST`;
  `use_gpencil_draw_onback`; `gpencil_paint`.
- Object modes: `PAINT_GREASE_PENCIL`, `EDIT_GPENCIL`, `SCULPT_GREASE_PENCIL`,
  `WEIGHT_GREASE_PENCIL`, `VERTEX_GREASE_PENCIL`.
- Factory startup has no brushes in `bpy.data.brushes`; drawing in tests is done through
  the data API, not the draw operator.
- `gp.layers.new(name, set_active=False)` leaves `layers.active` as None;
  `gp.layers.active = layer` sets it. Layers iterate in creation order.
- `radius`, `opacity` and `cyclic` are not in `drawing.attributes` until something
  writes them (`attributes["radius"]` raises KeyError); `point.radius` /
  `point.opacity` then read the defaults 0.01 / 1.0. `position` always exists.
  Bulk reads: `attributes[name].data.foreach_get("value" | "vector", array)`.
- A custom curve-domain INT attribute keeps its values through `add_strokes` (new
  strokes get 0), `reorder_strokes(new_indices=…)` and `remove_strokes(indices=…)`:
  values stay with their strokes.
- `curve_offsets[i].value` has n + 1 entries (stroke start offsets plus the total).
- Strokes also have `fill_id` (INT, curve) and `hide_stroke` (BOOLEAN, curve). A stroke is
  filled when `fill_id != 0`, with the material's `fill_color` (alpha included) under the
  layer tint; `MaterialGPencilStyle.show_fill` is ignored by the renderer and emits a
  DeprecationWarning ("removed in Blender 6.0"), and the material panel no longer shows
  it. `hide_stroke = True` hides the outline. GP materials also carry a default shader
  node tree.
- String ID properties on the GreasePencil datablock and the custom attributes survive
  `save_as_mainfile` + `open_mainfile`.
- `bpy.ops.object.mode_set(mode="PAINT_GREASE_PENCIL")` and back to `OBJECT` work in
  background mode. `gpencil_stroke_placement_view3d` defaults to `ORIGIN`,
  `gpencil_surface_offset` to 0.0.

### Viewport / views

- `RegionView3D`: `view_matrix`, `window_matrix`, `perspective_matrix`,
  `view_perspective`, `is_perspective`, `view_location`, `view_rotation`,
  `view_distance`, `view_camera_zoom`, `view_camera_offset`.
- `SpaceView3D`: `lens`, `clip_start`, `clip_end`, `camera`, `region_3d`.
- `bpy_extras.view3d_utils`: `location_3d_to_region_2d`, `region_2d_to_location_3d`,
  `region_2d_to_origin_3d`, `region_2d_to_vector_3d`.
- `camera_object.calc_matrix_camera(depsgraph, x=…, y=…)` returns the projection;
  `P[0][0] = 1/tan(fov_x/2)` (checked: lens 50, sensor 36 → 2.778).
- `bpy_extras.object_utils.world_to_camera_view(scene, cam, co)`.
- `scene.ray_cast(depsgraph, origin, direction) -> (hit, location, normal, index, object, matrix)`;
  the normal is world space. It does not hit Grease Pencil objects.
- `-b --factory-startup` has one window with a VIEW_3D area and a real `RegionView3D`,
  but its matrices are never recomputed: setting `view_location/rotation/distance`
  leaves `view_matrix` stale, and `window_matrix` is read-only. **`RegionView3D.update()`
  segfaults Blender in background mode.** Tests build views from real camera matrices
  and pass duck-typed fake viewports.
- The viewport projection uses a 72 mm sensor: at lens 50, `P[0][0] = 1.3889` (a
  camera's 36 mm sensor gives 2.778), so views are derived from `window_matrix`, never
  from `SpaceView3D.lens`.
- A camera spec from a projection matrix round-trips through a render camera and
  `calc_matrix_camera(x=w, y=h)` for PERSP and ORTHO, landscape and portrait: landscape
  `sensor_fit = "HORIZONTAL"`, `angle = 2·atan(1/P[0][0])`, `ortho_scale = 2/P[0][0]`;
  portrait `"VERTICAL"` with `P[1][1]`. Maximum error 2.4e-7.

### Render

- `scene.render.engine = "BLENDER_WORKBENCH"` is accepted even though the static enum
  items list only `BLENDER_EEVEE`.
- `scene.display.shading`: `light` ∈ `STUDIO, MATCAP, FLAT`; `color_type` ∈ `MATERIAL,
  OBJECT, RANDOM, VERTEX, TEXTURE, SINGLE`; `studio_light` (matcap default
  `basic_bright.exr`), `show_cavity`, `show_object_outline`, `show_xray`.
  There is no `show_wireframes`; Workbench *render* ignores `object.display_type = "WIRE"`
  (identical coverage measured), hence the `WIREFRAME` modifier approach.
- `scene.display`: `render_aa`, `viewport_aa`, `light_direction`, `shading`.
- `scene.view_settings.view_transform` defaults to `AgX`; `Standard` gives flat colours.
- `render.film_transparent`, `render.image_settings.file_format = "PNG"`,
  `color_mode = "RGBA"`, `bpy.ops.render.render(write_still=True)` writes
  `render.filepath`.
- `bpy.data.images["Render Result"].size` is `(0, 0)` in background mode: read pixels by
  writing a file and `bpy.data.images.load`. `image.pixels.foreach_get/foreach_set` with
  a float32 numpy array; save with `filepath_raw`, `file_format`, `save()`.
- Timing (256–512 px, default cube): first render ~0.43 s, later renders milliseconds.
- `gpu.types.GPUOffScreen(w, h)` works in background mode (backend `OPENGL`);
  `draw_view3d(scene, view_layer, view3d, region, view_matrix, projection_matrix, *,
  do_color_management=False, draw_background=True)` needs a real `SpaceView3D` and
  region, so it is GUI-only.
- `object.show_in_front` exists (viewport only).

### Libraries

- `bpy.data.libraries.write(filepath, datablocks: set, *, path_remap="NONE",
  fake_user=False, compress=False)`; `path_remap` ∈ `NONE, RELATIVE, RELATIVE_ALL,
  ABSOLUTE`. Indirect datablocks are written too.
- `bpy.data.libraries.load(filepath, *, link=False, pack=False, relative=False,
  set_fake=False, recursive=False, reuse_local_id=False, assets_only=False,
  clear_asset_data=False, create_liboverrides=False, …)` → context manager
  `(src, dst)`; assign name lists to `dst.objects` etc.; after the block, `dst.objects`
  holds the appended `Object`s (not linked to any collection yet).
- Appending leaves a `bpy.types.Library` in `bpy.data.libraries` even with `link=False`;
  remove it after restore. Name collisions get `.001` suffixes.
- `bpy.data.orphans_purge` exists but is global; Whittle does not use it.
- `ID.user_remap(new)` moves every use of an ID to another: for an object, collection
  membership, children's parent pointers and modifier/constraint references; for a
  material, every slot that used it (on other objects too). Remove the old ID after.
- Appended objects carry no `library_weak_reference` (meshes do, inconsistently), so
  restore pairs by the manifest's names and order instead. An object referenced only
  indirectly (a boolean modifier's cutter) is appended too, unlinked and as `Name.001`
  when the name is taken; `src.objects` lists it.
- `bpy.ops.object.mode_set(mode="OBJECT")` from Edit Mode works under `-b`, after
  which `user_remap` of the mesh is safe.
- Measured on the crate: `libraries.write` of the target ≈ 2 ms; append + remap +
  cleanup ≈ 4 ms.
- Snapshots are written with `path_remap="ABSOLUTE"`, not `RELATIVE_ALL`: an image path
  made relative to `nodes/<id>/` would be resolved against the user's `.blend` once
  appended, and break.
- A geometry-nodes modifier's input value (`getattr(mod.properties.inputs,
  identifier).value`) and a nested group's node settings survive write + append.
- `libraries.write(path, set())` writes a valid file; loading it lists no objects (an
  empty node 0).
- Ghost by append: appending a target from its `target.blend` gives `Crate.001`,
  `Wood.001`, keeps `whittle_uid` and leaves one `Library`. Removing the object, then
  the unused appended data and the Library, returns `bpy.data` counts to baseline.
  Linking (`link=True`) also works and takes `display_type`, but a linked "Crate"
  shares the local object's name, so name lookups could pick it; Whittle appends and
  renames instead.
- A 128 px Workbench thumbnail takes ≈ 0.2 s on the first render of a session (shader
  compile) and ≈ 10 ms after.
- `snapshot.restore` used to leave whatever mode was active; it now leaves a mode only
  when the active object is one being replaced, so a sketch in
  `PAINT_GREASE_PENCIL` survives a history restore.

### App, timers, handlers, extensions

- `bpy.app.timers.register(fn, *, first_interval=0, persistent=False)`,
  `unregister(fn)`, `is_registered(fn)`; `fn()` returns seconds or `None`.
  **Timers do not run during `blender -b --python script`.**
- `bpy.app.handlers`: `depsgraph_update_post`, `load_pre`, `load_post`, `save_post`,
  `exit_pre`, `undo_post`, `redo_post`, `render_pre/post`; decorate with
  `@bpy.app.handlers.persistent` to survive file loads.
- `bpy.app.online_access` (False under `--factory-startup -b`), `bpy.app.background`.
- `bpy.utils.extension_path_user(package, *, path="", create=False)`;
  `bpy.utils.user_resource("EXTENSIONS")` → `~/.config/blender/5.2/extensions`.
- `sys.exit(n)` inside a `--python` script sets Blender's exit code;
  `--python-exit-code N` sets it for an uncaught exception.
- `numpy` is importable in Blender's Python.
- Geometry Nodes modifier inputs moved in 5.2: `mod["Socket_2"] = value` raises
  `TypeError`; use `getattr(mod.properties.inputs, identifier).value = value`, with the
  identifier from `group.interface.items_tree`.
- `bpy.app.online_access` is read-only; `--online-mode` on the command line turns it on.
- Depsgraph handlers (checked under `-b`): `view_layer.update()` runs
  `depsgraph_update_post` synchronously, and a second `update()` reports nothing
  (updates are consumed). Location → Object `is_updated_transform`. Vertex co +
  `mesh.update()` → Object geometry + Mesh. Material colour → shading-only updates on
  Object, Mesh, Material and the material's ShaderNodeTree. `select_set`/`hide_set` →
  only the Scene. Adding a modifier to one object tags *other* objects with
  `is_updated_shading`. ID property writes → no update. Entering Edit Mode → Object +
  Mesh geometry. `ID.session_uid` exists and equals `update.id.original.session_uid`.
  `view_layer.update()` with nothing pending ≈ 2 µs.
- Undo cannot run under `-b`, so the undo handlers (`_after_undo`) are checked by
  calling them, not by a real Ctrl+Z.
- UI: `UILayout.panel(idname, default_closed=False)` → `(header, body)` with `body`
  None while closed, and `template_icon(icon_value, scale)` exist in 5.2.
  `bpy.utils.previews` loads a PNG under `-b` (`image_size` is right) but `icon_id`
  is 0 there, so thumbnails are only checked by hand.
- Manifest keys accepted by 5.2's validator (`addons_core/bl_pkg/cli/blender_ext.py`):
  `id`, `schema_version`, `name`, `tagline`, `version`, `type`, `maintainer`, `license`,
  `blender_version_min`, `blender_version_max`, `website`, `copyright`, `permissions`
  (table; keys `files`, `network`, `clipboard`, `camera`, `microphone`), `tags`,
  `platforms`, `wheels`, `[build] paths`, `[build] paths_exclude_pattern`. Template:
  `scripts/templates_toml/blender_manifest.toml` in Blender's install.
- `blender --command extension {build,validate,install-file,…}`.
- `WindowManager.invoke_confirm(operator, event, title="", message="", confirm_text="",
  icon='NONE', …)`. `StringProperty(search=fn, search_options={"SUGGESTION"})` offers
  `fn(self, context, edit_text)`'s strings and still accepts free text (checked by
  assigning `"claude-foo"`). An `AddonPreferences` class's RNA properties only exist while
  it is registered.
- Assets: `ID.asset_mark()` works on instances (a type-level `hasattr` is False, it is an RNA
  function). `bpy.types.AssetRepresentation` has `name, id_type, local_id,
  full_library_path, full_path, …`; `context.asset` is set in the Asset Browser, whose
  context menu is `ASSETBROWSER_MT_context_menu`. `Menu.remove(fn)` of an entry that is not
  there is a no-op. `libraries.load(..., assets_only=True, clear_asset_data=True)` appends a
  marked object or collection (a collection brings its objects) without its asset data,
  and leaves a `Library` behind.
- `bmesh.ops.create_grid(size=s)` spans ±s (`x_segments` cells); `create_cube(size=1)` spans
  ±0.5; `create_cone(radius2=0)` makes a cone; `create_monkey` spans about 2.73 × 1.97.
- Image empties: `empty_display_type = "IMAGE"`, `obj.data = image`, `empty_image_offset`,
  `empty_image_side`, `use_empty_image_alpha` (the alpha is `obj.color[3]`),
  `show_empty_image_only_axis_aligned`. `scene.ray_cast` hits a `hide_select` object.
- With a distribution-packaged Blender whose Python is the system `/usr/bin/python3.14` (3.14.8), its `ensurepip`
  bundles pip 26.2.1, whose `install` takes `--isolated`, `--no-input`, `--require-hashes`,
  `--only-binary`, `--no-deps` and `--disable-pip-version-check` (checked from the bundled
  wheel's `--help`, nothing installed). `-I -m venv` works with it. A venv's `bin/python`
  whose target was removed is a dangling symlink: `Path.is_file()` is False.
- `bpy.utils.extension_path_user("bl_ext.user_default.whittle")` is
  `~/.config/blender/5.2/extensions/.user/user_default/whittle`.

### Binary data in a `.blend` (probed for chats, §14)

- `id["key"] = some_bytes` stores a `bytes` ID property that reads back as `bytes`,
  byte-equal after save and reload. 5 MB: assigned in 2 ms, +5.00 MB on disk, saved in
  3 ms (5.09 MB with `compress=True`: random data does not compress). 64 MB works
  (59 ms to assign). A group of 200 × 2 entries (dict of dicts of bytes) assigns in
  1 ms and reads back in under 1 ms.
- Deleting the property and saving again shrinks the file (5.54 → 0.54 MB, the same
  as the empty file), also with `save_mainfile` over the same path; the `.blend1`
  backup then holds the previous, larger save.
- `save_pre` runs before the data is written, also for `save_as_mainfile(copy=True)`:
  properties set there are in the file, and deleting them in `save_post` leaves
  nothing in memory.
- Undo (GUI Blender, 20 pushes of a moved cube): with 50 MB of bytes properties in the
  data, `ed.undo_push` 5.9 ms (1.1 ms without), `ed.undo` 14.5 ms (3.4), resident memory
  about twice the payload, and undo rolled back a change to the properties with the
  scene. After a load whose `load_post` deleted the payload, pushes were 1.0 ms and no
  undo brought it back.
- ID properties on the window manager are not kept by a file load (with or without
  `load_ui`). A Text with `use_fake_user` and no other user survives save and load.
- A Text datablock is no store for binary data: `from_string` of 6.8 MB of base64 on
  one line did not finish in 150 s, and 0.7 MB of base64 in 76-character lines added
  1.6 MB to the file.
- `bpy.data.is_dirty` read from Python (background, or a GUI timer) did not follow
  edits or saves, so whether deleting the payload in `save_post` / `load_post` marks the
  file modified is to be checked by hand (the title bar's `*`).

### claude-agent-sdk 0.2.167

- Forking at a message: `ClaudeAgentOptions(resume=S, fork_session=True,
  resume_session_at=<uuid>)` (sent as `--resume-session-at=`) starts a new session id
  whose transcript ends at that message. Checked live with haiku: after two turns in
  session S, a fork at the first turn's last message uuid gave a new session whose
  messages (`get_session_messages(id, directory=session_dir)`) hold the first turn's
  prompt and not the second's. A plain `resume=S` keeps the id S.
- `AssistantMessage.uuid` and `UserMessage.uuid` are filled by the bundled CLI.
- `client.get_server_info()` returns the CLI's initialize response (the SDK keeps it
  from `connect()`): `commands`, `agents`, `output_style`, … and `models`, a list of
  `ModelInfo` rows `{value, resolvedModel?, displayName, description, disabled?, …}`
  (read from the bundled CLI's schema; `unavailable_models` is `@internal`). No
  separate models request exists in the SDK or the CLI's control protocol.
  `client.set_model(model)` sends the `set_model` control request; the session and
  its id stay.
- The offline alternative, `claude_agent_sdk.fork_session(S, directory=,
  up_to_message_id=)`, copies a transcript with fresh uuids; Whittle does not need it.

- `ClaudeSDKClient(options=None, transport=None)`: `connect(prompt=None)`,
  `query(prompt: str | AsyncIterable[dict], session_id="default")`,
  `receive_messages()`, `receive_response()` (stops after a `ResultMessage`),
  `interrupt()`, `set_model()`, `set_permission_mode()`, `get_mcp_status()`,
  `get_context_usage()`, `get_server_info()`, `disconnect()`; async context manager.
  The client must stay in the task group it connected in.
- `ClaudeAgentOptions` fields used: `tools` (`[]` = no built-ins), `allowed_tools`,
  `disallowed_tools`, `system_prompt` (str → `--system-prompt`; `None` → empty prompt),
  `mcp_servers`, `strict_mcp_config`, `permission_mode` (`default`, `acceptEdits`,
  `bypassPermissions`, `plan`, `dontAsk`, `auto`), `model`, `fallback_model`, `resume`,
  `fork_session`, `resume_session_at`, `session_id`, `cwd`, `cli_path` (default: the
  bundled `claude_agent_sdk/_bundled/claude`), `env` (merged over `os.environ`),
  `stderr` (callback), `setting_sources` (`None` = all; `[]` = none), `skills`
  (`None` | `"all"` | list of exact names, `plugin:skill` for plugin skills; setting it
  adds `Skill(...)` to allowed tools and defaults `setting_sources` to
  `["user", "project"]` only when that is `None`), `plugins`
  (`[{"type": "local", "path": …}]` → `--plugin-dir`), `include_partial_messages`,
  `max_turns`, `max_budget_usd`, `thinking`, `effort`, `can_use_tool`, `hooks`.
- `@tool(name, description, input_schema, annotations=None)` on `async def handler(args)
  -> {"content": [...], "is_error"?: bool}`; `input_schema` may be `{"x": str}`, a
  TypedDict, or a full JSON Schema dict (used as-is when it has `type` and `properties`).
  Arguments are validated with jsonschema before the handler runs; handler exceptions
  become error results.
- Result content blocks passed through: `{"type": "text", "text"}` and
  `{"type": "image", "data": <base64>, "mimeType": "image/png"}`.
- `ToolAnnotations(maxResultSizeChars=N, read_only_hint=…, …)` from `claude_agent_sdk`.
- `create_sdk_mcp_server(name, version="1.0.0", tools=[...]) -> McpSdkServerConfig`;
  tools are exposed to the model as `mcp__<server key>__<tool name>`.
- Messages: `SystemMessage(subtype, data)` (`init` carries `session_id`, `tools`,
  `mcp_servers`, `skills`, `plugins`, `model`); `AssistantMessage(content, model,
  parent_tool_use_id, error, usage, message_id, stop_reason, session_id, uuid)`;
  `UserMessage(content, uuid, parent_tool_use_id, tool_use_result)`; blocks
  `TextBlock(text)`, `ThinkingBlock(thinking, signature)`, `ToolUseBlock(id, name, input)`,
  `ToolResultBlock(tool_use_id, content, is_error)`; `ResultMessage(subtype, duration_ms,
  duration_api_ms, is_error, num_turns, session_id, stop_reason, total_cost_usd, usage,
  result, errors, terminal_reason, …)` — `total_cost_usd` is the session's running
  total (the SDK says a conversation reset zeroes it; confirmed live across two turns) — `terminal_reason` `aborted_streaming` /
  `aborted_tools` after an interrupt; `StreamEvent` only with partial messages.
- Errors: `ClaudeSDKError`, `CLIConnectionError`, `CLINotFoundError`, `ProcessError`,
  `CLIJSONDecodeError`.
- `resume` reaches the CLI as a single `--resume=<id>` argument; `fork_session` as
  `--fork-session`.
- `create_sdk_mcp_server` keeps its tools inside the MCP server; tests call them through
  `claude_agent_sdk._internal.sdk_mcp_bridge.SdkMcpBridge` (`initialize`, then
  `tools/call`), the same JSON-RPC path the CLI uses, which also runs the schema check.
- Plugin layout accepted by `claude plugin validate`:
  `<dir>/.claude-plugin/plugin.json` (`name`, `version`, `description`; `author`
  recommended) and `<dir>/skills/<name>/SKILL.md` with `name`/`description` frontmatter.
- The bundled CLI honours `MCP_TOOL_TIMEOUT` (ms) for MCP tool calls.
- The GP v3 datablock class is `bpy.types.GreasePencil`, not `GreasePencilv3`
  (`decisions.md` corrected accordingly).
