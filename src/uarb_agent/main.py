"""Entrypoint: `python -m uarb_agent` (or the `uarb-agent` script). Listens for email until stopped."""

import json
import logging
import queue
import sys
import threading
import time

from .config import Settings
from .intent import IntentParser
from .mailbox import Mailbox
from .pipeline import Pipeline, current_job
from .scraper import UarbScraper
from .state import State
from .storage import Storage

STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line, including `extra=` fields and the current job id."""

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "job": current_job.get(),
            "msg": record.getMessage(),
        }
        data.update({k: v for k, v in vars(record).items() if k not in STANDARD_ATTRS})
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str, ensure_ascii=False)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    for noisy in ("httpx", "httpx2", "httpcore", "botocore", "boto3", "s3transfer", "websockets", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    setup_logging()
    log = logging.getLogger("uarb_agent")
    settings = Settings()
    mailbox = Mailbox(settings.agentmail_api_key, settings.agentmail_inbox)
    state = State(settings.data_dir / "state.db")
    if state.is_empty():
        state.baseline(mailbox.recent_received())
    pipeline = Pipeline(
        settings,
        mailbox,
        state,
        IntentParser(settings.deepseek_api_key, settings.deepseek_model, settings.deepseek_base_url,
                     settings.max_requests_per_email),
        UarbScraper(settings.recordings_budget_bytes),
        Storage(settings),
    )
    jobs: queue.Queue[str] = queue.Queue()
    stop = threading.Event()

    def worker() -> None:
        while not stop.is_set():
            try:
                message_id = jobs.get(timeout=1)
            except queue.Empty:
                continue
            pipeline.handle(message_id)

    threading.Thread(target=worker, name="worker", daemon=True).start()
    log.info("agent started", extra={"inbox": settings.agentmail_inbox, "model": settings.deepseek_model})
    try:
        mailbox.listen(jobs.put, stop)
    except KeyboardInterrupt:
        stop.set()
        log.info("agent stopped")


if __name__ == "__main__":
    main()
