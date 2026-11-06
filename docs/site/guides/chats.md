# Chats

A file can hold any number of chats. Each chat is one conversation with its own
[history](history.md), its own Claude session, and its own [model and effort](models.md).
The sidebar shows one chat at a time, the current chat.

Each time you send, your request and Claude's work on it make one turn, and a chat is a series
of turns.

All the chats in a file work on the same scene. A chat is a separate conversation, not a
separate copy of your model.

## Open the chat menu

The chat's title is in the sidebar's header. Click it to open the chat menu.

:::{figure} ../images/guides-chats/chat-menu.png
:alt: The chat menu: New Chat, three conversations with their turns, age and size, the total for the file, and the rename and delete items

The chat menu over three chats. The check mark is on the current chat.
:::

The most recently active chat comes first. The line under each title gives:

- **Turns**: the chat's turns on all its branches, not counting a failed turn that changed
  nothing.
- **Age**: how long ago its last turn ended.
- **Size**: what the chat adds to the saved `.blend`.

The dim line near the bottom gives the number of chats and their total size. For a file you
have not saved yet, it says `when saved` in place of `in this file`.

The menu lists 20 chats. With more than that, a last row, such as **Show 5 More**, lists the
rest.

## Start a new chat

Start a new chat when you want Claude to begin fresh: on another object, or on something
unrelated to the conversation so far.

1. Open the chat menu.
2. Click **New Chat**.

You get an empty conversation with a fresh Claude session, so Claude remembers nothing from
your other chats. The scene is not touched: Claude finds it as you left it when you send the
first turn, and that is where the chat's history starts.

:::{figure} ../images/guides-chats/new-chat.png
:alt: The sidebar after New Chat: the header reads New chat, the conversation is empty, and the Start from row is showing

A new chat, before its first turn.
:::

