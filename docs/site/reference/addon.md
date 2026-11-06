# Add-on API

The Blender side of Whittle, under `whittle/addon/`. It draws the sidebar, records the sketch,
starts the agent process and carries out the agent's calls on the scene. The package may import
`bpy` anywhere and never imports `whittle.agent`. It starts no threads: everything here runs on
Blender's main thread, from an operator, a handler or a timer.

This page is a map of the package, then the generated listing. The
[Architecture overview](../develop/architecture.md) follows a turn through these modules, and
[Extending Whittle](../develop/extending.md) says which ones a given change touches.

## The modules

**Settings and files**

- {py:mod}`~whittle.addon.prefs`: the add-on preferences, with defaults when the add-on is not registered, the last read of each style guide, and which guides may be read.
- {py:mod}`~whittle.addon.props`: per-scene state, `scene.whittle`, and keeping a file's `//` style guide path naming the same guide through a first save, Save As and undo.
- {py:mod}`~whittle.addon.paths`: where Whittle keeps its files and which Python runs the agent.
- {py:mod}`~whittle.addon.setup`: sets up the agent's private venv, and holds the operators behind the preferences' buttons.

**What the user marks up**

- {py:mod}`~whittle.addon.sketch`: the Whittle Sketch Grease Pencil object, and the session that watches the viewport while the user draws.
- {py:mod}`~whittle.addon.views`: camera snapshots taken from the 3D viewport, one per sketch view.
- {py:mod}`~whittle.addon.viewmarks`: the small camera in the viewport at each sketch view; clicking one moves the viewport back to it.
- {py:mod}`~whittle.addon.targets`: the target picker, an object list plus an optional collection.
- {py:mod}`~whittle.addon.autotarget`: makes the target list follow the selection when Auto is on.
- {py:mod}`~whittle.addon.refs`: reference images, attached to one request or pinned to the session.

**Reading and writing the scene**

- {py:mod}`~whittle.addon.bundle`: writes a request bundle from the live sketch.
- {py:mod}`~whittle.addon.render`: Workbench renders from sketch views or cameras the agent describes.
- {py:mod}`~whittle.addon.snapshot`: writes target objects out and restores them over the current datablocks.
- {py:mod}`~whittle.addon.execution`: runs agent code in the live scene and reports what changed.
- {py:mod}`~whittle.addon.meshcheck`: mesh health numbers and a weld, which agent code calls as `whittle.mesh_report` and `whittle.weld`.

**The link to the agent**

- {py:mod}`~whittle.addon.process`: the agent process: spawn, handshake, crash detection and shutdown.
- {py:mod}`~whittle.addon.bridge`: Blender's end of the bridge: a socket drained from a timer, and a queue that runs the agent's calls on the main thread.
- {py:mod}`~whittle.addon.commands`: the handlers for the agent's calls.

**Turns and what they leave behind**

- {py:mod}`~whittle.addon.turn`: runs turns, and owns the agent process, the command context and the stream.
- {py:mod}`~whittle.addon.stream`: the live transcript: entries for the sidebar, and a `transcript.jsonl` per turn.
- {py:mod}`~whittle.addon.transcript`: a session's full transcript as readable text, for a Text datablock.
- {py:mod}`~whittle.addon.history`: the history tree: a snapshot of the target per node, restoring and branching.
- {py:mod}`~whittle.addon.compare`: the A/B toggle between the live scene and another node, and the ghost, which shows the parent node as a wireframe.
- {py:mod}`~whittle.addon.start`: start points: what node 0 of the history is. It has nothing to do with starting the agent.
- {py:mod}`~whittle.addon.chats`: the open file's chats, stored in the `.blend` around a save and taken back out when the file opens.
- {py:mod}`~whittle.addon.models`: the model menu, and which model and effort the current chat runs on.

**The sidebar and the keys**

- {py:mod}`~whittle.addon.ui`: the Whittle tab in the 3D viewport sidebar.
- {py:mod}`~whittle.addon.conversation`: the turns the sidebar shows, from the history's start to its current node, then the running turn.
- {py:mod}`~whittle.addon.operators`: operators for sketching, views, submitting and driving the agent by hand.
- {py:mod}`~whittle.addon.previews`: thumbnails of render images for the sidebar.
- {py:mod}`~whittle.addon.editors`: shows images and texts in an editor, reusing an open one or else opening a new window.
- {py:mod}`~whittle.addon.enter`: Enter sends from the prompt box; Shift+Enter adds a line.
- {py:mod}`~whittle.addon.shortcut`: Shift+Alt+C, straight into typing a prompt with no mouse.
- {py:mod}`~whittle.addon.keys`: the default keys for sketching, Capture View and Send.

