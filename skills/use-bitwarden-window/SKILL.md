---
name: use-bitwarden-window
description: Check a Bitwarden Window unlock timer on Omarchy or macOS, create or verify its configured age recovery note, save a piped secret as a personal login item when requested, or pass a keyring-synced secret to a command without printing it.
---

# Use Bitwarden Window

Run the scoped client on the computer named by the user, as the desktop user who installed it. Each computer has its own one-hour window.

- **Check the timer.** Run `~/.local/bin/bw-window status`. Exit 0 and a count of seconds mean the window is open. Exit 1 with `Bitwarden window closed or session unavailable.` means there is no open window. For other errors, report the client's message.
- **Open a window.** The user clicks **BW** and enters their password on that computer, or runs `bw-unlock` in their own terminal. Once they authenticate, retry the requested scoped command. Keep passwords and `BW_SESSION` out of chat, files and the agent's environment.
- **Check or save the recovery key.** Only when the user asks for this operation, run `~/.local/bin/bw-window recovery-note`. It can create the configured personal secure note if missing. Output and exit 0 confirm verification after sync. On a conflict or uncertain write, report the message and leave reconciliation to the owner. A status check alone does not verify a backup.
- **Save a secret.** Only when the user explicitly asks to store a secret, pipe it from its source into `~/.local/bin/bw-window save "NAME"`, for example `ssh host 'cat path/to/file' | ~/.local/bin/bw-window save "NAME"`. Never pass the secret as an argument or environment variable, and never print it or the item. Optional `--username USER`, `--uri URL` and `--notes-file FILE` add metadata. Output and exit 0 confirm a created or identical login item after sync. The command never overwrites: on a conflict, report the message and leave changes to the owner. After an uncertain write, rerun the same command once to verify.
- **Use a synced secret.** For a name the user listed in `keyring_items` of `~/.config/bw-window/config.json`, pass `~/.local/bin/bw-window get "NAME"` straight to the consuming command: `~/.local/bin/bw-window get "NAME" | tool --token-stdin` or `TOKEN="$(~/.local/bin/bw-window get "NAME")" tool`. It works while the window is closed and prints the value without a trailing newline. Never run it in a way that shows the value in chat, logs or files, and never echo, inspect or compare it. Exit 1 means the name is not listed or has no copy since the last unlock; report the message and ask the user to unlock or adjust the list. Change `keyring_items` only at the user's request.
- **Close early.** Use `~/.local/bin/bw-window lock` only at the user's request. This also locks the native CLI profile used by other terminals.
- **Upgrade.** Only when the user asks, run `~/.local/bin/bw-window upgrade` (or `upgrade vX.Y.Z`) on that computer. It refuses while a window is open; report that and let the user decide whether to lock. Report its last line and exit code.

Use these scoped commands directly. The optional full-CLI shell helper is for the human's interactive terminal. Keep the identity file, secrets and vault items out of tool output.
