"""Private developer setup for local secrets.

Prompts (hidden input) for the Postgres password of ``mentor_pro_admin`` and
the OpenRouter API key, then:

* sets the role password as a SCRAM-SHA-256 verifier computed locally, so the
  plaintext password never reaches the server or its logs;
* writes ``.env`` at the repository root (git-ignored);
* adds/updates the matching line in the user's ``pgpass.conf``.

Run it yourself in a private terminal; secrets are never printed.

    python scripts/dev/setup_secrets.py
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"

DB_HOST = "127.0.0.1"
DB_PORT = "5432"
DB_NAME = "mentor_pro"
DB_ROLE = "mentor_pro_admin"
SCRAM_ITERATIONS = 4096
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def scram_sha256_verifier(password: str, salt: bytes | None = None,
                          iterations: int = SCRAM_ITERATIONS) -> str:
    """Return a Postgres SCRAM-SHA-256 verifier (RFC 5802/7677) for password."""
    salt = salt if salt is not None else secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def find_psql() -> str:
    found = shutil.which("psql")
    if found:
        return found
    for version in ("17", "16", "15"):
        candidate = Path(rf"C:\Program Files\PostgreSQL\{version}\bin\psql.exe")
        if candidate.exists():
            return str(candidate)
    sys.exit("psql not found; add the PostgreSQL bin directory to PATH.")


def prompt_secret(label: str, min_length: int) -> str:
    while True:
        first = getpass.getpass(f"{label}: ")
        if len(first) < min_length:
            print(f"Must be at least {min_length} characters.")
            continue
        if getpass.getpass(f"Repeat {label}: ") != first:
            print("Values do not match; try again.")
            continue
        return first


def set_role_password(psql: str, superuser: str, verifier: str) -> None:
    # The verifier is a hash, not the password; it is passed via stdin.
    sql = f"ALTER ROLE {DB_ROLE} PASSWORD '{verifier}';\n"
    result = subprocess.run(
        [psql, "-h", DB_HOST, "-p", DB_PORT, "-U", superuser, "-d", "postgres",
         "-v", "ON_ERROR_STOP=1", "-q"],
        input=sql, text=True, capture_output=True,
    )
    if result.returncode != 0:
        sys.exit(f"Could not set the role password: {result.stderr.strip()}")


def write_env(db_password: str, openrouter_key: str) -> None:
    managed = {
        "DATABASE_URL": f"postgresql://{DB_ROLE}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
        "PGHOST": DB_HOST,
        "PGPORT": DB_PORT,
        "PGDATABASE": DB_NAME,
        "PGUSER": DB_ROLE,
        "PGPASSWORD": db_password,
        "OPENROUTER_API_KEY": openrouter_key,
        "OPENROUTER_BASE_URL": OPENROUTER_BASE_URL,
    }
    kept: list[str] = []
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            key = line.split("=", 1)[0].strip()
            if key not in managed:
                kept.append(line)
    lines = kept + [f"{k}={v}" for k, v in managed.items()]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_pgpass(db_password: str) -> Path:
    if os.name == "nt":
        path = Path(os.environ["APPDATA"]) / "postgresql" / "pgpass.conf"
    else:
        path = Path.home() / ".pgpass"
    path.parent.mkdir(parents=True, exist_ok=True)
    escaped = db_password.replace("\\", "\\\\").replace(":", "\\:")
    prefix = f"{DB_HOST}:{DB_PORT}:{DB_NAME}:{DB_ROLE}:"
    lines = []
    if path.exists():
        lines = [l for l in path.read_text(encoding="utf-8").splitlines()
                 if not l.startswith(prefix)]
    lines.append(prefix + escaped)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    return path


def main() -> None:
    psql = find_psql()
    superuser = input("Postgres superuser to apply the change [postgres]: ").strip() or "postgres"
    db_password = prompt_secret(f"New password for {DB_ROLE}", min_length=12)
    keep_key = ENV_PATH.exists() and "OPENROUTER_API_KEY=" in ENV_PATH.read_text(encoding="utf-8")
    openrouter_key = getpass.getpass(
        "OpenRouter API key" + (" (Enter keeps current)" if keep_key else "") + ": ").strip()
    if not openrouter_key and keep_key:
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                openrouter_key = line.split("=", 1)[1]
    if not openrouter_key:
        sys.exit("An OpenRouter API key is required.")

    set_role_password(psql, superuser, scram_sha256_verifier(db_password))
    write_env(db_password, openrouter_key)
    pgpass = update_pgpass(db_password)
    print(f"Done. Role password set; wrote {ENV_PATH.name} and {pgpass}.")


if __name__ == "__main__":
    main()
