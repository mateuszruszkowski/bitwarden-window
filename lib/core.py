"""Shared operations for a local, one-hour Bitwarden CLI session."""

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import tempfile
import time
from typing import NamedTuple
from urllib.parse import urlsplit

HOME_DIR = Path(pwd.getpwuid(os.getuid()).pw_dir)
RUNTIME_DIR = Path("/run/user") / str(os.getuid()) / "bw-window"
WINDOW_SECONDS = 3600
US_SERVER = "https://vault.bitwarden.com"
# Bitwarden accepts about 3.6 KiB of plaintext in one encrypted password field.
SECRET_LIMIT = 3072
# UTF-8 byte limits of one `save` request. JSON escaping at most doubles them.
LOGIN_LIMITS = {"name": 256, "secret": SECRET_LIMIT, "username": 256, "uri": 2048, "notes": 4096}
REQUEST_LIMIT = 32768
MESSAGES = {
    "closed": "Bitwarden window closed or session unavailable.",
    "expired": "The authentication window expired.",
    "busy": "A Bitwarden window is already active or starting.",
    "reconcile": "Recovery-note state is ambiguous. Reconcile the local escrow record and vault manually.",
    "relock": "A previous relock is unconfirmed. Run bw-window lock before unlocking again.",
    "fresh": "A fresh authentication timestamp is required.",
    "auth": "The authenticated Bitwarden account or server could not be verified.",
    "config": "Check the local Bitwarden window configuration.",
    "key": "The configured age identity could not be validated.",
    "https": "Vault writes require an HTTPS Bitwarden server.",
    "conflict": "An existing vault item conflicts with the requested personal item.",
    "different": "The stored identity differs from the local identity.",
    "duplicate": "Multiple vault items match the requested name.",
    "vault": "Bitwarden could not complete the operation.",
    "verify": "The vault item could not be verified after sync.",
    "input": f"Pipe one non-empty line of printable text, at most {SECRET_LIMIT} bytes, on standard input.",
    "item": "Use a printable item name and metadata within the documented limits.",
    "usage": "Usage: bw-window save NAME [--username USER] [--uri URL] [--notes-file FILE] < SECRET",
    "path": "Use a Linux installation path containing only ASCII letters, digits, spaces, or /._+@-.",
    "service": "The local Bitwarden window service could not complete the request.",
}


class Failure(Exception):
    """A fixed public error code, safe to send to the client."""


