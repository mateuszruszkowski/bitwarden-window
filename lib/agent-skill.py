"""Install or remove the bundled instructions in the personal Agent Skill registries."""
import errno
import hashlib
import os
from pathlib import Path
import sys
import tempfile


NAME = "use-bitwarden-window"
SOURCE = Path(__file__).parent.parent / "skills" / NAME / "SKILL.md"


def digest(data):
    return hashlib.sha256(data).hexdigest().encode() + b"\n"


def replace_file(path, data):
    tmp = tempfile.NamedTemporaryFile(dir=path.parent, delete=False)
    try:
        with tmp:
            tmp.write(data)
        os.replace(tmp.name, path)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def manage(root, data):
    registry = root / "skills"
    target = registry / NAME
    guide = target / "SKILL.md"
    receipt = target / ".bitwarden-window.sha256"
    if root.is_symlink() or registry.is_symlink():
        print(f"Skipped linked skill registry {registry}.", file=sys.stderr)
        return
    if data is not None:
        registry.mkdir(parents=True, exist_ok=True)
        try:
            target.mkdir(mode=0o700)
        except FileExistsError:
            pass
        else:
            replace_file(guide, data)
            replace_file(receipt, digest(data))
            return
    if not os.path.lexists(target):
        return
    if (target.is_symlink() or guide.is_symlink() or receipt.is_symlink()
            or not guide.is_file() or not receipt.is_file()
            or receipt.read_bytes() != digest(guide.read_bytes())):
        print(f"Preserved existing or edited skill {target}.", file=sys.stderr)
        return
    if data is not None:
        if receipt.read_bytes() != digest(data):
            replace_file(guide, data)
            replace_file(receipt, digest(data))
        return
    guide.unlink()
    receipt.unlink()
    try:
        target.rmdir()
    except OSError as exc:
        if exc.errno != errno.ENOTEMPTY:
            raise
        print(f"Preserved additional files at {target}.", file=sys.stderr)


if __name__ == "__main__":
    if sys.argv[1:] not in (["install"], ["uninstall"]):
        sys.exit("Usage: agent-skill.py install|uninstall")
    data = SOURCE.read_bytes() if sys.argv[1] == "install" else None
    for registry_name in (".agents", ".claude"):
        root = Path.home() / registry_name
        try:
            manage(root, data)
        except OSError as exc:
            print(f"Could not update the skill in {root}: {exc}", file=sys.stderr)
