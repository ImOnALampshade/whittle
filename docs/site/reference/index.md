# API reference

Generated from the source by autodoc, so it always matches the code. The build mocks `bpy` and
the other packages Whittle runs against, which means it needs neither Blender nor the agent's
environment; a class that inherits from a Blender type shows the type's name as its base.

Whittle runs as separate processes, and the reference follows that split:

- [Add-on API](addon.md): the Blender side, in `whittle/addon/`.
- [Agent API](agent.md): the agent process, in `whittle/agent/`.
- [Shared modules API](shared.md): what needs no Blender, directly in `whittle/`.

<!-- api -->
