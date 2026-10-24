# Working on Whittle

A guide for coding agents and new contributors. It points into `docs/` rather than
repeating it; when this file and a doc disagree, the doc wins (and fix this file).

## What Whittle is

A Blender 5.2 extension (Linux x86_64, Blender's Python 3.14) that runs a Claude Agent
SDK agent as a chat in the 3D viewport sidebar. The user sketches over a model with
Grease Pencil, writes a prompt, and the agent edits the open scene by running Python in
Blender. Every turn is a node in a branching history; chats are stored in the `.blend`.
Licensed GPL-3.0-or-later.

Three processes:

```
Blender (add-on, main thread)  <-- bridge: JSON lines over 127.0.0.1 -->  agent process
                                                                          (venv Python, asyncio)
                                                                              |
                                                                     bundled Claude CLI
                                                                     (from the claude-agent-sdk wheel)
```

- **Add-on**, `whittle/addon/`: may import `bpy`, `bmesh`, `mathutils`, `gpu`, `numpy`.
  Never imports `whittle.agent`.
- **Agent**, `whittle/agent/`: never imports `bpy`. Only `agent/runner.py` imports
  `claude_agent_sdk`; everything else there is stdlib, so the fake agent runs under any
  Python 3.14.
- **Shared**, `whittle/*.py` (`protocol`, `formats`, `tree`, `chats`, `caches`,
  `markdown`, `models`, `venv`): stdlib only at module level. `whittle/__init__.py` stays
  bpy-free at import time.
- **The bridge**: `addon/bridge.py` (Blender side, driven by `bpy.app.timers`) and
  `agent/connection.py` (agent side) speak `whittle/protocol.py`. Agent tool calls are
  queued and run on Blender's main thread in `addon/commands.py`.
- Code uses relative imports only (inside Blender the package is `bl_ext.<repo>.whittle`).

Read first: [docs/architecture.md](docs/architecture.md) (the blueprint: §1 layout, §2
processes and authentication, §3 protocol, §4 main-thread queue, §5 agent side, §10
tests). Then [docs/decisions.md](docs/decisions.md) (why), [docs/ui.md](docs/ui.md) (the
sidebar spec), [docs/prompting.md](docs/prompting.md) (agent-facing text) and
[docs/progress.md](docs/progress.md) (what exists, known gaps, manual checklist).
`decisions.md` wins over `design.md`; `architecture.md` wins on implementation detail.

## Setup

You need Blender 5.2 as `blender` on `PATH`. The README's Development section has the
exact commands; in short:

- Make `.venv/` at the repo root from Blender 5.2's own Python 3.14 and install
  `agent_env/requirements.lock` with `--require-hashes --only-binary :all: --no-deps`,
  exactly as the add-on does. Install nothing else into it.
- `export WHITTLE_AGENT_PYTHON="$PWD/.venv/bin/python"` (or the Development → Agent
  Python preference) so the add-on uses it instead of a private venv.
- Symlink `whittle/` into a local extensions repository to run the source in place;
  restart Blender after code changes.
- `WHITTLE_USER_DIR` points Whittle's user folder at a scratch folder for manual runs.
- No API key is needed for development: the fake agent (`agent/fake.py`, scripts in
  `tests/fixtures/fake/`) plays scripted turns. With Developer Extras on, the sidebar's
  Development → Fake Script runs one.

## Commands

Every command is time-bounded; keep it that way for anything you add.

```sh
./run_tests.sh                 # offline suite: agent side in .venv, then blender -b
./run_tests.sh -v -k test_chat # only matching tests, on either side
./screens.sh                   # sidebar screenshots into build/screens/ (~1.5 min)
./screens.sh conversation asking
./build.sh                     # validate and build build/whittle-<version>.zip
```

- **Tests** use the stdlib `unittest` (pytest is not installed). Agent tests are in
  `tests/agent/` (fake Blender, fake SDK client); Blender tests are in `tests/blender/`,
  run through `tests/blender/run.py` inside `blender -b --factory-startup`, and pump
  `Bridge.tick()` themselves (timers never fire in `-b`). With `-k`, a side with no
  match exits 5 and is skipped; the script fails only if neither side matched.
- **Live tests** (`tests/blender/test_live.py`) call the real API: only with
  `WHITTLE_LIVE=1` and `ANTHROPIC_API_KEY`, and they cost money (cents, billed to that
  key). Run them only when asked.
- **Screenshots**: `screens.sh` runs one real GUI Blender per scenario in
  `tests/screens/catalog.py`, in a hidden nested Wayland session (`kwin_wayland
  --virtual`), so no window appears on the desktop. Without `kwin_wayland` it stops;
  `WHITTLE_SCREENS_VISIBLE=1` shows the windows instead, only when the person running
  it wants that. A failed scenario's log is `build/screens-work/<scenario>/blender.log`.
- **Build**: `build.sh` refuses to build when `whittle/requirements.lock` or
  `whittle/LICENSE` differs from its root copy. It never copies them for you.

## Hard rules

**Supply chain.**
- Every dependency is an exact pin with hashes in `agent_env/requirements.lock`,
  installed from wheels only, without resolution. No `github:`/VCS references.
- Never add, upgrade or remove a package without the maintainer's explicit approval,
  and never in a change about something else.
- `whittle/requirements.lock` stays byte-identical to `agent_env/requirements.lock`
  (`build.sh` and a test check it).
- An unexpected change to either lock in a diff is a red flag: stop and surface it.
- Never publish anything (no uploads, no pushes) on anyone's behalf.

**Authentication and Anthropic's terms** (architecture §2 Authentication, decisions
Auth and Distribution).
- An Anthropic API key only: the preference, else `ANTHROPIC_API_KEY`. Never add a
  claude.ai login, subscription plan credentials, or a way to collect such tokens.
