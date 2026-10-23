# Whittle sidebar

The spec for the Whittle tab in the 3D viewport sidebar (View3D → N → Whittle). It
replaces the panel stack described in `design.md` §5 (status, Sketch, Request, Activity,
History, Development). Everything the old panels could do is still reachable; the
table in §9 says where each feature lives now.

The model is a chat app: one conversation with the turns of the current branch, a
Sketch button whose tools appear while sketching, and a prompt box at the bottom.
History and branching sit on the turns themselves (one ⋯ menu per message, a branch
switcher in a message with siblings) and in a popover for the whole tree, not in a
panel that is always open.

## 1. Principles

1. **One conversation, one prompt.** The panel reads top to bottom as: what Claude is
   working on (the target line), the conversation, the Sketch button, the prompt. No
   section headers apart from the panel's own title.
2. **Nothing until it is relevant.** A control shows only in the state it serves: the
   stroke types only while sketching, the stroke count only once there are strokes,
   Amend and Answer only once there is something to send with them, the start points
   only before anything has been sent, the switcher only on a message with siblings.
   Everything is said once: no busy sign repeated in three places, no draft shown both
   in its field and above it, no list repeated by its heading.
3. **Quiet by default.** Red (`alert`) is used only for real failures: a failed turn's
   one line, a crashed agent, a failed environment setup, a missing or refused API key.
   A first-run setup, a comparison, a question and a tool call the agent recovered from
   are never red. A button is never red; at most the line above it is.
4. **One message, one menu.** Each user message has exactly one ⋯ (Edit & Resend first,
   then go back, compare, ghost, open render, transcript). Older turns have no buttons
   until opened. The full tree is one click away (🕘 beside Send) but never takes space
   in the panel.
5. **Status is ambient.** A running turn shows its progress in the conversation; the
   header icon is an hourglass only while the agent starts or stops outside a turn,
   else a gear; both open the agent popover. A problem the user must act on is one box
   in the panel body, said once.
6. **Bounded height.** Blender panels cannot scroll on their own, so the conversation
   shows the current branch with the last two turns expanded, the three before them
   folded to one line each, and older ones in "N earlier turns".
7. **Text uses the width it has.** Text is wrapped and shortened by measuring it with
   the UI font (`blf`), against the region's real width, and shortened at a word's end.
8. **No ids in the panel.** Node ids (`n0003`) appear only in tooltips.
9. **Developer tools are hidden** unless Preferences → Interface → Developer Extras is
   on (`context.preferences.view.show_developer_ui`).
10. **Draw code stays testable.** Every part is a plain function of `(layout, ...)`
    driven by the panel classes, so the recording-layout tests keep working. Draw
    functions never write to Blender data.

## 2. Structure

```
WHITTLE_PT_main          sidebar panel, category "Whittle", no label of its own
  header (left side)     the current chat's title ▾: popover → WHITTLE_PT_chats (§3.11)
  header (right side)    agent icon: icon-only popover → WHITTLE_PT_agent
  body                   attention box (only when needed)
                         target line (+ manual targets when Auto is off)
                         comparison bar (only while comparing)
                         start row (only before anything is sent)
                         conversation
                         sketch (button, tools while sketching, stroke count)
                         composer (reference chips, prompt, Send/Stop, model ▾, 🕘)
WHITTLE_PT_debug         "Development"  child of main, DEFAULT_CLOSED,
                         poll: Developer Extras on

Popovers (bl_space_type VIEW_3D, bl_region_type HEADER, so they never show up as
sidebar panels of their own):
  WHITTLE_PT_agent       agent state (and why it stopped), model, session folder,
                         Start/Stop Agent, Preferences
  WHITTLE_PT_history     the whole tree; bl_ui_units_x = 24
  WHITTLE_PT_chats       New Chat, the chats in this file, rename and delete;
                         bl_ui_units_x = 18
  WHITTLE_PT_targets     target collection, Replace With Selection, Clear
  WHITTLE_PT_type_prompt the Shift+Alt+C popup: the composer's field, one line,
                         already in edit mode (§3.12); bl_ui_units_x = 20

Menus:
  whittle.turn_menu      per-message ⋯ menu: an operator (node property) whose invoke
                         opens WindowManager.popup_menu
  whittle.ref_menu       per-reference ⋯ menu, the same way (index property)
  WHITTLE_MT_stop        Stop ▾: keep or undo the running turn
  WHITTLE_MT_start_primitive   the primitives, then the Asset Browser hint
  WHITTLE_MT_models      the model menu from the composer's model button (§3.13)
  WHITTLE_MT_models_older      its Older Models submenu
```

The ⋯ buttons are operators whose `invoke` calls `context.window_manager.popup_menu`
with a draw function closed over the id: a Menu class cannot take an argument, and an
operator's property travels with the button.