def read_file(path, limit, *, private=False):
    """Open each path component without following links, including parent directories."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError
    flags = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_RDONLY
    parent = os.open("/", flags)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, flags, dir_fd=parent)
            os.close(parent)
            parent = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as handle:
            st = os.fstat(fd)
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                    or st.st_mode & (0o077 if private else 0o022) or st.st_nlink != 1):
                raise ValueError
            data = handle.read(limit + 1)
            if len(data) > limit:
                raise ValueError
            return data
    finally:
        os.close(parent)


def executable(value):
    if not isinstance(value, str) or not value.startswith("/") or ".." in Path(value).parts:
        raise ValueError
    st = os.stat(value)
    if (not stat.S_ISREG(st.st_mode) or st.st_uid not in (0, os.getuid())
            or st.st_mode & 0o022 or not os.access(value, os.X_OK)):
        raise ValueError
    return value


def configured_binaries():
    try:
        paths = json.loads(read_file(HOME_DIR / ".local/lib/bw-window/paths.json", 16384))
        bw = executable(paths["bw"])
        try:
            age = executable(paths["age_keygen"]) if paths.get("age_keygen") is not None else None
        except (ValueError, OSError):
            age = None  # A removed optional helper must never interfere with relocking.
        return bw, age, paths.get("cli_env", {})
    except (KeyError, OSError, ValueError, TypeError, RecursionError):
        raise Failure("config") from None


# The platform wrappers use these installer-selected executables unchanged.
# Defer reporting a broken installation until a native operation is requested,
# so the timer, socket client and explicit lock command remain available.
try:
    BW, AGE_KEYGEN, CLI_ENV = configured_binaries()
except Failure:
    BW = AGE_KEYGEN = None
    CLI_ENV = {}


def now():
    clock = time.CLOCK_MONOTONIC_RAW if sys.platform == "darwin" else time.CLOCK_BOOTTIME
    return time.clock_gettime(clock)


def fresh(value):
    if not value.isascii() or not value.isdecimal() or len(value) > 12:
        raise Failure("fresh")
    stamp = int(value)
    if not 0 <= now() - stamp <= 30:
        raise Failure("fresh")
    return stamp


class Settings(NamedTuple):
    server: str | None
    identity: Path | None
    title: str | None


def server_url(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError
    parts = urlsplit(value)
    if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None
            or parts.password is not None or "?" in value or "#" in value or "\\" in value):
        raise ValueError
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    port = parts.port
    if port is not None and port != (443 if parts.scheme == "https" else 80):
        host += f":{port}"
    return f"{parts.scheme}://{host}" + parts.path.rstrip("/")


def settings():
    path = HOME_DIR / ".config/bw-window/config.json"
    try:
        try:
            values = json.loads(read_file(path, 16384))
        except FileNotFoundError:
            values = {}
        if not isinstance(values, dict) or values.keys() - {"server_url", "identity_file", "note_title"}:
            raise ValueError
        server = server_url(values["server_url"]) if "server_url" in values else None
        if server is not None and not server.startswith("https://"):
            raise ValueError
        identity = values.get("identity_file")
        if identity is not None:
            identity = HOME_DIR / identity[2:] if identity.startswith("~/") else Path(identity)
            if not identity.is_absolute() or ".." in identity.parts:
                raise ValueError
        title = values.get("note_title")
        if title is not None and (not isinstance(title, str) or not title or len(title) > 256
                                  or not title.isprintable() or title.strip() != title or title.startswith("-")):
            raise ValueError
        return Settings(server, identity, title)
    except (AttributeError, TypeError, ValueError, OSError, RecursionError):
        raise Failure("config") from None


def bw_env(token=None):
    path = os.pathsep.join([str(Path(BW).parent), "/usr/bin", "/bin"]) if BW else "/usr/bin:/bin"
    env = {**CLI_ENV, "HOME": str(HOME_DIR), "PATH": path, "LANG": "C.UTF-8"}
    if token is not None:
        env["BW_SESSION"] = token
    return env


def native(token, *args, data=b"", as_json=False):
    if BW is None:
        raise Failure("config")
    try:
        result = subprocess.run([BW, "--nointeraction", *args], input=data, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=bw_env(token), timeout=45)
        if result.returncode and args == ("lock",) and token is None:
            # On a fresh installation bw rejects lock with "unauthenticated".
            # Only this state proves there is no CLI account to relock.
            state = native(None, "status", as_json=True)
            if isinstance(state, dict) and state.get("status") == "unauthenticated":
                return None
        result.check_returncode()
        return json.loads(result.stdout) if as_json else None
    except (ValueError, OSError, subprocess.SubprocessError):
        raise Failure("vault") from None


class Account(str):
    """Preserve the user ID interface and bind escrow consent to this window's configuration."""

    def __new__(cls, value, server, configuration):
        result = super().__new__(cls, value)
        result.server = server
        result.configuration = configuration
        return result


def account(token, expected=None):
    configuration = settings()
    state = native(token, "status", as_json=True)
    if not isinstance(state, dict) or "serverUrl" not in state:
        raise Failure("auth")
    try:
        server = US_SERVER if state["serverUrl"] is None else server_url(state["serverUrl"])
    except ValueError:
        raise Failure("auth") from None
    user = state.get("userId")
    if (state.get("status") != "unlocked"
            or (configuration.server is not None and server != configuration.server)
            or not isinstance(user, str) or not user
            or (expected is not None and user != expected)
            or (isinstance(expected, Account) and (configuration != expected.configuration
                                                   or server != expected.server))):
        raise Failure("auth")
    return Account(user, server, configuration)


def read_identity(identity):
    if AGE_KEYGEN is None:
        raise Failure("key")
    try:
        data = read_file(identity, 8192, private=True)
        lines = [line for line in data.splitlines() if line and not line.startswith(b"#")]
        if len(lines) != 1 or not re.fullmatch(rb"AGE-SECRET-KEY-1[A-Z0-9]+", lines[0]):
            raise Failure("key")
        secret = lines[0] + b"\n"
        result = subprocess.run([AGE_KEYGEN, "-y"], input=secret, capture_output=True,
                                timeout=5, check=True, env=bw_env())
        if not re.fullmatch(rb"age1[a-z0-9]+\n?", result.stdout):
            raise Failure("key")
        return secret.decode("ascii")
    except (OSError, ValueError, subprocess.SubprocessError):
        raise Failure("key") from None


