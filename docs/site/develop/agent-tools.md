# Agent tools and skills

What the agent can do, and what it is told. It has seven tools of Whittle's own, one tool
from the CLI (`Skill`), ten recipe skills and a system prompt. This page lists them as the
code defines them:

- `whittle/agent/tools.py` holds the tools, in `TOOLS`.
- `whittle/agent/plugin/skills/` holds the skills.
- `whittle/agent/system_prompt.md` and `whittle/agent/prompt.py` hold the prompt.

To add a tool or a skill, see {doc}`Extending Whittle <extending>`. The rules for wording any
of this text are in `docs/prompting.md`.

{doc}`Architecture overview <architecture>` shows how the pieces fit. This page uses these terms:

- **The CLI** is the bundled Claude CLI, which the SDK starts and which runs the model.
- A **turn** is one prompt from the user and everything the agent does for it.
- A **target** is an object the turn is meant to edit. A turn with no targets creates new objects.
- A **sketch view** is the viewpoint the user drew strokes from. Each has an id.
- The **request bundle** is the folder Blender writes for a turn, with the prompt, targets,
  strokes and images.
- The **session folder** is a chat's folder on disk, which holds its bundles and snapshots.
- An **amendment** is a message or strokes the user sends during a turn.

## What the agent is allowed

`runner.build_options` decides this when a session starts:

| Option | Value | Effect |
|---|---|---|
| `tools` | `["Skill"]` | The only built-in CLI tool. There is no file, shell or web tool, so the agent reaches the scene only through the tools below. |
| `allowed_tools` | `TOOL_NAMES` | The seven tools run without asking. |
| `permission_mode` | `"dontAsk"` | Anything else is refused rather than prompted for. |
| `mcp_servers`, `strict_mcp_config` | `blender` and `whittle` only | The two in-process servers from `build_servers`, and no others. |
| `setting_sources` | `[]` | No settings files are read. |
| `plugins`, `skills` | `agent/plugin`, `whittle:<name>` for each of `prompt.SKILLS` | The recipe skills, and only those. |
| `cwd` | the chat's session folder | |

## The tools

`TOOLS` maps a name to `(server, handler, description, schema, returns images)`. A tool's full
name is `mcp__<server>__<name>`; `TOOL_NAMES` lists them. Handlers are plain async functions
of `(ctx, args)`, so tests call them without the SDK, and `build_servers` wraps them for the
SDK's in-process servers.

| Tool | Full name | Reaches | Images | Reply deadline |
|---|---|---|---|---|
| `exec` | `mcp__blender__exec` | Blender | no | none |
| `inspect` | `mcp__blender__inspect` | Blender | no | 300 s |
| `render` | `mcp__blender__render` | Blender | yes | 300 s |
| `checkpoint` | `mcp__blender__checkpoint` | Blender | no | 300 s |
| `restore_checkpoint` | `mcp__blender__restore_checkpoint` | Blender | no | none |
| `request` | `mcp__whittle__request` | the request bundle on disk | yes | not a call |
| `ask` | `mcp__whittle__ask` | Blender, then the user | no | none |

The **description** in `TOOLS` is the man page the model reads. The sections below say what
each tool does in the code, which includes things the model is not told.

**Images** marks the tools built with `ToolAnnotations(maxResultSizeChars=4_000_000)`, so
their image results stay inline.

**Reply deadline** is how long the agent waits for Blender. 300 s is the default of
`Connection.call`. `exec` and `restore_checkpoint` have no limit because Blender cannot stop
code once it runs, so a timeout would only report as not done what may still complete. `ask`
waits on a person. The runner sets `MCP_TOOL_TIMEOUT` to 24 hours so the CLI does not time
that call out first.

### exec

Runs Python in the live scene. This is where every edit happens.

| Parameter | Type | Required | Meaning |
|---|---|---|---|
| `code` | string | yes | Python source to run. |
| `label` | string | no | A few words for the sidebar row. Without one, the row shows the code's first line. |

`handle_exec` in `addon/commands.py` first takes the targets and the objects made this turn out
of Edit Mode, because `obj.data` would be stale and what the code wrote would be lost on leaving.
`addon/execution.py` then runs the code on Blender's main thread:

- **Namespace.** One `ExecNamespace` holds the variables between calls. It starts with `bpy`,
  `bmesh`, `mathutils`, `math`, `Vector`, `Matrix` and `whittle`.
- **No time limit.** The call cannot be interrupted, and Blender is frozen until it returns.
  This is why the prompt asks for small steps.
