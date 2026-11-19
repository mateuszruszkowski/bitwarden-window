"""Exercise the public Omarchy installer in a private HOME, without a live desktop."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).absolute().parents[1]


@unittest.skipUnless(sys.platform == "linux" and sys.version_info >= (3, 13) and os.getuid() != 0,
                     "requires an unprivileged Linux user with Python 3.13+")
class InstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="bw-window-install-")
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / "test home"
        self.home.mkdir()
        self.bin = Path(temp.name) / "tools"
        self.bin.mkdir()
        for tool in ("bw", "ghostty", "hyprctl", "age-keygen", "systemd-run"):
            self.stub(tool, "exit 0")
        self.stub("systemctl", 'case "$*" in *is-active*) exit 3;; *) exit 0;; esac')
        self.stub("omarchy", 'case "$*" in "shell shell ping") echo ok;; *) exit 0;; esac')
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.home)}
        self.lib = self.home / ".local/lib/bw-window"
        self.client = self.home / ".local/bin/bw-window"

    def stub(self, name, code):
        script = self.bin / name
        script.write_text("#!/bin/sh\n" + code + "\n")
        script.chmod(0o700)

    def call(self, script):
        return subprocess.run([ROOT / script], env=self.env, capture_output=True, text=True)

    def test_install_upgrade_uninstall(self):
        for _ in range(2):
            result = self.call("install.sh")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.client.is_file())
        self.assertTrue((self.home / ".local/bin/bw-unlock").is_file())
        self.assertTrue((self.lib / "native-bw").samefile(self.bin / "bw"))
        config = self.home / ".config/bw-window/config.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("{}")
        result = self.call("uninstall.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.client.exists())
        self.assertFalse((self.home / ".local/bin/bw-unlock").exists())
        self.assertEqual(config.read_text(), "{}")

    def test_custom_profile_and_private_ca(self):
        self.env.update({"BITWARDENCLI_APPDATA_DIR": str(self.home / "custom profile"),
                         "XDG_CONFIG_HOME": str(self.home / "xdg"),
                         "NODE_EXTRA_CA_CERTS": str(self.home / "ca.pem"),
                         "HTTPS_PROXY": "http://proxy.example:8080",
                         "NO_PROXY": "vault.example",
                         "BW_SESSION": "fixture-excluded", "NODE_OPTIONS": "fixture-excluded"})
        result = self.call("install.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads((self.lib / "paths.json").read_text())
        self.assertEqual(config["cli_env"], {key: self.env[key] for key in (
            "BITWARDENCLI_APPDATA_DIR", "XDG_CONFIG_HOME", "NODE_EXTRA_CA_CERTS", "HTTPS_PROXY", "NO_PROXY")})
        self.assertTrue((self.home / ".config/omarchy/plugins/community.bitwarden-window/manifest.json").exists())

    def test_partial_desktop_removal_and_reinstall(self):
        self.assertEqual(self.call("install.sh").returncode, 0)
        plugin = self.home / ".config/omarchy/plugins/community.bitwarden-window"
        plugin.rename(plugin.with_suffix(".removed"))
        cache = self.lib / "__pycache__"
        cache.mkdir()
        (cache / "core.cpython-314.pyc").touch()
        self.assertEqual(self.call("uninstall.sh").returncode, 0)
        self.assertEqual(self.call("install.sh").returncode, 0)

    def test_maintenance_respects_auth_and_pending_relock(self):
        self.assertEqual(self.call("install.sh").returncode, 0)
        fd = os.open(self.lib.parent, os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            self.assertNotEqual(self.call("uninstall.sh").returncode, 0)
            self.assertNotEqual(self.call("install.sh").returncode, 0)
        finally:
            os.close(fd)
        marker = self.home / ".local/state/bw-window/relock-required"
        marker.parent.mkdir(parents=True)
        marker.touch()
        self.assertNotEqual(self.call("install.sh").returncode, 0)
        self.assertTrue(self.client.is_file())

    def test_foreign_client_is_preserved(self):
        self.client.parent.mkdir(parents=True)
        self.client.write_text("managed elsewhere")
        self.assertNotEqual(self.call("install.sh").returncode, 0)
        self.assertEqual(self.client.read_text(), "managed elsewhere")
        self.assertFalse(self.lib.exists())

    def test_foreign_shell_command_is_preserved(self):
        self.client.parent.mkdir(parents=True)
        other = self.client.with_name("bw-unlock")
        other.write_text("mine")
        self.assertNotEqual(self.call("install.sh").returncode, 0)
        self.assertEqual(other.read_text(), "mine")
        self.assertFalse(self.lib.exists())


if __name__ == "__main__":
    unittest.main()
