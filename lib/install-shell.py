"""Install the shell helpers, the bww shortcut and a PATH line for ~/.local/bin."""
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile

home = Path.home()
lib = home / ".local/lib/bw-window"
bin_dir = home / ".local/bin"
shortcut = bin_dir / "bww"
SHORTCUT = "#!/bin/sh\nexec " + shlex.quote(str(bin_dir / "bw-window")) + ' "$@"\n'
PATH_LINE = 'case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac  # Bitwarden Window\n'


def startup_file():
    shell = Path(os.environ.get("SHELL", "")).name
    if shell == "zsh":
        return home / ".zshrc"
    if shell == "bash":
        return home / (".bash_profile" if sys.platform == "darwin" else ".bashrc")
    return None


def owned_shortcut():
    return shortcut.is_file() and not shortcut.is_symlink() and shortcut.read_text() == SHORTCUT


def uninstall():
    if owned_shortcut():
        shortcut.unlink()
    rc = startup_file()
    if rc and rc.is_file() and PATH_LINE in (text := rc.read_text()):
        rc.write_text(text.replace(PATH_LINE, ""))


if sys.argv[1:] == ["uninstall"]:
    uninstall()
    raise SystemExit
settings = json.loads((lib / "paths.json").read_text())
if (lib / ".bitwarden-window-public").read_text().strip() != "bitwarden-window/v1":
    raise SystemExit("The public broker is not installed.")
source = Path(__file__).parent
with tempfile.TemporaryDirectory(dir=lib) as tmp:
    stage = Path(tmp)
    for name in ("auth.py", "shell.sh", "upgrade.py"):
        shutil.copyfile(source / name, stage / name)
        os.chmod(stage / name, 0o600)
        os.replace(stage / name, lib / name)
    (stage / "native-bw").symlink_to(settings["bw"])
    os.replace(stage / "native-bw", lib / "native-bw")
with tempfile.NamedTemporaryFile(mode="w", dir=bin_dir, delete=False) as launcher:
    launcher.write("#!/bin/sh\nexec " + shlex.quote(settings["python"]) + " -I " +
                   shlex.quote(str(lib / "auth.py")) + ' "$@"\n')
    os.fchmod(launcher.fileno(), 0o700)
os.replace(launcher.name, bin_dir / "bw-unlock")

if os.path.lexists(shortcut) and not owned_shortcut():
    print(f"Kept the existing {shortcut}; use bw-window instead of bww.")
else:
    with tempfile.NamedTemporaryFile(mode="w", dir=bin_dir, delete=False) as launcher:
        launcher.write(SHORTCUT)
        os.fchmod(launcher.fileno(), 0o700)
    os.replace(launcher.name, shortcut)
if str(bin_dir) not in os.environ.get("PATH", "").split(":"):
    rc = startup_file()
    if rc is None:
        print(f"Add {bin_dir} to PATH in your shell to run bw-window and bww by name.")
    elif PATH_LINE not in (rc.read_text() if rc.is_file() else ""):
        with open(rc, "a") as profile:
            profile.write(PATH_LINE)
        print(f"Added {bin_dir} to PATH in {rc}. Open a new terminal to run bw-window and bww by name.")
