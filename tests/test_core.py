"""Public fixtures only. No test calls the installed Bitwarden CLI."""

import importlib.util
import json
import os
from pathlib import Path
import pwd
import runpy
import socket
import shutil
import signal
import stat
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).absolute().parents[1]
TITLE = "Fixture recovery"
TOKEN = b"fixture-session"

# The stand-in recognizes only the commands the public interface needs. Record
# command names (never stdin or the session) for assertions across processes.
FAKE_BW = '''#!/usr/bin/python3 -I
import base64, json, os, sys, time
from pathlib import Path
home = Path(os.environ["HOME"])
assert "NODE_OPTIONS" not in os.environ and "BW_PASSWORD" not in os.environ
args = sys.argv[1:]
assert args.pop(0) == "--nointeraction"
cmd = args[0]
with (home / "calls").open("a") as f:
    f.write(cmd + "\\n")
state = json.loads((home / "state").read_text())
if cmd == "lock":
    if state.get("lock_fails"):
        sys.exit(1)
    assert "BW_SESSION" not in os.environ
    (home / "locked").touch()
    sys.exit()
if not (cmd == "status" and state.get("lock_fails")):
    assert os.environ["BW_SESSION"] == "fixture-session"
items = home / "items"
active = json.loads(items.read_text()) if items.exists() else []
if cmd == "status":
    result = state["status"]
elif cmd == "sync":
    time.sleep(state.get("sync_delay", 0))
    sys.exit()
elif cmd == "list":
    if state.get("list_error"):
        sys.exit(1)
    if state.get("hide_items"):
        active = []
    if "--trash" in args:
        result = state.get("trash", [])
    elif "--archived" in args:
        result = state.get("archive", active)
    else:
        result = active
elif cmd == "create":
    result = json.loads(base64.b64decode(sys.stdin.buffer.read()))
    result["id"] = "fixture-item"
    items.write_text(json.dumps(active + [result]))
    if state.get("lost_reply"):
        sys.exit(1)
elif cmd == "get":
    result = state.get("get", next(i for i in active if i["id"] == args[2]))
else:
    sys.exit(2)
print(json.dumps(result))
'''


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name).resolve()
        self.lib = self.home / ".local/lib/bw-window"
        self.lib.mkdir(parents=True)
        self.config = self.home / ".config/bw-window/config.json"
        self.config.parent.mkdir(parents=True)
        self.key = self.home / "identity"
        self.runtime = self.home / "runtime"
        self.bw = self.home / "fake-bw"
        self.bw.write_text(FAKE_BW)
        self.bw.chmod(0o700)
        self.age = shutil.which("age-keygen", path="/usr/bin:/opt/homebrew/bin:/usr/local/bin")
        self.paths = self.lib / "paths.json"
        self.paths.write_text(json.dumps({"bw": str(self.bw), "age_keygen": self.age}))
        shutil.copyfile(ROOT / "lib/core.py", self.lib / "core.py")
        self.state = {"status": {"status": "unlocked", "serverUrl": None, "userId": "fixture-id"}}
        self.save_state()
        self.core = self.load_core()

    def save_state(self):
        (self.home / "state").write_text(json.dumps(self.state))

    def load_core(self):
        spec = importlib.util.spec_from_file_location("core", self.lib / "core.py")
        module = importlib.util.module_from_spec(spec)
        with patch.object(pwd, "getpwuid", return_value=SimpleNamespace(pw_dir=str(self.home))):
            spec.loader.exec_module(module)
        module.RUNTIME_DIR = self.runtime
        return module

    def configure(self, **extra):
        self.config.write_text(json.dumps({"identity_file": "~/identity", "note_title": TITLE, **extra}))

    def identity(self):
        if self.age is None:
            self.skipTest("requires age-keygen")
        subprocess.run([self.age, "-o", self.key], check=True, capture_output=True)
        self.key.chmod(0o600)

    def principal(self):
        return self.core.account(TOKEN.decode())

    def escrow(self, user):
        return self.core.escrow(TOKEN.decode(), user)

    def calls(self):
        path = self.home / "calls"
        return path.read_text().splitlines() if path.exists() else []


