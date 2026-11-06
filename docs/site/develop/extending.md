# Extending Whittle

Recipes for the common changes. Each lists every place the change touches, in the order
to make them, and says which test notices a step you missed. They assume you have read the
[Architecture overview](architecture.md) and have a working checkout
([Development setup and testing](setup-and-testing.md)). The modules named here are in the
[Add-on](../reference/addon.md), [Agent](../reference/agent.md) and
[Shared modules](../reference/shared.md) API reference.

Some rules hold for all of them:

- **The process boundary.** `whittle/addon/` may import `bpy`, and never imports
  `whittle.agent`. `whittle/agent/` never imports `bpy`, and only `agent/runner.py` imports
  `claude_agent_sdk` at module level (`agent/tools.py` imports it inside `build_servers`).
  The shared `whittle/*.py` modules use the stdlib only at module level. Imports are
  relative, because inside Blender the package is `bl_ext.<repo>.whittle`.
- **The main thread.** All `bpy` access happens on Blender's main thread, from the bridge
  tick or an operator.
- **Docs change with the code.** Update `README.md`, `docs/architecture.md`, `docs/ui.md`,
  `docs/decisions.md` and `docs/progress.md` in the same change, wherever they say what you
  changed.
- **No new packages on the way past.** Adding, upgrading or removing a dependency needs the
  maintainer's approval and a change of its own.
- New source files start with `# SPDX-License-Identifier: GPL-3.0-or-later`.

## A tool for the agent

A tool has an agent side, which the model calls, and usually a Blender side, which runs on
the main thread. The two meet at a bridge method. The steps below add a made-up `measure`
tool, the distance between two objects. The existing tools are listed in
[Agent tools and skills](agent-tools.md), and the bridge is described in
[Protocol and file formats](protocol.md).

1. **Name the method.** Add it to `protocol.Method`, under the agent to Blender calls:

   ```python
   MEASURE = "measure"
   ```

   A tool that needs nothing from Blender skips this step and the next. `request` is one: it
   reads the turn's bundle from disk.

2. **Handle it in Blender.** Write the handler in `addon/commands.py` and add it to
   `build_handlers`:

   ```python
   def handle_measure(ctx: CommandContext, params: dict) -> dict:
       names = require(params, "a", str), require(params, "b", str)
       found = [bpy.data.objects.get(name) for name in names]
       if None in found:
           raise BridgeError(ErrorCode.NOT_FOUND, f"no object among {names}")
       a, b = found
       distance = (a.matrix_world.translation - b.matrix_world.translation).length
       return {"distance": distance, "notes": ctx.take_notes()}
   ```

   ```python
   Method.MEASURE: lambda p: handle_measure(ctx, p),
   ```

   `require` checks a parameter and raises `bad_request`. A handler returns plain JSON data,
   raises `BridgeError`, or returns a `Deferred` when the answer comes later, as `ask` does.
   It runs on the main thread and cannot be pre-empted, so keep it short.

   Two sets in `addon/bridge.py` decide how the queue treats a method. Add a method that
   changes the scene to `SCENE_METHODS`, so it waits while the user is in a modal operation,
   for at most `MODAL_WAIT` (10 seconds). Add a slow one to `SLOW_METHODS`, so the tick ends
   after it and at most one runs per tick.

   A handler that edits the scene starts as `handle_exec` does, with `ctx.before_edit()` and
   then `ctx.edits += 1`. The first makes the turn's undo step land before the edit (see
   [Undo](../guides/undo.md)). The count is how the turn knows the scene may have changed:
   without it, Ctrl+Z during the turn skips the turn's start, and a failed turn whose only
   edits came from this tool folds into its parent as if it had changed nothing.

