"""Run with non-system Python 3.10+, Swift 6 and a logged-in macOS GUI session.

All launchd labels and paths are temporary. Exercise the real menu client with
a synthetic CLI over pipes, without showing a password prompt on the desktop.
"""

import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import runpy
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).absolute().parents[1]
FAKE_KEYRING = runpy.run_path(str(ROOT / "tests/test_core.py"))["FAKE_KEYRING"]
FAKE_BW = """
import base64, hashlib, json, os, sys
from pathlib import Path

home = Path(os.environ["HOME"])
args = sys.argv[1:]
if args == ["--version"]:
    print("1.2.3")
    sys.exit(0)
if args == ["unlock", "--help"]:
    print("bw unlock --passwordfile")
    sys.exit(0)
assert str(home) == EXPECTED_HOME
assert "BW_PASSWORD" not in os.environ and "BW_CLIENTSECRET" not in os.environ
assert args.pop(0) == "--nointeraction"
cmd = args.pop(0)
assert os.environ.get("BW_SESSION") not in sys.argv
with (home / "calls").open("a") as stream:
    print(cmd, file=stream)
if cmd == "unlock":
    assert args == ["--passwordfile", "/dev/stdin", "--raw"]
    assert "BW_SESSION" not in os.environ
    print("malformed reply" if (home / "fail unlock").exists() else hashlib.sha256(sys.stdin.buffer.read()).hexdigest())
elif cmd == "status":
    valid = hashlib.sha256(os.environ["BW_SESSION"].encode()).hexdigest() == EXPECTED_DIGEST
    print(json.dumps(dict(userId="fixture", status="unlocked" if valid else "locked",
                          serverUrl="https://fixture.invalid")))
elif cmd == "lock":
    assert "BW_SESSION" not in os.environ
elif cmd == "sync":
    pass
elif cmd == "list":
    note = home / "fixture-item.json"
    print("[]" if not note.exists() or "--archived" in args or "--trash" in args else "[" + note.read_text() + "]")
elif cmd == "create":
    item = json.loads(base64.b64decode(sys.stdin.buffer.read()))
    item["id"] = "fixture"
    with (home / "fixture-item.json").open("x") as out:
        json.dump(item, out)
    print(json.dumps(item))
elif cmd == "get" and args == ["item", "fixture"]:
    print((home / "fixture-item.json").read_text())
else:
    sys.exit(2)
"""
MENU_MAIN = """
if CommandLine.arguments.dropFirst() == ["--test-unlock"] {
    let home = URL(fileURLWithPath: ProcessInfo.processInfo.environment["HOME"]!)
    let password = FileHandle.standardInput.readDataToEndOfFile()
    do {
        try WindowClient(home: home).unlock(password: password, holding: AuthLock(home: home))
    } catch { exit(1) }
} else {
    dispatchMain()
}
"""