- **Errors.** Every exception is caught, `SystemExit` and `KeyboardInterrupt` included, so
  agent code cannot quit Blender or stop the bridge's timer. The traceback starts at the
  agent's own code, and each run's source is registered so later tracebacks can show it.

The result is plain text with four parts: `stdout` (cut at 20,000 characters, with a note of
the full length), the error if there was one, a `scene diff` and any `note:` lines. The diff
compares a summary of every object before and after, and names what was added, what was
removed and which fields changed. A failed run comes back with `is_error` set.

The `whittle` object is `execution.WhittleHelper`:

| Call | Does |
|---|---|
| `whittle.targets()` | Lists the request's target objects as they are now. Found by `whittle_uid`, so a renamed target is still one. |
| `whittle.mesh_report(obj, evaluated=True)` | Measures a mesh in world space and returns a dict. `evaluated=False` measures `obj.data` without its modifiers. Raises `TypeError` for an object with no mesh geometry. |
| `whittle.weld(obj, dist=1e-4)` | Merges near-duplicate vertices, dissolves degenerate geometry, deletes loose vertices and recalculates normals outward on the object's own mesh. Returns `{"removed_verts": n}`. It does not fuse overlapping parts. |
| `whittle.view3d_override()` | A `temp_override` for the first 3D viewport, for the few operators that need one. Raises `RuntimeError` when there is none, as in background Blender. |

`mesh_report` returns `verts`, `faces`, `tris`, `quads`, `ngons`, `shells`, `open_edges`,
`bad_verts`, `flipped_edges`, `duplicate_verts`, `tiny_faces`, `self_intersections`, `volume`
and `watertight`, all from `addon/meshcheck.py`. The agent learns what they mean from the
`mesh-check` skill. `watertight` means closed, consistently wound and of positive volume, so
it is true for a part buried in a body too. `shells` and `self_intersections` show that case.

### inspect

Reads the scene without changing it and returns JSON.

| Parameter | Type | Required | Meaning |
|---|---|---|---|
| `query` | string | yes | One of the queries below. |
| `name` | string | with `object` | The object's name. Ignored by other queries. |

| Query | Returns |
|---|---|
| `summary` | `targets`, and for every object in the scene its type, transform, dimensions, parent, modifiers, materials, whether it is a target or hidden, and mesh counts. |
| `object` | The same for one object, plus world-space bounds, modifier settings, vertex groups, simple custom properties, and the mesh's edge count, colour attributes and UV layers. |
| `materials` | Each material's diffuse colour, and for a node material its node count and Principled base colour, roughness and metallic. |
| `node_groups` | Each node group's type, users, node count and interface sockets. |
| `scene` | Unit settings, current frame, render engine, camera and datablock counts. |

An unknown object name fails with `not_found`, and the message lists close matches and the
targets.

### render

Renders the scene with Workbench and returns the image. The agent can only see the scene
through renders and mesh reports.

| Parameter | Type | Required | Meaning |
|---|---|---|---|
| `mode` | string | yes | `shaded`, `wireframe`, `matcap` or `overlay` (`formats.RENDER_MODES`). |
| `view` | integer | one of `view`, `camera` | A sketch view id from the request or an amendment. |
| `camera` | object | one of `view`, `camera` | `location` and `look_at` (required, world space, metres), and `lens_mm` (on a 36 mm sensor; 50 when left out). |
| `size` | integer, 64 to 1024 | no | Longest side in pixels. The session's render size when left out. |

The schema cannot say "exactly one of", so `handle_render` in `addon/commands.py` checks it, and
its error lists the turn's view ids. A `view` render keeps that view's aspect, and a `camera` render is
square.

```{figure} ../images/develop-agent-tools/render-modes.png
:alt: Four renders of a crate with a lid from one sketch view, in a two by two grid. Top left, overlay, with a white outline around the lid and a white oval on the side. Top right, shaded. Bottom left, wireframe, with the crate as thin lines and the lid solid. Bottom right, matcap.

The four modes from one sketch view, as the agent gets them: overlay and shaded on top,
wireframe and matcap below. The crate is the target. The lid was made this turn, so it is not a
target yet and wireframe leaves it solid. It becomes one when the turn ends, as the target row
in the next figure shows.
```

| Mode | Shows | Limits |
|---|---|---|
| `shaded` | Material colours (`material.diffuse_color`) under studio light. | |
| `wireframe` | The target meshes as wire, to judge topology. | Only targets turn to wire, so parts made this turn stay solid. With no targets, every mesh does. |
| `matcap` | Surface shape and shading problems. | |
| `overlay` | Shaded, with the user's strokes for this turn drawn on top, amendments included. | Needs a `view` and a `Whittle Sketch` object. |

