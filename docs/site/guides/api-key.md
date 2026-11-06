# API key and cost

Whittle runs Claude with your own Anthropic API key, and every turn is billed to that key's
account. A claude.ai login or a Claude subscription won't work: Whittle takes an API key
only, and API usage is billed separately from any subscription.

A *turn* is one request you send and everything Claude does to answer it. The *agent* is the
background process that runs Claude for Whittle; it starts when you first press **Send**.

## Add a key

1. Open **Edit → Preferences → Add-ons → Whittle**.
2. Press **Get an API Key**. It opens the keys page of the
   [Claude Console](https://platform.claude.com/settings/keys) in your browser.
3. Make a key there and copy it. The Console account needs API credits.
4. Paste the key into **Anthropic API Key**.

```{figure} ../images/guides-api-key/prefs-typed.png
:alt: The Claude box in Whittle's preferences: the Anthropic API Key field filled with stars, the line "Usage is billed to the key's Anthropic Console account." and the Get an API Key button

A key in the preference. The field shows stars instead of the key.
```

The key is saved with Blender's preferences, not in your `.blend`. If you have turned off
Blender's **Auto-Save Preferences**, use **Save Preferences** or the key is gone next time
you start Blender. {doc}`Privacy and safety <privacy>` says where the key goes.

To change the key, paste a new one over it. A running agent picks it up at the next turn,
when it restarts.

## Use a key from the environment

If you already keep a key in `ANTHROPIC_API_KEY`, Whittle can use that. Leave **Anthropic
API Key** empty, set the variable in a terminal, and start Blender from that same terminal
window.

On Linux, where the second line is the full path to `blender` if it isn't on your `PATH`:

```sh
export ANTHROPIC_API_KEY=your-key
blender
```

On macOS:

```sh
export ANTHROPIC_API_KEY=your-key
/Applications/Blender.app/Contents/MacOS/Blender
```

In the Windows Command Prompt, with the path to your own `blender.exe`:

```bat
set ANTHROPIC_API_KEY=your-key
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
```

Blender only sees what was set before it started. A Blender opened from a desktop icon
won't see a variable you set in a terminal, and changing the variable means restarting
Blender.

## Check which key is in use

A key in the preference wins over one in the environment. The line under the field says
what Whittle found:

| The line says | Whittle is using |
|---|---|
| `Usage is billed to the key's Anthropic Console account.` | The key in the preference |
| `Using ANTHROPIC_API_KEY from Blender's environment.` | The key in the environment |
| `Whittle needs an Anthropic API key to run Claude.` | Nothing: it found no key |

```{figure} ../images/guides-api-key/prefs-environment.png
:alt: The Claude box in Whittle's preferences: an empty Anthropic API Key field, the line "Using ANTHROPIC_API_KEY from Blender's environment." and the Get an API Key button

The preference is empty, so Whittle uses the key from the environment.
```

To switch from the preference to the environment, clear the field.

## When the sidebar asks for a key

If you press **Send** with no key anywhere, the agent doesn't start. Nothing is billed, your
prompt stays in the box, and the sidebar says what to do.

```{figure} ../images/guides-api-key/key-needed.png
:alt: The Whittle sidebar with a box reading "Add an API key to start", the line "Whittle runs Claude with your own Anthropic API key, billed to your Console account.", Get a Key and Preferences buttons, and the prompt "Add a lid." still in the prompt box

The prompt is still there, and Send stays enabled.
```

1. Press **Get a Key** and make a key in the Console.
2. Press **Preferences…** and paste it into **Anthropic API Key**. The box in the sidebar
   goes away.
3. Press **Send** again.

A red `The API key was refused` is different: Whittle has a key and Anthropic turned it
down. See {doc}`Troubleshooting <troubleshooting>`.

## Use a gateway

If your company sends API traffic through a gateway, set `ANTHROPIC_BASE_URL` to its address
the same way as the key above, in the terminal you start Blender from. Give the address without `/v1`, such
as `https://gateway.example.com`. There is no preference for it, and the sidebar doesn't show
that one is in use.

- **You still need a key.** The agent won't start without one, and it is the only credential
  that gets through. Whittle removes every other way of signing in from the agent's
  environment, including `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_CUSTOM_HEADERS`, so
  the gateway has to accept the key on its own.
- **Everything goes to the gateway**: your key, the turns and the list of models. See
  {doc}`Privacy and safety <privacy>`.
- **If the gateway doesn't list its models**, the model menu shows Whittle's own list. You
  can still type a model id; see {doc}`Models and effort <models>`.
- **The cost in the sidebar isn't the gateway's price.** Check with whoever runs it.

## See what a turn cost

Only turns are billed. Starting the agent lists the models your key can use, which uses no
tokens, and an idle agent costs nothing.

A turn costs what its model charges for everything it reads and writes: your prompt, the
sketch and references, the [style guide](settings.md#style-guides), the conversation so far,
Claude's thinking and the renders it looks at. So it depends on the request, and Whittle can't tell you the price before you send.
Anthropic's [pricing page](https://platform.claude.com/docs/en/about-claude/pricing) has the
price per token. The surest guide is to run one turn of the kind you plan to do and read its
cost.

To read it, open the last tool group of a finished turn. Its header reads **Used N tools**,
**Thought, used N tools** when Claude also thought, or just **Thought**. The cost is the dim
line at its end, in US dollars, after the number of steps. A step is one reply from Claude
within the turn, and a turn with more steps costs more.

```{figure} ../images/guides-api-key/turn-cost.png
:alt: A finished turn in the sidebar with its Used 2 tools group open, showing the exec and render calls, a render thumbnail, and the dim line "3 steps · $0.1240"

The cost is at the end of the turn's last tool group. This figure is an example.
```

Every turn's cost is also in the transcript: click a turn's **⋮** button and pick **Open
Transcript**. That is also where to look for a turn with no such group. A failed or stopped
turn is still billed for what it used, and a turn cut off by a crash shows no cost at all.

Whittle doesn't add turns up. The sidebar's figure comes from the bundled Claude program, so
treat it as a guide: your bill and your running total are in the Console.

## Keep the cost down

Whittle has no spending limit of its own. Set one in the Console, then use these to spend
less per turn:

- **Pick a smaller model or a lower effort** for small jobs. See
  {doc}`Models and effort <models>`.
- **Lower Self-check Rounds** (3 by default, from 0 to 10). Each round is more renders and
  more steps.
- **Lower Render Size** (512 by default, from 64 to 1024). Smaller images cost less, but
  Claude sees less detail. You can set these two for every file or for one file; see
  {doc}`Settings <settings>`.
- **Sketch from only the views you need.** Claude checks its work from every view that has
  strokes, so each extra one adds renders. A view you captured and never drew from isn't sent
  once other views have strokes. See {doc}`Sketching <sketching>`.
- **Unpin references you're done with.** A pinned image goes out with every request. See
  {doc}`Reference images <references>`.
- **Keep style guides short.** A guide's text, up to 128 KiB, goes with every request of
  every turn. A changed guide also means the next turn reads everything without the
  [prompt cache](models.md)'s discount. See [Style guides](settings.md#style-guides).
- **Start a new chat for unrelated work.** Each turn carries its chat's conversation, so
  a long chat costs more per turn. See {doc}`Chats <chats>`.
- **Stop a turn that has gone wrong**, rather than letting it finish, or amend it to change
  course. See {doc}`Prompts and targets <prompting>`.
