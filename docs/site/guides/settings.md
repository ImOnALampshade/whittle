# Settings

Whittle's settings live in two places. The **Preferences** apply to every file. **For This
File**, in the popover behind the Whittle panel's gear, overrides six of them and is stored
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
self-check rounds, a quick blockout that needs fewer, or a palette for one project.

1. In the 3D viewport's sidebar (**N**), open the **Whittle** tab and click the gear at the
   right of the panel's header. This opens the agent popover. The agent is the background
   process that talks to Claude, and while it is starting or stopping the gear shows an
   hourglass instead. See [The sidebar](sidebar.md#header).
2. Under **For This File**, type a value into the field you want to change.
3. Save the file. The value is stored on the current scene, so it travels with the `.blend`
   and applies to every chat while that scene is active. A file with several scenes needs
   it set in each: another scene shows "(default)" and gets the Preferences.

```{figure} ../images/guides-settings/agent-popover.png
:alt: The agent popover. Triangle Budget and Render Size say (default); Self-check Rounds is 2, the palette is weathered oak, dark iron, the bevel style is chunky, and the style notes are filled in

The agent popover. Triangle Budget and Render Size follow the Preferences, so they say
"(default)" and their reset buttons are greyed out. This file sets the other four.
```

A field with "(default)" after its name shows the value from the Preferences, so it always
says what Claude will get. Typing sets a value for this file, even the same value. That
includes an empty one: clear **Palette** and this file has no palette, whatever the
Preferences say.

To go back to the Preferences, press the reset button at the end of the field's line.

## Change a setting for every file

Set the value in the **Defaults** box of the Preferences. It holds the same six settings,
and it reaches every file that has not set its own value, existing files included.

## When a change takes effect

Settings reach Claude at the next turn, the next prompt you send. If the agent, the
background process that talks to Claude, is idle and running on other settings, Whittle
restarts it before that turn, and the conversation carries on from the history, unless
[Claude's session cannot be reopened](troubleshooting.md#claude-lost-the-earlier-conversation).
A turn that is already running is not restarted.

## The six session settings

These are the settings in both **Defaults** and **For This File**.

| Setting | Default | Allowed | What it does |
|---|---|---|---|
| **Triangle Budget** | 2000 | 10 or more | Rough triangle budget for the whole [target](prompting.md) |
| **Self-check Rounds** | 3 | 0 to 10 | How many times Claude may fix what its [self-check](#budget-rounds-and-render-size) finds |
| **Render Size** | 512 | 64 to 1024 | Pixel size of Claude's self-check renders |
| **Palette** | Empty | Any text | The colours Claude builds materials from |
| **Bevel Style** | Empty | Any text | How Claude bevels edges |
| **Style Notes** | Empty | Any text | Extra style guidance |

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

### Palette, bevel style and style notes

Together these are the style Claude works to. Claude reads them as your preferences for the
file, not as rules. A request's prompt or sketch wins, and a preference that doesn't suit a
part can be left off it: a bevel on a cloth strap, iron on a rope. If Claude departs from
one in a way you would notice, it says so in its reply.

**Palette** is a short list, such as `weathered oak, dark iron`. Left empty, Claude picks
colours that suit the object and the prompt.

**Bevel Style** suggests three styles as you click into it, and takes any other text as
written, such as `rounded corners only`. Left empty, Claude decides per shape.

| Style | What Claude is told |
|---|---|
| `none` | Crisp, unbevelled edges |
| `subtle` | Narrow bevels on hard edges, just wide enough to catch the light |
| `chunky` | Wide, clearly visible bevels that round edges and corners off, a stylised look |

**Style Notes** is anything else about the look, such as `worn painted wood`.

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
: **Triangle Budget**, **Self-check Rounds**, **Render Size**, **Palette**, **Bevel Style**
  and **Style Notes**. See [The six session settings](#the-six-session-settings).

Files
: **Save Chats in the .blend**: on by default. See
  [Keep chats out of the .blend](#keep-chats-out-of-the-blend).

Development
: **Agent Python**: a development override for the Python that runs the agent. Leave it
  empty unless you work on Whittle. See
  [Development setup and testing](../develop/setup-and-testing.md).