Widths: `make_ctx` takes the region's width less `ui.REGION_MARGIN` (58 px at scale 1:
the tab strip and the panel's margins) as the room a top-level label's text has; a box
takes `BOX_PAD` more, an icon `ICON_PX`. Everything must look right at the default
sidebar width (280 px) and at 448 px (the harness's wide variant).

## 3. The parts

### 3.1 Header

```
 ▾ Crate lid and handles ▾              ⚙
```

The left side is the chat title (§3.11); the panel has no `bl_label`, so the title
takes its place, and `bl_options` has `HEADER_LAYOUT_EXPAND` so it gets the header's
width. The right side is the agent icon.

`WHITTLE_PT_main.draw_header_preset` draws one unembossed, icon-only popover button for
`WHITTLE_PT_agent`: `SORTTIME` while the agent is starting, busy or stopping and no turn
is running (a turn shows its own progress), otherwise `PREFERENCES`. Problems are not
repeated here: the attention box has them.

`WHITTLE_PT_agent` shows:

```
 Agent: ready
   ·the agent exited with code 3·    (dim, only when crashed or failed)
 Model: Opus 5.5 (claude-opus-5-5)   the current chat's (§3.13)
 Effort: High                       the current chat's (§3.13)
 Chats: in crate.blend              (FILE_BLEND)
 [ Stop Agent ]                     (or [ Start Agent ])
 [ Preferences… ]
```

The chats line names the file that stores the chats (§3.11); their working copy is a
hidden cache in Whittle's user folder, never beside the file. For an unsaved file it
reads `Chats: unsaved file` with `ERROR` and a dim line `Saving the file stores its
chats in it.`

### 3.2 Attention box

Drawn at the top of the body, only in these cases (at most one; the order is the
priority). Only the lines marked red are `alert`; the box and its button never are.

| Case | Text | Button |
|---|---|---|
| setup running | `Setting up Claude: <progress>` (`SORTTIME`) | `Cancel` |
| environment missing or broken | `Set up Claude to start` (`INFO`); a specific reason, dim; after a failed setup `Last setup failed: …` in red | `Set Up…` (`whittle.venv_install`, INVOKE_DEFAULT keeps its confirmation) |
| no API key | `Add an API key to start` (`INFO`); dim: `Whittle runs Claude with your own Anthropic API key, billed to your Console account.` | `Preferences…` and `Get a Key` (`wm.url_open`, the Console's API keys page) |
| crashed | `Claude stopped unexpectedly` (red, `ERROR`) | `Restart and Retry` (`whittle.retry` on the turn it ended, which restarts the agent) or `Restart` (`whittle.agent_start`) when no turn can be retried |
| failed to start | `Claude could not start` (red) | the same |
| key refused | `The API key was refused` (red) | `Preferences…` and `Get a Key` |

The crash reason (`exited with code 3`) is in the agent popover. When the box offers
Restart and Retry, the turn the crash ended shows a dim `Interrupted` (`PAUSE`) instead of its own failure line and Retry, so the crash is reported once.
While the box is shown, the conversation's notes from outside any turn (a run that did
not start) are left out: the box says why.

While the environment needs setting up, Send is disabled.

"No API key": a start found no key (the agent's `needs_key` state, architecture §2
Authentication) and none has been added since; Send stays enabled and tries again.
"Key refused": a turn or start error whose message is the CLI's authentication
failure (invalid API key, HTTP 401, not logged in) sets `key_problem` on the
controller. The turn itself still ends as failed in the conversation.

### 3.3 Target line

One row:

```
 ▣ Crate, Crate_Lid              [Auto]
```

- Label with `OBJECT_DATA`: `targets.describe`, shortened to the row (`Crate, Crate_Lid`,
  `Crate + 2 more`, `New objects in Whittle Target`). With nothing to target it says
  what will happen, dim, over two lines if it must: `Nothing selected: Claude adds new
  objects` (`No targets: …` with Auto off). With Auto off the line only counts the
  targets (`2 targets`): the rows below list them.
- While a turn runs the icon is `LOCKED`, the label shows the turn's targets, and Auto
  is drawn inactive (dim): the target cannot change mid-turn.
- `[Auto]`: `prop(scene.whittle, "target_auto", toggle=True)`, text `Auto`; its tooltip
  starts `Follow the selection`.

**Auto on**: the target list follows the focus. Whenever the selection or active object
changes in Object Mode, a handler (`depsgraph_update_post` plus a msgbus subscription on
the view layer's active object) rewrites `scene.whittle.targets` to:

1. the eligible selected objects (`targets.eligible`: never the sketch, a ghost, a
   helper, a camera or light), active object first; or, when none is selected,
2. the active object if it is eligible; or
3. nothing ("new objects").

The target collection is untouched by Auto and is still included. Auto does not sync
in other modes (Grease Pencil draw mode on the sketch, Edit Mode), during a turn, or
while comparing. Whenever Whittle itself changes the target list (a turn finishing or
kept partial adds the created objects, Restore, Branch, branch switch, Compare → End,
a start point), it also selects exactly those objects, so the next sync agrees with the
history. Turning Auto on syncs at once.

**Auto off**: the picked objects as plain rows, then one button:

```
 ▣ 2 targets                      (Auto)
 ▣ Crate                           ✕
 ▣ Crate_Lid                       ✕
 ▤ Whittle Target (2)                     only with a collection
 [ + Add Barrel                  ] [⋯]
```

- One row per target: a label (`OBJECT_DATA`, the object's name) and `X` →
  `whittle.target_remove`. A label, not the object's ID field, which would add a
  second ✕ of its own.
- `whittle.target_add` names what it adds: `Add Barrel` for one selected object that is
  not a target yet, `Add 2 Selected` for several; disabled `Add Selected` when there is
  nothing new selected. So the selection and the targets read apart.
- `⋯` → `WHITTLE_PT_targets`: the collection field (`target_collection`), `Replace With
  Selection` (`whittle.target_from_selection`), `Clear` (`whittle.target_clear`).

### 3.4 Comparison bar

Only while a comparison is active, under the target line, two rows in a box (not
alert):

```
 ┌──────────────────────────────────┐
 │ ⇄ Showing: Add a lid             │
 │ [  Swap  ][Keep This ][  Done  ] │
 └──────────────────────────────────┘
```

`Showing: the current scene` or `Showing: <prompt>` without its final period
(`Showing: Start: Crate` for the start), no node id; then text buttons, aligned: `Swap`
(`whittle.compare_toggle`), `Keep This` (`whittle.compare_end keep=True`, only while the
compared turn is shown: keeping the current scene is just Done) and `Done`
(`whittle.compare_end keep=False`). Icons do not fit beside the text at the default
width, and alone they did not say what they do. Their tooltips say what each does and
that saving the file meanwhile saves what is shown. The compared turn's bubble, when it
is in the conversation, carries an `ARROW_LEFTRIGHT` mark beside its ⋯. Send is disabled while
comparing; `whittle.submit`'s poll message (`End the comparison to send`) is the
disabled button's tooltip. No line in the composer.

### 3.5 Start row

```
 ·Start from·
 [Selection][Blank][Primitive ▾]
```

A dim `Start from` line, so the three read as ways to begin, then one
`row(align=True)`, text only: `whittle.start_existing` (`Selection`), `whittle.start_blank`
(`Blank`), `menu WHITTLE_MT_start_primitive` (`Primitive`). The label does not fit beside
the buttons at the default width, so it is a line of its own. The Asset Browser hint (`Or right-click an asset in the Asset Browser`) is the
last, dim line of the Primitive menu.

Shown when `start.can_start(...)` allows a start and nothing has been sent in this
session (no turn at all in the conversation, a folded one included), unless the user
is plainly on their way: sketching, or a prompt typed with a target picked. After a
first turn that failed and folded away, the panel stays on that turn and its Retry;
the history popover offers the start row instead (§3.10).

A start taken before the first turn shows as a dim `Start: Blank` line. With turns, the
start is in the history popover only.

The start operators' options (a primitive's size…) stay in Blender's
Adjust Last Operation panel. Typing a prompt and pressing Send also works, with the
scene as it is.

### 3.6 Conversation

The conversation is the path from the root to the current node (`tree.path(current)`,
folded nodes excluded), followed by the running turn if there is one. Its content comes
from the live stream for turns of this Blender session and from
`nodes/<id>/transcript.jsonl` for older ones (read once per node and cached, so a
reopened file shows the same conversation). The start is not a line of the
conversation.

**An expanded turn** (the last two turns of the path, the running turn, a folded
failure):

```
 ┌──────────────────────────────────┐
 │ Add a lid that overhangs a little│   user bubble: box, full width
 │ and carve a handle slot.        ⋯│   ⋯ on the last line
 │ ✎ 3 strokes · 2 views · 1 ref   │   dim, only if any (then ⋯ is here)
 └──────────────────────────────────┘
 Adding a lid that overhangs by 1 cm,
 then checking from both views.
 ▸ Used 4 tools                         layout.panel, closed
 The lid sits flush now.
 [ thumbnail ]                          last render of the turn
```

- **User bubble**: `layout.box()`. The prompt wrapped at the box's full width, at most 4
  lines (the last shortened with `…`); `(sketch only)` without a prompt. If the request
  had strokes, views or references, one dim line with `GREASEPENCIL`: `3 strokes · 2
  views · 1 ref`. The last line is a `split` whose right part holds the `THREE_DOTS` →
  `whittle.turn_menu` button, after the branch switcher (§3.7) when the turn has
  siblings; if that line is too long to share, its last word moves down a line. The ⋯
  of the running turn is disabled until it ends.
- **Claude's text**: each assistant text entry, wrapped, no prefix, no icon, always in
  full (an earlier "More" fold after 8 lines interrupted replies mid-list). That
  includes Claude's short notes between tool calls, which Opus 5.5 sends as narration
  thinking blocks (`architecture.md` §5): they are ordinary text between tool groups,
  not part of a group, so a turn reads as a few lines of intent and progress with the
  tool calls folded between them.
- **Markdown** in Claude's text (and in its questions) is rendered, not shown raw
  (`whittle/markdown.py`, drawn by `ui.draw_markdown`). A label has one font, so the
  styling lives in the text and the markers go:
  - **Inline**: bold and italic become Unicode's sans-serif bold and italic letters,
    inline code (and `<code>`, `<kbd>`) its monospace letters (`𝚖𝚎𝚜𝚑_𝚛𝚎𝚙𝚘𝚛𝚝`), all of
    which Blender's fallback fonts draw. Letters without a styled form (é, ß) stay
    regular, and `snake_case` stays as it is. Struck text (`~~`, `<s>`, `<del>`) gets a
    hair space and U+20EA (a stroke overlay) between its letters: Blender has U+0336
    only in its monospace font, which is not a fallback, and lifts a combining mark
    that follows a letter above it, but leaves one after a space where the font puts
    it, so the overlays join into a line through the text. Backslash escapes of any
    ASCII punctuation are read first, as CommonMark does, so `` \` `` is a backtick,
    not a code span. Known limit: inline code has no background chip, and only
    letters and digits have monospace forms, so its punctuation (`(`, `_`) stays in
    the proportional font.
  - **Headings** by level (a label has one size, so level shows in rules and dimming):
    H1 bold in a taller row over a double line, H2 bold over a line, H3 and H4 bold,
    H5 bold and dim, H6 italic and dim; a gap before each.
  - **Lists** hang beside a bullet (`•`, `◦`, `▪` by depth), their number or a task box
    (`☐`, `🗹`) in a margin. `☑` is not used: Blender draws it from its emoji font, half
    as wide again as `☐`, and the margin cuts it.
  - **Quotes** are dim and indented one step per level, with a dim bar (`▏`) in the
    margin of each level on every row, so three-deep quotes show three bars, gaps
    and code boxes included; what is inside them (lists, nested quotes, code) is laid
    out like anything else.
  - **Code**: fenced blocks and indented ones (four spaces after a blank line, outside
    a list) sit in one box in monospace letters, their spaces en spaces (a plain space
    is half as wide as those letters) so indentation lines up; unwrapped but broken
    where too wide. The box's first row is the fence's language, dim (`python`; empty
    for an indented block), and an unembossed `COPYDOWN` button (`whittle.copy_code`)
    that copies the block, as written, to the clipboard.
  - **Tables** are a box of columns (nested splits), each as wide as its text, shared
    out when that is wider than the panel (a column narrower than its share keeps its
    width); cells wrap in their column. The header row is bold above a line, a lighter
    line separates rows, and each column is aligned as its `:---:` row says.
  - **Maths**: `$…$` (not before a digit, so prices stay) and `$$…$$` / `\[…\]` blocks
    become Unicode, best effort: Greek letters, operators and relations as symbols,
    `\,` a thin space and `\:` `\;` a medium one (U+2009, U+2005; the source's spaces
    beside them go, as TeX ignores them),
    `^`/`_` as superscript and subscript letters (in brackets when one has no such
    form), `\frac{a}{b}` as `a⁄b`, `\sqrt` as `√`; unknown commands lose their
    backslash. A block is a centred line.
  - **HTML**: `<details><summary>S</summary>…</details>` is a closed sub-panel headed
    S with its body laid out inside; `<b>`/`<strong>`, `<i>`/`<em>`, `<code>`/`<kbd>`,
    `<s>`, `<sup>`/`<sub>` and `<br>` map to the styles above; other HTML tags go and
    their text stays (`List<String>` is not a tag); entities are decoded.
  - **Links** show their text underlined: U+0332 is only in the monospace font, but
    Inter has U+035F (a double macron below), and one after each letter of the link
    joins into a line under it. A line with a link ends in an unembossed `URL` button
    (`whittle.open_link`, whose tooltip names the link's text and address); a line
    with several opens a menu of them instead (`whittle.link_menu`: each link's text
    and site, `the docs · docs.blender.org`). The line wraps leaving room for the
    button. Bare `https://` and `www.` addresses are links too; like GFM, a bare
    address keeps a closing parenthesis that closes one in it
    (`https://en.wikipedia.org/wiki/Foo_(bar)`), and so does a link's address.
  - **Footnotes**: a reference is a superscript number (in the order they are first
    referred to) and the notes come at the end, dim, after a line, their number in the
    margin.
  - **Emoji**: Blender 5.2 ships Noto Emoji (monochrome), so emoji draw as outline
    glyphs (🎲 a die, 🧊 a cube). What would be a box goes: variation selectors, skin
    tones and keycap frames are dropped, a joined emoji (a family) is its first part,
    and the few emoji no bundled font has are left out.
  - A rule is a line and a blank line a small gap. A source line break stays a line
    break; so do two trailing spaces, a trailing backslash and `<br>`.
- **Tool groups**: consecutive tool calls (and thinking) between two texts collapse into
  one `layout.panel(f"whittle_tools_{node}_{n}", default_closed=True)`, header `Used 4
  tools` (`Thought, used 4 tools` with thinking), icon `TOOL_SETTINGS`; while a call in
  it is in flight, the header is that call (`exec · carve handle slots`) with
  `SORTTIME`, or `Running 2 tools` when several are in flight. Expanded, each call is its own nested `layout.panel`, header `exec · add
  lid` with `CHECKMARK` / `CANCEL` / `SORTTIME`, body the code and result
  (`stream.tool_detail`), and each render's thumbnail with an `IMAGE_DATA` button
  (`whittle.open_image`). The last group of a finished turn ends with a dim `4 steps ·
  $0.0021`. Failed calls are never `alert`. While Claude asks, the in-flight `ask` call
  is left out: the question block says it.
- **Turn thumbnail**: the turn's last render (or the node's `thumb.png`),
  `template_icon` without a button (Open Render is in ⋯). Its scale grows with the
  sidebar: `width / 20 × 0.36`, between 4 and 8. Only on expanded turns.
- **Notes**: `note` entries (context notes, an amendment delivered, the session
  restarted) are one dim line with `INFO`. (There is no warning when the user edits
  the target during a turn; see decisions.md.) The interrupt record (`Stopping: keeping the changes`) has its own kind, `stopping`, and
  is not drawn: the running turn's phase line and the stopped turn's end line say it.
- **Amendments and answers** appear in the turn as small user bubbles (box) prefixed
  `Amend:` / `Answer:`.
- **Turn end**, after the thumbnail: a finished turn has none. An interrupted turn ends
  with a dim `Stopped, changes kept` or `Stopped, changes undone` (`PAUSE`). A failed
  turn ends with its reason in red with `CANCEL` (`Claude stopped with an error`;
  `Failed` when there is none), at most 2 lines, and, if it is the last turn, `Retry` at
  the right of its first line
  (`whittle.retry`: a recorded failure is branched then sent; a folded one never left
  its parent, so its prompt goes back in the box if it is empty and its pending strokes
  and references are sent as they are).
- **A failed turn that changed nothing** is folded in the tree (never current). It still
  shows after its parent while it is the latest thing that happened in this Blender
  session, with its failure and `Retry`; it disappears at the next send or when Blender
  restarts. Its prompt does not go back into the prompt box (the bubble shows it, and
  Retry or ⋯ → Edit & Resend bring it back).

**A collapsed turn** (older turns of the path): one
`layout.panel(f"whittle_turn_{node}", default_closed=True)` whose header is the prompt
shortened to one line at a word's end, with the status icon when it is not `complete`
(`PAUSE`, `CANCEL`). No buttons. Opened, its body is the expanded turn, bubble and ⋯
included. Because the panel id is first seen when the turn becomes old, it always
starts closed.

**Folding further**: when more than 3 turns are collapsed, the oldest go into one
`layout.panel("whittle_earlier", default_closed=True)` headed `N earlier turns`.

**Not at the end of the branch**: when the current node has children (after going back,
or after Edit & Resend), the conversation ends at the current node and is followed by
one row:

```
 ·1 later turn·           [↻ Return to Latest]
```

`Return to Latest` restores the newest leaf under the current node (`whittle.branch_switch` with
`node=<that leaf>`). Send reads `Send as Branch` (§3.9).

**The running turn**: drawn expanded, after the path. Under its last entry, the phase,
dim, `SORTTIME`:

| Phase | Line |
|---|---|
| starting the agent or the session | `Starting Claude…` |
| running | `Working…`, only while no tool call is in flight (one in flight shows its hourglass in the group header, which says it) |
| waiting for the user | the question block (§4.4) |
| interrupting | `Stopping…` |

**Empty**: a session with nothing sent shows no conversation at all.

### 3.7 Branch switcher

In the last row of a user bubble whose node has non-folded siblings, left of its ⋯, as
chat apps do: `TRIA_LEFT`, dim `1/2`, `TRIA_RIGHT`, unembossed. An arrow that leads
nowhere now (no sibling on that side, or not `operators.can_switch`) is a dim icon
label in its place, so the list's end shows and the count does not move (a disabled
unembossed button would draw nothing). The arrows are `whittle.branch_switch` with `node` set to the
previous / next sibling: it restores the newest leaf under that sibling (the sibling
itself if it is a leaf), as one undo step `Whittle: switch to <node>`, exactly like
Restore. Siblings are ordered by creation.

### 3.8 Sketch

Between the conversation and the composer, after a `layout.separator()`.

Not sketching:

```
 [✎ Sketch]
```

`whittle.sketch`, text `Sketch`, left-aligned.

While sketching, two rows packed to the left:

```
 [✎ Sketch][📷 Capture View]
 [〰][+][−][⌇][▭][≡] ·Carve·
```

The Sketch button stays where it was, pressed, with Capture View beside it; the stroke
types are a `row(align=True)` of their own, then the active type's name (dim):

| Button | Operator | Icon | Notes |
|---|---|---|---|
| Sketch (stop) | `whittle.sketch_stop` | `GREASEPENCIL` | text `Sketch`, `depress=True` |
| Free | `whittle.stroke_type type=free` | `STROKE` | `depress` = active type |
| Add | `… type=add` | `ADD` | |
| Carve | `… type=carve` | `REMOVE` | |
| Crease | `… type=crease` | `MOD_BEVEL` | |
| Region | `… type=region` | `SELECT_SET` | a dashed box: an area, not a solid |
| Note | `… type=note` | `TEXT` | a text page: words, not a letter |
| Capture View | `whittle.capture_view` | `CAMERA_DATA` | text `Capture View` |

`whittle.stroke_type`'s `description` names each type and its meaning (`Carve: remove
material here`).

**Stroke count**, only when there is something to count: outside a turn, the pending
strokes, the strokes an earlier turn was sent with that are still shown (a stopped or
failed sketch turn keeps them), and the stored views (`3 strokes · 2 views`, `1 stroke
sent · 1 view`, `1 view`), so Clear and the view list are in reach whenever the
viewport shows something; during a turn, the strokes it was sent with and those
drawn since (`3 sent · 1 new`), left out when both are zero. It is the header of
`layout.panel_prop(window_manager, "whittle_show_views")` (closed by default; a
window-manager property rather than a layout panel's own state, so it can be read and
set from Python, and is never saved), with a `TRASH` button (`whittle.clear_sketch`) at
its right. Opened, it lists `View 2 · 1 stroke` rows with an `X`
(`whittle.view_remove`); the current view (where new strokes go) has `VIEW_CAMERA` and a
dim `current` tag when the row has room, the others `CAMERA_DATA`. None is dimmed: dim
reads as disabled. Each row's text is an unembossed `whittle.view_snap` button, packed
left so it reads as the label it is: clicking it moves the viewport back to that view,
which becomes the current one. Under the rows, the checkbox **Markers While Sketching**
(`WindowManager.whittle_show_view_markers`, on by default, never saved).

**View markers**: while sketching, the viewport shows a small camera at each view's eye,
pointing the way it looked (a frustum, or a box for an orthographic view), at a constant
size on screen; the current view's is orange, the others light grey, and the one the
viewport is at is hidden. Hovering one highlights it white; clicking it snaps the
viewport back to that view, as its row does. The viewport's Gizmos overlay hides them
too.

**Keys** (add-on items in the 3D View keymap, so they work over the viewport in every
mode, Draw Mode included; listed and rebindable in Preferences → Keymap under 3D View →
3D View (Global), and meant for a tablet's express keys):

| Key | Operator | Does |
|---|---|---|
| Shift+Alt+D | `whittle.sketch_toggle` | Toggle Sketch Mode: starts sketching, or stops |
| Shift+Alt+N | `whittle.next_stroke_type` | the next stroke type (free → add → carve → crease → region → note) |
| Shift+Alt+V | `whittle.capture_view` | Capture View |
| Shift+Alt+Enter | `whittle.submit` | Send |

### 3.9 Composer

```
 [▧ crate_front.png][📌]                   reference chips, packed into rows
 [▧ crate_side.png]
 [Match the proportions in the ][📎]
 [reference photos.            ]
 [       ▶ Send       ][Opus 5.5 ▾][🕘]
```

- **References**: attachment chips right above the prompt field, packed into as few
  rows as fit the width. A chip is one `whittle.ref_menu` button (§5) with the file name
  and its preview as the icon, sized to its text; clicking it opens the menu with pin,
  place, open and remove. A pinned chip carries a pressed `PINNED` button
  (`whittle.ref_pin`) beside it that unpins it. No path field.
- **The draft shows once**, in its box. The box is multi-line and wraps, so a long
  prompt can be read and edited in place; there is no wrapped copy elsewhere.
- **Prompt row**: `textbox(props, "prompt", initial_visible_lines=3,
  placeholder="Ask Claude…")` (Blender 5.2's multi-line text box; it scrolls past its
  height and can be resized by dragging its corner), then 📎: `whittle.ref_add`, icon
  `FILE_IMAGE`, icon only. Amending and answering use the same box.
- **Enter sends, Shift+Enter adds a line**, as in the Claude apps. The box itself ends
  editing on Enter (and on a click elsewhere) and adds a line on Shift+Enter; it has no
  hook for Enter, so `whittle.enter_send` sits on the release of Enter in the Window
  keymap and sends the field confirmed just before it (`addon/enter.py`): Send for the
  prompt, Amend while a turn runs, Answer while Claude asks. A click away never sends,
  blank text never sends, and when sending is not possible (a comparison) the text stays.
- **Shift+Alt+C** types into this field from anywhere without the mouse (§3.12); the
  field's tooltip says so.
- **Button row** (`scale_y=1.4`): `whittle.submit` with icon `PLAY`, text `Send`, or
  `Send as Branch` when the current node is not at the end of its branch; then the
  model button (§3.13), `menu("WHITTLE_MT_models", text=<short name>)` (`Opus 5.5`,
  or the id itself for one Whittle cannot read), sized to its text; then the
  history popover (`popover("WHITTLE_PT_history", text="", icon="RECOVER_LAST")`, a
  clock with a back arrow, in a fixed-width part of a `split` so the icon is never
  squeezed; tooltip from the panel's `bl_description`, starting `History`). Send is
  enabled when there is a prompt, a pending stroke or a reference, no comparison and no
  setup needed. Pressing Send clears the prompt once the turn is accepted (the text is
  in the user bubble); a run that never starts puts it back.

**While a turn runs**:

```
 [Ask Claude…                    ][📎]
 [ + Amend ][ ✕ Stop ▾ ]         [🕘]     Amend only with text or new strokes
```

- The model button is not shown: the model changes between turns.
- The field is `amend_text`, with the same placeholder as between turns (`Ask Claude…`).
- `Amend` (`whittle.amend`, `ADD`) shows only when there is amend text or a stroke
  drawn since Send, disabled while interrupting (`ctl.can_amend`). Without it, Stop
  takes the row.
- `Stop ▾` is `menu("WHITTLE_MT_stop", text="Stop", icon="CANCEL")`: `Stop and Keep
  Changes` (`whittle.interrupt mode=KEEP`, `PAUSE`) and `Stop and Undo This Turn`
  (`mode=RESTORE`, `LOOP_BACK`).
- References can still be added: they go with the next request.

**While Claude asks**: the question is in the conversation (§4.4); the field is
`ask_answer`, with the same placeholder, `Ask Claude…`: there is one placeholder in
every state, and the question right above says what the text answers. `Answer` (`whittle.answer`) shows once
an answer is typed; `Amend` shows when strokes were drawn since Send (a typed
amendment waits for the answer, since the field is the answer's); Stop stays.

### 3.10 History popover

`WHITTLE_PT_history`, opened by 🕘. Width 24 units, so a turn's title is rarely cut;
Blender scrolls a popover that is taller than the window.

```
 History                          [Hide Ghost]   only while a ghost is shown
 ┌ comparison bar, if comparing ┐
 ·Start from·                                     only before any turn is kept
 [Selection][Blank][Primitive ▾]
 [▣] Start: Crate                           ⋯
 [▣] add a lid               ·2 branches·   ⋯
 ↳ [▣] carve a slot                         ⋯
   [▣] sand the edges                       ⋯
 ↳ [▣] add rope handles                     ⋯   the current row is highlighted
 [≡ Open Transcript]
```

- One row per non-folded node from `tree.walk()`: indentation, the node thumbnail
  (`template_icon`, scale 1.5), the title, then `THREE_DOTS` → `whittle.turn_menu` (the
  same menu as in the conversation).
- **The title is the Restore button**: `whittle.history_restore` with the node's label
  (`Start: <start label>` for the root) and its status icon when not complete, in a
  left-aligned row with `emboss = "PULLDOWN_MENU"`, so it reads like a menu item and
  lights up under the pointer; the current node's is drawn `depress=True`, highlighted.
  Disabled per `operators.can_restore`. The node id is in its tooltip (`n0003 · add rope
  handles`).
- **Indentation is a function of the node's branch level only** (`ui.branch_levels`): a
  node whose parent has one child continues its parent's line at the same level; the
  children of a branch point are one level in, all of them, so siblings line up. A
  long session without branches stays flat. The first row of each branch has a
  dim `↳` mark (`ui.BRANCH_MARK`, text, not a disclosure triangle, which looked
  collapsible) and the row a branch leaves from says so at its right, dim (`2
  branches`). Each level is one unit, the same step at every level, and levels past 4
  do not step further, so titles keep their room. A title cut short has its full text
  in the tooltip.
- The indentation, marker and thumbnail are a fixed-width first part of a `split`, the
  title the rest; the indentation is a sub-row with `ui_units_x`, never a separator (in
  a row a separator is as tall as it is wide).
- Footer: `whittle.open_transcript` (`TEXT`).
- Ghost is shown from the current turn's ⋯ menu; the header has `Hide Ghost` only while
  one is shown.

### 3.11 Chats

`architecture.md` §14 has the data model and the storage.

A file holds any number of chats. Each chat is one conversation with its own history
tree and its own Claude session; the panel always shows exactly one, the current
chat. As in Claude Design, the chats live in a menu under the title: the panel never
lists them.

**Title button** (panel header, left, `ui.draw_chat_title`): `layout.popover(
"WHITTLE_PT_chats", text=<title>)` in a left-aligned row, which Blender draws as a
dropdown with its own chevron. The title is shortened to the header's width at a
word's end (`…`), measured like every other text (§1.7), leaving `HEADER_RESERVE`
(3.6 units) for the collapse arrow, the button's chevron and the agent icon. Before the first turn
the title is `New chat`. Tooltip: `Chats: start a new chat or go back to an earlier
one`.

**Titles** come from the chat's first prompt, as in the Claude apps: its first
non-empty line without its closing full stop, cut at a word's end to 40 characters with `…`; a first turn without a
prompt is `Sketch of Crate` (its first target), or `Sketch` with no target. The title
is set when the first turn is sent and never changes by itself after that (an Edit &
Resend of the first turn keeps it). **Rename This Chat…** sets one by hand; clearing
the field goes back to the automatic title.

**The chat menu** (`WHITTLE_PT_chats`, 18 units wide):

```
 [+ New Chat                          ]
 ·Conversations·
 [Crate lid and handles             ] ✓   current: highlighted, check mark
 ·  12 turns · 2 hours ago · 1.9 MB·
 [Barrel with metal bands           ] 🗑
 ·  4 turns · yesterday · 0.6 MB·
 [Lamp post                         ] 🗑
 ·  9 turns · over a week ago · 2.4 MB·
 ───────────────────────────────────────
 ·3 chats · 4.9 MB in this file·
 [✎ Rename This Chat…                 ]
 [🗑 Delete This Chat…                 ]
 [🗑 Delete Other Chats…               ]
```

- **New Chat** (`whittle.chat_new`, `ADD`), first and full width. It starts an empty
  chat and makes it current: an empty conversation (§4.1, with the start row), a
  fresh Claude session and a history of its own whose start node is the scene as it
  is when the chat's first turn is sent (or a start point is taken). The scene is not
  touched. Disabled, with the reason as its tooltip (`poll_message_set`): while a turn
  runs or Claude asks (`Wait for the turn to end, or stop it`), while comparing (`End
  the comparison first`), and when the current chat has no turns yet (`This chat is
  new already`).
- **Conversations**, a dim label, then one entry per chat, most recently active first.
  An entry is two rows: the title as a `whittle.chat_switch` button (`chat` property),
  left-aligned with `emboss = "PULLDOWN_MENU"` like the history popover's titles,
  not pressed (the check mark alone marks the current chat); at its right, in a fixed-width part of a
  `split`, a `CHECKMARK` label on the current chat and an unembossed `TRASH` button
  (`whittle.chat_delete`, `chat` property) on the others. The second row is dim and
  indented: `12 turns · 2 hours ago · 1.9 MB`.
  - **Turns** counts every turn of the chat's tree on every branch, folded failures
    not included (`1 turn`, `12 turns`).
  - **Age** is from the end of the chat's last turn (its creation for a chat without
    one): `just now` (under a minute), `5 minutes ago`, `2 hours ago`, `yesterday`, `3
    days ago`, `over a week ago`, `over a month ago`, `over a year ago`
    (`chats.age_label`).
  - **Size** is what the chat adds to the saved `.blend` (its packed size, §14 of the
    architecture), one decimal in MB, `0.1 MB` at least, so bloat is visible. It is
    measured when a turn ends and when the file is saved, never in draw code.
  - Switching is disabled, with the same tooltips as New Chat, while a turn runs or
    Claude asks and while comparing. The current chat's title button does nothing.
    Its tooltip names the chat: `Barrel with metal bands · 4 turns`. The trash icons
    stay enabled during a turn: only the chat a turn runs in has to wait.
- At most 20 entries; with more, a last row `Show 23 More` (`TRIA_DOWN`, toggling
  `WindowManager.whittle_show_all_chats`, `SKIP_SAVE`) lists them all (Blender
  scrolls a popover taller than the window).
- **Footer**, after a separator: a dim total, `3 chats · 4.9 MB in this file` (`1
  chat · …`; for an unsaved file `… when saved`), then three left-aligned
  `PULLDOWN_MENU` items: `Rename This Chat…` (`whittle.chat_rename`, `GREASEPENCIL`)
  and `Delete This Chat…` (`whittle.chat_delete` with the current chat, `TRASH`;
  disabled while a turn runs, Claude asks or a comparison shows), both only once the
  chat has a turn (an empty chat goes by itself when another becomes current), and
  `Delete Other Chats…` (`whittle.chat_delete_many`, `TRASH`; only with other chats).
  When all are listed, the last row reads `Show Fewer` (`TRIA_UP`).
- A chat with no turns is not listed unless it is current, and is dropped when
  another chat becomes current: New Chat repeated never leaves empty chats behind.

**Switching** (`whittle.chat_switch`) leaves the scene exactly as it is: it changes
which conversation the panel shows and which Claude session the next turn continues.
The chosen chat's history tree is all there, so ⋯ → Go Back to This Turn, the branch
switcher and the 🕘 popover go back to any of its turns by hand. Pending strokes, the
prompt box, references and the target list stay as they are (they belong to the
scene, not to a chat). A ghost is hidden. Until the next Send, the end of the
conversation has one dim line with `INFO`:

```
 ·ⓘ The scene is as you left it; Claude·
 ·  will look at it before editing.·
```

and the next turn's context tells Claude the same (architecture §14). The conversation
ends at the chat's current node as usual; when that node has children, "N later
turns" with Return to Latest shows as always.

**Deleting a chat** (`whittle.chat_delete`) always asks first,
`invoke_confirm(title='Delete "<title>"?', message=…, confirm_text="Delete",
icon="WARNING")`, with the message `4 turns, 0.6 MB. It leaves this file the next time
you save.` (Blender does not wrap that message, so it stays short; the scene is never
changed by a delete.) Deleting removes
the chat's history, transcripts, renders and Claude session at once from the cache
folder, and from the `.blend` at the next save. Deleting the current chat makes the
most recently active remaining chat current (as a switch: the scene stays), or an
empty new chat when none is left. The chat a turn is running in cannot be deleted.

**Delete Other Chats…** (`whittle.chat_delete_many`) is a dialog
(`invoke_props_dialog`, title `Delete Chats`, confirm `Delete`):

```
 Delete Chats
 Which  [Older Than a Month         ▾]
 ·Deletes 7 chats, 18.2 MB. This chat stays.·
 ·They leave this file the next time you save.·
                                 [ Delete ]
```

`which`: `All Other Chats`, `Older Than a Week`, `Older Than a Month` (the default),
`Older Than 3 Months` (91 days), by the same age as the menu. The count line follows
the choice; with nothing to delete it reads `No chat is that old.` and Delete does
nothing. The current chat is never included.

**Rename This Chat…** (`whittle.chat_rename`) is a props dialog (`Rename Chat`, confirm
`Rename`) with the title field, filled with the current title.

**A chat made on another machine** (someone else's file, or the user's own from
another computer; architecture §14) shows read-only until continued: its conversation
and history as usual, and above the sketch row a small box (`ui.draw_foreign`):

```
 ┌──────────────────────────────────┐
 │ ? Continue this chat?            │
 │   ·It was made on another machine.·│
 │ [         ✓ Continue           ] │
 └──────────────────────────────────┘
 [✎ Sketch]
 [Make the handles thicker.      ][📎]
 [ ·▶ Send· ]           [Opus 5.5 ▾][🕘]   disabled
```

Send is disabled, its tooltip `This chat was made on another machine: Continue it to
send, or start a New Chat`; Enter and Shift+Alt+C leave the text in the box. The draft,
sketch and references can still be prepared. **Continue** (`whittle.chat_continue`,
`CHECKMARK`; tooltip: its whole conversation goes to Claude with the next turn, so only
for files you trust) marks the chat as continued here, for good: the box goes and Send
works. New Chat in the chat menu stays available. Chats from files saved before
Whittle recorded where a chat was made never ask.

**The same file open in another Blender** (each keeps its own copy of the chats): while
the other Blender has it open, one dim line with `INFO` at the top of the panel, under
the attention box (`ui.draw_elsewhere`):

```
 ·ⓘ This file is open in another Blender;·
 ·  chats here won't merge with it.·
```

### 3.12 Typing without the mouse (Shift+Alt+C)

Shift+Alt+C, from any editor and in any mode (sketching and Edit Mode included), goes
straight to typing a prompt:

```
 ┌ Ask Claude ───────────────────────────────────┐   under the pointer
 │ [Add a lid|                                 ] │   already in edit mode
 │ ·Enter sends · End keeps your draft · long…·  │   dim hint
 └───────────────────────────────────────────────┘
```

1. The 3D viewport's sidebar opens on the Whittle tab (the viewport under the
   pointer, else the window's largest), so the conversation is in view.
2. `WHITTLE_PT_type_prompt` pops up under the pointer (22 units wide): a title, the
   composer's own field, as a one-line field with `activate_init`, the way F2 renames
   (placeholder `Ask Claude…`, as in the sidebar), and a dim hint, `Enter sends · End
   keeps your draft · long prompts: use the sidebar box`, fitted to the width by
   dropping its last parts whole (`shortcut.hint`). Typing starts at once.
3. **Enter sends** exactly as Enter in the sidebar's box does: the field confirms and
   the popup closes on the press, and `whittle.enter_send` sends on the release (§3.9).
   Blank text and a send that is not possible (a comparison) leave the text in the
   sidebar's box, as there. **Esc** closes the popup and leaves the field as it was.

The field follows the composer: `prompt` (`Ask Claude`), `amend_text` while a turn runs
(`Amend the Running Turn`), `ask_answer` while Claude asks (`Answer Claude`). It is
picked when the key is pressed, so a turn ending mid-typing does not swap it. A draft
already in the field opens selected, as in any Blender field: typing replaces it, End
adds to it, Esc brings it back. The field is the sidebar's, so the text is in both.

The popup's field is one line: Blender's multi-line box never takes the keyboard when
a popup opens, so Shift+Enter cannot add a line there (a draft's line breaks are kept,
just not shown). Long prompts are written in the sidebar's box.

The key is an add-on keymap item, `whittle.type_prompt` in the Window keymap, listed
and rebindable in Preferences → Keymap (Window → Ask Claude). Why this key:
`decisions.md`, Shortcut.

### 3.13 Model and effort

`architecture.md` §15 has where the list comes from and how a chat's model and effort
reach the agent.

Each chat runs on a model of its own, as in the Claude apps: the button beside Send
names it (`Opus 5.5 ▾`) and opens the model menu. A new chat starts on the add-on's
**Model** preference (`claude-opus-5-5` unless changed); a chat's first turn keeps the
model it was sent with, so changing the preference later moves only chats that have no
turn yet. Changing a chat's model applies from its next turn, in the same Claude
session (the conversation carries on); the button is hidden while a turn runs, and the
menu's items say why they are disabled while Claude asks.

Each chat also has an effort, how much Claude thinks: Low, Medium or High, picked in
the same menu. A new chat runs at High; a change applies from the chat's next turn, in
the same session, like the model. There is no preference for it: High suits
multi-step modelling turns, and Low or Medium trade depth for speed and cost on small
edits.

**The model menu** (`WHITTLE_MT_models`, opened from the button):

```
 ✓ Opus 4.6                       only when the chat is on an older or custom model
 ─────────────────
   Opus 5.5                       the newest of each family, by family:
 ✓ Sonnet 5.5                     Opus, Sonnet, Haiku, Fable, then others by name
   Haiku 5.5
   Fable 5.1
 ─────────────────
   Older Models                 ▸
   Other Model…
 ─────────────────
   ·Effort·                       a dim heading
   Low
   Medium
 ✓ High                           the chat's effort (High by default)
 ─────────────────
   Use Sonnet 5.5 for New Chats   only when the chat's model is not the default
 ─────────────────
   ·Listed by the Models API 1 hour ago·
```

- Each item is `whittle.chat_model` with the model's id; its text is the family and
  version (`Opus 5.5`), its icon `CHECKMARK` on the chat's model and `BLANK1` on the
  others, so the names line up; its tooltip is the full name and id (`Claude Opus 5.5
  (claude-opus-5-5)`).
- **Older Models** (`WHITTLE_MT_models_older`) has one column per family with older
  versions, its dim name on top, newest first: `Opus 5`, `Opus 4.8`, … With none,
  a dim `No older models`. It has no title of its own (`bl_label` is empty; the
  entry passes its text): a menu's title rule spans only its first column.
- **Other Model…** opens a dialog with the chat's id in a text field, for any model id
  (a proxy's name, a dated snapshot). The chat then shows that id in the button and
  first in the menu.
- **Effort**: a dim `Effort` label, then `whittle.chat_effort` for `low`, `medium` and
  `high` (text `Low`, `Medium`, `High`), `CHECKMARK` on the chat's and `BLANK1` on the
  others. Each tooltip says what the level is for (`Least thinking: fastest and
  cheapest, for small, clear edits`). The agent popover lists it under the model
  (`Effort: High`).
- **Use … for New Chats** (`whittle.default_model`) sets the preference.
- The dim last line says where the list is from: `Listed by the Models API <age>`, or
  `Listed by Claude <age>` when only the CLI's own list could be had (age as in the
  chat menu), or `Built-in list until Claude starts` before any agent has reported one.

## 4. States

ASCII mockups at the default width. `[ ]` is a button or field, `( )` a toggle, `▸` a
closed panel; dim text is marked `·dim·`.

### 4.1 Empty (new file, nothing picked)

```
 Whittle                              ⚙
 ·▣ Nothing selected: Claude·     (Auto)
 ·  adds new objects·
 ·Start from·
 [Selection][Blank][Primitive ▾]

 [✎ Sketch]
 [Ask Claude…                    ][📎]
 [       ▶ Send       ][Opus 5.5 ▾][🕘]
```

Send is disabled (nothing to send). No stroke row, no stroke types, no placeholders.

### 4.2 Prompt typed (Crate selected)

```
 Whittle                              ⚙
 ▣ Crate                          (Auto)

 [✎ Sketch]
 [Add a lid to the crate.        ][📎]
 [       ▶ Send       ][Opus 5.5 ▾][🕘]
```

A target and a prompt: the start row steps aside.

### 4.3 Running / streaming

```
 Whittle                              ⚙     the turn shows its own progress
 🔒 Crate                        ·(Auto)·
 ┌──────────────────────────────────┐
 │ Add a lid and carve a handle slot│
 │ on each side.                  ·⋯·│
 └──────────────────────────────────┘
 Plan: add a lid that overhangs the
 crate a little, then carve a handle
 slot on each side.
 ▸ Used 2 tools
 The lid sits right. Now the handle slots.
 ▸ ⧗ Running 2 tools                     no Working…: this says it
 [ thumbnail ]

 [✎ Sketch]
 [Ask Claude…                    ][📎]
 [          ✕ Stop ▾          ]  [🕘]
```

### 4.4 Asking

```
 🔒 Crate                        ·(Auto)·
 ┌──────────────────────────────────┐
 │ Add a lid to the crate.        ·⋯·│
 └──────────────────────────────────┘
 Adding the lid first.
 ▸ Used 1 tool
 ┌──────────────────────────────────┐
 │ ? Should the lid overhang the    │   box, not alert
 │   crate by 1 cm, or sit flush?   │
 │ [ Overhang ][ Flush ]            │   one button per choice
 └──────────────────────────────────┘

 [✎ Sketch]
 [Ask Claude…                    ][📎]   the question above says what it answers
 [          ✕ Stop ▾          ]  [🕘]     Answer appears once typed
```

### 4.5 Finished conversation (three turns)

```
 ▣ Crate, Crate_Lid               (Auto)
 ▸ Add a lid to the crate.
 ┌──────────────────────────────────┐
 │ Carve a handle slot in the front.⋯│
 └──────────────────────────────────┘
 Carving a handle slot into the front face.
 ▸ Used 2 tools
 The front has a handle slot now.
 [ thumbnail ]
 ┌──────────────────────────────────┐
 │ Make the wood darker.           ⋯│
 └──────────────────────────────────┘
 Darkening the wood and lightening the
 lid for contrast.
 ▸ Used 2 tools
 Recoloured.
 [ thumbnail ]

 [✎ Sketch]
 [Ask Claude…                    ][📎]
 [       ▶ Send       ][Opus 5.5 ▾][🕘]
```

### 4.6 Branched (second branch current)

```
 ┌──────────────────────────────────┐
 │ Add a lid.                      ⋯│
 └──────────────────────────────────┘
 Adding a lid.
 [ thumbnail ]
 ┌──────────────────────────────────┐
 │ Add rope handles on both sides.  │
 │                       ◂ 2/2 ·▸· ⋯│   ▸ dim: the last sibling
 └──────────────────────────────────┘
 Adding rope handles instead.
```

◂ goes to "Add metal handles on both sides." (1/2) and restores its newest node.

After ⋯ → Edit & Resend on "Add rope handles": the scene is at "Add a lid.", the old
prompt, strokes and references are back in the composer, and:

```
 ┌──────────────────────────────────┐
 │ Add a lid.                      ⋯│
 └──────────────────────────────────┘
 Lid added.
 [ thumbnail ]
 ·1 later turn·       [↻ Return to Latest]

 [✎ Sketch]
 [Add rope handles on both sides.][📎]
 [▶ Send as Branch][Opus 5.5 ▾][🕘]
```

### 4.7 Sketching

```
 ▣ Crate                          (Auto)
 [✎ Sketch][📷 Capture View]               Sketch depressed
 [〰][+][−̲][⌇][▭][≡] ·Carve·               Carve depressed
 ▾ 3 strokes · 2 views                🗑
   📷 View 1 · 1 stroke               ✕
   🎥 View 2 · 2 strokes  ·current·   ✕
   ☑ Markers While Sketching
 [Add a lid that ov… in the front.][📎]   the draft once, in its field
 [       ▶ Send       ][Opus 5.5 ▾][🕘]
```

Auto does not resync while in draw mode: the target stays what it was when sketching
started. The start row is hidden while sketching.

### 4.8 Manual targets

```
 ▣ 2 targets                        (Auto)   ← off; the rows say which
 ▣ Crate                                ✕
 ▣ Crate_Lid                            ✕
 [ + Add Barrel                    ] [⋯]
```

### 4.9 Errors

A recovered tool error, then a failed turn:

```
 ┌──────────────────────────────────┐
 │ Add a lid.                      ⋯│
 └──────────────────────────────────┘
 Adding a lid.
 ▸ Used 1 tool                           ← the ✗ is inside, not here
 That had a syntax error; fixing it.
 ▸ Used 2 tools
 Done: the crate has a lid.
 [ thumbnail ]
 ┌──────────────────────────────────┐
 │ Make it bigger and give it feet.⋯│
 └──────────────────────────────────┘
 Scaling the crate up, then adding feet.
 ▸ Used 2 tools
 [ thumbnail ]
 ✕ Claude stopped with       [⟳ Retry]   ← the only red: one line, wrapped
   an error
```

A crashed agent:

```
 ┌──────────────────────────────────┐
 │ ⚠ Claude stopped unexpectedly    │   red line, normal button
 │ [ ⟳ Restart and Retry ]          │
 └──────────────────────────────────┘
 ▣ Crate                          (Auto)
 ┌──────────────────────────────────┐
 │ Add a lid.                      ⋯│
 └──────────────────────────────────┘
 Starting on the lid.
 ·⏸ Interrupted·                          the box above says why
```

First run, no environment:

```
 ┌──────────────────────────────────┐
 │ ⓘ Set up Claude to start         │   not red
 │ [ ⤓ Set Up… ]                    │
 └──────────────────────────────────┘
 …
 [       ▶ Send       ][Opus 5.5 ▾][🕘]     disabled
```

### 4.10 Long session (13 turns)

```
 ▸ 8 earlier turns
 ▸ Step 9: move the crate a…
 ▸ Step 10: move the crate a…
 ▸ Step 11: move the crate a…
 ┌──────────────────────────────────┐
 │ Step 12: move the crate a        │
 │ centimetre along x.             ⋯│
 └──────────────────────────────────┘
 Nudged (12).
 [ thumbnail ]
 ┌──────────────────────────────────┐
 │ Step 13: …                      ⋯│
 └──────────────────────────────────┘
 …
```

At most 1 (earlier) + 3 collapsed lines + 2 expanded turns, whatever the length.

### 4.11 Comparing

```
 ▣ Crate, Crate_Lid               (Auto)
 ┌──────────────────────────────────┐
 │ ⇄ Showing: Add a lid             │
 │ [  Swap  ][Keep This ][  Done  ] │
 └──────────────────────────────────┘
 ┌──────────────────────────────────┐
 │ Add a lid.                     ⇄ ⋯│   the compared turn is marked
 └──────────────────────────────────┘
 …conversation…
 [Ask Claude…                    ][📎]
 [       ▶ Send       ][Opus 5.5 ▾][🕘]     disabled; tooltip says why
```

### 4.12 Chats

The header in the mockups above reads the chat's title (§3.11), not `Whittle`.

A new chat (after New Chat, the crate still selected):

```
 ▾ New chat ▾                         ⚙
 ▣ Crate                          (Auto)
 ·Start from·
 [Selection][Blank][Primitive ▾]

 [✎ Sketch]
 [Ask Claude…                    ][📎]
 [       ▶ Send       ][Opus 5.5 ▾][🕘]
```

Switched to an older chat (the scene was left as the last chat had it):

```
 ▾ Barrel with metal bands ▾          ⚙
 ▣ Barrel                         (Auto)
 ▸ Make a barrel.
 ┌──────────────────────────────────┐
 │ Add two metal bands.            ⋯│
 └──────────────────────────────────┘
 Adding two bands near the ends.
 ▸ Used 3 tools
 [ thumbnail ]
 ·ⓘ The scene is as you left it; Claude·
 ·  will look at it before editing.·

 [✎ Sketch]
 [Ask Claude…                    ][📎]
 [       ▶ Send       ][Opus 5.5 ▾][🕘]
```

## 5. Menus

`whittle.turn_menu` (node from its property), items disabled per `operators.can_*`:

| Item | Operator | Icon |
|---|---|---|
| Edit & Resend | `whittle.history_branch` | `GREASEPENCIL` |
| Go Back to This Turn (Go Back to the Start for the start) | `whittle.history_restore` | `LOOP_BACK` |
| Compare With Current | `whittle.history_compare` | `ARROW_LEFTRIGHT` |
| Ghost of Previous Turn / Hide Ghost | `whittle.ghost_toggle` (only for the current node) | `GHOST_*` |
| Open Render | `whittle.open_image` (the turn's last render; hidden without one) | `IMAGE_DATA` |
| Open Transcript | `whittle.open_transcript` | `TEXT` |

The start's menu has Go Back to the Start and Compare With Current. A folded turn's menu has
Edit & Resend (which only puts its prompt back in the box: the scene never left its
parent and its strokes are still pending) and Open Transcript.

`whittle.ref_menu`: `Pin to Every Request` / `Unpin` (`whittle.ref_pin`), then `Place
Facing the View`, `Place Behind, Front`, `Place Behind, Right`, `Place Below, Top`
(`whittle.ref_place` with `index` and `align`: a popup menu's submenu cannot carry the
index, so the four are flat), then `Open Image` (`whittle.open_image`) and `Remove`
(`whittle.ref_remove`).

`WHITTLE_MT_start_primitive`: one item per primitive, then the dim Asset Browser hint.

`WHITTLE_MT_stop`: §3.9.

`WHITTLE_PT_chats`: §3.11.

`WHITTLE_MT_models`, `WHITTLE_MT_models_older`: §3.13.

## 6. Development panel

`WHITTLE_PT_debug`, label `Development`, child of the main panel, `DEFAULT_CLOSED`,
`poll` returns `context.preferences.view.show_developer_ui`. The current bundle's folder
name, `whittle_fake_script`, `whittle_bundle_path` (both on the window manager, so no
`.blend` carries them: a fake script runs any Python), `Run Bundle`, `Start Agent` / `Stop Agent`, and the
agent log tail when it crashed or failed.

## 7. Operators and properties

Added for the chat sidebar:

| Id | Label | Does |
|---|---|---|
| `whittle.branch_switch` | Switch Branch | `node`: restore the newest leaf under it; undo step |
| `whittle.retry` | Retry | `node`: resend a failed turn's request from its parent (branch then send; a folded turn just sends); restarts a stopped agent on the way |
| `whittle.turn_menu` | Turn | `node`: opens the turn's ⋯ menu (§5) |
| `whittle.ref_menu` | Reference | `index`: opens the reference's ⋯ menu (§5) |

Added for chats (§3.11; none of them is an undo step, and none changes the scene):

| Id | Label | Does |
|---|---|---|
| `whittle.chat_new` | New Chat | starts an empty chat and makes it current |
| `whittle.chat_switch` | Switch Chat | `chat`: makes that chat current; description names it (`Barrel with metal bands · 4 turns`) |
| `whittle.chat_continue` | Continue | continues the current chat made on another machine: records this install in its `adopted`, so it is never asked about again; poll: the current chat is foreign |
| `whittle.chat_rename` | Rename Chat | `title` (empty: the automatic title), in a props dialog on the current chat |
| `whittle.chat_delete` | Delete Chat | `chat`: confirms, then deletes it (the current one: switches first) |
| `whittle.chat_delete_many` | Delete Chats | `which` (`OTHERS`, `WEEK`, `MONTH`, `QUARTER`): a dialog with the count and size, then deletes |

Added for sketching (§3.8):

| Id | Label | Does |
|---|---|---|
| `whittle.sketch_toggle` | Toggle Sketch Mode | Shift+Alt+D: `whittle.sketch` or `whittle.sketch_stop`, whichever applies; undo step |
| `whittle.view_snap` | Snap to View | `id`: moves the viewport to the view and makes it current; no undo step, like Blender's view operators |

`WindowManager.whittle_show_view_markers` (BoolProperty, `SKIP_SAVE`, default on) holds
whether the view markers show while sketching.

Added for typing without the mouse (§3.12):

| Id | Label | Does |
|---|---|---|
| `whittle.type_prompt` | Ask Claude | Shift+Alt+C: opens the sidebar on the Whittle tab and `WHITTLE_PT_type_prompt` under the pointer, its field in edit mode |

Added for Claude's Markdown (§3.6; internal, no undo step):

| Id | Label | Does |
|---|---|---|
| `whittle.open_link` | Open Link | `url`, `text`: `wm.url_open` of url, only for `http`, `https` and `mailto` (`markdown.openable`; any other link is drawn as plain text); tooltip `Open “the docs”: https://docs.blender.org` |
| `whittle.link_menu` | Links | `links` (JSON `[[text, url], …]`): a popup menu with a `whittle.open_link` per link |
| `whittle.copy_code` | Copy Code | `text`: puts a code block on the clipboard |

Added for the model per chat (§3.13; no undo step):

| Id | Label | Does |
|---|---|---|
| `whittle.chat_model` | Model | `model`: the current chat runs on it from its next turn (a file without a chat gets one); empty: a props dialog (`Other Model`, confirm `Use Model`) for any id. Poll: not while a turn runs or Claude asks. Description: `Claude Opus 4.6 (claude-opus-4-6)` |
| `whittle.chat_effort` | Effort | `effort` (`low` \| `medium` \| `high`): the current chat runs at it from its next turn (a file without a chat gets one). Poll as `whittle.chat_model`. Description: what the level is for |
| `whittle.default_model` | Use for New Chats | `model`: sets the add-on's Model preference |

`WindowManager.whittle_show_all_chats` (BoolProperty, `SKIP_SAVE`) holds whether the
chat menu lists every chat.

`scene.whittle.chat` (StringProperty, `HIDDEN`) names the chat that
`scene.whittle.history_node` belongs to (§8).

Changed:

- `whittle.submit` keeps its id (keymaps); the button text is `Send` / `Send as New
  Branch`. It clears `prompt` when the turn is accepted, and a dropped run puts it
  back. Its poll explains a comparison with `poll_message_set`.
- `whittle.history_branch` on a folded turn only puts its prompt back
  (`operators.can_branch` allows it while the scene is at its parent).
- `whittle.stroke_type` has a per-type `description`.
- `whittle.history_restore` has a `description` naming the node (`n0003 · label`).
- `whittle.compare_toggle` and `whittle.compare_end` tooltips say that saving during a
  comparison saves what is shown.
- A turn finishing, kept partial, Restore, Branch, `branch_switch`, Compare → End and the
  start points select the target list's objects when `target_auto` is on.

`WindowManager.whittle_show_views` (BoolProperty, `SKIP_SAVE`) holds whether the view
list is open.

Properties on `scene.whittle`:

- `target_auto: BoolProperty(name="Auto", default=True)`, description `Follow the
  selection: Claude works on the selected objects (or the active one). Turn off to pick
  the objects by hand`.
- `stream_length` is removed; old files that have it load fine, the value is ignored.

Labels the user sees: Send, Send as Branch, Amend, Stop, Answer, Retry, Restart and
Retry, Return to Latest, Auto, Sketch, Capture View, Edit & Resend, Go Back to This Turn,
Go Back to the Start, Compare With Current, Ghost of Previous Turn, Hide Ghost, Open
Render, Open Transcript, Start from, Selection, Blank, Primitive, Add Selected, Swap,
Keep This, Done. "Claude" names the agent everywhere in the panel ("Ask
Claude…", "Claude stopped unexpectedly").

## 8. Undo

Each turn pushes `Whittle: before <node>` when it starts and `Whittle: <node> <label>`
when it finishes; Restore, Edit & Resend (`Whittle: edit & resend <node>`, after the
prompt and strokes are back), branch switch and Compare → Keep push one step each;
sketch (Sketch, Stop Sketching) and reference (Add, Remove, Pin, Place) operators are
`UNDO`. Because the conversation is drawn from `scene.whittle.history_node`, Ctrl+Z
after a Restore or a branch switch moves the conversation back with the scene.

Ctrl+Z during a turn goes back to the turn's start: the agent is told on its next call
and a warning says so in the conversation. Ctrl+Z during a comparison ends it without
touching the scene (the undo put back a scene from before it). An undo that takes the
sketch out of Draw Mode ends the sketch session.

Chats are not undone: New Chat, a switch, a rename and a delete push no undo step, and
Ctrl+Z never changes the current chat. An undo step that holds another chat's node
(`scene.whittle.chat` is not the current chat) rolls the scene back but leaves the
current chat's node where it is.

## 9. Feature reachability

Every feature of the old panels, and where it lives now.

| Feature | Before | Now |
|---|---|---|
| Submit | Request → Submit | Composer → Send; Shift+Alt+Enter over the viewport |
| Amend with text | Request (during turn) → Amend | Composer during a turn: type, then Amend |
| Amend with strokes | Request → Amend | Composer → Amend (shown once strokes are drawn, also while Claude asks) |
| Amend with text while Claude asks | Request → Amend | After answering (the field is the answer's while Claude asks) |
| Interrupt → Keep | Request → Keep | Composer → Stop ▾ → Stop and Keep Changes |
| Interrupt → Restore | Request → Restore | Composer → Stop ▾ → Stop and Undo This Turn |
| Answer a question (choice) | Activity box buttons | Question block in the conversation |
| Answer a question (free text) | Activity box field + Answer | Composer field, then Answer |
| Add reference | Request → Add Reference | Composer 📎 |
| Pin / unpin reference | Request row pin | Reference chip → Pin / Unpin; a pinned chip's 📌 unpins it |
| Place reference (View/Front/Right/Top) | Request row button + redo panel | Reference chip → Place … |
| Remove reference | Request row ✕ | Reference chip → Remove |
| Reference thumbnail | Request row | Reference chip icon |
| Edit a reference's path | Request row path field | Remove and add again |
| Sketch / Stop Sketching | Sketch panel | Sketch button |
| Stroke types (6) | Sketch panel grid | Icon buttons while sketching (tooltips name them; the active one is named) |
| Next stroke type | keymap only | Shift+Alt+N (keymap only) |
| Toggle sketch mode | — (new) | Shift+Alt+D (keymap only; the Sketch button does the same) |
| Capture View | Sketch panel | Capture View beside Sketch while sketching; Shift+Alt+V |
| View list with stroke counts, current view | Sketch panel | Stroke count ▸ (whenever strokes or views are shown, sent ones included) |
| Remove view | Sketch panel ✕ | Stroke count ▸ → ✕ |
| Snap to a view | — (new) | Stroke count ▸ → the view's row, or its marker in the viewport while sketching |
| View markers on/off | — (new) | Stroke count ▸ → Markers While Sketching |
| Clear sketch | Sketch panel 🗑 | Stroke count 🗑 (also after a stopped or failed sketch turn, or with views only) |
| Strokes ready / sent / pending | Sketch panel line | Stroke count |
| Targets auto from selection | — (new) | Target line (Auto) |
| Targets manual list, remove | Main panel list | Auto off → rows with ✕ |
| Add Selected | Main panel | Auto off → Add <name> |
| From Selection | Main panel | Auto off → ⋯ → Replace With Selection (or Auto on) |
| Clear targets | Main panel ✕ | Auto off → ⋯ → Clear |
| Target collection | Main panel field | Auto off → ⋯ → collection field; shown as a row |
| Target lock warning | Main panel alert box | Removed: user edits during a turn are not reported |
| Start From Selection | Start panel | "Start from" row → Selection (before anything is sent; then the 🕘 popover until a turn is kept) |
| Blank | Start panel | Start row → Blank (nothing added to the scene, nothing selected) |
| Primitive menu (+ size) | Start panel | Start row → Primitive ▾ (+ redo panel) |
| Start From Asset | Asset Browser context menu | unchanged; hinted in the Primitive menu |
| Start shown after starting | Start panel "Start: …" | Dim start line before the first turn; 🕘 popover's first row |
| History tree with thumbnails, status, current | History panel | 🕘 popover |
| Restore | History row ⟲ | Turn ⋯ → Go Back to This Turn; popover row title |
| Restore the start | History row ⟲ | Popover's first row |
| Branch | History row | Turn ⋯ → Edit & Resend; popover ⋯ |
| Switch between branches | Restore in History | Turn ◂ 1/2 ▸; popover row title |
| Return to the end of a branch | Restore in History | "later turns" row → Return to Latest |
| Compare | History row ⇄ | Turn ⋯ → Compare With Current; popover ⋯ |
| Compare Toggle / Keep / End | History compare box | Comparison bar: Swap / Keep This / Done (and popover) |
| Saving during a comparison warning | History compare box | Tooltips of the comparison bar's buttons |
| Ghost | History → Ghost of … | Current turn ⋯ → Ghost of Previous Turn / Hide Ghost; popover → Hide Ghost |
| "Next submit branches from …" | Request | Send reads "Send as Branch" |
| "End the comparison to submit" | Request | Send disabled, its tooltip says why |
| Folded failed turns hidden | History | unchanged; shown once in the conversation with Retry |
| Assistant text | Activity | Conversation |
| Thinking | Activity | Inside the tool group |
| Tool calls with code and result | Activity, one panel each | Tool group ▸ → each call ▸ |
| Recovered tool error | Activity, red ✗ | Tool group (expanded) ✗, not red |
| Render thumbnails + Open Image | Activity, every render | Turn thumbnail; every render with its button inside the tool group; ⋯ → Open Render |
| Notes (context, delivered amendment) | Activity | Dim note lines in the turn |
| Turn done (steps, cost) | Activity line | Tool group footer |
| Turn failed | Activity red line | The reason in red at the turn's end, Retry beside it |
| Turn interrupted | Activity line | "Stopped, changes kept/undone" line |
| Open Transcript | Activity button | Turn ⋯; 🕘 popover footer |
| Entries count | Activity field | Removed: fixed length rule (§3.6) |
| Agent state and phase | Main panel | Header icon (busy or not) and agent popover; phase line in the running turn |
| Model | Main panel (one for all) | Per chat: composer → model button ▾ (§3.13); the default for new chats in Preferences; named in the agent popover. Effort per chat in the same menu |
| Session folder, development session warning | Main panel | Agent popover: the file that stores the chats, or the unsaved-file warning |
| Session folder move waiting | Activity | Removed: the chats' cache never moves (architecture §14) |
| Crash reason + Restart Agent | Main panel alert box | Attention box (Restart and Retry); the reason in the agent popover |
| Agent environment setup / progress / cancel / last failure | Main panel box | Attention box |
| Missing or refused API key | — (a failed turn) | Attention box |
| Start / Stop Agent | Development | Agent popover; Development |
| Fake script, bundle path, Run Bundle, bundle shown | Development | Development (Developer Extras only) |
| Agent log tail | Development | Development (Developer Extras only) |
| Undo / redo across turns, restores, sketching | Ctrl+Z | unchanged; the conversation follows |
| New chat, earlier chats, rename, delete | — (new) | Header title ▾ → chat menu (§3.11) |
| Type a prompt, amendment or answer without the mouse | — (new) | Shift+Alt+C (§3.12) |
| Continue a chat made on another machine | — (new) | The box above the sketch row → Continue (§3.11) |
| Same file open in another Blender | — (new) | A dim line at the top of the panel (§3.11) |

## 10. Screenshot gate

The sidebar is accepted on real screenshots from `./screens.sh`, looked at, not only on
headless tests. Every scenario below must exist and pass its check, at the default
width and, for `conversation` and `long_session`, the wide variant too.

| Scenario | Check |
|---|---|
| `empty` | 4.1; "Nothing selected: Claude adds new objects"; one start row under "Start from", buttons not cut; no stroke row, no stroke types; nothing red |
| `start` | default cube scene, start row shown under "Start from" |
| `prompt_typed` | 4.2; no start row |
| `shortcut_popup` | §3.12; the `Ask Claude` popup under the pointer, its one-line field in edit mode holding the half-typed prompt, the dim hint whole below it |
| `prompt_only_done` | one finished prompt-only turn; no red; no start line |
| `sketching` | 4.7; Sketch pressed with Capture View beside it, types on their own row, depressed correctly, the active one named; view list open, no view dimmed, the current one tagged, rows left-aligned like labels, the markers checkbox under them; the draft once, in its field |
| `view_markers` | a viewport shot, not the sidebar: one marker per view, each pointing at the crate, the current one orange; none on top of the eye |
| `streaming` | 4.3; gear in the header; one busy sign: "Running 2 tools" in the group header, no Working…; Stop alone; Auto dim |
| `asking` | 4.4; question not red and said once; Stop alone; placeholder `Ask Claude…` |
| `conversation` | 4.5; older turn collapsed; two expanded; one ⋯ per message; text wraps to the width |
| `markdown` | a Markdown reply: no `**`, `#` or `- ` markers; bold heading with a line under it; bold and italic words; bullets and numbers in a margin; the whole reply shown |
| `markdown_stress` | a stress test shown whole (the 8-line cap lifted): headings told apart by their rules and dimming (H1 over a double line, H2 a line, H3 and H4 bold, H5 and H6 dim); struck text with a line through it; inline code monospace; escapes without backslashes; task boxes; nested quotes indented and dim with their list, a bar per quote level; indented and fenced code in boxes, each with a copy button on its first row, `python` dim beside it; a boxed table with a bold header, aligned columns and a wrapped cell; maths as symbols, the block centred; a closed "Click to expand" section; HTML styled, entities decoded; emoji without boxes; link text underlined; a link button at the end of a line with one link, and a menu button on the line with two; the bare Wikipedia address keeping its `(bar)`; superscript footnote references and the dim notes at the end; no raw markers |
| `branched` | 4.6; switcher in the bubble's last row left of ⋯: ◂ 2/2 with a dim ▸ |
| `branch_edit` | after Edit & Resend: later-turns row with Return to Latest, Send as Branch, prompt brought back |
| `interrupted` | thumbnail, then one dim "Stopped, changes kept" |
| `error_turn` | 4.9; recovered error not red; the failure one red line (wrapped at most once) with Retry beside it |
| `folded_failure` | a failed turn that changed nothing: shown with Retry, no tree node, prompt box empty, no start row |
| `crashed` | one red line with Restart and Retry; the turn ends with a dim "Interrupted", without its own Retry |
| `setup_needed` | neutral box with Set Up…; Send disabled; no repeated note |
| `key_needed` | neutral box `Add an API key to start` with its dim line, Preferences… and Get a Key; the prompt still in the box; no repeated note |
| `manual_targets` | 4.8; the target line counts ("2 targets"), the rows name them; one ✕ per row; Add <selected object>; the draft once |
| `references` | two reference chips right above the prompt, one with a pressed pin; the draft once |
| `comparing` | 4.11; "Showing: <prompt>" without quotes; Swap / Keep This / Done as text, not cut; the compared bubble marked; no node id, nothing red |
| `long_session` | 4.10; panel no taller than `conversation` + 8 rows |
| `history_popover` | 13-turn tree, two branches: one indentation step per level, siblings at equal indentation, lines flat, each branch's first row marked ↳ (no disclosure triangles), branch points say "2 branches", titles whole including the current row, current row highlighted, one ⋯ per row |
| `turn_menu` | the ⋯ menu opened on a turn, Edit & Resend first, then Go Back to This Turn |
| `developer` | Developer Extras on: Development panel shown; off (every other scenario): absent |
| `chat_menu` | three chats, the second-newest current: New Chat first; Conversations; each entry's title whole, its dim `N turns · <age> · <size>` line; ✓ on the current entry (highlighted), 🗑 on the others; the footer total and three items; nothing red |
| `chat_menu_many` | 25 chats of varied age and size: 20 entries then `Show 5 More`; long titles shortened with `…` at a word's end, the ✓/🗑 column aligned on every row; ages from `just now` to `over a year ago` |
| `new_chat` | 4.12 after New Chat: header `New chat ▾` beside the agent icon, empty conversation, start row; nothing else |
| `switched_chat` | 4.12 after switching to an older chat: its title in the header, its conversation, the dim "scene is as you left it" line once at the end, the scene unchanged |
| `continue_chat` | §3.11: a chat from another machine, its conversation shown; the `Continue this chat?` box above the sketch row with its dim line and Continue; Send disabled; the draft kept; nothing red |
| `open_elsewhere` | §3.11: one dim line at the top, `This file is open in another Blender; chats here won't merge with it.`, wrapped, not red |
| `delete_confirm` | the confirmation of 🗑 on a chat: its title, turns and size, "leaves this file the next time you save" |
| `delete_many` | the Delete Chats dialog on `Older Than a Month`, with the count and size line |
| `model_menu` | the model menu over a chat on Sonnet 5.5: Opus 5.5, Sonnet 5.5 (✓), Haiku 5.5, Fable 5.1, then Older Models ▸ and Other Model…, `Use Sonnet 5.5 for New Chats`, the dim source line `Listed by the Models API 1 hour ago`; names whole, icons in one column |
| `model_menu_older` | the Older Models submenu with the chat on Opus 4.6: one column per family under its dim name, newest first, ✓ on Opus 4.6; no title or rule over the first column alone |

Popover and menu scenarios end by returning a `Popup` (`tests/screens/scenarios.py`):
the harness puts the pointer over the sidebar with a simulated mouse move, shoots the
window, opens the popup (`wm.call_panel`, or the operator invoked: `wm.call_menu` for a menu),
shoots again and crops to what changed, leaving out the status bar (a menu puts its
hints there). The chat scenarios build their chats through the add-on's own
controller and fake agent, then set each chat's age by its recorded times, so ages
and sizes are stable from run to run. `delete_confirm` and `delete_many` invoke the
operators, which open their dialogs. Every scenario's header shows its chat's title,
so the header is checked in all of them: title not cut by Blender's `...`, the
chevron and the agent icon both visible. Tooltips are turned off for the run, since the pointer rests on
the popup's first item.

General checks on every shot: no text clipped by Blender's own `...` at 280 px (Whittle
shortens with `…` at a word's end), except inside a one-line text field; nothing said
twice (a draft, a busy sign, a list and its heading); no row wider than the sidebar;
text lines use the width they have; red only in `error_turn`, `folded_failure` and
`crashed`.