class TestCore(Fixture):
    def test_default_account_has_no_escrow_access(self):
        with patch.dict(os.environ, {"BW_PASSWORD": "decoy", "NODE_OPTIONS": "decoy",
                                     "BITWARDENCLI_APPDATA_DIR": "/invalid"}):
            user = self.principal()
            with patch.object(self.core, "read_identity", side_effect=AssertionError):
                with self.assertRaisesRegex(self.core.Failure, "^config$"):
                    self.escrow(user)
        self.assertEqual(self.calls(), ["status", "status"])
        self.assertIsNone(self.core.settings().identity)

    def test_lock_on_a_fresh_profile_and_on_native_failure(self):
        self.state["lock_fails"] = True
        self.state["status"]["status"] = "unauthenticated"
        self.save_state()
        self.core.native(None, "lock")
        for status in ("locked", "unlocked"):
            self.state["status"]["status"] = status
            self.save_state()
            with self.assertRaisesRegex(self.core.Failure, "^vault$"):
                self.core.native(None, "lock")

    def test_changes_after_unlock_prevent_key_access(self):
        self.configure()
        user = self.principal()
        for change in ["account", "server", "config-and-server", "missing-config"]:
            with self.subTest(change=change):
                self.state["status"].update(userId="fixture-id", serverUrl=None)
                self.configure()
                if change == "account":
                    self.state["status"]["userId"] = "different"
                elif change == "missing-config":
                    self.config.unlink()
                else:
                    self.state["status"]["serverUrl"] = "https://example.invalid"
                    if change == "config-and-server":
                        self.configure(server_url="https://example.invalid")
                self.save_state()
                with patch.object(self.core, "read_identity", side_effect=AssertionError):
                    with self.assertRaisesRegex(self.core.Failure, "^auth$"):
                        self.escrow(user)
        self.assertNotIn("create", self.calls())

    def test_server_identity_and_native_null(self):
        for native, configured, success in [
                (None, self.core.US_SERVER, True), (self.core.US_SERVER + "/", self.core.US_SERVER, True),
                (None, "https://example.invalid", False), ("", self.core.US_SERVER, False),
                ("https://example.invalid", "https://example.invalid/", True),
                ("https://example.invalid/other", "https://example.invalid", False)]:
            with self.subTest(native=native, configured=configured):
                self.configure(server_url=configured)
                self.state["status"]["serverUrl"] = native
                self.save_state()
                if success:
                    self.assertEqual(self.principal(), "fixture-id")
                else:
                    with self.assertRaisesRegex(self.core.Failure, "^auth$"):
                        self.principal()

    def test_optional_https_server_pin(self):
        for url in [self.core.US_SERVER, "https://vault.bitwarden.eu", "https://example.invalid:8443/vault"]:
            self.state["status"]["serverUrl"] = url
            self.save_state()
            self.configure(server_url=url + "/")
            self.assertEqual(self.principal().server, url)
            self.configure(server_url="https://other.invalid")
            with self.assertRaisesRegex(self.core.Failure, "^auth$"):
                self.principal()
        for invalid in ["http://example.invalid", "relative", "https://user@example.invalid",
                        "https://example.invalid:bad", "https://example.invalid/#fragment",
                        "https://example.invalid/?query=yes", None]:
            self.configure(server_url=invalid)
            with self.assertRaisesRegex(self.core.Failure, "^config$"):
                self.principal()

    def test_overlapping_first_creates_use_one_durable_intent(self):
        self.configure()
        self.identity()
        user = self.principal()
        barrier = threading.Barrier(2, timeout=10)
        read = self.core.read_identity
        def both_saw_empty_vault(identity):
            barrier.wait()
            return read(identity)
        def attempt():
            try:
                return self.escrow(user)
            except self.core.Failure as exc:
                return str(exc)
        with patch.object(self.core, "read_identity", side_effect=both_saw_empty_vault):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = [pool.submit(attempt) for _ in range(2)]
                self.assertCountEqual([job.result(timeout=15) for job in results], ["created", "reconcile"])
        self.assertEqual(self.calls().count("create"), 1)

    def test_follow_active_account_on_eu_and_self_hosted(self):
        self.configure()
        self.identity()
        for url, normalized, user_id in [
                ("https://VAULT.bitwarden.eu:443/", "https://vault.bitwarden.eu", "first"),
                ("http://LOCALHOST:8080/vault/", "http://localhost:8080/vault", "second")]:
            with self.subTest(url=url):
                self.state["status"].update(serverUrl=url, userId=user_id)
                self.save_state()
                user = self.principal()
                self.assertEqual(user.server, normalized)
                self.assertEqual(str(user), user_id)
                self.assertEqual(self.escrow(user), "created")
                (self.home / "items").unlink()  # separate synthetic vaults

    def test_unknown_option_is_reported(self):
        self.configure(server_urll="https://example.invalid")
        with self.assertRaisesRegex(self.core.Failure, "^config$"):
            self.principal()
        self.assertNotIn("create", self.calls())

    def test_account_switched_immediately_before_create(self):
        self.configure()
        self.identity()
        user = self.principal()
        read = self.core.read_identity
        def switch(identity):
            secret = read(identity)
            self.state["status"]["userId"] = "other"
            self.save_state()
            return secret
        with patch.object(self.core, "read_identity", side_effect=switch):
            with self.assertRaisesRegex(self.core.Failure, "^auth$"):
                self.escrow(user)
        self.assertNotIn("create", self.calls())

    def test_indeterminate_create_requires_manual_reconciliation_after_restart(self):
        self.configure()
        self.identity()
        self.state["lost_reply"] = True
        self.save_state()
        with self.assertRaisesRegex(self.core.Failure, "^vault$"):
            self.escrow(self.principal())
        self.assertTrue((self.home / "items").exists())
        self.core = self.load_core()
        self.state.update(lost_reply=False, hide_items=True)
        self.save_state()
        with patch.object(self.core, "read_identity", side_effect=AssertionError):
            with self.assertRaisesRegex(self.core.Failure, "^reconcile$"):
                self.escrow(self.principal())
        self.assertEqual(self.calls().count("create"), 1)

    def test_known_id_protects_against_missing_or_replaced_search_result(self):
        self.configure()
        self.identity()
        self.assertEqual(self.escrow(self.principal()), "created")
        items = self.home / "items"
        old = json.loads(items.read_text())[0]
        self.core = self.load_core()
        for result in [[], [dict(old, id="different")]]:
            items.write_text(json.dumps(result))
            with self.assertRaisesRegex(self.core.Failure, "^reconcile$"):
                self.escrow(self.principal())
        self.state["list_error"] = True
        self.save_state()
        with self.assertRaisesRegex(self.core.Failure, "^vault$"):
            self.escrow(self.principal())
        self.assertEqual(self.calls().count("create"), 1)

    def test_create_and_verify_without_clobber(self):
        self.configure()
        self.identity()
        user = self.principal()
        self.assertEqual(self.calls(), ["status"])
        self.assertEqual(self.escrow(user), "created")
        self.assertEqual(self.escrow(user), "verified")  # no entitlement: archive repeats active item
        self.assertEqual(self.calls().count("create"), 1)
        receipt = self.runtime / "obsidian-verified"
        self.assertRegex(receipt.read_text(), r"^[0-9]+\n$")
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
        item = json.loads((self.home / "items").read_text())[0]
        self.assertTrue(item["notes"].startswith("AGE-SECRET-KEY-"))
        self.assertFalse(item["notes"].startswith("#"))

    def test_collisions_never_write(self):
        self.configure()
        self.identity()
        user = self.principal()
        path = self.home / "items"
        item = {"id": "fixture-item", "type": 2, "name": TITLE, "notes": "unrelated"}
        for active, additions, error in [
                ([item], {}, "different"), ([item, item], {}, "duplicate"),
                ([dict(item, type=1)], {}, "conflict"), ([dict(item, name=TITLE.upper())], {}, "conflict"),
                ([dict(item, organizationId="org")], {}, "conflict"),
                ([], {"trash": [item]}, "conflict"), ([], {"archive": [item]}, "conflict"),
                ([item], {"archive": [dict(item, archivedDate="today")]}, "conflict")]:
            with self.subTest(error=error):
                path.write_text(json.dumps(active))
                self.state = {"status": self.state["status"], **additions}
                self.save_state()
                with self.assertRaisesRegex(self.core.Failure, "^" + error + "$"):
                    self.escrow(user)
                self.assertEqual(json.loads(path.read_text()), active)
        self.assertNotIn("create", self.calls())

    def test_partial_search_match_and_failed_readback(self):
        self.configure()
        self.identity()
        user = self.principal()
        other = {"id": "other", "name": TITLE + " log"}
        (self.home / "items").write_text(json.dumps([other]))
        self.state["get"] = {"id": "fixture-item", "type": 2, "name": TITLE, "notes": "different"}
        self.save_state()
        with self.assertRaisesRegex(self.core.Failure, "^different$"):
            self.escrow(user)
        self.assertFalse((self.runtime / "obsidian-verified").exists())
        self.assertEqual(json.loads((self.home / "items").read_text())[0], other)

    def test_identity_permissions_and_links(self):
        self.identity()
        self.key.chmod(0o644)
        with self.assertRaisesRegex(self.core.Failure, "^key$"):
            self.core.read_identity(self.key)
        self.key.chmod(0o600)
        link = self.home / "linked"
        link.symlink_to(self.key)
        (self.home / "parent").symlink_to(self.home, target_is_directory=True)
        for candidate in (link, self.home / "parent/identity"):
            with self.assertRaisesRegex(self.core.Failure, "^key$"):
                self.core.read_identity(candidate)
        self.key.write_text("AGE-SECRET-KEY-1INVALID\n")
        with self.assertRaisesRegex(self.core.Failure, "^key$"):
            self.core.read_identity(self.key)

    def test_installer_paths_and_invalid_config(self):
        self.paths.write_text(json.dumps({"bw": str(self.bw), "age_keygen": None}))
        core = self.load_core()
        self.assertEqual(core.BW, str(self.bw))
        self.assertIsNone(core.AGE_KEYGEN)
        self.paths.write_text('{"bw":"bw","age_keygen":null}')
        with self.assertRaisesRegex(core.Failure, "^config$"):
            core.configured_binaries()
        self.configure(identity_file="../identity")
        with self.assertRaisesRegex(core.Failure, "^config$"):
            core.settings()


