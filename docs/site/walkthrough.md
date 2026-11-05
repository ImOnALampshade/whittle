# Walkthrough

This page follows one small job from start to finish: a plain crate becomes a chest with a
lid, a latch and rope handles. On the way you ask for a change in words, sketch the next one
from two views, answer a question from Claude, try an alternative on a branch, compare the
two, undo a turn that went too far, and save.

Whittle is a Blender add-on that lets Claude, an AI agent, edit the open scene from a chat in
the sidebar. Each request, with Claude's work on it and its reply, is a *turn*.

```{note}
The screenshots come from a scripted demo agent, so Claude's replies here are illustrative.
The edits to the model are real, but with a real agent the wording, the tools it uses and
the result will differ, and it may or may not ask you anything.
```

You need Whittle set up with your API key: see {doc}`quickstart`. Every turn you send costs
tokens on that key; {doc}`guides/api-key` says what a turn's cost depends on and where to
read it.

## Start from a simple model

Open Blender and make or open something simple. This walkthrough uses a 50 cm cube named
Crate, with a brown material. Press **N** over the 3D viewport to open the sidebar and click
the **Whittle** tab.

Click the crate to select it. The target line at the top of the panel names what Claude will
work on, and with **Auto** on it follows your selection.

```{figure} images/walkthrough/plain-crate.png
:alt: Blender with a plain brown cube selected in the 3D viewport. The Whittle sidebar shows the target line reading Crate, with Auto on, the Start from buttons, the Sketch button, an empty prompt box and a disabled Send button.

A plain crate, selected, and the Whittle tab open. Nothing has been sent yet.
```

## Ask for a change

Click in the prompt box, type what you want and press **Enter** or **Send**.

```{figure} images/walkthrough/first-prompt.png
:alt: The Whittle sidebar with the prompt "Bevel the edges and add a lid that overhangs a little." typed in the prompt box and Send enabled.

The first request, in words alone.
```

Claude starts at once and works in the open scene. The target line shows a lock, because the
target cannot change during a turn, and each call to Blender shows as it runs. You do not
have to wait: you can type or draw to add to the request, or use **Stop** to end the turn.

```{figure} images/walkthrough/first-running.png
:alt: The sidebar during the turn. The target line has a lock, Claude's plan is written below the prompt, a row with an hourglass reads exec, bevel and lid, and the Send button has become Stop.

The turn running, with one call in flight.
```

When the turn ends you get Claude's reply and a render of the result. The row **Used 2
tools** opens to show what Claude ran. The new lid is now part of the target, so the next
request can reach it.

```{figure} images/walkthrough/first-done.png
:alt: The sidebar after the turn. The target line reads Crate, Crate_Lid, then come the prompt, the reply, a closed row reading Used 2 tools, a closing line and a render of the crate with a lid.

The finished turn.
```

```{figure} images/walkthrough/first-done-view.png
:alt: The crate in the viewport with softly bevelled edges and a flat lid that overhangs on all sides.

The same result in the viewport: soft edges and a lid.
```

{doc}`guides/prompting` has more on writing requests and choosing targets.

## Sketch the next change

Some requests are easier to draw than to describe. This one has four parts: a latch on the
front, a finger slot in the lid, a sharper front edge on the lid, and a painted panel on the
side.

Press **Sketch** (or **Shift+Alt+D** over the viewport). Blender goes into Draw Mode, and a
row of stroke types appears in the sidebar. Each type has its own colour and tells Claude
what you mean. The icons have no labels: from left to right they are Free, Add, Carve,
Crease, Region and Note. Hover over one to see its name and meaning, and the active type's
name shows beside the row.

```{figure} images/walkthrough/sketch-start.png
:alt: The top of the sidebar in Sketch mode. Sketch is pressed, beside Capture View. Below them is a row of six icons with the first active, and the name Free beside the row.

Sketch mode, with Free picked and nothing drawn yet.
```

Pick a type, then draw on the model; strokes stick to the surface under them.

Orbit to the front of the crate and draw five strokes, one each of Add, Carve and Crease and
two of Note:

| Stroke | Colour | What it says | Drawn here |
|---|---|---|---|
| Add | Green | Build material here | The outline of the latch |
| Carve | Red | Remove material here | The finger slot in the lid |
| Crease | Yellow | A sharp edge or a bevel along this line | Along the lid's front edge |
| Note | Grey | A note for Claude: an arrow, a circle, a label | An arrow pointing at the latch, in two strokes: the shaft, then the head |

