# Sketching

Draw on your model to show Claude where a change goes, and write what you want in the
prompt. A stroke says *where* better than words can, and your words say what it means. You
can send a sketch with a prompt, or on its own.

## Draw a sketch

1. Open the sidebar: hover over the 3D viewport, press **N** and click the **Whittle**
   tab. See [The sidebar](sidebar.md).
2. Pick the target, what Claude should work on. See [Prompts and targets](prompting.md).
3. Press **Sketch**, just above the prompt box, or press **Shift+Alt+D** over the
   viewport. Blender switches to Grease Pencil Draw Mode on an object called
   `Whittle Sketch`.
4. Draw over the model with the mouse or a pen.
5. Orbit and draw from other angles if one angle doesn't show everything.
6. Type what you want and press **Send**, or press **Shift+Alt+Enter** over the viewport.

```{figure} ../images/guides-sketching/sketch-strip.png
:alt: The sidebar in Sketch mode. Sketch is pressed with Capture View beside it. Below are a row reading 3 strokes, 2 views, a list of the two views, and the Markers While Sketching checkbox.

Sketch mode. The stroke count is open, listing the views: the angles you drew from.
```

Strokes stick to the surface under the pointer. Off a surface, they land on a plane
facing you at the depth of the 3D cursor, so their depth is only approximate. Drawing on
the same area from a second angle helps Claude place them.

The strokes are a guide, not exact geometry. Claude reads a wobbly line for its size,
position and shape, and builds a clean one.

**Auto** makes the target follow your selection, but it holds still while you sketch, so
selecting objects doesn't change the target. The objects Claude makes are still added to
the target, when your request finishes or you stop it with **Stop and Keep Changes**.

To stop, press **Sketch** again or press **Shift+Alt+D**. Blender goes back to Object
Mode, the object you had active is active again, and your Grease Pencil placement and
auto-keying settings come back. If you started from Edit Mode, you end in Object Mode.
Your strokes stay, and you can pick up where you left off.

## Say what the strokes mean

Every stroke is the same plain red line, like a redline on a drawing. The prompt is what
tells Claude what it means, so one kind of mark does every job: "cut a slot here", "build
the lid out to this line", "sharpen this edge" or "paint this panel". When strokes mean
different things, say which is which: "the loop is a slot, the line is an edge to sharpen".

Leave the `Whittle Sketch` object in the scene: it holds your strokes, and Claude leaves it
alone too.

## Work with views

Claude sees your sketch from each angle you drew it from. Each of those angles is a
*view*, and each stroke belongs to the view it was drawn from.

You rarely need to think about this. When you draw after moving the viewport far enough,
Whittle makes a new view by itself. Far enough means any one of these:

- you turned the view by more than 15°
- you panned or moved in by more than a tenth of the distance to the point you orbit around
- you changed the field of view by more than 15%: the lens, or the zoom of an orthographic view
- you switched between perspective and orthographic

Looking through a scene camera, the view matches that camera and its render size.

### Capture a view by hand

Press **Capture View**, or press **Shift+Alt+V** over the viewport. The key also works
when you aren't sketching. The new view becomes the current one, and new strokes go to it.

Capture a view by hand when:

- you moved the viewport only a little and still want a separate view
- you want Claude to see an angle without drawing on it: capture the view, then send a
  prompt with no strokes

Only views with strokes go to Claude, so a view you captured and never drew from isn't
sent if the sketch has strokes from other views. A request with no strokes at all sends
the current view.

### See and manage your views

The stroke count under the Sketch button reads something like `3 strokes · 2 views`. Click
it to open the list of views.

- **Go back to a view**: click its row. The viewport moves there, and the view becomes
  the current one, so what you draw next joins it.
- **See which view is current**: its row has a different camera icon and, when there's
  room, the word `current`. New strokes go to this view.
- **Remove a view**: click its **X**. A view that still has strokes can't be removed.
- **Clear everything**: click the trash icon beside the stroke count and confirm. This
  removes every stroke and every view.

To remove one stroke, press Ctrl+Z right after drawing it, or use Blender's Erase tool.
See [Undo](undo.md) for how undo behaves around sketching and turns.

### Use the view markers

While you sketch, a small camera marks each view in the viewport, pointing the way that
view looked.

