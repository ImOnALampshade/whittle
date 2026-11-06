# Protocol and file formats

Whittle has three formats a contributor needs to know:

- the **bridge protocol**, JSON lines between Blender and the agent process
  ({py:mod}`whittle.protocol`);
- the **request bundle** and **session folder**, what a turn leaves on disk
  ({py:mod}`whittle.formats`, {py:mod}`whittle.tree`);
- **chat storage**, the cache folder and what the `.blend` keeps
  ({py:mod}`whittle.chats`, {py:mod}`whittle.caches`).

All of these modules are stdlib only, so both processes and the agent tests share one
reader. [Architecture overview](architecture.md) says how the processes fit together, and
[Shared modules API](../reference/shared.md) has the functions. To add a tool, see
[Agent tools and skills](agent-tools.md).

The turn, bundle and chat examples below are real. They come from one run of the
[fake agent](setup-and-testing.md#the-fake-agent), which plays scripted turns with no API
key: a turn sketched on the crate, a second turn, another take on the second turn, and a
save. Only paths and long lines are shortened. The fake agent differs from the real one in
small ways, which this page points out where it matters.

```{figure} ../images/develop-protocol/history.png
:alt: The history popover. Start: Crate, then "Add a lid that overhangs the crate slightly", which has two children, "Make the wood darker" and the selected "Make the wood lighter".

The example run in the history popover: nodes `n0001`, `n0002` and, current, `n0003`.
```

## The bridge

### Framing

One TCP connection per agent process, on `127.0.0.1`. Blender listens on a free port, and
starts the agent with `--port <port>` and a random token in the `WHITTLE_TOKEN`
environment variable.

Each message is one UTF-8 JSON object on one line, ended by `\n`. `protocol.encode` writes
it with no spaces and `ensure_ascii=False`. `protocol.LineDecoder` keeps a partial line
until the rest arrives.

A line may be up to `MAX_LINE`, 16 MiB. A longer line, invalid JSON, a `v` other than
`VERSION` (1) or an unknown `type` raises `ProtocolError`. Blender then fails the agent;
the agent stops reading and exits. Images never go over the socket: a message carries a
path, and the other side reads the file.

### Handshake

The agent speaks first:

```json
{"v":1,"type":"hello","token":"8f3c…","protocol":1,"pid":48213,"agent_version":"0.1.0","mode":"fake"}
{"v":1,"type":"welcome","protocol":1}
```

`mode` is `"sdk"` or `"fake"`. Blender compares the token with `hmac.compare_digest` and
checks `protocol`. On a match it closes the listener, so nothing else can connect, and
answers `welcome`. Anything else fails the agent. The agent waits 10 s for `welcome`
(`connection.HANDSHAKE_TIMEOUT`), and Blender 30 s for the handshake
(`process.HANDSHAKE_TIMEOUT`).

### Messages

Every message has `v` and `type`:

| `type` | Fields | Direction |
| --- | --- | --- |
| `hello` | `token`, `protocol`, `pid`, `agent_version`, `mode` | agent to Blender, first line only |
| `welcome` | `protocol` | Blender to agent, the reply to `hello` |
| `call` | `id`, `method`, `params` (object) | either way |
| `result` | `id`, `ok`, then `data` or `error` | either way, the reply to the `call` with that `id` |
| `event` | `name`, `data` (object) | agent to Blender only, no reply |

Ids are strings, the sender's prefix and a counter: `b1`, `b2` from Blender, `a1`, `a2`
from the agent. A result for an id nobody is waiting on is logged and dropped.

```json
{"v":1,"type":"call","id":"a1","method":"inspect","params":{"query":"summary"}}
{"v":1,"type":"result","id":"a1","ok":true,"data":{"objects":[],"targets":[],"notes":[]}}
{"v":1,"type":"result","id":"b2","ok":false,"error":{"code":"no_session","message":"start_session first","detail":null}}
```

### Errors

`error` is `{"code", "message", "detail"}`, where `detail` is a traceback or null. Codes
are `protocol.ErrorCode`:

| Code | When |
| --- | --- |
| `bad_request` | A parameter is missing or of the wrong type, or the call makes no sense now (`checkpoint` outside a turn). |
| `unknown_method` | No handler for the method. |
| `not_found` | A named object, view or checkpoint does not exist, or `amend` names a turn that is no longer running. |
| `busy` | `submit` while a turn is running. |
| `interrupted` | A queued agent call dropped because the user stopped the turn, or an `ask` cancelled. |
| `no_session` | `submit` or `amend` before `start_session`. |
| `agent_crashed` | Made locally for pending calls when the connection goes. Never sent. |
| `timeout` | Made locally on the agent side when a call waited too long. Never sent. |
| `internal` | An unexpected exception in a handler (`detail` is the traceback), a `start_session` whose SDK connect failed, or a result that cannot be encoded (`detail` null in both). |

An amendment is what the user adds while a turn runs, more text or more strokes; see
[Prompts and targets](../guides/prompting.md#amend-a-running-turn).

An error in the Python the model sent to `exec` is not a bridge error. `exec` still answers
`ok: true`, with the Python error in `data.error`, because the model needs to read it and
try again.

### Blender to agent calls

The agent handles these in `agent/dispatch.py`, which checks parameters before the runner
sees them.

| Method | Params | `data` |
| --- | --- | --- |
| `start_session` | `session_dir`, `store_dir` (or null), `model`, `effort`, `resume` (or null), `fork`, `resume_at` (or null), `settings` | `{}`, once the SDK client has connected. Replaces any live client. |
| `submit` | `turn_id`, `bundle_dir` (absolute), `prompt`, `context` (list of str), `model` (or null), `effort` (or null) | `{"accepted": true}` |
| `amend` | `turn_id`, `amend` (int), `text` (may be `""`), `bundle_dir` (or null) | `{"queued": true}` |
| `interrupt` | `turn_id` | `{}` |
| `ping` | none | `{"time": float}` |
| `shutdown` | none | `{}`, and the agent closes the SDK client and exits |

`store_dir` is the chat's `sdk/` folder, where the SDK transcripts go; see
[Chat storage](#chat-storage).

`effort` is one of `low`, `medium` and `high` (`models.EFFORTS`); `start_session` defaults
it to `high`. A `submit` whose `model` or `effort` differs from the session's switches the
live session first. See [Models and effort](../guides/models.md).

`settings` is `prefs.session_settings()`: integers `poly_budget`, `self_check_rounds` and
`render_size`, strings `style_file` and `style_guide` (the path and the guide's text as last
read, or no text at all for a guide this install has not approved, whatever a Read Now
found), the boolean `style_incomplete` (part of the guide did not load), and optionally
`max_turns` and `max_budget_usd`, which go to the SDK. `resume`, `fork` and `resume_at`
come from `tree.session_plan`; see [Node](#node) below.

`context` is lines from Whittle that go before the prompt, such as the note a branch
leaves for the agent.

### Agent to Blender calls

These are queued and run on Blender's main thread in `addon/commands.py`
(`build_handlers`). Every result but `ask`'s unattended one carries `notes`, a list of
one-off messages for the model. Today that is the warning that the user pressed Ctrl+Z
during the turn.

| Method | Params | `data` |
| --- | --- | --- |
| `exec` | `code`, `label` | `stdout`, `error` (`{type, message, traceback}` or null), `diff`, `notes` |
| `inspect` | `query` (`summary`, `object`, `materials`, `node_groups`, `scene`), `name` for `object` | depends on the query |
| `render` | `mode`, one of `view` and `camera`, `size` | `path`, `strokes_path`, `width`, `height`, `ms`, `notes` |
| `checkpoint` | `label` | `checkpoint_id`, `label`, `restorable`, `objects`, `notes` |
| `restore_checkpoint` | `checkpoint_id` | `restored`, `removed`, `notes` |
| `ask` | `question`, `choices` | `answer`, `notes`, sent when the user answers. With nobody to ask, in background Blender, `{"answer": "", "unattended": true}` at once. |

`diff` is `{"added": [name], "removed": [name], "changed": [{"name", "fields"}]}`.

`render` takes a `mode` from `formats.RENDER_MODES`: `shaded`, `wireframe`, `matcap` or
`overlay`. Giving both `view` and `camera`, or neither, is `bad_request`; so is `overlay`
without a `view`. `camera` is `{"location", "look_at", "lens_mm"}`. `size` runs from 64 to
1024 and defaults to the session's `render_size`.

A call waits on the agent side for 300 s (`Connection.call`), except `exec`,
`restore_checkpoint` and `ask`, which wait for as long as they take: Blender cannot stop
code once it runs, and a person can take their time.

On the Blender side a tick starts no new call once 30 ms have passed (`TICK_BUDGET`), and
runs at most one `render` (`SLOW_METHODS`). A call already running is never cut short.
`exec`, `render`, `checkpoint` and `restore_checkpoint` (`SCENE_METHODS`) wait while the
user is in a modal operation, for 10 s at most (`MODAL_WAIT`). Calls that only read go at
once.

### Events

Every event's `data` has `turn_id`, null outside a turn.

| Name | `data` beyond `turn_id` |
| --- | --- |
| `status` | `state`, `detail`. States: `idle`, `connecting`, `running`, `waiting_user`, `interrupting`, `session_ended`. |
| `turn_started` | none |
| `text` | `text`: a whole assistant text block. Partial streaming is off. |
| `thinking` | `text` |
| `tool_use` | `tool_use_id`, `tool` (the short name), `input` |
| `tool_result` | `tool_use_id`, `is_error`, `summary` (the first 500 characters), `images` (paths) |
| `turn_finished` | `session_id`, `subtype`, `is_error`, `interrupted`, `cost_usd`, `session_cost_usd`, `num_turns`, `duration_ms`, `result_text`, `errors`, `too_large`, `amends_undelivered`, `message_uuid` |
| `amend_delivered` | `amend`, `via` (`tool_result` or `query`) |
| `error` | `code`, `message`: a failure the agent survives, such as `connect_failed` |
| `log` | `level`, `message` |
| `models` | `models` (ids), `source` (`api` or `cli`), once per process, after its first session connects |

`session_ended` means the SDK session stopped while the process lives on. Blender then
starts a new session for the next run. If a `submit` overtakes that status and comes back
`no_session`, `TurnController` starts a session and sends the same bundle again under the
same node.

### One turn

The sketched turn from the example run, in order, with the start of it as the real runner
sends it: `turn_started` and `status` go out before the result of `submit`, because the
runner sends them while it handles the call. The fake agent answers `submit` first and
sends those two events after.

```text
Blender                                       agent
  call b2 submit {turn_id: n0001, ...}   -->
                                         <--  event turn_started
                                         <--  event status running
                                         <--  result b2 {accepted: true}
                                         <--  event text "I'll add a lid ..."
                                         <--  event tool_use exec
                                         <--  call a1 exec {code, label}
  result a1 {stdout, error, diff, notes} -->
                                         <--  event tool_result
                                         <--  event tool_use render
                                         <--  call a2 render {view: 1, mode: overlay}
  result a2 {path, strokes_path, ...}    -->
                                         <--  event tool_result
                                         <--  event tool_use render
                                         <--  call a3 render {camera, mode: shaded}
  result a3 {path, strokes_path, ...}    -->
                                         <--  event tool_result
                                         <--  event text "The lid sits ..."
                                         <--  event turn_finished
                                         <--  event status idle
```

The `exec` call's reply, then the end of the turn:

```json
{"v":1,"type":"result","id":"a1","ok":true,"data":{"stdout":"lid Crate_Lid\n","error":null,"diff":{"added":["Crate_Lid"],"removed":[],"changed":[]},"notes":[]}}
{"v":1,"type":"event","name":"turn_finished","data":{"turn_id":"n0001","session_id":"fake-fb77ee69","subtype":"success","is_error":false,"interrupted":false,"cost_usd":0.0,"num_turns":5,"duration_ms":160,"result_text":"Added a lid.","errors":[],"too_large":false,"amends_undelivered":[],"message_uuid":"fake-msg-6d052ac4"}}
```

The real runner also sends `session_cost_usd` in `turn_finished`; the fake agent leaves it
out. `too_large` is true when the turn failed because its images were too big for one request.

## Files on disk

Most JSON files have `format` and `version` keys; `camera.json`, `in-use.json`, the
`open-<key>.json` marks and the `packed/` records do not. All are UTF-8. `formats.write_json_atomic` writes a temp file,
then replaces the target through `platforms.replace`, so a reader never sees half a file.
`formats.read_json` refuses a file nested more than 1000 deep without parsing it.
Validators raise `FormatError`, naming the file and the key.

Times differ by file. `session.json` is to the second (`2026-11-04T21:41:08+0000`, from
`tree.now_iso`). The chat files are to the millisecond, so two turns ending in one second
still sort (`2026-11-04T21:41:07.794+00:00`, from `chats.now_iso`).

## The request bundle

Everything the agent gets for one turn, written by `addon/bundle.py` before the `submit`.
It lives at `nodes/<node id>/request/`, and `bundle_dir` is its absolute path.

```text
request/
  request.json
  strokes.json
  views/<view id>/camera.json
  views/<view id>/overlay.png     a render from the view, strokes drawn over it
  views/<view id>/strokes.png     the strokes alone, on transparency
  refs/<name>.<ext>               copies of the attached reference images
```

The writer works in a hidden sibling folder, checks it with `formats.read_bundle`, then
renames it into place, so a bundle is whole or absent.

`views` holds the views the strokes use. A request without strokes gets the current view
alone, the one new strokes go to, and with no views at all there is no `views/` folder. An
overlay draws all of the bundle's strokes, not only those tagged with its view.

```{figure} ../images/develop-protocol/overlay.png
:alt: The crate from a three-quarter view, a red closed stroke above its top and another on its front face.

`views/1/overlay.png` from `n0001`'s bundle, the sketched turn, whose strokes use views 1
and 2. It is shown in Blender's Image Editor.
```

### request.json

`read_bundle` needs every key here but `target_collection`. This is `n0003`'s, a request
with no strokes, so `views` holds the current view only, here also the latest.

```json
{
 "format": "whittle.request",
 "version": 1,
 "node": "n0003",
 "parent": "n0001",
 "prompt": "Make the wood lighter.",
 "target": [
  {"uid": "29d654bc97d143fda6fc9742eee04844", "name": "Crate", "type": "MESH"},
  {"uid": "9c3cff98b5394d5a9a90c6ed0c323571", "name": "Crate_Lid", "type": "MESH"}
 ],
 "views": [2],
 "units": {"system": "METRIC", "scale_length": 1.0},
 "settings": {"self_check_rounds": 3, "poly_budget": 2000, "style_file": ""},
 "refs": [],
 "amend": null,
 "target_collection": null
}
```

| Key | Meaning |
| --- | --- |
| `node`, `parent` | This turn's node and its parent. `parent` may be null. |
| `prompt` | What the user wrote. |
| `amend` | The amendment number in an amend bundle, else null. |
| `target` | `uid` is the object's `whittle_uid` property, so a renamed target is still found. |
| `views` | View ids, each with a folder under `views/`. |
| `refs` | Paths inside the bundle. An absolute path, a drive or `..` is refused. |
| `units` | From `scene.unit_settings`. |
| `settings` | Three of the session settings (`bundle.SETTINGS_KEYS`); `render_size` is not one. `style_file` is the path, not the guide's text. An older bundle's other keys are ignored. |
| `target_collection` | The collection new objects go in, when the target is one. Optional when reading. |

### strokes.json

`{"format": "whittle.strokes", "version": 1, "strokes": [...]}`. One stroke from `n0001`'s
bundle, cut to its first point:

```json
{
 "index": 2, "view": 2, "cyclic": true,
 "points": [[0.09, -0.2501, 0.38]],
 "radius": [0.006],
 "opacity": [1.0],
 "on_surface": [true],
 "normal": [[0.0, -1.0, 0.0]],
 "hit_object": ["Crate"]
}
```

`points` are world-space positions. The other five lists run in parallel with `points`,
one entry per point; `normal` and `hit_object` are null where the point hit nothing. Every
stroke needs at least one point and a `view` the request lists.

### camera.json

One per view, read into `formats.View`:

| Key | Meaning |
| --- | --- |
| `id` | The view id. It must match the folder name. |
| `view_matrix`, `window_matrix` | 4 by 4 row-major lists, from `RegionView3D`, or from the scene camera in camera view. |
| `is_perspective` | Whether the projection is perspective, read from `window_matrix`. |
| `width`, `height` | The region's size in pixels, or the render size in camera view. |
| `from_camera` | The scene camera's name in camera view, else null. |
| `camera` | `matrix_world`, `type` (`PERSP` or `ORTHO`), `angle`, `ortho_scale`, `sensor_fit` (`HORIZONTAL` or `VERTICAL`), `clip_start`, `clip_end`. |

`camera` is worked out at capture, so the renderer rebuilds the view without deriving
anything.

### Amend bundles

An amendment with strokes writes `nodes/<node id>/amend-<n>/`, the same layout with
`request.amend` set to `n`, `prompt` set to the amendment's text, and only that
amendment's strokes and views. A text-only amendment writes none, and its `amend` call
has `bundle_dir` null.

## The session folder

One chat's history. `formats.SessionDir` builds these paths, so use it rather than joining
them by hand.

```text
<session folder>/
  session.json                the history tree
  .system_prompt.md           the agent's system prompt, never packed
  compare/live.blend          the live scene while a comparison runs
  nodes/<node id>/
    target.blend              the target after this node
    target.json               its manifest, for restoring
    thumb.png                 128 px thumbnail
    transcript.jsonl          the turn's events
    request/                  the request bundle (none for the root)
    amend-<n>/                amend bundles
    renders/                  001-v1-overlay.png, 002-cam-shaded.png, ...
    checkpoints/              start.blend, c1.blend, ... each with a .json manifest
```

Node ids are `n` and at least four digits (`formats.node_id`). A number is not reused
while its folder exists; a turn that never ran loses its folder, and the next run takes
the freed number. Render names are a sequence number, `v<view>` or `cam`, and
the mode. An overlay render also leaves `<name>-strokes.png`, which `strokes_path` names.

### session.json

`tree.write_session` validates before it writes, and `tree.read_session` marks any turn
still `running` as `failed`, since nothing can be running in a file just read.

```json
{
 "format": "whittle.session",
 "version": 1,
 "created": "2026-11-04T21:41:08+0000",
 "root": "n0000",
 "current": "n0003",
 "nodes": {"n0000": {}, "n0001": {}, "n0002": {}, "n0003": {}}
}
```

`current` is the node the scene reflects. A history that cannot be read is moved aside as
`session.json.bad-<time>` when the next turn starts a fresh tree.

### Node

`n0001`, the turn both branches grow from:

```json
{
 "id": "n0001",
 "parent": "n0000",
 "children": ["n0002", "n0003"],
 "created": "2026-11-04T21:41:08+0000",
 "status": "complete",
 "label": "Add a lid that overhangs the crate slightly.",
 "prompt": "Add a lid that overhangs the crate slightly.",
 "agent_session_id": "fake-fb77ee69",
 "continued_session": null,
 "agent_message_uuid": "fake-msg-6d052ac4",
 "cost_usd": 0.0,
 "num_turns": 5,
 "duration_ms": 160,
 "kept_partial": false,
 "restored": false,
 "snapshot": true,
 "created_uids": ["9c3cff98b5394d5a9a90c6ed0c323571"],
 "folded": false,
 "too_large": false
}
```

| Key | Meaning |
| --- | --- |
| `status` | `running`, `complete`, `interrupted` or `failed` (`tree.STATUSES`). |
| `label` | The prompt's first line, cut to 60 characters; `(sketch only)` without a prompt; `Start` on the root unless a start point names it. |
| `agent_session_id` | The SDK session at the end of the turn. |
| `continued_session` | The SDK session the turn carried on, set at submit. Optional when reading. |
| `agent_message_uuid` | The turn's last transcript message: where a branch from here cuts the conversation. |
| `kept_partial`, `restored` | An interrupted turn whose edit was kept, or whose target was put back. |
| `snapshot` | `target.blend` was written, so Restore can use it. |
| `created_uids` | The `whittle_uid` of each object the agent made this turn. |
| `folded` | A failed turn that changed nothing, hidden in its parent. Only a failed leaf can be folded. Optional when reading. |
| `too_large` | A failed turn whose images were too big for one request, so the sidebar offers Edit and not Retry. Optional when reading. |

`tree.session_plan` reads these to choose how the next turn reaches a matching
conversation. In the example, `n0002` carried on `fake-fb77ee69`, the session of its
parent. `n0003` branches from `n0001` after that session moved on, so it forks: it gets
`resume` set to that session, `fork` true, `resume_at` set to `fake-msg-6d052ac4`, and a
session of its own, `fake-f2544dde`. The user's view of this is in
[History and branches](../guides/history.md).

### target.json

The manifest beside each snapshot, also written for each checkpoint. Restore uses it to
pair appended datablocks with their names.

```json
{
 "format": "whittle.target",
 "version": 1,
 "objects": [
  {"uid": "29d654bc97d143fda6fc9742eee04844", "name": "Crate", "type": "MESH", "data_name": "Crate",
   "collections": [""], "parent": null, "parent_uid": null, "materials": ["Wood"], "node_groups": []}
 ],
 "datablocks": {"materials": ["Wood"], "node_groups": [], "images": []}
}
```

A collection name of `""` is the scene's master collection. An optional `loose` key,
`{"materials": [...], "node_groups": [...]}`, lists datablocks written for their own sake
that no object in the snapshot uses.

### transcript.jsonl

One line per record, appended as it happens. The agent's events for the turn are stored as
received, beside `local` records of what happened on Blender's side. The first line of a
node is always its `submit`:

```json
{"v":1,"type":"local","name":"submit","data":{"node":"n0003","prompt":"Make the wood lighter.","bundle_dir":"<session folder>/nodes/n0003/request","targets":["Crate","Crate_Lid"],"parent":"n0001","context":["You are continuing from history node n0001 (Add a lid that overhangs the crate slightly.). Changes made on other branches after it do not exist in the scene."]}}
{"v":1,"type":"event","name":"turn_started","data":{"turn_id":"n0003"}}
```

| Local record | `data` |
| --- | --- |
| `submit` | `node`, `prompt`, `bundle_dir`, `targets`, `parent`, `context` |
| `amend` | `amend`, `text`, `bundle_dir`, `strokes` |
| `amend_returned` | `amend`, `reason` |
| `answer` | `question`, `answer` |
| `interrupt` | `mode`: `keep` or `restore` |
| `restored` | `objects` |
| `undo` | none |
| `warning` | `text`: a warning that belongs to the turn, such as a lost resume |

The sidebar rebuilds a finished conversation from this file, and **Open Transcript** turns
it into text (`addon/transcript.py`), so a new event needs a line there too.

## Chat storage

A file's chats live in a hidden cache, and the `.blend` holds a packed copy from the moment
it is saved. Nothing is ever written beside the `.blend`. How this looks to a user is in
[Chats](../guides/chats.md).

```text
<user dir>/
  install.json                 this install's id
  guides.json                  the style guides this install approved
  cache/open-<key>.json        a running Blender's mark: the saved file it has open
  cache/<file id>/             the cache root
    cache.json                 the file it belongs to
    in-use.json                the Blender that has it open
    chats.json                 the index the chat menu draws from
    chats/<chat id>/           one chat, also the agent's working folder for it
      chat.json
      session.json, nodes/     the session folder above
      sdk/<session id>.jsonl   the chat's SDK transcripts
    packed/<chat id>.zip       the chat as last written into the .blend
    packed/<chat id>.json      {"digest", "fingerprint", "size"}
```

File ids are `f` and 16 hex digits, chat ids `c` and 8, and install ids `i` and 16. The
SDK transcripts are in `sdk/` so they travel with the chat (`agent/store.py`). A cache not
used for 30 days is deleted (`caches.MAX_AGE`), never one in use.

### chats.json

```json
{
 "format": "whittle.chats",
 "version": 1,
 "current": "cbc09a364",
 "chats": {
  "cbc09a364": {
   "title": "Add a lid that overhangs the crate…",
   "created": "2026-11-04T21:41:07.794+00:00",
   "updated": "2026-11-04T21:41:09.517+00:00",
   "turns": 3,
   "size": 776666,
   "digest": "296cdfed7657d10b10f57445a81ee63ce79f0f8e14940e0168900f35f949a004",
   "model": "claude-opus-5-5",
   "origin": "id2b03283df2b21b3",
   "adopted": [],
   "effort": null
  }
 }
}
```

| Key | Meaning |
| --- | --- |
| `updated` | The end of the chat's last turn, else `created`. |
| `turns` | Nodes other than the root that are not folded, on every branch. |
| `size` | Bytes it adds to the `.blend`. |
| `digest` | sha256 of the zip the `.blend` last got, or null. |
| `model`, `effort` | The chat's own, or null for the default. A chat keeps the model its first turn was sent with. |
| `origin`, `adopted` | The install that made the chat, and those that continued it after asking. |

`model`, `effort`, `origin` and `adopted` are optional when reading. A missing or
unreadable index is rebuilt from the chat folders.

### chat.json

The chat's own record, which the index can be rebuilt from:

```json
{
 "format": "whittle.chat",
 "version": 1,
 "id": "cbc09a364",
 "title": "Add a lid that overhangs the crate…",
 "title_custom": false,
 "created": "2026-11-04T21:41:07.794+00:00",
 "model": "claude-opus-5-5",
 "effort": null,
 "origin": "id2b03283df2b21b3",
 "adopted": []
}
```

`title_custom` is true once the user has named the chat, so the first turn does not rename
it.

### cache.json, in-use.json, open marks, install.json

```json
{"format": "whittle.cache", "version": 1, "id": "fbca47cbd9c82f98f", "path": "/home/you/crate.blend", "used": 1793828469.554102, "base": "6c2516119bbed376…"}
{"pid": 48190, "host": "workstation"}
{"pid": 48190, "host": "workstation", "path": "/home/you/crate.blend"}
{"format": "whittle.install", "version": 1, "id": "id2b03283df2b21b3"}
```

In `cache.json`, `path` is the `.blend` (null while unsaved) and `used` is seconds since
the epoch. `base` is `caches.state_stamp` of the file state the cache was last in step
with, or null. `in-use.json` goes when the file closes. A crashed Blender's claim names a
dead process, so it does not count.

`open-<key>.json` sits beside the caches, one per running Blender with a saved file open, with
or without a cache, so two Blenders on one file see each other even when it has no chats. It
goes when the file closes, and the cache clean-up removes a crashed Blender's.

### guides.json

```json
{"format": "whittle.guides", "version": 1, "guides": ["/home/you/project/style/crates.md"]}
```

Each entry is a `style.guide_key`: an approved guide's absolute path, tidied, in the
platform's case. It is read and written by `style.read_approved` and `style.write_approved`.
A record that cannot be read, or from a later version, approves nothing, and a later version's
is never overwritten. Nothing about approvals goes in the `.blend`.

### The packed zip

`chats.pack` zips the chat folder. It leaves out `compare/`, `nodes/*/checkpoints/`,
dotfiles and `.tmp` files. PNG and `.blend` members are stored as they are, since they are
compressed already, and the rest deflated. A `.jsonl` still being appended to is read up
to its last whole line.

A `.blend` is data from whoever made it, so `chats.unpack` checks every member path before
writing anything (no `..`, no absolute paths, no backslashes or colons) and refuses a chat
that would unpack to more than 4 GiB (`MAX_UNPACKED`). The folder appears whole or not at
all.

`chats.fingerprint` is a sha256 of each member's path, size and modification time. It is
cheap enough to take at every save, and `pack_all` packs a chat again only when it
changed.

### In the .blend

The payload sits on a Text datablock named `.whittle` (`addon/chats.py`), and only while a
file is being saved or just after it is loaded:

| ID property | Holds | Kept |
| --- | --- | --- |
| `whittle_file_id` | The file id | Always |
| `whittle_chats_index` | `chats.json` as a JSON string | From `save_pre` to `save_post`, and read and removed in `load_post` |
| `whittle_chats` | A group, chat id to the zip's bytes | The same |

So undo steps never copy the payload, and undo cannot roll a chat back. With the **Save
Chats in the .blend** preference off, the Text holds the file id alone.

On load, `Chats.reconcile` makes the cache match the file, and the file wins: a chat
folder that differs or that the file lacks is deleted, and chats the cache lacks are
unpacked when first used. The exception is a crash. When `base` equals the stamp of what
the file stores, the cache was built on exactly this file and went on without a save, so
it stays as it is.

## Changing a format

- **A new key** in a file: make it optional when reading, so older files and chats from
  other people's `.blend` files still load. The patterns are `_OPTIONAL_SPEC` in
  `tree.py`, `_ENTRY_OPTIONAL` in `chats.py` and `target_collection` in `formats.py`.
- **A breaking change**: raise the version. `protocol.VERSION` must match on both sides,
  or the handshake fails. `formats.VERSION` is checked on request, strokes, target, session
  and index files, so a saved `.blend` with the old number stops reading until you add a
  migration. `chats.py` writes its `1` literally, so change that too.
- **A new call**: add it to `protocol.Method`, and see [Extending Whittle](extending.md).
- **A new event**: add it to `protocol.Event`, handle it in `TurnController.on_event`, and
  give it a line in `addon/transcript.py`. If the sidebar shows it, it also needs a case in
  `Stream.append` (`addon/stream.py`).
- **Tests**: `tests/agent/test_protocol.py`, `test_formats.py`, `test_tree.py`,
  `test_chats.py` and `test_caches.py` run without Blender;
  `tests/blender/test_bundle.py` and `test_bridge.py` run inside it. See
  [Development setup and testing](setup-and-testing.md).
