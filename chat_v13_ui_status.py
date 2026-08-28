from chat_v13_ui import TechnocoreChat, load_identity, derive_did, IDENTITY_PATH


def set_status(self, state: str) -> None:
    labels = {
        "connected": "● Connected",
        "connecting": "● Connecting...",
        "reconnecting": "● Reconnecting...",
        "sending": "● Sending...",
        "offline": "● Offline",
        "rate_limited": "● Rate limited",
        "server_error": "● Server error",
    }
    self.update_connection(labels.get(state, "● Unknown"))


TechnocoreChat.set_status = set_status
