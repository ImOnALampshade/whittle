# Installing and updating

Whittle installs in two parts: the extension, which you add to Blender once, and the agent
environment, which the extension downloads when you ask it to. The *agent* is the program that
runs Claude beside Blender, and a *turn* is one prompt and the work Claude does on it. This page
covers both parts, then updating and removing them. When you are done, go on to
{doc}`API key and cost <api-key>`.

## What you need

- Blender 5.2 or later, whose Python is 3.13 or 3.14. blender.org's builds bundle 3.13. See
  [Platforms](#platforms) for the systems it runs on.
- An internet connection for setup, and about 320 MB of disk space for the agent environment.
  The largest download is about 114 MB.
- An {doc}`Anthropic API key <api-key>`, before your first turn.

## Install the extension

Whittle is not on extensions.blender.org yet, so you install a zip. Download
`whittle-0.1.0.zip` from the
[latest release](https://github.com/ImOnALampshade/whittle/releases/latest). One zip serves every
platform, and the `.sha256` file beside it is its checksum, to check the download against. Then
go on to [Install the zip](#install-the-zip).

### Build the zip yourself

You can build the zip from the source instead. That only packs the source into a zip: nothing is
compiled.

Get the source from [Whittle's GitHub page](https://github.com/ImOnALampshade/whittle): choose
**Code → Download ZIP** and unpack it, or run
`git clone https://github.com/ImOnALampshade/whittle.git`. Then open a terminal in the folder
that holds `build.sh`.

On Linux, run:

```sh
./build.sh            # validates, then writes build/whittle-0.1.0.zip
```

This needs Blender on your `PATH`, the list of folders your terminal looks in for programs. If
`blender --version` prints a version, it is. If not, add the folder that holds `blender` to your
`PATH`, or use the commands below with its full path.

`build.sh` is a POSIX shell script that uses GNU `timeout`, so on Windows and macOS run the
commands in it yourself, with Blender's full path in place of `blender`:

```sh
mkdir build
blender --factory-startup --command extension validate whittle
blender --factory-startup --command extension build --source-dir whittle --output-dir build
```

| System | Blender's full path, if you installed it in the usual place |
|---|---|
| Windows, in Command Prompt | `"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"` |
| macOS | `/Applications/Blender.app/Contents/MacOS/Blender` |

On a Mac, `./build.sh` works too once Blender is on your `PATH` and `brew install coreutils` has
provided `timeout`.

Either way the zip lands in the `build` folder, as `whittle-0.1.0.zip`.

### Install the zip

In Blender:

1. Open **Edit → Preferences → Get Extensions**. If an **Online Extensions** box appears, press
   its **Allow Online Access**: Whittle needs that, and it is the same switch as in
   [Allow online access](#allow-online-access). **Continue Offline** leaves it off.
2. Click the arrow to the right of **Repositories**, and choose **Install from Disk…**.

```{figure} ../images/guides-installation/install-from-disk.png
:alt: The Extension Settings menu, with Install from Disk at the bottom.

The menu behind the arrow to the right of **Repositories**.
```

3. Pick `whittle-0.1.0.zip`. Leave **Enable on Install** ticked in the file browser's
   options.

```{figure} ../images/guides-installation/install-options.png
:alt: The file browser's options, with Enable on Install ticked and the User Default repository chosen.

On by default.
```

Whittle now has a tab in the 3D viewport's sidebar (press N): see {doc}`The sidebar <sidebar>`.

## Allow online access

Turn on **Preferences → System → Network → Allow Online Access**. Without it Whittle cannot
download the agent environment or start the agent, and it says so. If you pressed **Allow Online
Access** in the **Online Extensions** box, this is already on.

```{figure} ../images/guides-installation/online-access.png
:alt: The Network panel of the System preferences, with Allow Online Access not yet ticked.

Blender's own switch, off here. Tick it.
```

## Set up the agent environment

1. Open **Preferences → Add-ons → Whittle**, and find the **Agent Environment** box.

```{figure} ../images/guides-installation/environment-not-set-up.png
:alt: The Agent Environment box with an empty Environment Folder field, the status Not set up yet, and the buttons Set Up Agent Environment and Reinstall.

Before setup. An empty **Environment Folder** means Whittle's own folder.
```

2. Press **Set Up Agent Environment**. A dialog says what it will download and where to.
   Nothing starts until you confirm.

```{figure} ../images/guides-installation/environment-confirm.png
:alt: A dialog titled Set Up Agent Environment reading Download 30 pinned packages incl. claude-agent-sdk 0.2.167 from PyPI into a folder, with Cancel and Download and Install buttons.

The folder is the one this setup will use.
```

3. Press **Download and Install**.

The status line follows the download, and the last lines of the setup's log appear under the
button. You can keep working in Blender and open other files while it runs. **Cancel Setup**
stops it.

```{figure} ../images/guides-installation/environment-downloading.png
:alt: The Agent Environment box during setup. The status reads Setting up, install, claude_agent_sdk, 43.1 of 114.1 MB. Below are a Cancel Setup button and eight lines of the log.

Partway through the largest file.
```

A slow connection is fine. Setup gives up only when no data arrives for 5 minutes, or after 3
hours in all. If it does, see [Setup failed](troubleshooting.md#setup-failed).

When the status reads **Ready**, setup is done.

```{figure} ../images/guides-installation/environment-ready.png
:alt: The Agent Environment box with a check mark and the status Ready, claude-agent-sdk 0.2.167.

Set up. The version is the agent package the environment holds.
```

You can also start from the sidebar. If you press **Send** with no environment, Send goes dim,
your prompt stays, and a box offers the same setup. **Set Up…** opens the same dialog, and the
box shows the progress with a **Cancel** button.

```{figure} ../images/guides-installation/sidebar-set-up.png
:alt: The Whittle sidebar with a box reading Set up Claude to start and a Set Up button, above the prompt Add a lid and a dim Send button.

The sidebar's offer.
```

### What setup does, and why

The agent is a separate program beside Blender, and it needs Python packages that Blender does
not have. Whittle keeps them in a private folder, so nothing is added to Blender's own Python,
and setup leaves no copy of them anywhere else. The packages are not in the zip because they
differ per platform: the zip stays the same everywhere, and setup fetches your platform's files.

Setup has three steps, and the status names each one:

1. **create**: makes a private Python environment from Blender's own Python.
2. **install**: downloads the 30 packages listed in the extension's `requirements.lock` (31 on
   Windows, with `pywin32`) from PyPI, among them Anthropic's `claude-agent-sdk`, which brings the Claude program the agent
   is built on.
3. **verify**: checks that the package loads, is the version the lock names, and brought that
   program with it. Only then does the environment count as ready.

These packages run on your computer with your key, so setup is strict about them:

- **Every file is checked.** The lock holds the exact version of each package and a hash, a
  fingerprint of its contents, for each file allowed. A file that does not match stops the
  install.
- **Wheels only.** A wheel is a prebuilt package, so nothing is compiled on your computer and
  no package's own install code runs.
- **Only what the lock lists.** Nothing beyond it is looked up or added.
- **From PyPI.** Setup names PyPI itself, drops pip and Python settings from its environment
  variables and ignores your own pip config. A mirror named in a system-wide pip config does not
  apply, so setup needs to reach pypi.org. That config's proxy and certificate settings still
  apply, and so do any extra sources it adds, but a file that does not match the lock's hash is
  refused either way. Proxy settings such as `HTTPS_PROXY` still apply.
- **Only when you say so.** Setup starts from the dialog alone, never by itself and never during
  a turn. Nothing is ever upgraded on its own.

### Put the environment somewhere else

Before setup, set **Environment Folder** to a new or empty folder. Empty means the `venv`
folder inside Whittle's user folder, which is:

| System | Whittle's user folder |
|---|---|
| Linux | `~/.config/blender/5.2/extensions/.user/user_default/whittle/` |
| Windows | `%APPDATA%\Blender Foundation\Blender\5.2\extensions\.user\user_default\whittle\` |
| macOS | `~/Library/Application Support/Blender/5.2/extensions/.user/user_default/whittle/` |

Whittle looks only at the folder set now. If you change it after setup, the status describes the
new folder, and the old one stays on disk until you delete it.

## What the status says

The line in the **Agent Environment** box tells you what to do next.

| Status | Meaning | What to do |
|---|---|---|
| **Not set up yet** | The folder is missing or empty. | Press **Set Up Agent Environment**. |
| **Setting up: …** | A step is running. | Wait, or press **Cancel Setup**. |
| **Ready: claude-agent-sdk …** | The environment matches this version of Whittle. | Nothing. |
| **Setup failed: …** | The reason follows, with the log's last lines under the buttons. | See [Setup failed](troubleshooting.md#setup-failed). |
| **Setup cancelled: …** | You stopped it. | Press **Set Up Agent Environment** to start again. |
| **Set up for an earlier version of Whittle: reinstall** | An update brought a different lock. | Press **Reinstall**. |
| **Incomplete or its Python is gone: reinstall** | A setup did not finish, or the Python it was made from was moved or removed. | Press **Reinstall**. |
| **The folder holds something Whittle did not make** | **Environment Folder** points at a folder with other files in it. Whittle will not overwrite them. | Choose another folder, or remove that one. |

**Reinstall** rebuilds the environment from scratch, after the same kind of dialog, and downloads
every file again. On a working environment it is rarely needed, and **Set Up Agent
Environment** refuses to run there. Both buttons are dim during a turn.

When the environment is not **Ready**, a developer who points Whittle at another Python sees it
named at the end of the status: see
{doc}`Development setup and testing <../develop/setup-and-testing>`.

The log of each setup is `logs/venv-<time>.log` in Whittle's user folder.

## Platforms

| Platform | Status |
|---|---|
| Linux x64 | Developed on a distribution's Blender with Python 3.14. blender.org's build (Python 3.13) has passed the offline tests in CI, but not a real agent turn. |
| Linux arm64 | Untested: blender.org publishes no build for it, so the automated tests cannot run it. Reports welcome. |
| Windows x64 | The agent-side tests have passed on GitHub's runners, but the Blender tests cannot finish there. Real use is untested: reports welcome. |
| macOS on Apple silicon | The offline tests have passed on GitHub's runners. Real use is untested: reports welcome. |
| macOS on Intel | Not supported. |
| Windows on Arm | Not supported. |

Whittle needs a build of each package for your platform. Intel Macs lack one for `cryptography`,
and Blender 5.2 has no Intel Mac build either. Windows on Arm lacks one for `claude-agent-sdk`.
The extension lists only the four platforms it can run on, so on any other Blender refuses the zip
at **Install from Disk…**, with a message that this platform is not one of those listed.

Windows paths can get long. If a turn fails on a path over 260 characters, turn on Windows' long
path support, or choose a shorter **Environment Folder**.

## Update Whittle

Blender does not offer updates for an extension installed from disk, and Whittle never updates
itself.

1. Wait for any turn or setup to finish: updating stops them.
2. Download or build the newer zip, and install it with **Install from Disk…**, as in
   [Install the extension](#install-the-extension). Blender replaces the old version.
3. Open **Preferences → Add-ons → Whittle**, and read the status.

An update keeps your preferences, your API key, your chats and the agent environment.

If the new version ships the same lock, the status stays **Ready**. If its lock is different, the
environment no longer matches.

```{figure} ../images/guides-installation/environment-earlier-version.png
:alt: The Agent Environment box with a warning icon and the status Set up for an earlier version of Whittle, reinstall.

After an update with a different lock. The sidebar says the same when you press **Send**.
```

Press **Reinstall** and confirm. The agent cannot start until you do, and Whittle does not rebuild
the environment on its own, so an update never downloads anything you did not agree to.

## Turn Whittle off or uninstall it

**To turn it off**, untick Whittle in **Preferences → Add-ons**. Its files stay, so the environment
needs no new setup when you tick it again. Blender forgets a disabled add-on's preferences,
though: you will enter your API key and your
[**Defaults**](settings.md#change-a-setting-for-every-file) again, and point **Environment Folder**
back if you had moved it.

**To uninstall it:**

1. Open **Preferences → Get Extensions**, and search for Whittle.
2. Open the menu at the right of its row, and choose **Uninstall**.

```{figure} ../images/guides-installation/extension-row.png
:alt: Whittle's row under Installed in Get Extensions, with a small arrow button at its right end.

The menu is the arrow at the end of the row.
```

Uninstalling removes:

- the extension;
- Whittle's user folder: the environment if it is in the default place, the setup and agent logs,
  and the chat cache;
- Whittle's preferences, your API key among them.

It leaves:

- your `.blend` files, with the chats saved in them;
- an **Environment Folder** you chose yourself. Delete that folder by hand.

If you install Whittle again later, it counts as a new install, so chats in older files open
with Send disabled until you continue them: see
[Open a chat made on another machine](chats.md#open-a-chat-made-on-another-machine).
