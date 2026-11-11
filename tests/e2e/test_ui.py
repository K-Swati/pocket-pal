import json
import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e
REPLY = "I'm right here with you, and I'm not going anywhere. What's been on your mind tonight?"


def enter(page: Page, url: str, intro: bool = False):
    page.goto(url)
    page.locator("#agree").check()
    page.locator("#start").click()
    expect(page.locator("#welcome")).to_be_hidden()
    if not intro:
        page.locator("#introSkip").click()
        expect(page.locator("#intro")).to_be_hidden()


def send(page: Page, text: str):
    page.locator("#text").fill(text)
    page.locator("#send").click()


def wait_for_audio(page: Page, timeout=8000):
    """Passes once the shared player is genuinely playing a reply (not muted, time advancing)."""
    page.wait_for_function(
        "() => !player.paused && !player.muted && player.currentTime > 0.1 && player.src.startsWith('blob:')", timeout=timeout)


def test_welcome_gate_requires_consent(page, server, errors):
    page.goto(server.url)
    expect(page.locator("#welcome")).to_be_visible()
    expect(page.locator("#start")).to_be_disabled()
    page.locator("#agree").check()
    page.locator("#start").click()
    expect(page.locator("#welcome")).to_be_hidden()
    page.reload()
    expect(page.locator("#welcome")).to_be_hidden()  # remembered
    assert errors == []


def test_typed_message_gets_reply_spoken_with_lip_sync(page, server, errors):
    enter(page, server.url)
    send(page, "I feel low today")
    expect(page.locator(".msg.bot").last).to_have_text(REPLY)
    wait_for_audio(page)
    page.wait_for_function("() => mouthLevel > 0.3", timeout=3000)
    expect(page.locator("#buddy")).to_have_attribute("data-state", "idle", timeout=10000)
    assert len(server.llm.calls) == 1 and errors == []


def test_can_keep_talking_while_friend_speaks(page, server, errors):
    enter(page, server.url)
    send(page, "first")
    wait_for_audio(page)
    send(page, "second")  # must not be blocked by playback
    expect(page.locator(".msg.me")).to_have_count(2)
    expect(page.locator(".msg.bot")).to_have_count(3)  # greeting + two replies
    assert errors == []


def test_crisis_shows_helplines_and_skips_model(page, server, errors):
    enter(page, server.url)
    send(page, "I want to kill myself")
    expect(page.locator(".banner")).to_contain_text("14416")  # en-IN locale -> Tele-MANAS
    expect(page.locator(".msg.bot").last).to_contain_text("glad you told me")
    expect(page.locator("#buddy")).to_have_attribute("data-state", "care", timeout=10000)
    assert server.llm.calls == [] and errors == []


def test_voice_input_auto_detects_end_of_speech(page, server, errors):
    enter(page, server.url)
    page.wait_for_timeout(2500)  # let the spoken greeting finish
    page.locator("#talk").click()
    expect(page.locator("#buddy")).to_have_attribute("data-state", "listening")
    # no second tap: the pause after speaking sends it
    expect(page.locator(".msg.me").last).to_have_text("I feel a bit lonely tonight", timeout=8000)
    expect(page.locator(".msg.bot")).to_have_count(2)
    assert server.stt.calls == 1 and errors == []


def test_hands_free_listens_again_after_reply(page, server, errors):
    enter(page, server.url)
    page.wait_for_timeout(2500)
    page.locator("#talk").click()
    expect(page.locator(".msg.me")).to_have_count(2, timeout=20000)  # second turn happened without any tap
    assert server.stt.calls >= 2 and errors == []


def test_hands_free_off_does_not_relisten(page, server, errors):
    enter(page, server.url)
    page.locator("#menuBtn").click()
    page.locator("#toggleHands").click()
    expect(page.locator("#toggleHands")).to_contain_text("off")
    page.locator("#closeMenu").click()
    page.wait_for_timeout(2500)
    page.locator("#talk").click()
    expect(page.locator(".msg.bot")).to_have_count(2, timeout=8000)
    expect(page.locator("#buddy")).to_have_attribute("data-state", "idle", timeout=8000)
    page.wait_for_timeout(1500)
    expect(page.locator("#buddy")).not_to_have_attribute("data-state", "listening")
    assert server.stt.calls == 1 and errors == []


def test_silence_stops_listening_quietly(page, server, errors):
    # a microphone that hears nothing at all
    page.add_init_script("""navigator.mediaDevices.getUserMedia = async () => {
        const c = new AudioContext(); return c.createMediaStreamDestination().stream; };""")
    enter(page, server.url)
    page.wait_for_timeout(2500)
    page.locator("#talk").click()
    expect(page.locator("#hint")).to_contain_text("didn't hear anything", timeout=12000)
    expect(page.locator("#buddy")).to_have_attribute("data-state", "idle")
    assert server.stt.calls == 0 and errors == []


