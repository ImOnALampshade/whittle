# Development setup and testing

How to run Whittle from a checkout, and what each script in the repo root does. You don't
need an API key for any of it except the [live tests](#live-tests): everything else runs
against a scripted fake agent. {doc}`architecture` explains the processes these tools
exercise.

| Command | What it does |
|---|---|
| `./run_tests.sh` | The offline suite: agent side in `.venv`, then Blender side in `blender -b` |
| `./gui_checks.sh` | Flows only a GUI Blender shows, in hidden Blenders (about 4 minutes) |
| `./screens.sh` | Sidebar screenshots into `build/screens/`, for review (several minutes) |
| `./docs.sh` | This site, into `build/docs/html` |
| `./docs_shots.sh` | This site's screenshots, into `docs/site/images/` |
| `./build.sh` | Validates the extension and builds its zip |

Before you send a change:

| You changed | Run |
|---|---|
| Anything | `./run_tests.sh` |
| How the sidebar looks | `./screens.sh` for the affected scenarios, and look at the images. `./screens.sh --docs` too if the README shows it |
| Sketching, undo, start points, saving, the preferences, or anything else in `tests/gui/catalog.py` | `./gui_checks.sh` |
| This site | `./docs.sh --strict`, and `./docs_shots.sh` for a page whose pictures are out of date |

## What you need

- Blender 5.2 as `blender` on your `PATH`. `run_tests.sh`, `build.sh`, `screens.sh`,
  `gui_checks.sh` and `docs_shots.sh` all run it from there.
- GNU `timeout`: the scripts are POSIX shell and bound every step with it. On a Mac,
  `brew install coreutils` provides it. On Windows, run the commands the scripts contain
  by hand; the dev venv's Python is `.venv\Scripts\python.exe` there.
- Linux with KDE's `kwin_wayland` for `screens.sh`, `gui_checks.sh` and `docs_shots.sh`.
  They open their Blenders in a hidden nested Wayland session and stop with a message when
  they can't have one.

## The dev venv

Make `.venv/` at the repo root once, from Blender 5.2's own Python (in Blender's folder,
`5.2/python/bin/python3.13` in blender.org's builds, or a system Python 3.14 when your
Blender uses that), and install the lock exactly as the add-on does:

```sh
PY=/path/to/blender-5.2/5.2/python/bin/python3.13
"$PY" -I -m venv .venv
.venv/bin/python -m pip install --isolated --disable-pip-version-check --no-input \
    --no-cache-dir --index-url https://pypi.org/simple \
    --require-hashes --only-binary :all: --no-deps -r agent_env/requirements.lock
```

Install nothing else into it: no other packages, no upgrades. It has to stay what the
private venv would be, the one the add-on's setup builds for a user in Whittle's user folder
({doc}`../guides/installation`), or the tests stop saying anything about that venv. A
dependency change is a change of its own, with the maintainer's approval
(`CONTRIBUTING.md`, Dependencies).

Then point the add-on at it, so it doesn't set up a private venv:

```sh
export WHITTLE_AGENT_PYTHON="$PWD/.venv/bin/python"
```

**Development → Agent Python** in Whittle's preferences does the same. The add-on takes the
first of these that is an existing file: the variable, the preference, then the private
venv.

## Running the source in Blender

Symlink the package into a local extensions repository:

```sh
ln -s "$PWD/whittle" ~/.config/blender/5.2/extensions/user_default/whittle
```

Enable Whittle in **Preferences → Add-ons**, and restart Blender after a code change. This
is your own Blender, so point `WHITTLE_USER_DIR` at a scratch folder to keep chat caches and
logs out of your real Whittle folder.

Whittle reads these variables:

