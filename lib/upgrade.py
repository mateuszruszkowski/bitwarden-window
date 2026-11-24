"""Download, verify and install a published Bitwarden Window release."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

VERSION = "0.8.1"
REPO = "https://github.com/mateuszruszkowski/bitwarden-window"
FIRST = (0, 8, 0)  # Earlier releases do not install this command.
TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
ASSET_LIMIT = 16 * 1024 * 1024


def fetch(url, limit):
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise SystemExit("The download is larger than expected.")
    return data


def latest_tag():
    # The release page redirects to the newest tag without an API rate limit.
    request = urllib.request.Request(REPO + "/releases/latest", method="HEAD")
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.geturl().rstrip("/").rsplit("/", 1)[-1]


def parse(tag):
    match = TAG.fullmatch(tag)
    if not match:
        raise SystemExit("Give a release tag such as v" + VERSION + ".")
    return tuple(map(int, match.groups()))


def window_closed(home):
    result = subprocess.run([home / ".local/bin/bw-window", "status"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    # 0 is an open window and 4 an unlock in progress; the installer reports other errors.
    return result.returncode not in (0, 4)


def verified_package(tag, platform, releases):
    version = tag[1:]
    name = f"bitwarden-window-{version}-{platform}"
    asset = name + (".zip" if platform == "macos" else ".tar.gz")
    base = f"{REPO}/releases/download/{tag}/"
    sums = fetch(base + "SHA256SUMS", 4096).decode("ascii")
    expected = {line.split()[1].lstrip("*"): line.split()[0] for line in sums.splitlines() if line.strip()}
    archive = fetch(base + asset, ASSET_LIMIT)
    if expected.get(asset) != hashlib.sha256(archive).hexdigest():
        raise SystemExit(f"{asset} does not match the release SHA256SUMS. Nothing was installed.")
    releases.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=releases) as tmp:
        stage = Path(tmp)
        (stage / asset).write_bytes(archive)
        if platform == "macos":
            # ditto keeps the file modes stored in the archive.
            subprocess.run(["/usr/bin/ditto", "-x", "-k", stage / asset, stage], check=True)
        else:
            with tarfile.open(stage / asset) as bundle:
                bundle.extractall(stage, filter="data")
        target = releases / tag
        if target.exists():
            shutil.rmtree(target)
        os.replace(stage / name, target)
    return target


def main(args):
    if len(args) > 1:
        print("Usage: bw-window upgrade [vMAJOR.MINOR.PATCH]", file=sys.stderr)
        return 2
    home = Path.home()
    releases = home / ".local/share/bw-window/releases"
    platform = {"darwin": "macos", "linux": "omarchy"}.get(sys.platform)
    if not platform:
        raise SystemExit("Requires Omarchy Linux or macOS.")
    try:
        tag = args[0] if args else latest_tag()
        if parse(tag) < FIRST:
            raise SystemExit(f"Install releases before v{'.'.join(map(str, FIRST))} from the README instead.")
        if tag == "v" + VERSION:
            print(f"Bitwarden Window {VERSION} is already installed.")
            return 0
        if not window_closed(home):
            raise SystemExit("Close the window with ~/.local/bin/bw-window lock, then upgrade.")
        package = verified_package(tag, platform, releases)
    except (OSError, urllib.error.URLError, subprocess.SubprocessError, tarfile.TarError) as exc:
        raise SystemExit(f"Download failed: {exc}") from None
    result = subprocess.run(["./install.sh"], cwd=package)
    if result.returncode:
        print(f"The installer stopped. The verified package is in {package}.", file=sys.stderr)
        return result.returncode
    # Keep the new package for ./uninstall.sh and the previous one for rolling back.
    for old in releases.iterdir():
        if old.name not in (tag, "v" + VERSION) and TAG.fullmatch(old.name):
            shutil.rmtree(old)
    print(f"Bitwarden Window {tag[1:]} installed from {package}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