```{figure} ../images/guides-sketching/view-markers.png
:alt: The viewport pulled back from the crate. A red outline and a small red loop are drawn on the crate, and two small wireframe cameras float around it, one blue and one light grey, each pointing at it.

Two view markers. The blue one is the current view.
```

- The current view's marker is blue, or your theme's colour for a selected list item.
  The others are light grey.
- Hover over a marker to highlight it, and click it to go back to that view. Clicking a
  marker doesn't draw a stroke.
- The marker of the view you are looking from is hidden.

To hide the markers, turn off **Markers While Sketching** at the bottom of the view list.
The viewport's Gizmos overlay hides them too.

## Send a sketch

Press **Send** in the sidebar, or press **Shift+Alt+Enter** over the viewport. You stay in
Sketch mode, ready for the next request.

Claude gets each stroke with its position, the camera of each view, and an
image of your strokes over the model from each view. What leaves your machine is listed
in [Privacy and safety](privacy.md).

You can send a sketch with no prompt. The conversation then shows `(sketch only)`.
Claude then has only the marks to go on, so a sentence usually helps.

### Add strokes while Claude works

A *turn* is one request and Claude's work on it. You can keep drawing during one. The
stroke count shows what was sent and what is new, as in
`3 sent · 1 new`, and **Amend** appears. Press it, or press **Shift+Alt+Enter**, to send
the new strokes into the running turn along with anything you typed. See
[Prompts and targets](prompting.md) for more on amending.

```{figure} ../images/guides-sketching/during-turn.png
:alt: The sidebar during a turn. The turn's prompt has a line reading 3 strokes, 2 views. Below, the Sketch row is still on, the stroke count reads 3 sent, 1 new, and the buttons at the bottom are Amend and Stop.

During a turn: one new stroke drawn since Send, and Amend ready to send it.
```

### What happens to your strokes afterwards

When a turn finishes, the strokes it was sent with are removed from the viewport, along
with views that no longer have strokes, except the current one. Strokes you drew during
the turn and didn't send stay, ready for the next request.

```{figure} ../images/guides-sketching/after-turn.png
:alt: The sidebar after the turn finished. The turn shows Claude's reply and a render of the crate with a lid. The Sketch row is still on, and the stroke count now reads 1 stroke, 1 view.

The same turn, finished. The three sent strokes are gone. The new one is waiting for the
next request.
```

A turn that you stop, or that fails after changing the scene, keeps its strokes in the
viewport. The count then reads like `1 stroke sent · 1 view`. They go out again with your
next request, unless you clear them. A turn that fails without changing anything leaves its
strokes waiting as new, so the count reads like `1 stroke · 1 view` and Send and Retry both
work on them: see [Failed turns and Retry](history.md#failed-turns-and-retry). **Edit &
Resend** brings a turn's strokes back with its prompt. See
[History and branches](history.md).

## Keys and tablet express keys

These keys work with the pointer over the viewport, in any mode, so you can start, draw
and send without reaching for the sidebar.

| Key | Name in the Keymap | Does |
|---|---|---|
| **Shift+Alt+D** | Toggle Sketch Mode | Starts or stops Sketch mode. |
| **Shift+Alt+V** | Capture View | Captures a view. |
| **Shift+Alt+Enter** | Send or Amend (shown as Shift Alt Return) | Send between turns, Amend while Claude works, Answer while Claude asks. Unlike Enter in the prompt box, it also sends strokes or references with no text typed. It does nothing when there is nothing to send. |

They all share Shift+Alt so that they suit a tablet's express keys. In your tablet's
settings, set one express key to send each key combination.

To change a key inside Blender:

1. Open **Edit → Preferences → Keymap**.
2. Type `Whittle` in the search box.
3. Find the row by its name in the table above.
4. Click the key on that row, then press the new one.

```{figure} ../images/guides-sketching/keymap.png
:alt: Blender's Keymap preferences searched for Whittle. Under 3D View are Send or Amend, Capture View and Toggle Sketch Mode, each with its key. Under Window are Ask Claude and two Send on Enter rows.

Whittle's keys in the Keymap preferences.
```

The search lists the sketch keys under **3D View**. Without a search, they are under
3D View → 3D View (Global). The two **Send on Enter** rows under Window are the prompt
box's own Enter key, not sketch keys, so leave them alone. See
[Keyboard shortcuts](shortcuts.md) for every key Whittle adds.
