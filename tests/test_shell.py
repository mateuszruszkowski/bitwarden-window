"""Full CLI stays in the originating shell; fixtures never contact a vault."""
import os
from pathlib import Path
import pty
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).absolute().parents[1] / "lib/shell.sh"


class ShellTest(unittest.TestCase):
    def test_token_scope_and_expiry(self):
        for shell in ("bash", "zsh"):
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as td:
                exe = shutil.which(shell)
                if not exe:
                    continue
                home = Path(td)
                bindir = home / ".local/bin"
                lib = home / ".local/lib/bw-window"
                bindir.mkdir(parents=True)
                lib.mkdir(parents=True)
                for file, body in [
                    (bindir / "bw-unlock", "printf '100 fixture-only'"),
                    (bindir / "bw-window", 'cat "$HOME/time"'),
                    (lib / "native-bw", 'test "$BW_SESSION" = fixture-only'),
                ]:
                    file.write_text("#!/bin/sh\n" + body + "\n")
                    file.chmod(0o700)
                master, slave = pty.openpty()
                try:
                    command = """
set -e
. "$1"
bw-unlock
echo 102 > "$HOME/time"
bw status
if env | grep -Eq 'fixture-only|^BW_SESSION='; then exit 3; fi
echo 3700 > "$HOME/time"
if bw status; then exit 4; fi
test -z "${__bw_window_key+x}"
"""
                    check = subprocess.run([exe, "-c", command, "check", SOURCE], stdin=slave,
                                           capture_output=True, timeout=10,
                                           env={"HOME": td, "PATH": "/usr/bin:/bin"})
                    self.assertEqual(check.returncode, 0, check.stderr)
                finally:
                    os.close(slave)
                    os.close(master)


if __name__ == "__main__":
    unittest.main()