- Never read or write the user's own Claude configuration (`~/.claude` and the like).
  The CLI runs with Whittle's private `CLAUDE_CONFIG_DIR`, and
  `process.agent_environment` strips other `ANTHROPIC_*`/`CLAUDE*` variables; keep both.
- The key goes nowhere but Blender's preferences and the agent's environment: never in
  argv, logs or session files (`tests/blender/test_auth.py` checks).
- Never modify the bundled CLI; Whittle only chooses its environment and folder.
- No "Claude Code" branding: Whittle is its own product, "Powered by Claude" at most.

**Tests and the user's machine.**
- The default suite makes no API calls, needs no key and installs nothing. Real API
  calls belong only in the opt-in live tests.
- Tests never touch the user's Blender config or Whittle folder: Blender tests run with
  `--factory-startup` and a temporary `WHITTLE_USER_DIR` (`tests/blender/helpers.py`);
  GUI runs point the `BLENDER_USER_*` folders into `build/screens-work/`, and the
  harness refuses to run otherwise.
- GUI Blender runs never pop windows on the desktop: use the hidden session.
- Every wait has a deadline and every subprocess a timeout; no test may hang.

## Conventions

- **Style**: match the code around you: plain functions, type hints, few comments and
  those saying why. New source files start with `# SPDX-License-Identifier:
  GPL-3.0-or-later`.
- **Main thread**: all `bpy` access happens on Blender's main thread, from the bridge
  tick or operators. `exec` cannot be pre-empted, so keep work per call short. Calls
  that change the scene wait while a modal operator runs (architecture §4).
- **Undo**: a turn pushes `Whittle: before <node>` and `Whittle: <node> <label>`;
  history operators push one step each; chats are never undone (ui.md §8). New
  scene-changing operators need a deliberate undo story.
- **Sidebar**: `docs/ui.md` is the spec; change it with the UI. Draw code is plain
  functions of `(layout, ctx)` in `addon/ui.py` that never write Blender data. UI
  changes are reviewed on screenshots: run `./screens.sh` for the affected scenarios and
  look at the images against ui.md §10's checks.
- **Agent-facing text** (system prompt, skills, tool descriptions, errors the agent
  reads) follows `docs/prompting.md`: practices with reasons, judgment over rules, normal
  volume, one home per fact, brief replies to the user, actionable errors.
- **Docs stay in step with the code**: update README, `docs/architecture.md`, `ui.md`
  and `progress.md` (what exists, known gaps) in the same change.
- **Commits**: imperative subject line, short body saying why.

## Where to look first

- **A tool for the agent**: handler and schema in `agent/tools.py` (`TOOLS`; handlers
  take `(ctx, args)`), a method in `protocol.Method` if it needs Blender, its handler in
  `addon/commands.py` (`build_handlers`; fake scripts reach it with a `call` step),
  tests in `tests/agent/test_tools.py` and `tests/blender/`, the table in
  architecture §5, and the description per prompting.md.
- **A skill**: `agent/plugin/skills/<name>/SKILL.md` (self-contained; the agent has no
  Read tool), its name in `agent/prompt.py` `SKILLS`, the list in architecture §1;
  `tests/blender/test_skills.py` runs each recipe's Python blocks.
- **A sidebar state**: spec and mockup in ui.md §4 and a check in §10, draw code in
  `addon/ui.py` (with `addon/conversation.py` for the conversation), a scenario in
  `tests/screens/catalog.py` and `scenarios.py`, layout tests in
  `tests/blender/test_sidebar.py`.
- **A stroke type**: `formats.STROKE_TYPES`, colours in `addon/sketch.py`, meanings in
  `addon/operators.py` `STROKE_MEANINGS`, icons in `addon/ui.py` `STROKE_ICONS`, the table in
  `agent/system_prompt.md`, and architecture §7.
- **A preference**: `addon/prefs.py` (`WhittlePreferences`, `DEFAULTS`), session
  defaults in `agent/prompt.py` `DEFAULTS` if the agent uses it, tests in
  `tests/blender/test_prefs.py`, and the README.
- **Wire formats**: `protocol.py` (bridge), `formats.py` (request bundle, session
  folder), architecture §3 and §8.
