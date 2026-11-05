# Whittle

```{image} ../images/hero.png
:alt: Whittle in Blender: strokes drawn over a model, with the chat in the 3D viewport sidebar
```

Whittle is a Blender extension that puts a Claude agent in the 3D viewport sidebar. Sketch
over a model with Grease Pencil, write a prompt, and the agent edits the open scene. Every
turn is a node in a branching history you can step back through, and a file can hold several
chats, all stored in the `.blend`. It needs Blender 5.2 and your own Anthropic API key.

Powered by Claude. Licensed GPL-3.0-or-later.

```{toctree}
:maxdepth: 1
:caption: Getting started

quickstart
walkthrough
```

```{toctree}
:maxdepth: 1
:caption: Guides

guides/installation
guides/api-key
guides/sidebar
guides/prompting
guides/sketching
guides/references
guides/history
guides/undo
guides/chats
guides/models
guides/settings
guides/shortcuts
guides/troubleshooting
guides/privacy
```

```{toctree}
:maxdepth: 1
:caption: Development

develop/architecture
develop/setup-and-testing
develop/extending
develop/agent-tools
develop/protocol
develop/design-notes
```

```{toctree}
:maxdepth: 1
:caption: API reference

Overview <reference/index>
reference/addon
reference/agent
reference/shared
```