3. **Write the agent handler.** In `agent/tools.py` a handler is an async function of
   `(ctx, args)`, so tests can call it without the SDK:

   ```python
   async def measure_tool(ctx: ToolContext, args: dict) -> dict:
       try:
           data = await ctx.connection.call(Method.MEASURE, {"a": args["a"], "b": args["b"]})
       except BridgeCallError as exc:
           return error_result(exc)
       text = f"{data['distance']:.4f} m"
       text += "".join(f"\nnote: {note}" for note in data.get("notes") or [])
       return {"content": [text_block(text)]}
   ```

   `connection.call` gives up after 300 seconds by default. `exec`,
   `restore_checkpoint` and `ask` pass `timeout=None`, because Blender cannot stop running
   code and a person may take a while to answer.

4. **Declare it.** Add an entry to `TOOLS` in `agent/tools.py`:

   ```python
   "measure": ("blender", measure_tool, DESCRIPTION,
               {"type": "object",
                "properties": {"a": {"type": "string", "description": "One object's name."},
                               "b": {"type": "string", "description": "The other's."}},
                "required": ["a", "b"]}, False),
   ```

   The tuple is the server (`blender` or `whittle`), the handler, the description, the JSON
   schema, and whether the tool returns images. `True` raises the result size limit, so the
   images stay inline. `TOOL_NAMES`, the SDK's allowed tools and `build_servers` all follow
   from this table; there is nothing else to register.

5. **Write the description for the model.** Follow `docs/prompting.md`: a short man page
   saying what the tool does, when it fits, what each parameter means and what it returns,
   with shapes enforced in the schema and errors that say what to change.
   `test_tools_are_documented_for_the_model` wants a few sentences, a description on every
   property, and no field asking for the model's reasoning.

6. **Title it in the sidebar, if it helps.** `stream.tool_title` makes a call's row. An
   unknown tool shows its name and any `label` in its input, so give it a branch there if a
   parameter says more.

7. **Test both sides.** `test_tool_names` in `tests/agent/test_tools.py` lists the tools by
   hand, so it fails until you add yours. Test the agent handler there with a
   `StubConnection`, and the Blender handler in `tests/blender/`.

8. **Update the docs.** Add the method to `docs/architecture.md` §3 and the tool to the table
   in §5.

A `call` step in a fake script reaches the Blender handler directly and skips `agent/tools.py`,
so it is the quick way to try step 2 in a real Blender. Nothing here needs an API key:

```json
{
  "turns": [
    {"steps": [{"say": "Checking the scene."},
               {"call": "inspect", "params": {"query": "summary"}, "expect": "ok"},
               {"say": "The crate is the only object here."}],
     "finish": {"subtype": "success", "is_error": false, "result": "The crate is the only object here."}}
  ]
}
```

Turn on **Developer Extras** in Blender's preferences and point the sidebar's
**Development → Fake Script** at the file. The next Send plays it.

```{figure} ../images/develop-extending/development-panel.png
:alt: The sidebar after a finished turn, with the Development panel open at the bottom: the last sent bundle, the Fake Script and Bundle fields, Run Bundle, Start Agent and Stop Agent

The Development panel, shown only with Developer Extras on.
```

```{figure} ../images/develop-extending/fake-call.png
:alt: A turn in the sidebar with its tool group opened: the row "inspect · summary" with a check mark, then the call's input as JSON and the start of its result

That script's call, opened. A call shows its title, its input as JSON and its result.
```

## A skill

A skill is a recipe the agent loads when it needs a technique: working code plus the
pitfalls. The agent has no Read tool, so a skill has to be self-contained.

1. **Write `whittle/agent/plugin/skills/<name>/SKILL.md`.** The frontmatter is simple
   `key: value` lines, each on one line. `name` matches the folder. `description` says what
   the skill does and when to use it, in the words a request would use:

   ```text
   ---
   name: bevel-crease
   description: Bevels hard-surface edges and turns strokes along an edge into bevelled or sharp edges ... Use when a stroke marks a hard edge, for prompts about bevels, chamfers ...
   ---
   ```

   `docs/prompting.md` has the rest: exact code for fragile operations, one default with an
   escape hatch rather than a menu, and no standing rules that repeat the system prompt.

