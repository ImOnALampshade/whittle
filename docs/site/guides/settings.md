# Settings

Whittle's settings live in two places. The **Preferences** apply to every file. **For This
File**, in the popover behind the Whittle panel's gear, overrides four of them and is stored
on the current scene, so it travels with the `.blend`. The model and effort are neither:
each chat keeps its own, see [Models and effort](models.md).

## Open the Preferences

1. Choose **Edit → Preferences → Add-ons**.
2. Find **Whittle** and open its entry.

Or, in the 3D viewport's sidebar (**N**), open the **Whittle** tab, click the gear at the
right of the panel's header and press **Preferences…** in the popover that opens. See
[The sidebar](sidebar.md#header).

Blender keeps these values with its own preferences, so they are the same in every file.

```{figure} ../images/guides-settings/preferences.png
:alt: Whittle's entry in Blender's Preferences, with the boxes Claude, Agent Environment, Defaults, Files and Development
:width: 680px

Whittle's preferences, once the agent environment is set up and a key is in.
```

Every preference is listed under [All preferences](#all-preferences).

## Change a setting for one file

Use this when a file needs something the others don't: a hero prop that deserves more
self-check rounds, a quick blockout that needs fewer, or a style guide of its own.

1. In the 3D viewport's sidebar (**N**), open the **Whittle** tab and click the gear at the
   right of the panel's header. This opens the agent popover. The agent is the background
   process that talks to Claude, and while it is starting or stopping the gear shows an
   hourglass instead. See [The sidebar](sidebar.md#header).
2. Under **For This File**, type a value into the field you want to change, or for
   **Style Notes** pick a file with the icon at the end of its field.
3. Save the file. The value is stored on the current scene, so it travels with the `.blend`
   and applies to every chat while that scene is active. A file with several scenes needs
   it set in each: another scene shows "(default)" and gets the Preferences.

```{figure} ../images/guides-settings/agent-popover.png
:alt: The agent popover. Triangle Budget and Render Size say (default); Self-check Rounds is 2, and Style Notes names a file, with the two files it sends listed under it and a warning that an import was not found

The agent popover. Triangle Budget and Render Size follow the Preferences, so they say
"(default)" and their reset buttons are greyed out. This file sets the other two. Under
**Style Notes** are the files it sends, and a warning about one that is missing.
```

A field with "(default)" after its name shows the value from the Preferences, so it always
says what Claude will get. Typing sets a value for this file, even the same value. That
includes an empty one: clear **Style Notes** and this file has no style guide, whatever the
Preferences say.

To go back to the Preferences, press the reset button at the end of the field's line.

## Change a setting for every file

Set the value in the **Defaults** box of the Preferences. It holds the same four settings,
and it reaches every file that has not set its own value, existing files included.

## When a change takes effect

Settings reach Claude at the next turn, the next prompt you send. If the agent, the
background process that talks to Claude, is idle and running on other settings, Whittle
restarts it before that turn, and the conversation carries on from the history, unless
[Claude's session cannot be reopened](troubleshooting.md#claude-lost-the-earlier-conversation).
A turn that is already running is not restarted. An edit to a style guide counts as a
change: see [Style guides](#style-guides).

## The four session settings

These are the settings in both **Defaults** and **For This File**.

| Setting | Default | Allowed | What it does |
|---|---|---|---|
| **Triangle Budget** | 2000 | 10 or more | Rough triangle budget for the whole [target](prompting.md) |
| **Self-check Rounds** | 3 | 0 to 10 | How many times Claude may fix what its [self-check](#budget-rounds-and-render-size) finds |
| **Render Size** | 512 | 64 to 1024 | Pixel size of Claude's self-check renders |
| **Style Notes** | Empty | A `.md` or `.txt` file | The [style guide](#style-guides) Claude works to |

### Budget, rounds and render size

After building, Claude renders the model and compares the renders with your sketch, then
fixes what is off and looks again. Each pass of fixes is a self-check round. For the
comparison, an overlay image draws your strokes over the render. Without a sketch, Claude
looks at the model from a few angles instead.

**Triangle Budget** is a loose guide, not a cap: Claude spends what the shape needs. It
counts the mesh with its modifiers applied, because Bevel, Mirror, Array and Subdivision
multiply triangles.

**Self-check Rounds** limits how many of those rounds Claude spends. When the rounds run out it stops, even if the result is not perfect, and says what is left.

**Render Size** sets the longest side of those renders, overlay images included. Claude can ask for another size for a single render.

Rounds and render size are cost settings as much as quality ones, because each round sends
renders back to the model. See [API key and cost](api-key.md).

## Style guides

A style guide is a text file saying how things should look: colours, edges, materials,
mood, anything about the look, in your own words. **Style Notes** points at one, and many
`.blend` files can point at the same one. Leave it empty and Claude chooses the look itself.

Claude reads the guide as your preferences for the file, not as rules. A request's prompt or
sketch wins, and guidance that doesn't suit a part can be left off it: a bevel on a cloth
strap, iron on a rope. If Claude departs from it in a way you would notice, it says so in
its reply. The guide is about the look only, so Claude is told not to act on anything in it
about tools, files or how to work.

### Where to keep it

Keep your guides in your project's folder, and pick one with the icon at the end of the
field. A path starting with `//` is relative to the folder of the open `.blend`, and it needs
a saved file. Any other path in the field has to be absolute or start with `~`. Set it under
**For This File**, or in **Defaults** for every file with no guide of its own.

If your guides are in the same repository as your `.blend` files, use `//` paths: they keep
working wherever the repository is cloned. Windows and Linux can share one, as a backslash in
a `//` path or an `@` import reads as a slash on every platform. A path with a drive or a
network share in it only means something on the machine it was written on.

**Save As** into another folder rewrites the `//` path of every scene that sets one under
**For This File**, so it still names the same guide. **Save Copy** does the same for the
copy and leaves the open file alone. A `//` path in **Defaults** is not rewritten: it is
relative to whichever `.blend` is open. An undo or redo across the Save As keeps naming the
same guide: the path is rewritten again for where the file is now. A `.blend` saved through a
symlinked folder is counted from the folder's real place, as reading the guide is. If a folder
on the way has a backslash in its name, on Linux or macOS, the path becomes an absolute one,
since a `//` path would read that backslash as a slash. A **Save As** onto another Windows
drive also leaves an absolute path, as no `//` path reaches across drives.

Moving a `.blend` in a file manager or with `git mv` fixes nothing, because Blender saves
nothing: the path is now counted from the new folder, **Style Notes** warns that the guide was
not found, and turns run without it until you pick it again. To move a `.blend` on its own,
open it and use **Save As** instead. Moving a whole folder with its guides inside it is fine:
the path between them stays the same.

### Set up a guide for a project

For a repository of `.blend` files that share a look:

1. Put the guides in the repository, and save the `.blend` there first. In a file that has
   never been saved, the file browser writes an absolute path, with no warning.
2. Click the gear at the right of the panel's header. Under **For This File**, pick the guide
   with the icon at the end of **Style Notes**.
3. Check that the field starts with `//`. If it doesn't, pick the guide again with **Relative
   Path** ticked in the file browser.
4. Save the `.blend`, and commit the guides with it.
5. Repeat for each `.blend`, and for each scene in it. There is no way to set many at once,
   and a new `.blend` has no guide until you set one.

**Defaults** rarely fits a repository. A `//` path there counts from each open file's own
folder, so it only works if every `.blend` sits at the same depth, and an absolute path only
works on one machine. It suits a guide you want on everything you make.

### Import other files

A line holding only `@` and a path pulls another file in at that spot, so a base look is
written once and other files add detail.

- The path is relative to the file doing the importing. Absolute paths and `~` work too.
  `//` does not: it is for the field only.
- The imported text replaces the line, so you choose the order. Imported files can import
  others.
- A file reached twice is included only the first time, so a shared base isn't repeated.
- A line with anything else on it is plain text, so an address or a handle in a sentence
  imports nothing. Neither does a line inside a fenced code block, in a list item or not.
- Nothing may follow the path on its line: `@base.md # the base` is plain text and is sent
  as it stands, with no warning.
- Quotes are not understood, so write paths without them. `@"my base.md"`, with a space, is
  plain text and is sent as it stands, with no warning. `@"base.md"`, without one, counts as
  an import: it is refused with a warning and left out.
- A path with spaces needs no quotes, but it must end in `.md` or `.txt`, or the line counts
  as a sentence. So `@bob read notes.md` is an import, of a file called `bob read notes.md`.
- A line holding only a handle, such as `@alice` or `@team/art-leads`, counts as an import
  and warns that the guide is incomplete. Reword it, or put it in a sentence.
- A link imports relative to where the real file lives, not where the link is.

### Example

A game with a shared art style, a faction and one of that faction's cultures:

```text
harbour-game/
  style/
    base.md
    factions/
      saltwrights.md
      reef-clans.md
  models/
    harbour_crane.blend
    coral_shrine.blend
```

`style/base.md`:

```text
# Art style
Chunky, hand-painted shapes. Bevels wide enough to read from across a room.
Muted colours, no pure black or white.
```

`style/factions/saltwrights.md`:

```text
@../base.md

# The Saltwrights
Salt-bleached driftwood, rope and green copper. Curves rather than corners.
```

`style/factions/reef-clans.md`:

```text
@saltwrights.md

# Reef clans
Coral inlays and shell plating. Everything looks grown, not built.
```

Each `.blend` points at the level it belongs to:

| File | **Style Notes** | Claude gets |
|---|---|---|
| `harbour_crane.blend` | `//../style/factions/saltwrights.md` | The art style, then the Saltwrights |
| `coral_shrine.blend` | `//../style/factions/reef-clans.md` | The art style, the Saltwrights, then the reef clans |

Change `base.md` once, and both follow.

### What loads, and when

- **The list.** Under the field, **Sent with each turn** shows the files loaded, the first
  ten and how many more. A file from outside the top guide's folder is shown in full and
  listed first, so it cannot hide past the tenth row; the rest follow in import order, and
  the text is sent in import order whatever the list shows. Their text goes to Anthropic
  with your turns, so look here in a `.blend` you did not make: the path is stored in the
  file and could name something private of yours. **and N more files** means more is being sent than you can see, so in a
  file you do not trust, clear **Style Notes** rather than send.
- **The last read.** The list and its warnings show what the last read found, not what is on
  disk now. After you edit a guide or fix an import, they catch up at the next turn or save,
  or when you pick the file again.
- **Opening a file.** Opening a `.blend` does not read the path it stores, since that could
  name a network share. The field says **Read at the next turn.** until you send a turn,
  save the file or press **Read Now**, which lists the files before anything is sent. Any
  path with no read yet shows the same, as can happen after an undo or a scene switch. Once a
  path has a read, the button goes.
- **File types.** Only `.md` and `.txt` files load, as UTF-8 text. A link is judged by the
  file it leads to, so `notes.md` linking to a private key is refused.
- **Size.** A guide can be 128 KiB in all. Reading stops at the file that would pass that,
  with a warning: that file and everything after it are left out, the rest of the files
  that imported it included.
- **Problems.** A missing, unreadable or refused file, the one in the field included, never
  stops a turn. It shows as a warning under the field, the conversation says so once, and
  Claude works from what did load and is told part of the guide is missing.
  [Troubleshooting](troubleshooting.md#part-of-the-style-guide-did-not-load) says what to do
  about each warning.
- **Edits.** Whittle reads the guide again before each turn, so an edit applies from the
  next turn. If the text changed, the agent restarts first, and the conversation carries on.
  A running turn and its amendments keep the guide they started with.
- **Cost.** The guide's text goes with every request of every turn. See
  [Keep the cost down](api-key.md#keep-the-cost-down).

## Keep chats out of the .blend

Whittle stores every chat inside the `.blend` when you save: prompts, Claude's replies and
code, reference images and renders. To keep them on this computer, for example before you
share a file:

1. Open the Preferences.
2. In the **Files** box, turn off **Save Chats in the .blend**.
3. Save the file.

Chats then stay in this computer's cache only, and files saved from now on carry none. See
[Chats](chats.md).

## Send usage data to Anthropic

The command-line program bundled with the agent can send Anthropic its own usage telemetry
and error reports. Whittle turns that off. To allow it, turn on **Send Claude CLI usage
data** in the **Claude** box of the Preferences. It is off until you do.

An idle agent restarts with the change at the next turn. If Blender's own environment sets
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, that setting stands even with the option on. What
a turn sends is in [Privacy and safety](privacy.md).

## Move the agent environment

Whittle keeps its private Python environment in the extension's user folder. To put it
somewhere else, for example a shorter path on Windows:

1. In the **Agent Environment** box, choose a new or empty folder as the **Environment
   Folder**. The environment goes straight into that folder, not into a subfolder.
2. Press **Set Up Agent Environment**.

The status line under the field describes the chosen folder. For a new or empty folder it
says **Not set up yet** until the setup has run there. A folder with other files in it says
**The folder holds something Whittle did not make**, and the setup refuses it. See [Installing and updating](installation.md).

## All preferences

Claude
: **Anthropic API Key**: the key Claude runs with, billed to its Anthropic Console account.
  Empty: `ANTHROPIC_API_KEY` from Blender's environment, if set; a key typed here wins over
  it. **Get an API Key** opens the Console. See [API key and cost](api-key.md).
: **Model for New Chats**: the model a new chat starts on, `claude-opus-5-5` by default. It
  suggests the models in the model menu, those last reported for your key plus the ones
  Whittle knows about, and takes any other model id. See
  [Models and effort](models.md).
: **Send Claude CLI usage data**: off by default. See
  [Send usage data to Anthropic](#send-usage-data-to-anthropic).

Agent Environment
: **Environment Folder**: where the agent's private Python environment lives. Empty means
  the extension's own user folder. Changing it clears a **Set up Claude to start** box: the
  next start looks again.
: **Set Up Agent Environment** and **Reinstall**: make the environment, or rebuild it from
  scratch. See [Installing and updating](installation.md).

Defaults
: **Triangle Budget**, **Self-check Rounds**, **Render Size** and **Style Notes**. See
  [The four session settings](#the-four-session-settings).

Files
: **Save Chats in the .blend**: on by default. See
  [Keep chats out of the .blend](#keep-chats-out-of-the-blend).

Development
: **Agent Python**: a development override for the Python that runs the agent. Leave it
  empty unless you work on Whittle. See
  [Development setup and testing](../develop/setup-and-testing.md).
