# Models and effort

Every chat has its own model, which is the Claude that does the work, and its own effort,
which is how much that Claude thinks before it acts. A new chat runs on Opus 5.5 at High.
You can change either one between turns.

## Change a chat's model

1. Wait for the turn to finish. The model button is hidden while a turn runs, and that
   includes a turn where Claude is waiting for your answer: answer it, and the button comes
   back when the turn ends.
2. At the bottom of the Whittle sidebar, click the button beside **Send**. It names the
   chat's model. See {doc}`The sidebar <sidebar>`.
3. Pick a model.

:::{figure} ../images/guides-models/model-button.png
:alt: The bottom of the sidebar: the Ask Claude box with the image button beside it, then Send, a button reading Sonnet 5.5 with a drop-down arrow, and the history button.

The model button, here on Sonnet 5.5.
:::

The change applies from the chat's next turn. The conversation carries on where it was, so
Claude still knows what you and it have done so far. Other chats stay as they are, and each
one's model and effort are stored with it in the `.blend`.

:::{figure} ../images/guides-models/model-menu.png
:alt: The model menu: Opus 5.5, Sonnet 5.5 with a check mark, Haiku 5.5 and Fable 5.1, then Older Models and Other Model, the Effort heading with Low, Medium and High with a check mark, then Use Sonnet 5.5 for New Chats, and a dim line reading Listed by the Models API 1 hour ago.

The model menu. The check marks show the chat's model and effort.
:::

The top of the menu lists the newest model of each family: Opus, Sonnet, Haiku and Fable.
Hover over one to see its full name and id. The dim line at the bottom says where the list
came from:

| The line says | The list is |
|---|---|
| `Listed by the Models API` and an age | what Anthropic's Models API reported for your key |
| `Listed by Claude` and an age | Claude's own list, used when the Models API could not be reached |
| `Built-in list until Claude starts` | the one that came with Whittle, because Whittle has not started Claude yet |

Whittle asks for the list when it starts Claude and remembers it, so a model released after
your copy of Whittle appears by itself. The menu also keeps the models that came with
Whittle, so it can show one your key cannot use. If you pick one of those, the turn fails
with an error; pick another model and press **Retry** on the failed turn.

### Use an older version

**Older Models** has the earlier versions of each family, newest first, in one column per
family.

:::{figure} ../images/guides-models/older-models.png
:alt: The Older Models submenu in four columns. Opus: 5, 4.8, 4.7, 4.6 with a check mark, and 4.5. Sonnet: 5, 4.6 and 4.5. Haiku: 4.5. Fable: 5.

Older Models, with the chat on Opus 4.6.
:::

A chat on an older model shows that model at the very top of the model menu, above the
newest ones.

### Use a model that isn't listed

**Other Model…** opens a dialog for any model id, such as a dated snapshot or the name your
[gateway](api-key.md#use-a-gateway) gives a model. Type the id and click **Use Model**. The
model button then shows what you typed, unless Whittle recognises the id, in which case it
shows the short name.

:::{figure} ../images/guides-models/other-model.png
:alt: The Other Model dialog: a Model ID field holding claude-sonnet-5-5, with Cancel and Use Model buttons.

The dialog starts with the chat's current id.
:::

## Change a chat's effort

Effort is in the same menu, under the models. It applies from the chat's next turn, and the
conversation carries on, as with the model.

| Effort | What it does | Good for |
|---|---|---|
| **Low** | Least thinking. Fastest and cheapest. | Small, clear edits |
| **Medium** | Some thinking. Quicker turns. | Routine edits |
| **High** | The most thinking Whittle offers. This is the default. | Multi-step edits |

Every chat starts at High. There is no preference to change that, so set a lower effort in
each chat that should have one.

To check a chat's settings without opening the menu, click the gear at the right of the
panel's header. The popover lists **Model** with its id and **Effort**. It still shows them
during a turn, when the model button is hidden. See {doc}`The sidebar <sidebar>`.

## Choose the model for new chats

New chats start on **Model for New Chats**, `claude-opus-5-5` unless you change it. There
are two ways to change it:

- **From the model menu.** Put a chat on the model you want, open the menu again and click
  **Use … for New Chats**, for example **Use Sonnet 5.5 for New Chats**. The item shows only
  when the chat's model differs from the current choice.
- **From the preferences.** Open **Edit → Preferences → Add-ons → Whittle**. Click the
  **Model for New Chats** field to pick from the list, or type any model id.

:::{figure} ../images/guides-models/new-chats-preference.png
:alt: The Claude box of Whittle's preferences: the Anthropic API Key field, a Get an API Key button, and the Model for New Chats field holding claude-opus-5-5.

**Model for New Chats** in Whittle's preferences.
:::

This only sets where new chats start. A chat keeps the model its first turn ran on, so
changing the preference later moves only chats that have no turn yet. It does not set
effort.

## Choose by task and cost

Start with the default. Opus 5.5 at High suits multi-step modelling. Move down when the job
is small, or when you find you are paying for more than the job needs.

| You want to | Try |
|---|---|
| Build something new, or make a change with many steps | Opus 5.5 at High |
| Make routine edits to a model that is already there | Sonnet 5.5 at Medium |
| Make small, clear edits, such as moving a part or changing a colour | Haiku 5.5 at Low |
| Attempt the hardest requests, where Opus 5.5 falls short | Fable 5.1 at High |

These are starting points, so judge them on your own work.

Fable is the most capable family and the most expensive per token, followed by Opus, then
Sonnet, then Haiku, which is by far the cheapest. Anthropic's
[pricing page](https://platform.claude.com/docs/en/about-claude/pricing) has the current
prices. A model's price and a turn's cost are not the same thing:

- **Lower effort cuts the thinking you pay for**, so it lowers the cost of a turn without
  changing the model.
- **Older does not mean cheaper.** The newest version of a family often costs the same as
  the one before it or less, so check the pricing page before you switch to save money.
- **Count the whole job.** A cheaper model that needs three more turns to get there can cost
  more than one that gets it right the first time.
- **Settle on a setting.** Anthropic charges less for the part of a conversation it has just
  read, which is called the prompt cache. Changing the model or the effort partway through a
  chat loses that cache, so Claude reads everything again without the discount on the next
  turn. That turn costs more than usual, and more the longer the chat is. A change now and
  then costs little, but changing every turn adds up.

A finished turn's cost is the dim last line of its last tool group, such as
`3 steps · $0.0123`. Open the group, **Used N tools**, to see it. A turn with no tool calls
has no group, so it shows no cost there; {doc}`API key and cost <api-key>` says where to
find it in the transcript. To compare two models on
the same request, change the model and use **Edit & Resend** on the turn: the new branch
runs on the new model, and the old branch stays there to compare with. The model belongs to
the chat, not the branch, so every later turn in the chat uses the new one. See
{doc}`History and branches <history>`.

Self-check rounds and render size also change what a turn costs. See
{doc}`API key and cost <api-key>` and {doc}`Settings <settings>`.
