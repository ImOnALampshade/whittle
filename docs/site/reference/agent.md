# Agent API

The agent process, under `whittle/agent/`. Blender starts it from the agent venv's Python as
`python -m whittle.agent --port N`. It connects back over the bridge, holds the Agent SDK
session and turns what the SDK reports into events. This page is a map of the package, to find
your way around the generated reference below;
[Architecture overview](../develop/architecture.md) explains how a session runs and where the
process sits between Blender and the bundled CLI.

## The modules

| Module | What it does |
|---|---|
| `__main__` | The entry point. Parses `--port`, `--host` and `--fake`, opens the connection, picks the runner, serves until `shutdown` or EOF, then closes the runner. |
| `connection` | The agent's end of the bridge: {py:class}`~whittle.agent.connection.Connection` does the handshake, makes calls to Blender, sends events and reads Blender's calls. |
| `dispatch` | Checks the parameters of Blender's calls and routes them to a runner. Defines the {py:class}`~whittle.agent.dispatch.Runner` protocol. |
| `runner` | {py:class}`~whittle.agent.runner.SdkRunner`, the real runner. Builds the session's options, owns the SDK client, maps SDK messages to events and adds up each turn's cost. |
| `fake` | {py:class}`~whittle.agent.fake.FakeRunner`, the scripted runner: the same `Runner` protocol, played from a JSON script. |
| `tools` | The `TOOLS` table of agent tools, their handlers, {py:class}`~whittle.agent.tools.ToolContext`, and {py:func}`~whittle.agent.tools.build_servers`, which wraps them as the two in-process MCP servers. |
| `prompt` | {py:func}`~whittle.agent.prompt.build` fills `system_prompt.md` in from the session settings. Also holds the `SKILLS` list and the plugin folder. |
| `store` | {py:class}`~whittle.agent.store.FolderSessionStore`, the SDK session store that keeps a chat's transcripts in the chat's own folder. |

Some of the package is not Python, and only `prompt` and `runner` use it: `system_prompt.md`
and the plugin folder, which holds the recipe skills in `plugin/skills/<name>/SKILL.md` and the
plugin's manifest, `plugin/.claude-plugin/plugin.json`.
[Agent tools and skills](../develop/agent-tools.md) covers those and the tools.

## How they fit together

`__main__` decides the shape of the process in `make_runner`: `--fake SCRIPT` gives a
`FakeRunner`, anything else an `SdkRunner`. Everything past that point talks to the `Runner`
protocol, so the rest of the package is the same in both modes.

**Calls from Blender.** `Connection.serve` hands each call to the handler that
{py:func}`~whittle.agent.dispatch.make_dispatcher` built. The dispatcher answers `ping` and
`shutdown` itself and passes `start_session`, `submit`, `amend` and `interrupt` to the runner,
already checked: a missing parameter or one of the wrong type goes back to Blender as
`bad_request` and never reaches a runner.

**Calls to Blender.** `SdkRunner` never calls Blender on the model's behalf. The model calls a
tool, and the tool's handler calls `Connection.call` through the `ToolContext`. `FakeRunner`
has no tools: its `call` steps go straight to the connection.

**Events to Blender.** Each runner sends its own through `Connection.send_event`, and tool
handlers through `ToolContext.event`, which adds the running turn's id.

**The `ToolContext`** is the state `SdkRunner` shares with the tools. There is one per runner.
`submit` sets its turn id and bundle folder. `amend` queues on it what the user
[adds during a running turn](../guides/prompting.md#amend-a-running-turn), and the next tool
result carries that to the model as a note, through `ToolContext.deliver_notes`. An amendment
that misses every tool result goes to the model as one more query in the same turn.

## What may import what

Nothing here imports `bpy` or `whittle.addon`; the agent reaches Blender only through the
bridge. Modules use the shared modules in `whittle/` and each other, with relative imports,
because inside Blender the package is `bl_ext.<repo>.whittle`.

The Agent SDK stays out of the way of the fake agent:

- `runner` imports `claude_agent_sdk` at module level, and `__main__` imports `runner` only when
  there is no `--fake`.
- {py:func}`~whittle.agent.tools.build_servers` imports it inside the function. The rest of
  `tools` loads without the SDK, which `fake` relies on for `amend_note`, the function that
  words those notes, and the agent tests for calling handlers directly.
- `store` needs no import at all: the SDK finds a session store's methods by name.

So the fake agent runs under any Python 3.13 or 3.14, with no SDK installed and no API key.
[Development setup and testing](../develop/setup-and-testing.md) shows how to run one, and
[Extending Whittle](../develop/extending.md) how to add a tool or a skill. What goes over the
bridge is in [Protocol and file formats](../develop/protocol.md).

<!-- api -->

## `whittle.agent`

```{eval-rst}
.. automodule:: whittle.agent
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.agent.__main__`

```{eval-rst}
.. automodule:: whittle.agent.__main__
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.agent.connection`

```{eval-rst}
.. automodule:: whittle.agent.connection
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.agent.dispatch`

```{eval-rst}
.. automodule:: whittle.agent.dispatch
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.agent.fake`

```{eval-rst}
.. automodule:: whittle.agent.fake
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.agent.prompt`

```{eval-rst}
.. automodule:: whittle.agent.prompt
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.agent.runner`

```{eval-rst}
.. automodule:: whittle.agent.runner
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.agent.store`

```{eval-rst}
.. automodule:: whittle.agent.store
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.agent.tools`

```{eval-rst}
.. automodule:: whittle.agent.tools
   :members:
   :undoc-members:
   :show-inheritance:
```
