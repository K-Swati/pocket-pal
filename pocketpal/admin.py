"""Admin API. Every route declares the permission it needs; the role -> permission map lives in auth.py.

    viewer       dashboard, usage events, audit log (read only)
    admin        + guardrail settings, block/unblock devices, see the staff list
    super_admin  + create staff, change roles, deactivate, reset passwords

Every change and every sign-in attempt is written to the audit log. Nothing here can show what people said:
the database never stores message text.
"""

from __future__ import annotations

import time
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from pocketpal.auth import COOKIE, ROLES, SESSION_SECONDS, Auth, create_staff, hash_password, password_problem, public
from pocketpal.db import DEFAULT_SETTINGS, DB, SETTING_TYPES


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class StaffIn(BaseModel):
    email: str = Field(min_length=3, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(min_length=1, max_length=80)
    role: Literal["viewer", "admin", "super_admin"]
    password: str = Field(min_length=10, max_length=200)


class StaffPatch(BaseModel):
    role: Optional[Literal["viewer", "admin", "super_admin"]] = None
    active: Optional[bool] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)


class PasswordIn(BaseModel):
    password: str = Field(min_length=10, max_length=200)


class BlockIn(BaseModel):
    device: str = Field(min_length=8, max_length=64, pattern=r"^[a-f0-9]+$")
    reason: str = Field(default="", max_length=200)


