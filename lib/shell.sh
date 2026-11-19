# Optional: source in an interactive Bash or Zsh before starting a new window.
bw-unlock() {
  case $- in *x*|*v*|*a*) printf '%s\n' 'Disable shell tracing and automatic export first.' >&2; return 2 ;; esac
  [ "$#" -eq 0 ] && [ -t 0 ] || { printf '%s\n' 'Usage: bw-unlock (in an interactive terminal)' >&2; return 2; }
  local bw_reply
  bw_reply=$("$HOME/.local/bin/bw-unlock" --shell) || return 1
  [ "$bw_reply" != open ] || return 0
  unset __bw_window_key __bw_window_until
  __bw_window_until=$((${bw_reply%% *} + 3600))
  __bw_window_key=${bw_reply#* }
  unset bw_reply
  printf '%s\n' 'Bitwarden window open. Full CLI access is available in this shell.'
}
bw() {
  case $- in *x*|*v*|*a*) printf '%s\n' 'Disable shell tracing and automatic export first.' >&2; return 2 ;; esac
  if [ -z "${__bw_window_until-}" ]; then
    "$HOME/.local/lib/bw-window/native-bw" "$@"
    return
  fi
  local bw_now
  bw_now=$("$HOME/.local/bin/bw-window" now) || return 1
  if [ "$bw_now" -ge "$__bw_window_until" ]; then
    unset __bw_window_key __bw_window_until
    printf '%s\n' 'Window expired. Run bw-unlock again.' >&2
    return 1
  fi
  if [ "$#" -eq 1 ] && [ "$1" = lock ]; then
    "$HOME/.local/bin/bw-window" lock || return 1
    unset __bw_window_key __bw_window_until
    return
  fi
  BW_SESSION="$__bw_window_key" "$HOME/.local/lib/bw-window/native-bw" "$@"
}
