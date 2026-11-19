"""Record the selected executables and non-secret CLI profile settings at install time."""
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit


def cli_environment():
    env = {}
    for key in ("BITWARDENCLI_APPDATA_DIR", "XDG_CONFIG_HOME", "NODE_EXTRA_CA_CERTS"):
        value = os.environ.get(key)
        if value:
            if not os.path.isabs(value):
                raise SystemExit(f"{key} must be an absolute path.")
            env[key] = value
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        value = os.environ.get(key)
        if value:
            proxy = urlsplit(value)
            if (proxy.scheme not in ("http", "https") or not proxy.hostname or proxy.username is not None
                    or proxy.password is not None or proxy.query or proxy.fragment or proxy.path not in ("", "/")):
                raise SystemExit(f"{key} must be a proxy address without credentials, path, query or fragment.")
            env[key] = value
    for key in ("no_proxy", "NO_PROXY"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


if __name__ == "__main__":
    dest, bw, age = sys.argv[1:]
    settings = dict(bw=os.path.abspath(bw), age_keygen=os.path.abspath(age) if age else None,
                    python=sys.executable, cli_env=cli_environment())
    with tempfile.NamedTemporaryFile(mode="w", dir=Path(dest).parent, delete=False) as handle:
        json.dump(settings, handle)
    os.replace(handle.name, dest)