Two functions are how most code finds the running state. `turn.current()` returns the one
{py:class}`~whittle.addon.turn.TurnController`, or `None` when there is none, and
`history.active()` returns the {py:class}`~whittle.addon.history.History` of the running
controller or else of the current chat. The controller owns the
{py:class}`~whittle.addon.process.AgentProcess`, which owns the
{py:class}`~whittle.addon.bridge.Bridge`. The controller builds the
{py:class}`~whittle.addon.commands.CommandContext` and passes
`commands.build_handlers(...)` to the process, so the bridge can run the agent's calls without
importing `commands`.

The agent reaches the scene only through the bridge's queue and a `commands` handler. Draw code
writes nothing: `ui` is plain functions of a layout, which is what lets the tests drive them
with a recording layout.

`chats` and `models` each exist twice. {py:mod}`whittle.addon.chats` and
{py:mod}`whittle.addon.models` are the Blender half; {py:mod}`whittle.chats` and
{py:mod}`whittle.models` in the [shared modules](shared.md) do the work that needs no `bpy`.
The add-on imports the shared ones under another name, `chat_store` or `store`. In the same
way `bridge` speaks {py:mod}`whittle.protocol`, `bundle` writes through
{py:mod}`whittle.formats`, and `history` keeps its nodes with {py:mod}`whittle.tree`.

## Import order

The imports at the top of these modules have no cycle. They stack like this, foundations first:

```text
bridge  prefs  views  stream  keys  editors  previews  meshcheck    import no add-on module
paths  sketch  execution  conversation  transcript
process  render  targets  chats  viewmarks
bundle  refs  models
snapshot
commands  history
compare
turn
setup  autotarget
operators
enter  start  shortcut
props
ui
__init__
```

Each row imports only from rows above it in this block. Code that needs a module further down
the block imports it inside the function: `prefs` reaches `turn` from a property's update
callback, and `history.active()` reaches `turn`. Keep to this, because an import at
the top that points the other way is a circular import when Blender enables the add-on.

`stream` and `conversation` import no `bpy` at all.

## What `register()` sets up

`whittle.register()` imports this package, so `bpy` is only needed once Blender enables the
extension. {py:func}`whittle.addon.register` then, in order:

1. registers `CLASSES`, which joins each module's own `CLASSES` tuple. An operator lives with
   its feature rather than in `operators`, so a new module with Blender classes needs adding
   to this tuple.
2. adds the properties: `Scene.whittle`, and the `WindowManager.whittle_*` settings that must
   never be saved in a file. `props.register_props` sets them at run time, so the listing shows
   the `Scene.whittle` group and not those.
3. opens the thumbnail collection, adds the file and undo handlers below, adds the Asset
   Browser menu entry, and starts `autotarget`: its depsgraph and `load_post` handlers, its
   message-bus subscription and a one-shot timer for the first sync.
4. adds the keymap items of `enter`, `shortcut` and `keys`.
5. finds the chats of a file that is already open.

{py:func}`whittle.addon.unregister` undoes all of it, and also stops the sketch session, the
agent and any setup in progress.

The file and undo handlers are private to `whittle/addon/__init__.py`, so the listing leaves
them out. They are all persistent, and each does little more than call into a module:

