# Keyboard shortcuts

Whittle's keys all use Shift+Alt (Shift+Option on a Mac), so they stay clear of Blender's
own keys and fit a tablet's express keys. You can change any of them.

## The keys

| Key | What it does | Where the pointer must be | Name in the Keymap |
|---|---|---|---|
| **Shift+Alt+C** | Opens the Whittle sidebar and a prompt field under the pointer, ready to type | Anywhere, over any editor | Ask Claude |
| **Shift+Alt+D** | Starts sketching, or stops | Over the viewport | Toggle Sketch Mode |
| **Shift+Alt+V** | Captures the current view | Over the viewport | Capture View |
| **Shift+Alt+Enter** | Sends, amends or answers (see below) | Over the viewport | Send or Amend |

All four work in every mode: Object Mode, Edit Mode and while sketching. "Over the
viewport" means the 3D view itself: with the pointer over the sidebar or a header, the
three viewport keys do nothing. {doc}`sketching` explains strokes and views.

**Shift+Alt+Enter** depends on what Whittle is doing. A *turn* is one request and Claude's
work on it, and *amending* adds to a turn that is still running.

- Between turns it sends. A typed prompt, a {doc}`reference image <references>` or new
  strokes are each enough. Enter in the prompt box needs typed text, so this is the key
  for sending strokes or a reference on their own.
- While Claude works it amends the turn, with text in the prompt box or strokes drawn
  since the turn began.
- While Claude asks a question it sends your answer, once you have typed one. With no
  answer typed, strokes drawn since the turn began amend the turn.
- With nothing to send it does nothing.
- It also does nothing while [comparing turns](history.md#compare-with-an-earlier-turn), or
  in a [chat from another machine](chats.md#open-a-chat-made-on-another-machine) you
  haven't continued. Hold the pointer over the dim Send button to see why.
- If Claude has no API key, it shows an error saying what's missing.
- If Claude isn't set up, the first press shows an error and the box offers the setup. After
  that it does nothing, as Send is dim, until it finds the environment: it looks again at each
  press, so one set up in another Blender is picked up.

{doc}`prompting` covers what Send, Amend and Answer do.

## Type a prompt without the mouse

Press **Shift+Alt+C**. The sidebar opens on the Whittle tab, in the viewport under the
pointer or else the window's largest one, and a small field appears under the pointer.
Start typing straight away.

```{figure} ../images/guides-shortcuts/ask-claude.png
:alt: A small popup titled Ask Claude with a half-typed prompt selected in its field, and a dim hint below.

The Ask Claude popup. A draft already in the field opens selected.
```

| Key in the popup | What it does |
|---|---|
| **Enter** | Sends, as Enter in the sidebar's box does |
| **Esc** | Closes the popup and leaves the field as it was |
| **End** | Keeps a draft that opened selected, and puts the cursor after it, so you add to it |
| Any other typing | Replaces a selected draft |

The popup types into the same field as the sidebar, so the text shows in both. While a
turn runs, what you type there amends the turn, and while Claude asks it is your answer.
The field is picked when you press the key, so a turn that ends while you type doesn't
swap it.

The popup's field is one line. Write long prompts in the sidebar's box.

## Keys in the prompt box

| Key | What it does |
|---|---|
| **Enter** or numpad Enter | Sends, amends or answers, whichever the box is doing. It needs typed text. |
| **Shift+Enter** | Adds a line |

Ctrl+Z is Blender's own key, and what it does during a turn is on the {doc}`undo` page.

## Change a key

1. Open **Edit → Preferences → Keymap**.
2. With **Name** chosen above the list, type `Whittle` in the search field. Every Whittle
   key is listed.
3. Click the key button on the right of a row, then press the new keys.

```{figure} ../images/guides-shortcuts/keymap.png
:alt: Blender's Preferences on the Keymap section, filtered by Whittle, listing Ask Claude and two Send on Enter rows under Window, and Send or Amend, Capture View and Toggle Sketch Mode under 3D View.

Whittle's keys in the Keymap, found by searching for Whittle. Blender calls the Enter key Return.
```

To check a key is free first, switch the search to **Key-Binding** and type the key with
spaces, such as `shift alt k`. Written with plus signs, it lists nothing even when the key
is taken.

The other things you can do from a row:

- Untick its checkbox to turn the key off and keep its binding.
- After a change, the **X** at the row's end becomes a back arrow. Click it to go back to
  the default.

Without the search, the keys are in two places: **Window → Ask Claude**, and
**3D View → 3D View (Global)** for the three viewport keys.

Leave the two **Send on Enter** rows alone. They are what makes Enter send from the
prompt box: without them, Enter only ends editing and sends nothing.

If **Auto-Save Preferences** is off, use **Save Preferences** in the menu at the bottom
left of the Preferences to keep your changes.

## Use a tablet's express keys

Whittle has no tablet setting of its own. In your tablet's driver, set each express key
to send a keystroke, and Blender sees it as if you had typed it.

| Express key | Keystroke |
|---|---|
| Sketch on or off | Shift+Alt+D |
| Capture view | Shift+Alt+V |
| Send | Shift+Alt+Enter |

If you changed a key in the Keymap, use your own key here instead.

Keep the pen hovering over the viewport as you press, not over the sidebar. Then a whole
sketch needs no keyboard:

1. Open the sidebar on the Whittle tab, with **View → Sidebar** or N over the viewport.
   The Sketch key doesn't open it.
2. Press Sketch to start. The sidebar shows the sketch tools.
3. Draw, orbit and draw again. Press Capture view when you want to record an angle.
4. Press Send. Strokes go without a prompt, or type one first to say what they mean.

Shift+Alt+C is not in the table because it needs a keyboard to type into. While Claude
works, Send amends the turn with whatever you drew since it began.

```{note}
These keys have been tested with simulated key presses, not yet with a physical tablet.
If an express key does nothing, check that the pen is over the viewport, then check the
keystroke in your tablet's driver.
```
