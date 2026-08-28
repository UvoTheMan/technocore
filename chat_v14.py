"""Technocore Chat v14 final UI build.

Presentation layer over the tested v13 room-switch core.
All networking, signing, polling, room switching, queueing,
and security behavior remain inherited from v13.
Command handling is defined here explicitly so it cannot be
lost to a stale or incomplete import of the v13 module.
"""

from chat_v13_room_switch import (
    TechnocoreChat as V13TechnocoreChat,
    IDENTITY_PATH,
    derive_did,
    load_identity,
    short_did,
)
from textual.widgets import Input


class TechnocoreChat(V13TechnocoreChat):
    TITLE = "Technocore Chat"
    SUB_TITLE = "Public DID-based rooms"

    CSS = """
    Screen { background: $background; }
    #room_header { height: 4; padding: 0 2; border-bottom: solid $panel; }
    #room_name { width: 1fr; content-align: left middle; text-style: bold; }
    #connection { width: auto; min-width: 20; content-align: right middle; }
    #identity { height: 2; padding: 0 2; color: $text-muted; content-align: left middle; }
    #messages { height: 1fr; border: round $panel; padding: 1 2; margin: 0 1; scrollbar-size: 1 1; scrollbar-gutter: stable; }
    #composer { height: 4; padding: 0 1; border-top: solid $panel; }
    #prompt { width: 3; content-align: center middle; text-style: bold; }
    #message_input { width: 1fr; border: round $panel; }
    #hint { height: 1; padding: 0 2; color: $text-muted; }
    """

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            self.handle_command(text)
        else:
            self.send_message(text)

    def handle_command(self, command: str) -> None:
        parts = command.split(maxsplit=1)
        name = parts[0].lower()
        if name == "/quit":
            self.exit_chat()
            return
        if name == "/join":
            if len(parts) != 2:
                self.write_message("Usage: /join <room>")
                return
            self.switch_room(parts[1])
            return
        if name == "/help":
            self.write_message("Commands: /help /tutorial /join <room> /from /seen /full /quit")
            return
        if name == "/tutorial":
            self.write_message("Type a message and press Enter to send it.")
            self.write_message("Use /join <room> to switch rooms.")
            self.write_message("Use /from to see your DID.")
            self.write_message("Use /seen to see identities observed in this session.")
            self.write_message("Use /full to display your complete DID.")
            self.write_message("Use /quit to exit.")
            return
        if name == "/from":
            self.write_message(f"You are {short_did(self.did, self.seen_dids)}")
            return
        if name == "/full":
            self.write_message(self.did)
            return
        if name == "/seen":
            self.write_message(f"Seen identities: {len(self.seen_dids)}")
            for did in self.seen_dids:
                self.write_message(f"  {short_did(did, self.seen_dids)}")
            return
        self.write_message(f"Unknown command: {name}")


def main():
    identity = load_identity(IDENTITY_PATH)
    did = derive_did(identity)
    print(f"Identity: {did}")
    TechnocoreChat(identity, did).run()


if __name__ == "__main__":
    main()
