"""AgentMail: live receive over a websocket (with reconnect), catch-up on startup, threaded replies."""

import base64
import email
import logging
import threading
from email import policy
from email.message import Message as EmailMessage
from pathlib import Path

import httpx
import websockets
from agentmail import AgentMail, Message, MessageReceivedEvent, Subscribe, Subscribed
from agentmail.core.api_error import ApiError

from .composer import Reply

log = logging.getLogger(__name__)

CATCH_UP_LIMIT = 50


class Mailbox:
    def __init__(self, api_key: str, inbox: str):
        self.client = AgentMail(api_key=api_key)
        self.inbox = inbox

    def listen(self, on_message, stop: threading.Event) -> None:
        """Call on_message(message_id) for every new email. Reconnects with backoff until stop is set."""
        backoff = 1
        while not stop.is_set():
            try:
                with self.client.websockets.connect() as socket:
                    socket.send_subscribe(Subscribe(inbox_ids=[self.inbox], event_types=["message.received"]))
                    for event in socket:
                        if isinstance(event, Subscribed):
                            log.info("websocket subscribed", extra={"inbox": self.inbox})
                            backoff = 1
                            # Anything that arrived while we were disconnected.
                            for message_id in self.recent_received():
                                on_message(message_id)
                        elif isinstance(event, MessageReceivedEvent):
                            on_message(event.message.message_id)
                        if stop.is_set():
                            return
            except (OSError, websockets.exceptions.WebSocketException, ApiError, httpx.HTTPError) as exc:
                log.warning("websocket disconnected", extra={"error": repr(exc)[:300], "retry_in_s": backoff})
            stop.wait(backoff)
            backoff = min(backoff * 2, 60)

    def recent_received(self) -> list[str]:
        """IDs of recent inbound messages, oldest first (the worker skips ones already handled)."""
        resp = self.client.inboxes.messages.list(self.inbox, limit=CATCH_UP_LIMIT, labels=["received"])
        return [m.message_id for m in reversed(resp.messages)]

    def get(self, message_id: str) -> Message:
        return self.client.inboxes.messages.get(self.inbox, message_id)

    def raw_headers(self, message_id: str) -> EmailMessage:
        """The API's message object has no headers, so read them from the raw .eml."""
        raw = self.client.inboxes.messages.get_raw(self.inbox, message_id)
        with httpx.stream("GET", raw.download_url, timeout=30) as resp:
            resp.raise_for_status()
            head = b""
            for chunk in resp.iter_bytes():
                head += chunk
                if b"\r\n\r\n" in head or b"\n\n" in head or len(head) > 256_000:
                    break
        return email.message_from_bytes(head, policy=policy.default)

    def history(self, message: Message) -> list[tuple[str, str]]:
        """Earlier messages in the thread as (role, text), oldest first, for follow-up questions."""
        thread = self.client.inboxes.threads.get(self.inbox, message.thread_id)
        out = []
        for m in sorted(thread.messages or [], key=lambda m: m.timestamp):
            if m.message_id == message.message_id:
                continue
            role = "assistant" if "sent" in (m.labels or []) else "user"
            text = (m.extracted_text or m.text or "").strip()
            if text:
                out.append((role, text))
        return out

    def reply(self, message_id: str, reply: Reply, zip_path: Path | None = None, zip_url: str | None = None) -> None:
        """Reply in-thread. zip_path attaches the file inline; zip_url makes AgentMail fetch it (bigger files)."""
        attachments = []
        if zip_path is not None and zip_url is None:
            content = base64.b64encode(zip_path.read_bytes()).decode()
            attachments.append({"filename": zip_path.name, "content_type": "application/zip", "content": content})
        elif zip_path is not None:
            attachments.append({"filename": zip_path.name, "content_type": "application/zip", "url": zip_url})
        self.client.inboxes.messages.reply(
            self.inbox, message_id, text=reply.text, html=reply.html, attachments=attachments or None
        )
        log.info("replied", extra={"message_id": message_id, "attachments": len(attachments)})


def body_text(message: Message) -> str:
    """The new text of an email without quoted history; falls back to the full text."""
    return (message.extracted_text or message.text or message.preview or "").strip()
