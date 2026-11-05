# Undo

Ctrl+Z and Ctrl+Shift+Z work as they do anywhere in Blender, and they reach Claude's edits
too. A turn is one prompt and everything Claude does in answer to it. The conversation
follows the scene: undo a turn and the conversation goes back with it. Undo leaves your chats
alone; the end of this page lists [what else it does not reach](undo-limits).

Undo is the quick way back. To return to any turn, however old, use
{doc}`History and branches <history>`.

## Take back a finished turn

1. Press **Ctrl+Z**.

The scene goes back to how it was before the turn, and the conversation ends at the turn
before it. The turn you undid is not gone: the conversation says **1 later turn** and offers
**Return to Latest**.

```{figure} ../images/guides-undo/after-undo.png
:alt: The Whittle sidebar after Ctrl+Z. The conversation ends at the turn "Add a lid to the crate." Below it, a dim line says 1 later turn, beside a Return to Latest button. The Send button now reads Branch.

Ctrl+Z after a second turn. The first turn is the current one, and the second waits under
**1 later turn**.
```

From here you have three choices:

- **Bring the turn back.** Press **Ctrl+Shift+Z**, or **Return to Latest**.
- **Try something else.** Write a new prompt. Send has become **Send as Branch** (**Branch**
  in a narrow sidebar), because a new turn from here starts a branch beside the one you undid.
- **Send the same request again, changed.** The prompt does not come back with Ctrl+Z, and
  the undone turn is no longer in the conversation. Click the history button, the clock at
  the right end of the row with Send, open the undone turn's ⋮ and choose **Edit & Resend**.
  See {doc}`History and branches <history>`.

If the turn came from a sketch, Ctrl+Z brings its strokes back too. A finished turn clears
its strokes as it ends, so they are part of what you undid.

### Going back more than one turn

The first press takes back the latest turn. Each older turn then takes two presses. The first
seems to do nothing, because it moves between two steps that hold the same scene: the start
of the turn you just undid, and the end of the turn before it. The second takes that turn
away. So taking back the last two turns takes three presses. The next section shows why.

## See where you are

Open **Edit > Undo History** to see every step Blender is keeping. Click one to go straight
to it. The dimmed entry with a dot is where you are now.

```{figure} ../images/guides-undo/undo-history.png
:alt: Blender's Undo History menu, newest first: Whittle: n0002 Add rope handles on both sides., Before Whittle turn, Whittle: n0001 Add a lid to the crate., Before Whittle turn, Original.

Undo History after two turns. Each turn has a step where it started and a step where it
finished.
```

These are the steps Whittle adds. `<node>` is the turn's id, such as `n0002`, and `<label>`
is the first line of its prompt, shortened if it is long.

| Step | When |
|---|---|
| `Before Whittle turn` | A turn starts, before Claude's first edit. |
| `Whittle: <node> <label>` | A turn finishes. |
| `Whittle: <node> so far` | You press Ctrl+Z during a turn and Claude has edited since the turn started or since your last undo or redo. |
| `Whittle: restore <node>` | You use **Go Back to This Turn**, or **Keep This** in a comparison. |
| `Whittle: switch to <node>` | You change branch. |
| `Whittle: edit & resend <node>` | You use **Edit & Resend**. |
| `Whittle: end comparison` | You end a comparison and return to the live scene. |

A turn that fails without changing anything adds only `Before Whittle turn`. Sketching and
reference images add steps too, under their own names, such as **Stop Sketching** or
**Add Reference**.

Ctrl+Z after **Go Back to This Turn** or a branch switch moves the conversation back along
with the scene.

## Undo during a turn

You don't have to wait for a turn to finish.

1. Press **Ctrl+Z** while Claude is working.

The scene goes back to how it was when the turn started, and a warning appears in the
conversation.

```{figure} ../images/guides-undo/during-turn.png
:alt: The Whittle sidebar during a turn. A tool call is still running, and under it a warning reads: Undo during a turn takes back what Claude did so far; Claude is told. The Stop button is still showing.

Ctrl+Z during a turn. The turn carries on: **Stop** is still there, and the call in flight
is still running.
```

**Ctrl+Z does not stop the turn.** Claude keeps going from the scene you put back. It finds
out with the result of its next step, and is told to look again at its target, the objects
it is working on (see {doc}`Prompts and targets <prompting>`), before going on. If it has no
more steps to make, it never finds out, so its last message can describe work that is no
longer in the scene.

- **Changed your mind?** Press **Ctrl+Shift+Z** and Claude's edits come back. The conversation
  shows the same warning again and Claude is told again, though this time nothing was taken away.
- **Pressing Ctrl+Z again** with no new edit from Claude goes on past the turn's start, to
  your own last step.
- **If you changed something yourself during the turn** and Claude has edited too, Ctrl+Z
  lands on your change, not on the turn's start, and your change stays. If Claude made no edit
  after it, the press seems to do nothing, though the warning still shows. Press it again to
  take that change back and carry on.

To end the turn as well, use **Stop ▾ > Stop and Undo This Turn**, described in
{doc}`Prompts and targets <prompting>`. It puts the target back and stops Claude, and the
turn stays in the history marked `Stopped, changes undone`.

## While sketching

Ctrl+Z takes back the last stroke and leaves you in Sketch mode, as Blender's Draw Mode does.
If an undo goes far enough to leave Draw Mode, or to remove the sketch, Sketch mode ends.
See {doc}`Sketching <sketching>`.

## While comparing

Ctrl+Z during a comparison ends it, and the scene is the one the undo put back. See
{doc}`History and branches <history>`.

## Chats are not undone

Ctrl+Z never changes the current chat. **New Chat**, switching chats, renaming and deleting
add no undo step, so none of them can be taken back with Ctrl+Z, and a deleted chat stays
deleted. See {doc}`Chats <chats>`.

Undo steps from another chat are still in the list after you switch. Pressing Ctrl+Z back
into one rolls the scene back, but the conversation stays where it is, so the two no longer
match. Press **Ctrl+Shift+Z** to come forward again.

(undo-limits)=

## What undo does not reach

- **Anything outside the scene.** A file that Claude's Python wrote stays written. See
  {doc}`Privacy and safety <privacy>`.
- **Old steps.** Blender keeps a limited number of them, set by **Undo Steps** in
  **Preferences > System > Memory & Limits**, and the list starts again when you open a
  file. Whittle's history keeps every turn in the `.blend`, so go back through
  {doc}`History and branches <history>` instead.