```{figure} images/walkthrough/sketch-front.png
:alt: The crate from the front, drawn over with a green outline below the lid, a red slot on the lid, a yellow line along the lid's front edge and a grey arrow pointing at the green outline.

Five strokes from the first view: the arrow is two of them.
```

The side panel can't be seen from here, so orbit round to the side. Press **Capture View**
(or **Shift+Alt+V**) to record the new angle. If you forget, drawing from a clearly
different angle records one for you. Pick **Region**, the type for "the area this request
is about", and outline the panel.

```{figure} images/walkthrough/sketch-side.png
:alt: The crate from its left side with a translucent blue area drawn low on the side. The earlier strokes can be seen edge-on at the top right.

A region from the second view. The first view's strokes stay where they were drawn.
```

Now write the request: `Add a latch here, carve a finger slot in the lid, sharpen its front
edge and paint the side panel.` The strokes say where, so the prompt only has to say what. The
row under the stroke types counts what you have drawn; open it to see each view. Click a
view's name to go back to it.

```{figure} images/walkthrough/sketch-ready.png
:alt: The sketch part of the sidebar. Sketch is pressed, beside Capture View, then come the six stroke types with Region active. The stroke count reads 6 strokes, 2 views, above rows for View 1 with 5 strokes and View 2 with 1 stroke, and a prompt ready to send.

Six strokes over two views, and the prompt that goes with them.
```

Press **Send**. {doc}`guides/sketching` covers all the stroke types and views.

## Answer a question

Claude can stop in the middle of a turn to ask you something. This time it wants to know what
the latch should be made of. The turn waits until you answer.

```{figure} images/walkthrough/question.png
:alt: The sidebar with the sketched request, marked 6 strokes, 2 views. Below it are a render and a box with the question "Should the latch be brass or dark iron?" and the buttons Brass and Dark iron.

The turn paused on a question.
```

Click **Brass**. If neither choice suits you, type an answer in the prompt box and press
**Answer**. Claude carries on from where it stopped.

```{figure} images/walkthrough/sketch-done.png
:alt: The finished turn in the sidebar. A small box reads Answer: Brass, then come the reply, a closed row reading Used 4 tools, and a render of the crate with a latch and a blue panel.

Your answer stays in the turn, between Claude's replies.
```

```{figure} images/walkthrough/sketch-done-view.png
:alt: The crate with a brass latch on the front running up onto the lid, a slot cut in the lid, a chamfered front edge on the lid and a blue painted panel low on the side.

The latch, the finger slot, the chamfered edge and the painted panel.
```

The strokes you sent are gone now that the turn is over, but you are still in Draw Mode. Press
**Sketch** again to leave it. The last view stays in the sketch and would go with your next
request, so press the trash icon on the row that now reads **1 view** and confirm, to start
the next sketch clean.

## Try an alternative on a branch

Ask for handles: type `Add rope handles on both sides.` and send it.

```{figure} images/walkthrough/rope-view.png
:alt: The crate with a rope ring on its side, above the blue panel.

Rope handles.
```

Suppose you want to see metal handles as well, without losing these. Every turn has a **⋮**
button at the end of its prompt. Click it on the rope handles turn, then click **Edit &
Resend**.

```{figure} images/walkthrough/turn-menu.png
:alt: A menu headed with the turn's prompt, listing Edit & Resend, Go Back to This Turn, Compare With Current (disabled), Ghost of Previous Turn, Open Render and Open Transcript.

The menu of a turn. Compare With Current is greyed out because this turn is the current one.
```

The scene goes back to how it was before that turn, and its prompt returns to the box. The
rope handles aren't gone: a line says there is one later turn, and the button now reads
**Send as Branch** (**Branch** if the sidebar is narrow). Change the prompt to `Add metal
handles on both sides.` and send it.

```{figure} images/walkthrough/edit-resend.png
:alt: The end of the sidebar. A line reads 1 later turn beside a Return to Latest button, and below it the prompt box holds "Add metal handles on both sides." above the button Send as Branch.

Back before the rope handles, with a new prompt ready to send as a branch.
```

Claude does the new version from the same starting point. The turn's prompt now carries a
switcher, **2/2**: this is the second of two versions of the turn. The arrows move between
them, and the scene changes with them.

```{figure} images/walkthrough/branched.png
:alt: The turn "Add metal handles on both sides." with a switcher reading 2/2 beside its menu button, then the reply and a render of the crate with a metal handle.

The second version of the turn, with the branch switcher.
```

