"""Technocore Chat v14 final UI build.

This file is the presentation layer over the tested v13 room-switch core.
"""

from chat_v13_room_switch import (
    TechnocoreChat as V13TechnocoreChat,
    IDENTITY_PATH,
    derive_did,
    load_identity,
)


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


def main():
    identity = load_identity(IDENTITY_PATH)
    did = derive_did(identity)
    print(f"Identity: {did}")
    TechnocoreChat(identity, did).run()


if __name__ == "__main__":
    main()