def find_note(call, title):
    def matches(*flags):
        items = call("list", "items", "--search", title, *flags, as_json=True)
        if not isinstance(items, list) or any(not isinstance(item, dict) or
                                              not isinstance(item.get("name"), str) for item in items):
            raise Failure("vault")
        return [item for item in items if item["name"].casefold() == title.casefold()]

    active = matches()
    if len(active) > 1:
        raise Failure("duplicate")
    # Without archive entitlement bw can return the active record for --archived.
    for item in matches("--archived"):
        if (not active or not item.get("id") or item["id"] != active[0].get("id")
                or item.get("archivedDate") or item.get("deletedDate")):
            raise Failure("conflict")
    if matches("--trash"):
        raise Failure("conflict")
    return active[0] if active else None


def verify_item(item, title, secret):
    if (not isinstance(item, dict) or item.get("name") != title or item.get("type") != 2
            or item.get("organizationId") is not None or item.get("deletedDate")
            or item.get("archivedDate") or not isinstance(item.get("id"), str) or not item["id"]
            or item["id"].startswith("-") or not isinstance(item.get("notes"), str)):
        raise Failure("conflict")
    stored = [line.strip() for line in item["notes"].splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    if len(stored) != 1 or not hmac.compare_digest(stored[0].encode(), secret.strip().encode()):
        raise Failure("different")
    return item["id"]


def runtime():
    RUNTIME_DIR.mkdir(mode=0o700, exist_ok=True)
    st = RUNTIME_DIR.lstat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid()
            or stat.S_IMODE(st.st_mode) != 0o700):
        raise Failure("service")


def record_verification():
    runtime()
    with tempfile.NamedTemporaryFile(mode="w", dir=RUNTIME_DIR, delete=False) as receipt:
        receipt.write(str(int(time.time())) + "\n")
    os.replace(receipt.name, RUNTIME_DIR / "obsidian-verified")


def sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def state_directory():
    directory = HOME_DIR
    for name in (".local", "state", "bw-window"):
        parent = directory
        directory = parent / name
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        else:
            sync_directory(parent)
        st = directory.lstat()
        forbidden = 0o077 if name == "bw-window" else 0o022
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & forbidden:
            raise Failure("service")
    return directory