| Variable | What it does |
|---|---|
| `ANTHROPIC_API_KEY` | The API key, when the preference is empty ({doc}`../guides/api-key`) |
| `WHITTLE_AGENT_PYTHON` | The Python that runs the agent, over the preference and the private venv |
| `WHITTLE_USER_DIR` | Whittle's user folder: chat caches, the venv, logs, the model list |
| `WHITTLE_LOG_LEVEL` | The agent's logging level, `INFO` by default. Its log is in the user folder's `logs/` |
| `WHITTLE_INLINE_SKILLS` | `1` puts the recipe skills into the system prompt instead of loading them as a plugin |

The scripts read these:

| Variable | What it does |
|---|---|
| `WHITTLE_LIVE` | `1` makes `run_tests.sh` run the live tests too |
| `WHITTLE_GUI` | `1` makes `run_tests.sh` run the GUI checks after both sides |
| `WHITTLE_GUI_VISIBLE` | `1` shows `gui_checks.sh`'s windows on your desktop |
| `WHITTLE_SCREENS_VISIBLE` | `1` shows `screens.sh`'s windows on your desktop |
| `WHITTLE_DOCSHOTS_SLOTS` | How many Blenders `docs_shots.sh` runs at once across the machine |
| `WHITTLE_DOCSHOTS_SLOT_WAIT` | How many seconds one waits for a slot, 3600 by default |

## The fake agent

`whittle/agent/fake.py` plays a JSON script through the real process, socket, handshake and
Blender handlers. It costs nothing and needs no key and no online access, only an agent
Python. The tests, the GUI checks and the screenshots all run on it, and you can use it by
hand to try the UI:

1. Turn on **Preferences → Interface → Display → Developer Extras**.
2. Open the sidebar's **Development** panel, which starts closed.
3. Pick a script in `tests/fixtures/fake/` with the folder button beside **Fake Script**,
   such as `stream.json` or `ask.json`. A typed relative path starts from the folder Blender
   runs in.
4. Type a prompt and press Send.

:::{figure} ../images/develop-setup-and-testing/developer-extras.png
:alt: The Display panel of Blender's Interface preferences, with the Developer Extras checkbox under Splash Screen.

Developer Extras adds a Development panel to the sidebar.
:::

:::{figure} ../images/develop-setup-and-testing/development-panel.png
:alt: The Whittle sidebar after one turn. Below the prompt box, the open Development panel shows the last sent bundle, the Fake Script and Bundle fields, Run Bundle, Start Agent and Stop Agent.

A turn played from `stream.json`, with the Development panel open below the prompt box. The
Fake Script path is shortened here; yours is absolute.
:::