```{figure} images/walkthrough/metal-view.png
:alt: The crate with a grey metal bar handle on its side, above the blue panel.

Metal handles.
```

## Compare with an earlier turn

The clock button at the end of the Send row, beside the model menu (**Opus 5.5** here), opens
the history, where every turn of the chat is listed.
The two handle turns are listed together, indented under the turn they branched from.
Clicking a title goes back to that turn.

```{figure} images/walkthrough/history-branches.png
:alt: The history popover listing Start: Crate, the bevel turn, the sketched turn marked 2 branches, and under it the rope handles and metal handles turns, with the metal one highlighted.

The history with two branches. The highlighted row is the current turn.
```

To flip between the two, click the **⋮** on the rope handles row and pick **Compare With
Current**.

```{figure} images/walkthrough/compare-menu.png
:alt: The same turn menu, with Compare With Current now enabled and the ghost item gone.

From another turn, Compare With Current is available.
```

The scene switches to the rope handles and a bar appears at the top of the panel, saying what
you are looking at. **Swap** flips between the two.

```{figure} images/walkthrough/comparing-rope.png
:alt: The crate with a rope ring in the viewport. At the top of the sidebar a box reads Showing: Add rope handles on both sides, with the buttons Swap, Keep This and Done.

Showing the compared turn.
```

```{figure} images/walkthrough/comparing-metal.png
:alt: The crate with a metal handle in the viewport. The box in the sidebar reads Showing: the current scene, with the buttons Swap and Done.

After Swap: showing the current scene.
```

The rope suits a chest better. Press **Swap** to show it again, then **Keep This**. **Done**
would have put the current scene back instead. You can't send anything until the comparison
ends, and if you save during a comparison, the file saves what is showing.

```{figure} images/walkthrough/kept-rope.png
:alt: The rope handles turn in the sidebar, its switcher reading 1/2 with the right arrow lit, then the reply and a render of the crate with a rope ring.

Back on the rope handles. The metal version is still there, one arrow away.
```

{doc}`guides/history` covers branches, going back and comparing.

## Undo a turn

Send `Make the wood much darker.` Claude does as it's told, and it's too much.

```{figure} images/walkthrough/too-dark.png
:alt: The crate with the wood nearly black, the lid, latch and rope still their earlier colours.

Too dark.
```

Press **Ctrl+Z** with the pointer over the viewport, as you would to undo anything else in
Blender. The whole turn comes off in one step, and the conversation goes back with the scene.
**Ctrl+Shift+Z** would bring it back.

```{figure} images/walkthrough/undone-view.png
:alt: The crate back in its earlier brown.

The wood as it was.
```

The turn stays in the history. The panel shows **1 later turn** with a **Return to Latest**
button, and anything you send now goes out as a branch.

```{figure} images/walkthrough/undone.png
:alt: The rope handles turn in the sidebar, followed by a line reading 1 later turn beside a Return to Latest button, and a disabled Send as Branch button under the empty prompt box.

After Ctrl+Z: the undone turn is one click away.
```

{doc}`guides/undo` covers undo during a turn and how it fits with the history.

## Finish

Send a gentler request, `Make the wood a little darker.`, and the crate is done.

```{figure} images/walkthrough/final-window.png
:alt: The finished chest in the viewport, in darker wood with a pale lid, brass latch, rope handle and blue panel. The sidebar shows the earlier turns folded away, the rope handles turn, and the last turn with its 2/2 switcher and render.

The finished chest. Older turns fold away in the sidebar; click one to open it.
```

The history shows everything you tried, including the metal handles and the wood that went
too dark. Any row is still a click away.

```{figure} images/walkthrough/final-history.png
:alt: The history popover with Start: Crate, the bevel turn, the sketched turn, then the rope handles turn with two branches under it, the much darker and the little darker turns, and the metal handles turn. The little darker turn is highlighted.

The whole job as a tree.
```

Save the file as usual with **File → Save**. By default the chat is stored in the `.blend`,
with its history, so it travels with the file. {doc}`guides/chats` explains that, and how to
start another chat in the same file.

## Where to go next

- {doc}`guides/sidebar` goes through every part of the panel.
- {doc}`guides/references` adds reference images to a request.
- {doc}`guides/models` picks the model and the effort for a chat.
- {doc}`guides/shortcuts` lists the keys, which suit a tablet's express keys.
