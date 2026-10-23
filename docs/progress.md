# Progress

## What exists

**The agent and the bridge** (design §2, §4, §9 item 1). A request bundle on disk can be sent
to a Claude agent that edits the open scene, renders from the sketch views to check its
work, and streams everything back to Blender.

- `whittle/`: the extension package. `blender_manifest.toml` validates and builds.
  `__init__.py` stays bpy-free and hands register/unregister to `addon/`.
  - `protocol.py`, `formats.py`: the JSON-lines wire protocol, plus the request bundle
    (request, strokes, camera files) with validation and the session-folder paths.
  - `agent/`: the agent process, `python -m whittle.agent --port N [--fake SCRIPT]`.
    - `connection.py`: the asyncio bridge client. `dispatch.py` routes Blender's calls.
    - `runner.py` holds `SdkRunner`: one `ClaudeSDKClient` per session, inside its own
      task. Built-in tools are off apart from Skill, with `dontAsk` and strict MCP config.
      The session counts as closed the moment the SDK stream ends, so a submit that
      arrives while the client is still disconnecting gets `no_session`, and a query
      left queued behind the stop still finishes its turn.
    - `tools.py` is the in-process MCP servers: `mcp__blender__{exec,inspect,render,checkpoint,restore_checkpoint}`
      and `mcp__whittle__{request,ask}`.
    - `fake.py` is a scripted agent for tests. `prompt.py` + `system_prompt.md` hold
      the Whittle conventions.
    - `plugin/` holds ten recipe skills, loaded as `whittle:<name>`, including
      `mesh-check` and `fuse-parts` for one-shell modeling.
  - `addon/`: the Blender side.
    - `process.py`: spawn, token handshake, crash detection, shutdown escalation. A stop
      before the agent's hello still shuts it down once the hello arrives.
    - `bridge.py`: non-blocking socket. A timer-driven queue runs the agent's calls on
      the main thread (30 ms budget per tick, at most one render per tick). Every call
      gets a reply: a result that cannot be JSON-encoded becomes an `internal` error.
      Failing event callbacks are logged. An unexpected exception in the timer crashes
      the agent visibly, so the timer is never silently dropped.
    - `commands.py` + `execution.py` + `render.py` handle the calls:
      - exec keeps a persistent namespace, captures stdout, trims tracebacks and diffs
        the scene.
        Agent code gets `whittle.mesh_report(obj)` (shells, open edges,
        self-intersections, triangles) and `whittle.weld(obj)` from `meshcheck.py`.
      - inspect answers summary, object, materials, node_groups and scene.
      - render does Workbench shaded/matcap/wireframe/overlay at 512 px from a view or
        a look-at camera, and leaves the scene settings untouched.
      - checkpoint, restore_checkpoint (see History) and ask.
    - `sketch.py`, `views.py` and `bundle.py` are the sketch capture described below.
    - `turn.py` runs start_session, submit and turn_finished, and writes the stream and
      `transcript.jsonl`. When the agent's SDK session ends on its own (`status
      session_ended`), the next run starts a new session; a submit that was already on
      its way gets `no_session` and is resubmitted once, under the same node. An accepted
      turn that the session end leaves without a `turn_finished` is failed. A run
      waiting on an agent that fails to start, stops or crashes is dropped and reported,
      never submitted later.
    - Node ids continue from the highest `nodes/nNNNN` already in the session folder, so
      a new controller (a Blender restart, a changed setting) never overwrites or appends
      to an earlier turn; submit refuses a node folder that already exists.
    - `operators.py` + `ui.py` + `conversation.py` + `autotarget.py`: the Whittle
      sidebar (below, and `docs/ui.md`).

**Sketch capture** (design §3, §9 item 2). The user sketches over the model and submits;
Whittle writes a request bundle from the live sketch and runs it.

- `addon/sketch.py`: the "Whittle Sketch" GP object with one tinted, unlit layer per
  stroke type (free, add, carve, crease, region, note), the active-type switch, and
  per-stroke tags `whittle_view` and `whittle_turn` (curve attributes). Region strokes
  get a `fill_id`, so they render as translucent blue areas. Each type layer keeps a
  single drawing keyed at Blender's lowest frame (`SKETCH_FRAME`), so the sketch is the
  same wherever the playhead is; a layer keyed elsewhere is moved onto that key.
  `SketchSession` enters Grease Pencil draw mode with Surface placement and auto-keying
  off, restoring the user's settings on exit, including when the sketch object is
  deleted while the session runs. A `depsgraph_update_post` handler tags
  each new stroke with the current view as soon as the stroke is added, capturing a
  new view when the viewport turned by more than 15°, panned or dollied by more than
  10 % of the view distance, switched persp/ortho or zoomed by more than 15 %; a 0.25 s
  timer does the same as a fallback.
- `addon/views.py`: views from the viewport's matrices (or the scene camera in camera
  view), stored on the sketch datablock, written as camera.json; an orthographic
  viewport's negative near plane is handled by moving the render camera's eye back.
- `addon/bundle.py`: writes `request.json`, `strokes.json` (world-space points, radius,
  opacity, per-point on-surface flag, normal and object, found by ray casts along each
  view's line of sight), `views/<id>/{camera.json, overlay.png, strokes.png}` and
  `refs/`, atomically and validated. Targets get a stable `whittle_uid`.
- `turn.py`: `run_sketch` writes the bundle into the next node's `request/` folder,
  stamps the sent strokes and submits it. The node number is only taken once the
  bundle is written, a failed write leaves no folder, a dropped run frees its number
  and clears its stamp from every stroke (hidden ones too, so a later run that cannot see
  them never removes them),
  and `request.parent` names the current history node (`n0000` for the first). A successful turn removes its strokes and
  prunes unused views; strokes drawn during the turn stay pending. A failed or
  interrupted turn keeps its strokes for the next run.
- Operators: `whittle.sketch`, `whittle.sketch_stop`, `whittle.sketch_toggle`,
  `whittle.stroke_type`, `whittle.next_stroke_type`, `whittle.capture_view`,
  `whittle.view_snap`, `whittle.submit` (Send), `whittle.clear_sketch`,
  `whittle.ref_add`, `whittle.ref_remove`; the sidebar's sketch strip and composer hold
  them.
- Default keys (`addon/keys.py`), in the 3D View keymap so they work in Draw Mode:
  Shift+Alt+D toggles Sketch mode, Shift+Alt+N the next stroke type, Shift+Alt+V
  captures a view, Shift+Alt+Enter sends. Free in Blender 5.2's default keymap (a test
  checks), rebindable in Preferences → Keymap, meant for a tablet's express keys.
- View markers and Snap to View (`addon/viewmarks.py`, `views.snap_viewport`): while
  sketching, a small camera marks each view's eye in the viewport (a gizmo group, the
  current view orange); clicking it, or the view's row in the view list, puts the
  viewport back at that view's eye, direction and field of view, with the pivot at the
  view's strokes, and makes it the view new strokes go to. The view list's **Markers
  While Sketching** turns them off.
- Agent side: `mcp__whittle__request` prints a summary line per stroke type, names each
  view's `strokes.png`, and decimates a dense stroke list (keeping endpoints, never
  cutting the JSON) while pointing at the full `strokes.json`.
- `tests/fixtures/crate/`: a hand-made bundle with a 0.5 m crate, two views, an
  outline of a lid (add) and a handle slot (carve).
  - `scene.py` builds the matching scene.
  - `make_bundle.py` regenerates the bundle's cameras and images.
- `tests/fixtures/fake/`: fake agent scripts used by the bridge tests.

**Sidebar and steering** (design §2, §4 "Watch & steer", §5, §9 item 3). The user can
watch a turn, steer it and stop it from the sidebar.

- **Sidebar** (`ui.py`), View3D → N → Whittle: a chat (see "Chat-style sidebar" below
  and `docs/ui.md`). Draw code is plain functions, so tests can drive them with a
  recording layout.
- **Targets** (`targets.py`, `scene.whittle.targets` + `target_collection`).
  - The target is an explicit list plus an optional collection. With Auto on (the
    default) the list follows the selection; with it off, it is picked by hand. Nothing
    picked means "make new objects".
  - Objects the agent creates join the list when the turn completes or is kept partial.
- **Amend** (`TurnController.amend`, `whittle.amend`).
  - A message and the strokes drawn since the submit go into the running turn. With
    strokes, `nodes/<id>/amend-<n>/` is written from just those strokes, and they are
    stamped `whittle_amend = n` under the turn's stamp.
  - The agent appends a `<user_amendment>` block (`User amendment n: …`) to the next
    tool result (any tool, errors too). If the model has already finished, it goes as a
    follow-up query and the turn goes on. `amend_delivered` says which way.
  - An amendment the agent never received (interrupt, session end, a turn that ended
    first) is handed back before the turn's strokes are cleared: its strokes are
    pending again, its folder goes, and its text returns to the prompt.
- **Interrupt** keeps the partial edit or restores the turn start. Every submit writes
  `checkpoints/start.blend` + `start.json` (`snapshot.py`). Restore puts back the
  target objects, their data, materials and GN groups via `ID.user_remap`, and removes
  objects the agent created. An object counts as created only if it is named in an exec
  diff and its `session_uid` was not there at turn start, so an existing object the
  agent renamed is neither deleted nor adopted as a target. Nothing else is touched, and no `.001` names or libraries
  are left. A restored turn keeps its strokes.
- **Ask**: the turn's phase becomes `waiting_user`, and the conversation shows the
  question. Answers and interrupts go into the transcript as local records.
- **Target lock**: removed; user edits during a turn are neither watched nor reported
  (decisions.md).
- **Redraws**: the bridge tags the 3D Viewports for redraw after every event, call
  result and run of agent calls, and on each agent state change (a crash noticed by
  polling included), so the sidebar never shows a stale phase or a missing answer box.
- **Pending strokes** drawn during a turn are counted in the sidebar and kept out of
  the agent's overlay renders (`sketch.isolate_strokes`), which show only the turn's
  own strokes and amendment strokes.
- **Agent side**:
  - `ToolContext.deliver_notes` puts amendments on every tool result. The
    `SdkRunner` handles follow-up queries and reports `amends_undelivered`.
  - Turn totals are summed over the turn's queries, and `cost_usd` is the turn's share
    of the session's running total.
  - The fake agent gained `wait_amend`, `read_amend` and `after_amend`, and its sleep
    is cut short by an interrupt.
  - The system prompt has a "Mid-turn messages" section.

**History** (design §6, §9 item 4). Every turn leaves a node in a tree the user can
restore, branch from and compare against, and each branch has its own SDK conversation.

- `whittle/tree.py` (stdlib): `Tree`/`Node`, `session.json` read/write/validate, and
  `session_plan`, the rule that decides restart / resume / fork / `resume_at` for a
  submit. Tested under `.venv/bin/python` (`tests/agent/test_tree.py`).
- `addon/history.py`: one `History` per session folder.
  - Node 0 ("Start") is written on the folder's first run.
  - Each turn adds a node at submit and finishes it at the turn's end with
    `target.blend` + `target.json` (target datablocks only), a 128 px `thumb.png`, the
    status, SDK session id, last message uuid, costs and the uids of the objects the
    agent made. Then one undo step, `Whittle: <node> <label>`.
  - Interrupt → Keep gives `interrupted` + `kept_partial`; Interrupt → Restore gives
    `interrupted` + `restored` with the turn start as its snapshot, and the next
    submit tells the agent. A crash or session end gives `failed`. A refused submit
    is dropped from the tree with its node folder; a `running` node read back after a Blender crash
    becomes `failed`.
  - Restore removes only objects the agent made that the node lacks, never the user's,
    and sets the target list. Branch restores the node's parent and brings back what the
    node sent, read from its request folder: the prompt, its strokes (as pending ones,
    after any drawn since, with their views; a view id the sketch now uses for another
    view gets a new id) and its references (unless a listed one has the same image, as
    a pinned one does). Strokes a failed or interrupted turn kept, still stamped with its
    number, are replaced by the request's copies rather than doubled. The restore and the
    replay are one undo step, `Whittle: edit & resend <node>`. So Submit makes a sibling
    from the same sketch. Submit refuses a
    request with no prompt, no strokes and no references.
  - The session folder never moves: it lives in the file's hidden cache in Whittle's
    user folder, named by an id the file stores (§14 of the architecture), so a first
    save, a Save As or moving the file leaves the controller and its chat where they
    are, even during a turn.
  - Restore, Compare and checkpoints find each snapshot object by its `whittle_uid`, so
    a target renamed since comes back in place, and a user object that took a
    target's old name moves aside to a `.NNN` name instead of being replaced. An
    agent's copy of an object gets its own uid when the turn finishes. A turn's
    targets are also resolved by uid (`CommandContext.targets`), so a target the agent
    renames mid-turn stays in its checkpoints and in the node snapshot.
  - A user's copy (Shift+D) of an object the agent made carries the same uid. Before
    Restore or Compare removes anything, `History.separate_copies` keeps the uid on
    the object the history knows (a name some node recorded for it, then being a
    target) and gives the rest uids of their own, so the copies count as the user's
    and stay. When the original cannot be told apart, nothing with that uid is
    removed.
  - What an appended object brings along beyond the target (a modifier's collection,
    an action, a world) is paired across every `bpy.data` ID type, so restores,
    compare toggles and the ghost no longer leave `.001` duplicates behind.
  - `scene.whittle.history_node` mirrors the current node so Blender's undo rolls it
    back; an undo/redo handler copies it into `session.json`. On file load the same
    sync runs, so a reopened `.blend` decides the current node (and the next submit's
    parent and session plan) even when a restore after the last save had moved
    `session.json` on.
- `addon/compare.py`: Compare toggles between the live scene (`compare/live.blend`) and
  another node; End puts the live scene back, Keep restores the node. Showing the node
  removes only objects the agent made, as Restore does, so a user object added to the
  target after that node stays (and survives Keep). The Ghost shows
  the current node's parent as a renamed, wireframe, unselectable copy in "Whittle
  Ghost", cleared at submit, on file load and by its toggle, also from a saved file.
- **Sessions** (`TurnController`): the controller remembers the node the live SDK client
  finished on. A submit from that node goes straight in; from a leaf that ends its
  session it resumes; from anywhere else it forks at the node's last message
  (`resume` + `fork_session` + `resume_session_at`, checked live), with a context note.
  After a Blender restart the first submit resumes from `session.json`. A resume that
  fails falls back to a fresh session with a note. Each node records at submit the SDK
  session it carries on (`continued_session`), so a turn that never finished (Blender
  quit mid-turn, an agent crash) still makes a later submit from its parent fork with
  a note rather than resume a conversation that went past the scene. Context notes reach the agent as a
  `<whittle_context>` block before the prompt.
- **Checkpoints**: `mcp__blender__checkpoint` writes `checkpoints/c<k>.blend` of the
  turn's objects; `mcp__blender__restore_checkpoint` puts it back and removes what the
  agent made after it, keeping Interrupt → Restore right.
- **Sidebar**: history sits on the turns (edit and resend, a branch switcher, a menu)
  and in the 🕘 popover with the whole tree; see "Chat-style sidebar" below.
- `snapshot.restore` now leaves a mode only when the active object is being replaced,
  so a restore keeps the sketch in draw mode; it takes `remove_uids` too.
- Tests: `test_history_snapshot.py` (fidelity of mesh, modifiers, a nested GN group
  and its input, materials incl. a shared one, created objects, an untouched
  bystander, renamed targets, a user object taking a target's old name, agent copies,
  user copies of agent objects, a user target newer than the compared node,
  modifier collections and actions not duplicated by restore, compare or ghost, files,
  sketch mode), `test_history.py`, `test_history_sessions.py` (also undo/redo sync and
  a save → restore → reopen in a fresh Blender),
  `test_session_folder.py` (the session folder following a first save, a Save As, a save
  during a turn, and a real Save As and reopen in a fresh Blender),
  `test_checkpoint.py` (also a target renamed mid-turn), `test_compare.py`, the history part of `test_sidebar.py`, and
  the gated `test_live.py::test_live_fork`.

**Start points, preferences and packaging** (design §5 Preferences, §7, §8, §9 item 5).
Whittle installs from a zip, sets up its own agent environment after asking, and a
session can start from the scene, from nothing, from a primitive or from an asset.

- `whittle/venv.py` (stdlib): reads the lock (30 pins with hashes), the venv's status
  (`missing`, `ready`, `stale`, `broken`, `foreign`) from its `whittle-venv.json` marker,
  the create / install / verify commands (`pip install --isolated --require-hashes
  --only-binary :all: --no-deps -r requirements.lock`, never an upgrade), a scrubbed
  environment, and `VenvSetup`, which runs them as subprocesses with a timeout each,
  cancel, a log, and a dry run. Tested under `.venv/bin/python` with a fake process and
  clock plus one real-subprocess run that installs nothing (`tests/agent/test_venv.py`).
- `addon/setup.py`: the venv folder (the `venv_dir` preference or `<user dir>/venv`),
  `begin()` with its refusals (a turn or a setup running, wrong platform, a foreign
  folder, no online access, background Blender), the timer (persistent, so opening or
  resetting a file mid-install does not leave the setup stuck "running"), and the operators
  `whittle.venv_install` (behind a confirmation dialog naming what is downloaded and
  where) and `whittle.venv_cancel`. `paths.agent_python()` counts the private venv only
  when it is `ready`; a stale or broken one is the `needs_setup` reason, and the main
  panel then shows a setup box instead of Restart Agent. Finishing a setup clears
  `needs_setup`.
- `addon/prefs.py`: four boxes. Claude (the API key, where the key in use comes from
  and a Get an API Key link, the model for new chats, the Powered by Claude line),
  Agent Environment (folder, status, Install / Reinstall / Cancel, the setup log),
  Defaults (triangle budget, style notes, self-check rounds, render size) and Development
  (agent Python). Every default comes from `DEFAULTS`.
- **Per-file settings** (design §10 guardrails, ui.md §3.1): `scene.whittle.poly_budget`
  and `style_notes` override the preferences for one file and are saved with it; the
  agent popover edits them under For This File, each "(default)" while unset and with a
  reset button (`whittle.file_setting_reset`). `prefs.session_settings(scene)` puts them
  over the preferences, so the session, the request bundle and the restart check all use
  the file's values. Tests: `tests/blender/test_file_settings.py` (the default read
  through, an override and its reset, the minimum, a wrong-typed value, another scene,
  the popover, the values in a saved file read by a fresh Blender, a restart on change).
- **API key only** (architecture §2, Authentication): the agent starts only with a key
  (the preference, else `ANTHROPIC_API_KEY` in Blender's environment); without one the
  process goes to `needs_key` and the attention box asks for a key. The agent's
  environment drops every other Claude or Anthropic credential variable, and the CLI
  runs with `CLAUDE_CONFIG_DIR` in Whittle's user folder, so it never sees a claude.ai
  login or the user's own Claude settings. Tests: `tests/blender/test_auth.py` (no key,
  no start and the prompt kept; the preference before the environment; the stripped
  environment and private folder handed to Popen; no copy of the key in the user folder
  or the agent's log after a run), `test_sidebar.py` (the key box).
- `addon/start.py` and the **Start from** row (shown until the first turn): Selection,
  Blank (this scene with nothing selected or targeted; nothing added), a Primitive menu (seven `bmesh.ops` primitives standing
  at the cursor) and **Start Whittle From Asset** in the Asset Browser's context menu
  (appended without leaving a library, or a local asset used in place). Each writes node
  0 now via `History.start`, which may rewrite a root that has no children yet.
  A retaken start first takes back what the earlier one put in the scene: objects
  it made (primitives, appended assets) are removed, file objects it only linked into
  `Whittle Target` are unlinked (and kept in the scene); an appended collection asset
  goes with its objects, a local one it linked into the scene is only unlinked. All are
  tagged `whittle_start`. From Selection drops the target collection and clears those tags, so what earlier starts made becomes
  part of the scene the user starts from.
  Whittle's helpers carry `whittle_reference` and are never targets.
- `request.json` gained an optional `target_collection`; the request tool tells the agent
  "New objects go in collection '…'", and the system prompt has a "Helpers in the scene"
  rule.
- `addon/refs.py`: references can be pinned (`WhittleRef.pinned`); a successful sketch
  turn removes the unpinned references it sent. **Place** makes a half-transparent image
  empty from a reference, aligned front, right, top or to the view.
- Packaging: `build.sh` checks the lock copy, validates and builds
  `build/whittle-0.1.0.zip` (gitignored); the manifest declares only `network` and
  `files`. `README.md` covers install, the venv setup, development and tests.
- Tests: `test_venv.py` (agent side), `test_prefs.py`, `test_venv_setup.py` (the dry-run
  operator, the refusals, the setup box, the confirmation dialog shown before anything
  starts, the timer surviving a file load), `test_start.py` (each start point,
  idempotence, retaken starts in a row (a collection asset included), refusals, the
  start row, a blank start followed by a fake turn), `test_refs.py`, and `test_manifest.py` (permissions, the zip's
  contents, `build.sh`, registration of the new classes and the Asset Browser entry).

**Fixes from the first manual test pass.** Testing in the GUI turned up behaviour bugs;
these are fixed, each with a regression test.

- **Settings changes restart an idle agent**: `operators.controller()` compares what the
  running agent was started with (`TurnController.launch_settings()`: Python, fake script,
  API key digest, model, session settings) with the settings now. A changed fake script
  replaces the controller; anything else stops the idle agent, so the next run starts a
  fresh one and resumes the conversation from the history. A busy controller is never
  touched (`test_steering.ControllerTest`).
- **Amend right after Submit**: Amend works from Submit on. While the agent or its
  session is still starting, the amendment is queued and goes in, in order, the moment
  the turn is accepted; a run that never starts hands its text back to the prompt
  (`test_steering.AmendWhileStartingTest`).
- **Thumbnails fill the frame**: history thumbnails are square and framed on the
  target's bounding-box corners, from the side the sketch view looked from
  (`test_history.NodesTest.test_thumbnails_frame_the_target`).
- **Failed turns that changed nothing fold** into their parent: kept in `session.json`
  (`folded: true`) with their request and transcript, but hidden from the tree, never
  current, and not restorable or branchable; the next submit forks the conversation at
  the parent, so the agent never sees the failed exchange. A failed turn that did edit
  the scene is still a node. The model is described in `architecture.md` §6
  (`test_history.OutcomeTest`, `test_tree`).
- **Compare → End and Toggle back to live** put the target list back as it was, found
  by `whittle_uid` (`test_compare.CompareTest.test_end_keeps_the_target_list`).
- **Prompt-only requests**: a request with no strokes and no views says so plainly in
  the turn's first message and in the request tool's summary, and the system prompt
  tells the agent to self-check from its own cameras then. The fake agent gained
  `if_views` / `else` steps and `"view": "first"`, and `stream.json` uses them, so it
  plays without errors on a prompt-only turn (`test_steering.StreamTest`,
  `test_runner`, `test_tools`, `test_fake_runner`).

**Sidebar screenshot harness.** The sidebar is checked on real screenshots of the panel,
shot in a GUI Blender without a person at the keyboard.

- `./screens.sh [scenario ...]` runs `tests/screens/run.py`: one factory-startup GUI Blender
  per scenario (sequentially, each under `timeout 120`), writing `build/screens/<name>.png`,
  `build/screens/wide/{conversation,long_session}.png` and `build/screens/index.json`
  (scenario, image, one-line description, size, pages). It exits non-zero when an image is
  missing.
- `tests/screens/harness.py` runs inside Blender: registers the in-repo add-on from
  `sys.path`, unregisters the other Python sidebar panels and selects the Whittle tab
  (Blender's built-in Item panel cannot be unregistered), turns region overlap and tooltips
  off, plays the scenario on `bpy.app.timers`, then `screen.screenshot_area` + a crop with
  Blender's image API and numpy. Panels taller than the sidebar are scrolled page by page
  (`view2d.scroll_down`) and stitched; the empty rows below the last panel are trimmed. The
  wide variant drags the sidebar's edge with `--enable-event-simulate` events (region width
  has no setter), which also keeps real input out of the window. A scenario that returns a
  `Popup` is shot as a popup: the pointer is moved over the sidebar (simulated), the window
  is shot, the popover (`wm.call_panel`) or the menu operator is opened, the window is shot
  again and cropped to what changed.
- `tests/screens/scenarios.py`: 23 states (empty, start, prompt_typed, prompt_only_done,
  sketching, streaming, conversation, branched, branch_edit, asking, interrupted,
  error_turn, folded_failure, crashed, setup_needed, key_needed, comparing, manual_targets,
  long_session, history_popover, turn_menu, references, developer), reached through
  `operators.submit_sketch`, `branch_node`, `compare_node`, `interrupt`, `targets`,
  `sketch.start_session` and the controller's state, never through the layout, with fake
  agent scripts written per scenario. The fake agent's call step has `"delay"` so a call can
  be shown in flight.
- Blender's user folders (`BLENDER_USER_*`) point into `build/screens-work/blender-user/`,
  with factory preferences saved there first, and the harness refuses to run if Blender's
  config folder is anywhere else.
- Tests: `test_screens.py` (scenario list vs catalog, stitching, trimming) and the fake
  runner's delayed call.

**Chat-style sidebar** (`docs/ui.md` is the spec; every state in its §10 was shot and
looked at). The Whittle tab reads like a chat app: what Claude is working on, the
conversation of the current branch, a Sketch button and a prompt box, with history in
each message's menu instead of an always-open panel. A control shows only in the state
it serves, and red is kept for real failures.

- One panel, `WHITTLE_PT_main`; the Start, Sketch, Request, Activity and History
  sub-panels are gone. Everything is said once: a running turn's progress is in the
  conversation only (the header icon is an hourglass only while the agent starts or
  stops outside a turn, else a gear), a draft only in its field. The header icon opens `WHITTLE_PT_agent` (state, why it stopped, model, session
  folder, Start/Stop, Preferences). A box appears at the top only when the user must
  act, and says it once: set up the environment (neutral, red only after a failed
  setup; Send is disabled meanwhile), a crash (one red line and **Restart and Retry**,
  which resends the turn the crash ended; that turn shows a dim "Interrupted"), a
  missing API key (neutral, the `needs_key` state) or a refused one
  (`TurnController.key_problem`, from the CLI's authentication errors), both with
  Preferences and Get a Key.
- **Text is measured** with the UI font (`blf`) against the region's real width, so lines
  use the room they have; shortened labels end at a word with `…`.
- **Targets**: the target line with an **Auto** toggle (`scene.whittle.target_auto`, on by
  default), dim while a turn runs. Auto follows the selection in Object
  Mode (`addon/autotarget.py`: a depsgraph handler and a message-bus subscription on the
  active object; selected objects, the active one first, else the active object, else
  new objects) and holds still during a turn, a comparison, sketching and other modes.
  Whenever Whittle sets the list itself (a turn's end, Restore, Branch, a branch switch,
  Compare, a start point) it selects those objects. With nothing to target the line
  says "Nothing selected: Claude adds new objects", dim. Auto off counts the targets on
  the line ("2 targets") and shows the picked objects as plain rows with one ✕ each, an
  **Add <selected object>** button, and ⋯ (`WHITTLE_PT_targets`: collection, Replace
  With Selection, Clear). Auto's tooltip starts "Follow the selection".
- **Start points**: one row under a dim "Start from" (Selection, Blank, Primitive ▾; the
  Asset Browser hint is in the Primitive menu), only before anything is sent and not while sketching or with a
  prompt and a target. After a first turn that failed and folded, the 🕘 popover offers it.
- **Conversation** (`addon/conversation.py`): the path to the current node, built from
  the live stream for the running turn and from each node's `transcript.jsonl` for
  finished ones. Each user bubble has the prompt at full width and one ⋯
  (`whittle.turn_menu`: Edit & Resend, Go Back to This Turn, Compare, ghost, Open
  Render, transcript) on its last line; a turn with siblings has ◂ 1/2 ▸ in that same
  row, left of the ⋯ (`whittle.branch_switch`; an arrow that leads nowhere is dim). The
  turn being compared is marked there with ⇄. The last two turns are
  expanded, with a thumbnail that grows with the sidebar; the three before fold to one
  line with no buttons, older ones into "N earlier turns". Tool calls collapse into one
  "Used 4 tools" line per run ("Running 2 tools" while several are in flight, and then
  no "Working…" line); a recovered tool error is a ✗ inside it, never red; an
  in-flight `ask` is left out while its question shows. A failed turn ends with its
  reason as one red line (wrapped once at most) and **Retry** beside it
  (`whittle.retry`); a failed turn that changed
  nothing shows once, after its parent, with the prompt box left empty (Retry or ⋯ →
  Edit & Resend bring the prompt back). The interrupt record no longer repeats the end
  line. "N later turns" with **Return to Latest** appears off the end of a branch, and
  Send reads **Send as Branch**.
- **Sketch**: a Sketch button; while sketching it stays pressed with **Capture View**
  beside it, and the six stroke types (Region and Note have clearer icons; tooltips name
  each, and the active one is named beside them) get a row of their own. The stroke
  count (with 🗑 and the view list; the current view has its own icon and a "current"
  tag, and none is dimmed) shows whenever the viewport shows something: pending
  strokes, strokes a stopped or failed turn was sent with, or views alone. Before, Clear
  and the view list were out of reach after a stopped or failed sketch turn.
- **Composer**: references as attachment chips right above the prompt (a chip opens its
  menu to pin, place, open, remove; a pinned one has a pressed pin that unpins it), the
  prompt field with 📎 (the draft shows only there), **Send** and the history popover
  (a clock-with-arrow icon in a fixed-width slot, tooltip "History…"). During a turn: the amend field and **Stop ▾** (keep or undo),
  with **Amend** once there is text or a new stroke; while Claude asks, **Answer** once an
  answer is typed. A comparison disables Send with a tooltip instead of a red line.
- **History popover** (`WHITTLE_PT_history`, 24 units wide so titles fit): one row per
  node with its thumbnail, its title as the Restore button (drawn like a menu item, the
  current one highlighted) and ⋯. Indentation is the node's branch level, one unit per
  level (at most 4), so siblings line up and long lines stay flat; a branch's first row
  has a dim ↳ and the row it leaves from says "2 branches". No disclosure triangles.
  Hide Ghost shows only while a ghost is shown.
- **Comparison bar**: "Showing: Add a lid", then **Swap**, **Keep This** (only while the
  compared turn is shown) and **Done** as text buttons; their tooltips carry the note
  about saving.
- The Development panel shows only with Preferences → Interface → Developer Extras.
- `scene.whittle.stream_length` is gone; files that have it load fine.
- Tests: `test_sidebar.py` (the panel in each state through a recording layout, the
  conversation over a history on disk, the crash reported once, the start points after
  a folded turn, the popover's levels and rows, menus), `test_chat.py` (Auto targets,
  the branch switcher, edit and resend, Retry of a folded and a recorded failure, the
  prompt handed back, refused-key classification, transcript replay), `test_tree.py`, and
  the updated start, refs, setup, history and steering tests.

**Chats** (`docs/ui.md` §3.11, architecture §14). A file holds any number of chats, each
its own conversation, history tree and Claude session; the panel shows the current one.
- **Header**: the current chat's title (`New chat` before its first turn), shortened at
  a word's end, opens the chat menu (`WHITTLE_PT_chats`): New Chat, the chats most
  recently active first (title, `N turns · <age> · <size>`, ✓ on the current one, 🗑 on
  the others), 20 at a time with `Show N More`, the total, and Rename This Chat…,
  Delete This Chat… and Delete Other Chats… (all, or older than a week, a month or
  three months). Every delete asks first.
- **Switching** leaves the scene as it is: it stops the old chat's agent and shows the
  other conversation; its history is all there to go back to a turn by hand, a dim line
  says the scene is as the user left it, and the next turn resumes (or forks) that
  chat's SDK session with a context line saying the scene may have changed. **New
  Chat** starts a fresh session whose node 0 is the scene when its first turn is sent.
  Both wait for a running turn or a comparison; neither is an undo step, and Ctrl+Z
  never changes the chat (`scene.whittle.chat` names the chat of the undone node).
- **Storage**: every chat is zipped into the `.blend` around each save (bytes ID
  properties on a hidden `.whittle` Text, added in `save_pre`, removed in `save_post`
  and `load_post`), repacked only when its folder changed. Nothing is written beside the
  `.blend`: the working copy is a hidden cache, `<user dir>/cache/<file id>/`, named by
  a random id the file stores on the same Text (so it follows renames and moves).
  Opening the file fills the cache from it and the file wins, except after a crash:
  work newer than the last save, built on exactly what that save stored (a stamp in
  the cache's `cache.json`), is kept. A copy opened while the original's cache is in
  use, or whose cache records another file that still exists, gets a fresh id, found
  again by its recorded path on later opens until it is saved, so a crash before that
  save keeps its work too. Caches not used for 30 days are deleted whenever a file is
  opened, never the open one. Deleting a
  chat removes it from the cache and the CLI's transcripts of its folder at once and
  from the file at the next save (a test checks the saved file shrinks by the chat's
  packed size).
- **SDK transcripts** go into each chat's `sdk/` through a `SessionStore`
  (`agent/store.py`), so a chat resumes after the file moved or on another machine.
- **Chats from another machine**: each chat records the install that made it (a
  random id in Whittle's user folder). Another install's chat opens read-only with a
  `Continue this chat?` box: Send is disabled with a tooltip until Continue, which is
  stored with the chat so it never asks again; New Chat stays available. Chats from
  before the marker never ask.
- **The same file in two Blenders** keeps a cache in each, as before, and while the
  other's claim is live the sidebar has one dim line saying the chats won't merge.
- **No migration**: the code for earlier development layouts (a single-session folder,
  `<name>.whittle/` beside a file and its `.replaced-<time>/` copies, the user folder's
  `caches/<sha1>/` and `dev-sessions/`) was removed.
- Tests: `tests/agent/test_chats.py`, `test_caches.py`, `test_store.py`,
  `tests/blender/test_chats.py` with `chats_file.py` (a real save, the cache deleted,
  reopen, restore, delete and shrink), `test_cache.py` with `cache_file.py` (a file's
  life in fresh Blenders: save and reopen, a move, a copy, a cache in use, a crash, an
  older file, cleanup by age; nothing beside the `.blend` but its `.blend1`), and
  `test_session_folder.py` (saving keeps the cache). Screens: `chat_menu`,
  `chat_menu_many`, `new_chat`, `switched_chat`, `continue_chat`, `open_elsewhere`,
  `delete_confirm`, `delete_many`.

**Opus 5.5 harness settings** (`prompting.md`, architecture §5 and §15).
- **Progress notes**: Claude's short notes between tool calls show as its text in the
  conversation. The bundled CLI requests thinking display `updates` when no display is
  set, so Whittle sets none, and the runner turns narration thinking blocks (told apart
  by their signature, as the CLI does) into `text` events. Other thinking stays in the
  tool group.
- **Effort per chat**: Low, Medium or High in the model menu, High for new chats, kept
  in the chat like its model. `--effort` at session start; a change switches the live
  session before the next query (`apply_flag_settings`), so the conversation carries on.
- Tests: `tests/agent/test_runner.py` (options, `thinking_kind`, narration as text,
  effort switches), `test_dispatch.py`, `test_chats.py` `EffortTest`,
  `tests/blender/test_models.py` (the Effort section, a switch between turns with the
  fake agent).

## How to run

```sh
./run_tests.sh            # everything offline; add -v for verbose
WHITTLE_LIVE=1 ./run_tests.sh   # also the live tests (call the API, ~$0.01)
./run_tests.sh -k test_compare  # only tests whose name matches, on either side
# one Blender test alone:
timeout 300 blender -b --factory-startup --python-exit-code 1 --python tests/blender/run.py -- -k test_compare
```

With `-k`, a side where nothing matches exits 5 (unittest's "no tests ran", which
`tests/blender/run.py` mirrors) and is skipped; `run_tests.sh` fails with 5 only when
neither side matched.

The live tests (`tests/blender/test_live.py`) run Blender with `--online-mode` and start
the real agent from `.venv/bin/python` on `claude-haiku-5-5`, with a $0.10 cap per
test (about $0.003 in all). They need `ANTHROPIC_API_KEY` in the environment (billed to
that key) and are skipped without it.
- The smoke test checks that `print(2 + 2)` reached Blender and printed `4`.
- The amend test sends an amendment right after `turn_started` and checks it was
  delivered: the model ran the extra `print(2)`. A second turn in the same session
  shows that `total_cost_usd` is the session's running total.
- The fork test runs two turns, restores the first node and runs a third: the third
  forks at the first node's message uuid, gets a new session id, and its transcript
  has the first prompt and not the second (about $0.007).

To build the extension: `./build.sh` (validates, then writes `build/whittle-0.1.0.zip`).
The README covers installing it and setting up the agent environment.

To drive a bundle by hand in Blender:
1. Build and install the extension: `./build.sh`, then `blender --command extension
   install-file -r user_default build/whittle-0.1.0.zip`.
2. Point `WHITTLE_AGENT_PYTHON` (or the Agent Python preference) at `.venv/bin/python`, or
   set up the agent environment from the preferences.
3. Allow Online Access in Preferences → System.
4. Open a scene with an object named `Crate`. `tests/fixtures/crate/scene.py` builds one.
5. In the sidebar's Whittle tab, set Bundle to `tests/fixtures/crate/request/` and press
   Run Bundle.

To sketch and steer by hand in Blender (steps 1–3 as above):
1. Open a scene with something to sketch on. In the sidebar's Whittle tab, select what
   Claude should work on (Auto follows the selection), or turn Auto off and pick targets
   or a collection. With nothing selected the agent makes new objects.
2. Press **Sketch**. Pick a stroke type, draw (strokes stick to surfaces), orbit to
   another angle and draw more. The camera button records a view explicitly.
3. Type a prompt, optionally add reference images with 📎, and press **Send**.
4. Watch the turn in the conversation. Open "Used N tools" to see each call's code and
   result, and press the image button beside a render to open it. While the turn runs
   you can draw more strokes, type into the field and press **Amend**, answer a
   question, or **Stop ▾** (keep the changes or undo the turn).
5. ⋯ → **Open Transcript** shows the whole session in a Text Editor. After a successful
   turn the submitted strokes disappear, and anything drawn since stays pending.

To try the UI without the API, turn on Developer Extras and set **Development → Fake
Script** to a script under `tests/fixtures/fake/` (for example `stream.json` or
`ask.json`). Send then plays it.

Every file's chats are cached in `<user dir>/cache/<file id>/` (an unsaved file gets
its id when its first chat is made, and keeps it when saved); the file itself stores
them at each save. Nothing is written beside the `.blend`.

## Known gaps

- **The chats' cache**:
  - A chat's conversation resumes through its transcript store when its cwd changed
    (a copy's fresh cache); that a real CLI resumes and forks from a
    store-materialized session is checked only offline (the SDK's materialization, and
    the fake agent), not live yet.
  - Save Copy leaves the cache with the open file; the copy carries the chats and gets
    a cache of its own when opened (its id's cache records the original).
  - Crash recovery keeps newer chat work for saved files. Closing without saving or
    File → Revert keeps it too (the cache was built on what the file stores); only a
    file that differs from that wins. An unsaved file that crashed starts a fresh
    cache when reopened (a new file never takes a stored id); its old cache ages out.
  - Opening Blender's own autosave or `quit.blend` (told apart by name) uses the id it
    stores without the path check, so it finds the original's cache and leaves its
    record alone; no test opens a real recovery file, and File → Recover is unchecked
    in the GUI.
  - "In use" is a claim file with the Blender's process id: a claim from another
    machine (a shared home folder) always counts, so a file open there gets a fresh
    cache here.
  - A real Save As in a GUI session is not checked by hand yet; the tests cover the
    handlers and real saves, moves and reopens under `-b`.
- **Branch** brings back the node's request strokes and references, not the strokes
  or text of its amendments.
- **Opus 5.5 settings, offline only**: the progress notes and the live effort switch
  were built from the bundled CLI's source and are tested with the fake client; no
  real turn has shown a narration block or switched effort yet. If notes never show,
  check the CLI log (`cli:` lines) for the `thinking-display-updates` beta; if a
  switch fails, the turn fails with the CLI's reason.
- **View markers and sketch keys** were checked in a hidden GUI Blender with simulated
  events: a marker highlights under the pointer, a click on it in Draw Mode snaps the
  viewport (view and projection matrices equal to the stored view's) without drawing a
  stroke, an orthographic snap matches too, and Shift+Alt+N, V and D work over the
  viewport in Draw Mode. Not yet tried with a real pen and express keys (checklist).
  Snapping does not bring back lens shift (not stored), and a view captured in a
  portrait viewport snapped into a landscape one keeps its field of view across the
  long side, not the short one.
- **Not built yet**:
  - Windows and macOS: the manifest lists `linux-x64` only and the lock holds manylinux
    x86_64 wheels, so `venv.compatible()` refuses other platforms.
- **The venv install** ran for real once from the GUI (and a real Haiku turn ran from
  it). Tests check the commands, the state machine with a fake process, a dry run and a
  real-subprocess run that installs nothing. A cancelled setup leaves its folder marked
  incomplete (`broken`), and the next setup rebuilds it with `--clear`. A cancel during the
  `--clear` of a reinstall can, in a narrow window, leave the folder without its marker,
  which then reads as `foreign` until it is removed by hand.
- **Chats**: whether taking the chats out of the data in `save_post` / `load_post` marks
  the file modified (the title bar's `*`) is unchecked; a test cannot read it. Blender's
  autosave and crash-recovery files carry no chats (no `save_pre`), only the file's id;
  the file's cache in the user folder still has them. A chat's size is measured by packing it at the end of
  each turn, which takes a few milliseconds per megabyte.
- **Checked by hand in the GUI** (first manual pass): sketching with views and overlays,
  the Image Editor and transcript, Interrupt Keep / Restore, Amend (text and strokes),
  ask, Restore with Ctrl+Z / Ctrl+Shift+Z, Compare / Toggle /
  End, the ghost, Branch, a real agent environment install, and one real Haiku turn
  (a prompt-only request, handled well).
- **GUI-only, still unverified** (see the checklist below): restart and resume, Blank +
  Sketch (strokes on surfaces, and off them on the view plane at the 3D cursor's depth),
  Primitive, the Asset Browser entry (`context.asset` exists only there), references
  placed from a real view, a real Ctrl+Z during a turn (back to the turn's start, the
  agent told) and during a comparison, and scene calls waiting out a real transform. How the panel looks in each state is now covered by
  the screenshot harness.
- **Screenshot harness**: the images are reviewed by eye, not diffed. Sketch strokes in the
  `sketching` scenario come from the data API (the crate fixture's strokes), not the draw
  tool. Shots are at UI scale 1 and the factory theme, with region overlap and tooltips off
  (the panels look the same; only the background behind them differs from Blender's
  default). The wide variant relies on the sidebar's edge being draggable at its left
  border; the harness fails if the width does not change. The windows open in a hidden
  nested KWin session (README), without focus, and are clamped to its height, so tall
  panels are scrolled and stitched.
- **Chat-style sidebar**:
  - Auto targets are tested headlessly (the sync rules, a depsgraph update after a
    selection change, the selection Whittle sets after a restore). The message-bus path
    (clicking another object in a real viewport) and its feel in a long session are for
    the manual checklist.
  - Text is measured with font 0 at the UI style's widget size times the UI scale,
    checked in the screenshots at 280 and 448 px and UI scale 1. A custom interface
    font or another scale may measure slightly off; Blender then shows its own `...`.
  - Collapsed turns, tool groups and "More" are layout panels: their open state is kept
    per region by Blender and cannot be set from Python, so the screenshots show them
    closed. The view list uses a window-manager property for that reason.
  - The popover and menu screenshots open them with `wm.call_panel` and the menu operator,
    not by clicking the 🕘 and ⋯ buttons themselves.
  - A refused key is recognised from the CLI's error text (invalid API key, 401,
    authentication_error); the exact message of a revoked key has not been seen live.
  - Retry on a folded turn sends what is in the prompt box when it is not empty (the
    folded prompt goes back there only when the box is empty).
  - While Claude asks, the field is the answer's, so a typed amendment waits until the
    question is answered; strokes can still be sent with Amend.
  - During a turn both switcher arrows are dim: switching waits for the turn to end.
  - A long draft is cut in the middle by Blender's one-line text field; while editing,
    the field scrolls. A wrapped copy above it was dropped as noise.
  - Reference chips are packed by measured width; at the default sidebar width two
    chips with long file names take a row each.
- **Queued amendments** (made while the turn starts) carry the strokes pending when the
  turn is accepted, not when Amend was pressed; strokes drawn in between ride along.
- **Folded turns** keep their request on disk; Edit & Resend on one only puts its prompt
  back (the scene never left its parent). Send takes the prompt out of the box and a
  fold does not put it back (the folded turn shows it), and a failed turn keeps its
  strokes. A folded turn shows in the conversation only in the Blender
  session that ran it. A turn that failed after only reading the scene folds even if
  the user edited the target meanwhile: the user's edit stays in the scene.
- **Settings restart**: a changed setting is noticed when an operator next looks up the
  controller (Send, Run Bundle, Start Agent, a start point), not the moment it changes.
  Stopping the idle agent waits for it to exit (normally well under a second).
- **Main-thread exec cannot be pre-empted**. A slow `exec` freezes the UI until it
  returns, and a Stop waits for it (the turn shows "Stopping…").
- **Restore scope**: the turn-start snapshot covers the target objects, their data, slot
  materials and GN groups. Images, materials assigned by geometry nodes, and objects
  only referenced by modifiers (a boolean cutter, its collection) and actions keep
  their current state.
- **Amend strokes on Run Bundle turns**: a turn run from a bundle on disk takes text
  amendments only; its sketch strokes are not stamped.
- **The undo note** reaches the agent only with its next tool result: a turn that makes
  no more tool calls never hears of the undo.
- **Created objects across undo**: created objects are told apart by `session_uid`. If a
  memfile undo during the turn changes uids, an existing object the agent renamed could
  again count as created.
- **`MCP_TOOL_TIMEOUT`** is set to 24 h so a long `ask` is not cut off, but this has not
  been checked live. `ask` in background Blender answers at once as unattended.
- **Resume after the `.blend` moved**: the CLI keys sessions by working directory (the
  chat's folder), so a moved chat resumes from its transcript store instead. A session
  missing from both falls back to a fresh session with a note. The fake agent covers that path; the real
  CLI's error shape for it has not been seen live.
- **Saving during a comparison** saves the compared node as shown. Restoring the live
  scene inside `save_pre` is unsafe, so the comparison bar's tooltips only warn.
- **Name clashes on restore**: a user object that took a restored target's name is
  renamed with a `.NNN` suffix. Object data that clashes with an unrelated datablock
  keeps the suffix the append gave it. Materials and node groups still pair by name, so
  a user material that took a target material's name is reverted with it.
- **Copies within a turn**: an agent copy shares its original's uid until the turn
  finishes, so an Interrupt → Restore or checkpoint restore in that turn tells them
  apart by name and by which one is being removed.
- **Ambiguous user copies**: if the user renames the agent's object away from every
  recorded name, drops it from the target list and also copies it, Restore cannot tell
  which is the agent's and keeps both.
- **History scope** matches the restore scope above: images, objects only referenced
  by modifiers and anything outside the target keep their current state.
- **Extra skills in context**: the session's skill list also includes the bundled CLI's
  own skills. They cannot be invoked under `dontAsk`, but they take up context. (The
  user's own skills no longer load: the CLI runs with Whittle's private configuration
  folder.)
- **Sketching is only tested headlessly.** Background Blender cannot draw with the real
  tool or move a viewport, so the draw-tool path (Surface placement, the strokes and
  attributes the brush writes), the watcher timer in a live UI, undo across sketching,
  and the panels' drawing are unverified until tried by hand. Tests use data-API strokes
  and fake viewports built from real camera matrices.
- **Which viewport**: the watcher tags strokes using the viewport whose view changed
  most recently (or the largest). With several 3D viewports, a stroke drawn in a still
  one right after orbiting another can get the other's view. Capture View is exact.
- **Tagging timing** is verified headlessly (a data-API stroke plus a depsgraph update);
  that the draw tool's stroke fires the handler before the user can orbit is expected
  but unconfirmed in the GUI. Viewport discovery is tested with fake screens.
- **Sketch key at the lowest frame**: the dope sheet shows the sketch layers' key far
  to the left of the scene range.
- **Camera lens shift** is not represented in views captured through a scene camera.
- **Vertex colours** do not show in the self-check renders (Workbench MATERIAL colour
  mode), so the recipes prefer per-face materials with `diffuse_color` set.

## Manual GUI checklist

Things only a person at a real Blender can confirm; the first manual pass covered the
rest (see Known gaps), and `./screens.sh` shows how the panel looks in each state. The
steps use the redesigned sidebar's names (`docs/ui.md`; its §9 maps them to the old
panels). Each step can use the real agent or **Development → Fake Script** (Developer
Extras on; the scripts named are under `tests/fixtures/fake/`).

1. **Restart**: save, quit, reopen and send. The conversation and the 🕘 history popover
   show the saved session, and the agent resumes it (no context-lost note in the turn).
2. **Start row → Blank** in a scene with the default cube selected: nothing is added to the
   scene, the cube is deselected and untouched, and the target line says Claude makes new
   objects. The first Send makes new objects, which become the targets.
3. **Start row → Primitive** → Cylinder: it stands at the 3D cursor and is the only
   target, and it is selected, so Auto keeps it.
4. **Asset Browser**: right-click an object asset from a library → Start Whittle From Asset:
   it is appended at the cursor, is the target, and Blender File view shows no library.
5. **References**: add two with 📎, pin one (click its chip → Pin to Every Request; the
   chip gets a pressed pin), send a turn that succeeds: only the pinned one stays. Its
   chip → Place Facing the View: a half-transparent image faces the viewport;
   Front / Right / Top place it behind the model from that side.
6. **Settings change** (`stream.json`, then `ask.json`): run a turn, change Development →
   Fake Script, send again: the new script plays. Change Defaults → Triangle Budget in
   the preferences and send: the agent is started again ("Starting Claude…" in the turn)
   and the turn runs. Then pick another model with the button beside Send and send: the
   turn runs on it without a restart (the model preference only sets new chats' model).
   Pick Low under Effort in the same menu and send: the turn runs at it, again without a
   restart, and the agent popover says `Effort: Low`.
7. **Amend right after Send** (`amend.json`): type into the amend field and press Amend
   (it appears once text is typed) straight after Send, before the turn starts: the turn notes that the amendment waits
   for the turn, then that it was delivered.
8. **Failed turn** (`fail_untouched.json`): the first turn fails without editing; it shows
   once in the conversation with Retry, the prompt box stays empty, and the history
   popover has no new node, keeps the start highlighted and offers the start row. The second fails after an edit and appears as a
   failed node.
9. **Compare targets**: at a node whose targets are Crate and Crate_Lid, ⋯ → Compare With
   Current on an earlier turn without the lid, Swap, Done: both are targets again (and
   selected, with Auto on).
10. **Auto targets**: click another object in Object Mode: the target line follows it.
    Click empty space: the active object stays the target. Start sketching: the target
    does not change. Turn Auto off, select something else: the list stays.
11. **Branching in the conversation**: ⋯ → Edit & Resend on a turn, change the prompt,
    Send as Branch: the turn's bubble shows ◂ 2/2 beside its ⋯; ◂ brings back the
    first branch's scene, and Ctrl+Z goes back again.
12. **The real buttons**: the history button beside Send opens its popover (its tooltip
    says History) and ⋯ on a turn opens its menu where the pointer is (the screenshots open them from Python); clicking a row
    title in the popover goes back to it; the header gear opens the agent popover; the
    ⋯ beside Add <object> opens the target options; a turn's "Used N tools" and a tool
    call inside it open and stay open across redraws. A stopped sketch turn: its strokes
    stay, and the stroke count's 🗑 clears them.
13. **API key**: with no key in the preferences and no `ANTHROPIC_API_KEY` in Blender's
    environment, type a prompt and Send: nothing starts, the prompt stays in the box and
    the box at the top asks for an API key, with Preferences and Get a Key (which opens
    the Console). Paste a key in the preferences: the box goes, and Send runs the turn.
    With a wrong key, Send: the turn fails and the box says the API key was refused.
14. **Crash**: kill the agent process during a turn: one box says Claude stopped
    unexpectedly; Restart and Retry starts it again and resends the turn.
15. **Chats**: click the title in the header: the chat menu opens under it. New Chat, a
    turn, then the first chat's title: its conversation is back and the scene is
    unchanged; Send resumes that conversation (no context-lost note). Save: the title bar
    shows no `*` afterwards. Delete the other chat from its 🗑 and confirm, save again:
    the file is smaller.
16. **The file carries its chats**: save, quit, delete the file's cache
    (`<user dir>/cache/<file id>/`, the newest folder there), reopen: every chat is in
    the menu with its turns, thumbnails and transcripts, and Send resumes. The file's
    folder holds only the `.blend` (and its `.blend1`).
17. **A crash keeps the chats**: save, send a turn, kill Blender (`kill -9`), start it
    and open the file: the unsaved turn is in the conversation.
18. **A chat from another machine**: open a `.blend` with chats saved by another
    install (or point `WHITTLE_USER_DIR` at an empty folder and reopen one of your own):
    the current chat shows `Continue this chat?`, Send is disabled and its tooltip says
    why. Continue: the box goes, Send works, and reopening the file does not ask again.
19. **The same file twice**: open a saved file in two Blenders: the second shows the dim
    "open in another Blender" line, and so does the first at its next redraw; quit
    the second and the first's line goes.
20. **Shift+Alt+C**: the popup shows the dim hint under its field, whole, at your UI
    scale; while Claude asks, the field's placeholder is `Ask Claude…` like the sidebar's.
21. **Tablet keys and markers**: map the tablet's express keys to Shift+Alt+D, N, V and
    Enter. With the pen over the viewport: D starts sketching, N cycles the type (the
    sidebar names it), V captures a view, D stops and starts again, Enter sends. Draw
    from two angles, orbit away: a camera marks each view; tap one with the pen: the
    viewport goes back there, and a stroke drawn now joins that view (its row's count
    goes up, no new view). Untick Markers While Sketching: they go.
22. **Per-file settings** (`stream.json`): the agent popover's For This File shows the
    preferences' triangle budget and style notes, each "(default)" with its reset button
    greyed out. Change the budget: the "(default)" goes and the reset button wakes. Send:
    the agent is started again and the turn's `request.json` carries the file's budget.
    Save, reopen: the value is still there; another file still shows the default. Reset:
    "(default)" is back.
