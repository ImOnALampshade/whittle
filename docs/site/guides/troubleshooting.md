# Troubleshooting

When Whittle needs you to act, a box appears at the top of the sidebar, under the chat
title. It shows one problem at a time, so a second box can follow once you fix the first.
A problem with a single turn shows at the end of that turn instead.

A **turn** is one prompt and Claude's work on it. The **agent** is the background program that
runs Claude for Whittle.

Find what the sidebar says:

| The sidebar says | Go to |
|---|---|
| **Set up Claude to start** | [The agent environment is not set up](#the-agent-environment-is-not-set-up) |
| **Last setup failed: …** | [Setup failed](#setup-failed) |
| **Add an API key to start** | [There is no API key](#there-is-no-api-key) |
| **The API key was refused** | [The API key was refused](#the-api-key-was-refused) |
| **Claude could not start** | [Claude could not start](#claude-could-not-start) |
| **Claude stopped unexpectedly** | [Claude stopped unexpectedly](#claude-stopped-unexpectedly) |
| A red line at the end of a turn | [A turn failed](#a-turn-failed) |
| **Could not resume the agent's earlier conversation** | [Claude lost the earlier conversation](#claude-lost-the-earlier-conversation) |
| **Part of the style guide did not load** | [Part of the style guide did not load](#part-of-the-style-guide-did-not-load) |
| **Use this style guide?** | [Whittle asks about a style guide](#whittle-asks-about-a-style-guide) |
| No box at the top, but **Send** is dim | [Send is dim](#send-is-dim) |

If Blender itself crashed, see [Blender crashed](#blender-crashed).

## The agent environment is not set up

Claude runs in a private Python environment that Whittle downloads once. The first time you
press **Send** without one, the box asks for it and Send goes dim. Your prompt stays in the
box.

```{figure} ../images/guides-troubleshooting/setup-needed.png
:alt: The sidebar with a box reading "Set up Claude to start" and a Set Up button, above a prompt and a dim Send button.

Not a failure: this is the first run.
```

1. Turn on **Preferences → System → Network → Allow Online Access** if it is off.
2. Press **Set Up…**, then **Download and Install** in the dialog.
3. Wait for the box to finish. It shows the download's progress and has a **Cancel** button.
4. Press **Send**.

If the environment is there by now, as after a setup in another Blender, **Set Up…** says
`The agent environment is ready` and the box goes.

{doc}`Installing and updating <installation>` says what gets downloaded and where it goes.

A dim line in the box gives the reason when there is an environment that Whittle cannot use:

| The line says | What to do |
|---|---|
| set up for an earlier version of Whittle | Press **Set Up…**. It rebuilds the environment. This is normal after an update. |
| incomplete or its Python is gone | Press **Set Up…**. It rebuilds the environment. |
| holds something Whittle did not make | Whittle will not overwrite that folder. Remove it, or choose another **Environment Folder**: see {doc}`Settings <settings>`. |

### Setup failed

After a failed setup the box adds **Last setup failed:** and the reason, in red. The same
reason is under **Preferences → Add-ons → Whittle → Agent Environment**, with the last lines of
the setup's log.

- **The download stopped.** Setup gives up when no data arrives for 5 minutes. Check your
  connection, and press **Set Up…** again. Behind a proxy, start Blender with `HTTPS_PROXY` set.
- **Anything else.** Read the [setup log](#logs).

Some refusals come before setup starts. Blender shows a message when you press **Download and
Install**, and there is no **Last setup failed:** line and no log:

| The message says | What to do |
|---|---|
| The agent environment needs Python 3.13 or 3.14 | This Blender runs another Python, which Whittle has no packages for. Use Blender 5.2 from [blender.org](https://www.blender.org/download/), which bundles Python 3.13. |
| Blender's Python has no ensurepip, so it cannot make a venv | This Blender runs on a Python without `ensurepip`, which can happen with a Blender from a Linux distribution. Use a Blender from [blender.org](https://www.blender.org/download/), or install your distribution's package that adds `ensurepip`. |

On an Intel Mac, Blender refuses the zip at **Install from Disk**, because Whittle does not
support that platform: see [Installing and updating](installation.md#platforms).

## There is no API key

Whittle needs your own Anthropic API key. Without one, Send starts nothing and your prompt
stays in the box.

```{figure} ../images/guides-troubleshooting/key-needed.png
:alt: The sidebar with a box reading "Add an API key to start", with Get a Key and Preferences buttons, above the prompt "Add a lid."

Send stays enabled and tries again once there is a key.
```

1. Press **Get a Key** and make a key in the
   [Claude Console](https://platform.claude.com/settings/keys), Anthropic's website for keys and
   billing.
2. Press **Preferences…** and paste it into **Anthropic API Key**.
3. Press **Send**.

{doc}`API key and cost <api-key>` has the details.

## The API key was refused

The key reached Anthropic and was turned down. It may be mistyped, or it may have been
deleted in the Claude Console.

```{figure} ../images/guides-troubleshooting/key-refused.png
:alt: The sidebar with a red line reading "The API key was refused", Get a Key and Preferences buttons, and below them a turn ending in "Claude stopped with an error" with a Retry button.

The box says what is wrong with the key. The turn still ends as failed.
```

1. Press **Preferences…** and paste a working key into **Anthropic API Key**. Press **Get a
   Key** if you need a new one.
2. Press **Retry** on the turn, or write a new prompt and press **Send**. The agent restarts by
   itself with the new key.

The box goes away when a turn finishes without an error.

## Claude could not start

The agent did not get going, so your turn did not run. The box does not say why: the reason is in the
agent popover, which opens from the gear in the sidebar's header.

```{figure} ../images/guides-troubleshooting/could-not-start.png
:alt: The sidebar with a red line reading "Claude could not start" and a Restart button, above the prompt "Add a lid." and an enabled Send button.

Your prompt stays in the box.
```

```{figure} ../images/guides-troubleshooting/online-reason.png
:alt: The agent popover. Under "Agent: failed" a dim line reads "Allow Online Access in Preferences > System to run the agent".

The reason is the dim line under the agent's state.
```

| The reason says | What to do |
|---|---|
| Allow Online Access in Preferences > System | Turn on **Preferences → System → Network → Allow Online Access**, then press **Restart**. |
| did not complete the handshake in time | The agent took more than 30 seconds to answer. Press **Restart**. On a busy computer, close something first. |
| exited with code … | Press **Restart**. If it happens again, follow [If it keeps happening](#if-it-keeps-happening). |
| cannot start the agent: … | The rest of the line says why. Press **Restart** once that is fixed. |

**Send** also tries again, so once the cause is fixed you can press it instead of Restart.

If the last turn in the conversation failed, the button reads **Restart and Retry** instead, and
pressing it sends that turn again. To start the agent without retrying, use **Start Agent** in
the agent popover.

## Claude stopped unexpectedly

The agent crashed. The scene stays as the turn left it.

```{figure} ../images/guides-troubleshooting/crashed.png
:alt: The sidebar with a red line reading "Claude stopped unexpectedly" and a Restart and Retry button, above the turn "Add a lid." ending in a dim Interrupted.

The box reports the crash, so the turn only says Interrupted.
```

Press **Restart and Retry** to start the agent and send the turn again. When there is no turn
to send again, the button is **Restart**. Retrying is a new request, and it is billed like any
other turn. {doc}`History and branches <history>` says what happens to the crashed turn.

The agent popover, from the gear in the header, gives the reason.

```{figure} ../images/guides-troubleshooting/crash-reason.png
:alt: The agent popover, reading "Agent: crashed" and below it, dim, "the agent exited with code 3".

The reason is the dim line under the agent's state.
```

### If it keeps happening

1. Save your file. Your chats go with it.
2. Rebuild the environment: **Preferences → Add-ons → Whittle → Agent Environment →
   Reinstall**, then **Download and Install**.
3. If it still crashes, read the end of the newest [agent log](#logs). Add that log when you
   report the problem.

## Blender crashed

If the file has been saved, its chats survive a crash. Whittle keeps a working copy as you go,
so every turn that finished is still in the history, saved or not. The scene comes from
whichever file you open, so it can be behind the chat.

**Open the file again.** The scene is as you last saved it, and the conversation follows the
scene: it ends at the turn the file was saved on. Turns that finished after that save are ahead
of it, and a row under the conversation says how many, such as **1 later turn**.

- Press **Return to Latest** to put the target back as the newest turn left it.
- Or write a prompt and press **Send as Branch**. The new turn branches from the turn the scene
  is on, and Claude is told so. The unsaved turns stay in the history.

**File → Recover → Auto Save** opens one of Blender's autosaves, and the chats come with it.
The conversation follows that scene too, so a turn the autosave caught is the last turn, with
its changes in the scene. A turn after the autosave is ahead of it, as above.

**File → Recover → Last Session** does the same after you quit Blender without saving. Blender
writes that file when it quits, so it does not help after a crash.

Save a recovered file to keep it. A turn that was still running in the crash never finished:
see [If Blender crashes during a turn](history.md#if-blender-crashes-during-a-turn).

## A turn failed

A failed turn ends with a reason in red. On the last turn, **Retry** sits beside it.

```{figure} ../images/guides-troubleshooting/failed-turn.png
:alt: The sidebar with two turns. The first says "That had a syntax error; fixing it." and goes on to finish. The second ends in red with "Claude stopped with an error" and a Retry button.

The first turn recovered from an error by itself. The second failed.
```

A tool call that fails inside a turn is not a failed turn. Claude reads the error and tries
again, as the first turn here did. You only need to act on a red line.

| The red line says | What happened | What to do |
|---|---|---|
| Claude stopped with an error | The run ended on an error with nothing more specific to say | Press **Retry**. |
| the agent CLI stopped, or the agent session ended | The agent's conversation ended during the turn | Press **Retry**. The next turn starts a new one. |
| Images too big: send fewer or smaller | The turn's images, with those already in the conversation, went over what one request can carry | Press **Edit**, which takes Retry's place here, and send fewer or smaller references, or start a new chat if the conversation already holds many: see [What Claude receives](references.md#what-claude-receives). |
| Anything else | The first line of the error Claude's service sent | Act on what it says. Check your Claude Console account if it is about credit or limits. |

If the turn changed the scene, the changes stay, and the turn is kept in the history. Press
**Retry** to go back and send it again, or write a new prompt to carry on from what it left.
{doc}`History and branches <history>` goes through the choices, and {doc}`Undo <undo>` covers
taking the changes back by hand.

### A failed turn that changed nothing

A turn that failed before it touched the scene leaves no step in the history. It stays in the
conversation, with **Retry**, until your next Send, and only while you are on the turn you sent
it from. Switching chats, opening a file or closing Blender drops it. The prompt box stays empty: **Retry** sends the turn's prompt, strokes and references again, and so does **Send** when strokes or references are waiting.

```{figure} ../images/guides-troubleshooting/folded-failure.png
:alt: The sidebar with one turn ending in red with "Claude stopped with an error" and a Retry button. The prompt box is empty.

This turn failed before it touched the scene.
```

If you want to change the prompt first, use **Edit & Resend** from the turn's ⋮ menu.

## Claude lost the earlier conversation

A turn normally continues the chat's Claude session. If Whittle cannot reopen that session when
a turn starts, a warning says `Could not resume the agent's earlier conversation (…); starting a
new one.`, and the turn runs in a new session. The warning stays on that turn, in the sidebar
and in the transcript, also after you reopen the file.

Your chat, its history and the scene are as they were. Claude no longer has what was said
earlier, but it is told so, and it looks at the target before editing. Later turns continue the
new session.

Say in your prompt whatever still matters from earlier turns, such as a style you settled on or
something to leave alone.

## Part of the style guide did not load

The conversation says this once, as a warning, when a turn starts without all of the
[style guide](settings.md#style-guides). The turn still runs: Claude works from what did
load, and is told part of the guide is missing.

To see what went wrong, click the gear at the right of the panel's header. Each file that
did not load has a warning under **Style Notes**, as does a path that won't work elsewhere:

| The warning says | What to do |
|---|---|
| `… was not found.` | The file has moved or been renamed, or the `.blend` moved on its own. Pick the guide again, or fix the `@` line. To move a `.blend`, use **Save As**. |
| `… was refused: only .md and .txt files load.` | Rename the file to `.md` or `.txt`. For a link, check the file it leads to. A line holding only a handle, such as `@alice`, counts as an import, and so does a quoted path with no space in it: reword the line, or take the quotes off. |
| `… passes the 128 KiB limit: it and the rest of the guide were left out.` | Trim the guide, or split it so a file imports less. |
| `… cannot be read: it is not UTF-8 text.` | Save the file as UTF-8 in your text editor. |
| `… cannot be read: …` with another reason | Check that you can open the file, and that its drive or share is there. |
| `… is not an absolute path.` | Start the path in the field with `//`, `~` or the full path. |
| `… is relative to the .blend: save the file to use it.` | Save the `.blend`. |
| `This path is absolute, so it will not travel with the file.` | It works here, and the turn is complete. For a clone or another machine, pick the guide again with **Relative Path** ticked in the file browser. |

The warnings are from the last read, so one you have fixed stays until the next turn or save,
or until you pick the file again.

## Whittle asks about a style guide

The box **Use this style guide?** over the prompt means this file, or a `//` path in your
**Defaults**, leads to a guide this computer has not approved, and **Send** stays disabled until you answer. You will see it once for each guide on each
computer: after a clone, in a file from someone else, or in a second clone in another folder,
which is another path. It also appears when a guide or the `.blend` moves, since the path is what was approved.
[Approving a guide](settings.md#approving-a-guide) says what each button does.

If it asks again for a guide you approved, on the same computer and at the same path, Whittle could not keep the
approval: check that it can write to its [user folder](privacy.md). A warning says so when you approve; the approval
then lasts until Blender closes. **Enter** and **Shift+Alt+Enter** do nothing while the
box is open, and your draft stays where it is.

## Send is dim

With no box at the top of the sidebar, Send is dim for one of these reasons:

- **There is nothing to send.** Type a prompt, draw a stroke or add a reference image.
- **You are comparing two turns.** End the comparison: see {doc}`History and branches <history>`.
- **The chat came from another machine.** Press **Continue** in the **Continue this chat?**
  box, or start a new chat: see {doc}`Chats <chats>`.
- **A style guide needs your answer.** Answer the **Use this style guide?** box: see
  [Whittle asks about a style guide](#whittle-asks-about-a-style-guide).

While a turn runs there is no Send: **Stop** takes its place. See {doc}`The sidebar <sidebar>`.

## Logs

Whittle has no button that opens its logs. They are plain text files in the `logs` folder of its
user folder:

| System | Folder |
|---|---|
| Linux | `~/.config/blender/5.2/extensions/.user/user_default/whittle/logs/` |
| Windows | `%APPDATA%\Blender Foundation\Blender\5.2\extensions\.user\user_default\whittle\logs\` |
| macOS | `~/Library/Application Support/Blender/5.2/extensions/.user/user_default/whittle/logs/` |

If you installed Whittle into another extension repository, that repository's name replaces
`user_default`.

| File | What it holds | How long it stays |
|---|---|---|
| `agent-<date>-<time>-….log` | One start of the agent, up to its crash or exit | The ten newest are kept |
| `venv-<date>-<time>.log` | One run of the environment setup | Until you delete it |

The name holds the date and time the log began, so sorted by name the newest comes last.

To see a log without leaving Blender:

- **Setup:** **Preferences → Add-ons → Whittle → Agent Environment** shows the last lines of the
  latest setup since Blender started.
- **Agent:** turn on **Preferences → Interface → Developer Extras**, and open the **Development**
  panel at the bottom of the sidebar. After a crash or a failed start it shows the last 20 lines.

For more detail in the agent log, start Blender with `WHITTLE_LOG_LEVEL=DEBUG` set in its
environment.

Your API key is never written to a log. A log can show folder names, so read it before you
share it. {doc}`Privacy and safety <privacy>` lists everything Whittle stores on your computer.
