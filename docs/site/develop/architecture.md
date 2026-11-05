# Architecture overview

Whittle lives in three processes: Blender, an agent process and the Claude CLI the agent
runs. This page is the map of how they fit together, for someone about to change the code.
The full blueprint is
[docs/architecture.md](https://github.com/ImOnALampshade/whittle/blob/main/docs/architecture.md),
which has every field, state and edge case; where it and this page disagree, it wins, and
the code wins over both.

## Three processes

```text
Blender (add-on, main thread)
    ^
    |  bridge: JSON lines over 127.0.0.1
    v
agent process (venv Python, asyncio)
    |
    |  started by the SDK
    v
bundled Claude CLI (from the claude-agent-sdk wheel)
```

| Process | Code | Runs on | What it does |
|---|---|---|---|
| Blender | `whittle/addon/` | Blender's Python, 3.13 or 3.14 | Sidebar, sketch, history. Runs every piece of agent code that touches the scene. |
| Agent | `whittle/agent/` | The agent venv's Python, asyncio | Holds the Agent SDK client, serves the agent's tools and turns SDK messages into events. |
| Claude CLI | From the `claude-agent-sdk` wheel | Started by the SDK | Talks to the Anthropic API. Whittle never modifies it; it only picks its environment and folder. |

The agent is a separate process for three reasons:

- `bpy` belongs to Blender's main thread, while the SDK is asyncio and starts a CLI of its
  own. Inside Blender's interpreter, its event loop would fight the UI.
- The SDK and its dependencies stay in a private venv, out of Blender's Python.
- A crash or a hang in the agent can't take Blender down.

The code is split to match, and these import rules hold throughout:

- `whittle/addon/` may import `bpy`, `bmesh`, `mathutils`, `gpu` and `numpy`. It never
  imports `whittle.agent`.
- `whittle/agent/` never imports `bpy`. Only `agent/runner.py` imports `claude_agent_sdk` at
  module level. `tools.build_servers` imports it too, but lazily, when the real runner calls
  it, so the rest of that folder is stdlib at import time. That is why the fake agent (a
  scripted stand-in that makes no API calls, see [The agent side](#the-agent-side)) runs
  under any Python 3.13 or 3.14.
- The shared modules at the top of `whittle/` (`protocol`, `formats`, `tree`, `chats`,
  `caches`, `markdown`, `models`, `style`, `venv`, `platforms`) are stdlib only at module
  level, and `whittle/__init__.py` imports nothing from Blender until `register()` runs.
  That is what lets `python -m whittle.agent` work without `bpy`.
- Code uses relative imports only, because inside Blender the package is
  `bl_ext.<repo>.whittle`.

## Who owns what in Blender

Three objects carry a turn on the add-on side:

- {py:class}`~whittle.addon.turn.TurnController` runs turns: it owns the agent process, the
  command context and the stream, and drives `start_session`, `submit` and `turn_finished`.
  There is one current controller, reached with `turn.current()`.
- {py:class}`~whittle.addon.process.AgentProcess` is the process's lifecycle: spawn,
  handshake, crash detection and shutdown. Its `state` is what the sidebar reports.
- {py:class}`~whittle.addon.bridge.Bridge` is the connection: the listening socket, framing,
  pending calls, the main-thread queue and `tick()`.

Agent calls land in the handlers `commands.build_handlers` returns, one per method. The
[Add-on API](../reference/addon.md) has the rest of the modules.

## Starting the agent

The first Send starts the agent. `AgentProcess.start` works through these checks and stops
at the first that fails:

1. Find the agent Python: `WHITTLE_AGENT_PYTHON`, then the **Agent Python** preference, then
   the private venv once its setup has been verified against the lock. With none, the state
   is `needs_setup`.
2. Find the API key: the preference, else `ANTHROPIC_API_KEY`. With none, the state is
   `needs_key`, and nothing is spawned.
3. Check `bpy.app.online_access`. With it off, the state is `failed`.

The fake agent needs no key and skips the online check. Then Blender listens on
`127.0.0.1` with a port the system picks, makes a random token and spawns:

```text
<python> -s -P -m whittle.agent --port <port> [--fake <script>]
```

The token and the key travel in the environment, never in argv, so neither shows in `ps`.
That environment has every other `ANTHROPIC_*` and `CLAUDE*` variable stripped, apart from the two
in `process.KEPT`, and a private `CLAUDE_CONFIG_DIR` under Whittle's user folder, so the CLI
has no way to sign in but the key and never sees the user's own Claude configuration. The
agent's output goes to a file in `<user dir>/logs/`, not a pipe, so a chatty agent can't
block on a full buffer. The last 10 logs are kept.

The agent connects back and sends `hello` with the token. Blender checks the token and the
protocol version, closes the listener so nothing else can connect, and answers `welcome`.
Anything else fails the agent and kills it. Blender gives the handshake 30 s and the agent
waits 10 s for its `welcome`.

`AgentProcess.state` runs through:

```text
stopped -> starting -> ready <-> busy -> stopping -> stopped
```

Any live state can go to `crashed` or `failed`. `needs_setup` and `needs_key` are where a
start stops before anything is spawned, and adding the missing piece clears them.

## The bridge

One TCP connection on `127.0.0.1`, carrying UTF-8 JSON, one object per line. Both ends
import `whittle/protocol.py`: `addon/bridge.py` on the Blender side, driven by timers, and
`agent/connection.py` on the agent side, on asyncio. A line can be 16 MiB at most, so images
never travel on it: Blender writes PNGs to the chat's session folder on disk and sends paths.

| Type | Direction | Meaning |
|---|---|---|
| `hello`, `welcome` | Agent first, then Blender | The handshake. |
| `call` | Either way | A request with an `id` and a method. |
| `result` | Either way | The reply to the `call` with the same `id`. |
| `event` | Agent to Blender only | A one-way notification, such as `text` or `turn_finished`. |

The calls split by direction:

- **Blender to agent**: `start_session`, `submit`, `amend`, `interrupt`, `ping`, `shutdown`.
- **Agent to Blender**: `exec`, `inspect`, `render`, `checkpoint`, `restore_checkpoint`, `ask`.

An exception in the agent's own `exec` code is not a bridge error. The call succeeds and
carries the exception in its result, so bridge errors mean something went wrong in the
protocol or the system. [Protocol and file formats](protocol.md) has each message's fields
and the error codes.

## The main-thread queue

All `bpy` access happens on Blender's main thread, and nothing on that thread may block on
the socket. So a `bpy.app.timers` callback drives {py:meth}`~whittle.addon.bridge.Bridge.tick`,
which does this each time:

1. Accept the connection, while waiting for one.
2. Read the socket until it would block, and dispatch what arrived. A `result` runs its
   pending callback, an `event` goes to `TurnController.on_event`, and a `call` joins
   `Bridge.queue`.
3. Poll the process, to notice an exit and to escalate a slow stop.
4. Run queued calls.
5. Send what it can of the outgoing buffer, without blocking.
6. Return the delay to the next tick.

Step 4 runs calls until the queue is empty or 30 ms have passed (`TICK_BUDGET`), and always
at least one, unless the first call is waiting on a modal operator (see below). A `render`
ends the step, since one per tick keeps the UI responsive. Each
handler is wrapped: `BridgeError` becomes an error result, any other exception becomes
`internal` with its traceback, and a result that can't be encoded is replaced by an
`internal` error, so the agent always gets a reply.

The next tick comes after 0.01 s with work queued or unsent, otherwise 0.05 s during a turn
and 0.2 s when idle. Timers don't redraw regions, so the bridge tags the 3D viewports for
a redraw itself, and that is how new text reaches the sidebar.

A few rules shape what the queue does:

- **Nothing pre-empts `exec`.** Python on the main thread can't be interrupted, and Blender
  is frozen until the code returns. There is no execution timeout, so the `exec` tool's
  description and the system prompt ask for short steps.
- **Modal operators go first.** `exec`, `restore_checkpoint`, `render` and `checkpoint` wait
  while a window runs a modal operator (a transform, a stroke, the knife), because changing
  data under one can crash Blender. Calls behind them wait too, which keeps the order. Some
  add-ons keep a modal running all the time, so the wait ends after 10 s (`MODAL_WAIT`).
  `inspect` and `ask` don't wait.
- **`ask` is deferred.** Its handler returns `Deferred()`, the bridge holds the call's id,
  and the reply goes out when the user answers, through `Bridge.resolve`.
- **An interrupt empties the queue.** Calls not yet started are answered `interrupted`
  without running, the call in progress finishes, and a pending `ask` fails. The flag clears
  when the turn ends.

Blender drops a timer whose callback raises, which would leave the agent connected to a
socket nobody reads. So the callback catches anything that escapes `tick()`, logs it and
crashes the agent visibly.

## The agent side

`agent/__main__.py` opens the {py:class}`~whittle.agent.connection.Connection`, does the
handshake, then serves until `shutdown` or EOF. Exiting on EOF means it never outlives
Blender. Both exit with code 0, and a failed handshake or start with 2. SIGTERM counts as
`shutdown`, so the session still closes properly.

`agent/dispatch.py` checks each call's parameters and routes it to a runner. There are two,
both behind the `Runner` protocol:

- {py:class}`~whittle.agent.runner.SdkRunner` runs the real agent. Its module is the only one
  that imports the SDK at module level, and `tools.build_servers`, the one lazy import, runs
  only when this runner calls it.
- {py:class}`~whittle.agent.fake.FakeRunner` plays a JSON script instead: stdlib only, no
  key, no API calls, and the same process, socket, handshake and Blender handlers as the
  real thing. [Development setup and testing](setup-and-testing.md) shows how to run one.

A `ClaudeSDKClient` has to stay in the task group it connected in, so `SdkRunner` owns one
long-lived session task per client. That task does two things:

- It starts a **reader** task, which loops over `client.receive_messages()` and turns each
  message into events with `map_message`.
- It runs the **controller** loop itself, which waits on an `asyncio.Queue` of commands and
  calls `client.query` and `client.interrupt`. A stop ends the loop, and the session task
  then disconnects the client.

The public runner methods only put commands on that queue. A chat's model or effort that
differs from the live session's is switched here, just before the query, so the conversation
carries on.

The session is built in `runner.build_options`, and it is locked down. The only built-in
tool is `Skill`, `permission_mode` is `dontAsk`, and `strict_mcp_config` and an empty
`setting_sources` keep out anything from the user's own setup. The agent's other tools come
from two in-process MCP servers built from `tools.TOOLS`:

| Server | Tools | How they work |
|---|---|---|
| `blender` | `exec`, `inspect`, `render`, `checkpoint`, `restore_checkpoint` | Each is a bridge call into the main-thread queue. |
| `whittle` | `request`, `ask` | `request` reads the turn's request bundle (prompt, strokes, views, references) from disk, with no bridge call. `ask` is a bridge call that waits for the user. |

A call waits 300 s for its result by default. `exec`, `restore_checkpoint` and `ask` wait
with no timeout: `ask` is waiting on a person, and Blender can't stop the other two once
they run, so a timeout could report as not done what may still complete.

The system prompt (`agent/system_prompt.md`, filled in by `prompt.build`) and the recipe
skills (`agent/plugin/skills/`) ship in the package.
[Agent tools and skills](agent-tools.md) covers the tools and skills, and
[Extending Whittle](extending.md) how to add one.

## One turn, end to end

Every turn becomes a node in the chat's [history tree](../guides/history.md), and it works on
the turn's [targets](../guides/prompting.md), the objects the agent is there to edit.

```text
Blender                                    Agent                     Claude CLI
-------                                    -----                     ----------
write the request bundle
start_session (when needed)  ------------> build options, connect -> start
undo step, turn-start snapshot
submit  --------------------------------->
                             <------------ turn_started
                                           query  ----------------> API call
                                           request tool: read bundle <- tool call
                             <------------ text, tool_use
queue; run on the main thread <----------- exec, render, ...         <- tool call
result  ---------------------------------> tool result  ----------->
                             <------------ tool_result
                                           ...
                             <------------ turn_finished             <- result
record the node, undo step
```

1. **Send.** `TurnController.run_sketch` starts the agent if it has to, then writes the
   request bundle (prompt, strokes, views, references) into the next node's `request/`
   folder. It is written now, not when the agent is ready, so strokes drawn while the agent
   starts stay pending for a later turn.
2. **Session.** Once the agent is `ready`, `tree.session_plan` decides whether the live
   conversation fits the node the scene reflects, or a new session has to resume or fork
   one. [History and branches](../guides/history.md) is the user's view of this.
3. **Submit.** Blender pushes the `Before Whittle turn` undo step, snapshots the targets to
   `checkpoints/start.blend` and sends `submit`. The agent's message gives the prompt
   and the bundle's path, and asks the model to call `request` first. That tool returns the
   request and strokes as text and each view's overlay as an image.
4. **Tools.** The model works through tools. Each result passes through
   `ToolContext.deliver_notes`, which is how an amendment the user sends mid-turn reaches
   the model. An amendment that misses every tool result goes as one more query in the same
   turn.
5. **Events.** Whole text blocks and tool calls stream to Blender as they complete, and
   `TurnController.on_event` hands them to the stream, the sidebar's source, and to the
   node's `transcript.jsonl`.
6. **Finish.** The runner counts queries against `ResultMessage`s and sends `turn_finished`
   when they match and no amendment is pending. Blender then records the history node with
   its snapshot, cost and SDK session id, and pushes the `Whittle: <node> <label>` undo step.
   [Undo](../guides/undo.md) has how those two steps behave.

```{figure} ../images/develop-architecture/streaming.png
:alt: The Whittle sidebar during a turn: the prompt, two paragraphs of Claude's text, a finished group reading Used 2 tools, a group reading Running 2 tools, a render thumbnail, and a Stop button
:width: 280px

A turn in flight. Each `text` event is a paragraph. `tool_use` and `tool_result` events merge
into the groups between them: "Used 2 tools" has finished, and "Running 2 tools" has
calls still waiting for a result.
```

What a turn leaves goes in the chat's session folder, a hidden cache in Whittle's user
folder. The folder is packed into the `.blend`, so the file carries its chats, without the
turn's checkpoints (used only during their turn) or comparison scratch.
[Protocol and file formats](protocol.md) has the layout.

## When it stops

**A crash.** After the handshake, an exited process or a closed socket outside `stopping`
is a crash, and every tick checks for both. Pending calls fail with `agent_crashed` and a
waiting `ask` is cancelled. A running turn that changed something is kept as a failed node
with the scene left as it is, and one that changed nothing folds into its parent, which stays
current.

A restart goes through `tree.session_plan`. After a crash between turns it resumes the current
node's SDK session. After a crash mid-turn the failed node has no session of its own, so the
next session forks from the nearest earlier node that has one, or starts fresh if none does,
and a note tells the agent to inspect the target. A folded turn that carried on its parent's
session makes the parent fork too, since it counts as the latest in that session.
[Troubleshooting](../guides/troubleshooting.md) has what the user sees.

**A normal stop.** `AgentProcess.stop` sends `shutdown`, and the agent closes its SDK session.
If the process is still there after 20 s Blender sends SIGTERM, and 5 s later SIGKILL. On
quit, on loading a file and in `unregister()` no more ticks will come, so the same sequence
runs synchronously, with 10 s before the SIGTERM.

The agent runs in its own process group, and a terminate or kill goes to the whole group, so
the CLI goes with it. What differs per platform lives in `whittle/platforms.py`: on Windows,
which no one has used for real yet, the group is a Job Object and a terminate is a hard kill.

## Where to go next

- [Design notes](design-notes.md): why it is built this way.
- [Protocol and file formats](protocol.md): the wire format, the bundle and the session folder.
- [Agent tools and skills](agent-tools.md): what the agent can call.
- [Extending Whittle](extending.md): where a new tool, skill, preference or stroke type goes.
- [Privacy and safety](../guides/privacy.md): what leaves the machine, and what the agent can
  do.
- [docs/architecture.md](https://github.com/ImOnALampshade/whittle/blob/main/docs/architecture.md):
  §2 processes, §3 protocol, §4 the main-thread queue, §5 the agent side, §6 history and
  sessions, §8 on-disk formats, §14 chats.