2. **Register it.** Add the name to `SKILLS` in `agent/prompt.py`. That lists the skill in the
   system prompt, enables it for the session and puts it in the inline fallback.

3. **Make every block run.** `test_every_recipe_block_runs` runs each `python` block of each
   skill, in order, in a fresh crate scene, with the same namespace `exec` gives the agent:
   `bpy`, `bmesh`, `mathutils`, `math`, `Vector`, `Matrix` and `whittle`. A block must finish
   without an error and print something, so end each one with a `print`. Later blocks of a
   skill see what earlier ones left, in the scene and in the namespace.

4. **Check it and update the docs.** `test_every_skill_has_matching_frontmatter` wants the
   folders and `SKILLS` to agree, a description of more than 40 characters and at least one
   `python` block. Add the name to the Recipe skills list in `docs/architecture.md` §1. A skill
   that carries modeling practice also belongs in `docs/modeling-practices.md`.

```sh
./run_tests.sh -k test_every_skill_has_matching_frontmatter
./run_tests.sh -k test_every_recipe_block_runs
```

## A sidebar state

`docs/ui.md` is the sidebar's spec, so a new state starts there. Sidebar changes are reviewed
on screenshots as well as tests.

1. **Spec it.** Add the state and its mockup to `docs/ui.md` §4, and its check to the table
   in §10. A new part of the sidebar also gets its own section in §3.

2. **Draw it.** Draw code in `addon/ui.py` is plain functions taking a layout, called in
   order from `draw_main`; the conversation's own model is in `addon/conversation.py`. A draw
   function reads what it needs from `Ctx` and never writes Blender data. A button that does
   something is an operator, in `addon/operators.py` and its `CLASSES`. An operator that
   changes the scene needs a deliberate undo story (`docs/ui.md` §8).

3. **Test the layout.** In `tests/blender/test_sidebar.py`, `AddonTestCase.draw` runs
   `draw_main` into a `RecordingLayout`, and `fake_controller` stands in for the turn
   controller, so a test can put the panel in any state without an agent:

   ```python
   def test_question_is_shown_once(self):
       question = {"question": "Should the lid overhang?", "choices": ["Yes", "No"]}
       ctl = fake_controller(AgentState.BUSY, running=True, phase="waiting_user", question=question)
       layout = self.draw(ctl)
       self.assertEqual(len([t for t in layout.labels() if "Should the lid" in t]), 1)
   ```

4. **Add a scenario.** Write a function in `tests/screens/scenarios.py` that reaches the state
   through the add-on's own controller and the fake agent. `asking` is a short one:

   ```python
   @scenario
   def asking(stage: Stage):
       stage.crate()
       script = stage.script("asking", [{"steps": [
           say("Adding the lid first."),
           exec_("add lid", LID),
           {"ask": "Should the lid overhang the crate by 1 cm, or sit flush with its sides?",
            "choices": ["Overhang", "Flush"]},
           say("Going with that."),
       ]}])
       stage.submit("Add a lid to the crate.", script)
       yield Until(lambda: stage.ctl.question is not None, "the question")
   ```

   Describe it in one line in `tests/screens/catalog.py`. `test_every_scenario_is_described`
   fails if the two lists differ.

5. **Look at it.** Run `./screens.sh <scenario>` and read the image against its row in
   `docs/ui.md` §10 and the general checks under that table: no text cut by Blender's own
   `...` at 280 px, nothing said twice, and red only in the failure scenarios. If the
   change alters what the README shows, refresh its images with `./screens.sh --docs`.

```{figure} ../images/develop-extending/asking.png
:alt: The sidebar paused on a question from Claude, with the buttons Overhang and Flush, and Stop in place of Send

What the `asking` scenario above produces.
```

```{figure} ../images/develop-extending/sketching.png
:alt: The sidebar in sketch mode: Sketch pressed with Capture View beside it, the stroke count and the list of two views

The `sketching` scenario, another sidebar state: Capture View shows only while sketching.
```

## A GUI check

