from chat_v13_room_switch import TechnocoreChat, load_identity, derive_did, IDENTITY_PATH, short_did


TechnocoreChat.CSS = """
Screen {
    background: $background;
}

#room_header {
    height: 3;
    padding: 0 1;
    border-bottom: solid $panel;
}

#room_name {
    width: 1fr;
    content-align: left middle;
    text-style: bold;
}

#connection {
    width: auto;
    content-align: right middle;
}

#identity {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

#messages {
    height: 1fr;
    border: round $panel;
    padding: 1 2;
    margin: 0 1;
    scrollbar-size: 1 1;
}

#composer {
    height: 3;
    border-top: solid $panel;
    padding: 0 1;
}

#prompt {
    width: 3;
    content-align: center middle;
    text-style: bold;
}

#message_input {
    width: 1fr;
    border: round $panel;
}

#hint {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}
"""


def polished_format_message(self, timestamp: str, sender: str, text: str) -> str:
    display_sender = "You" if sender == self.did else short_did(sender, self.seen_dids)
    clean_timestamp = timestamp
    if timestamp.endswith("Z"):
        clean_timestamp = timestamp[:-1]
    if "T" in clean_timestamp:
        clean_timestamp = clean_timestamp.split("T", 1)[1]
    if "." in clean_timestamp:
        clean_timestamp = clean_timestamp.split(".", 1)[0]
    return f"[{clean_timestamp}] {display_sender}: {text}"


TechnocoreChat.format_message = polished_format_message


def main():
    identity = load_identity(IDENTITY_PATH)
    did = derive_did(identity)
    print(f"Identity: {did}")
    TechnocoreChat(identity, did).run()


if __name__ == "__main__":
    main()
