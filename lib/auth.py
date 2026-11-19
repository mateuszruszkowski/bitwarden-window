"""Interactive unlock. Only the initiating shell may receive the fresh CLI token."""
import fcntl
import json
import os
from pathlib import Path
import pwd
import resource
import signal
import stat
import subprocess
import sys


def main():
    if sys.argv[1:] in (["--help"], ["-h"]):
        print("Usage: bw-unlock  (open a one-hour Bitwarden window)")
        return
    shell_mode = sys.argv[1:] == ["--shell"]
    if sys.argv[1:] not in ([], ["--shell"]) or not sys.stdin.isatty():
        sys.exit("Run bw-unlock in an interactive terminal.")
    if shell_mode and not stat.S_ISFIFO(os.fstat(1).st_mode):
        sys.exit("Source shell.sh to enable full CLI access in this terminal.")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    settings = json.loads((home / ".local/lib/bw-window/paths.json").read_text())
    native = Path(settings["bw"])
    broker = home / ".local/bin/bw-window"
    state = home / ".local/state/bw-window"
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = state.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        sys.exit("The bw-window state directory must be private (0700).")
    env = {**settings.get("cli_env", {}), "HOME": str(home), "PATH": f"{native.parent}:/usr/bin:/bin",
           "TERM": os.environ.get("TERM", "xterm-256color"), "LANG": "en_US.UTF-8"}
    lockfd = os.open(state / "auth.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(lockfd, "rb") as lock:
        mode = os.fstat(lock.fileno())
        if not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.getuid() or mode.st_mode & 0o077:
            sys.exit("Invalid authentication lock.")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit("An unlock is already in progress.")
        status = subprocess.run([broker, "status"], capture_output=True, env=env)
        if status.returncode == 0:
            sys.stderr.buffer.write(status.stdout)
            if shell_mode:
                print("Full CLI access is available only in the shell that opened the window. To start here, run bw-window lock first.", file=sys.stderr)
                print("open")
            return
        if status.returncode != 1:
            sys.exit("Check the local Bitwarden Window installation.")
        def interrupted(*_):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, interrupted)
        try:
            result = subprocess.run([native, "unlock", "--raw"], stdout=subprocess.PIPE, env=env)
            token = result.stdout.strip()
            if result.returncode or not 0 < len(token) <= 1024 or not all(32 < b < 127 for b in token):
                raise ValueError("unlock")
            stamp = subprocess.check_output([broker, "now"], env=env).strip()
            if not stamp.isdigit():
                raise ValueError("clock")
            subprocess.run([broker, "start", stamp], input=token, stdout=subprocess.DEVNULL, env=env, check=True)
        except (ValueError, OSError, subprocess.SubprocessError, KeyboardInterrupt):
            if subprocess.run([broker, "status"], capture_output=True, env=env).returncode:
                relock = subprocess.run([native, "--nointeraction", "lock"], capture_output=True, env=env)
                if relock.returncode:
                    sys.exit("Unlock failed and the CLI lock was not confirmed. Run bw lock in your terminal.")
            sys.exit("Unlock was cancelled or the one-hour window could not start.")
        if shell_mode:
            sys.stdout.buffer.write(stamp + b" " + token)
        else:
            print("Bitwarden window open for one hour.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError):
        sys.exit("Check the Bitwarden Window installation and permissions.")
