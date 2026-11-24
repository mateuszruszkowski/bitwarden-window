import hashlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("upgrade", Path(__file__).absolute().parents[1] / "lib/upgrade.py")
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


def tarball(version, installer):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as bundle:
        body = installer.encode()
        info = tarfile.TarInfo(f"bitwarden-window-{version}-omarchy/install.sh")
        info.size, info.mode = len(body), 0o755
        bundle.addfile(info, io.BytesIO(body))
    return data.getvalue()


class UpgradeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.releases = self.home / ".local/share/bw-window/releases"
        (self.home / ".local/bin").mkdir(parents=True)
        self.status(1)
        for patch in (mock.patch.dict(os.environ, HOME=str(self.home)),
                      mock.patch.object(sys, "platform", "linux"),
                      mock.patch.object(upgrade, "latest_tag", return_value="v0.9.0")):
            patch.start()
            self.addCleanup(patch.stop)
        self.files = {}
        fetch = mock.patch.object(upgrade, "fetch", side_effect=lambda url, limit: self.files[url.rsplit("/", 1)[-1]])
        self.fetch = fetch.start()
        self.addCleanup(fetch.stop)

    def status(self, code):
        client = self.home / ".local/bin/bw-window"
        client.write_text(f"#!/bin/sh\nexit {code}\n")
        client.chmod(0o700)

    def publish(self, archive, digest=None):
        asset = "bitwarden-window-0.9.0-omarchy.tar.gz"
        self.files[asset] = archive
        self.files["SHA256SUMS"] = f"{digest or hashlib.sha256(archive).hexdigest()}  {asset}\n".encode()

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            try:
                code = upgrade.main(list(args))
            except SystemExit as exc:
                code, err = 1, io.StringIO(str(exc))
        return code, out.getvalue() + err.getvalue()

    def test_installs_verified_latest_and_keeps_previous(self):
        self.publish(tarball("0.9.0", '#!/bin/sh\necho installed > "$HOME/ran"\n'))
        current = "v" + upgrade.VERSION
        for old in ("v0.7.9", current, "notes"):
            (self.releases / old).mkdir(parents=True)
        code, output = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertEqual((self.home / "ran").read_text(), "installed\n")
        self.assertTrue((self.releases / "v0.9.0/install.sh").is_file())
        self.assertEqual(sorted(p.name for p in self.releases.iterdir()), sorted(["notes", current, "v0.9.0"]))

    def test_checksum_mismatch_installs_nothing(self):
        self.publish(tarball("0.9.0", '#!/bin/sh\ntouch "$HOME/ran"\n'), digest="0" * 64)
        code, output = self.run_main("v0.9.0")
        self.assertEqual(code, 1)
        self.assertIn("does not match", output)
        self.assertFalse((self.home / "ran").exists())
        self.assertFalse((self.releases / "v0.9.0").exists())

    def test_open_window_blocks_before_download(self):
        for code in (0, 4):
            self.status(code)
            result, output = self.run_main("v0.9.0")
            self.assertEqual(result, 1)
            self.assertIn("bw-window lock", output)
        self.fetch.assert_not_called()

    def test_failed_installer_keeps_package_and_old_releases(self):
        self.publish(tarball("0.9.0", "#!/bin/sh\nexit 3\n"))
        (self.releases / "v0.8.1").mkdir(parents=True)
        code, output = self.run_main()
        self.assertEqual(code, 3)
        self.assertIn("verified package", output)
        self.assertTrue((self.releases / "v0.8.1").is_dir())

    def test_tag_rules(self):
        self.assertEqual(self.run_main("v0.7.0")[0], 1)
        self.assertEqual(self.run_main("latest")[0], 1)
        self.assertEqual(self.run_main("v0.9.0", "extra")[0], 2)
        code, output = self.run_main("v" + upgrade.VERSION)
        self.assertEqual(code, 0)
        self.assertIn("already installed", output)
        self.fetch.assert_not_called()

    def test_archive_escape_is_rejected(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as bundle:
            info = tarfile.TarInfo("../outside")
            bundle.addfile(info, io.BytesIO())
        self.publish(data.getvalue())
        self.assertEqual(self.run_main("v0.9.0")[0], 1)
        self.assertFalse((self.home / ".local/share/bw-window/outside").exists())


if __name__ == "__main__":
    unittest.main()
