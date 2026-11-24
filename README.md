# Bitwarden Window

A menu-bar countdown for the official Bitwarden CLI on **Omarchy Linux** and **macOS**. Click **BW**, unlock once, and see how many minutes remain. The window lasts one hour from authentication, including time spent asleep. Using it from another terminal does not reset the timer.

Use it when a shell script or local assistant needs to check whether the vault is open, or to back up one dedicated age recovery key. The scoped client never returns the session token or the contents of a vault item. This is an independent project, unaffiliated with Bitwarden, Omarchy or age.

## Install

**[Download for Omarchy (.tar.gz)](https://github.com/mateuszruszkowski/bitwarden-window/releases/download/v0.8.1/bitwarden-window-0.8.1-omarchy.tar.gz)** · **[Download for macOS (.zip)](https://github.com/mateuszruszkowski/bitwarden-window/releases/download/v0.8.1/bitwarden-window-0.8.1-macos.zip)** · [Release notes](https://github.com/mateuszruszkowski/bitwarden-window/releases/tag/v0.8.1) · [SHA-256 checksums](https://github.com/mateuszruszkowski/bitwarden-window/releases/download/v0.8.1/SHA256SUMS)

1. Install the [official Bitwarden CLI](https://bitwarden.com/help/cli/) and sign in with `bw login`. If you already use the CLI, keep your current account and server.
2. Download and extract the archive for your desktop. On macOS, double-click the ZIP in Finder. On Omarchy, choose **Extract Here** in the file manager.
3. Open a terminal in the extracted folder and run `./install.sh` as your usual desktop user. Use the same shell and profile where you use `bw`. Keep the folder for `./uninstall.sh`.

Or run the same command on either system, from a directory where you keep software. It needs `git` and selects Omarchy or macOS itself.

```sh
git clone --depth 1 --branch v0.8.1 https://github.com/mateuszruszkowski/bitwarden-window.git bitwarden-window && (cd bitwarden-window && ./install.sh)
```

Later releases install with `bw-window upgrade`. See [Update](#update).

The Omarchy package requires Omarchy Shell with the Quickshell plugin API, Hyprland, Ghostty, user systemd and system Python 3.13+. The macOS package requires macOS 13+, a graphical login, a non-system Python 3.10+ on PATH and Swift 6 from Xcode or the Command Line Tools. Its installer builds the native menu app locally and starts it at graphical login.

### What's in v0.8.1

v0.8.1 adds `bww`, a short name for `bw-window` such as `bww status` or `bww lock`, accepts `update` as another name for `upgrade`, and puts `~/.local/bin` on your PATH when it is missing. v0.8.0 added `bw-window upgrade`, which downloads, verifies and installs a newer release on either system. v0.7.0 added an optional copy of selected login passwords into the system keyring and `bw-window get NAME` to read them while the window is closed. It is off unless you list items in `keyring_items`. v0.6.0 added `bw-window save`, and v0.5.0 was the first release of Bitwarden Window for Omarchy and macOS.

- A **BW** button next to the Omarchy clock or in the macOS menu bar. Unlock once to start a 60-minute countdown on that computer.
- A `bw-window status` command for other terminals, SSH sessions and local assistants. Source the optional shell helper to use the full CLI in the terminal where you unlock.
- A bundled [Agent Skill](skills/use-bitwarden-window/SKILL.md) for Codex and Claude Code. It teaches the agent to check the timer and handle an explicitly requested recovery-key backup or secret save.
- An optional `bw-window recovery-note` command to create or verify one personal secure note for an age backup key. Unlocking alone never writes a note.
- An optional `bw-window save NAME` command to create or verify one personal login item from a secret piped on standard input.
- An optional [keyring copy](#optional-keyring-copy) of listed login passwords, refreshed at each unlock and read with `bw-window get NAME`.

The installer puts the commands in `~/.local/bin`. If that directory is not on your PATH, it adds one marked line to `~/.zshrc`, or to `~/.bashrc` (`~/.bash_profile` on macOS) for bash, and removal deletes it. Open a new terminal afterwards. With another shell, add the directory yourself or use the full paths below. Use real directories for `~/.local`, `~/.config` and the parent directories of the recovery identity. The broker rejects symbolic links along these paths.

### Install with a coding agent

Paste this into your coding agent on the computer where you want the BW button.

```text
Install Bitwarden Window v0.8.1 from https://github.com/mateuszruszkowski/bitwarden-window. Follow AGENTS.md at that tag and verify the BW menu and CLI status. I’ll sign in and unlock locally.
```

For a fresh installation, the agent runs the [one-line command](#install) as your desktop user. On Omarchy it can run over SSH while you are logged in to the desktop. After installation, `~/.local/bin/bw-window status` reports a closed window until you unlock. For an existing installation, use the [agent guide](https://github.com/mateuszruszkowski/bitwarden-window/blob/v0.8.1/AGENTS.md). Both downloadable packages also include it.

## Account and server

If `bw` is already signed in to the right account, the default settings are ready to use. You do not need an account ID. Run `bw config server` to see the CLI server. To set up a new CLI profile, choose the server **before** `bw login`. [Bitwarden CLI documentation](https://bitwarden.com/help/cli/#config)

| Server | CLI setup |
| --- | --- |
| Bitwarden US | The default on a fresh CLI profile, or `bw config server https://vault.bitwarden.com` |
| Bitwarden EU | `bw config server https://vault.bitwarden.eu` |
| Self-hosted | `bw config server https://vault.example.org` with your own HTTPS address |

Optionally restrict Bitwarden Window to one server. Run `install -d -m 700 ~/.config/bw-window` and add `"server_url": "https://vault.bitwarden.eu"` to the JSON object in `~/.config/bw-window/config.json`. A file with that single property is valid. Set mode `0600` on the file. This checks the address reported by the CLI. Use the official CLI to change servers.

Installation records the selected CLI executable, profile directory (`BITWARDENCLI_APPDATA_DIR` or `XDG_CONFIG_HOME`), private CA **path** (`NODE_EXTRA_CA_CERTS`) and credential-free HTTP(S) proxy settings. This lets the menu, shell and background service use the same profile. Update the installation after moving the CLI, changing these settings or adding `age-keygen`.

## Open a window

1. Click **BW**, or run `~/.local/bin/bw-unlock` in an interactive terminal.
2. Enter your master password locally. The badge changes to a countdown such as **BW 59 min**.
3. In a different terminal on the same computer, run `~/.local/bin/bw-window status`. It reports the seconds remaining in the local lease. The recovery-note operation also checks the actual vault session. Each computer has its own timer.

Run `~/.local/bin/bw-window lock` to close the window early. To use the full Bitwarden CLI in one terminal, run these commands there **before opening the window**. If the menu already opened a window, run `~/.local/bin/bw-window lock` first.

```sh
. "$HOME/.local/lib/bw-window/shell.sh"
bw-unlock
```

Use this in interactive Bash or Zsh with `set -x`, `set -v` and `set -a` off. Only the shell that starts the window this way receives the fresh token. Other terminals and agents keep using the scoped client. Closing the originating terminal ends its shell-local access; the background window continues until lock or expiry.

## Optional recovery note

This feature stores **a private age identity** in **your personal Bitwarden vault**. Anyone who can read that vault item can decrypt backups encrypted to the corresponding recipient. The menu and countdown also work without this feature. Unlocking alone does not upload a key.

Install `age-keygen` (from [age](https://github.com/FiloSottile/age)) before installation if you want this feature. Use a dedicated identity file you already own, with one private key and mode `0600`. Create `~/.config/bw-window` with mode `0700` and a private `config.json` (mode `0600`). Example:

```json
{
  "identity_file": "~/.config/my-backup/recovery.agekey",
  "note_title": "My backup recovery key"
}
```

No account ID or server setting is required. The next window follows the account currently selected in `bw`. Within an open window, a change of account or server stops the recovery operation. To use a new account, start a new window.

Set up or edit the recovery configuration **before unlocking**. If you edited it during an open window, run `~/.local/bin/bw-window lock` and open a fresh window first. To create or verify the note, run

```sh
~/.local/bin/bw-window recovery-note
```

The command syncs the vault, creates the named personal secure note if absent, and checks its identity against the local file after sync. On a conflict, inspect the named item in the official Bitwarden app. Treat a nonzero exit as an unverified backup. A successful check confirms the saved key. Test a restore separately with your backup software. If several computers share a vault, create and verify the note on one computer before using the others.

If a write loses its reply, the tool reports an ambiguous recovery note and blocks another create on this computer. Search the personal vault, archive and trash for the exact title. Close the window, inspect the matching local record in `~/.local/state/bw-window/escrow-*.json` and keep a copy before reconciling it. An empty record marks an uncertain write. Once you have confirmed the remote state, move only that record aside, open a fresh window and retry. The `obsidian` command remains an alias for `recovery-note`.

## Local automation

The installer registers **`use-bitwarden-window`** under `~/.agents/skills/` for Codex (including Codex sessions in T3) and `~/.claude/skills/` for Claude Code. In a new session on the target computer, try one of these prompts.

| Agent | Example prompt |
| --- | --- |
| Codex | `$use-bitwarden-window How many minutes are left on this computer?` |
| Claude Code | `/use-bitwarden-window Check the timer on this computer.` |

A status request only checks the timer. If the window is closed, unlock locally with **BW** and ask the agent to check again. Ask explicitly to create or verify the configured recovery note, or to save a secret. An agent passes a [keyring copy](#optional-keyring-copy) to a command through a pipe or `$(...)` and does not show it in chat. The agent uses the following commands.

| Command | Result |
| --- | --- |
| `~/.local/bin/bw-window status` | Remaining seconds while the window is open (exit 0). A closed window exits 1 |
| `~/.local/bin/bw-window recovery-note` | Create or verify the one configured recovery note on explicit request |
| `~/.local/bin/bw-window save NAME [--username USER] [--uri URL] [--notes-file FILE] < SECRET` | Create or verify one personal login item on explicit request |
| `~/.local/bin/bw-window get NAME` | Print one value copied to the keyring at the last unlock, for a name in `keyring_items` |
| `~/.local/bin/bw-window upgrade [vX.Y.Z]` | Install the latest or the given release while the window is closed, at your request. `update` is the same command |

`bww` is a short name for `bw-window` and takes the same commands, for example `bww status`, `bww lock` or `bww update`.

`save` stores one secret, such as an API key, as the password of a personal login item named `NAME`. It reads the secret only from piped standard input, never from arguments or the environment: one line of printable text of at most 3072 bytes, with the trailing newline removed. For example, run `ssh host 'cat ~/.config/app/token' | ~/.local/bin/bw-window save "App API key"`. The command never edits or deletes an item. If an item with the same name already holds the same secret and every supplied option, it is only verified. Any other matching item, including one in the archive or trash, is reported as a conflict and left unchanged. Like the recovery note, `save` requires an HTTPS server, stops if the account or server changes, and verifies the item after sync. It prints one result line and never prints the secret or the item. After an uncertain write, run the same command again to verify the item.

A local process with access to your user account can call these operations. The tool is intended for trusted scripts on a trusted workstation. It is not a sandbox for untrusted same-user code. During a vault operation the official CLI receives its token in the child process environment. Code running as you, or as an administrator, can potentially inspect it, replace user-owned executables or read your local identity file. Expiry, manual lock and a macOS broker restart call `bw lock` for the same CLI profile. Expect other terminals using that profile to need a fresh unlock. If you run native `bw lock` yourself, the badge may continue counting down while the next recovery operation detects the locked vault. The desktop app and browser extension have their own unlock state.

## Optional keyring copy

This feature copies the passwords of **listed** login items into the system keyring, so scripts can read them while the window is closed. It changes the security model: a process running as you can read a copied value without your master password, for as long as your keyring is unlocked. It is off by default. Keep the list short and limit it to keys you would also keep in a local credentials file. Copies use the macOS login keychain through `/usr/bin/security`, or the Secret Service (for example GNOME Keyring) through `secret-tool` on Linux. Install `libsecret` and run a Secret Service provider on Omarchy before using it.

List exact item names in `~/.config/bw-window/config.json`:

```json
{
  "keyring_items": ["App API key", "Mail relay password"]
}
```

At each unlock, after the window opens, the broker syncs the vault and stores the password of each listed personal or shared login item under the service `bitwarden-window`, with the item name as the account. It overwrites the previous copy, so a changed password reaches the keyring at the next unlock. It removes copies for names you take off the list. The window opens even if a copy fails. A name that matches no item, several items (for example a personal item and a shared item with the same name), or an item that is not a login with a password of at most 1024 printable ASCII characters is not copied, and any earlier copy is removed. If the vault sync fails, earlier copies are kept. Names must match the item name exactly, including case. List at most 32 names of at most 128 characters each, without `"`, `\`, a leading `-` or surrounding spaces. Edit the list before unlocking; the next unlock applies it.

Read a copied value with

```sh
~/.local/bin/bw-window get "App API key" | some-tool --token-stdin
TOKEN="$(~/.local/bin/bw-window get "App API key")"
```

`get` prints the value to standard output **without a trailing newline** and exits 0. It works while the window is open or closed. It reads only names that are still in `keyring_items`, and it exits 1 with a message on standard error when the name is not listed or no copy is available. `status` adds a line such as `Keyring: 1 of 2 listed items synced at the last unlock; not synced: Mail relay password (missing).` The codes are `missing`, `duplicate`, `unsupported`, `keyring` (the keyring refused or failed) and `vault` (the vault could not be read). On macOS `status` shows `pending` while the copy is still running just after an unlock. The broker never prints, logs or passes a value on a command line. A copy stays in the keyring until the next unlock after you remove its name, and uninstalling does not remove copies. To remove all of them, empty the list or delete it, then unlock once.

## Update

Close the active window with `bw-window lock`, then run

```sh
bw-window upgrade
```

`bw-window update`, `bww upgrade` and `bww update` do the same. Since v0.8.1 the installer puts `~/.local/bin` on your PATH. If your shell reports `command not found`, open a new terminal or use the full path `~/.local/bin/bw-window`.

It refuses while a window is open. It downloads the latest release package for your system, checks it against the release `SHA256SUMS` and runs its installer. Give a tag such as `v0.8.0` to install that release instead, including an earlier one to roll back. Packages are kept in `~/.local/share/bw-window/releases/`: the installed one, for `./uninstall.sh`, and the one it replaced. The checksum detects a damaged download. It does not protect against a compromised GitHub account, see [SECURITY.md](SECURITY.md).

Versions before v0.8.0 do not have `upgrade`. To update one of them, close the window and either extract the [current release](https://github.com/mateuszruszkowski/bitwarden-window/releases/tag/v0.8.1) into a fresh folder and run its `./install.sh`, or, in a clean Git checkout whose `origin` is this project's GitHub repository, run

```sh
git fetch --depth 1 origin +refs/tags/v0.8.1:refs/tags/v0.8.1
git switch --detach v0.8.1
./install.sh
```

On Omarchy, run `omarchy restart shell` if the bar is still showing the previous widget. Use a stable CLI path such as the Arch `bitwarden-cli` package when possible.

## Remove

Close the active window with `~/.local/bin/bw-window lock`. Run `./uninstall.sh` from the extracted folder or Git checkout for the installed version, or from its package in `~/.local/share/bw-window/releases/` after an upgrade. On Omarchy the installer uses the user systemd manager. On macOS removal unloads both login agents. Removal cleans up the skill copies installed by the package. Installation, updates and removal preserve existing or locally edited skills with the same name. Linked registry directories are skipped. It also deletes `bww` and the PATH line added by the installer. Remove any `shell.sh` source line you added to your shell configuration. The personal config in `~/.config/bw-window/`, the recovery records in `~/.local/state/bw-window/`, the age identity and the Bitwarden vault item are preserved.

## Tests

Run `python3 -m unittest discover -s tests -v` as a regular user. The suite uses synthetic sessions and temporary homes. The Linux service tests use transient units in your systemd user manager. The macOS tests require a GUI login and use uniquely named temporary launchd jobs. Install `age-keygen` to run recovery-note tests. Platform-specific tests skip on other systems.

The Omarchy widget was validated with Omarchy Shell 4.0 development builds, Hyprland 0.57 and Ghostty 1.4. macOS builds target macOS 13 and newer. The menu and service run as LaunchAgents at graphical login, including in the background. Their definitions live at `~/Library/LaunchAgents/org.bitwardenwindow.{broker,menu}.plist`; the menu application is `~/.local/lib/bw-window/macos/Bitwarden Window.app`.

## Security reports and license

Use the repository's **Security** tab to report sensitive findings privately. Do not include a vault export, identity file, session token or password in a report. Licensed under the [MIT License](LICENSE).
