from email.message import Message

import pytest

from uarb_agent.guard import Verdict, check, is_automated, sender_address
from uarb_agent.state import State

OWN = "uarb-agent@agentmail.to"


def headers(**h) -> Message:
    m = Message()
    for k, v in h.items():
        m[k.replace("_", "-")] = v
    return m


@pytest.fixture
def state(tmp_path) -> State:
    return State(tmp_path / "state.db")


def test_sender_address():
    assert sender_address("Jane Doe <Jane@Example.com>") == "jane@example.com"


@pytest.mark.parametrize("sender,hdrs", [
    (OWN, {}),
    ("mailer-daemon@googlemail.com", {}),
    ("noreply@example.com", {}),
    ("jane@example.com", {"Auto_Submitted": "auto-replied"}),
    ("jane@example.com", {"Precedence": "bulk"}),
    ("jane@example.com", {"X_Autoreply": "yes"}),
    ("jane@example.com", {"List_Id": "<news.example.com>"}),
])
def test_automated_mail_is_ignored(sender, hdrs):
    assert is_automated(sender, OWN, headers(**hdrs))


def test_normal_mail_is_not_automated():
    assert is_automated("jane@example.com", OWN, headers(Auto_Submitted="no")) is None


def test_allowlist(state):
    verdict, _ = check("eve@example.com", OWN, headers(), state, {"jane@example.com"}, 5, 60)
    assert verdict is Verdict.NOT_ALLOWED


def test_per_sender_limit(state):
    for _ in range(2):
        state.record_served("jane@example.com")
    assert check("jane@example.com", OWN, headers(), state, set(), 2, 60)[0] is Verdict.RATE_LIMITED
    assert check("bob@example.com", OWN, headers(), state, set(), 2, 60)[0] is Verdict.OK


def test_global_limit_goes_silent(state):
    state.record_served("a@example.com")
    assert check("b@example.com", OWN, headers(), state, set(), 5, 1)[0] is Verdict.IGNORE


def test_claim_is_once_per_message(state):
    assert state.claim("m1")
    state.finish("m1", "done")
    assert not state.claim("m1")


def test_interrupted_message_is_retried_once(state):
    assert state.claim("m1")  # crashed before finish()
    assert state.claim("m1")  # retried after restart
    assert not state.claim("m1")  # but not forever


def test_baseline_marks_existing_mail_handled(state):
    assert state.is_empty()
    state.baseline(["old1", "old2"])
    assert not state.claim("old1")
    assert state.claim("new1")
