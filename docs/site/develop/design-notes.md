# Design notes

Whittle's working design is seven Markdown files in the repository's `docs/` folder. This
site explains how to use and change Whittle; those files hold the detail and the reasons,
and they are what a change to the code updates. This page says what each one answers. The
files stay in the repository rather than on this site, so the links below open them there.

## Which file to open

| You want to know | Open |
|---|---|
| What Whittle set out to be, and the loop it is built around | [`design.md`] |
| Why something is the way it is, or why an obvious alternative was dropped | [`decisions.md`] |
| How something is built: a module, a message, a file on disk, a Blender API quirk | [`architecture.md`] |
| What the sidebar shows in a given state, and how it is accepted | [`ui.md`] |
| How to word the system prompt, a skill, a tool description or an error the agent reads | [`prompting.md`] |
| What the agent is told about good meshes, and the evidence behind it | [`modeling-practices.md`] |
| What is built, what is not, and what only a person can check | [`progress.md`] |

[`design.md`]: https://github.com/ImOnALampshade/whittle/blob/main/docs/design.md
[`decisions.md`]: https://github.com/ImOnALampshade/whittle/blob/main/docs/decisions.md
[`architecture.md`]: https://github.com/ImOnALampshade/whittle/blob/main/docs/architecture.md
[`ui.md`]: https://github.com/ImOnALampshade/whittle/blob/main/docs/ui.md
[`prompting.md`]: https://github.com/ImOnALampshade/whittle/blob/main/docs/prompting.md
[`modeling-practices.md`]: https://github.com/ImOnALampshade/whittle/blob/main/docs/modeling-practices.md
[`progress.md`]: https://github.com/ImOnALampshade/whittle/blob/main/docs/progress.md
[`AGENTS.md`]: https://github.com/ImOnALampshade/whittle/blob/main/AGENTS.md

## When they disagree

They were written at different times, so they do not all carry the same weight:

- `decisions.md` wins over `design.md`.
- `architecture.md` wins over both on implementation detail: module names, wire formats and
  file formats.
- `ui.md` replaces the panel list in `design.md` §5.
- `progress.md` says what is actually built, whichever of the others describes it.

The code is what runs. If a doc and the code differ, one of them is wrong, and the fix
belongs in the change that finds it.

## The seven files

### design.md

The original design: the core loop (orbit, sketch, prompt, watch the edit, keep a node in
the history), the sketching model, the agent's shape, history, start points and the build
phases. Read it for intent, and treat its details as history. A banner at the top lists what
has since gone: the target lock (a warning whenever the user touched the target during a
turn), the `<name>.whittle/` folder beside the `.blend`, the Blank start point's ground grid
and scale reference, stroke types, and Blender 4.2. Its §10 lists the open questions that `decisions.md`
resolves, and the first five areas in `progress.md` still cite its sections and build phases.

### decisions.md

