from chat_v13_room_switch import TechnocoreChat as BaseTechnocoreChat
from chat_v13_room_switch import load_identity, derive_did, IDENTITY_PATH
from textual.containers import Container, Horizontal
from textual.widgets import Footer, Header, Input, Label, RichLog, Static


class TechnocoreChat(BaseTechnocoreChat):
    CSS = """
    Screen { background: $background; }
    #room_header { height: 4; padding: 0 2; border-bottom: solid $panel; }
    #room_name { width: 1fr; content-align: left middle; text-style: bold; }
    #connection { width: auto; min-width: 18; content-align: right middle; }
    #identity { height: 2; padding: 0 2; color: $text-muted; content-align: left middle; }
    #messages { height: 1fr; border: round $panel; padding: 1 2; margin: 0 1; scrollbar-size: 1 1; scrollbar-gutter: stable; }
    #composer { height: 4; padding: 0 1; border-top: solid $panel; }
    #prompt { width: 3; content-align: center middle; text-style: bold; }
    #message_input { width: 1fr; border: round $panel; }
    #hint { height: 1; padding: 0 2; color: $text-muted; }
    """

    def compose(self):
        yield Header()
        with Horizontal(id="room_header"):
            yield Label(f"# {self.room}", id="room_name")
            yield Label("● Connecting...", id="connection")
        yield Static(f"Identity: {self.did}", id="identity")
        yield RichLog(id="messages", wrap=True, markup=False, auto_scroll=True, max_lines=300)
        with Container(id="composer"):
            with Horizontal():
                yield Label(">", id="prompt")
                yield Input(placeholder="Type a message...", id="message_input")
        yield Static("/help   /tutorial   /join <room>   /from   /seen   /full   /quit", id="hint")
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            self.handle_command(text)
        else:
            self.send_message(text)


def main():
    identity = load_identity(IDENTITY_PATH)
    did = derive_did(identity)
    print(f"Identity: {did}")
    TechnocoreChat(identity, did).run()


if __name__ == "__main__":
    main()
