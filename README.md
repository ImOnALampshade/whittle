# Whittle

A Blender extension for sketch-driven modeling: orbit a model, sketch over it with Grease
Pencil, add a prompt or reference images, and a Claude agent makes the edit in your open
scene while you watch and steer. Every turn becomes a node in a branching history.

Whittle is powered by Claude, through your own Anthropic API key. It is an independent
open-source project, not made by, endorsed by or affiliated with Anthropic.

![The Whittle sidebar: a conversation of three finished turns with their tool calls and
render thumbnails](build/screens/wide/conversation.png)

(The image is generated, not committed: `./screens.sh conversation` writes it, see
[Sidebar screenshots](#sidebar-screenshots).)

See [docs/design.md](docs/design.md) for the original design, [docs/architecture.md](docs/architecture.md)
for how it is built, [docs/decisions.md](docs/decisions.md) for the choices behind it,
[docs/ui.md](docs/ui.md) for the sidebar, and [docs/progress.md](docs/progress.md) for what
works today and what is still rough.

Requirements: Blender 5.2 on Linux x86_64 (its Python 3.14), and an Anthropic API key.
The agent environment is only built for that platform for now.

## Status and limitations

Whittle is young (0.1.0); expect rough edges.

- **Platforms**: Linux x86_64 and Blender 5.2 only. The pinned agent environment holds
  wheels for that platform and Python 3.14; Windows and macOS are not built yet.
- **Sign-in**: an Anthropic API key only (API key and cost). Every turn calls Claude
  and costs tokens.
- **Not built yet**: view gizmos and snap-to-view, default keys for the sketch operators,
  and per-file overrides of the triangle budget and style notes.
- **Checked in a real GUI Blender by script**: flows background tests cannot reach, such
  as a real Ctrl+Z during a turn, strokes drawn with the real draw tool and File → Recover,
  run in `./gui_checks.sh` (GUI checks, below). What still needs a person, such as
  tablet pressure and clicking the sidebar's own buttons, is the manual checklist in
  [docs/progress.md](docs/progress.md).

## Install

1. Build the extension zip:

   ```sh
   ./build.sh            # validates, then writes build/whittle-0.1.0.zip
   ```

2. Install it: in Blender, **Edit → Preferences → Get Extensions → Install from Disk…** and
   pick `build/whittle-0.1.0.zip`, or from a shell:

   ```sh
   blender --command extension install-file -r user_default build/whittle-0.1.0.zip
   ```

3. Turn on **Preferences → System → Network → Allow Online Access**. Whittle refuses to start
   the agent, or download anything, without it.

4. Set up the agent environment: **Preferences → Add-ons → Whittle → Agent Environment → Set
   Up Agent Environment**, then confirm the dialog. (The sidebar offers the same button when
   the agent cannot start for lack of it.)

   - **What it downloads**: the 30 packages pinned in `requirements.lock`, among them
     Anthropic's `claude-agent-sdk` 0.2.167, whose wheel bundles the Claude Code CLI that
     runs the agent. They come from PyPI only, as prebuilt wheels.
   - **How**: Whittle makes a venv from Blender's own Python (`sys.executable -I -m venv`), then
     runs
     `pip install --isolated --disable-pip-version-check --no-input --progress-bar raw --require-hashes --only-binary :all: --no-deps -r requirements.lock`
     inside it. Every file must match a hash in the lock, nothing is built from source (so no
     package's setup code runs), and nothing beyond the lock is resolved. `PIP_*`, `PYTHON*`,
     `UV_*`, `VIRTUAL_ENV` and `CONDA_*` variables are dropped for these steps, so no
     configuration can point pip at another index. Proxies (`HTTPS_PROXY`) and `SSL_CERT_*`
     are kept.
   - **Slow connections**: the `claude-agent-sdk` wheel is about 114 MB. The status line shows
     its download progress, and the install is only stopped if no data arrives for 5 minutes
     (or after 3 hours in all), so a slow but working connection gets there.
   - **Where**: the extension's user folder, `~/.config/blender/5.2/extensions/.user/user_default/whittle/venv`,
     unless you pick another **Environment Folder** first. The log of each setup is in
     `…/whittle/logs/venv-<time>.log`.
   - **Updates**: Whittle never upgrades anything by itself. After an extension update that
     ships a different lock, the preferences (and the sidebar) say the environment was set up
     for an earlier version; press **Reinstall** to rebuild it from the new lock.

5. Add your API key (next section).

## API key and cost

Whittle runs Claude only with an Anthropic API key, as Anthropic's terms ask of
products built on the Agent SDK. It cannot use a Claude.ai login or a Free, Pro or Max
plan, and it never reads the Claude configuration in your home folder.

1. Make a key in the [Claude Console](https://platform.claude.com/settings/keys)
   (**Get an API Key** in Whittle's preferences opens that page). The Console account
   needs API credits; API usage is billed separately from any Claude subscription.
2. Paste it into **Preferences → Add-ons → Whittle → Anthropic API Key**.

Or leave the preference empty and start Blender with `ANTHROPIC_API_KEY` in its
environment. A key in the preferences wins over the environment; the preferences say
which one is in use. Without either, the agent does not start and the sidebar asks for a
key.

The key is kept in Blender's preferences (saved with them in `userpref.blend`) and handed
to the agent process in its environment; Whittle writes it nowhere else and never logs
it. The agent's environment drops every other Claude or Anthropic credential, and the
bundled CLI runs with a configuration folder of Whittle's own
(`…/extensions/.user/user_default/whittle/claude/`), so it never sees your own Claude
login, settings, hooks or MCP servers.

**Cost**: every turn is billed to the key's account at the model's API price. A turn's
cost shows at the end of the turn in the conversation (`· $0.0123`). The model, the
**Self-check Rounds** and the **Render Size** are the main levers: Opus is the most
capable and the most expensive per token, Haiku the cheapest, and each self-check round
sends renders back to the model. Set spending limits in the Console.

**Model for New Chats** is the model a new chat starts on, `claude-opus-5-5` by default;
it offers the models your key can use and takes any other model id. The **Defaults** box
sets the triangle budget, style notes, self-check rounds and render size every session
starts with.

## Use

Open the 3D viewport sidebar (N) → **Whittle**. It reads like a chat: what Claude is working
on, the conversation, a sketch strip and a prompt box. The panel's header shows the
current chat's title (click it for the chat menu, step 8); the icon beside it is the
agent's state: click it for the model, the session folder and Start/Stop.

1. **Target**: with **Auto** on (the default) Claude works on whatever is selected (or the
   active object); with nothing at all it makes new objects. Turn Auto off to pick targets
   by hand, or to name a collection.
2. **Start from** (shown until the first turn, optional):
   - **Selection**: the selected objects, as they are, are the target and history node 0.
   - **Blank**: this scene as it is, with nothing selected and nothing targeted, so Claude
     makes new objects. Nothing is added to the scene.
   - **Primitive**: a cube, cylinder, sphere, … standing at the 3D cursor.
   - **Asset Browser**: right-click an object or collection asset → **Start Whittle From Asset**.
   Typing a prompt and pressing Send works too: node 0 is the scene as it is.
3. **Sketch**: press Sketch, pick a stroke type (free, add, carve, crease, region, note; the
   tooltips say which is which) and draw; strokes stick to surfaces, and off a surface they
   land on the view plane at the 3D cursor. Orbit and draw from more angles.
4. **Describe**: type a prompt (Shift+Enter adds a line); 📎 adds reference images. Pin a reference to send it with
   every request; its ⋯ menu places it in the scene as a half-transparent image empty.
   **Shift+Alt+C** from anywhere, in any mode, opens the sidebar and a prompt field under
   the pointer, ready to type with no mouse: Enter sends, Esc closes. While a turn runs it
   amends the turn, and while Claude asks it answers. Rebind it in Preferences → Keymap
   (Window → Ask Claude).
5. **Model**: the button beside Send (`Opus 5.5 ▾`) picks the model this chat runs on,
   from its next turn: the newest of each family (Opus, Sonnet, Haiku, Fable), older
   versions under **Older Models**, or **Other Model…** for any id. The list is the one
   the Models API reported for your key when the agent last started, kept in Whittle's
   user folder; before that, a built-in list.
6. **Send** (Enter, or the Send button), then watch the turn. While it works, type into the
   field and press Enter or **Amend**,
   answer Claude's questions, or **Stop ▾** (keep the changes or undo the turn).
7. **History** lives on the turns: ✎ edits and resends a turn as a new branch, ‹ 1/2 ›
   switches between branches, and ⋯ goes back to a turn, compares it, shows a ghost or opens
   its render and transcript. The 🕘 button beside Send shows the whole tree.
8. **Chats**: the title in the header opens the chat menu. **New Chat** starts an empty
   conversation with a fresh Claude session and its own history, from the scene as it
   is. Clicking an earlier chat goes back to its conversation and Claude session; the
   scene stays as it is (its history is there to go back to a turn by hand). Each chat
   shows its turns, age and the size it adds to the file. Delete one with its 🗑, or
   many with **Delete Other Chats…** (all, or older than a week, a month or three
   months); either asks first. Each chat keeps its own model.

Every chat is stored inside the `.blend` when you save, so the file alone carries them all,
and nothing is written beside it. That includes everything in them: your prompts, Claude's
replies and the code it ran, your reference images and its renders. Before you share a
`.blend`, delete its chats, or turn off **Preferences → Add-ons → Whittle → Files → Save
Chats in the .blend** (chats then stay in this computer's cache, and files saved from then
on carry none). While you work, Whittle keeps a hidden copy in its own
user folder (`cache/<file id>/`), named by an id the file stores, so it follows the file
when it is renamed or moved; a copy of the file gets a cache of its own. Opening the file
fills the cache from it and the file wins, except after a crash: chat work newer than
the last save is kept. Caches not used for 30 days are deleted. A deleted chat leaves the
file at the next save, so old chats do not keep it large. Files from before chats open
with their history as the first chat, and the `<name>.whittle` folders earlier versions
kept beside a file move into the hidden cache the first time it is opened.

`./gui_checks.sh` walks through most of these in a real Blender (GUI checks, below), and
[docs/progress.md](docs/progress.md) has a manual checklist for the rest.

## Privacy and safety

Whittle talks to Anthropic's API only, with your key, while the agent runs: a model
listing when it starts, then the turns. The bundled Claude Code CLI may also send
Anthropic its own usage telemetry and error reports; set
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` (or `DISABLE_TELEMETRY=1`) in Blender's
environment to turn that off. What a turn sends:

- your prompts, amendments and answers to Claude's questions, and the reference images
  you attach or pin;
- the sketch: the strokes with their types and positions, the camera of each view, and
  the overlay images of your strokes over the viewport;
- what Claude looks at while it works: scene information it asks for (object names,
  transforms, mesh statistics, materials, modifiers, node groups), the output and errors
  of the Python it runs, and the self-check renders it makes of the target;
- Whittle's system prompt and recipe skills, and the conversation so far.

Anthropic's handling of API data is set out in its
[privacy policy](https://www.anthropic.com/legal/privacy) and
[commercial terms](https://www.anthropic.com/legal/commercial-terms). Conversations are
also kept locally, in the chat cache and in the `.blend` when you save it, so a shared
`.blend` carries its chats (delete them from the chat menu first if that matters).

## Security

- **Claude runs Python as you.** The agent edits the scene by running Python inside your
  Blender, unsandboxed and without asking each time: it can do anything you can, such as
  read and write your files, start programs and reach the network. That is what lets it
  model, and it is also why what it reads matters.
- **Be careful with files you did not make.** Claude reads the scene (object, material
  and collection names), your reference images and, when you continue a chat, that chat's
  whole conversation. A `.blend` from someone else can carry chats too, and continuing
  one replays its conversation to Claude as if it were its own. Text planted in any of
  these could try to steer Claude. Start a **New Chat** on a file from elsewhere rather
  than continuing its chats, and do not run Whittle on files you do not trust.
- Blender's **Auto Run Python Scripts** setting does not cover Whittle: it only stops
  scripts stored in a file. Nothing Whittle stores in a file runs code by itself.
- Links in Claude's replies open only `http`, `https` and `mailto` addresses.

## Development

You need Blender 5.2 as `blender` on your `PATH`: `run_tests.sh`, `build.sh`,
`screens.sh` and `gui_checks.sh` run it from there.

- Make the dev venv `.venv/` at the repo root once, from Blender 5.2's own Python 3.14 (in
  Blender's folder, `5.2/python/bin/python3.14`, or a system Python 3.14 when your
  Blender uses that), and install the pinned lock exactly as the add-on does:

  ```sh
  PY=/path/to/blender-5.2/5.2/python/bin/python3.14
  "$PY" -I -m venv .venv
  .venv/bin/python -m pip install --isolated --disable-pip-version-check --no-input \
      --require-hashes --only-binary :all: --no-deps -r agent_env/requirements.lock
  ```

  Use `.venv/bin/python` for agent-side code. **Never install anything else into it**: no
  other packages, no upgrades.
- Point the add-on at it instead of setting up a private venv:

  ```sh
  export WHITTLE_AGENT_PYTHON="$PWD/.venv/bin/python"
  ```

  (or set **Development → Agent Python** in the preferences).
- Work on the source in place by symlinking the package into a local extensions repository:

  ```sh
  ln -s "$PWD/whittle" ~/.config/blender/5.2/extensions/user_default/whittle
  ```

  then enable Whittle in **Preferences → Add-ons** and restart Blender after code changes.
- To try the UI without the API (and without a key), turn on Preferences → Interface →
  **Developer Extras** and set the sidebar's **Development → Fake Script** to a script
  under `tests/fixtures/fake/` (e.g. `stream.json`, `ask.json`); Send then plays it.
- `whittle/requirements.lock` must stay a byte-identical copy of `agent_env/requirements.lock`;
  `build.sh` and a test check it.

Environment variables Whittle reads:

| Variable | What it does |
|---|---|
| `ANTHROPIC_API_KEY` | The API key, when the preference is empty (API key and cost). |
| `WHITTLE_AGENT_PYTHON` | The Python that runs the agent, over the preference and the private venv. |
| `WHITTLE_USER_DIR` | Whittle's user folder (chat caches, the venv, logs, the model list). Point it at a scratch folder to keep manual dev runs out of your real one. |
| `WHITTLE_LOG_LEVEL` | The agent's logging level (`INFO` by default; `DEBUG` for more). Its log is in the user folder's `logs/`. |
| `WHITTLE_INLINE_SKILLS` | `1` puts the recipe skills into the system prompt instead of loading them as a plugin. |
| `WHITTLE_LIVE` | `1` makes `run_tests.sh` run the live tests too (Tests). |
| `WHITTLE_SCREENS_VISIBLE` | `1` makes `screens.sh` show its windows on your desktop (Sidebar screenshots). |
| `WHITTLE_GUI` | `1` makes `run_tests.sh` run the GUI checks too (GUI checks). |
| `WHITTLE_GUI_VISIBLE` | `1` makes `gui_checks.sh` show its windows on your desktop (GUI checks). |


### Sidebar screenshots

```sh
./screens.sh                       # every scenario, about 1.5 minutes
./screens.sh conversation asking   # only these
```

`screens.sh` opens a real GUI Blender (`--factory-startup`, one at a time, each under a
120 s timeout, quitting by itself) per scenario in `tests/screens/catalog.py`. Each
scenario builds a scene, drives the fake agent through the add-on's own controller to a
state (a finished turn, a question, a turn mid-stream, a branched history, …) and the
harness crops the Whittle sidebar out of a screenshot, scrolling and stitching when the
panels are taller than the window. Results go to `build/screens/<scenario>.png`, plus
`build/screens/wide/conversation.png` with a 1.6× wider sidebar and `build/screens/index.json`
describing each image. The script exits non-zero if any image is missing; a failed
scenario's Blender log is in `build/screens-work/<scenario>/blender.log`. Blender's user
folders point into `build/screens-work/`, so the runs never touch your own preferences or
recent files. The windows open in a hidden, nested Wayland session (`kwin_wayland
--virtual`, KDE's compositor, started on first use and reused after), so nothing shows on
your desktop; without `kwin_wayland` the script stops and says so (use
`WHITTLE_SCREENS_VISIBLE=1` on other desktops). `WHITTLE_SCREENS_VISIBLE=1` shows
the windows on your desktop instead (without taking focus; they ignore real input while
they run).

### GUI checks

```sh
./gui_checks.sh                         # every check, about four minutes
./gui_checks.sh undo_turn blank_sketch  # only these
WHITTLE_GUI=1 ./run_tests.sh            # the whole suite, then every check
```

Some things only a GUI Blender does: a real Ctrl+Z (undo needs a window), the draw tool
placing strokes on surfaces, a transform's modal operator, the Asset Browser's context
menu, file browsers, Blender's autosave and File → Recover, the title bar's `*`.
`gui_checks.sh` runs each check in `tests/gui/catalog.py` in a real GUI Blender started
with `--enable-event-simulate`, in the same hidden nested session as `screens.sh`: the
check builds a scene, drives the add-on with the fake agent, sends the input under test
(a key, a drag of the draw tool, a right-click) as simulated events through Blender's own
event handling, and asserts what came of it. A check that needs a restart, a crash or
Blender's own recovery files runs one Blender per phase (a crash is a `kill -9` of
Blender itself), sharing a work folder. Blender's user folders, its temporary folder and
Whittle's user folder are the run's own, under `build/gui-checks/`, so nothing touches
your preferences, recent files or autosaves. The script exits non-zero if any check
failed; each phase's Blender log is in `build/gui-checks/<check>/phase-<n>.log`, and
`build/gui-checks/report.json` lists the results. `WHITTLE_GUI_VISIBLE=1` shows the
windows on your desktop instead (they ignore real input while they run).

## Tests

```sh
./run_tests.sh                 # the whole offline suite; add -v for verbose
./run_tests.sh -k test_start   # only tests whose name matches
WHITTLE_LIVE=1 ANTHROPIC_API_KEY=… ./run_tests.sh  # also the live tests
```

`run_tests.sh` runs the agent-side tests under `.venv/bin/python`, then the Blender-side tests
inside `blender -b --factory-startup`, each step under a `timeout`. Tests use the stdlib
`unittest` only (pytest is not installed) and a scripted fake agent, so the offline suite
needs no key, makes no network calls and never installs anything: the venv setup is
tested through its command construction, a fake process and a dry run.

With `-k`, each side runs only the tests whose name matches; a side where nothing matches
is skipped, and the script fails (exit code 5) only when no test matched on either side.
`WHITTLE_GUI=1` runs the GUI checks after both sides (GUI checks).

The live tests call the real API with `ANTHROPIC_API_KEY` (a few US cents per run, billed
to that key): they use `claude-haiku-5-5` with a tiny prompt, and `run_tests.sh` adds
`--online-mode` to Blender for them.

## Contributing

Issues and pull requests are welcome; [CONTRIBUTING.md](CONTRIBUTING.md) has the details.
Before you send a change, run `./run_tests.sh` (and `./screens.sh` for sidebar changes,
looking at the images), keep `README.md` and `docs/` in step with what you change, and
follow the supply-chain notes below: no new or upgraded dependencies without discussing
them first.

## Supply-chain notes

- Every dependency is pinned to an exact version with hashes, installed from wheels only and
  without dependency resolution. Nothing is ever upgraded automatically, and there are no
  `github:` or VCS references.
- The install only runs after you confirm the dialog, never during a turn (so the agent's own
  Python can never start one), and never from background Blender.
- The bundled Claude Code CLI is run as Anthropic ships it, unmodified.
- A change to `agent_env/requirements.lock` (or its packaged copy) in a diff that should not
  touch dependencies is a red flag: stop and look at it.
- Whittle never publishes anything.

## License

Whittle is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, either version 3
of the License, or (at your option) any later version. See [LICENSE](LICENSE).

It downloads and runs third-party packages under their own licenses, among them
Anthropic's Claude Agent SDK and the Claude Code CLI it bundles, whose use is governed by
[Anthropic's Commercial Terms of Service](https://www.anthropic.com/legal/commercial-terms).
"Claude" and "Anthropic" are trademarks of Anthropic, PBC.