The panel also has **Bundle** and **Run Bundle**, which send a folder from disk to the agent
as a [request bundle](protocol.md#the-request-bundle), everything the agent gets for one
turn, and **Start Agent** and **Stop Agent**. When the agent has crashed or failed it shows
the end of the agent's log.

Fake Script and Bundle live on the window manager, so no `.blend` carries them. A script's
`call` steps run whatever Python they hold, so one that came with a shared file would run
on Send. Treat a script as code.

A script is `{"turns": [{"steps": [...], "finish": {...}}]}`, and each submit plays the
next turn:

```json
{
  "turns": [
    {
      "steps": [
        {"say": "Adding a lid."},
        {"call": "exec", "params": {"label": "add lid", "code": "print('lid')"}, "expect": "ok"},
        {"ask": "Bevel the edges?", "choices": ["Yes", "No"]}
      ],
      "finish": {"subtype": "success", "is_error": false, "result": "Added a lid."}
    }
  ]
}
```

A `call` is a real bridge call, so any agent-to-Blender method works: `exec`, `inspect`,
`render`, `checkpoint`, `restore_checkpoint` or `ask`. `expect` can also be `error:<code>`.
Other steps sleep, wait for an amendment, end the session or crash the process. `finish` can
also give the turn's `cost` in USD, 0 by default, so a turn shows a cost at no charge. The
`whittle.agent.fake` entry in {doc}`../reference/agent` has them all, and
`tests/fixtures/fake/` has a script for most situations.

## The test suite

```sh
./run_tests.sh                 # the whole offline suite; add -v for verbose
./run_tests.sh -k test_start   # only tests whose id matches, on either side
WHITTLE_GUI=1 ./run_tests.sh   # the suite, then every GUI check
```

It runs two sides in turn, each under a `timeout`:

- **Agent side**, `tests/agent/`, under `.venv/bin/python` for up to 5 minutes. No Blender:
  `tests/agent/fakes.py` has `FakeBlender`, an in-process server speaking the bridge
  protocol, and `FakeSdkClient`, which yields real `claude_agent_sdk` messages from a script.
- **Blender side**, `tests/blender/`, inside `blender -b --factory-startup` for up to 15
  minutes, through `tests/blender/run.py`. Tests that need an agent spawn the fake one.

Tests use the stdlib `unittest`; pytest isn't installed. `bpy.app.timers` never fire under
`-b`, so Blender tests call `Bridge.tick()` themselves, with `pump(controller, until,
timeout, what)` from `tests/blender/helpers.py`, which fails the test at its deadline.
Derive a test from `AgentTestCase` in the same file for a temp user folder and a clean-up of
any agent it started, or wrap it in `TempUserDir` for the folder alone.

`-k` matches anywhere in a test's id, so a module's name selects the module. A side where
nothing matches exits 5 and is skipped, and the script fails with 5 only when neither side
matched.

To run one Blender test without the script:

```sh
timeout 900 blender -b --factory-startup --python tests/blender/run.py -- -k test_start
```

{doc}`extending` says where the tests for each kind of change go.

## GUI checks

```sh
./gui_checks.sh                         # every check
./gui_checks.sh undo_turn blank_sketch  # only these
```

Some things only a GUI Blender does: a real Ctrl+Z, the draw tool placing strokes on
surfaces, a transform's modal operator, file browsers, the Asset Browser's context menu,
autosave and File → Recover, the title bar's `*`, the Preferences window.
`tests/gui/catalog.py` says what each check confirms, and `tests/gui/checks.py` drives it.

The run builds the zip with `build.sh` and installs it with `blender --command extension
install-file` into a local repository of its own, `build/gui-checks/gui_checks/`, so every
check runs the installed extension as a user would. Each check runs one GUI Blender per
phase, started with `--enable-event-simulate`, and sends its input as simulated events
through Blender's own event handling. A check that needs a restart, a crash or Blender's
recovery files takes several phases in one work folder; a crash is a `kill -9` of that
Blender. `tests/gui/spy.py` records what Blender's own redraws drew, which is how the
preference checks assert on the Preferences, the sidebar and the popovers.

The agent is the fake one, API keys are fake, and Blender runs offline. Blender's user
folders, its temporary folder and Whittle's user folder are the run's own under
`build/gui-checks/`. The harness refuses to run if Blender's config folder isn't the run's,
or if Whittle wasn't loaded from the run's repository.

The script exits non-zero if any check failed. Look in:

- `build/gui-checks/report.json`: the results.
- `build/gui-checks/<check>/phase-<n>.log`: each phase's Blender log.
- Beside the logs: screenshots from the preference checks.

## Sidebar screenshots

```sh
./screens.sh                       # every scenario
./screens.sh conversation asking   # only these
./screens.sh --docs                # the README's images, into docs/images/
```

`screens.sh` is how a UI change gets reviewed. It runs one real GUI Blender per scenario in
`tests/screens/catalog.py`, one at a time and each under a 120 s timeout. A scenario builds a
scene and drives the fake agent to a state; the harness then crops the sidebar out of a
screenshot, scrolling and stitching when the panels are taller than the window.

Results go to `build/screens/<scenario>.png`, with `build/screens/wide/` for the wider
sidebar of `conversation`, `markdown` and `long_session`, and `build/screens/index.json`
describing each image. A failed scenario's log is
`build/screens-work/<scenario>/blender.log`.

The README's images are committed under `docs/images/`. Regenerate them with `--docs` after
a change to what they show, and look at each before you commit it.

## Hidden windows

`gui_checks.sh`, `screens.sh` and `docs_shots.sh` never open a window on your desktop:
their Blenders run in a nested session from `kwin_wayland --virtual`. The first two share
one session, started on first use and left running for the next run. `docs_shots.sh` gives
each Blender a session of its own.

`WHITTLE_GUI_VISIBLE=1` and `WHITTLE_SCREENS_VISIBLE=1` show the windows instead, for when
you want to watch a run or don't have `kwin_wayland`. The windows ignore real input while
they run. `docs_shots.sh` has no such switch.

## This site

The site's source is `docs/site/`: one MyST page per doc, `conf.py`, and the API reference
that autodoc builds from the docstrings. It has a venv of its own, `.venv-docs/`, kept
apart from `.venv` so nothing it needs reaches the agent's environment or the zip. Make it
once from Python 3.13 or 3.14:

```sh
python3 -m venv .venv-docs
.venv-docs/bin/pip install --require-hashes --only-binary :all: --no-deps -r docs/site/requirements.lock
```

`docs.sh` prints these commands if the venv is missing. Only `docs.sh` uses it:
`docs_shots.sh` and the tests run from the [dev venv](#the-dev-venv), `.venv`, so make that
too.

```sh
./docs.sh                  # into build/docs/html
./docs.sh --strict         # warnings are errors, and every page is rebuilt
./docs.sh --out DIR        # DIR/html and DIR/doctrees, for builds running at once
```

A build needs no Blender and no network: the source's imports are mocked. Use `--strict`
before you send a change, because an incremental build doesn't repeat an unchanged page's
warnings. `./run_tests.sh -k test_docs_site` checks what the source promises without
building it: every module is in the reference, every page is in a toctree, and every image
exists.

You don't publish the site: [CI](#ci-and-releases) does, from `main`.

### Its screenshots

```sh
./docs_shots.sh <page-slug> [shot ...]   # a page, or some of its shots
./docs_shots.sh --all                    # every page
./docs_shots.sh --list                   # every shot; launches nothing
./docs_shots.sh --check                  # validates every spec; launches nothing
./docs_shots.sh --keep <page-slug>       # keeps the run's folder after a success
```

A page's slug is its doc name with `/` replaced by `-`, so `guides/api-key` is
`guides-api-key`. Its spec is `docs/site/shots/<page-slug>.py`, and its images land in
`docs/site/images/<page-slug>/<shot>.png`. A test fails if a spec's shot isn't shown on its
page. Specs named `_*` are examples: `--all` leaves them out, and their images go to
`build/docs-shots/images/`. `docs/site/shots/README.md` is the guide to writing a spec, and
`docs/site/shots/_example.py` has one of everything.

Unlike `screens.sh`, each shot runs Whittle installed as an extension, built from `whittle/`
once per change to it. Run as many at once as you like: a machine-wide queue lets a few
Blenders run at a time, so a queued run can wait for minutes. A shot's Blender and Whittle
folders are its run's own under `build/docs-shots/`. Each Blender and its compositor hold GPU
memory, so raise `WHITTLE_DOCSHOTS_SLOTS` only if the card has room: when it runs out, sessions
fail to start and Blender reports `EGL_BAD_ALLOC`.

Re-shooting gives the same pixels and then leaves the image alone, so a changed image in
`git status` means a changed picture. A failed shot exits non-zero, keeps the old image and
prints its log's path; the run's folder under `build/docs-shots/` is kept. Look at every
image you make, and keep this machine's paths out of them: the shots guide says how.

## Building the zip

```sh
./build.sh         # build/whittle-<version>.zip
./build.sh DIR     # into DIR
```

It validates the extension and builds one zip for every platform, since the zip carries no
wheels ({doc}`../guides/installation`). It refuses to build when
`whittle/requirements.lock` differs from `agent_env/requirements.lock`, or `whittle/LICENSE`
from `LICENSE`. It never copies them for you: a difference is something to look at.

## CI and releases

GitHub Actions runs on GitHub's free standard runners and needs no secrets. `ci.yml` runs on
pushes to `main` and `ci/**` and on pull requests; `release.yml` runs on tags. Both call
`test.yml`, which downloads a pinned Blender (`.github/scripts/fetch_blender.py` checks its
SHA-256 before unpacking it), makes `.venv` from Blender's Python, installs the lock, and
runs `./run_tests.sh` and `./build.sh`. The GUI checks and the screenshots are not part of
CI, because they need `kwin_wayland`.

`docs.yml` publishes this site to <https://imonalampshade.github.io/whittle/>. On a push to
`main` that changes what the site is built from, or when started by hand, it makes `.venv-docs`
from the lock and runs `./docs.sh --strict`, so a warning fails the run, and a second job
deploys the result to GitHub Pages. A push to `ci/**` touching those paths builds without
deploying, which is how to try a change to the workflow. Nothing waits for it: a failure leaves
the site as it was until the next good build, and holds back neither CI nor a release. The site
follows `main`, so it can describe things newer than the latest release. The repository's Pages
source must be GitHub Actions, set once in Settings → Pages → Build and deployment before
`docs.yml` first reaches `main`. If that push comes first, its deploy job fails and the setting
starts nothing, so start `docs.yml` by hand on `main` afterwards.

Linux x64 (`ubuntu-latest`) is the gate. Windows x64 and macOS on Apple silicon run too, but
their failures count for nothing yet, and a release does not wait for them. Linux arm64 has
no CI, because blender.org publishes no build for it. [Platforms](../guides/installation.md#platforms)
says how far each one has got.

To cut a release, set `version` in `whittle/blender_manifest.toml`, merge that to `main`, then
tag that commit with `v` plus the version and push the tag:

```sh
git tag v0.2.0
git push origin v0.2.0
```

The tag must match the manifest, or the release stops at once. When the tests pass,
`whittle-<version>.zip` and its `.sha256` are attached to a new GitHub Release. A tag with a
hyphen, such as `v0.2.0-rc1`, publishes a prerelease of the manifest's `0.2.0`.

## Live tests

`tests/blender/test_live.py` calls the real API, so it is opt-in and costs a few US cents a
run, billed to the key you give it:

```sh
WHITTLE_LIVE=1 ANTHROPIC_API_KEY=… ./run_tests.sh -k test_live
```

Without `-k` that runs the whole suite as well. They skip without `WHITTLE_LIVE=1`, without
a key, or when Blender has no online access; `run_tests.sh` adds `--online-mode` for them.
They use `claude-haiku-5-5`, tiny prompts and a 10 cent budget per turn, and check what the
fake agent can't: a real tool call reaching Blender, an amendment reaching the agent, and a
branch forking at the right message. Run them when a change touches how the real agent is
started or spoken to, not as a routine.

## Rules for tests

- **Offline by default.** The suite makes no API calls, needs no key and installs nothing.
  The venv setup is tested through its command construction, a fake process and a dry run.
  Real API calls belong only in the live tests.
- **Your machine stays yours.** Tests never touch your Blender config or Whittle folder.
  Blender tests run with `--factory-startup`, and a test that touches Whittle's user folder
  gets a fresh one from `AgentTestCase` or `TempUserDir`. GUI runs point the `BLENDER_USER_*`
  folders under `build/`.
- **No windows.** GUI Blender runs use the [hidden session](#hidden-windows).
- **Everything is time-bounded.** Every wait has a deadline and every subprocess a timeout.
  No test may hang, and anything you add to a script goes under `timeout`.
- **The locks stay put.** `whittle/requirements.lock` is byte-identical to
  `agent_env/requirements.lock`; `build.sh` and a test check it. An unexpected change to
  either in a diff is a red flag: stop and find out why.
- **No key in logs.** The key goes only to Blender's preferences and the agent's
  environment. `tests/blender/test_auth.py` checks the agent's log and Whittle's user folder
  for it ({doc}`../guides/privacy`).
