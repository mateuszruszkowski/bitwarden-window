#!/bin/bash
set -eu
umask 077
[[ $(uname -s) == Darwin && $(id -u) != 0 ]] || { echo 'Run as your macOS login user.' >&2; exit 1; }
cd "$(dirname "$0")"
python=
while IFS= read -r candidate; do
    if [[ $candidate != /* || $candidate -ef /usr/bin/python3 ]]; then continue; fi
    if "$candidate" -IB -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
        python=$candidate
        break
    fi
done < <(type -aP python3)
[[ -n $python ]] || { echo 'Put a non-system Python 3.10 or newer on PATH.' >&2; exit 1; }
exec "$python" -IB - "$PWD" "$@" <<'PY'
import contextlib
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import stat
import subprocess as sp
import sys
import tempfile
import time

src = Path(sys.argv[1])
remove = sys.argv[2:] == ["--uninstall"]
if sys.argv[2:] and not remove:
    sys.exit("Usage: install.sh [--uninstall]")
home = Path.home()
domain = f"gui/{os.getuid()}"
lib = home / ".local/lib/bw-window"
client = home / ".local/bin/bw-window"
state = home / ".local/state/bw-window"
agents = home / "Library/LaunchAgents"
marker = lib / ".bitwarden-window-public"
signature = b"bitwarden-window/v1\n"
mac = lib / "macos"
menu = mac / "Bitwarden Window.app/Contents/MacOS/BWWindowMenu"
broker_label = "org.bitwardenwindow.broker"
menu_label = "org.bitwardenwindow.menu"


def agent(label, argv, **options):
    return {"Label": label, "ProgramArguments": list(map(str, argv)), "RunAtLoad": True,
            "EnvironmentVariables": {"HOME": str(home)}, "Umask": 0o077, **options}


jobs = {broker_label: agent(broker_label, [client, "_daemon"], KeepAlive=True, ThrottleInterval=1,
                            AbandonProcessGroup=False, ExitTimeOut=60, SoftResourceLimits={"Core": 0},
                            HardResourceLimits={"Core": 0}),
        menu_label: agent(menu_label, [menu], KeepAlive={"Crashed": True}, LimitLoadToSessionType="Aqua")}


def plist(label):
    return agents / (label + ".plist")


def launch(*args, check=True):
    return sp.run(["/bin/launchctl", *args], check=check, capture_output=True)


def check_ownership():
    owned = (not lib.is_symlink() and not marker.is_symlink() and marker.is_file()
             and marker.read_bytes().rstrip(b"\n") == signature.rstrip(b"\n"))
    if os.path.lexists(lib) and not owned:
        sys.exit(f"Existing installation at {lib}. Move it before installing.")
    if os.path.lexists(client) and not (owned and client.is_symlink() and client.readlink() == mac / "client"):
        sys.exit(f"Existing command at {client}. Leaving it in place.")
    loaded = []
    for label, spec in jobs.items():
        file = plist(label)
        if os.path.lexists(file):
            if not owned or file.is_symlink() or not file.is_file():
                sys.exit(f"Existing launch agent at {file}. Leaving it in place.")
            installed = plistlib.loads(file.read_bytes())
            if any(installed.get(key) != spec[key] for key in ("Label", "ProgramArguments")):
                sys.exit(f"Existing launch agent at {file}. Leaving it in place.")
        info = launch("print", f"{domain}/{label}", check=False)
        if info.returncode == 0:
            lines = [line.strip() for line in info.stdout.decode(errors="replace").splitlines()]
            if not owned or not file.exists() or f"path = {file}" not in lines:
                sys.exit(f"Launch agent label already in use: {label}")
            loaded.append(label)
    if not owned and any(os.path.lexists(state / name) for name in ("daemon.lock", "control.sock")):
        sys.exit("An existing broker owns the runtime directory.")
    return owned, loaded


def stage_install(stage):
    python = Path(sys.executable)
    bw = shutil.which("bw")
    if not bw or not Path(bw).is_absolute():
        sys.exit("Put the Bitwarden CLI (bw) on PATH.")
    age = shutil.which("age-keygen")
    if age:
        age = os.path.abspath(age)
    bw_env = {"HOME": str(stage), "PATH": str(Path(bw).parent) + ":/usr/bin:/bin", "LC_ALL": "C"}
    binaries = [python, Path(bw)]
    if age:
        binaries.append(Path(age))
    for binary in binaries:
        st = binary.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid not in (0, os.getuid()) or st.st_mode & 0o022:
            sys.exit(f"Unsafe executable: {binary}")
    def probe(*args):
        return sp.check_output([bw, *args], env=bw_env, stdin=sp.DEVNULL, timeout=30, text=True).strip()

    version = probe("--version")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", version):
        sys.exit("bw did not report a Bitwarden CLI version.")
    if "--passwordfile" not in probe("unlock", "--help"):
        sys.exit("The selected bw does not support unlock --passwordfile.")
    if age:
        sp.run([age, "--version"], env=bw_env, timeout=10, capture_output=True, check=True)
    package = stage / "macos"
    bundle = package / "Bitwarden Window.app"
    binary = bundle / "Contents/MacOS/BWWindowMenu"
    binary.parent.mkdir(parents=True)
    shutil.copyfile(src / "Info.plist", bundle / "Contents/Info.plist")
    target = os.uname().machine + "-apple-macosx13.0"
    sp.run(["/usr/bin/xcrun", "swiftc", "-target", target, "-swift-version", "6", "-warnings-as-errors", "-O",
            str(src / "Menu.swift"), "-o", binary], check=True)
    sp.run(["/usr/bin/codesign", "--sign", "-", "--options", "runtime", bundle], check=True)
    sp.run(["/usr/bin/codesign", "--verify", "--strict", bundle], check=True)
    shutil.copyfile(src / "bw-window", package / "broker.py")
    script = shlex.join([str(python), "-IB", str(mac / "broker.py")])
    (package / "client").write_text(f'#!/bin/sh\nexec {script} "$@"\n')
    (package / "client").chmod(0o700)
    shutil.copyfile(src.parent / "lib/core.py", stage / "core.py")
    (stage / marker.name).write_bytes(signature)
    sp.run([python, "-I", src.parent / "lib/install-paths.py", stage / "paths.json", bw, age or ""], check=True)
    (stage / "bw-window").symlink_to(mac / "client")
    for label, spec in jobs.items():
        (stage / plist(label).name).write_bytes(plistlib.dumps(spec))


def require_closed(loaded):
    if broker_label in loaded:
        result = sp.run([client, "status"], capture_output=True, timeout=15)
        if result.returncode != 1 or not result.stderr.startswith(b"Bitwarden window closed"):
            sys.exit("Cannot confirm a closed window. Run ~/.local/bin/bw-window lock before changing the installation.")


def apply(stage, owned, loaded):
    backup = stage / "previous"
    backup.mkdir()
    stopped, moved, added, started = [], [], [], []
    targets = [mac, lib / "core.py", lib / "paths.json", marker, client, *map(plist, jobs)]
    try:
        for label in reversed(loaded):
            launch("bootout", f"{domain}/{label}")
            stopped.append(label)
        for target in targets:
            if os.path.lexists(target):
                target.rename(backup / target.name)
                moved.append(target)
            if not remove:
                target.parent.mkdir(parents=True, exist_ok=True)
                (stage / target.name).rename(target)
                added.append(target)
        if not remove:
            for label in jobs:
                launch("bootstrap", domain, plist(label))
                started.append(label)
            for _ in range(80):
                result = sp.run([client, "status"], capture_output=True, timeout=5)
                if result.returncode == 1 and result.stderr.startswith(b"Bitwarden window closed"):
                    break
                time.sleep(0.15)
            else:
                raise RuntimeError("The broker did not report a closed window after startup.")
    except BaseException:
        try:
            for label in reversed(started):
                launch("bootout", f"{domain}/{label}")
            for target in reversed(added):
                target.rename(stage / target.name)
            for target in moved:
                (backup / target.name).rename(target)
            if not owned:
                for name in ("control.sock", "daemon.lock"):
                    (state / name).unlink(missing_ok=True)
                with contextlib.suppress(OSError):
                    lib.rmdir()
            for label in reversed(stopped):
                launch("bootstrap", domain, plist(label))
        except BaseException as restore_error:
            recovery = Path(tempfile.mkdtemp(prefix=".bw-recovery-", dir=lib.parent))
            backup.rename(recovery / "previous")
            raise RuntimeError(f"Could not restore installation. Previous files saved in {recovery}.") from restore_error
        raise
    if remove:
        for name in ("control.sock", "daemon.lock"):
            (state / name).unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            lib.rmdir()


def main():
    for directory in (home / ".local", lib.parent, client.parent, state.parent, state,
                      home / "Library", agents):
        if directory.is_symlink():
            sys.exit(f"Unexpected symlink in installation path: {directory}")
    if remove and not lib.parent.exists():
        return
    lib.parent.mkdir(parents=True, exist_ok=True)
    directory = os.open(lib.parent, os.O_RDONLY | os.O_DIRECTORY)
    fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
    owned, loaded = check_ownership()
    if remove and not owned:
        return
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    meta = state.lstat()
    if meta.st_uid != os.getuid() or not stat.S_ISDIR(meta.st_mode) or stat.S_IMODE(meta.st_mode) != 0o700:
        sys.exit("The broker state directory must be private to your account.")
    flags = os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(state / "auth.lock", flags, 0o600), "rb") as auth:
        meta = os.fstat(auth.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid() or meta.st_mode & 0o077:
            sys.exit("Invalid authentication lock.")
        fcntl.flock(auth, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_closed(loaded)
        with tempfile.TemporaryDirectory(prefix=".bw-install-", dir=lib.parent) as directory:
            stage = Path(directory)
            if not remove:
                stage_install(stage)
            apply(stage, owned, loaded)
    print("Bitwarden Window removed." if remove else "Bitwarden Window installed for this login.")


try:
    main()
except BlockingIOError:
    sys.exit("An unlock or installation is already in progress.")
except (OSError, ValueError, RuntimeError, sp.SubprocessError) as exc:
    sys.exit(str(exc))
PY