Short entries saying what was chosen and why, grouped as Environment, Agent process,
Behaviour, Shortcut, Sketching, Sketch keys and view markers, Chats, and Continuous integration. This is the place for the
reasons the code cannot show: why there are no Intel Macs (a pinned dependency has no wheel
for them), why the target lock was removed (it fired far too often: even changing the
viewport's shading counted), why Shift+Alt+C opens a popup instead of the sidebar's box
(Python cannot start editing a sidebar field). An entry that was reversed says so with its
date, so read the entry rather than assuming the first plan held. A new key needs a row here.

### architecture.md

The implementation blueprint, and the longest file. [Architecture overview](architecture.md)
is the way in; this is the full version. Its sections:

| § | Covers |
|---|---|
| 1 | Repository layout, the system prompt, style guides, the recipe skills |
| 2 | Processes and lifecycle, including authentication |
| 3 | The bridge protocol |
| 4 | The main-thread command queue on the Blender side, `exec` and render |
| 5 | The agent side: connection, runner, MCP tools, fake agent |
| 6 | History, sessions and branching |
| 7 | Sketching and views |
| 8 | On-disk formats: session folder, request bundle |
| 9 | Packaging and the agent venv |
| 10 | Tests |
| 11 | Implementation notes |
| 12 | The sidebar's implementation |
| 13 | Start points and references |
| 14 | Chats and storage in the `.blend` |
| 15 | The model and effort per chat |

The appendix, API notes, records what was probed in Blender 5.2.2 and `claude-agent-sdk`
0.2.167: Grease Pencil v3, viewports, render, libraries, timers and handlers, binary data in
a `.blend`. Check it before trying a `bpy` call that looks like it should work.
[Protocol and file formats](protocol.md) introduces §3 and §8.

### ui.md

The sidebar's spec. [The sidebar](../guides/sidebar.md) tells a user what is there; this file
tells a contributor what must be there and why, and it changes with the UI.

- §1 is the principles, such as "nothing until it is relevant" and red only for real failures.
- §3 goes through the parts one by one, and §4 draws each state as a text mock-up.
- §5 to §7 cover the menus, the Development panel, and the operators and properties.
- §8 is the undo design, and §9 says where each feature can be reached.
- §10 is the screenshot gate: one check per scenario in `tests/screens/catalog.py`.

A UI change is accepted on real screenshots, read against §10. For example, §4.4 draws a
turn paused on a question, and the gate's check for the `asking` scenario is: "question not
red and said once; Stop alone; placeholder `Ask Claude…`".

```{figure} ../images/develop-design-notes/asking.png
:alt: The Whittle sidebar during a turn that has paused on a question, with one button per choice, the prompt box reading Ask Claude, and a Stop button

The `asking` scenario, the state `ui.md` §4.4 draws and §10 checks.
```

### prompting.md

How agent-facing text is written: `whittle/agent/system_prompt.md`, the skills' `SKILL.md`
files, the tool descriptions and schemas in `whittle/agent/tools.py`, the context notes added
to a turn, and every error or result the agent reads. Its stance is practices with reasons
rather than rules, at normal volume. Points specific to the default model, Claude Opus 5.5,
are marked **[5.5]**, and its sources are listed at the end.

Read it before changing any of that text, especially its Changing a prompt section. The
offline suite uses the fake agent, so it checks that a note or error is produced and shaped
right, not how the model responds to the wording. A wording change needs a manual run with a
real API key. See [Agent tools and skills](agent-tools.md).

### modeling-practices.md

The research behind the system prompt's "Modeling practice" section and the `mesh-check` and
`fuse-parts` skills. It begins with the failure that prompted it, horns on a sphere head that
rendered fine but were not one solid, then covers attaching parts, measuring, topology,
shading, transforms and asset hygiene. Points marked **verified** were run headless in Blender
5.2.2; the rest come from practitioners and documentation, listed at the end. The Project
defaults table records where the project leans. These are defaults the agent may depart from,
as long as it says what it chose.

### progress.md

The state of the project, in four parts:

- **What exists**: everything built so far, by area, with the modules and tests behind it.
- **How to run**: the commands; [Development setup and testing](setup-and-testing.md) is the
  guide to them.
- **Known gaps**: what is missing, limited or checked only offline. Look here before filing
  something as a bug.
- **Manual GUI checklist**: what only a person at a real Blender can confirm, such as a tablet
  pen's pressure.

## Keeping them current

Update `README.md`, `architecture.md`, `ui.md`, `decisions.md`, `progress.md` and the site's
pages in `docs/site/` in the same change as the code, and [`AGENTS.md`] when what it says
changes. If `AGENTS.md` and a doc
disagree, the doc wins, and `AGENTS.md` is the one to fix. For what a new tool, skill or
preference touches, see [Extending Whittle](extending.md). A new key goes in
`whittle/addon/keys.py`, with a check in `tests/blender/test_keys.py` and a row in `ui.md`, the
README and `decisions.md`.

No test reads the seven files' content, so nothing but review keeps them true
(`tests/agent/test_guide.py` only checks that what `AGENTS.md` names exists). Some comments
in the source cite them by section (`architecture §14`, `design §10`), so renumbering a
section means searching for those too.