def reserve(path):
    """An empty durable file is the write intent. Only one caller can acquire it."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise Failure("reconcile") from None
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    sync_directory(path.parent)


def known_id(path):
    try:
        value = json.loads(read_file(path, 4096, private=True))
        item_id = value["id"]
        if not isinstance(item_id, str) or not item_id:
            raise ValueError
        return item_id
    except FileNotFoundError:
        return None
    except (OSError, TypeError, ValueError, KeyError):
        raise Failure("reconcile") from None


def confirm_id(path, item_id):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as record:
        json.dump({"id": item_id}, record)
        record.flush()
        os.fsync(record.fileno())
    os.replace(record.name, path)
    sync_directory(path.parent)


def escrow(token, user):
    if not isinstance(user, Account):
        raise Failure("auth")
    principal = account(token, user)
    if not principal.server.startswith("https://"):
        raise Failure("https")
    identity = principal.configuration.identity
    title = principal.configuration.title
    if identity is None or title is None:
        raise Failure("config")
    destination = json.dumps([principal.server, str(principal), title.casefold()]).encode()
    record = state_directory() / ("escrow-" + hashlib.sha256(destination).hexdigest() + ".json")
    known = known_id(record)

    def call(*args, **kwargs):
        account(token, principal)
        return native(token, *args, **kwargs)

    call("sync")
    item = find_note(call, title)
    if known is not None and (item is None or item.get("id") != known):
        raise Failure("reconcile")
    account(token, principal)
    secret = read_identity(identity)
    if item is None:
        # A timeout, lost reply, or crash could follow a successful create.
        # Persist intent first and leave it pending until independent readback.
        reserve(record)
        try:
            account(token, principal)
        except Failure:
            # No create was issued. Only this caller owns the exclusive intent.
            record.unlink()
            sync_directory(record.parent)
            raise
        payload = {"type": 2, "name": title, "notes": secret, "secureNote": {"type": 0},
                   "organizationId": None}
        item = native(token, "create", "item", data=base64.b64encode(json.dumps(payload).encode()),
                      as_json=True)
        outcome = "created"
    else:
        outcome = "verified"
    item_id = verify_item(item, title, secret)
    if outcome == "verified" and known is None:
        reserve(record)
    call("sync")
    current = find_note(call, title)
    if current is None or verify_item(current, title, secret) != item_id:
        raise Failure("verify")
    if verify_item(call("get", "item", item_id, as_json=True), title, secret) != item_id:
        raise Failure("verify")
    account(token, principal)
    if known is None:
        confirm_id(record, item_id)
    record_verification()
    return outcome


def login_fields(values):
    """Validate one save request. Errors are fixed codes that never echo its content."""
    if not isinstance(values, dict) or values.keys() != LOGIN_LIMITS.keys():
        raise Failure("item")
    for key, limit in LOGIN_LIMITS.items():
        value = values[key]
        if value is None and key in ("username", "uri", "notes"):
            continue
        if (not isinstance(value, str) or not value
                or not all(c.isprintable() or (key == "notes" and c in "\t\n") for c in value)
                or len(value.encode()) > limit):
            raise Failure("input" if key == "secret" else "item")
    name = values["name"]
    if name.strip() != name or name.startswith("-") or " " in (values["uri"] or ""):
        raise Failure("item")
    return values


def save_request(args):
    """Client side of save. The secret is read only from piped standard input."""
    options = {"--username": "username", "--uri": "uri", "--notes-file": "notes"}
    values = dict.fromkeys(LOGIN_LIMITS)
    args = list(args)
    while args:
        arg = args.pop(0)
        if arg in options and args and values[options[arg]] is None:
            values[options[arg]] = args.pop(0)
        elif arg not in options and values["name"] is None:
            values["name"] = arg
        else:
            raise Failure("usage")
    if values["name"] is None:
        raise Failure("usage")
    if values["notes"] is not None:
        try:
            with open(values["notes"], "rb") as handle:
                values["notes"] = handle.read(LOGIN_LIMITS["notes"] + 2).decode().removesuffix("\n")
        except (OSError, ValueError):
            raise Failure("item") from None
    if sys.stdin is None or sys.stdin.isatty():
        raise Failure("input")
    # A read shorter than requested is the whole input; allow one trailing line ending.
    raw = sys.stdin.buffer.read(SECRET_LIMIT + 3)
    if len(raw) > SECRET_LIMIT + 2:
        raise Failure("input")
    try:
        values["secret"] = raw.decode().removesuffix("\n").removesuffix("\r")
    except ValueError:
        raise Failure("input") from None
    return json.dumps(login_fields(values), ensure_ascii=False).encode()


def verify_login(item, values):
    """Require the requested name and secret, and every metadata field the caller supplied."""
    if (not isinstance(item, dict) or item.get("name") != values["name"] or item.get("type") != 1
            or item.get("organizationId") is not None or item.get("deletedDate")
            or item.get("archivedDate") or not isinstance(item.get("id"), str) or not item["id"]
            or item["id"].startswith("-") or not isinstance(item.get("login"), dict)):
        raise Failure("conflict")
    login = item["login"]
    uris = login.get("uris") or []
    if (not isinstance(login.get("password"), str) or not isinstance(uris, list)
            or not hmac.compare_digest(login["password"].encode(), values["secret"].encode())
            or (values["username"] is not None and login.get("username") != values["username"])
            or (values["notes"] is not None and item.get("notes") != values["notes"])
            or (values["uri"] is not None
                and [isinstance(uri, dict) and uri.get("uri") for uri in uris] != [values["uri"]])):
        raise Failure("conflict")
    return item["id"]


def save(token, user, data):
    """Create one personal login item or verify an identical one. Never edit or return it."""
    if not isinstance(user, Account):
        raise Failure("auth")
    try:
        if len(data) > REQUEST_LIMIT:
            raise ValueError
        values = login_fields(json.loads(data))
    except (ValueError, RecursionError):
        raise Failure("item") from None
    principal = account(token, user)
    if not principal.server.startswith("https://"):
        raise Failure("https")

    def call(*args, **kwargs):
        account(token, principal)
        return native(token, *args, **kwargs)

    # No durable intent record: after a lost create reply, a retry with the same
    # input finds the item and verifies it.
    call("sync")
    item = find_note(call, values["name"])
    if item is None:
        login = {"username": values["username"], "password": values["secret"],
                 "uris": [{"uri": values["uri"], "match": None}] if values["uri"] else []}
        payload = {"type": 1, "name": values["name"], "notes": values["notes"], "login": login,
                   "organizationId": None}
        item = call("create", "item", data=base64.b64encode(json.dumps(payload).encode()), as_json=True)
        outcome = "created"
    else:
        outcome = "verified"
    item_id = verify_login(item, values)
    call("sync")
    current = find_note(call, values["name"])
    if current is None or verify_login(current, values) != item_id:
        raise Failure("verify")
    if verify_login(call("get", "item", item_id, as_json=True), values) != item_id:
        raise Failure("verify")
    account(token, principal)
    return outcome
