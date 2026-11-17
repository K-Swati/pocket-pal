"""Staff authentication and role-based access control (RBAC).

- Passwords: PBKDF2-SHA256 with a per-user salt and constant-time comparison.
- Sessions: an HMAC-signed token in an httpOnly, SameSite=Strict cookie. Each staff row has a token_version;
  changing a password, role or active flag bumps it, which instantly signs that person out everywhere.
- CSRF: state-changing admin requests must also send the X-Requested-With header, which other sites cannot set.
- Brute force: repeated failed logins for an email/IP pair are locked out for a while.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request

from pocketpal.db import DB

ROLES = ("viewer", "admin", "super_admin")
_VIEWER = {"dashboard:read", "events:read", "audit:read"}
_ADMIN = _VIEWER | {"settings:write", "devices:manage", "staff:read"}
PERMISSIONS: dict[str, frozenset] = {
    "viewer": frozenset(_VIEWER),
    "admin": frozenset(_ADMIN),
    "super_admin": frozenset(_ADMIN | {"staff:manage"}),
}
COOKIE = "pp_admin"
SESSION_SECONDS = 12 * 3600
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "pocketpal"


# ---- passwords ----
# PBKDF2-SHA256 (standard library everywhere), OWASP-recommended work factor. The iteration count is stored in
# each hash, so it can be raised later without breaking existing accounts.
def _iterations() -> int:
    return int(os.environ.get("PBKDF2_ITERATIONS", "600000"))


def hash_password(password: str) -> str:
    salt, n = secrets.token_bytes(16), _iterations()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, n)
    return f"pbkdf2_sha256${n}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(n))
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> Optional[str]:
    if len(password) < 10:
        return "Password must be at least 10 characters."
    if password.lower() == password or not any(c.isdigit() for c in password):
        return "Use upper and lower case letters and at least one number."
    return None


# ---- signing secret ----
def load_secret() -> bytes:
    env = os.environ.get("SECRET_KEY")
    if env:
        return env.encode()
    data = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    data.mkdir(parents=True, exist_ok=True)
    f = data / "secret.key"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
        f.chmod(0o600)
    return f.read_text().strip().encode()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))




class Auth:
    def __init__(self, db: DB, secret: bytes):
        self.db, self.secret = db, secret
        self._fails: dict[str, list[float]] = defaultdict(list)

    # ---- tokens ----
    def issue(self, staff: dict) -> str:
        body = _b64(json.dumps({"sid": staff["id"], "v": staff["token_version"], "exp": int(time.time()) + SESSION_SECONDS}).encode())
        sig = _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())
        return f"{body}.{sig}"

    def staff_from_token(self, token: Optional[str]) -> Optional[dict]:
        if not token or "." not in token:
            return None
        body, sig = token.rsplit(".", 1)
        good = _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        try:
            data = json.loads(_unb64(body))
        except ValueError:
            return None
        if data.get("exp", 0) < time.time():
            return None
        staff = self.db.one("SELECT * FROM staff WHERE id = ?", (data.get("sid"),))
        if not staff or not staff["active"] or staff["token_version"] != data.get("v"):
            return None
        return staff

    # ---- brute-force protection ----
    def _key(self, email: str, ip: str) -> str:
        return f"{email.lower()}|{ip}"

    def locked(self, email: str, ip: str, limit: int = 5, window: float = 900) -> bool:
        k = self._key(email, ip)
        self._fails[k] = [t for t in self._fails[k] if time.time() - t < window]
        return len(self._fails[k]) >= limit

    def failed(self, email: str, ip: str) -> None:
        self._fails[self._key(email, ip)].append(time.time())

    def cleared(self, email: str, ip: str) -> None:
        self._fails.pop(self._key(email, ip), None)

    def login(self, email: str, password: str) -> Optional[dict]:
        staff = self.db.one("SELECT * FROM staff WHERE email = ?", (email.strip(),))
        if not staff:
            verify_password(password, f"pbkdf2_sha256${_iterations()}${'00' * 16}${'00' * 32}")  # same work whether or not the email exists
            return None
        if not staff["active"] or not verify_password(password, staff["pw_hash"]):
            return None
        self.db.run("UPDATE staff SET last_login = ? WHERE id = ?", (time.time(), staff["id"]))
        return staff

    # ---- FastAPI dependencies ----
    def current(self, request: Request) -> dict:
        staff = self.staff_from_token(request.cookies.get(COOKIE))
        if not staff:
            raise HTTPException(401, "Please sign in.")
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            raise HTTPException(403, "Missing request header.")
        return staff

    def require(self, permission: str) -> Callable:
        def dep(staff: dict = Depends(self.current)) -> dict:
            if permission not in PERMISSIONS.get(staff["role"], ()):
                raise HTTPException(403, "Your role does not allow this.")
            return staff
        return dep


def public(staff: dict) -> dict:
    """Staff fields that are safe to send to the browser."""
    return {k: staff[k] for k in ("id", "email", "name", "role", "active", "created_at", "last_login")} | {
        "permissions": sorted(PERMISSIONS[staff["role"]])}


def create_staff(db: DB, email: str, name: str, role: str, password: str) -> int:
    if role not in ROLES:
        raise ValueError("unknown role")
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    return db.run("INSERT INTO staff(email, name, role, pw_hash, created_at) VALUES (?,?,?,?,?)",
                  (email.strip(), name.strip(), role, hash_password(password), time.time()))
