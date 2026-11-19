---
name: use-bitwarden-window
description: Check a Bitwarden Window unlock timer on Omarchy or macOS, or create or verify its configured age recovery note when requested.
---

# Use Bitwarden Window

Run the scoped client on the computer named by the user, as the desktop user who installed it. Each computer has its own one-hour window.

- **Check the timer.** Run `~/.local/bin/bw-window status`. Exit 0 and a count of seconds mean the window is open. Exit 1 with `Bitwarden window closed or session unavailable.` means there is no open window. For other errors, report the client's message.
- **Open a window.** The user clicks **BW** and enters their password on that computer, or runs `bw-unlock` in their own terminal. Once they authenticate, retry the requested scoped command. Keep passwords and `BW_SESSION` out of chat, files and the agent's environment.
- **Check or save the recovery key.** Only when the user asks for this operation, run `~/.local/bin/bw-window recovery-note`. It can create the configured personal secure note if missing. Output and exit 0 confirm verification after sync. On a conflict or uncertain write, report the message and leave reconciliation to the owner. A status check alone does not verify a backup.
- **Close early.** Use `~/.local/bin/bw-window lock` only at the user's request. This also locks the native CLI profile used by other terminals.

Use these scoped commands directly. The optional full-CLI shell helper is for the human's interactive terminal. Keep the identity file and vault items out of tool output.
