# The sidebar

Everything you do with Whittle happens in one tab of the 3D viewport's sidebar. This
page goes through that tab from top to bottom and says what each part is for, then what
changes while Claude works and when something needs you.

Two words come up throughout. A **turn** is one request of yours and Claude's reply to it.
The **agent** is the background process that runs Claude for Whittle.

To open it, hover over the 3D viewport, press **N** and click the **Whittle** tab.
**Shift+Alt+C** also opens it, from any editor, with a prompt field under the pointer
([Keyboard shortcuts](shortcuts.md)).

```{figure} ../images/guides-sidebar/in-the-window.png
:alt: Blender's window with the crate in the 3D viewport and the Whittle tab open in the viewport's sidebar, showing one finished turn.

The Whittle tab sits at the right edge of the 3D viewport. Drag the sidebar's left edge
to widen it: Claude's text wraps to the room it has.
```

## What is where

The sidebar reads like a chat. A part shows only when it has something to say, so most
of the time you see what is in the picture below.

```{figure} ../images/guides-sidebar/overview.png
:alt: The sidebar after three turns. From the top: the chat title and a gear, the target line with Auto, one folded turn, two open turns with their replies and renders, the Sketch button, the prompt box, and Send with the model and history buttons.

From the top: the **header** (chat title, gear), the **target line** (Crate, Crate_Lid,
and Auto), the **conversation** (an older turn folded to one line, then the last two
turns in full), the **Sketch** button, the **prompt box** and the row with **Send**, the
model button and the history button.
```

