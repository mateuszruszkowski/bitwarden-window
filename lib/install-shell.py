"""Install the optional shell functions without editing shell startup files."""
import json
import os
from pathlib import Path
import shlex
import shutil
import tempfile

home = Path.home()
lib = home / ".local/lib/bw-window"
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
bin_dir = home / ".local/bin"
with tempfile.NamedTemporaryFile(mode="w", dir=bin_dir, delete=False) as launcher:
    launcher.write("#!/bin/sh\nexec " + shlex.quote(settings["python"]) + " -I " +
                   shlex.quote(str(lib / "auth.py")) + ' "$@"\n')
    os.fchmod(launcher.fileno(), 0o700)
os.replace(launcher.name, bin_dir / "bw-unlock")
