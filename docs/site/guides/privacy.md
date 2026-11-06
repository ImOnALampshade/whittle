# Privacy and safety

Whittle sends your work to Anthropic so Claude can see it, keeps a copy of every chat on
your computer and in your `.blend`, and lets Claude run Python in your Blender. This page
says what that means and what you can do about it.

## What leaves your computer

Nothing about your scene leaves until you send a turn, which is one prompt and the work
Claude does on it. Typing a prompt, drawing a sketch and attaching a reference all stay
local.

The agent is the background program that talks to Claude. It uses Anthropic's API, with
your key. It asks for the list of models when it starts, then sends the turns. A turn
sends:

- your prompts, amendments and answers to Claude's questions, and the reference images
  you attach or pin;
- the sketch: the strokes with their positions, the camera of each view, and
  images of your strokes over the model;
- what Claude looks at while it works: scene information it asks for (object names,
  transforms, mesh statistics, materials, modifiers, node groups), the output and errors
  of the Python it runs, and the renders it makes to check its own work;
- details of the request: the target's object names, this file's triangle budget and
  self-check rounds, the file names of your references, and folder paths on your computer,
  which can include your user name;
- the text of the [style guide](settings.md#style-guides), if the file has one: every file
  it loads. **Style Notes** in the agent popover names the first ten and counts the rest;
- Whittle's instructions to Claude, and the conversation so far.

The target is the objects you pick for Claude to change: see
[Prompts and targets](prompting.md). It limits what Claude should change, not what it can
see. Claude can read every object in the open file.

Anthropic's handling of API data is set out in its
[privacy policy](https://www.anthropic.com/legal/privacy) and
[commercial terms](https://www.anthropic.com/legal/commercial-terms).

Two other things reach the network:

- **Setup.** Setting up the agent environment downloads its pinned, hash-checked packages
  from PyPI. See [Installing and updating](installation.md).
- **Claude's own Python**, if it chooses to, as [below](#claude-runs-python-as-you).

Whittle needs Blender's **Allow Online Access** (Preferences → System) for setup and for
the agent; with it off, neither starts.

If Blender's environment sets `ANTHROPIC_BASE_URL`, say for a company gateway, the agent
sends all of this, and your key, to that address instead.

## Keep usage data off

The Claude command-line program bundled with Whittle can send Anthropic its own usage
telemetry and error reports. Whittle turns that off, so the program sends only the turns.

To check or change it, open **Preferences → Add-ons → Whittle** and look at **Send Claude
CLI usage data** in the Claude box. It is off by default. A change reaches an idle agent
at the next turn, when it restarts.

```{figure} ../images/guides-privacy/usage-data.png
:alt: The Claude box of Whittle's preferences, with Send Claude CLI usage data unticked.

**Send Claude CLI usage data**, off as it is by default.
```

If you tick it while Blender's own environment sets
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, the variable wins and nothing extra is sent.

## What is stored where

**Your API key** is in Blender's preferences (`userpref.blend`) and, while the agent runs,
in that process's environment. Whittle writes it nowhere else, so it is never in a
`.blend`, a chat or a log. See [API key and cost](api-key.md).

**Your chats** are in two places: inside the `.blend` when you save it, and in a hidden
copy in Whittle's user folder while you work. Nothing is written beside your file. A chat
holds your prompts, Claude's replies and the code it ran, your reference images, its
renders, and snapshots of the objects it worked on. Each turn's stored request also records
the path of the style guide in use, one from **Defaults** included, so that path travels with
the chat and stays there after you clear the field. Deleting the chat removes it.

**Whittle's user folder** is `extensions/.user/user_default/whittle/` in Blender's
configuration folder:

| System | Blender's configuration folder |
|---|---|
| Linux | `~/.config/blender/5.2/` |
| Windows | `%APPDATA%\Blender Foundation\Blender\5.2\` |
| macOS | `~/Library/Application Support/Blender/5.2/` |

If you installed Whittle into another extension repository, that repository's name replaces
`user_default`.

| In the user folder | What it holds | How long |
|---|---|---|
| `cache/` | The working copy of each file's chats. Each chat also has a copy of its system prompt with the style guide's text in it, which stays on this computer and is not packed into the `.blend` | Deleted once unused for 30 days, never for the open file |
| `claude/` | The bundled program's own state and transcripts | A chat's go when the chat is deleted or its cache expires |
| `agents/` | On Windows only, a record of each running agent: its process number and start time | Removed when the agent exits, or by a later start if it was killed |
| `logs/` | Agent logs, and a log of each setup | The last ten agent logs are kept |
| `venv/` | The agent's private Python, unless **Environment Folder** points elsewhere | Until you remove it |
| `models.json` | The list of models | Replaced as it updates |
| `install.json` | A random id for this install, which marks the chats made here. It names no person or machine | Until you remove it |

On Windows, an agent that was killed can also leave a `claude-resume-*` folder in the
temporary folder. A later agent start removes it once it is a day old.

The bundled program never reads your own Claude configuration, if you have one: Whittle
gives it a folder of its own.

## Share a .blend without your chats

Every chat in a saved file travels with it. Before you send a `.blend` to someone, do one
of these, then save:

- Delete the chats from the chat menu. See [Chats](chats.md). A deleted chat leaves the
  file at the next save, not before.
- Or turn off **Save Chats in the .blend**, in the Files box of **Preferences → Add-ons →
  Whittle**. Files saved from then on carry no chats.

```{figure} ../images/guides-privacy/save-chats.png
:alt: The Files box of Whittle's preferences, with Save Chats in the .blend ticked.

**Save Chats in the .blend**, on by default.
```

Four things to watch:

- With this setting off, the cache is the only copy of a file's chats, and a cache unused
  for 30 days is deleted with them.
- Blender's backup, `yourfile.blend1`, is the previous save and can still hold the chats.
  Don't send it.
- **Open Transcript** shows the chat's whole transcript in a text named `Whittle Transcript`.
  That text is only a view: no save keeps it, whatever this setting says, and it goes when you
  delete the chat. A file saved by an older Whittle may hold a copy, which goes at the file's
  next save with Whittle enabled.
- Some of Whittle's state is part of the scene and stays in the file either way: the
  text in the prompt box, any strokes still in the sketch, the list of references with
  their file paths, and this file's settings such as the path in **Style Notes**. A stopped or failed
  turn leaves the strokes you sent in the sketch.

## Remove what Whittle keeps on this computer

1. Delete the chats you no longer want, and save the files that hold them. Delete any
   `.blend1` backups of those files too.
2. Clear **Anthropic API Key** in the preferences, if you set one there.
3. Quit Blender and delete Whittle's user folder, and the **Environment Folder** if you
   pointed it elsewhere.
4. On Windows, delete any `claude-resume-*` folders in the temporary folder.

Whittle makes what it needs again. With its folder gone you will have to set up the agent
environment again, and chats in your `.blend` files will count as made elsewhere and ask to
be continued.

## Claude runs Python as you

The agent edits the scene by running Python inside your Blender. That Python is not
sandboxed, and Claude does not ask before each run. It can do anything you can: read and
write your files, start programs, reach the network. Its output goes back to Claude, so
anything it reads goes to Anthropic. That is what lets it model, and it is why what
Claude reads matters.

The bundled program's own file and shell tools are turned off, so everything Claude does
on your machine goes through Blender.

For a quick look at what ran, open a turn's **Used … tools** or **Thought, used … tools**
line, then a call inside it. The sidebar shows the first 40 lines of a call and a short
result. Long lines are cut at the sidebar's edge, so widening it shows more of each line,
but no more lines.

```{figure} ../images/guides-privacy/tool-code.png
:alt: Whittle's sidebar with a finished turn's tool calls opened, showing Python code.

A turn's tool calls opened, with the code Claude ran. Lines are cut at the sidebar's edge.
```

To read a turn's code in full, click the turn's **⋮** button and pick **Open Transcript**.
It shows the chat's whole transcript in Blender's Text Editor, with every line of each
call's code and a short result.

To stop a turn, use **Stop** under the prompt box, and pick **Stop and Keep Changes** or
**Stop and Undo This Turn**. Stop and Undo This Turn puts the target back and removes the
objects Claude made. Anything else its Python changed stays changed, in the scene or on
disk. Ctrl+Z is the way back for the whole scene, though not for files on disk: see
[Undo](undo.md).

Blender's **Auto Run Python Scripts** setting does not cover Whittle. It only stops
scripts stored in a file. Nothing Whittle stores in a file runs code by itself.

## Be careful with files you did not make

Claude reads the scene (object, material and collection names), your reference images,
the style guide and, when you continue a chat, that chat's whole conversation. Text planted
in any of these could try to steer Claude, and Claude can run Python.

So a chat made on another machine opens with Send disabled, and asks
**Continue this chat?** You are asked once per chat. Chats from files saved before Whittle
recorded where a chat was made never ask.

```{figure} ../images/guides-privacy/continue-chat.png
:alt: Whittle's sidebar showing a box that asks Continue this chat? above a disabled Send button.

A chat from another machine. Continuing replays its whole conversation to Claude.
```

With a file from someone else:

- Start a **New Chat** rather than pressing **Continue**. See [Chats](chats.md).
- A new chat still reads the scene, so don't run Whittle at all on a file you don't trust.
- Check **Style Notes** in the agent popover before you send, pressing **Read Now** to list
  the files. The `.blend` stores that path, and what it loads is sent with your turns. Only
  `.md` and `.txt` files load, but a private note of that kind could. The list names only the
  first ten files: **and N more files** means more is sent than you can see, so in a file you
  don't trust, clear **Style Notes** rather than send. See
  [Style guides](settings.md#style-guides).

Links in Claude's replies open only `http`, `https` and `mailto` addresses. Any other link
is plain text.
