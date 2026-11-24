# Installing Bitwarden Window for a user

Use the **v0.6.0** release on the target computer, in the user's graphical login session and usual Bitwarden CLI profile. The root installer selects Omarchy or macOS. Use the user's normal permissions. [README and downloads](README.md#install)

## Before installation

- Check that the official `bw` executable is on PATH. Use `bw login --check` to check sign-in. The user signs in with `bw login` and enters their own credentials locally.
- On **Omarchy**, check for Omarchy Shell with the Quickshell plugin API, Hyprland, Ghostty, user systemd and system Python 3.13+. On **macOS 13+**, use a non-system Python 3.10+ on PATH and a Swift 6 compiler. Recovery-note support also needs `age-keygen`.
- If `~/.local/bin/bw-window` exists, run its `status` command. An open window can stay in use until expiry. Close it early only at the user's request. The marker `~/.local/lib/bw-window/.bitwarden-window-public` identifies a public installation. Preserve existing files when the installer reports an ownership conflict.

## Install

For a fresh checkout, run the pinned command in the [README](README.md#install-with-a-coding-agent). If you already extracted the v0.6.0 archive for this platform, run `./install.sh` from its root. This installs the menu, background service, CLI and the [use-bitwarden-window skill](skills/use-bitwarden-window/SKILL.md). Keep the directory for `./uninstall.sh`.

## Verify

| Platform | Check |
| --- | --- |
| Omarchy | `omarchy plugin list` shows `community.bitwarden-window` as enabled. `systemctl --user is-enabled bw-window-relock.service` prints `enabled`. |
| macOS | `launchctl print "gui/$(id -u)/org.bitwardenwindow.broker"` and `launchctl print "gui/$(id -u)/org.bitwardenwindow.menu"` both show `state = running`. |

Run `~/.local/bin/bw-window status`. A fresh installation normally reports `Bitwarden window closed or session unavailable.` with exit 1. Use the platform checks above alongside that result. An open window prints the remaining seconds and exits 0. Report other errors with their message.

Check that `~/.agents/skills/use-bitwarden-window/SKILL.md` (Codex) and `~/.claude/skills/use-bitwarden-window/SKILL.md` (Claude Code) are readable. If the installer preserved a conflicting entry or skipped a linked registry, report which agent was affected. Start a fresh agent session to pick up the skill.

For a live unlock test, the user clicks **BW** and enters their password locally. Check `status` again from a separate terminal. Agents use the scoped client without sourcing the full-CLI shell helper or requesting the master password or `BW_SESSION`.

Run `~/.local/bin/bw-window recovery-note` only when the user requests a backup or verification of the configured age key. It can create a personal vault item. Report success only on exit 0 and keep the key and vault contents out of output. Run `~/.local/bin/bw-window save NAME` only when the user explicitly asks to store a secret, with the secret piped on standard input and kept out of output.
