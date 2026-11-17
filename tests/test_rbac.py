import pytest
from fastapi.testclient import TestClient

from pocketpal.api import create_app
from pocketpal.auth import COOKIE, Auth, create_staff, hash_password, verify_password
from pocketpal.db import DB
from pocketpal.llm import MockProvider

H = {"X-Requested-With": "pocketpal"}
PW = "Correct-horse-9"


@pytest.fixture
def env():
    db = DB(":memory:")
    db.set_setting("classifier_enabled", False)
    for email, role in [("super@x.io", "super_admin"), ("admin@x.io", "admin"), ("viewer@x.io", "viewer")]:
        create_staff(db, email, role.title(), role, PW)
    app = create_app(providers=[MockProvider()], stt=None, tts=None, db=db, secret=b"rbac-secret")
    return db, app


def signed_in(app, email):
    c = TestClient(app)
    assert c.post("/api/admin/login", json={"email": email, "password": PW}).status_code == 200
    return c


# (method, path, body, minimum role)
ENDPOINTS = [
    ("get", "/api/admin/stats", None, "viewer"),
    ("get", "/api/admin/events", None, "viewer"),
    ("get", "/api/admin/audit", None, "viewer"),
    ("get", "/api/admin/settings", None, "viewer"),
    ("get", "/api/admin/devices/blocked", None, "viewer"),
    ("put", "/api/admin/settings", {"off_topic_mode": "strict"}, "admin"),
    ("post", "/api/admin/devices/block", {"device": "abcdef0123456789", "reason": "spam"}, "admin"),
    ("delete", "/api/admin/devices/block/abcdef0123456789", None, "admin"),
    ("get", "/api/admin/staff", None, "admin"),
    ("post", "/api/admin/staff", {"email": "new@x.io", "name": "New", "role": "viewer", "password": "Another-pass-1"}, "super_admin"),
    ("patch", "/api/admin/staff/3", {"name": "Renamed"}, "super_admin"),
    ("post", "/api/admin/staff/3/password", {"password": "Brand-new-pass-2"}, "super_admin"),
]
RANK = {"viewer": 0, "admin": 1, "super_admin": 2}


@pytest.mark.parametrize("who", ["viewer", "admin", "super_admin"])
@pytest.mark.parametrize("method, path, body, minimum", ENDPOINTS)
def test_permission_matrix(env, who, method, path, body, minimum):
    db, app = env
    c = signed_in(app, {"viewer": "viewer@x.io", "admin": "admin@x.io", "super_admin": "super@x.io"}[who])
    kwargs = {"headers": H} | ({"json": body} if body is not None else {})
    status = getattr(c, method)(path, **kwargs).status_code
    if RANK[who] >= RANK[minimum]:
        assert status in (200, 201), (who, path, status)
    else:
        assert status == 403, (who, path, status)


@pytest.mark.parametrize("method, path, body, minimum", ENDPOINTS)
def test_signed_out_gets_401(env, method, path, body, minimum):
    _, app = env
    kwargs = {"headers": H} | ({"json": body} if body is not None else {})
    assert getattr(TestClient(app), method)(path, **kwargs).status_code == 401


def test_csrf_header_required_for_changes(env):
    _, app = env
    c = signed_in(app, "super@x.io")
    assert c.put("/api/admin/settings", json={"off_topic_mode": "strict"}).status_code == 403
    assert c.put("/api/admin/settings", json={"off_topic_mode": "strict"}, headers=H).status_code == 200


def test_wrong_password_and_lockout(env):
    db, app = env
    c = TestClient(app)
    for _ in range(5):
        assert c.post("/api/admin/login", json={"email": "admin@x.io", "password": "nope"}).status_code == 401
    assert c.post("/api/admin/login", json={"email": "admin@x.io", "password": PW}).status_code == 429
    assert [e["action"] for e in db.q("SELECT action FROM audit_log")].count("login.failed") == 5


def test_tampered_or_forged_token_rejected(env):
    _, app = env
    c = signed_in(app, "viewer@x.io")
    token = c.cookies.get(COOKIE)
    body, sig = token.rsplit(".", 1)
    forged = Auth(DB(":memory:"), b"other-secret").issue({"id": 1, "token_version": 0})
    for bad in (body + "x." + sig, body + "." + sig[:-2] + "aa", forged):
        c2 = TestClient(app)
        c2.cookies.set(COOKIE, bad, path="/api/admin")
        assert c2.get("/api/admin/me").status_code == 401


def test_role_change_signs_person_out_everywhere(env):
    db, app = env
    sup, adm = signed_in(app, "super@x.io"), signed_in(app, "admin@x.io")
    assert adm.get("/api/admin/staff").status_code == 200
    assert sup.patch("/api/admin/staff/2", json={"role": "viewer"}, headers=H).status_code == 200
    assert adm.get("/api/admin/me").status_code == 401


