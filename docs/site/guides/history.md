# History and branches

Every turn is kept as a step in a tree: what you sent, what Claude replied, and the target
as the turn left it. The target is the objects the turn worked on and the ones Claude made.
Only the target is recorded, and the rest of the file is left alone.
{doc}`Prompts and targets <prompting>` explains how it is chosen.

You can go back to any step, try a turn another way, and look at two steps side by side.
Going back deletes nothing, so an idea you dropped is still there later.

Each chat has its own tree, starting from a **Start** step: the target as it was before
the first turn. The tree is saved in the `.blend` with the chat. See {doc}`Chats <chats>`.

History actions wait for a running turn to end, and for a comparison to end. Until then
their buttons and menu items are dim.

## See the whole tree

Click the history button, the clock at the right end of the row with Send. The popover
lists every turn of the chat, with a thumbnail of each.

```{figure} ../images/guides-history/history-popover.png
:alt: The History popover listing a Start row and five turns. "Make the wood darker." says "2 branches" at its right. The rows after it are indented, with a small arrow on the first row of each branch. The current row, the last, "Add metal handles on both sides.", is highlighted.

The history popover. A step that branches says **2 branches** at its right; the current
step is highlighted.
```

- Click a row's title to go back to that turn.
- Click a row's ⋮ for the same menu the turn has in the conversation.
- If a title is cut short, hold the pointer over it to read it whole.
- A pause icon marks a stopped turn, and a cross a failed one.
- **Open Transcript**, at the bottom, shows the chat's whole transcript in Blender's
  Text Editor. It is dim while the chat has no turns.