Background tests cannot reach some things: a real Ctrl+Z, the draw tool, a modal transform, a
file browser, File → Recover, a crash, the Preferences. A GUI check runs those in a real,
hidden Blender with simulated input. Use one only when a `blender -b` test cannot do the job.

1. **Describe it.** Add a `Check` to `CHECKS` in `tests/gui/catalog.py`, saying what it
   confirms. A check has one phase by default. Each phase is one Blender, with a deadline of 90
   seconds unless it sets its own. A check that needs a restart or a crash has more:

   ```python
   "my_check": Check(
       "Save after a turn and reopen: the conversation is the saved one.",
       (Phase(), Phase(open="scene.blend"))),
   ```

   The first phase opens `base.blend`, a copy of the factory startup file. A later phase may
   open what an earlier one saved.

2. **Write the phases.** In `tests/gui/checks.py`, a phase is a generator over a `GuiStage`,
   added with `@phase`, one per `Phase` and in order:

   ```python
   @phase("undo_turn")
   def undo_turn(stage: GuiStage):
       ...
       node = stage.submit("Move the crate.", script)
       yield Until(lambda: stage.tools("ok"), "the agent's first call")
       yield from stage.press("Z", ctrl=True)
       yield from stage.settle()
       expect_equal((crate_x(), crate_y()), start, "the crate after Ctrl+Z (exactly the turn's start)")
   ```

   A phase reaches its state through the add-on's controller and operators, as a scenario
   does, and sends only the input under test as events, with `press`, `click`, `drag`
   and `type_text`. `button` is not an event: it runs an operator as a sidebar button does,
   invoked in that region with an undo step, because Blender has no Python API for where a
   button is drawn. A phase yields a number of seconds to wait, or an `Until`, whose default
   limit is 20 seconds. `expect` and `expect_equal` assert. Phases of a check share a
   work folder: `stage.remember(key=value)` and `stage.recall("key")` carry small values
   between them. A phase that returns `KILL` ends its Blender with `kill -9`.

3. **Run it.**

   ```sh
   ./gui_checks.sh my_check
   ```

   The script builds and installs the extension first, so the check runs what a user would.
   Each phase's log is at `build/gui-checks/<check>/phase-<n>.log`, and the results are in
   `build/gui-checks/report.json`.

4. **Update the lists.** `test_every_check_has_its_phases` needs the catalog and the phases
   to agree, and `test_the_first_phase_opens_the_startup_file` guards the first phase. Add the
   check to the list and the count in `docs/progress.md`, and to the README's GUI checks if it
   covers something new.

## A preference

A preference is either a plain add-on setting or a session setting, which reaches the agent and
can differ per file. There is nothing between the two: `prefs.session_settings()`, which is what
`start_session` carries, reads only the keys in `prefs.SESSION_SETTINGS`, and every one of those
has a per-file override. A preference left out of that tuple never reaches the agent, and
`prompt.build` uses its own default whatever the user set. The current preferences are in
[Settings](../guides/settings.md).

**Every preference**, in `addon/prefs.py`:

1. Add the default to `DEFAULTS`. `prefs.get()` reads only the keys listed there, and falls
   back to these values while the add-on is not registered.
2. Add the property to `WhittlePreferences`, taking its default from `DEFAULTS`.
   `test_rna_defaults_match_defaults` compares the two.
3. Show it: `WhittlePreferences.draw` lays out each box by hand.
4. Test it in `tests/blender/test_prefs.py`, and add it to the README.

**A session setting**, which the agent's system prompt uses, also needs all of these:

5. Its key in `prefs.SESSION_SETTINGS`, whose order is the order of the For This File fields,
   and its rows in `LABELS` and `DESCRIPTIONS`, plus `LIMITS` for an integer. Use those in the
   property of step 2 rather than repeating them.
6. A property on `WhittleSceneProps` in `addon/props.py`, which is written by hand:

   ```python
   palette: StringProperty(
       name="Palette", **_file_setting("palette"), description=_file_description("palette"))
   ```

   `test_every_session_setting_has_an_override` fails without it.
