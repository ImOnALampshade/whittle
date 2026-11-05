# Writing a page's screenshots

Each page has one spec, `docs/site/shots/<page-slug>.py` (`guides/api-key` is
`guides-api-key`), declaring `SHOTS`. Images land in
`docs/site/images/<page-slug>/<shot>.png`; the page shows one with
`![Alt text](/images/<page-slug>/<shot>.png)`. `_example.py` here works and has
one of everything: `./docs_shots.sh _example`, images in
`build/docs-shots/images/_example/`.

```sh
./docs_shots.sh <page-slug> [shot ...]   # shoot a page, or some of its shots
./docs_shots.sh --check                  # validate every spec; launches nothing
./docs_shots.sh --list                   # every shot
./docs_shots.sh --all                    # every page
```

Run as many as you like at once: each Blender has its own hidden session and
folders, nothing reaches the desktop, and a machine-wide queue runs a few at a
time (a queued run blocks and says so; it can take minutes when many run, so
start it in the background). A failed shot exits non-zero, keeps the old image
and prints its log's path. Look at every PNG you make.

## A spec

```python
from tests.docshots.spec import (LID, Popup, Shot, Snap, done, exec_, popup, preferences, region, render, say,
                                 sidebar, turns, viewport, window)

SHOTS = [
    # Reuse a scenario (tests/screens/catalog.py lists them): it knows what to capture.
    Shot("chat-menu", "The chat menu over three chats.", scenario="chat_menu"),
    # A scenario, captured another way.
    Shot("three-turns", "The viewport after three turns.", viewport(), scenario="conversation"),
    # A scripted turn, no code: the crate, then these prompts against a fake script.
    Shot("one-turn", "One finished turn.", sidebar(), setup=turns("lid.json", "Add a lid to the crate.")),
]
```

Keep everything but `SHOTS` free of `bpy` at the top of the file: `--check`
imports specs outside Blender. Import `bpy` inside a setup if you need it. New
states live in your spec, never in a shared file; a shot name is `lower-case-with-hyphens`,
and the description is one line.

**What to capture**

| | |
|---|---|
| `sidebar()` | the Whittle sidebar, stitched to its whole length |
| `viewport()` | the 3D viewport |
| `window()` | the whole window |
| `region("OUTLINER")` | an area by type; `region("VIEW_3D", "HEADER")` one of its regions; `region(box=(x, y, w, h))` a box from the window's top left |
| `popup(panel="WHITTLE_PT_agent")` | a popover over the sidebar, cropped to it; also `menu="WHITTLE_MT_models"`, `operator="whittle.type_prompt", props={...}` |
| `preferences()` | Whittle's preferences as Blender opens them; `preferences(scroll=6)` further down, `preferences(full=True)` the whole list |
| `preferences("EXTENSIONS")` | another section; `preferences("KEYMAP", search="Whittle")` filtered; `preferences("EXTENSIONS", menu="USERPREF_MT_extensions_settings")` a menu over it |
| `window(of="FILE_BROWSER", crop=...)` | a further window a setup opened |

Any of these but `region` takes `crop=(x, y, w, h)` from the image's top left.
`preferences()` needs no setup. `Shot(..., wide=1.6)` widens the sidebar.

## A setup of your own

A setup is a generator over `stage`. It yields a number to wait that long, or
`Until(check, "what")` to wait for a condition; when it ends, the shot is taken.
Shots that share a setup run in one Blender, on one continuing scene: `yield
Snap("name")` takes a shot there and then, and a shot no `Snap` names is taken
at the end.

```python
def story(stage):
    stage.crate()                                   # the crate, selected and targeted
    script = stage.fake("lid_and_handles.json")     # docs/site/shots/fake/<page-slug>/, else tests/fixtures/fake/
    yield from stage.turns(["Add a lid to the crate."], script)
    yield Snap("after-lid")
    yield from stage.turns(["Add rope handles on both sides."], script)
    stage.orbit((3.0, -4.0, 2.5), 2.2)              # the crate is small until the view moves
    yield 0.3
    yield Snap("after-handles", "after-handles-viewport")
    node = stage.history().tree.current
    yield Snap("turn-menu", popup=Popup("operator", "whittle.turn_menu", {"node": node}))

SHOTS = [
    Shot("after-lid", "The sidebar after the first turn.", sidebar(), setup=story),
    Shot("after-handles", "The sidebar after the second turn.", sidebar(), setup=story),
    Shot("after-handles-viewport", "The crate after the second turn.", viewport(), setup=story),
    Shot("turn-menu", "A turn's menu.", popup(), setup=story),
]
```

A fake script is `{"turns": [{"steps": [...], "finish": {...}}]}`, one entry per
turn; `tests/fixtures/fake/` has plenty to copy. A short one can stay in the
spec, with `stage.script("name", [{"steps": [say("Adding a lid."), exec_("add
lid", LID), render((1.5, -1.5, 1.2))], "finish": done("Added a lid.")}])`.

`stage` is the scenarios' `Stage` (`tests/screens/scenarios.py`: `crate`, `props`,
`submit`, `finished`, `turns`, `add_object`, `run`, `script`, `write_image`,
`scroll_sidebar_to_end`), with the GUI checks' simulated input
(`tests/gui/checks.py`: `press`, `click`, `drag`, `move`, `type_text`, `button`)
and `fake`, `orbit`, `chat`, `age`, `preferences` (Whittle's add-on preferences)
and `agent_ready()` (the Preferences say Ready). Copy from the scenarios: they
show sketches, branches, chats and models. `Until`, `Popup`, `say`, `exec_`,
`render`, `done` and the turns' code (`LID`, `ROPE_HANDLES`, `HORNS`, ...) come
from `tests.docshots.spec`.

## Good to know

- Every shot starts the same: factory Blender with Whittle installed as a user
  has it, the default cube scene, one fixed window. `sidebar` and `popup` shots
  run at 1400 x 2000, and a setup with any `viewport`, `window` or `region` shot
  at 1600 x 1000. Re-shooting gives the same pixels; the image is left alone
  then, so a changed image in `git status` means a changed picture.
- The agent is the fake one and there is never an API key, so no shot can show
  a real reply: write it in the fake script. Set `stage.preferences.api_key` to
  an obviously fake value for a shot of a filled-in key; it stays in the run.
- A setup has 150 s, plus 30 s for each further shot; `Shot(..., deadline=120)`
  adds to that. A run's Blender logs are in `build/docs-shots/<run>/`, kept after
  a failure.
- `wide=` drags the sidebar's edge, so a `window()` shot's status bar then says
  Resize Region; crop the last rows off if it matters.
- Time-dependent text is yours to pin: `stage.age(chat, seconds)` for a chat's age.
- A file browser shows this machine's folders, so crop to the part you want.
  Anything else that shows a path, set to something neutral first.
- Shots are of the extension as built from `whittle/`, once per change to it
  (the first run after an edit takes a few seconds longer).