- While nothing is kept yet, as after a first turn that failed without changing anything,
  **Start from** is at the top of the popover. See [Start row](sidebar.md#start-row).

## The turn menu

Each of your messages in the conversation has a three-dots button (⋮) at its right that
opens the turn's menu.
Older turns are folded to one line: open one to reach its ⋮, or use the popover.

```{figure} ../images/guides-history/turn-menu.png
:alt: The menu of a turn, listing Edit & Resend, Go Back to This Turn, Compare With Current, Open Render and Open Transcript.

The menu of an earlier turn.
```

| Item | What it does |
|---|---|
| **Edit & Resend** | Goes back to before this turn and puts its request back in the prompt box, ready to send as a new branch. |
| **Go Back to This Turn** | Puts the target back as this turn left it. On the Start step it reads **Go Back to the Start**. |
| **Compare With Current** | Shows this turn in the scene, and lets you swap between it and what you had. |
| **Ghost of Previous Turn** | Shows the turn before as a wireframe. Only on the current turn. |
| **Open Render** | Shows the turn's last render in an Image Editor. Only when the turn has a render. |
| **Open Transcript** | Shows the chat's whole transcript in a Text Editor. |

The Start step has only Go Back to the Start and Compare With Current.

## Go back to an earlier turn

1. Open the turn's ⋮ and choose **Go Back to This Turn**, or click its title in the history
   popover.
2. The target returns to how that turn left it, and the conversation ends at that turn.
3. To keep working from here, write a prompt and press **Send as Branch**. To return,
   press **Return to Latest**.

Objects Claude made after that turn are removed. Your own objects stay, and a copy you made
of one of Claude's objects counts as yours. Changes you made by hand to the target's
objects do not stay: those objects come back as the turn recorded them. Choosing **Go Back
to This Turn** on the current turn is a quick way to drop such changes.

While you are not at the end of a branch, a row under the conversation says how many turns
are ahead (**1 later turn**), and **Return to Latest** takes you to the newest one. Send
reads **Send as Branch**, or just **Branch** when there is no room.

Going back is one undo step, and Ctrl+Z moves the conversation back with the scene. See
{doc}`Undo <undo>`.

(edit-resend)=

## Try a turn again with Edit & Resend

Use this when a turn went the wrong way and you want to change what you asked.

1. Open the turn's ⋮ and choose **Edit & Resend**. A turn no longer in the conversation, such as
   one you undid, is still in the history popover: open its ⋮ there.
2. The target goes back to before that turn. The turn's prompt, sketch strokes and
   reference images come back, ready to change. The prompt replaces anything in the prompt
   box; strokes you drew since stay beside the old ones.
3. Change the prompt, the strokes or the references.
4. Press **Send as Branch** (it reads **Branch** when there is no room).

```{figure} ../images/guides-history/branch-edit.png
:alt: The sidebar after Edit & Resend. The conversation ends at "Add a lid." with a row saying 1 later turn and a Return to Latest button. The prompt box holds "Add rope handles on both sides." and the send button reads Branch.

After Edit & Resend on the second turn: the conversation ends at the first turn, and the
second turn's prompt is back in the box. **Return to Latest** takes you back to the old turn.
```

The new turn sits beside the old one in the tree, and the old one stays as it was. See
{doc}`Sketching <sketching>` and {doc}`Reference images <references>` for changing a
request's strokes and images.

## Switch between branches

Two turns that grew from the same step are branches. The first turn of each shows a
switcher in its message, left of the ⋮.

```{figure} ../images/guides-history/branched.png
:alt: The sidebar with two turns. The second, "Add rope handles on both sides.", shows 2/2 between a left and a dim right arrow, left of its menu button.

The second of two takes on a turn. The left arrow goes to the first take; the right arrow
is dim because there is no third.
```

Click an arrow to go to the other branch. The scene becomes what that branch's newest turn
left, and the conversation follows. You can also click any row in the history popover.

Claude's conversation follows the branch too. When you send from an earlier turn, Claude
continues from that point and does not see the turns on other branches. Whittle tells it
which turn the scene reflects.

## Compare with an earlier turn

To look at how a model has changed, without leaving where you are:

1. Open the ⋮ of the turn you want to see, in the conversation or the popover, and choose
   **Compare With Current**.
2. The scene shows that turn, and a bar under the row naming the target says what is showing.
3. Press **Swap** to switch between that turn and your scene, as often as you like.
4. Press **Done** to end the comparison with your scene as it was, hand edits included. Or,
   while the earlier turn is showing, press **Keep This** to stay on it, which is the same as
   going back to it.

```{figure} ../images/guides-history/comparing.png
:alt: The sidebar during a comparison. A box under the row naming the target says "Showing: Add a lid" with the buttons Swap, Keep This and Done. The "Add a lid." message has a two-way arrow beside its menu button, and Send is dim.

Comparing with the first turn. The compared turn has a two-way arrow beside its ⋮, and Send
is dim until the comparison ends.
```

- **Saving while comparing saves what is showing.** Press Done first unless you mean that.
- Send, the history actions and switching chats wait for the comparison to end.
- Your own objects stay in the scene on both sides, whichever turn is showing.
- Ctrl+Z ends a comparison too. See {doc}`Undo <undo>`.

### See the last change as a ghost

To see what the last turn changed, without swapping, open the current turn's ⋮ and choose
**Ghost of Previous Turn**. The target as it was one turn earlier appears as a wireframe
over the scene.

```{figure} ../images/guides-history/ghost.png
:alt: The 3D viewport showing the crate made taller, with a wireframe of the shorter crate inside it.

The crate after "Make the crate taller", with the turn before it as a ghost.
```

You cannot select the ghost, and it does not render. To remove it, choose **Hide Ghost**
from the same menu or from the top of the history popover. Going back, Edit & Resend and
switching branches remove it as well.

## Stopped turns

While a turn runs, **Stop ▾** takes the place of Send. Claude stops after what it is
doing now, and the sidebar says **Stopping…** until then.

- **Stop and Keep Changes** leaves the target as Claude left it, including anything it made
  so far. The turn ends with **Stopped, changes kept**.
- **Stop and Undo This Turn** puts the target back as it was when the turn started, and
  Claude is told. The turn ends with **Stopped, changes undone**.

```{figure} ../images/guides-history/interrupted.png
:alt: The sidebar after a stopped turn. Under the turn's render is a dim line with a pause icon, "Stopped, changes kept".

A turn stopped halfway, with the lid it had added kept.
```

Either way the turn stays in the tree, and your next Send carries on from it. The prompt
box is empty, and the turn's sketch strokes and reference images stay in place, so the next
Send includes them. If you sent strokes alone, Send stays dim until you type a prompt, as
those strokes are no longer new. To send the same request again, with or without changes,
use [Edit & Resend](edit-resend), which makes them new again; a stopped turn has no Retry.

## Failed turns and Retry

A failed turn ends with its reason in red. If it is the last turn in the conversation and
no later turns follow it, **Retry** sits beside the reason. When there are later turns, as
after a failed **Send as Branch**, there is no Retry: use **Edit & Resend** from the turn's ⋮.
Retry is a new request and is billed like any other turn
(see {doc}`API key and cost <api-key>`). A turn that ends with
`Images too big: send fewer or smaller` has **Edit** in Retry's place, which does what
**Edit & Resend** does, since the same images would fail the same way. Send fewer or smaller
references, or start a new chat if the conversation already holds many: see
[What Claude receives](references.md#what-claude-receives).

**A failed turn that changed something** stays in the tree, with the scene as it left it.

```{figure} ../images/guides-history/failed-turn.png
:alt: The sidebar with two turns. The second ends with "Claude stopped with an error" in red and a Retry button beside it.

The second turn scaled the crate up, then failed.
```

You have three ways on from here:

- **Retry** goes back to before the turn and sends the same prompt, strokes and references
  again as a new branch. The failed attempt stays in the tree.
- **Edit & Resend**, from the turn's ⋮, does the same but lets you change the request first.
- A new prompt and **Send** carries on from what the failed turn left.

**A failed turn that changed nothing** is not kept in the tree. It shows in the conversation
until your next Send, and only while you are on the turn you sent it from. Switching chats,
opening a file or closing Blender drops it.

```{figure} ../images/guides-history/folded-failure.png
:alt: The sidebar with one turn that ends with "Claude stopped with an error" in red and a Retry button. The prompt box is empty.

A turn that failed before touching the scene.
```

Its strokes and references are still in place, so **Retry** just sends again. If you have
typed something in the prompt box, Retry sends that in place of the old prompt.
**Send** does the same while the turn shows: with strokes or references waiting and the box
empty, it sends them with the turn's prompt, and what you type replaces that prompt.
**Edit & Resend** only puts the old prompt back in the box for you to change, because the
scene never moved.

### When Claude stops unexpectedly

If Claude crashes during a turn, a box at the top of the sidebar says **Claude stopped
unexpectedly** in red, and the turn ends with a dim **Interrupted**. Press **Restart and Retry**
to start Claude again and send the turn again, as Retry does. With no turn to retry, the button
is **Restart**.

```{figure} ../images/guides-history/crashed.png
:alt: The sidebar with a red "Claude stopped unexpectedly" message and a Restart and Retry button above the conversation. The turn "Add a lid." ends with a dim Interrupted.

The crash is reported once, in the box above the conversation.
```

If this keeps happening, see {doc}`Troubleshooting <troubleshooting>`.

### If Blender crashes during a turn

The turn shows as failed in the history popover when you open the file again. It never
finished, so nothing was recorded to go back to and its title is dim. Its ⋮ still has
**Edit & Resend**, which brings back what you sent. For turns that finished before the crash,
see [Blender crashed](troubleshooting.md#blender-crashed).

Quitting normally, or opening another file, is different: the running turn ends there and
then as a failed turn like any other. It is kept with what it had done, or dropped if it
had changed nothing.