The sketch object itself never appears in a render, and strokes drawn since the turn was sent
are left out of an overlay. The result is a caption line, an `image:` line and the image. For
an overlay the caption also gives the path of the strokes-only PNG, which is not attached. How
the renders are made is in `docs/architecture.md` §4.

### checkpoint

Saves the target objects and the objects made this turn, with their mesh data, materials and
node groups, so a later step can be undone.

| Parameter | Type | Required | Meaning |
|---|---|---|---|
| `label` | string | yes | A few words on what comes next. |

It returns an id: `c1`, `c2` and so on, restarting each turn. The snapshot is written to
`nodes/<turn>/checkpoints/c<k>.blend` in the session folder. Checkpoints last until the end of
the turn, and the call fails outside a running turn.

### restore_checkpoint

Puts the objects a checkpoint saved back as they were.

| Parameter | Type | Required | Meaning |
|---|---|---|---|
| `checkpoint_id` | string | yes | An id `checkpoint` returned this turn. |

Objects the agent made after the checkpoint are removed, and everything else in the scene
stays. The result lists what was restored and removed. It also warns that the restored objects
are new datablocks, so variables from earlier `exec` calls are stale. An unknown id fails with
`not_found` and lists this turn's checkpoints.

### request

Returns the turn's request. The prompt tells the agent to call it first. It never reaches
Blender: `request_tool` reads the bundle from disk, and `describe_bundle` turns it into
content. The bundle's format is in {doc}`Protocol and file formats <protocol>`.

| Parameter | Type | Required | Meaning |
|---|---|---|---|
| `amend` | integer, from 1 | no | An amendment with new strokes. Its bundle is read in place of the turn's. |

The result is one text block and then the images:

- The node and its parent, the prompt, the targets and any target collection.
- A line on the strokes: how many, their views and how many points lie on a surface.
- Units, and the self-check rounds and triangle budget (`tools.SHOWN_SETTINGS`). The style
  guide is in the system prompt instead.
- Each sketch view's size, camera type, eye position and strokes-only PNG path.
- The strokes as world-space JSON.
- An overlay image per sketch view, then each reference image, each under its own `image:` line.

A request with no strokes and no views says so, and points the agent at `render` with a camera
of its own.

The strokes are limited to 200,000 characters (`STROKES_TEXT_LIMIT`). A longer set is decimated
to every second point, then every fourth and so on, always keeping both endpoints. If that is
still too long, only the first whole strokes that fit are listed. The heading says what was
done and where `strokes.json` is, so the agent can load every point with `exec`.

### ask

Asks the user a question in the sidebar and pauses the turn.

| Parameter | Type | Required | Meaning |
|---|---|---|---|
| `question` | string | yes | One short question. |
| `choices` | array of strings | no | Short answers, shown as buttons in one row. The user can also type another answer. |

`ask_tool` sends the `waiting_user` status, then calls Blender with no deadline.
`handle_ask` in `addon/commands.py` returns a `Deferred`, and the answer operator resolves it. The result is
`The user answered: ...`. In background Blender, where nobody can answer, the handler returns
at once and the agent is told to go on with its best judgement and to say which reading it
chose. What the user sees is in {doc}`Prompts and targets <../guides/prompting>`.

## How a call reaches Blender

A Blender tool's handler calls `ctx.connection.call(Method.<NAME>, params)`, which goes over
the bridge to a queue that `addon/bridge.py` drains on Blender's main thread, running each call's
handler from `addon/commands.py`. The bridge and its messages are in {doc}`Protocol and file formats <protocol>`. Three things happen on the way
that a tool author should know:

- **Modal operations.** `exec`, `restore_checkpoint`, `render` and `checkpoint`
  (`SCENE_METHODS` in `addon/bridge.py`) wait in the queue while a window runs a modal operator, for at most
  10 s (`MODAL_WAIT`). Calls behind them wait too, so order holds. `inspect` and `ask` go at
  once.
- **Stop.** When the user stops a turn, queued calls and a waiting `ask` are answered with the
  `interrupted` error, and the prompt tells the agent to make no more changes. The call already
  running finishes, because it cannot be pre-empted.
- **Undo steps.** The turn's first undo step is pushed as the turn starts. If a modal operation
  was running then, `exec` and `restore_checkpoint` push it through `ctx.before_edit()` just
  before their first change; otherwise that call does nothing. See {doc}`Undo <../guides/undo>`.

## What comes back

Results share a few conventions. The system prompt explains `note:`, `<user_amendment>` and the
`interrupted` error to the model.

