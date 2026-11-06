# Working on Whittle

A guide for coding agents and new contributors. It points into `docs/` rather than
repeating it; when this file and a doc disagree, the doc wins (and fix this file).

## What Whittle is

A Blender 5.2 extension (Blender's Python, 3.13 or 3.14) that runs a Claude Agent SDK agent as a
chat in the 3D viewport sidebar. The user sketches over a model with Grease Pencil,
writes a prompt, and the agent edits the open scene by running Python in Blender. Every
turn is a node in a branching history; a file can hold several chats, stored in the
`.blend`. Licensed GPL-3.0-or-later.

Platforms (README, Platforms): developed on Linux x64 with a distribution's Blender on
Python 3.14 (blender.org's 3.13 has passed the offline suite in CI, not a real turn); Linux arm64, Windows
x64 and macOS on Apple silicon are in the manifest and the code, and the last two run in
CI, but real use on all three is untested; Intel Macs are not supported. One zip serves all four: it carries no wheels, and the setup installs the
platform's own from the hash-pinned lock. What differs per platform lives in
`whittle/platforms.py` and takes the platform as an argument, so the Linux suite covers
the Windows branches with kernel32 faked; route new process spawning, killing, liveness
probes, atomic file replaces and the clean-up of what a killed agent leaves through it.

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
  `claude_agent_sdk` at module level (`tools.build_servers` does so when called); everything
  else there is stdlib, so the fake agent runs under any Python 3.13
  or 3.14.
- **Shared**, `whittle/*.py` (`protocol`, `formats`, `tree`, `chats`, `caches`,
  `markdown`, `models`, `style`, `venv`, `platforms`): stdlib only at module level.
  `whittle/__init__.py` stays bpy-free at import time.
- **The bridge**: `addon/bridge.py` (Blender side, driven by `bpy.app.timers`) and
  `agent/connection.py` (agent side) speak `whittle/protocol.py`. Agent tool calls are
  queued and run on Blender's main thread in `addon/commands.py`.
- Code uses relative imports only (inside Blender the package is `bl_ext.<repo>.whittle`).

Read first: [docs/architecture.md](docs/architecture.md) (the blueprint: §1 layout, §2
processes and authentication, §3 protocol, §4 main-thread queue, §5 agent side, §10
tests). Then [docs/decisions.md](docs/decisions.md) (why), [docs/ui.md](docs/ui.md) (the
sidebar spec), [docs/prompting.md](docs/prompting.md) (agent-facing text),
[docs/modeling-practices.md](docs/modeling-practices.md) (the research behind the system
prompt's modeling practice and the mesh skills) and [docs/progress.md](docs/progress.md)
(what exists, known gaps, manual checklist). `decisions.md` wins over `design.md`;
`architecture.md` wins on implementation detail.

## Setup

You need Blender 5.2 as `blender` on `PATH`. The README's Development section has the
exact commands; in short:

- Make `.venv/` at the repo root from Blender 5.2's own Python (3.13 or 3.14) and install
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

Every command is time-bounded; keep it that way for anything you add. The scripts are
POSIX shell and use GNU `timeout`; `screens.sh`, `gui_checks.sh` and `docs_shots.sh` need
Linux with KDE's `kwin_wayland`.

```sh
./run_tests.sh                 # offline suite: agent side in .venv, then blender -b
./run_tests.sh -v -k test_chat # only matching tests, on either side
./gui_checks.sh                # every GUI check in a real, hidden Blender (~4 min)
./gui_checks.sh undo_turn send_key
WHITTLE_GUI=1 ./run_tests.sh   # the suite, then every GUI check
./screens.sh                   # sidebar screenshots into build/screens/ (several minutes)
./screens.sh conversation asking
./screens.sh --docs            # the README's images, into docs/images/
./build.sh                     # validate and build build/whittle-<version>.zip
./docs.sh                      # the documentation site into build/docs/html
./docs.sh --strict --out DIR   # every page rebuilt, warnings are errors, all of it in DIR
./docs_shots.sh guides-undo    # a site page's screenshots, into docs/site/images/
./docs_shots.sh --all          # every page's (~6 min); --list and --check launch nothing
```

- **Tests** use the stdlib `unittest` (pytest is not installed). Agent tests are in
  `tests/agent/` (fake Blender, fake SDK client); Blender tests are in `tests/blender/`,
  run through `tests/blender/run.py` inside `blender -b --factory-startup`, and pump
  `Bridge.tick()` themselves (timers never fire in `-b`). With `-k`, a side with no
  match exits 5 and is skipped; the script fails only if neither side matched.
- **Live tests** (`tests/blender/test_live.py`) call the real API: only with
  `WHITTLE_LIVE=1` and `ANTHROPIC_API_KEY`, and they cost money (cents, billed to that
  key). Run them only when asked.
- **GUI checks** (`tests/gui/`: `catalog.py` says what each check confirms, `checks.py`
  drives it) cover what only a GUI Blender does: a real Ctrl+Z during a turn, the draw
  tool on surfaces, modal transforms, file browsers, File → Recover, crashes, the keys,
  the Preferences. `gui_checks.sh` first builds the zip with `build.sh` and installs it
  with `blender --command extension install-file` into a local extension repository of
  the run's own (`build/gui-checks/gui_checks/`, the only repository listed), so every
  check runs the installed extension as a user would. Each check runs one GUI Blender per
  phase with `--enable-event-simulate`, sends simulated input through Blender's own event
  handling, and uses the fake agent and fake API keys only, with Blender offline.
  Blender's user folders, its temp folder and Whittle's user folder are the run's own,
  under `build/gui-checks/`; the harness refuses to run if Blender's config folder is not
  the run's or Whittle was not loaded from the run's repository. Results are in
  `build/gui-checks/report.json`, each phase's log in
  `build/gui-checks/<check>/phase-<n>.log`, and the preference checks leave screenshots
  beside it. `tests/gui/spy.py` records what Blender's own redraws drew, for asserting
  on the Preferences, the sidebar and the popovers.
- **Screenshots**: `screens.sh` runs one real GUI Blender per scenario in
  `tests/screens/catalog.py`. A failed scenario's log is
  `build/screens-work/<scenario>/blender.log`. The README's images are committed under
  `docs/images/`; regenerate them with `--docs` after a change to what they show, and
  look at each before committing.
- **Hidden windows**: `gui_checks.sh`, `screens.sh` and `docs_shots.sh` open their Blenders
  in a hidden nested Wayland session (`kwin_wayland --virtual`), so no window appears on
  the desktop. Without `kwin_wayland` they stop and say so. `WHITTLE_GUI_VISIBLE=1` and
  `WHITTLE_SCREENS_VISIBLE=1` show the windows instead, only when the person running
  them wants that; `docs_shots.sh` has no such switch.
- **Documentation site**: `docs/site/`, a Sphinx project with one MyST page per doc and the
  API reference autodoc builds from the docstrings. `docs.sh` builds it from `.venv-docs/`,
  a docs-only venv from `docs/site/requirements.lock`; it needs no Blender and no network.
  Install nothing for it into `.venv`. `docs_shots.sh` runs from `.venv`: each shot's spec is
  `docs/site/shots/<page-slug>.py` (`tests/docshots/` runs them; `docs/site/shots/README.md`
  is the guide), its image `docs/site/images/<page-slug>/<shot>.png`, committed. Every
  Blender gets its own hidden session and folders under `build/docs-shots/`, and
  `WHITTLE_DOCSHOTS_SLOTS` caps how many run at once. `tests/agent/test_docs_site.py` and
  `test_docshots.py` check the source and the specs without Sphinx or Blender.
- **Build**: `build.sh` refuses to build when `whittle/requirements.lock` or
  `whittle/LICENSE` differs from its root copy. It never copies them for you.

- **CI**: `.github/workflows/`, GitHub-hosted runners only. `ci.yml` and `release.yml`
  both call `test.yml` (offline suite and `build.sh`, one job per runner); `release.yml`
  also checks the tag (`.github/scripts/release_tag.py`) and publishes from a job with no
  checkout. `ubuntu-latest` gates; `windows-latest` and `macos-latest` use
  `continue-on-error`, and `publish` does not need them. Blender comes from
  `.github/scripts/fetch_blender.py`, with its version and hashes pinned there. Actions
  are first-party and pinned to a commit: `tests/agent/test_ci.py` checks that and the
  rest. How to cut a release is in the README.

## Hard rules

**Supply chain.**
- Every dependency is an exact pin with hashes in `agent_env/requirements.lock`,
  installed from wheels only, without resolution. No `github:`/VCS references. The docs
  site's tools follow the same rules in `docs/site/requirements.lock`, and never ship.
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
  `process.agent_environment` strips other `ANTHROPIC_*`/`CLAUDE*` variables, keeping
  only the two in `process.KEPT` (a gateway's `ANTHROPIC_BASE_URL` and the user's own
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`); keep both.
- The key goes nowhere but Blender's preferences and the agent's environment: never in
  logs or files (`tests/blender/test_auth.py` checks the agent's log and Whittle's user
  folder for it).
- The CLI's own usage telemetry and error reports are off by default: the agent runs
  with `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` unless the user turns on **Send
  Claude CLI usage data** (`usage_data`, off by default). Keep that default.
- Never modify the bundled CLI; Whittle only chooses its environment and folder.
- No "Claude Code" branding: Whittle is its own product, "Powered by Claude" at most.

**Tests and the user's machine.**
- The default suite makes no API calls, needs no key and installs nothing. Real API
  calls belong only in the opt-in live tests.
- Tests never touch the user's Blender config or Whittle folder. Blender tests run with
  `--factory-startup`, and a test that touches Whittle's user folder gets a fresh one of
  its own: derive it from `AgentTestCase`, or wrap it in `TempUserDir`
  (`tests/blender/helpers.py`), which points `WHITTLE_USER_DIR` at a temp folder for that
  one test. GUI runs point the `BLENDER_USER_*` folders into `build/gui-checks/` or
  `build/screens-work/`.
- GUI Blender runs never pop windows on the desktop: use the hidden session.
- Every wait has a deadline and every subprocess a timeout; no test may hang.

## Conventions

- **Style**: match the code around you: plain functions, type hints, few comments and
  those saying why. New source files start with `# SPDX-License-Identifier:
  GPL-3.0-or-later`.
- **Main thread**: all `bpy` access happens on Blender's main thread, from the bridge
  tick or operators. `exec` cannot be pre-empted, so keep work per call short. Calls
  that change the scene wait while a modal operator runs (architecture §4).
- **Undo** (ui.md §8): a turn pushes `Before Whittle turn` as it starts, before the
  agent's first edit (after a running modal operation ends), and
  `Whittle: <node> <label>` when it finishes. Ctrl+Z during a turn lands on the turn's
  start: an `undo_pre` handler first gives the agent's edits so far a step of their own
  (`Whittle: <node> so far`), so Ctrl+Shift+Z brings them back. History operators push
  one step each; chats are never undone. New scene-changing operators need a deliberate
  undo story.
- **Sidebar**: `docs/ui.md` is the spec; change it with the UI. Draw code is plain
  functions taking a layout in `addon/ui.py` (with `addon/conversation.py` for the
  conversation), and it never writes Blender data. UI changes are reviewed on
  screenshots: run `./screens.sh` for the affected scenarios and look at the images
  against ui.md §10's checks.
- **Keys** (`addon/keys.py`, ui.md §3.8 and §3.12): add-on keymap items, all on
  Shift+Alt so they stay clear of Blender's own keys and fit a tablet's express keys:
  Shift+Alt+D toggles Sketch mode, V captures a view, and
  Enter (`whittle.send_key`) does what Enter in the prompt box does (Send, Amend during a
  turn, Answer while Claude asks). Shift+Alt+C (`addon/shortcut.py`, the Window keymap)
  opens the "Ask Claude" prompt under the pointer. Each is rebindable in Preferences →
  Keymap. `tests/blender/test_keys.py` checks each against Blender's default keymap; a
  new key needs its row in ui.md, the README and decisions.md.
- **Model and effort** belong to the chat (ui.md §3.13): each chat keeps its own model
  and effort (`models.EFFORTS`, High by default), set from the menu beside Send and
  recorded in its chat entry. **Model for New Chats** in the preferences only seeds new
  chats.
- **Per-file settings** (ui.md §3.1, the agent popover's For This File): the four session
  settings in `prefs.SESSION_SETTINGS` (triangle budget, self-check rounds, render size,
  style notes) are the preferences' Defaults, and a file can override each one
  (`props.FILE_SETTINGS`, stored on the scene, so they travel with the `.blend`). `prefs.session_settings()` merges them; a change restarts the agent before
  the next turn. Names, tooltips and bounds live once in `prefs.py` (`LABELS`,
  `DESCRIPTIONS`, `LIMITS`).
- **Style guides** (architecture §1, decisions Behaviour): Style Notes (`style_file`) is
  a path to a `.md` or `.txt` file, which `style.load_guide` reads with its `@path`
  imports. Draw code only asks `prefs.style_guide` for the last read; the disk is read
  before each turn and when a path may have changed, never from a redraw, and a running
  turn and its amendments keep the guide they started with. `session_settings` carries the text, so a changed guide restarts the agent like a
  changed setting. Nothing about a guide fails a turn: a problem is a warning for the
  user and one line for the agent. A `.blend` from someone else can name any path and
  what loads goes to the API, so keep the file-type check on the resolved path and the
  128 KiB cap. A save into another folder rewrites `//` overrides as strings only
  (`props.rebase_style_paths`): it never reads the guide, and it writes the store, not the
  property, whose update reads. `style.portable_path` leaves rooted paths alone.
- **Chats from another machine** (ui.md §3.11): every chat records the install that
  made it (`origin`, the random id in the user folder's `install.json`). A chat from
  another install opens with a **Continue this chat?** box; Send stays disabled
  until Continue (`whittle.chat_continue`) adds this install to the chat's `adopted`.
  Anything that sends a turn must respect that gate.
- **Agent-facing text** (system prompt, skills, tool descriptions, errors the agent
  reads) follows `docs/prompting.md`: practices with reasons, judgment over rules, normal
  volume, one home per fact, brief replies to the user, actionable errors.
- **Docs stay in step with the code**: update README, `docs/architecture.md`, `ui.md`,
  `decisions.md` and `progress.md` (what exists, known gaps, the manual checklist) in the
  same change, and this file when what it says changes. The site in `docs/site/` is part
  of that: `docs/*.md` are the specs and the record, its guide pages are the user's view.
- **Commits**: imperative subject line, short body saying why.

## Where to look first

- **A tool for the agent**: handler and schema in `agent/tools.py` (`TOOLS`; handlers
  take `(ctx, args)`), a method in `protocol.Method` if it needs Blender, its handler in
  `addon/commands.py` (`build_handlers`; fake scripts reach it with a `call` step),
  tests in `tests/agent/test_tools.py` and `tests/blender/`, the tables in
  architecture §5 and `docs/site/develop/agent-tools.md`, and the description per
  prompting.md.
- **A skill**: `agent/plugin/skills/<name>/SKILL.md` (self-contained; the agent has no
  Read tool), its name in `agent/prompt.py` `SKILLS`, the lists in architecture §1 and
  `docs/site/develop/agent-tools.md`; `tests/blender/test_skills.py` runs each recipe's Python blocks.
- **A sidebar state**: spec and mockup in ui.md §4 and a check in §10, draw code in
  `addon/ui.py` (with `addon/conversation.py` for the conversation), a scenario in
  `tests/screens/catalog.py` and `scenarios.py`, layout tests in
  `tests/blender/test_sidebar.py`, and the user's view in `docs/site/guides/sidebar.md`.
- **A flow only a GUI shows** (a real undo, a key, a file browser, a restart): a check
  in `tests/gui/catalog.py` and `checks.py`, its description in the catalog, and the
  lists in the README's GUI checks and progress.md.
- **A preference**: `addon/prefs.py` (`WhittlePreferences`, `DEFAULTS`), session
  defaults in `agent/prompt.py` `DEFAULTS` if the agent uses it, tests in
  `tests/blender/test_prefs.py`, the README and `docs/site/guides/settings.md`. A session setting a file may override
  also goes in `prefs.SESSION_SETTINGS` (with its `LABELS` and `DESCRIPTIONS`), which
  gives it a field in For This File; tests in `tests/blender/test_file_settings.py`.
- **The style guide**: resolving it and its wording in `whittle/style.py` (tests in
  `tests/agent/test_style.py`), the last reads and what the sidebar shows in
  `addon/prefs.py`, how the agent is to read it in `agent/system_prompt.md`, and the
  user's view in `docs/site/guides/settings.md`.
- **Something platform-specific**: `whittle/platforms.py` (with the platform passed
  in, tested in `tests/agent/test_platforms.py`), `venv.compatible()` for which
  platforms set up at all, and the README's Platforms table.
- **A page of the documentation site**: `docs/site/<doc>.md`, listed in a toctree in
  `docs/site/index.md`; its pictures in `docs/site/shots/<page-slug>.py`, shot with
  `./docs_shots.sh <page-slug>` and shown on the page (`tests/agent/test_docs_site.py`
  checks that); a new module gets its `automodule` in `docs/site/reference/`.
- **Wire formats**: `protocol.py` (bridge), `formats.py` (request bundle, session
  folder), architecture §3 and §8, and `docs/site/develop/protocol.md`.