@unittest.skipUnless(sys.platform == "darwin", "requires macOS launchd and Swift")
class MacInstall(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir="/private/tmp", prefix="bww-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.home = root / "Test Home"
        self.bin = self.home / "Tools With Spaces"
        self.bin.mkdir(parents=True)
        self.src = root / "export"
        shutil.copytree(ROOT / "osx", self.src / "osx")
        for name in ("install.sh", "uninstall.sh"):
            shutil.copy2(ROOT / name, self.src / name)
        shutil.copytree(ROOT / "lib", self.src / "lib")
        shutil.copytree(ROOT / "skills", self.src / "skills")
        # Substitute only the account home for the common core's passwd lookup.
        # The assertion also prevents contacting a real CLI if that contract changes.
        core = (ROOT / "lib/core.py").read_text()
        fixture = f'''from unittest.mock import patch
from types import SimpleNamespace
import os
assert os.environ["HOME"] == {str(self.home)!r}
with patch("pwd.getpwuid", return_value=SimpleNamespace(pw_dir=os.environ["HOME"])):
    exec(compile({core!r}, __file__, "exec"))
assert str(BW) == os.path.join(os.environ["HOME"], "Tools With Spaces", "bw")
Keychain.tool = os.path.join(os.environ["HOME"], "Tools With Spaces", "security")
'''
        (self.src / "lib/core.py").write_text(fixture)
        self.base = "org.bitwardenwindow.test." + root.name
        self.domain = f"gui/{os.getuid()}"
        for filename, count in (("install.sh", 2), ("Info.plist", 1)):
            file = self.src / "osx" / filename
            original = file.read_text()
            self.assertEqual(original.count("org.bitwardenwindow."), count)
            file.write_text(original.replace("org.bitwardenwindow.", self.base + "."))
        for role in ("broker", "menu"):
            self.addCleanup(subprocess.run, ["launchctl", "bootout", f"{self.domain}/{self.base}.{role}"],
                            capture_output=True)
        swift = self.src / "osx/Menu.swift"
        self.assertEqual(swift.read_text().count("MainActor.assumeIsolated {"), 1)
        swift.write_text(swift.read_text().split("MainActor.assumeIsolated {")[0] + MENU_MAIN)
        self.password = secrets.token_urlsafe(32).encode()
        self.token = hashlib.sha256(self.password).hexdigest().encode()
        digest = hashlib.sha256(self.token).hexdigest()
        backend = self.bin / "fixture.py"
        backend.write_text(f"EXPECTED_HOME = {str(self.home)!r}\nEXPECTED_DIGEST = {digest!r}\n" + FAKE_BW)
        (self.bin / "security").write_text(FAKE_KEYRING)
        (self.bin / "security").chmod(0o700)
        for name, args in (("bw", [sys.executable, "-IB", str(backend)]),
                           ("python3", [sys.executable])):
            wrapper = self.bin / name
            wrapper.write_text('#!/bin/sh\nexec ' + shlex.join(args) + ' "$@"\n')
            wrapper.chmod(0o700)
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin",
                    "BW_PASSWORD": "synthetic-forbidden", "BW_CLIENTSECRET": "synthetic-forbidden",
                    "CLANG_MODULE_CACHE_PATH": str(root / "modules")}
        self.lib = self.home / ".local/lib/bw-window"
        self.client = self.home / ".local/bin/bw-window"
        self.menu = self.lib / "macos/Bitwarden Window.app/Contents/MacOS/BWWindowMenu"
        self.config = self.home / ".config/bw-window/config.json"
        self.config.parent.mkdir(parents=True)
        self.config.write_text('{"server_url": "https://fixture.invalid"}')
        self.install = self.src / "install.sh"
        self.uninstall = self.src / "uninstall.sh"

    def invoke(self, *args, data=None, success=True):
        result = subprocess.run(args, input=data, env=self.env, capture_output=True, timeout=90)
        self.assertNotIn(self.password, result.stdout + result.stderr)
        self.assertNotIn(self.token, result.stdout + result.stderr)
        self.assertEqual(result.returncode == 0, success, result.stderr.decode())
        return result

    def test_lifecycle(self):
        self.client.parent.mkdir(parents=True)
        self.client.write_text("legacy client\n")
        self.invoke(self.install, success=False)
        self.invoke(self.src / "osx/uninstall.sh", success=False)
        self.assertEqual(self.client.read_text(), "legacy client\n")
        self.client.unlink()

        self.invoke(self.install)
        skills = [self.home / name / "skills/use-bitwarden-window" for name in (".agents", ".claude")]
        for skill in skills:
            self.assertEqual((skill / "SKILL.md").read_bytes(),
                             (ROOT / "skills/use-bitwarden-window/SKILL.md").read_bytes())
        binaries = json.loads((self.lib / "paths.json").read_text())
        self.assertEqual(binaries["bw"], str(self.bin / "bw"))
        self.assertIsNone(binaries["age_keygen"])
        self.assertEqual((self.lib / ".bitwarden-window-public").read_text().strip(), "bitwarden-window/v1")
        for role in ("broker", "menu"):
            label = f"{self.base}.{role}"
            info = self.invoke("/bin/launchctl", "print", f"{self.domain}/{label}")
            self.assertIn(b"state = running", info.stdout)
            plist = self.home / f"Library/LaunchAgents/{label}.plist"
            self.assertTrue(plistlib.loads(plist.read_bytes())["RunAtLoad"])
        failure = self.home / "fail unlock"
        failure.touch()
        self.invoke(self.menu, "--test-unlock", data=self.password, success=False)
        self.assertEqual((self.home / "calls").read_text().splitlines()[-2:], ["unlock", "lock"])
        failure.unlink()
        self.invoke(self.menu, "--test-unlock", data=self.password)
        calls = (self.home / "calls").read_bytes()
        for _ in range(3):
            self.invoke(self.client, "status")
        self.assertEqual((self.home / "calls").read_bytes(), calls)
        remaining = self.invoke(self.client, "status").stdout
        seconds = int(re.search(rb"(\d+) seconds remaining", remaining)[1])
        self.assertTrue(3590 <= seconds <= 3600)
        self.invoke(self.client, "start", self.invoke(self.client, "now").stdout.strip(), data=self.token, success=False)
        self.assertEqual(set((self.home / "calls").read_text().split()), {"lock", "unlock", "status"})
        self.assertIn(b"window", self.invoke(self.install, success=False).stderr)
        self.assertIn(b"window", self.invoke(self.uninstall, success=False).stderr)
        self.invoke(self.client, "status")
        self.assertIn(b"configuration", self.invoke(self.client, "obsidian", success=False).stderr)
        sock = self.home / ".local/state/bw-window/control.sock"
        self.assertEqual(stat.S_IMODE(sock.stat().st_mode), 0o600)
        for file in self.home.rglob("*"):
            if file.is_file():
                content = file.read_bytes()
                self.assertNotIn(self.password, content, file.name)
                self.assertNotIn(self.token, content, file.name)
        self.invoke(self.client, "lock")
        self.assertEqual(self.invoke(self.client, "status", success=False).returncode, 1)
        self.invoke(self.install)
        self.invoke(self.uninstall)
        self.invoke(self.src / "osx/uninstall.sh")
        self.assertFalse(os.path.lexists(self.client))
        for skill in skills:
            self.assertFalse(os.path.lexists(skill))
        self.assertFalse(self.lib.exists())
        self.assertEqual(json.loads(self.config.read_text())["server_url"], "https://fixture.invalid")

    @unittest.skipUnless(shutil.which("age-keygen"), "requires optional age-keygen")
    def test_explicit_escrow(self):
        keygen = self.bin / "age-keygen"
        keygen.symlink_to(shutil.which("age-keygen"))
        identity = self.home / "synthetic identity"
        self.invoke(keygen, "-o", identity)
        self.config.write_text(json.dumps(dict(server_url="https://fixture.invalid", identity_file=str(identity),
                                               note_title="Fixture recovery")))
        self.invoke(self.install)
        self.invoke(self.menu, "--test-unlock", data=self.password)
        note = self.home / "fixture-item.json"
        self.assertFalse(note.exists())
        self.assertIn(b"created and verified", self.invoke(self.client, "obsidian").stdout)
        self.assertEqual(json.loads(note.read_text())["name"], "Fixture recovery")
        self.assertIn(b"verified", self.invoke(self.client, "obsidian").stdout)
        self.invoke(self.client, "lock")
        self.invoke(self.uninstall)
        self.assertTrue(identity.exists())
        self.assertTrue(note.exists())

    def test_explicit_save(self):
        self.invoke(self.install)
        self.invoke(self.menu, "--test-unlock", data=self.password)
        item = self.home / "fixture-item.json"
        secret = b"synthetic-api-key"
        for data, message in ((secret + b"\n", b"created and verified"), (secret, b"Existing personal login")):
            result = self.invoke(self.client, "save", "Fixture login", data=data)
            self.assertIn(message, result.stdout)
            self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertEqual(json.loads(item.read_text())["login"]["password"], secret.decode())
        self.assertIn(b"conflicts", self.invoke(self.client, "save", "Fixture login", data=b"other",
                                                success=False).stderr)
        self.assertIn(b"standard input", self.invoke(self.client, "save", "Fixture login", data=b"",
                                                     success=False).stderr)
        self.invoke(self.client, "status")
        self.invoke(self.client, "lock")
        self.invoke(self.uninstall)

    def test_keyring_copy_outlives_the_window(self):
        secret = b"synthetic-keyring-value"
        (self.home / "fixture-item.json").write_text(json.dumps(
            {"id": "fixture", "type": 1, "name": "Fixture login", "login": {"password": secret.decode()}}))
        self.config.write_text(json.dumps({"server_url": "https://fixture.invalid",
                                           "keyring_items": ["Fixture login", "Absent"]}))
        self.invoke(self.install)
        self.invoke(self.menu, "--test-unlock", data=self.password)
        # Status does not wait for the copy, which runs after the start reply.
        until = time.monotonic() + 30
        while b"pending" in (status := self.invoke(self.client, "status").stdout) and time.monotonic() < until:
            time.sleep(0.2)
        self.assertIn(b"\nKeyring: 1 of 2 listed items synced at the last unlock; not synced: Absent (missing).\n",
                      status)
        self.invoke(self.client, "lock")
        self.assertEqual(self.invoke(self.client, "get", "Fixture login").stdout, secret)
        for name in ("Absent", "Other"):
            failed = self.invoke(self.client, "get", name, success=False)
            self.assertEqual(failed.stdout, b"")
        self.assertNotIn(secret, (self.home / "keyring-argv").read_bytes())
        self.assertNotIn(secret.hex().encode(), (self.home / "keyring-argv").read_bytes())
        self.invoke(self.uninstall)

    def test_bootout_relocks(self):
        self.invoke(self.install)
        self.invoke(self.menu, "--test-unlock", data=self.password)
        before = (self.home / "calls").read_text().splitlines().count("lock")
        self.invoke("/bin/launchctl", "bootout", f"{self.domain}/{self.base}.broker")
        self.wait_for_locks(before + 1)
        self.assertEqual(self.invoke(self.client, "status", success=False).returncode, 3)

    def wait_for_locks(self, count):
        until = time.monotonic() + 12
        while time.monotonic() < until:
            if (self.home / "calls").read_text().splitlines().count("lock") >= count:
                return
            time.sleep(0.05)
        self.fail("The synthetic native CLI did not relock.")

    def test_expiry_without_polling(self):
        with (self.src / "lib/core.py").open("a") as fixture:
            fixture.write("\nWINDOW_SECONDS = 4\n")
        self.invoke(self.install)
        self.invoke(self.menu, "--test-unlock", data=self.password)
        self.wait_for_locks(2)
        self.assertEqual(self.invoke(self.client, "status", success=False).returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
