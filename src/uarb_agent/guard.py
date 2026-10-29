"""Decides whether an incoming email gets handled: loop protection, allowlist, rate limits."""

import re
from email.message import Message
from email.utils import parseaddr
from enum import Enum

from .state import State

AUTOMATED_SENDERS = re.compile(r"^(mailer-daemon|postmaster|no-?reply|do-?not-?reply|bounce[s]?)([+@]|$)", re.I)


class Verdict(str, Enum):
    OK = "ok"
    IGNORE = "ignore"  # never reply (would risk a mail loop)
    NOT_ALLOWED = "not_allowed"
    RATE_LIMITED = "rate_limited"


def sender_address(from_header: str) -> str:
    return parseaddr(from_header)[1].strip().lower()


def is_automated(sender: str, own_address: str, headers: Message) -> str | None:
    """Reason to ignore the message, or None. Replying to robots can start an endless email loop."""
    if sender == own_address.lower():
        return "from our own inbox"
    if AUTOMATED_SENDERS.match(sender):
        return f"automated sender {sender}"
    auto = (headers.get("Auto-Submitted") or "").strip().lower()
    if auto and auto != "no":
        return f"Auto-Submitted: {auto}"
    if (headers.get("Precedence") or "").strip().lower() in {"bulk", "junk", "list", "auto_reply"}:
        return f"Precedence: {headers.get('Precedence')}"
    for name in ("X-Autoreply", "X-Autorespond", "List-Id", "List-Unsubscribe"):
        if headers.get(name):
            return f"{name} header present"
    return None


def check(sender: str, own_address: str, headers: Message, state: State, allowed: set[str],
          per_sender_per_hour: int, global_per_day: int) -> tuple[Verdict, str]:
    reason = is_automated(sender, own_address, headers)
    if reason:
        return Verdict.IGNORE, reason
    if allowed and sender not in allowed:
        return Verdict.NOT_ALLOWED, sender
    if state.served_count(86400) >= global_per_day:
        # Out of daily email quota: replying would itself use the quota, so stay silent.
        return Verdict.IGNORE, "global daily limit reached"
    if state.served_count(3600, sender) >= per_sender_per_hour:
        return Verdict.RATE_LIMITED, sender
    return Verdict.OK, ""