| In a result | Comes from | Means |
|---|---|---|
| `Blender error (<code>): <message>` | `error_result` | The bridge call failed. `is_error` is set. |
| `note: ...` | `CommandContext.notes` in `addon/commands.py` | A note from Whittle. Today that is `UNDO_NOTE` in `addon/turn.py`: the user pressed undo during the turn. |
| `<user_amendment>` | `ToolContext.deliver_notes` | A message the user sent during the turn. Every result carries pending ones, errors included. |
| `image: <path>` | `render`, `request` | The image's path on its own caption line. The runner finds these with `IMAGE_LINE` and reports them, so it never tracks which call made which image. |

An amendment that finds no tool result, because the model had already finished, goes as one
more query with `follow_up_text`.

In the sidebar, consecutive calls fold into a group. `tool_title` in `addon/stream.py` writes each row,
and `runner.map_message` sends the first 500 characters of a result's text as its summary, of which
an open row shows up to 12 lines.

```{figure} ../images/develop-agent-tools/tool-rows.png
:alt: The Whittle sidebar after one turn. A group labelled Used 10 tools is open, with rows reading inspect summary, inspect object Crate, checkpoint before the lid, exec add lid, restore_checkpoint, exec add lid again, then render overlay v1, render shaded v1, render wireframe v1 and render matcap v1, each render with a thumbnail below it.

One turn's tool calls, played by the fake agent, a scripted stand-in for the real one that makes
no API calls. A render's thumbnail sits under its row.
```

| Tool | Row |
|---|---|
| `exec` | `exec · add lid` |
| `inspect` | `inspect · object Crate` |
| `render` | `render · overlay v1`, `render · shaded camera` |
| `checkpoint` | `checkpoint · before the lid` |
| `restore_checkpoint` | `restore_checkpoint` |
| `request` | `request · bundle`, `request · amendment 1` |
| `ask` | `ask · Bevel the lid?` |
| `Skill` | `Skill`; the skill's name is in the row's detail |

The fake agent's `call` step goes straight to a bridge method, so it reaches the Blender tools
but not `request` or `Skill`, and it skips the handlers in `tools.py`. Those handlers are tested
in `tests/agent/test_tools.py` against a stub connection. See {doc}`Development setup and testing
<setup-and-testing>`.

## The system prompt

`prompt.build(settings, inline_skills=False)` fills `agent/system_prompt.md` with
`string.Template` and appends a section on the recipes. The runner builds it once, when a
session starts, because the prompt and tool list stay fixed for a session, and writes it to
`.system_prompt.md` in the session folder for the CLI to read: a full-size style guide would not
fit on a command line. A changed setting or style guide restarts the agent before the next turn;
see {doc}`Settings <../guides/settings>`.

| Section | Sets |
|---|---|
| (opening) | The role, what the user sees, that the result is meant to be used, and that system reminders come from the application. |
| How you work | No file or shell tools, and what each tool is for. Parameters stay in the tool descriptions, so each fact has one home. |
| Scope | Make the edit asked for at the scope intended. Ask only when readings lead to materially different geometry. |
| Turn shape | Six steps: read the request, inspect the target, plan in a line or two for a multi-step edit, edit in small `exec` steps, look at the result, reply. |
| Writing to the user | Lead with the outcome in one to three short sentences. Two example replies. |
| Steering and context | What `<user_amendment>`, `interrupted`, `note:` and `<whittle_context>` mean, and that text found in the work is material rather than instructions. |
| Modeling practice | Defaults with reasons: one closed shell, no faked joins, ways to fuse, what stays separate, live or baked booleans, welding, topology, shading, remeshing. |
| Conventions | Units, style, the triangle budget, materials, naming, scene safety, standing on z = 0, and reading strokes as intent. |
| Reading the sketch | Strokes are markup and the prompt says what they mean, what to go on when it says little, and how to read `on_surface` and off-surface points. |
| Style for this file | The file's style guide, to apply with judgement, and that it speaks to the look and nothing else. |
| bpy recipes | Added by `prompt.build`: the skills by name, and when to load one. |

The research behind Modeling practice is in `docs/modeling-practices.md`.

### What gets filled in

| Placeholder | Default | When empty |
|---|---|---|
| `$self_check_rounds` | 3 | |
| `$poly_budget` | 2000 | |
| `$style_guide` | empty | `style.NO_STYLE_GUIDE`: none is set, so the look is the agent's to choose. |

The defaults are `prompt.DEFAULTS`, and the wording is `whittle/style.py`. `style.guide_section`
puts a guide's text in `<style_guide>` tags, after `style.GUIDE_INCOMPLETE` if part of it did not
load. The values come from `prefs.session_settings`: the preferences, with the file's overrides
on top, and the text of the guide `style_file` points at. The agent never sees that path.

