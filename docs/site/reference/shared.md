# Shared modules API

The modules directly under `whittle/`. The add-on and the agent are separate processes, joined
by a local socket, the bridge; the [Architecture overview](../develop/architecture.md) shows how
they fit together. These modules sit below the [add-on](addon.md) and the [agent](agent.md), and
hold what the two sides share or what is worth testing without Blender: the wire protocol, the
on-disk formats, the history tree, the chat store and the venv setup.

## The rule

Shared modules import only the standard library at module level, plus each other. That is
what makes them shared in practice:

- Blender's Python and the agent's venv Python can both load them.
- The agent process runs as `python -m whittle.agent` from the same package, so
  `whittle/__init__.py` stays free of `bpy` at import time. Its `register()` and
  `unregister()` import `whittle.addon` only when Blender calls them.
- The agent-side tests cover this code without Blender. See
  [Development setup and testing](../develop/setup-and-testing.md).

Imports are relative, because inside Blender the package is `bl_ext.<repo>.whittle`. Logic
the add-on owns but that needs no `bpy` is worth putting here, with a thin Blender half under
`whittle/addon/`, so those tests can reach it.

## What each module owns

Being shared does not mean both processes import a module. Several are here only so that
they stay testable without Blender, and just the add-on uses them.

| Module | Owns | Imported by | More |
| --- | --- | --- | --- |
| `protocol` | Bridge messages: framing, envelopes, method, event and error names | add-on, agent | [The bridge](../develop/protocol.md#the-bridge) |
| `formats` | Request bundles, the session folder, node ids, atomic JSON writes | add-on, agent | [Files on disk](../develop/protocol.md#files-on-disk) |
| `models` | Reading model ids, the model menu's list, efforts and defaults | add-on, agent | [Models and effort](../guides/models.md) |
| `style` | Bevel style suggestions, and how the prompt words the style settings | add-on, agent | [Settings](../guides/settings.md) |
| `tree` | The history tree in `session.json`, and which Agent SDK session a submit continues | add-on | [session.json](../develop/protocol.md#sessionjson), [History and branches](../guides/history.md) |
| `chats` | A file's chats, their index, and packing a chat into a zip for the `.blend` | add-on | [The packed zip](../develop/protocol.md#the-packed-zip), [Chats](../guides/chats.md) |
| `caches` | Each file's hidden cache folder, the file id, the install id | add-on | [Chat storage](../develop/protocol.md#chat-storage) |
| `markdown` | Claude's Markdown as `Line`s a Blender panel can draw | add-on | [The sidebar](../guides/sidebar.md) |
| `venv` | The agent's venv: the commands that build it from `requirements.lock`, and `VenvSetup` | add-on | [What setup does](../guides/installation.md#what-setup-does-and-why), [The dev venv](../develop/setup-and-testing.md#the-dev-venv) |
| `platforms` | What differs between Linux, Windows and macOS | add-on, and the agent through `formats` | [Architecture overview](../develop/architecture.md) |

Four of these have a Blender half that does the `bpy` work, in three add-on modules:
`whittle.addon.chats` for `chats` and `caches`, `whittle.addon.models` for `models`, and
`whittle.addon.setup` for `venv`. Two of those halves, `whittle.addon.chats` and
`whittle.addon.models`, share a name with a shared module, so add-on code imports the shared
`chats` and `models` under another name, `store` or `chat_store`.

The modules build on each other in one direction. `platforms` is at the bottom, then
`formats`, `tree`, `chats` and `caches` in that order; `models` uses `formats`, and `venv`
uses `platforms`. `protocol`, `markdown` and `style` import nothing from Whittle.

## Passing the platform in

`whittle.platforms` takes the platform (a `sys.platform` value) as an argument, and on
Windows the kernel32 calls too, so the Linux suite covers the Windows branches with kernel32
faked. New process spawning, killing, liveness probes, atomic file replaces and clean-up of
what a killed agent leaves all go through it.

<!-- api -->

## `whittle`

```{eval-rst}
.. automodule:: whittle
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.caches`

```{eval-rst}
.. automodule:: whittle.caches
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.chats`

```{eval-rst}
.. automodule:: whittle.chats
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.formats`

```{eval-rst}
.. automodule:: whittle.formats
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.markdown`

```{eval-rst}
.. automodule:: whittle.markdown
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.models`

```{eval-rst}
.. automodule:: whittle.models
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.platforms`

```{eval-rst}
.. automodule:: whittle.platforms
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.protocol`

```{eval-rst}
.. automodule:: whittle.protocol
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.style`

```{eval-rst}
.. automodule:: whittle.style
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.tree`

```{eval-rst}
.. automodule:: whittle.tree
   :members:
   :undoc-members:
   :show-inheritance:
```

## `whittle.venv`

```{eval-rst}
.. automodule:: whittle.venv
   :members:
   :undoc-members:
   :show-inheritance:
```
