# Prompts and targets

A turn is one exchange: you send a request, Claude edits the scene and replies. It starts
with a prompt, a sketch, reference images or any mix of them, and works on a target. This page covers what to write, how to choose the target, how to steer a turn
while it runs, and what Claude does before it reports back.

## Write a prompt

1. Open the Whittle tab in the 3D viewport's sidebar (N).
2. Check the target line at the top: it says what Claude will work on.
3. Click the box that says *Ask Claude…* and type. **Shift+Enter** adds a line. The box scrolls past three lines, and you can drag its corner to make it taller.
4. Press **Enter** or **Send**. The text moves into the conversation as your turn.

:::{figure} ../images/guides-prompting/prompt-typed.png
:alt: The Whittle sidebar with Crate on the target line, Auto on, and "Add a lid to the crate." in the prompt box above the Send button

The crate is the target and a prompt is ready to send.
:::

**Send** is available once there is a prompt, a stroke not yet sent or a reference image,
so a sketch on its own is a complete request ([Sketching](sketching.md),
[Reference images](references.md)). It is greyed out while you
[compare with an earlier turn](history.md), and in a
[chat from another machine](chats.md) until you continue it. Clicking away from the box
never sends, and Enter in a blank box does nothing.

If the turn cannot start, for example because there is no [API key](api-key.md), your
prompt stays in the box.

### What makes a good prompt

Say what you want changed, in the words you would use with a person. Claude reads the
prompt together with the sketch and references, so a prompt can be short when the strokes
say where: "carve this slot" over a stroke needs nothing more.

- **Give sizes when they matter.** Claude builds in real units (1 Blender unit is 1 metre)
  and picks sensible real-world sizes for the rest, such as about 0.5 m for a crate.
- **Say what to keep apart or fuse together.** By default a part that belongs to the body
  is fused into one closed mesh, and a part that moves on its own, like a lid or a wheel,
  stays a separate object parented to the body. Ask if you want it otherwise.
- **Name the look.** Claude uses flat colours or vertex colours, not textures. For a look
  that should hold across a whole file, set a palette, bevel style or style notes in
  [Settings](settings.md) instead of repeating it. A prompt or sketch wins over those.
- **Ask for one edit at a time.** Each turn is a step in the
  [history](history.md) you can go back to or branch from, so smaller turns give you more
  places to return to.