7. For a text field, its key in `OWN_LINE_SETTINGS` in `addon/ui.py`, so it gets a line of its
   own under its label.
8. The same default in `DEFAULTS` in `agent/prompt.py`, which `test_agent_side_defaults_agree`
   compares with the add-on's.
9. Its substitution in `prompt.build`, which passes each key by name, and a `$name` in
   `agent/system_prompt.md`.
10. Its type in `dispatch.session_params`, which checks each setting `start_session` carries.
11. Tests in `tests/blender/test_file_settings.py`.

The rest follows from `SESSION_SETTINGS`: `props.FILE_SETTINGS`, the popover's field and reset
button, `prefs.session_settings()`, and the agent's restart before the next turn when a value
changes.

A value the agent needs that must not differ per file needs a route of its own. The chat's model
and effort are `start_session` parameters of their own, and `usage_data` goes into the agent's
environment through `process.agent_environment`.

```{figure} ../images/develop-extending/preferences-defaults.png
:alt: The Defaults box: Triangle Budget 2000, Self-check Rounds 3 and Render Size 512 in one row, then the Palette, Bevel Style and Style Notes fields

The Defaults box in the preferences, drawn by hand in `WhittlePreferences.draw`.
```

```{figure} ../images/develop-extending/agent-popover.png
:alt: The agent popover: the agent's state, model and effort, then For This File, where Triangle Budget and Render Size say (default) and the other four settings have values, each with a reset button

For This File in the agent popover, drawn from `props.FILE_SETTINGS`. An unset field says
(default), and its reset button is greyed out.
```

## Something platform-specific

Whatever differs by platform lives in `whittle/platforms.py` and takes the platform as an
argument, defaulting to `sys.platform`. That lets the Linux suite run the Windows branches.
Route these through it instead of calling the OS directly:

| To do this | Use |
|---|---|
| Start a helper process without a console window | `hidden_window()`, as `Popen` keywords |
| Start a process you need to stop with its children | `own_group()`, then `ProcessTree(popen)` |
| Stop that process and everything it started | `ProcessTree`: `terminate`, `kill`, `close` |
| Ask whether a process lives | `pid_alive(pid)` |
| Replace a file atomically | `replace(src, dst)` |
| Clean up what a killed agent left | `note_agent`, `forget_agent`, `live_agent_starts`, `clear_stale_resume_folders` |

To add a branch:

1. **Take the platform as a keyword with a default**, and test it with `is_windows(platform)`:

   ```python
   def hidden_window(platform: str = sys.platform) -> dict:
       return {"creationflags": CREATE_NO_WINDOW} if is_windows(platform) else {}
   ```

   The module is shared, so it stays stdlib only.

2. **Test it in `tests/agent/test_platforms.py`.** Pass `"win32"` in. Calls into Windows go through
   `Kernel32`, and the tests replace it with `FakeKernel`, which records its calls and fails on
   request.

3. **Say what you ran it on.** The README's Platforms table says how far each platform has got,
   and so far only Linux x64 has been used for real.

Paths that differ by platform inside the agent environment are in `whittle/venv.py`:
`venv_python` and `bundled_cli_name`.

Supporting a new platform touches more:

- `platforms` in `whittle/blender_manifest.toml`, and `SUPPORTED`, `SUPPORTED_TEXT` and, for a
  new operating system, `_OS_NAMES` in `whittle/venv.py`, which `venv.compatible` checks.
  `test_platforms_match_what_the_setup_accepts`
  in `tests/blender/test_manifest.py` lists the manifest's platforms by hand.
- Wheels for every pin in `agent_env/requirements.lock` that applies there, for both Python
  3.13 and 3.14 (`PYTHONS` in `whittle/venv.py`), with their hashes in the lock. A compiled pin
  has every file's hash already; `pywin32` is added by hand with a `sys_platform` marker and has
  only its Windows x64 hashes, so another Windows platform needs its own. If one is missing, the
  platform waits for a lock change, and that needs the maintainer's approval.
- The README's Platforms table.
