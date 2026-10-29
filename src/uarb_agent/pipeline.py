"""Handles one email end to end. Runs on a single worker thread, so jobs never overlap (1 GB VM)."""

import logging
import shutil
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

from . import guard
from .composer import (
    ReplyParts,
    compose_ack,
    compose_clarification,
    compose_failure,
    compose_not_allowed,
    compose_rate_limited,
    compose_result,
)
from .config import Settings
from .intent import IntentError, IntentParser
from .mailbox import Mailbox, body_text
from .models import DocType, FetchResult
from .packager import Delivery, build_zip, choose_delivery, zip_name
from .scraper import MatterNotFound, RowOutOfReach, ScrapeError, UarbScraper
from .state import State
from .storage import Storage

log = logging.getLogger(__name__)
current_job: ContextVar[str] = ContextVar("current_job", default="-")


class Pipeline:
    def __init__(self, settings: Settings, mailbox: Mailbox, state: State, intent: IntentParser,
                 scraper: UarbScraper, storage: Storage):
        self.s = settings
        self.mailbox = mailbox
        self.state = state
        self.intent = intent
        self.scraper = scraper
        self.storage = storage

    def handle(self, message_id: str) -> None:
        if not self.state.claim(message_id):
            return
        job_id = uuid.uuid4().hex[:8]
        current_job.set(job_id)
        work = self.s.data_dir / "jobs" / job_id
        try:
            status, detail = self._process(message_id, job_id, work)
            self.state.finish(message_id, status, detail)
            log.info("job finished", extra={"status": status, "detail": detail})
        except Exception:
            # Last line of defence for a long-running agent: log the full traceback, tell the sender,
            # and keep serving other emails. The message is marked failed, never silently dropped.
            log.exception("job crashed")
            self.state.finish(message_id, "failed", "crash")
            self.mailbox.reply(message_id, compose_failure(job_id))
        finally:
            shutil.rmtree(work, ignore_errors=True)
            current_job.set("-")

    def _process(self, message_id: str, job_id: str, work: Path) -> tuple[str, str]:
        msg = self.mailbox.get(message_id)
        if "received" not in (msg.labels or []):
            return "ignored", "not an inbound message"
        sender = guard.sender_address(msg.from_)
        verdict, why = guard.check(
            sender, self.s.agentmail_inbox, self.mailbox.raw_headers(message_id), self.state,
            self.s.allowed, self.s.per_sender_per_hour, self.s.global_per_day,
        )
        log.info("received", extra={"sender": sender, "subject": msg.subject, "verdict": verdict.value})
        if verdict is guard.Verdict.IGNORE:
            return "ignored", why
        if verdict is guard.Verdict.NOT_ALLOWED:
            self.mailbox.reply(message_id, compose_not_allowed(job_id))
            return "done", "sender not allowed"
        if verdict is guard.Verdict.RATE_LIMITED:
            self.mailbox.reply(message_id, compose_rate_limited(job_id))
            return "done", "rate limited"
        self.state.record_served(sender)

        try:
            parsed = self.intent.parse(body_text(msg), self.mailbox.history(msg))
        except IntentError as exc:
            log.error("intent failed", extra={"error": str(exc)})
            self.mailbox.reply(message_id, compose_failure(job_id))
            return "done", "intent failed"
        log.info("intent", extra={"parsed": parsed.model_dump(mode="json")})
        if not parsed.requests:
            self.mailbox.reply(message_id, compose_clarification(parsed.clarification_needed, job_id))
            return "done", "asked for clarification"

        self.mailbox.reply(message_id, compose_ack(parsed.requests, job_id))
        results: list[FetchResult] = []
        errors: list[str] = []
        for i, req in enumerate(parsed.requests):
            try:
                results.append(self.scraper.fetch(req, work / f"req{i}"))
            except MatterNotFound:
                errors.append(f"I couldn't find matter {req.matter} on the UARB site. Please check the number.")
            except RowOutOfReach as exc:
                errors.append(
                    f"I can only reach the first {exc.args[0]} {req.doc_type.value} for {req.matter} as the site "
                    f"lists them, so I couldn't start from number {req.start}."
                )
            except (ScrapeError, PlaywrightError) as exc:
                log.error("scrape failed", extra={"matter": req.matter, "type": req.doc_type.value, "error": str(exc)})
                errors.append(
                    f"I couldn't fetch {req.doc_type.value} for {req.matter} because the UARB site didn't respond "
                    "as expected. Please try again in a few minutes."
                )

        parts = ReplyParts(results=results, errors=errors, notes=parsed.notes, job_id=job_id)
        zip_path = None
        if any(r.files for r in results):
            zip_path = work / zip_name(results, datetime.now())
            parts.zip_size = build_zip(results, zip_path)
            has_recordings = any(r.request.doc_type is DocType.RECORDINGS and r.files for r in results)
            parts.link_days = self.s.recordings_link_days if has_recordings else self.s.link_days
            prefix = "recordings" if has_recordings else "zips"
            parts.link = self.storage.upload(zip_path, f"{prefix}/{job_id}/{zip_path.name}", parts.link_days)
            parts.delivery = choose_delivery(parts.zip_size, self.s.inline_max_bytes, self.s.attach_max_bytes)
            log.info("zip ready", extra={"bytes": parts.zip_size, "delivery": parts.delivery.value})

        reply = compose_result(parts)
        if parts.delivery is Delivery.INLINE:
            self.mailbox.reply(message_id, reply, zip_path=zip_path)
        elif parts.delivery is Delivery.URL_ATTACHMENT:
            self.mailbox.reply(message_id, reply, zip_path=zip_path, zip_url=parts.link)
        else:
            self.mailbox.reply(message_id, reply)
        return "done", f"{sum(len(r.files) for r in results)} files, {len(errors)} errors"