**Start from** is optional: you can just write a prompt and send. Only a **Primitive** or an
asset start can change the scene, by adding to it. See [Start row](sidebar.md#start-row).

A chat is titled from its first prompt: the prompt's first line, cut to 40 characters. A first
turn with no prompt is called `Sketch of Crate`, after its first
[target](prompting.md#choose-the-target), or `Sketch` if it has none.

A chat with no turns is dropped as soon as you move to another chat, so clicking around never
leaves empty chats behind. **New Chat** is disabled while the current chat has no turns; its
tooltip says `This chat is new already`.

## Go back to an earlier chat

1. Open the chat menu.
2. Click the chat's title.

The sidebar shows that conversation, and your next turn continues its Claude session, unless
[that session cannot be reopened](troubleshooting.md#claude-lost-the-earlier-conversation). The
scene stays exactly as it is, including anything other chats or you changed in the meantime.
Your prompt, [strokes](sketching.md), [references](references.md) and targets stay too: they
belong to the scene, not to a chat.

Until you next send, a dim line at the end of the conversation reminds you of this. Claude gets
the same message with your next turn, and looks at the scene before editing it.

:::{figure} ../images/guides-chats/switched-chat.png
:alt: The sidebar after switching back to an earlier chat: its conversation, then the line The scene is as you left it; Claude will look at it before editing

Back in an earlier chat, with the reminder above the prompt box.
:::

To put the scene back the way this chat left it, go back to one of its turns by hand: see
[History and branches](history.md). Going back to a turn only removes objects that this chat
made. What another chat made is left alone.

## When New Chat or a chat title is greyed out

You cannot leave the current chat in these cases, and the tooltip says why:

- A turn is running, or Claude is waiting for your answer: `Wait for the turn to end, or stop it`.
- A comparison is showing: `End the comparison first`. See [History and branches](history.md).

## Rename a chat

1. Make it the current chat.
2. Open the chat menu and click **Rename This Chat…**.
3. Type a title and click **Rename**.

An empty title puts the automatic one back. Otherwise a title never changes by itself.

## Delete a chat

Deleting a chat removes its history, transcripts, renders and Claude session. The scene is not
changed: what Claude built stays.

To delete a chat other than the current one:

1. Open the chat menu.
2. Click the trash icon beside the chat.
3. Click **Delete** in the confirmation.

To delete the current chat, click **Delete This Chat…** near the bottom of the menu instead. The
most recently active remaining chat becomes current, or a new empty chat if none is left.

:::{figure} ../images/guides-chats/delete-confirm.png
:alt: A confirmation titled Delete "Make a barrel with two metal bands"?, saying 1 turn, 0.2 MB, it leaves this file the next time you save, with Cancel and Delete buttons

Every delete asks first.
:::

**Ctrl+Z does not bring a chat back**: chats are outside Blender's undo. See [Undo](undo.md).

A trash icon in the menu works while a turn runs, since that turn is in the current chat.
**Delete This Chat…** has to wait, like switching.

### Delete many chats at once

1. Open the chat menu.
2. Click **Delete Other Chats…**. It is there only when the file has other chats.
3. In **Which**, choose **All Other Chats**, **Older Than a Week**, **Older Than a Month** or
   **Older Than 3 Months** (91 days). Age counts from the end of a chat's last turn.
4. Check the count and size under **Which**, then click **Delete**.

The current chat is never included, however old it is. If no chat matches, the dialog says
`No chat is that old.`

:::{figure} ../images/guides-chats/delete-many.png
:alt: The Delete Chats dialog with Which set to Older Than a Month, saying it deletes 1 chat, 0.2 MB, and that this chat stays

The dialog tells you how many chats go, and how much they take up.
:::

### When the file gets smaller

A deleted chat leaves the hidden copy Whittle works from at once (see
[Where chats are stored](#where-chats-are-stored)), but it stays in the `.blend` on disk until
you next save. Save after deleting, especially before you share the file. If Blender
keeps backups (`.blend1`), the backup still holds the chat until the save after that.

## Where chats are stored

Chats are stored inside the `.blend` when you save, so the file alone carries them and nothing
is written beside it. That includes your prompts, Claude's replies and the code it ran, your
reference images and its renders. Moving or renaming the file keeps its chats.

**Save the file to keep a new file's chats.** Until the first save, there is no file to hold them.

While you work, Whittle keeps a hidden working copy in its own user folder. If Blender crashes
or you close without saving, opening the file again keeps the chat work done since the last
save: see [Blender crashed](troubleshooting.md#blender-crashed). Working copies not used for 30 days are deleted; that loses nothing stored in a `.blend`.

To share a `.blend` without its chats, delete them and save, or turn off **Save Chats in the
.blend** in Whittle's preferences, in the **Files** box. With it off, files you save from then
on carry no chats, and chats live only in the working copy, so they go if you leave the file
unopened for 30 days. [Settings](settings.md) has the preferences, and
[Privacy and safety](privacy.md) has what a shared file can carry.

## Open a chat made on another machine

A chat made on another machine, someone else's or your own from another computer, can't send
anything until you decide. You can read its conversation and prepare a prompt, a sketch and
references, but **Send** is disabled.

The rest of the chat still works. Its [history](history.md) is live, so going back to one of its
turns changes the scene, and you can rename or delete the chat. That is on purpose: Whittle holds
back only what would send text to Claude from a chat this install did not start, and looking
through the chat helps you decide.

:::{figure} ../images/guides-chats/continue-chat.png
:alt: The sidebar showing a chat from elsewhere: its conversation, a box reading Continue this chat? It was made on another machine, with a Continue button, and Send greyed out under a typed prompt

A chat from another machine. The prompt typed below it stays there until you choose.
:::

You have two choices:

- **Continue**: click it in the box. The box goes, and you are not asked about this chat again.
  Send works, unless the [**Use this style guide?** box](settings.md#approving-a-guide) is open
  too: each needs its own answer. The whole conversation goes to Claude with your next turn, so
  continue only chats from files you trust. The chat records this, so in a repository the
  `.blend` differs at your next save.
- **New Chat**: start fresh from the chat menu, with none of that conversation sent. This is the
  safer choice for a file from someone else. [Privacy and safety](privacy.md) explains why.

Whittle tells chats apart by a random id it keeps for this install, which names no person or
machine. If Whittle's user folder was reset, it gets a new id, so your own chats ask too. Chats
from files saved before Whittle recorded this never ask. For a repository on two machines, see
[Set up a guide for a project](settings.md#set-up-a-guide-for-a-project) for what asks and how often.

## The same file open in another Blender

When two Blenders have the same saved file open, a dim line shows at the top of the sidebar in
both, whether the file has chats or not:

:::{figure} ../images/guides-chats/open-elsewhere.png
:alt: The top of the sidebar with the line: This file is open in another Blender; chats here won't merge with it

The line goes when the other Blender closes the file.
:::

Each Blender keeps its own copy of the chats, and they never merge. Whichever saves last decides
what the file stores, so chat work saved from the other Blender is lost from the file.

To avoid that, save and close the file in one Blender, then reopen it in the other with
**File > Revert** or **File > Open** before you carry on there. Closing alone is not enough: the
other Blender still holds its older copy, and its next save overwrites what you saved. Reopening
drops whatever that Blender had not saved, scene and chats alike.

Or use **Save As** in one of them to make it a file of its own.