def test_tap_to_send_early_still_works(page, server, errors):
    enter(page, server.url)
    page.wait_for_timeout(2500)
    page.locator("#talk").click()
    page.wait_for_timeout(900)
    page.locator("#talk").click(force=True)  # pulsing button is never "stable"
    expect(page.locator(".msg.me").last).to_have_text("I feel a bit lonely tonight")
    assert server.stt.calls == 1 and errors == []


def test_double_tap_starts_only_one_recording(page, server, errors):
    enter(page, server.url)
    page.wait_for_timeout(2500)
    page.locator("#talk").click()
    page.locator("#talk").click(force=True)
    expect(page.locator(".msg.me")).to_have_count(1, timeout=10000)
    page.wait_for_timeout(500)
    assert server.stt.calls <= 1 and errors == []


def test_male_voice_choice_reaches_server(page, server, errors):
    enter(page, server.url)
    page.locator("#menuBtn").click()
    page.locator('#voiceSeg button[data-v="male"]').click()
    expect(page.locator('#voiceSeg button[data-v="male"]')).to_have_class(re.compile("sel"))
    page.locator("#closeMenu").click()
    send(page, "hello")
    expect(page.locator(".msg.bot")).to_have_count(2)
    page.wait_for_function("() => !player.paused || buddy.dataset.state === 'idle'")
    assert "male" in server.tts.voices and errors == []


def test_themes_switch_and_persist(page, server, errors):
    enter(page, server.url)
    for theme in ["sunrise", "ocean", "meadow", "candy", "night", "lavender", "night"]:
        page.locator("#menuBtn").click()
        page.locator(f'#swatches button[data-t="{theme}"]').click()
        expect(page.locator("html")).to_have_attribute("data-theme", theme)
        page.locator("#closeMenu").click()
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "night")
    assert page.locator("#deco i").count() > 20  # stars
    assert errors == []


def test_character_reacts_to_tap(page, server, errors):
    enter(page, server.url)
    page.wait_for_timeout(2200)  # let the welcome wave finish
    page.locator("#buddy").click()
    expect(page.locator("#buddy")).to_have_attribute("data-state", "happy")
    expect(page.locator("#buddy .heart").first).to_be_attached()
    assert errors == []


def test_history_persists_and_forget_erases(page, server, errors):
    enter(page, server.url)
    send(page, "my cat is called Miso")
    expect(page.locator(".msg.bot")).to_have_count(2)
    page.reload()
    expect(page.locator(".msg.me")).to_have_text(["my cat is called Miso"])
    page.locator("#menuBtn").click()
    page.locator("#forget").click()
    expect(page.locator("#forget")).to_contain_text("Tap again")
    page.locator("#forget").click()
    expect(page.locator("#welcome")).to_be_visible()
    assert page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('friend.') && k !== 'friend.theme')") == ["friend.agreed"] or \
        page.evaluate("localStorage.getItem('friend.messages')") is None
    assert errors == []


def test_stalled_browser_voice_never_freezes_app(page, server_no_tts, errors):
    page.add_init_script("speechSynthesis.speak = () => {};")  # the Chrome bug: speech that never ends
    enter(page, server_no_tts.url)
    send(page, "hello")
    expect(page.locator(".msg.bot")).to_have_count(2)
    send(page, "are you there")
    expect(page.locator(".msg.bot")).to_have_count(3)
    expect(page.locator("#buddy")).to_have_attribute("data-state", "idle", timeout=15000)
    assert errors == []


def test_help_sheet_lists_regional_lines(page, server, errors):
    enter(page, server.url)
    page.locator("#help").click()
    expect(page.locator("#lines")).to_contain_text("Tele-MANAS")
    expect(page.locator("#lines")).to_contain_text("emergency")
    page.locator("#closeHelp").click()
    expect(page.locator("#helpSheet")).to_be_hidden()
    assert errors == []


def test_text_appears_in_sync_with_voice_not_before(page, server, errors):
    enter(page, server.url)
    page.wait_for_timeout(2500)
    send(page, "I feel low")
    bot = page.locator(".msg.bot").last
    expect(bot).to_have_class(re.compile("typing"))      # dots while the voice is prepared, no text yet
    assert REPLY not in bot.inner_text()
    wait_for_audio(page)                                   # the moment Pocket Pal starts talking...
    first = bot.inner_text()
    assert 0 < len(first) < len(REPLY)                     # ...only the first words are showing
    expect(bot).to_have_text(REPLY)                        # and the rest follows the voice
    assert server.tts.texts[-2:] == ["I'm right here with you, and I'm not going anywhere.", "What's been on your mind tonight?"]
    assert errors == []


def test_interrupting_shows_full_reply(page, server, errors):
    enter(page, server.url)
    page.wait_for_timeout(2500)
    send(page, "hi")
    wait_for_audio(page)
    send(page, "sorry, one more thing")   # interrupts Pocket Pal mid-sentence
    expect(page.locator(".msg.bot").nth(1)).to_have_text(REPLY)
    assert errors == []


