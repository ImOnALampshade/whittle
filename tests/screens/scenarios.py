# SPDX-License-Identifier: GPL-3.0-or-later
"""The states the screenshot harness shoots. Each scenario is a generator
over a Stage: it builds its scene, then drives the add-on through the same
controller and operator functions the sidebar's buttons call, with the fake
agent on real timers. It yields a number to wait that many seconds, or an
Until to wait for a condition; when it returns, the harness shoots.

Scenarios reach their state through those functions, never through the
sidebar's layout, so they hold while the layout changes."""

import json
import os
import shutil
import time
from pathlib import Path

import bpy

from tests.blender.sketch_helpers import add_stroke
from tests.fixtures.crate.scene import build_scene
from whittle import chats as chat_store
from whittle import formats
from whittle import models as model_store
from whittle.addon import chats, models, operators, sketch, targets, turn, views

REPO = Path(__file__).resolve().parents[2]
FAKE = REPO / "tests" / "fixtures" / "fake"
CRATE_BUNDLE = REPO / "tests" / "fixtures" / "crate" / "request"

LID = ("mesh = bpy.data.meshes.new('Crate_Lid')\nbm = bmesh.new()\nbmesh.ops.create_cube(bm, size=1.0)\n"
       "bm.to_mesh(mesh)\nbm.free()\nlid = bpy.data.objects.new('Crate_Lid', mesh)\n"
       "lid.scale = (0.54, 0.54, 0.04)\nlid.location = (0, 0, 0.52)\n"
       "bpy.context.scene.collection.objects.link(lid)\nprint('lid', lid.name)")


class Until:
    def __init__(self, check, what: str):
        self.check = check
        self.what = what


class Popup:
    """Returned by a scenario to shoot a popover or a menu opened over the
    sidebar instead of the sidebar alone: ("panel", panel id) opens a panel
    as a popup, ("operator", op id, {props}) invokes an operator that opens
    one."""

    def __init__(self, kind: str, name: str, props: dict | None = None):
        self.kind = kind
        self.name = name
        self.props = props or {}


# -- fake agent steps ---------------------------------------------------------

def say(text: str) -> dict:
    return {"say": text}


def exec_(label: str, code: str, **extra) -> dict:
    return {"call": "exec", "params": {"label": label, "code": code}, **extra}


def render(location, mode: str = "shaded", look_at=(0.0, 0.0, 0.3), **extra) -> dict:
    return {"call": "render", "params": {"camera": {"location": list(location), "look_at": list(look_at)},
                                         "mode": mode, "size": 128}, **extra}


def done(result: str) -> dict:
    return {"subtype": "success", "is_error": False, "result": result}


# -- the stage ----------------------------------------------------------------

