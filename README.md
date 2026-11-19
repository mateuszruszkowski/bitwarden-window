# Bitwarden Window for macOS

A menu-bar countdown for the official Bitwarden CLI on **Omarchy Linux** and **macOS**. Click **BW**, unlock once, and see how many minutes remain. The window lasts one hour from authentication, including time spent asleep. Using it from another terminal does not reset the timer.

Use it when a shell script or local assistant needs to check whether the vault is open, or to back up one dedicated age recovery key. The scoped client never returns the session token or the contents of a vault item. This is an independent project, unaffiliated with Bitwarden, Omarchy or age.

## macOS quick start

The native menu app and its broker start at graphical login. After installation click **BW** in the macOS menu bar. Use `~/.local/bin/bw-window status` from Terminal or from an SSH session under the same login.

## Install

Start in a desktop session as the user who will use the menu. Install the [official Bitwarden CLI](https://bitwarden.com/help/cli/) and log in with `bw login`. The window uses the account and server already selected in the CLI, including EU and self-hosted accounts.

| Platform | Requirements | Interface |
| --- | --- | --- |
| Omarchy | Omarchy Shell with the Quickshell plugin API, Hyprland (Lua rules for automatic centering), Ghostty, user systemd, system Python 3.13+ | **BW** next to the clock |
| macOS | macOS 13+, a graphical login, a non-system Python 3.10+ on PATH and a Swift 6 compiler (Xcode or Command Line Tools) | Native **BW** menu bar item and secure password field |

```sh
git clone --branch osx https://github.com/mateuszruszkowski/bitwarden-window.git
cd bitwarden-window
./install.sh
```

Run the installer from the same shell and profile where you use the official CLI. It installs under your home directory. The macOS menu and service start at graphical login. If `bw-window` is missing from your shell's PATH, use `~/.local/bin/bw-window` directly, or add `~/.local/bin` to PATH. The [Omarchy branch](https://github.com/mateuszruszkowski/bitwarden-window/tree/omarchy) and [macOS branch](https://github.com/mateuszruszkowski/bitwarden-window/tree/osx) include a platform-specific quick start. Use the root installer on all three branches so you get both the widget and its background service.

Use real directories for `~/.local`, `~/.config` and the parent directories of the recovery identity. The broker rejects symbolic links along these paths.

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

Give a local assistant the two commands below instead of a password or `BW_SESSION`.

| Command | Result |
| --- | --- |
| `~/.local/bin/bw-window status` | Remaining seconds while the window is open |
| `~/.local/bin/bw-window recovery-note` | Create or verify the one configured recovery note on explicit request |

A local process with access to your user account can call these operations. The tool is intended for trusted scripts on a trusted workstation. It is not a sandbox for untrusted same-user code. During a vault operation the official CLI receives its token in the child process environment. Code running as you, or as an administrator, can potentially inspect it, replace user-owned executables or read your local identity file. Expiry, manual lock and a macOS broker restart call `bw lock` for the same CLI profile. Expect other terminals using that profile to need a fresh unlock. If you run native `bw lock` yourself, the badge may continue counting down while the next recovery operation detects the locked vault. The desktop app and browser extension have their own unlock state.

## Update

From the cloned repository, close the active window with `~/.local/bin/bw-window lock`, run `git pull --ff-only` and rerun `./install.sh`. On Omarchy, run `omarchy restart shell` if the bar is still showing the previous widget. Use a stable CLI path such as the Arch `bitwarden-cli` package when possible.

## Remove

From the same checkout, run `./uninstall.sh`. Close the active window first. On Omarchy the installer uses the user systemd manager. On macOS removal unloads both login agents. Remove any `shell.sh` source line you added to your shell configuration. The personal config in `~/.config/bw-window/`, the recovery records in `~/.local/state/bw-window/`, the age identity and the Bitwarden vault item are preserved.

## Tests

Run `python3 -m unittest discover -s tests -v` as a regular user. The suite uses synthetic sessions and temporary homes. The Linux service tests use transient units in your systemd user manager. The macOS tests require a GUI login and use uniquely named temporary launchd jobs. Install `age-keygen` to run recovery-note tests. Platform-specific tests skip on other systems.

The Omarchy widget was validated with Omarchy Shell 4.0 development builds, Hyprland 0.57 and Ghostty 1.4. macOS builds target macOS 13 and newer. The menu and service run as LaunchAgents at graphical login, including in the background. Their definitions live at `~/Library/LaunchAgents/org.bitwardenwindow.{broker,menu}.plist`; the menu application is `~/.local/lib/bw-window/macos/Bitwarden Window.app`.

## Security reports and license

Use the repository's **Security** tab to report sensitive findings privately. Do not include a vault export, identity file, session token or password in a report. Licensed under the [MIT License](LICENSE).