| Blender handler | What runs |
| --- | --- |
| `load_pre`, `exit_pre` | End the sketch session, close the controller, `chats.release` |
| `load_post` | `compare.reset`, `props.forget_style_moves`, `prefs.forget_approvals`, drop any [ghost](../guides/history.md#see-the-last-change-as-a-ghost) (the wireframe of the turn before), `history.invalidate`, `chats.after_load`, `history.sync_from_scene`, then `prefs.read_own_style_guide` |
| `load_post_fail` | `chats.load_failed` |
| `save_pre` | `props.rebase_style_paths`, `transcript.keep_out_of_file`, `chats.before_save` |
| `save_post` | `props.settle_style_paths`, `chats.after_save`, `prefs.refresh_style_guides` |
| `save_post_fail` | `props.settle_style_paths`, `chats.save_failed` |
| `undo_pre` | `TurnController.before_undo` |
| `undo_post`, `redo_post` | `props.follow_style_paths`, `history.sync_from_scene`, `history.release_folded_strokes`, `compare.forget`, `sketch.after_undo`, `transcript.after_undo`, `TurnController.after_undo` |

[Undo](../guides/undo.md) describes what the user sees of the undo handlers, and
[Chats](../guides/chats.md) what the save and load ones keep.

Apart from `autotarget`'s first sync, timers are started where they are needed, not here: the
bridge's in `bridge.start_timer`, the sketch session's in
{py:class}`~whittle.addon.sketch.SketchSession`, the venv install's in `setup`, and in `shortcut`
the retry that picks the Whittle tab in a sidebar that has not drawn yet. Timers never fire under `blender -b`, so the controller and the sketch session both
take `use_timer=False`, and tests call `Bridge.tick()` themselves;
[Development setup and testing](../develop/setup-and-testing.md) has the helpers.

## Reading the listing

The build mocks `bpy`, so the Blender classes appear without Blender's half of them:

- **Operators.** `bl_idname` gives the operator's name: `WHITTLE_OT_copy_code` has
  `bl_idname = 'whittle.copy_code'`, which is `bpy.ops.whittle.copy_code()`.
- **Properties.** An operator's or a property group's property shows only its kind, as in
  `path: bpy.props.StringProperty`. The arguments, so the label, the default and the bounds,
  are not there; follow the class's **[source]**. The values users see are in [Settings](../guides/settings.md).
- **Private bases.** `_Panel`, `_HistoryOperator` and `_StartOperator` are not listed, so what
  a class gets from them is not listed with it. `WHITTLE_PT_main` shows no `bl_space_type`,
  and the history operators show no `node` property or `execute`.
- **Blender's overrides.** `draw`, `execute`, `invoke`, `poll` and the like mean what Blender
  says they mean, and most have no docstring.

Module constants, such as `CLASSES`, `HANDLERS` and `prefs.SESSION_SETTINGS`, are not listed at
all, whatever the mock does: autodoc only takes those with a doc comment, and these have none.
Look for them in the source.

<!-- api -->

## `whittle.addon`

```{eval-rst}
.. automodule:: whittle.addon
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.autotarget`

```{eval-rst}
.. automodule:: whittle.addon.autotarget
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.bridge`

```{eval-rst}
.. automodule:: whittle.addon.bridge
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.bundle`

```{eval-rst}
.. automodule:: whittle.addon.bundle
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.chats`

```{eval-rst}
.. automodule:: whittle.addon.chats
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.commands`

```{eval-rst}
.. automodule:: whittle.addon.commands
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.compare`

```{eval-rst}
.. automodule:: whittle.addon.compare
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.conversation`

```{eval-rst}
.. automodule:: whittle.addon.conversation
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.editors`

```{eval-rst}
.. automodule:: whittle.addon.editors
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.enter`

```{eval-rst}
.. automodule:: whittle.addon.enter
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.execution`

```{eval-rst}
.. automodule:: whittle.addon.execution
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.history`

```{eval-rst}
.. automodule:: whittle.addon.history
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.keys`

```{eval-rst}
.. automodule:: whittle.addon.keys
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.meshcheck`

```{eval-rst}
.. automodule:: whittle.addon.meshcheck
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.models`

```{eval-rst}
.. automodule:: whittle.addon.models
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.operators`

```{eval-rst}
.. automodule:: whittle.addon.operators
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.paths`

```{eval-rst}
.. automodule:: whittle.addon.paths
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.prefs`

```{eval-rst}
.. automodule:: whittle.addon.prefs
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.previews`

```{eval-rst}
.. automodule:: whittle.addon.previews
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.process`

```{eval-rst}
.. automodule:: whittle.addon.process
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.props`

```{eval-rst}
.. automodule:: whittle.addon.props
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.refs`

```{eval-rst}
.. automodule:: whittle.addon.refs
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.render`

```{eval-rst}
.. automodule:: whittle.addon.render
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.setup`

```{eval-rst}
.. automodule:: whittle.addon.setup
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.shortcut`

```{eval-rst}
.. automodule:: whittle.addon.shortcut
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.sketch`

```{eval-rst}
.. automodule:: whittle.addon.sketch
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.snapshot`

```{eval-rst}
.. automodule:: whittle.addon.snapshot
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.start`

```{eval-rst}
.. automodule:: whittle.addon.start
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.stream`

```{eval-rst}
.. automodule:: whittle.addon.stream
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.targets`

```{eval-rst}
.. automodule:: whittle.addon.targets
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.transcript`

```{eval-rst}
.. automodule:: whittle.addon.transcript
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.turn`

```{eval-rst}
.. automodule:: whittle.addon.turn
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.ui`

```{eval-rst}
.. automodule:: whittle.addon.ui
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.viewmarks`

```{eval-rst}
.. automodule:: whittle.addon.viewmarks
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.addon.views`

```{eval-rst}
.. automodule:: whittle.addon.views
   :members:
   :undoc-members:
   :show-inheritance:
```