Claude makes routine calls itself, such as segment counts or how a part attaches. It says
so when it sees a better approach, then does what you asked. It only stops to ask when
your request could mean very different geometry ([below](#answer-a-question)).

## Choose the target

The target is what Claude edits. It is asked to leave every other object alone, and new
objects it makes join the target when the turn ends, so a follow-up can change them.
That is an instruction Claude follows rather than a lock on the scene: see
[Privacy and safety](privacy.md).

### Auto: follow the selection

**Auto** is on by default, and the target follows your selection in Object Mode:

1. The selected objects, with the active object first.
2. If nothing is selected, the active object.
3. If there is neither, nothing: Claude makes new objects.

A [target collection](#pick-targets-by-hand) stays a target on top of these.

Cameras, lights, light probes, speakers, the Whittle Sketch object and reference images
never count as targets.

:::{figure} ../images/guides-prompting/nothing-selected.png
:alt: The Whittle sidebar with the target line reading "Nothing selected: Claude adds new objects"

With nothing to target, the target line says Claude adds new objects. The **Start from**
row is covered in [The sidebar](sidebar.md).
:::

Auto holds still in other modes (Edit Mode, or while you sketch), during a comparison and
during a turn, so selecting something while you draw does not change the target. When a
turn ends, Whittle selects the target, new objects included, so the next prompt carries on
from there.

### Pick targets by hand

Turn **Auto** off when the target should stay put while you select other things.

1. Click **Auto** on the target line. The current target stays, listed one row per object.
2. Select an object in the viewport and press **Add** with its name (**Add 2 Selected** for
   several).
3. Press the ✕ on a row to remove that object.

:::{figure} ../images/guides-prompting/manual-targets.png
:alt: The target line reading "2 targets" with Auto off, rows for Crate and Crate_Lid, and an Add Barrel button

Crate and Crate_Lid are the targets. Barrel is selected but not a target until you press
**Add Barrel**.
:::

The three-dots button beside **Add** has three more things:

- **Collection**: every object in this collection is a target too, and Claude is told to
  put new objects in it. It stays part of the target with **Auto** back on, where the target
  line shows it as `Props (3)`, after any other targets, or as `New objects in Props` while
  it is empty. To clear it, turn Auto off and empty this field or press **Clear**.
- **Replace With Selection**: makes the selected objects the whole list.
- **Clear**: empties the list, so Claude makes new objects.

:::{figure} ../images/guides-prompting/target-options.png
:alt: A small popover with a collection field and the buttons Replace With Selection and Clear

The options behind the three-dots button.
:::

While a turn runs, a lock icon replaces the object icon and the target cannot change.

## Type from anywhere with Shift+Alt+C

**Shift+Alt+C** opens a prompt field under the pointer, over any editor and in any mode,
sketching and Edit Mode included. It also opens the Whittle sidebar in the 3D viewport, so
you can watch the conversation.

:::{figure} ../images/guides-prompting/ask-claude.png
:alt: A popup titled Ask Claude with the text "Add a lid to the" selected in its field and the hint "Enter sends · End keeps your draft · long prompts: use the sidebar box"

The Ask Claude popup with a draft, selected: typing replaces it, **End** adds to it.
:::

- **Enter** sends, the same as Enter in the sidebar's box.
- **Esc** closes the popup and leaves the field as it was.
- A draft already in the field opens selected: typing replaces it, and **End** adds to it.

The popup uses the same field as the sidebar, so the text is in both. It follows what the
sidebar is doing: while a turn runs it amends the turn, and while Claude asks it answers.
The field is a single line, so write long prompts in the sidebar's box.

Rebind the key in **Preferences → Keymap** ([Keyboard shortcuts](shortcuts.md)).

## Watch a turn

The first Send starts Claude, which takes a moment, and the sidebar says
**Starting Claude…**. After that you
see Claude's short notes between folded groups of tool calls, and the model changing in the
viewport. Each group's header shows the step in flight, with its label: **exec** is a step that runs
Python.

:::{figure} ../images/guides-prompting/running.png
:alt: A running turn in the sidebar: the prompt, Claude's notes, a tool group whose header reads "exec · carve handle slots", and a Stop button below the prompt box

A turn in progress. The target line is locked and **Stop** has replaced **Send**.
:::

Blender stays usable between steps, but a step that runs Python holds Blender until it
returns. You can orbit and draw while Claude works, and Ctrl+Z works too
([Undo](undo.md)).

## Amend a running turn

To change course without stopping, add to the turn while it runs.

1. Type in the same box, or draw more strokes. **Amend** appears next to **Stop**.
2. Press **Amend** or **Shift+Alt+Enter**. **Enter** also sends typed text, but it does
   nothing for strokes alone with an empty box.

:::{figure} ../images/guides-prompting/amend-typed.png
:alt: The bottom of the sidebar during a turn: "Make the slots a bit wider." in the prompt box with Amend and Stop buttons below it

An amendment ready to send.
:::

Your message appears in the turn as an **Amend:** bubble. Claude folds it into the work
under way, rather than starting something new. A short note says when it was delivered.

:::{figure} ../images/guides-prompting/amended.png
:alt: A running turn with a box reading "Amend: Make the slots a bit wider." after Claude's notes

The amendment in the conversation.
:::

Amend works from the moment you press Send. If the turn has not started yet, the amendment
waits and a note says so. If the turn ends before the amendment reaches Claude, a note says
that too, the text goes back in the prompt box and any strokes are pending again, so
nothing you wrote is lost. You cannot amend once you have pressed Stop.

The model cannot change mid-turn, and a reference image added during a turn goes with the
next request.

## Answer a question

Claude asks when your request could mean materially different geometry. The turn pauses
until you reply, for up to a day, so there is no hurry.

:::{figure} ../images/guides-prompting/asking.png
:alt: The sidebar with a boxed question "Should the lid overhang the crate by 1 cm, or sit flush with its sides?" and the buttons Overhang and Flush

A question with two choices.
:::

- Press one of the choice buttons, if there are any.
- Or type your own answer in the box and press **Enter** or **Answer**. The **Answer**
  button appears once you have typed something.

Your reply appears in the turn as an **Answer:** bubble. **Shift+Alt+C** answers as well.

While a question is open the box is for the answer, so a typed amendment has to wait until
after it. Strokes are different: **Amend** still appears if you draw while Claude asks.

## Stop a turn

Press **Stop** and pick what happens to the work so far.

:::{figure} ../images/guides-prompting/stop-menu.png
:alt: The Stop menu with two items, Stop and Keep Changes and Stop and Undo This Turn

The two ways to stop.
:::

- **Stop and Keep Changes** leaves the target as Claude left it. The turn stays in the
  history as a partial turn.
- **Stop and Undo This Turn** puts the target back as it was when the turn started, and
  removes what Claude made.

The sidebar says **Stopping…** until the step that is running ends: Blender cannot cut
off Python that has started, so a slow step finishes first. The turn then ends with a dim
**Stopped, changes kept** or **Stopped, changes undone**.

:::{figure} ../images/guides-prompting/interrupted.png
:alt: A stopped turn in the sidebar ending with the line "Stopped, changes kept", the prompt box and Send button back below it

A turn stopped with its changes kept.
:::

After **Stop and Undo This Turn**, Claude is told with your next prompt that the target went
back, so it does not assume that work is still there. To take a turn back after it has finished, see [Undo](undo.md) and
[History and branches](history.md).

## Read Claude's replies

A finished turn ends with a short reply: what changed, and anything you may want to decide,
such as something it could not do. The scene shows the rest.

Claude's text and questions are Markdown, drawn in the sidebar:

- **Bold**, *italic*, struck-through and `code` styles, headings, lists and task boxes, quotes
  and tables.
- Code blocks sit in a box with a copy button.
- A line with a link has a button at its end that opens it. A line with several links
  opens a menu of them.
- Maths comes out as Unicode symbols, as well as it can.
- A collapsible section is a closed sub-panel, so its text stays hidden until you click it open.
- Footnotes come at the end of the reply. Emoji are drawn as outlines, and a few are left out.

:::{figure} ../images/guides-prompting/markdown.png
:alt: A reply in the sidebar with a heading, bold and italic text, nested and numbered lists, a quote and a code block with a copy button

A reply in Markdown.
:::

A sidebar label has only one text size, so headings show by their rule lines and dimming, and
inline code has no background.

## What Claude can do

Claude edits your open scene by running Python in Blender, so most things a script can do
are in reach: modelling, modifiers, Geometry Nodes, materials and object setup. It has
ready-made recipes for common jobs:

- bevels and creases along a stroke
- solid blockouts from a closed outline
- boolean cuts for holes, slots and grooves
- sweeps along a stroke, for handles, pipes and rope
- fusing parts into one mesh
- scattering small details over a surface
- round props spun from a half profile
- Mirror and Array set-ups
- flat colours per face and vertex colours

It also reads the scene (objects, materials, node groups and units), and can set a
checkpoint before a risky step and go back to it within the turn.

Python here runs as you, unsandboxed and without asking each time.
[Privacy and safety](privacy.md) says what that means and what each turn sends.

## How Claude checks its work

Claude cannot see your viewport. It checks an edit two ways before it finishes:

- **Numbers**: a mesh report on what it made or changed, which finds what a render hides,
  such as a buried base, an unwelded seam or a flipped face.
- **Pictures**: Workbench renders. With a sketch it renders from each of your sketch views
  with your strokes on top, and compares the model with them. Without a sketch it places
  two or three cameras around the target. It can also render wireframe and matcap images.

If something is clearly off, it fixes it and looks again, up to the limit of
**Self-check Rounds**. At the limit it stops and says what is left.

To see the checks, open a **Used N tools** group in the conversation. Each call opens to its
code and result, and each render has a thumbnail and a button that opens it in an Image
Editor. The last group ends with the turn's steps and cost. The turn's last render also
shows under its reply, and **Open Render** in the turn's three-dots menu opens it.

:::{figure} ../images/guides-prompting/self-check.png
:alt: A finished turn in the sidebar: the prompt, a closed group reading "Used 4 tools", Claude's short reply and a thumbnail of the crate with its lid

A finished turn. Its edit, mesh report and two renders are folded into **Used 4 tools**,
above the reply and the last render.
:::

| Setting | Default | Range | What it does |
|---|---|---|---|
| **Self-check Rounds** | 3 | 0 to 10 | How many fix rounds Claude may spend after its renders |
| **Render Size** | 512 | 64 to 1024 | The pixel size of its self-check renders |

Each round sends renders back to the model, so these are also two of the main levers on a
turn's cost ([API key and cost](api-key.md)). Set them for all files or for one file in
[Settings](settings.md).
