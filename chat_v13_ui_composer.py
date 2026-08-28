from chat_v13_ui import TechnocoreChat, load_identity, derive_did, IDENTITY_PATH
from textual.widgets import Input


def send_message_with_feedback(self, text: str) -> None:
    if getattr(self, "sending", False):
        return
    self.sending = True
    self.update_connection("● Sending...")
    self.write_message(f"You: {text}")
    threading.Thread(target=self._send_with_feedback_worker, args=(text,), daemon=True).start()


def _send_with_feedback_worker(self, text: str) -> None:
    try:
        room_at_send = self.room
        payload = send_signed_message(self.identity, self.did, room_at_send, text)
        if self.running:
            self.call_from_thread(self._send_feedback_done, payload, room_at_send)
    except Exception as exc:
        if self.running:
            self.call_from_thread(self._send_feedback_failed, str(exc))


def _send_feedback_done(self, payload, room_at_send: str) -> None:
    self.sending = False
    if room_at_send == self.room:
        self.update_connection("● Connected")
    else:
        self.update_connection("● Connected")


def _send_feedback_failed(self, error: str) -> None:
    self.sending = False
    self.update_connection("● Connected")
    self.write_message(f"Send failed: {error}")


# Keep this layer independent so the existing v13 networking implementation remains unchanged.
# The normal send path is deliberately left available for the next integration step.
