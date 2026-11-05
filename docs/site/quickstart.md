# Quickstart

This page takes you from nothing to one finished edit, and back again. You install
Whittle, give it what it needs to run, ask Claude to change Blender's default cube, look
at the result and undo it. Each prompt and the work Claude does on it is a *turn*; the
program that runs Claude beside Blender is the *agent*.

You need:

- Blender 5.2 on a [supported platform](guides/installation.md).
- The Whittle zip, `whittle-0.1.0.zip`, from the
  [latest release](https://github.com/ImOnALampshade/whittle/releases/latest).
  [Installing and updating](guides/installation.md#install-the-extension) has more, and how
  to build it yourself.
- An Anthropic API key whose Console account has API credits. Every turn is billed to
  that account; [API key and cost](guides/api-key.md) says what moves the price.

Claude edits your scene by running Python inside Blender, without asking each time. Read
[Privacy and safety](guides/privacy.md) before you use Whittle on files you did not make.

## Install the extension

1. In Blender, open **Edit → Preferences → Get Extensions**.
2. Click the arrow to the right of **Repositories** and choose **Install from Disk…**.

   ```{figure} images/quickstart/install-menu.png
   :alt: The top of the Get Extensions section. The arrow to the right of Repositories is pressed and its menu is open on Install from Disk, over the Online Extensions box with its Continue Offline and Allow Online Access buttons

   The arrow to the right of **Repositories**, with its menu open.
   ```

   If an **Online Extensions** box appears, as it does here, pressing its **Allow Online
   Access** does the same as step 4.

3. Pick `whittle-0.1.0.zip` and press **Install from Disk**. Leave **Enable on Install**
   ticked.
4. Open the **System** section and tick **Allow Online Access**, under **Network**.
   Whittle will not download anything or start the agent without it.

   ```{figure} images/quickstart/online-access.png
   :alt: The System section of Blender's Preferences, with the Allow Online Access checkbox in the Network panel, not yet ticked

   Allow Online Access is in the Network panel of the System section.
   ```

## Set up the agent environment

Claude runs in a small Python environment of its own, which Whittle downloads once.

1. Still in the Preferences, open **Add-ons**, find **Whittle** and expand it.
2. In the **Agent Environment** box, press **Set Up Agent Environment**.

   ```{figure} images/quickstart/environment.png
   :alt: The Agent Environment box, with an empty Environment Folder field, the status Not set up yet, and the Set Up Agent Environment and Reinstall buttons

   Before setup the box says **Not set up yet**.
   ```

3. Read the dialog and press **Download and Install**.
4. Wait for the status line to change to **Ready**. The largest download is about 114 MB,
   and the line shows its progress.

[Installing and updating](guides/installation.md) covers what is downloaded and where it
goes.

## Add your API key

1. In the same preferences, press **Get an API Key**. It opens the Claude Console's keys
   page in your browser. Make a key there and copy it.
2. Paste it into **Anthropic API Key**.

```{figure} images/quickstart/api-key.png
:alt: The Claude box in Whittle's preferences: an empty Anthropic API Key field, the line Whittle needs an Anthropic API key to run Claude, and the Get an API Key button

The key field, at the top of Whittle's preferences.
```

The line under the field changes to say usage is billed to the key's Console account.
Close the Preferences.

## Open the sidebar

1. Start a new file with **File → New → General**. The default cube is selected.
2. Move the pointer over the 3D viewport and press **N** to open the sidebar.
3. Click the **Whittle** tab on the sidebar's right edge.

```{figure} images/quickstart/first-look.png
:alt: The default cube, selected, in the viewport. The Whittle tab is open in the sidebar, showing Cube as the target with Auto on, the Start from buttons, Sketch, an empty Ask Claude box and a greyed-out Send button

The Whittle tab on a new file.
```

The row with the **Auto** button says what Claude will work on: **Cube**, because it is
selected and **Auto** is on. You can ignore **Start from** and **Sketch** for now. [The
sidebar](guides/sidebar.md) goes through every part.

## Send a first prompt

1. Click the **Ask Claude…** box and type a request:

   ```text
   Bevel the edges of the cube.
   ```

2. Press **Enter**, or the **Send** button. (Shift+Enter adds a line instead of sending.)

```{figure} images/quickstart/prompt.png
:alt: The Whittle sidebar with Bevel the edges of the cube typed in the prompt box and the Send button enabled

A prompt, ready to send.
```

The first Send starts the agent, so give it a moment. While the turn runs, Claude's text
and tool calls appear in the sidebar and the scene changes in front of you. **Stop**, in
place of Send, opens a menu: **Stop and Keep Changes** ends the turn early and keeps
Claude's edits so far, and **Stop and Undo This Turn** ends it and takes them back.

## See the result

When the turn ends, the sidebar shows your prompt, Claude's reply, a **Used 2 tools** row
and a render Claude made to check its work. Claude's words and the number of tools will
differ from the picture. A turn can have several tools rows, with Claude's notes between
them, and a row may read **Thought, used 3 tools**.

```{figure} images/quickstart/finished.png
:alt: The cube in the viewport now has rounded edges. The sidebar shows the prompt, Claude's reply, Used 2 tools and a small render of the bevelled cube

The finished turn, with the edit in your scene.
```

The edit is ordinary Blender data, so you can keep working on it by hand. Expand a tools
row to see what Claude ran; the last one ends with the steps and what the turn cost.

## Undo it

With the pointer over the viewport, press **Ctrl+Z**. One press takes back the whole
turn, as long as you have done nothing else since.

```{figure} images/quickstart/undone.png
:alt: The cube is square again. The sidebar has no conversation now, only a line saying 1 later turn with a Return to Latest button, and the Send button reads Branch

After Ctrl+Z the cube is square again, and the turn waits under **1 later turn**.
```

The turn is not lost. **Return to Latest** brings it back, scene and conversation. If you
send a new prompt from here instead, the button reads **Branch**: the new turn becomes a
second branch beside the first, and you can switch between them.
[History and branches](guides/history.md) explains the tree, and [Undo](guides/undo.md)
covers Ctrl+Z during a turn.

## If the sidebar asks for something

| The sidebar says | What to do |
|---|---|
| **Set up Claude to start** | Press **Set Up…** there, then **Download and Install**. |
| **Add an API key to start** | Press **Get a Key**, then **Preferences…**, and paste the key. |
| **Claude could not start** | Click the gear at the top of the panel for the reason. If it asks for online access, tick **Allow Online Access** (Preferences → System → Network), then press the box's **Restart** or **Restart and Retry**. |
| **The API key was refused** | Check the key in the Console, and paste it again. |

[Troubleshooting](guides/troubleshooting.md) has the rest.

## Where next

- [Walkthrough](walkthrough.md): a full session, from start to finish.
- [Sketching](guides/sketching.md): draw on the model to show Claude where and what.
- [Prompts and targets](guides/prompting.md): choose what Claude works on and how to ask.
- [Models and effort](guides/models.md): trade capability against speed and cost.
- [Chats](guides/chats.md): several conversations in one file, and what a saved `.blend`
  carries.