def test_character_picker_switches_persists_and_names_the_ai(page, server, errors):
    enter(page, server.url)
    expect(page.locator("#chars button")).to_have_count(5)
    for key, name in [("miso", "Miso"), ("bao", "Bao"), ("clover", "Clover"), ("nimbus", "Nimbus"), ("mochi", "Mochi")]:
        page.locator("#menuBtn").click()
        page.locator(f'#chars button[data-c="{key}"]').click()
        expect(page.locator(f'#art svg[data-char="{key}"]')).to_be_attached()
        expect(page.locator("#title")).to_have_text(name)
        for part in ["#smile", "#mouthShape", "#face", "#bodyGroup"]:   # every character can talk and emote
            expect(page.locator(part)).to_have_count(1)
        page.locator("#closeMenu").click()
    page.locator("#menuBtn").click()
    page.locator('#chars button[data-c="clover"]').click()
    page.locator("#closeMenu").click()
    page.reload()
    expect(page.locator("#title")).to_have_text("Clover")
    page.wait_for_timeout(2500)
    send(page, "who are you?")
    expect(page.locator(".msg.bot").last).to_have_text(REPLY)
    assert "Your name is Clover" in server.llm.calls[-1][0]["content"]
    assert errors == []


def test_mouth_moves_for_every_character(page, server, errors):
    enter(page, server.url)
    page.wait_for_timeout(2500)
    for key in ["miso", "bao", "clover", "nimbus"]:
        page.evaluate(f"applyCharacter('{key}')")
        send(page, "hi")
        wait_for_audio(page)
        page.wait_for_function("() => mouthLevel > 0.3 && document.getElementById('mouthO').style.display === ''", timeout=4000)
    assert errors == []


def test_character_colours_never_change_with_theme(page, server, errors):
    enter(page, server.url)
    colour = "() => getComputedStyle(document.querySelector('#art svg')).getPropertyValue('--char2').trim()"
    for key, expected in [("mochi", "#f59ab5"), ("miso", "#f39a4c"), ("bao", "#b57d52"), ("clover", "#ab97ee"), ("nimbus", "#8ccbf2")]:
        page.evaluate(f"applyCharacter('{key}')")
        seen = set()
        for theme in ["lavender", "sunrise", "ocean", "meadow", "candy", "night"]:
            page.evaluate(f"applyTheme('{theme}')")
            seen.add(page.evaluate(colour))
        assert seen == {expected}, (key, seen)
    assert errors == []


def test_each_theme_has_its_own_scene(page, server, errors):
    enter(page, server.url)
    signature = {"lavender": ".aurora", "sunrise": ".sun", "ocean": ".wave", "meadow": ".leaf", "candy": ".sprinkle", "night": ".moon"}
    for theme, marker in signature.items():
        page.evaluate(f"applyTheme('{theme}')")
        expect(page.locator("#deco")).to_have_attribute("data-scene", theme)
        expect(page.locator(f"#deco {marker}").first).to_be_attached()
        others = [m for t, m in signature.items() if t != theme]
        assert page.locator("#deco " + ", #deco ".join(others)).count() == 0, theme
    assert errors == []


def test_first_time_intro_walks_in_talks_then_goes_to_chat(page, server, errors):
    enter(page, server.url, intro=True)
    expect(page.locator("#intro")).to_be_visible()
    expect(page.locator("#walker #buddy")).to_be_attached()            # the real character is centre stage
    expect(page.locator("#introFx .wand")).to_be_attached()               # the magic wand swoops in
    expect(page.locator("#introFx .ring")).to_be_attached(timeout=4000)   # ...and poof
    expect(page.locator("#introBubble")).to_contain_text("I'm Mochi", timeout=10000)
    wait_for_audio(page)                                                 # it speaks its lines
    expect(page.locator("#introBubble")).to_contain_text("not a therapist", timeout=30000)
    expect(page.locator("#intro")).to_be_hidden(timeout=40000)
    expect(page.locator(".stage #buddy")).to_be_attached()              # back in its spot above the chat
    expect(page.locator(".buddy-spot")).to_have_count(0)
    assert page.evaluate("localStorage.getItem('friend.introSeen')") == "true"
    page.reload()
    expect(page.locator("#intro")).to_be_hidden()                       # only the first time
    assert errors == []


def test_intro_can_be_skipped_and_replayed(page, server, errors):
    enter(page, server.url, intro=True)
    expect(page.locator("#intro")).to_be_visible()
    page.locator("#introSkip").click()
    expect(page.locator("#intro")).to_be_hidden(timeout=3000)
    expect(page.locator(".stage #buddy")).to_be_attached()
    page.locator("#menuBtn").click()
    page.locator("#replayIntro").click()
    expect(page.locator("#intro")).to_be_visible()
    page.locator("#introSkip").click()
    expect(page.locator("#intro")).to_be_hidden(timeout=3000)
    send(page, "hello")                                                  # chat still works afterwards
    expect(page.locator(".msg.bot").last).to_have_text(REPLY)
    assert errors == []