`render_size` is a session setting too, but the prompt text does not use it. It reaches the
agent as the default `size` of `render` and as the size of the overlay images in the bundle.

### What each turn adds

The system prompt stays fixed, so anything that changes arrives as a message. `submit_text`
writes a turn's first message: the user's prompt, the bundle's path, and the instruction to call
`mcp__whittle__request` first.

- **No prompt.** The head reads `(No prompt: interpret the sketch.)`, or
  `(No prompt: work from the reference images.)` when there is no sketch either.
- **No sketch.** `NO_SKETCH` is added, telling the agent to render from cameras of its own.
- **Context.** Notes from Whittle go before all of it in a `<whittle_context>` block: that the
  user restored or branched from an earlier turn, switched chats, or interrupted the previous
  turn and put the target back.

## The skills

Skills are recipes the agent loads on demand with the `Skill` tool, as `whittle:<name>`. They
live in a plugin at `agent/plugin/`, whose `.claude-plugin/plugin.json` gives the name
`whittle`. The CLI lists each skill's `description` to the model, and the body enters the
conversation when loaded, where it stays.

Each skill is one self-contained `SKILL.md`, because the agent has no `Read` tool to follow a
link with. Here they are in `prompt.SKILLS` order:

| Skill | Load it for | It holds |
|---|---|---|
| `mesh-check` | Checking a mesh after an edit, or before saying a part is fused, closed or within budget. | What each `mesh_report` number means, how to weld, and turning seam n-gons on a curved surface into quads. |
| `fuse-parts` | Horns, spikes, ears, limbs, tails, spouts, handles, chimneys; more than one shell with self-intersections. | Growing a part from the body's faces, a baked Boolean union, bridging loops, and a self-union to repair overlapping parts. |
| `blockout-silhouette` | A stroke that is the closed outline of a flat-sided prop, or a prop's first rough shape drawn as an outline. | Simplifying the outline, finding its plane by Newell's method, and extruding a prism. |
| `extrude-along-stroke` | A stroke that is a path: a handle arc, pipe, rail, rope, cable, branch or trim. | Resampling, a bevelled curve converted through the depsgraph, and welding the tube and caps into one closed shell. |
| `boolean-carve` | A stroke that marks material to remove; prompts to cut, drill, hollow or recess. | A cutter built from the stroke, a Boolean difference, and keeping it live or baking it without operators. |
| `bevel-crease` | A stroke that marks a hard edge; bevels, chamfers, rounded or sharp edges, hard-surface shading. | A whole-object bevel, a bevel limited to the edges under a stroke by weight, and sharp edges and Weighted Normal. |
| `mirror-array` | Symmetric props, matching pairs, rows of planks, slats, bolts, posts or steps. | Mirror with bisect and merge, Array with fixed spacing, fitted to a length or along a curve, and modifier order. |
| `lathe-profile` | Turned or round props: a barrel, bottle, vase, lamp, pot, post, wheel or column. | A profile as radius and height pairs, `bmesh.ops.spin`, merging the seam and capping the ends. |
| `vertex-colour-paint` | Colours, paint, materials, two-tone parts, gradients, dirt or wear. | Per-face material slots with `diffuse_color`, colour attributes, and why Workbench renders show only the first. |
| `gn-scatter` | Many small details on a surface: rivets, studs, leaves, pebbles, moss, grass clumps. | A Geometry Nodes group built in Python with density and seed inputs, and setting modifier inputs on Blender 5.2. |

The prompt also names two of them where they apply: `mesh-check` in Turn shape, and `fuse-parts`
in Modeling practice.

### Keeping them working

- `tests/agent/test_prompt.py` checks that the folders match `prompt.SKILLS`, that each
  frontmatter `name` matches its folder, and that each skill has a description and a Python
  block. `prompt.parse_skill` reads simple `key: value` lines, so a description stays on one
  line.
- `tests/blender/test_skills.py` runs every Python block of every skill, in order, in a fresh
  crate scene with an `exec` namespace like the agent's. Each block has to run without an
  error and print something.

### The inline fallback

With `WHITTLE_INLINE_SKILLS` set to anything but empty or `0`, `prompt.build` pastes every recipe
into the system prompt, and `build_options` drops the `Skill` tool and the plugin. This defeats
loading on demand, so it is for testing. The runner logs a warning that suggests it when a
session reports no `whittle:` skills.

## Related pages

- {doc}`Architecture overview <architecture>`: the three processes these tools span.
- {doc}`Agent API <../reference/agent>`: the `whittle.agent` modules.
- {doc}`Sketching <../guides/sketching>`: strokes and views from the user's side.