def test_deactivated_staff_cannot_sign_in(env):
    _, app = env
    sup = signed_in(app, "super@x.io")
    sup.patch("/api/admin/staff/3", json={"active": False}, headers=H)
    assert TestClient(app).post("/api/admin/login", json={"email": "viewer@x.io", "password": PW}).status_code == 401


def test_super_admin_cannot_demote_self_and_last_super_admin_is_protected(env):
    db, app = env
    sup = signed_in(app, "super@x.io")
    assert sup.patch("/api/admin/staff/1", json={"role": "admin"}, headers=H).status_code == 400
    assert sup.patch("/api/admin/staff/1", json={"active": False}, headers=H).status_code == 400
    # a second super admin can't remove the first if they'd be the last one... promote admin, then try to demote both
    sup.patch("/api/admin/staff/2", json={"role": "super_admin"}, headers=H)
    second = signed_in(app, "admin@x.io")
    assert second.patch("/api/admin/staff/1", json={"role": "viewer"}, headers=H).status_code == 200
    assert TestClient(app).post("/api/admin/login", json={"email": "super@x.io", "password": PW}).status_code == 200
    db.run("UPDATE staff SET active = 0 WHERE id = 1")
    assert db.one("SELECT COUNT(*) AS n FROM staff WHERE role='super_admin' AND active=1")["n"] == 1


def test_weak_passwords_rejected(env):
    _, app = env
    sup = signed_in(app, "super@x.io")
    r = sup.post("/api/admin/staff", json={"email": "w@x.io", "name": "W", "role": "viewer", "password": "alllowercase1"}, headers=H)
    assert r.status_code == 400


def test_settings_validation(env):
    _, app = env
    adm = signed_in(app, "admin@x.io")
    for bad in ({"off_topic_mode": "chaos"}, {"max_reply_sentences": 99}, {"unknown": 1}, {"classifier_enabled": "yes"}):
        assert adm.put("/api/admin/settings", json=bad, headers=H).status_code == 400


def test_settings_change_guardrails_live_and_is_audited(env):
    db, app = env
    adm = signed_in(app, "admin@x.io")
    adm.put("/api/admin/settings", json={"maintenance_message": "Back in five minutes."}, headers=H)
    r = TestClient(app).post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.json()["reply"] == "Back in five minutes." and r.json()["route"] == "maintenance"
    entry = db.one("SELECT * FROM audit_log WHERE action = 'settings.update'")
    assert entry["actor_email"] == "admin@x.io"


def test_blocked_device_is_refused_and_others_are_not(env):
    db, app = env
    user = TestClient(app)
    user.post("/api/chat", json={"messages": [{"role": "user", "content": "hello"}]}, headers={"X-Device-Id": "device-123"})
    device = db.one("SELECT device FROM events")["device"]
    assert device and "device-123" not in device                      # stored only as a keyed hash
    signed_in(app, "admin@x.io").post("/api/admin/devices/block", json={"device": device, "reason": "abuse"}, headers=H)
    assert user.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}, headers={"X-Device-Id": "device-123"}).status_code == 403
    assert user.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}, headers={"X-Device-Id": "other"}).status_code == 200


def test_admins_can_never_see_what_people_said(env):
    db, app = env
    TestClient(app).post("/api/chat", json={"messages": [{"role": "user", "content": "my secret is pineapple"}]})
    sup = signed_in(app, "super@x.io")
    for path in ("/api/admin/events", "/api/admin/stats", "/api/admin/audit"):
        assert "pineapple" not in sup.get(path).text
    dump = "\n".join(db._conn.iterdump())
    assert "pineapple" not in dump


def test_passwords_are_hashed():
    h = hash_password("Some-password-1")
    assert "Some-password-1" not in h and verify_password("Some-password-1", h) and not verify_password("wrong", h)


def test_bootstrap_super_admin_from_env(monkeypatch):
    monkeypatch.setenv("SUPERADMIN_EMAIL", "boot@x.io")
    monkeypatch.setenv("SUPERADMIN_PASSWORD", "Boot-strap-pass-1")
    db = DB(":memory:")
    create_app(providers=[MockProvider()], stt=None, tts=None, db=db, secret=b"s")
    assert db.one("SELECT role FROM staff WHERE email = 'boot@x.io'")["role"] == "super_admin"
    create_app(providers=[MockProvider()], stt=None, tts=None, db=db, secret=b"s")   # second start: no duplicate
    assert db.one("SELECT COUNT(*) AS n FROM staff")["n"] == 1