def build_router(db: DB, auth: Auth) -> APIRouter:
    r = APIRouter(prefix="/api/admin")

    def ip(request: Request) -> str:
        return request.client.host if request.client else "?"

    # ---- session ----
    @r.post("/login")
    def login(body: LoginIn, request: Request, response: Response) -> dict:
        if auth.locked(body.email, ip(request)):
            db.audit(None, "login.locked", body.email)
            raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
        staff = auth.login(body.email, body.password)
        if not staff:
            auth.failed(body.email, ip(request))
            db.audit(None, "login.failed", body.email)
            raise HTTPException(401, "Email or password is incorrect.")
        auth.cleared(body.email, ip(request))
        db.audit(staff, "login.ok")
        response.set_cookie(COOKIE, auth.issue(staff), max_age=SESSION_SECONDS, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", path="/api/admin")
        return public(staff)

    @r.post("/logout")
    def logout(response: Response, staff: dict = Depends(auth.current)) -> dict:
        db.audit(staff, "logout")
        response.delete_cookie(COOKIE, path="/api/admin")
        return {"ok": True}

    @r.get("/me")
    def me(staff: dict = Depends(auth.current)) -> dict:
        return public(staff)

    @r.post("/me/password")
    def change_own_password(body: PasswordIn, staff: dict = Depends(auth.current)) -> dict:
        problem = password_problem(body.password)
        if problem:
            raise HTTPException(400, problem)
        db.run("UPDATE staff SET pw_hash = ?, token_version = token_version + 1 WHERE id = ?", (hash_password(body.password), staff["id"]))
        db.audit(staff, "password.change", staff["email"])
        return {"ok": True, "signed_out": True}

    # ---- dashboard (viewer+) ----
    @r.get("/stats")
    def stats(days: int = 7, staff: dict = Depends(auth.require("dashboard:read"))) -> dict:
        days = max(1, min(days, 90))
        since = time.time() - days * 86400
        chats = "FROM events WHERE kind = 'chat' AND ts >= ?"
        total = db.one(f"SELECT COUNT(*) AS n, COUNT(DISTINCT device) AS devices, AVG(latency_ms) AS avg_ms {chats}", (since,))
        return {
            "days": days,
            "messages": total["n"], "devices": total["devices"], "avg_latency_ms": round(total["avg_ms"] or 0),
            "by_category": db.q(f"SELECT category AS key, COUNT(*) AS n {chats} GROUP BY category ORDER BY n DESC", (since,)),
            "by_route": db.q(f"SELECT route AS key, COUNT(*) AS n {chats} GROUP BY route ORDER BY n DESC", (since,)),
            "by_provider": db.q(f"SELECT provider AS key, COUNT(*) AS n {chats} GROUP BY provider ORDER BY n DESC", (since,)),
            "crisis": db.one(f"SELECT COUNT(*) AS n {chats} AND category = 'crisis'", (since,))["n"],
            "guardrail_rewrites": db.one(f"SELECT COUNT(*) AS n {chats} AND flags LIKE '%output:%'", (since,))["n"],
            "per_day": db.q(f"SELECT date(ts, 'unixepoch') AS day, COUNT(*) AS n {chats} GROUP BY day ORDER BY day", (since,)),
        }

    @r.get("/events")
    def events(limit: int = 100, category: str = "", staff: dict = Depends(auth.require("events:read"))) -> dict:
        limit = max(1, min(limit, 500))
        where, args = ("WHERE category = ?", (category,)) if category else ("", ())
        rows = db.q(f"SELECT id, ts, kind, device, category, route, flags, provider, latency_ms FROM events {where} ORDER BY id DESC LIMIT ?",
                    args + (limit,))
        return {"events": rows}

    @r.get("/audit")
    def audit(limit: int = 100, staff: dict = Depends(auth.require("audit:read"))) -> dict:
        return {"entries": db.q("SELECT id, ts, actor_email, action, target, detail FROM audit_log ORDER BY id DESC LIMIT ?",
                                (max(1, min(limit, 500)),))}

    # ---- guardrail settings (read: viewer+, write: admin+) ----
    @r.get("/settings")
    def get_settings(staff: dict = Depends(auth.require("dashboard:read"))) -> dict:
        return {"settings": db.settings(), "defaults": DEFAULT_SETTINGS}

    @r.put("/settings")
    def put_settings(body: dict[str, Any], staff: dict = Depends(auth.require("settings:write"))) -> dict:
        changed = {}
        for key, value in body.items():
            if key not in SETTING_TYPES:
                raise HTTPException(400, f"Unknown setting: {key}")
            want = SETTING_TYPES[key]
            if want is int and (isinstance(value, bool) or not isinstance(value, int)) or want is not int and not isinstance(value, want):
                raise HTTPException(400, f"{key} must be {want.__name__}")
            if key == "off_topic_mode" and value not in ("redirect", "strict"):
                raise HTTPException(400, "off_topic_mode must be 'redirect' or 'strict'")
            if key == "max_reply_sentences" and not 1 <= value <= 8:
                raise HTTPException(400, "max_reply_sentences must be between 1 and 8")
            if key == "maintenance_message" and len(value) > 300:
                raise HTTPException(400, "maintenance_message is too long")
            changed[key] = value
        for key, value in changed.items():
            db.set_setting(key, value)
        db.audit(staff, "settings.update", detail=changed)
        return {"settings": db.settings()}

    # ---- devices (admin+) ----
    @r.get("/devices/blocked")
    def blocked(staff: dict = Depends(auth.require("events:read"))) -> dict:
        return {"devices": db.q("SELECT device, reason, blocked_by, ts FROM blocked_devices ORDER BY ts DESC")}

    @r.post("/devices/block")
    def block(body: BlockIn, staff: dict = Depends(auth.require("devices:manage"))) -> dict:
        db.run("INSERT OR REPLACE INTO blocked_devices(device, reason, blocked_by, ts) VALUES (?,?,?,?)",
               (body.device, body.reason, staff["email"], time.time()))
        db.audit(staff, "device.block", body.device, {"reason": body.reason})
        return {"ok": True}

    @r.delete("/devices/block/{device}")
    def unblock(device: str, staff: dict = Depends(auth.require("devices:manage"))) -> dict:
        db.run("DELETE FROM blocked_devices WHERE device = ?", (device,))
        db.audit(staff, "device.unblock", device)
        return {"ok": True}

    # ---- staff (list: admin+, manage: super_admin) ----
    @r.get("/staff")
    def list_staff(staff: dict = Depends(auth.require("staff:read"))) -> dict:
        return {"staff": [public(s) for s in db.q("SELECT * FROM staff ORDER BY created_at")]}

    @r.post("/staff", status_code=201)
    def add_staff(body: StaffIn, staff: dict = Depends(auth.require("staff:manage"))) -> dict:
        if db.one("SELECT 1 AS x FROM staff WHERE email = ?", (body.email,)):
            raise HTTPException(409, "Someone with that email already exists.")
        try:
            sid = create_staff(db, body.email, body.name, body.role, body.password)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        db.audit(staff, "staff.create", body.email, {"role": body.role})
        return public(db.one("SELECT * FROM staff WHERE id = ?", (sid,)))

    def _active_super_admins(exclude: int) -> int:
        return db.one("SELECT COUNT(*) AS n FROM staff WHERE role = 'super_admin' AND active = 1 AND id != ?", (exclude,))["n"]

    @r.patch("/staff/{sid}")
    def edit_staff(sid: int, body: StaffPatch, staff: dict = Depends(auth.require("staff:manage"))) -> dict:
        target = db.one("SELECT * FROM staff WHERE id = ?", (sid,))
        if not target:
            raise HTTPException(404, "No such staff member.")
        if sid == staff["id"] and (body.role not in (None, target["role"]) or body.active is False):
            raise HTTPException(400, "You can't change your own role or deactivate yourself.")
        losing_super = target["role"] == "super_admin" and target["active"] and (
            (body.role and body.role != "super_admin") or body.active is False)
        if losing_super and _active_super_admins(sid) == 0:
            raise HTTPException(400, "There must always be at least one active super admin.")
        updates, args = [], []
        for col in ("role", "active", "name"):
            val = getattr(body, col)
            if val is not None:
                updates.append(f"{col} = ?")
                args.append(int(val) if col == "active" else val)
        if not updates:
            return public(target)
        db.run(f"UPDATE staff SET {', '.join(updates)}, token_version = token_version + 1 WHERE id = ?", tuple(args) + (sid,))
        db.audit(staff, "staff.update", target["email"], body.model_dump(exclude_none=True))
        return public(db.one("SELECT * FROM staff WHERE id = ?", (sid,)))

    @r.post("/staff/{sid}/password")
    def reset_password(sid: int, body: PasswordIn, staff: dict = Depends(auth.require("staff:manage"))) -> dict:
        target = db.one("SELECT * FROM staff WHERE id = ?", (sid,))
        if not target:
            raise HTTPException(404, "No such staff member.")
        problem = password_problem(body.password)
        if problem:
            raise HTTPException(400, problem)
        db.run("UPDATE staff SET pw_hash = ?, token_version = token_version + 1 WHERE id = ?", (hash_password(body.password), sid))
        db.audit(staff, "staff.password_reset", target["email"])
        return {"ok": True}

    return r