@unittest.skipUnless(sys.platform == "linux" and sys.version_info >= (3, 13), "Linux system Python >=3.13")
class TestLinuxService(Fixture):
    def setUp(self):
        super().setUp()
        if not Path("/usr/bin/systemd-run").exists() or subprocess.run(
                ["/usr/bin/systemctl", "--user", "show", "--property=Version", "--value"], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL).returncode:
            self.skipTest("requires an available systemd user manager")
        self.unit = "bw-window-test-" + uuid4().hex + ".service"
        self.launcher = self.home / "bw window"
        # Each manager invocation uses the package wrapper, with pwd, unit name
        # and runtime redirected before main. No real user vault or unit is touched.
        self.launcher.write_text(f"""#!/usr/bin/python3 -I
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import runpy, sys
with patch("pwd.getpwuid", return_value=SimpleNamespace(pw_dir={str(self.home)!r})):
    app = runpy.run_path({str(ROOT / 'omarchy/bw-window')!r})
g = app["main"].__globals__
g["UNIT"] = {self.unit!r}
g["PROGRAM"] = Path(__file__)
g["core"].RUNTIME_DIR = Path({str(self.runtime)!r})
g["SOCKET"] = g["core"].RUNTIME_DIR / "control.sock"
short = Path({str(self.home / 'short')!r})
if short.exists():
    g["core"].WINDOW_SECONDS = 5
try:
    sys.exit(g["main"](sys.argv[1:]))
except g["core"].Failure as exc:
    sys.exit(g["core"].MESSAGES[str(exc)])
""")
        self.launcher.chmod(0o700)
        self.addCleanup(subprocess.run, ["/usr/bin/systemctl", "--user", "stop", self.unit],
                        capture_output=True, timeout=75)

    def cli(self, *args, data=b""):
        return subprocess.run([self.launcher, *args], input=data, capture_output=True, timeout=75)

    def open_window(self):
        clock = self.cli("now")
        self.assertEqual(clock.returncode, 0, clock.stderr)
        stamp = clock.stdout.decode().strip()
        started = self.cli("start", stamp, data=TOKEN)
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertRegex(started.stdout, rb"^Bitwarden window open; [0-9]+ seconds remaining\.\n$")
        return stamp

    def assert_relocked(self):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if (self.home / "locked").exists() and not (self.runtime / "control.sock").exists():
                break
            time.sleep(0.1)
        self.assertTrue((self.home / "locked").exists())
        self.assertFalse((self.runtime / "control.sock").exists())
        self.assertNotEqual(self.cli("status").returncode, 0)

    def test_start_status_duplicate_and_lock(self):
        stamp = self.open_window()
        for attempt in ((stamp, TOKEN), (stamp, b""), ("0", TOKEN)):
            self.assertNotEqual(self.cli("start", attempt[0], data=attempt[1]).returncode, 0)
        status = self.cli("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertRegex(status.stdout, rb"^Bitwarden window open; 35[0-9]{2} seconds remaining\.\n$")
        self.assertEqual(stat.S_IMODE((self.runtime / "control.sock").stat().st_mode), 0o600)
        self.assertEqual(self.calls(), ["status"])
        self.assertNotEqual(self.cli("obsidian").returncode, 0)
        self.assertNotIn("create", self.calls())
        locked = self.cli("lock")
        self.assertEqual(locked.returncode, 0, locked.stderr)
        self.assert_relocked()

    def test_login_recovery_ignores_live_window_and_relocks_after_interruption(self):
        self.open_window()
        self.assertEqual(self.cli("_recover").returncode, 0)
        self.assertEqual(self.cli("status").returncode, 0)
        self.assertEqual(self.cli("lock").returncode, 0)
        marker = self.core.state_directory() / "relock-required"
        self.core.reserve(marker)
        self.assertEqual(self.cli("_recover").returncode, 0)
        self.assertFalse(marker.exists())
        self.assertEqual(self.calls().count("lock"), 2)

    def test_failed_crash_relock_blocks_fresh_start_until_manual_lock(self):
        self.open_window()
        self.state["lock_fails"] = True
        self.save_state()
        subprocess.run(["/usr/bin/systemctl", "--user", "kill", "--kill-whom=main",
                        "--signal=KILL", self.unit], check=True, capture_output=True)
        timeout = time.monotonic() + 12
        while (self.runtime / "control.sock").exists() and time.monotonic() < timeout:
            time.sleep(0.1)
        self.assertFalse((self.runtime / "control.sock").exists())
        marker = self.home / ".local/state/bw-window/relock-required"
        self.assertTrue(marker.exists())
        self.assertGreaterEqual(self.calls().count("lock"), 2)
        stamp = self.cli("now").stdout.decode().strip()
        rejected = self.cli("start", stamp, data=TOKEN)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(b"relock", rejected.stderr)
        self.assertTrue(marker.exists())
        self.state["lock_fails"] = False
        self.save_state()
        self.assertEqual(self.cli("lock").returncode, 0)
        self.assertFalse(marker.exists())
        self.open_window()

    def test_socket_rejects_foreign_peer_uid(self):
        with patch.object(pwd, "getpwuid", return_value=SimpleNamespace(pw_dir=str(self.home))):
            wrapper = runpy.run_path(str(ROOT / "omarchy/bw-window"))
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        with left, right:
            wrapper["same_user"](left)
            with patch.object(os, "getuid", return_value=os.getuid() + 1):
                with self.assertRaisesRegex(wrapper["core"].Failure, "^service$"):
                    wrapper["same_user"](left)

    def test_unsupported_unit_command_path_rejected_before_authentication(self):
        invalid = self.launcher.with_name("percent%specifier")
        self.launcher.rename(invalid)
        self.launcher = invalid
        self.assertNotEqual(self.cli("now").returncode, 0)
        self.assertIn(b"installation path", self.cli("start", str(int(self.core.now())), data=TOKEN).stderr)
        self.assertEqual(self.calls(), [])

    def test_cli_explicit_escrow(self):
        self.configure()
        self.identity()
        self.open_window()
        self.assertEqual(self.calls(), ["status"])
        for expected in (b"Personal recovery note created", b"Existing personal recovery note verified"):
            result = self.cli("obsidian")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.startswith(expected))
            self.assertNotIn(b"AGE-", result.stdout + result.stderr)
            self.assertNotIn(TOKEN, result.stdout + result.stderr)
        self.assertEqual(self.calls().count("create"), 1)

    def test_crash_relocks(self):
        self.open_window()
        subprocess.run(["/usr/bin/systemctl", "--user", "kill", "--kill-whom=main",
                        f"--signal={signal.SIGKILL.value}", self.unit], check=True, capture_output=True)
        self.assert_relocked()

    def test_expiry_relocks(self):
        self.configure()
        self.state["sync_delay"] = 90
        self.save_state()
        (self.home / "short").touch()
        self.open_window()
        result = self.cli("obsidian")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sync", self.calls())
        self.assertNotIn("create", self.calls())
        self.assert_relocked()


if __name__ == "__main__":
    unittest.main()
