import re

import pytest
from playwright.sync_api import Page, expect

from pocketpal.auth import create_staff

from .test_ui import enter, send

pytestmark = pytest.mark.e2e
PW = "Correct-horse-9"


@pytest.fixture
def staffed(server):
    for email, role in [("super@x.io", "super_admin"), ("admin@x.io", "admin"), ("viewer@x.io", "viewer")]:
        create_staff(server.db, email, role.replace("_", " ").title(), role, PW)
    return server


def sign_in(page: Page, url: str, email: str, password: str = PW):
    page.goto(url + "/admin")
    page.locator("#email").fill(email)
    page.locator("#password").fill(password)
    page.locator("#loginForm button").click()
    if password == PW:
        expect(page.locator("#app")).to_be_visible()
        expect(page.locator("#tabs button").first).to_be_visible()


def tabs(page):
    return page.locator("#tabs button").all_inner_texts()


def test_wrong_password_shows_error(page, staffed, errors):
    sign_in(page, staffed.url, "admin@x.io", "nope")
    expect(page.locator("#loginErr")).to_contain_text("incorrect")
    expect(page.locator("#app")).to_be_hidden()


def test_viewer_is_read_only(page, staffed, errors):
    sign_in(page, staffed.url, "viewer@x.io")
    expect(page.locator("#role")).to_have_text("Viewer")
    assert tabs(page) == ["Overview", "Activity", "Guardrails", "Devices", "Audit log"]   # no Staff tab
    page.locator("#tabs button", has_text="Guardrails").click()
    expect(page.locator("#guardRO")).to_be_visible()
    expect(page.locator("#saveSettings")).to_be_disabled()
    assert errors == []


def test_admin_changes_guardrails_and_chat_obeys(page, staffed, errors):
    sign_in(page, staffed.url, "admin@x.io")
    assert "Staff" in tabs(page)
    page.locator("#tabs button", has_text="Guardrails").click()
    expect(page.locator("#settingsForm")).to_have_attribute("data-loaded", "1")
    page.locator("#s_maint").fill("Back in five minutes.")
    page.locator("#saveSettings").click()
    expect(page.locator("#settingsMsg")).to_contain_text("Saved")
    page.locator("#tabs button", has_text="Staff").click()
    expect(page.locator("#addStaffCard")).to_be_hidden()                       # admins can't add staff
    chat = page.context.new_page()
    enter(chat, staffed.url)
    send(chat, "hello")
    expect(chat.locator(".msg.bot").last).to_have_text("Back in five minutes.")
    assert errors == []


def test_super_admin_manages_staff_and_it_is_audited(page, staffed, errors):
    sign_in(page, staffed.url, "super@x.io")
    page.locator("#tabs button", has_text="Staff").click()
    page.locator("#n_name").fill("Robin")
    page.locator("#n_email").fill("robin@x.io")
    page.locator("#n_role").select_option("viewer")
    page.locator("#n_pw").fill("Temporary-pass-1")
    page.locator("#addStaff button").click()
    row = page.locator("#staff tr", has_text="robin@x.io")
    expect(row).to_be_visible()
    row.locator("select").select_option("admin")
    expect(page.locator(".toast").last).to_contain_text("Updated")
    page.locator("#staff tr", has_text="robin@x.io").locator("button", has_text="Deactivate").click()
    expect(page.locator("#staff tr", has_text="robin@x.io")).to_contain_text("Deactivated")
    expect(page.locator("#staff tr", has_text="(you)").locator("select")).to_have_count(0)   # can't change own role
    page.locator("#tabs button", has_text="Audit log").click()
    for action in ["staff.create", "staff.update", "login.ok"]:
        expect(page.locator("#audit")).to_contain_text(action)
    assert errors == []


def test_activity_shows_metadata_only_and_admin_can_block(page, staffed, errors):
    chat = page.context.new_page()
    enter(chat, staffed.url)
    send(chat, "my secret is pineapple")
    expect(chat.locator(".msg.bot")).to_have_count(2)
    sign_in(page, staffed.url, "admin@x.io")
    page.locator("#tabs button", has_text="Activity").click()
    expect(page.locator("#events tr")).to_have_count(1)
    assert "pineapple" not in page.content()
    page.locator("#events button", has_text="Block device").click()
    expect(page.locator(".toast")).to_contain_text("blocked")
    send(chat, "hello again")
    expect(chat.locator(".msg.bot").last).to_contain_text("isn't available")
    page.locator("#tabs button", has_text="Devices").click()
    page.locator("#blocked button", has_text="Unblock").click()
    expect(page.locator("#blocked")).to_contain_text("No blocked devices")
    assert errors == []


def test_off_topic_request_is_redirected_in_the_app(page, server, errors):
    enter(page, server.url)
    send(page, "write me a python function to sort a list")
    expect(page.locator(".msg.bot")).to_have_count(2)
    system = server.llm.calls[-1][0]["content"]
    assert "Do not do the task" in system and errors == []


def test_breathing_tool(page, server, errors):
    enter(page, server.url)
    send(page, "I'm panicking and my heart is racing")
    card = page.locator(".toolcard")
    expect(card).to_contain_text("Breathe with me")
    card.locator("button").click()
    expect(page.locator("#breathe")).to_be_visible()
    expect(page.locator("#breathLabel")).to_have_text(re.compile("Breathe in"), timeout=3000)
    expect(page.locator("#breathLabel")).to_have_text(re.compile("Hold"), timeout=6000)
    page.locator("#breathStop").click()
    expect(page.locator("#breathe")).to_be_hidden()
    assert errors == []