class Stage:
    def __init__(self, work: Path):
        self.work = Path(work)

    @property
    def scene(self):
        return bpy.context.scene

    @property
    def props(self):
        return bpy.context.scene.whittle

    @property
    def ctl(self) -> turn.TurnController:
        return turn.current()

    def override(self) -> dict:
        win = bpy.context.window_manager.windows[0]
        area = max((a for a in win.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
        region = next(r for r in area.regions if r.type == "WINDOW")
        return {"window": win, "screen": win.screen, "area": area, "region": region}

    def run(self, fn, *args, **kwargs):
        """Calls fn(context, ...) as an operator in the 3D viewport would."""
        with bpy.context.temp_override(**self.override()):
            return fn(bpy.context, *args, **kwargs)

    def script(self, name: str, turns: list) -> Path:
        path = self.work / f"fake-{name}.json"
        path.write_text(json.dumps({"turns": turns}, indent=1))
        return path

    def crate(self, *, pick: bool = True):
        """The crate scene, the crate selected and, with pick, the target."""
        crate = build_scene()
        for obj in self.scene.objects:
            obj.select_set(False)
        if pick:
            crate.select_set(True)
            bpy.context.view_layer.objects.active = crate
            self.run(targets.set_from_selection)
        return crate

    def add_object(self, name: str, location, size=(0.3, 0.3, 0.3)):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([(x * size[0] / 2, y * size[1] / 2, z * size[2] / 2)
                          for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], [],
                         [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
        obj = bpy.data.objects.new(name, mesh)
        obj.location = location
        self.scene.collection.objects.link(obj)
        return obj

    def submit(self, prompt: str, script: Path) -> str:
        """Types the prompt and presses Submit with the fake agent playing script."""
        bpy.context.window_manager.whittle_fake_script = str(script)
        self.props.prompt = prompt
        _ctl, node = self.run(operators.submit_sketch)
        return node

    def finished(self, node: str) -> Until:
        def check():
            ctl = self.ctl
            if ctl.errors:
                raise RuntimeError(f"the controller reported: {ctl.errors}")
            return (ctl.last_finished or {}).get("turn_id") == node and not operators.busy(ctl)
        return Until(check, f"turn {node} to finish")

    def turns(self, prompts, script: Path):
        """Submits each prompt in turn and waits for its turn to end."""
        nodes = []
        for prompt in prompts:
            nodes.append(self.submit(prompt, script))
            yield self.finished(nodes[-1])
        return nodes

    def tools(self, status: str) -> list:
        ctl = self.ctl
        return [e for e in ctl.stream.entries() if e.kind == "tool" and e.status == status] if ctl else []

    def write_image(self, name: str, colour) -> Path:
        """A small gradient PNG to stand in for a reference photo."""
        size = 96
        img = bpy.data.images.new(name, size, size)
        pixels = []
        for y in range(size):
            for x in range(size):
                t = (x + y) / (2 * size)
                pixels += [colour[0] * (0.4 + t), colour[1] * (0.4 + t), colour[2] * (0.4 + t), 1.0]
        img.pixels.foreach_set(pixels)
        path = self.work / f"{name}.png"
        img.filepath_raw = str(path)
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)
        return path


# -- scenarios ----------------------------------------------------------------

SCENARIOS = {}


def scenario(fn=None, *, open_panels: bool = False):
    def add(fn):
        fn.open_panels = open_panels
        SCENARIOS[fn.__name__] = fn
        return fn
    return add(fn) if fn is not None else add


@scenario
def empty(stage: Stage):
    stage.crate(pick=False)
    yield 0.2


@scenario
def start(stage: Stage):
    # The default cube scene as a new file shows it, the cube selected.
    yield 0.2


@scenario
def prompt_typed(stage: Stage):
    stage.crate()
    stage.props.prompt = "Add a lid to the crate."
    yield 0.2


@scenario
def shortcut_popup(stage: Stage):
    """Shift+Alt+C's popup, opened by its own operator, a prompt half typed
    in its field."""
    stage.crate()
    stage.props.prompt = "Add a lid to the"
    yield 0.2
    return Popup("operator", "whittle.type_prompt")


@scenario
def prompt_only_done(stage: Stage):
    stage.crate()
    yield from stage.turns(["Add a lid to the crate."], FAKE / "stream.json")


@scenario
def sketching(stage: Stage):
    stage.crate()
    obj = sketch.ensure_sketch_layers(stage.scene)
    bundle = formats.read_bundle(CRATE_BUNDLE)
    for view_id in sorted(bundle.views):
        views.add_view(obj.data, lambda _i, view=bundle.views[view_id]: view)
    for stroke in bundle.strokes:
        add_stroke(obj, stroke.type, stroke.points, radius=stroke.radius, opacity=stroke.opacity,
                   cyclic=stroke.cyclic, view=stroke.view)
    sketch.set_active_type(obj, "carve")
    bpy.context.window_manager.whittle_show_views = True
    stage.props.prompt = bundle.request.prompt
    stage.run(sketch.start_session)
    yield Until(lambda: sketch.current_session() is not None, "sketch mode")


@scenario
def streaming(stage: Stage):
    stage.crate()
    script = stage.script("streaming", [{"steps": [
        say("Plan: add a lid that overhangs the crate a little, then carve a handle slot on "
            "each side and check the result from two angles."),
        exec_("add lid", LID),
        render((1.5, -1.5, 1.2)),
        say("The lid sits right. Now the handle slots."),
        {"gather": [
            exec_("carve handle slots", "print('carving')", delay=90),
            render((-1.5, -1.5, 1.0), delay=90),
        ]},
    ]}])
    stage.submit("Add a lid and carve a handle slot on each side.", script)
    yield Until(lambda: len(stage.tools("pending")) >= 2 and len(stage.tools("ok")) >= 2,
                "two calls in flight")


@scenario
def conversation(stage: Stage):
    stage.crate()
    script = stage.script("conversation", [
        {"steps": [say("I'll add a lid that overhangs the crate by a couple of centimetres."),
                   exec_("add lid", LID), render((1.5, -1.5, 1.2)),
                   say("Done: the crate has a lid.")], "finish": done("Added a lid.")},
        {"steps": [say("Carving a handle slot into the front face."),
                   exec_("handle slot", "bpy.data.objects['Crate'].scale.z = 1.05"),
                   render((0.0, -2.0, 0.6)), say("The front has a handle slot now.")],
         "finish": done("Carved a handle slot.")},
        {"steps": [say("Darkening the wood and lightening the lid for contrast."),
                   exec_("recolour", "bpy.data.materials['Wood'].diffuse_color = (0.3, 0.18, 0.08, 1)"),
                   render((-1.5, -1.5, 1.2), mode="matcap"), say("Recoloured.")],
         "finish": done("Recoloured the crate.")},
    ])
    yield from stage.turns(["Add a lid to the crate.", "Carve a handle slot in the front.",
                            "Make the wood darker."], script)


MARKDOWN_REPLY = """## What I changed

I grew **two horns** out of the sphere's top, so it is still *one closed mesh*:

- Each horn is 5 rings, tapering to a point
- They curve outwards, mirrored left and right
  - fused with `mesh_report` showing **1 shell**
1. Checked from the front
2. Checked from three-quarters

> The horns are a little long; say if you want them shorter.

```
shells 1 · watertight · 1,248 tris
```"""


@scenario
def markdown(stage: Stage):
    stage.crate()
    script = stage.script("markdown", [
        {"steps": [say("Growing two horns from the top of the crate."),
                   exec_("horns", "bpy.data.objects['Crate'].scale.z = 1.05"),
                   render((1.5, -1.5, 1.2)), say(MARKDOWN_REPLY)],
         "finish": done("Added two horns.")},
    ])
    yield from stage.turns(["Add two horns."], script)


# Every kind of Markdown a reply to "write a markdown stress test" holds,
# each at least once.
MARKDOWN_STRESS = r"""# H1 Stress Test
Intro line under the title.
## H2 Section
### H3 Subsection
#### H4 Level four
##### H5 Level five
###### H6 Level six

**Bold**, *italic*, ***both***, ~~struck out~~, `inline_code(42)` and snake_case_name.
Escapes: \*not italic\*, \`not code\`, \<b\>, \# \[x\] \\ done.
Hard break with two spaces
and with a backslash\
then the rest.

- [x] Done task
- [ ] Open task
- Plain bullet
  1. Nested number
     - deeper

> A quote with **bold**
>
> - a list in a quote
>> A nested quote
>>> Three deep

    indented_code = True
    print(indented_code)

```python
def f(x):
    return x ** 2  # fenced
```

| Left | Centre | Right |
|:-----|:------:|------:|
| a | b | 1 |
| a longer cell that wraps inside its column | `code` | 22.5 |

Inline maths $E = mc^2$, $x_1 + x_2$, $\frac{a}{b}$ and $\alpha \leq \beta$.
$$\int_0^1 x^2 \, dx = \tfrac{1}{3} \quad \sum_{i=1}^{n} i \cdot \sqrt{x} \times \pi \neq \foo$$

<details><summary>Click to expand</summary>

Hidden **body** text.
</details>

HTML: <b>bold</b>, <em>italic</em>, <code>code</code>, <kbd>Ctrl</kbd>+<kbd>Z</kbd>,
<span>span</span>,<br>after a br, &lt;tag&gt; &amp; &quot;q&quot; &#39;s&#39; a&nbsp;b.
Emoji: 🎲 🧊 ✅ 🚀 👍🏽 1️⃣ ❤️
Links: [the docs](https://docs.blender.org) and <https://claude.ai>.
One link: https://en.wikipedia.org/wiki/Foo_(bar).
A footnote here[^1] and another[^note].

[^1]: The first footnote.
[^note]: The second, *styled*."""


@scenario
def markdown_stress(stage: Stage):
    """The whole stress test at once."""
    stage.crate()
    script = stage.script("markdown_stress", [{"steps": [say(MARKDOWN_STRESS)], "finish": done("Done.")}])
    yield from stage.turns(["Write a Markdown stress test."], script)


@scenario
def branched(stage: Stage):
    stage.crate()
    script = stage.script("branched", [
        {"steps": [say("Adding a lid."), exec_("add lid", LID), render((1.5, -1.5, 1.2)),
                   say("Done.")], "finish": done("Added a lid.")},
        {"steps": [say("Adding metal handles on both sides."),
                   exec_("metal handles", "bpy.data.objects['Crate'].scale.x = 1.05"),
                   render((0.0, -2.0, 0.6)), say("Metal handles added.")],
         "finish": done("Added metal handles.")},
        {"steps": [say("Adding rope handles instead."),
                   exec_("rope handles", "bpy.data.objects['Crate'].scale.y = 1.05"),
                   render((0.0, -2.0, 0.6)), say("Rope handles added.")],
         "finish": done("Added rope handles.")},
    ])
    first, second = yield from stage.turns(["Add a lid.", "Add metal handles on both sides."], script)
    stage.run(operators.branch_node, second)
    yield from stage.turns(["Add rope handles on both sides."], script)


@scenario
def branch_edit(stage: Stage):
    """After Edit & Resend on the second turn: the scene is back at the
    first, and the second's prompt is in the prompt box again."""
    stage.crate()
    script = stage.script("branch_edit", [
        {"steps": [say("Lid added."), exec_("add lid", LID), render((1.5, -1.5, 1.2))],
         "finish": done("Added a lid.")},
        {"steps": [say("Rope handles added."),
                   exec_("rope handles", "bpy.data.objects['Crate'].scale.y = 1.05"),
                   render((0.0, -2.0, 0.6))], "finish": done("Added rope handles.")},
    ])
    _first, second = yield from stage.turns(["Add a lid.", "Add rope handles on both sides."], script)
    stage.run(operators.branch_node, second)
    yield 0.2


@scenario
def asking(stage: Stage):
    stage.crate()
    script = stage.script("asking", [{"steps": [
        say("Adding the lid first."),
        exec_("add lid", LID),
        {"ask": "Should the lid overhang the crate by 1 cm, or sit flush with its sides?",
         "choices": ["Overhang", "Flush"]},
        say("Going with that."),
    ]}])
    stage.submit("Add a lid to the crate.", script)
    yield Until(lambda: stage.ctl.question is not None, "the question")


@scenario
def interrupted(stage: Stage):
    stage.crate()
    script = stage.script("interrupted", [{"steps": [
        say("Adding the lid, then carving handle slots on all four sides."),
        exec_("add lid", LID),
        say("Now the handle slots."),
        exec_("carve handle slots", "print('carving')", delay=60),
        say("This is never said: the turn was interrupted."),
    ]}])
    node = stage.submit("Add a lid and handle slots.", script)
    yield Until(lambda: stage.tools("pending"), "a call in flight")
    operators.interrupt("KEEP")
    yield stage.finished(node)


@scenario
def error_turn(stage: Stage):
    stage.crate()
    script = stage.script("error_turn", [
        {"steps": [say("Adding a lid."),
                   exec_("add lid", "lid = bpy.data.objects.new('Crate_Lid', None\n"),
                   say("That had a syntax error; fixing it."),
                   exec_("add lid", LID), render((1.5, -1.5, 1.2)),
                   say("Done: the crate has a lid.")], "finish": done("Added a lid.")},
        {"steps": [say("Scaling the crate up, then adding feet."),
                   exec_("scale", "bpy.data.objects['Crate'].scale = (1.2, 1.2, 1.2)"),
                   {"call": "inspect", "params": {"query": "object", "name": "Crate_Feet"},
                    "expect": "error:not_found"}],
         "finish": {"subtype": "error_during_execution", "is_error": True, "result": ""}},
    ])
    yield from stage.turns(["Add a lid.", "Make it bigger and give it feet."], script)


@scenario
def folded_failure(stage: Stage):
    """A turn that failed without changing anything: not in the history,
    shown once with Retry, the prompt box left empty."""
    stage.crate()
    script = stage.script("folded_failure", [
        {"steps": [say("Looking at the crate first."),
                   {"call": "inspect", "params": {"query": "summary"}, "expect": "ok"}],
         "finish": {"subtype": "error_max_turns", "is_error": True, "result": ""}},
    ])
    yield from stage.turns(["Add a lid with brass hinges."], script)


@scenario
def crashed(stage: Stage):
    stage.crate()
    script = stage.script("crashed", [{"steps": [say("Starting on the lid."), {"sleep": 0.2},
                                                 {"fail": "scripted crash"}]}])
    node = stage.submit("Add a lid.", script)
    yield Until(lambda: not operators.busy(stage.ctl) and stage.ctl.process.state == "crashed",
                f"the agent to crash during {node}")


@scenario
def setup_needed(stage: Stage):
    """No agent environment: Send finds none and the panel offers to set
    one up."""
    stage.crate()
    os.environ["WHITTLE_AGENT_PYTHON"] = str(stage.work / "no-such-python")
    stage.props.prompt = "Add a lid."
    try:
        stage.run(operators.submit_sketch)
    except RuntimeError:
        pass
    yield Until(lambda: stage.ctl is not None and stage.ctl.process.state == "needs_setup",
                "the setup prompt")


@scenario
def key_needed(stage: Stage):
    """No API key in the preferences or the environment: Send starts
    nothing and the panel asks for a key."""
    stage.crate()
    os.environ.pop("ANTHROPIC_API_KEY", None)
    stage.props.prompt = "Add a lid."
    try:
        stage.run(operators.submit_sketch)
    except RuntimeError:
        pass
    yield Until(lambda: stage.ctl is not None and stage.ctl.process.state == "needs_key",
                "the API key prompt")


@scenario
def comparing(stage: Stage):
    stage.crate()
    script = stage.script("comparing", [
        {"steps": [say("Lid added."), exec_("add lid", LID)], "finish": done("Added a lid.")},
        {"steps": [say("Wood darkened."),
                   exec_("recolour", "bpy.data.materials['Wood'].diffuse_color = (0.3, 0.18, 0.08, 1)")],
         "finish": done("Recoloured.")},
    ])
    first, _second = yield from stage.turns(["Add a lid.", "Make the wood darker."], script)
    stage.run(operators.compare_node, first)
    yield 0.2


@scenario
def manual_targets(stage: Stage):
    crate = stage.crate(pick=False)
    stage.props.target_auto = False
    lid = stage.add_object("Crate_Lid", (0.0, 0.0, 0.53), (0.54, 0.54, 0.04))
    barrel = stage.add_object("Barrel", (1.0, 0.0, 0.3), (0.4, 0.4, 0.6))
    targets.add(stage.scene, [crate, lid])
    # The selection is elsewhere: the picked target does not follow it.
    barrel.select_set(True)
    bpy.context.view_layer.objects.active = barrel
    stage.props.prompt = "Give the crate and its lid matching bevels."
    yield 0.2


@scenario
def long_session(stage: Stage):
    stage.crate()
    turns, prompts = _nudges(13)
    yield from stage.turns(prompts, stage.script("long_session", turns))


def _nudges(count: int, start: int = 1) -> tuple[list, list]:
    turns, prompts = [], []
    for k in range(start, start + count):
        turns.append({"steps": [say(f"Nudging the crate, step {k}."),
                                exec_(f"nudge {k}", "bpy.data.objects['Crate'].location.x += 0.01"),
                                say(f"Nudged ({k}).")], "finish": done(f"Nudged {k}.")})
        prompts.append(f"Step {k}: move the crate a centimetre along x.")
    return turns, prompts


@scenario
def history_popover(stage: Stage):
    """A 13-turn tree with two branches, shown in the history popover."""
    stage.crate()
    turns, prompts = _nudges(13)
    script = stage.script("history_popover", turns)
    nodes = yield from stage.turns(prompts[:9], script)
    # Another take on the fourth turn, two turns long.
    stage.run(operators.branch_node, nodes[3])
    yield from stage.turns(prompts[9:11], script)
    # And another on the seventh turn of the first branch.
    stage.run(operators.branch_node, nodes[6])
    yield from stage.turns(prompts[11:], script)
    return Popup("panel", "WHITTLE_PT_history")


@scenario
def turn_menu(stage: Stage):
    stage.crate()
    script = stage.script("turn_menu", [
        {"steps": [say("Lid added."), exec_("add lid", LID), render((1.5, -1.5, 1.2))],
         "finish": done("Added a lid.")},
        {"steps": [say("Wood darkened."),
                   exec_("recolour", "bpy.data.materials['Wood'].diffuse_color = (0.3, 0.18, 0.08, 1)")],
         "finish": done("Recoloured.")},
    ])
    first, _second = yield from stage.turns(["Add a lid.", "Make the wood darker."], script)
    return Popup("operator", "whittle.turn_menu", {"node": first})


@scenario
def references(stage: Stage):
    stage.crate()
    for name, colour, pinned in (("crate_front", (0.8, 0.5, 0.2), True), ("crate_side", (0.3, 0.5, 0.8), False)):
        ref = stage.props.refs.add()
        ref.path = str(stage.write_image(name, colour))
        ref.pinned = pinned
    stage.props.prompt = "Match the proportions in the reference photos."
    yield 0.5


@scenario(open_panels=True)
def developer(stage: Stage):
    bpy.context.preferences.view.show_developer_ui = True
    stage.crate()
    yield from stage.turns(["Add a lid to the crate."], FAKE / "stream.json")


# -- chats --------------------------------------------------------------------

HOUR, DAY = 3600, 86400


def _chat(stage: Stage, name: str, prompts: list[str], *, new: bool = True):
    """A chat made the way the sidebar makes one: New Chat (unless it is
    the file's first), then its turns through the fake agent."""
    if new:
        stage.run(operators.new_chat)
    turns, _ = _nudges(len(prompts))
    yield from stage.turns(prompts, stage.script(name, turns))
    return chats.get().current


def _age(chat: str, seconds: float) -> None:
    """The chat's last turn moved back in time, so the menu's ages are the
    same from run to run."""
    store = chats.get()
    store.entry(chat).updated = chat_store.iso(time.time() - seconds)
    store.save()


def _three_chats(stage: Stage):
    """Crate (two turns), barrel and lamp chats, oldest last."""
    stage.crate()
    crate = yield from _chat(stage, "crate", ["Add a lid and rope handles to the crate.",
                                              "Make the rope handles thicker."], new=False)
    barrel = yield from _chat(stage, "barrel", ["Make a barrel with two metal bands."])
    lamp = yield from _chat(stage, "lamp", ["Model a lamp post beside the crate, about 2 m tall."])
    _age(crate, 2 * HOUR)
    _age(barrel, 5 * 60)
    _age(lamp, 9 * DAY)
    return crate, barrel, lamp


@scenario
def chat_menu(stage: Stage):
    crate, _barrel, _lamp = yield from _three_chats(stage)
    stage.run(operators.switch_chat, crate)
    return Popup("panel", "WHITTLE_PT_chats")


MANY_TITLES = [
    "Barrel with metal bands", "Lamp post", "Market stall with a striped awning and crates of fruit",
    "Wooden bench", "Treasure chest with iron corners and a domed, studded lid", "Well with a roof",
    "Cart wheel", "Signpost", "Rowing boat with oars resting across the seats", "Anvil", "Stool",
    "Hay bale", "Lantern on a hook", "Fence section with a gate that swings inwards", "Bucket",
    "Bookshelf full of books of every size", "Cauldron", "Archery target on a stand", "Ladder",
    "Mailbox", "Tent", "Totem pole with four carved animals stacked", "Rocking chair",
]


@scenario
def chat_menu_many(stage: Stage):
    """25 chats: two made through the agent, the rest copies of the first
    with their own titles, ages and sizes."""
    stage.crate()
    first = yield from _chat(stage, "many-1", ["Add a lid and rope handles to the crate."], new=False)
    second = yield from _chat(stage, "many-2", ["Make the crate taller, then add feet."])
    store = chats.get()
    # Every age the menu says within the first 20, then older ones.
    ages = [10, 20 * 60, 3 * HOUR, 20 * HOUR, 30 * HOUR, 3 * DAY, 9 * DAY, 15 * DAY, 40 * DAY, 60 * DAY,
            120 * DAY, 200 * DAY, 300 * DAY, 400 * DAY, 450 * DAY, 500 * DAY, 550 * DAY, 600 * DAY,
            650 * DAY, 700 * DAY, 750 * DAY, 800 * DAY, 900 * DAY]
    for i, (title, age) in enumerate(zip(MANY_TITLES, ages)):
        chat = store.new()
        shutil.rmtree(store.folder(chat))
        shutil.copytree(store.folder(first), store.folder(chat))
        store.refresh(chat)
        entry = store.entry(chat)
        entry.title = title
        entry.turns = 1 + (i * 7) % 15
        entry.size = 120_000 + (i * 733_000) % 4_800_000
        entry.updated = chat_store.iso(time.time() - age)
    _age(first, 2 * HOUR)
    _age(second, 30)
    store.index.current = first
    store.save()
    return Popup("panel", "WHITTLE_PT_chats")


@scenario
def new_chat(stage: Stage):
    stage.crate()
    yield from _chat(stage, "first", ["Add a lid and rope handles to the crate."], new=False)
    stage.run(operators.new_chat)
    yield 0.2


@scenario
def switched_chat(stage: Stage):
    stage.crate()
    script = stage.script("switched", [
        {"steps": [say("Adding a lid."), exec_("add lid", LID), render((1.5, -1.5, 1.2)), say("Done.")],
         "finish": done("Added a lid.")},
        {"steps": [say("Adding metal bands near both ends."),
                   exec_("bands", "bpy.data.objects['Crate'].scale.x = 1.05"),
                   render((0.0, -2.0, 0.6)), say("Two bands added.")], "finish": done("Added bands.")},
    ])
    # A first prompt long enough that the header shortens the title.
    yield from stage.turns(["Add a lid with brass hinges, then two metal bands near both ends.",
                            "Add two metal bands."], script)
    earlier = chats.get().current
    yield from _chat(stage, "other", ["Make the crate twice as tall."])
    stage.run(operators.switch_chat, earlier)
    yield 0.2


@scenario
def continue_chat(stage: Stage):
    """A chat made on another machine: it reads, and asks before sending."""
    stage.crate()
    yield from _chat(stage, "foreign", ["Add a lid and rope handles to the crate."], new=False)
    store = chats.get()
    store.entry(store.current).origin = "i00000000000000ff"
    store.save()
    stage.props.prompt = "Make the handles thicker."
    yield 0.2


@scenario
def open_elsewhere(stage: Stage):
    """The same file open in another Blender: one quiet line at the top."""
    stage.crate()
    yield from _chat(stage, "elsewhere", ["Add a lid and rope handles to the crate."], new=False)
    # Another Blender's claim on a cache of the same file, without one.
    chats.open_elsewhere = lambda **_kw: True
    yield 0.2


@scenario
def delete_confirm(stage: Stage):
    crate, barrel, _lamp = yield from _three_chats(stage)
    stage.run(operators.switch_chat, crate)
    return Popup("operator", "whittle.chat_delete", {"chat": barrel})


@scenario
def delete_many(stage: Stage):
    crate, _barrel, lamp = yield from _three_chats(stage)
    _age(lamp, 45 * DAY)
    stage.run(operators.switch_chat, crate)
    return Popup("operator", "whittle.chat_delete_many", {})


# -- models -------------------------------------------------------------------

# What the Models API lists for a key (only the newest of each family here).
LISTED = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]


def _model_chat(stage: Stage, model: str):
    """A chat with one turn, then on model for its next, with the account's
    list as the agent reported it an hour ago."""
    stage.crate()
    yield from _chat(stage, "model", ["Add a lid and rope handles to the crate."], new=False)
    model_store.write_cache(models.cache_path(), LISTED, "api", fetched=time.time() - HOUR)
    models.set_chat_model(model)
    yield 0.2


@scenario
def model_menu(stage: Stage):
    yield from _model_chat(stage, "claude-sonnet-5-5")
    return Popup("operator", "wm.call_menu", {"name": "WHITTLE_MT_models"})


@scenario
def model_menu_older(stage: Stage):
    yield from _model_chat(stage, "claude-opus-4-6")
    return Popup("operator", "wm.call_menu", {"name": "WHITTLE_MT_models_older"})