| To do this | Use |
|---|---|
| Start a new chat, or go back to an earlier one | the [chat title](#header) |
| See what the agent is doing, or change this file's settings | the [gear](#header) |
| Choose what Claude works on | the [target line](#target-line) |
| Say what you want | the [prompt box](#prompt-box-and-send) |
| Draw what you want | the [Sketch button](#sketch) |
| Attach a picture | the image button [beside the prompt box](#prompt-box-and-send) |
| Go back, branch or compare | the [three-dot button (⋮)](#the-menu-of-a-message) on a message, or the history button |
| Change the turn while it runs, or stop it | [Amend and Stop](#while-claude-works) |

## Header

The panel's header has the chat on the left and the agent on the right.

- **The chat title** opens the chat menu, where you start a new chat and go back to
  earlier ones. It reads `New chat` until you send the first turn, then takes its title
  from your first prompt. See [Chats](chats.md).
- **The gear** opens the agent popover. It turns into an hourglass while the agent is
  starting or stopping between turns. A running turn shows its progress in the
  conversation instead, so the gear stays a gear.

```{figure} ../images/guides-sidebar/agent-popover.png
:alt: The agent popover: the agent's state, the model and effort, the For This File settings with a reset button on each line and the style guide's files under Style Notes, then Start Agent and Preferences.

The agent popover. At the top are the agent's state, and the current chat's model and
effort. **For This File** holds the settings stored in this `.blend`. At the bottom are
**Start Agent** (**Stop Agent** while it runs) and **Preferences…**.
```

You rarely need Start Agent or Stop Agent, because **Send** starts the agent by itself. **Stop
Agent** ends that background process and nothing else: your chats and the scene stay, and the
next Send starts the agent again and carries on the conversation. Pressed during a turn, it
ends the turn as failed, so to end a turn use [**Stop**](prompting.md#stop-a-turn) instead.

Once the agent has started, the popover also has a line saying which file stores the
chats. `Chats: unsaved file` means they are not stored in a `.blend` until you save. After
a crash, the reason is here too. [Settings](settings.md) explains For This File.

## Attention box

When Claude cannot work until you do something, a box appears at the top of the panel.
There is never more than one, and it goes away when the problem does. Red means a real
failure. A first run is not one, so those boxes stay grey.

| The box says | What it means | What to do |
|---|---|---|
| `Set up Claude to start` | Send or **Start Agent** found no agent environment: it is not installed yet, or needs installing again. Nothing checks sooner, so a new install shows no box until you first press Send. Your prompt stays in the box, and Send is disabled until the setup finishes. | **Set Up…**, then confirm. See [Installing and updating](installation.md). |
| `Setting up Claude: …` | The setup is running. | Wait, or **Cancel**. |
| `Add an API key to start` | Whittle found no key. Your prompt stays in the box. | **Get a Key** opens the Anthropic Console's keys page; paste the key under **Preferences…**, then press Send again. See [API key and cost](api-key.md). |
| `The API key was refused` (red) | Anthropic did not accept the key. The turn ends as failed too. | The same two buttons. |
| `Claude stopped unexpectedly` (red) | The agent crashed. | **Restart and Retry** restarts it and sends the interrupted turn again. **Restart** appears when there is no turn to retry. |
| `Claude could not start` (red) | The agent failed to start. | The same buttons. The gear's popover has the reason. |

```{figure} ../images/guides-sidebar/setup-needed.png
:alt: The attention box saying Set up Claude to start, with a Set Up button, above the target line. Send is greyed out.

After Send found no agent environment. The box is not red, the prompt waits in its box,
and Send is disabled until the setup finishes.
```

```{figure} ../images/guides-sidebar/key-needed.png
:alt: The attention box saying Add an API key to start, with Get a Key and Preferences buttons. The prompt Add a lid is still in the prompt box.

No API key. The prompt waits in its box, and Send stays enabled so you can try again once
the key is in.
```

```{figure} ../images/guides-sidebar/crashed.png
:alt: A box with the red line Claude stopped unexpectedly and a Restart and Retry button. Below it the turn ends with a dim Interrupted.

After a crash. Only the line is red. The turn the crash ended says `Interrupted`, and the
box above says why.
```

More causes and fixes are in [Troubleshooting](troubleshooting.md).

## Target line

The line under the header says what the next request works on.

- **Auto** on (the default): the target follows your selection in Object Mode: the
  selected objects, or the active object when nothing is selected. The line names them,
  such as `Crate, Crate_Lid` or `Crate + 2 more`. With neither, it says `Nothing selected:
  Claude adds new objects`.
- **Auto** off: you pick the targets. The line counts them, and they are listed below it.
- A padlock in place of the object icon means a turn is running. The target cannot change
  until it ends, so Auto is dimmed.

```{figure} ../images/guides-sidebar/manual-targets.png
:alt: Auto off. The line says 2 targets, with Crate and Crate_Lid listed below it, each with an X, then a button Add Barrel and a ⋮ button.

With Auto off, ✕ removes a target. The button under the list adds what is selected and
names it, here `Add Barrel`. The ⋮ beside it has the target collection, **Replace With
Selection** and **Clear**.
```

[Prompts and targets](prompting.md) covers how to choose targets.

## Comparison bar

While you compare two states of the scene, a box under the target line says which one is
showing. **Swap** switches between them, **Keep This** keeps the compared turn (it shows
only while that turn is on screen), and **Done** ends the comparison. Send is disabled until
you end it.

```{figure} ../images/guides-sidebar/comparing.png
:alt: A box saying Showing: Add a lid, with the buttons Swap, Keep This and Done. The first message below it carries a compare mark beside its ⋮ button.

Comparing the scene with an earlier turn. The compared turn's message has a mark beside
its ⋮.
```

You start a comparison from a message's ⋮ menu. See [History and branches](history.md).

## Start row

Before you send anything, **Start from** offers four ways to begin. All are optional:
typing a prompt and pressing Send starts from the scene as it is.

- **Selection**: start from the selected objects, as they are.
- **Blank**: start from this scene with nothing selected or targeted, so Claude makes new
  objects. Nothing is added to the scene.
- **Primitive**: add a primitive at the 3D cursor and start from it. Its size is in
  Blender's Adjust Last Operation panel.
- **Asset**: this one has no button. In the Asset Browser, right-click an object or
  collection asset and choose **Start Whittle From Asset**. It becomes the target, and a
  collection asset the [target collection](prompting.md#pick-targets-by-hand). An asset in
  this file is used in place. One from another file is appended, with nothing left linking
  to that file, and an object is placed at the 3D cursor. Other assets, such as materials,
  do not have the menu item, and it is dim once the history has turns.

```{figure} ../images/guides-sidebar/empty.png
:alt: The sidebar before anything is sent. The target line says Nothing selected: Claude adds new objects. Below it are Start from and the buttons Selection, Blank and Primitive.

Nothing selected and nothing sent yet.
```

```{figure} ../images/guides-sidebar/primitive-menu.png
:alt: The Primitive menu listing the primitives, then a hint to right-click an asset in the Asset Browser.

The Primitive menu. Its last line is a reminder that you can also start from an asset.
```

The row goes away once you have sent something, and also while you sketch or when you have
typed a prompt with a target picked. While a first turn that failed without changing
anything is showing, **Start from** is in the
[history popover](history.md#see-the-whole-tree) instead. A Blank, Primitive or Asset start
shows as a dim line, such as `Start: Blank`, until the first turn.

## Conversation

The conversation shows the current branch: each turn is your message, then Claude's reply.

### Your message

A box holds your prompt, up to four lines of it. A turn with no prompt reads `(sketch
only)`. If you sent strokes, [views](#sketch) or references, a dim line counts them, such
as `3 strokes · 2 views · 1 ref`.

### The menu of a message

The ⋮ on a message is the one menu for that turn. It is disabled while the turn runs.

```{figure} ../images/guides-sidebar/turn-menu.png
:alt: A turn's menu, with Edit & Resend first, then Go Back to This Turn, Compare With Current, Open Render and Open Transcript.

**Edit & Resend** takes another go at the turn, and **Go Back to This Turn** returns to it.
**Compare With Current** shows it in place of the current scene. **Open Render** shows the
turn's last render, and **Open Transcript** shows the chat's whole transcript in a Text
Editor. The current turn also has **Ghost of Previous Turn**, which shows the turn before as
a wireframe.
```

[History and branches](history.md) explains each of them.

### Claude's reply

Claude's text is always shown whole, with its Markdown drawn: headings, lists, tables and
code blocks, which have a button that copies them. A link has a button at the end of its
line that opens it.

Between the text, tool calls fold into one line, such as `Used 2 tools`. Click it to see
each call. Click a call to see its code and result. Long lines are cut at the sidebar's
width, and a long call at 40 lines: widen the sidebar, or use
[**Open Transcript**](history.md#the-turn-menu) in the message's menu for the full code. A turn in full ends with its last render.

```{figure} ../images/guides-sidebar/tools-open.png
:alt: A finished turn with both tool groups opened. The first shows the call exec, add lid, opened on its code and result. The second shows a closed render call, the render with a button beside it, and a dim line reading 5 steps and a cost.

Both tool groups open, and the first call opened on its code and result. A check mark is a
call that worked, and a cross one that failed. The button beside a render opens it in an
Image Editor. The last group ends with the turn's steps and its cost.
```

A failed call inside a group is not red: Claude usually fixes it and carries on.

### Long conversations

Blender panels cannot scroll by themselves, so the conversation keeps its height. The last
two turns show in full, the three before them fold to a line each, and anything older goes
under `N earlier turns`. Click a folded line to open it.

```{figure} ../images/guides-sidebar/long-session.png
:alt: A conversation of thirteen turns. At the top a closed line 8 earlier turns, then three folded turns, then the last two turns in full.

Thirteen turns: eight under `8 earlier turns`, three folded, two in full.
```

### Branches

A message with another version has a switcher beside its ⋮. The arrows go to the other
version, and the number says which one you are on.

```{figure} ../images/guides-sidebar/branched.png
:alt: A message about rope handles with a switcher reading 2/2 beside its ⋮ button.

The second of two versions of this message. The right arrow is dim because there is no third.
```

After you go back, the conversation ends where you are, with a line such as `1 later turn`
and **Return to Latest**. Sending from here makes a new branch, so Send reads **Send as
Branch**, or **Branch** when the sidebar is too narrow for that.

```{figure} ../images/guides-sidebar/later-turns.png
:alt: The conversation ending at a turn, followed by 1 later turn and a Return to Latest button. The old prompt is back in the prompt box and the send button reads Branch.

After **Edit & Resend**: the prompt is back in its box, and the button reads **Branch**.
```

## Sketch

The **Sketch** button sits between the conversation and the prompt box. Press it to draw
over the model. It stays pressed while you sketch, and **Capture View** appears beside it. There
is nothing to pick first: draw, then say in the prompt what your strokes mean.

A **view** is a saved viewpoint. Each stroke belongs to the view it was drawn from, so Claude
sees your sketch from where you drew it. Whittle makes views as you move around, and
**Capture View** saves one by hand.

```{figure} ../images/guides-sidebar/sketching.png
:alt: Sketch mode. The Sketch button is pressed with Capture View beside it, then comes the stroke count with two views listed and a Markers While Sketching checkbox.

While sketching. Under the Sketch button is the count, here of strokes and views. Open it for
the list of views. Click a view to go back to it, and ✕ to remove one that has no strokes.
The trash icon on the count's line clears the sketch.
```

The count stays once you stop sketching, as long as the viewport has strokes or views to
show. While a turn runs it counts what was sent and what you have drawn since, such as
`3 sent · 1 new`. [Sketching](sketching.md) covers all of this.

## Prompt box and Send

The bottom of the panel is where you write the request.

- **The prompt box**, marked `Ask Claude…`, shows three lines and scrolls past that. Drag
  its corner to resize it. **Enter** sends and **Shift+Enter** adds a line. Clicking
  elsewhere keeps the text without sending it.
- **The image button** beside it adds a reference image. Each one shows as a chip above the
  box.
- **Send** sends the prompt, the sketch and the references. Your text moves into the
  conversation, and comes back to the box if the run never starts.
- **The model button** beside Send names the chat's model and opens the menu for its model
  and effort. See [Models and effort](models.md).
- **The history button** at the end opens the whole tree of turns. See [History and
  branches](history.md).

```{figure} ../images/guides-sidebar/references.png
:alt: Two reference chips, crate_front.png with a pressed pin and crate_side.png, above a prompt about matching the proportions in the reference photos.

Two references, the first pinned, so it goes with every request and not only the next.
Click a chip for its menu: pin it, place it in the scene, open it or remove it. The pressed
pin unpins it. See [Reference images](references.md).
```

### Why Send is greyed out

Send needs something to send: a prompt, a stroke not yet sent, or a reference. If you have
one and it is still grey, the reason is one of these:

- Send found no agent environment: use the attention box.
- A comparison is open: press **Done** in the comparison bar.
- The chat came from another machine: see [below](#notices-about-the-chat-or-the-file).
- A turn is running: Send has made way for Stop.

Hovering over the disabled button gives the reason for a comparison and for a chat from
another machine.

## While Claude works

Press Send and the sidebar changes:

- The target line locks.
- Your message appears, and Claude's text and tool calls stream in below it.
- A dim line under the last entry says where the turn is: `Starting Claude…`, `Working…` or
  `Stopping…`. While a tool call runs, the hourglass on its group says so instead, as in
  `Running 2 tools`.
- Send becomes **Stop**, and the model button goes: the model changes between turns.

```{figure} ../images/guides-sidebar/running.png
:alt: A turn at work. The target line has a padlock and a dimmed Auto, the reply so far ends in a group reading Running 2 tools with an hourglass, and the button row has only Stop and the history button.

A turn at work, with two tool calls in flight.
```

**To change course**, type in the box or draw more strokes. **Amend** appears beside Stop as
soon as there is something to send, and Claude gets it in the running turn. **Enter** sends
typed text. Strokes alone go with the **Amend** button or **Shift+Alt+Enter**. It shows in the
conversation as a small box starting `Amend:`. See [Amend a running
turn](prompting.md#amend-a-running-turn).

```{figure} ../images/guides-prompting/amend-typed.png
:alt: The sidebar during a turn, with an amendment typed in the prompt box and the buttons Amend and Stop below it.

An amendment ready to send.
```

**To stop**, open **Stop**, then choose what happens to the work so far.

```{figure} ../images/guides-sidebar/stop-menu.png
:alt: The Stop menu with two items, Stop and Keep Changes, and Stop and Undo This Turn.

**Stop and Keep Changes** leaves the scene as Claude left it. **Stop and Undo This Turn** puts
the target back as it was when the turn started.
```

**To answer a question**, press one of its choices, or type your own answer in the box and
press **Answer** or **Enter**. Your answer shows as a small box starting `Answer:`. Strokes
you draw while Claude asks can still go in with **Amend**. Typed text is taken as the answer,
so an amendment in words has to wait until you have answered.

```{figure} ../images/guides-sidebar/asking.png
:alt: A box in the conversation with a question mark asking whether the lid should overhang the crate by 1 cm or sit flush, with buttons Overhang and Flush.

Claude asks. The question is part of the conversation, not an error, so it is not red.
```

```{figure} ../images/guides-sidebar/answer-typed.png
:alt: The same question with an answer typed in the prompt box, and the buttons Answer and Stop below it.

An answer of your own, ready to send.
```

You can add references during a turn as well. They go with the next request.

## How a turn ends

A finished turn just ends: it has no end line, and Send comes back.

A turn you stopped ends with a dim line, `Stopped, changes kept` or `Stopped, changes undone`.

```{figure} ../images/guides-sidebar/interrupted.png
:alt: A turn ending with its render and a dim line reading Stopped, changes kept.

A stopped turn.
```

A failed turn ends with its reason in red. On the last turn, **Retry** is beside it and sends
the same request again from where the turn started. If the turn's images were too big for one
request, **Edit** is there instead, as sending them again would fail the same way.

```{figure} ../images/guides-sidebar/failed.png
:alt: Two turns. The first finished. The second ends with the red line Claude stopped with an error and a Retry button.

The first turn had a tool error that Claude recovered from, so nothing is red there. The
second failed.
```

A failed turn that changed nothing is not kept in the history. It shows with Retry until your
next Send: [History and branches](history.md#failed-turns-and-retry) says when else it goes.

## Notices about the chat or the file

Three more things can appear, each saying something about the chat or the file.

A chat made on another machine, in someone else's file or your own from another computer,
opens with Send disabled. A box above the Sketch button asks **Continue this chat?**, and Send
stays disabled until you press **Continue**. You can still write a draft, sketch and add references
meanwhile. Continue only for files you trust: the chat's whole conversation goes to Claude
with your next turn.

```{figure} ../images/guides-sidebar/continue-chat.png
:alt: The box Continue this chat? It was made on another machine, with a Continue button above the Sketch button. The prompt is typed and Send is greyed out.

A chat from another machine. **New Chat** in the chat menu is the other way forward.
```

A file naming a style guide this computer has not approved shows a box there too, **Use this
style guide?**, and Send stays disabled until you answer it: see
[Approving a guide](settings.md#approving-a-guide).

If the same file is open in another Blender, a dim line at the top of the panel says so,
because each Blender keeps its own copy of the chats and they will not merge.

```{figure} ../images/guides-sidebar/open-elsewhere.png
:alt: A dim line at the top of the panel reading This file is open in another Blender; chats here won't merge with it.

The same file open twice.
```

After you switch to an earlier chat, a dim line at the end of the conversation says `The scene
is as you left it; Claude will look at it before editing.` It stays until your next turn.
[Chats](chats.md) explains why.

## For developers

With **Developer Extras** on in Blender's Preferences, a closed **Development** panel appears
at the bottom of the Whittle tab. See [Development setup and
testing](../develop/setup-and-testing.md).
