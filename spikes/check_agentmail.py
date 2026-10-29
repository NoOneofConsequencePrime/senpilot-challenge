"""Gates G6 + G7: AgentMail inbox, live websocket receive, in-thread reply with an inline ZIP and a
URL-backed ZIP (presigned OCI link from check_storage.py).

Usage:
  python spikes/check_agentmail.py create <username>   # creates the inbox if you didn't in the console
  python spikes/check_agentmail.py listen              # then send an email to the inbox from TEST_RECIPIENT
"""

import base64
import io
import sys
import time
import zipfile

from agentmail import AgentMail, MessageReceivedEvent, Subscribe, Subscribed

from gate_env import GateEnv, s3_client
from check_storage import KEY


def small_zip() -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "Feasibility check G6: inline attachment.\n")
    return base64.b64encode(buf.getvalue()).decode()


def create(client: AgentMail, username: str) -> None:
    inbox = client.inboxes.create(request={"username": username, "display_name": "UARB Agent"})
    print("created inbox:", inbox.inbox_id, "-> put this in AGENTMAIL_INBOX")


def listen(client: AgentMail, env: GateEnv) -> None:
    env.require("agentmail_inbox")
    attachments = [{"filename": "inline-test.zip", "content_type": "application/zip", "content": small_zip()}]
    if env.oci_namespace:
        url = s3_client(env).generate_presigned_url(
            "get_object", Params={"Bucket": env.oci_bucket, "Key": KEY}, ExpiresIn=3600
        )
        attachments.append({"filename": "url-test-10mb.zip", "content_type": "application/zip", "url": url})
    else:
        print("OCI not configured: skipping the URL attachment (G7)")

    with client.websockets.connect() as socket:
        socket.send_subscribe(Subscribe(inbox_ids=[env.agentmail_inbox], event_types=["message.received"]))
        print(f"Listening. Now send any email to {env.agentmail_inbox} (waiting up to 10 min)...")
        deadline = time.time() + 600
        for event in socket:
            if isinstance(event, Subscribed):
                print("subscribed:", event.inbox_ids)
            elif isinstance(event, MessageReceivedEvent):
                msg = event.message
                lag = time.time() - msg.timestamp.timestamp()
                print(f"received from {msg.from_!r} subject {msg.subject!r} ({lag:.1f}s after it was received)")
                print("headers present:", sorted((msg.headers or {}).keys())[:25])
                print("extracted_text:", (msg.extracted_text or msg.text or "")[:200])
                t0 = time.time()
                client.inboxes.messages.reply(
                    env.agentmail_inbox,
                    msg.message_id,
                    text="Feasibility check: this reply should be threaded and carry inline-test.zip"
                    + (" and url-test-10mb.zip." if len(attachments) > 1 else "."),
                    html="<p>Feasibility check: this reply should be <b>threaded</b> and carry the test ZIP(s).</p>",
                    attachments=attachments,
                )
                print(f"replied in {time.time() - t0:.1f}s. Check your inbox (and spam): threaded? attachments open?")
                return
            if time.time() > deadline:
                raise SystemExit("no email received within 10 minutes")


def main() -> None:
    env = GateEnv()
    env.require("agentmail_api_key")
    client = AgentMail(api_key=env.agentmail_api_key)
    if sys.argv[1:2] == ["create"]:
        create(client, sys.argv[2])
    else:
        listen(client, env)


if __name__ == "__main__":
    main()
