from pathlib import Path
from getpass import getpass
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import base64
import json
import threading
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Footer, Header, Input, Label, RichLog, Static


IDENTITY_PATH = Path("identity.pem")
BASE = "https://technocore.chat"
ROOM = "lobby"

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def base58btc_encode(data: bytes) -> str:
    number = int.from_bytes(data, "big")
    encoded = ""

    while number:
        number, remainder = divmod(number, 58)
        encoded = ALPHABET[remainder] + encoded

    leading_zeroes = len(data) - len(data.lstrip(b"\x00"))

    return "1" * leading_zeroes + (encoded or "")


def load_identity(
    path: Path,
    passphrase: str | None = None,
) -> Ed25519PrivateKey:
    if not path.exists():
        raise SystemExit(f"Identity file not found: {path}")

    data = path.read_bytes()

    password = None

    if b"ENCRYPTED" in data:
        raw = (
            passphrase
            if passphrase is not None
            else getpass("Passphrase for identity.pem: ")
        )
        password = raw.encode()

    try:
        key = serialization.load_pem_private_key(
            data,
            password=password,
        )
    except ValueError as exc:
        raise SystemExit(
            "Could not decrypt identity.pem. Check the passphrase or path."
        ) from exc

    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("identity.pem is not an Ed25519 key")

    return key


def derive_did(key: Ed25519PrivateKey) -> str:
    public_key = key.public_key()

    raw_public = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    multicodec_key = b"\xed\x01" + raw_public

    return "did:key:z" + base58btc_encode(multicodec_key)


def short_did(
    full: str,
    seen: list[str],
    min_chars: int = 8,
    max_chars: int = 16,
) -> str:
    key = full.removeprefix("did:key:")

    for length in range(min_chars, max_chars + 1, 2):
        suffix = key[-length:]

        matches = [
            did
            for did in set(seen)
            if did.removeprefix("did:key:")[-length:] == suffix
        ]

        if len(matches) <= 1:
            return "…" + suffix

    return full


def read_room(room: str, *, since=None, limit=50, wait=None):
    query = {
        "format": "json",
        "limit": str(limit),
    }

    if since is not None:
        query["since"] = str(since)

    if wait is not None and since is not None:
        query["wait"] = str(wait)

    url = f"{BASE}/r/{quote(room, safe='')}?" + urlencode(query)

    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "technocore-chat/1.1",
        },
    )

    with urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def sign_message(
    identity: Ed25519PrivateKey,
    room: str,
    nonce: int,
    text: str,
) -> str:
    payload = f"{room}|{nonce}|{text}".encode("utf-8")

    signature = identity.sign(payload)

    return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")


def send_signed_message(
    identity: Ed25519PrivateKey,
    did: str,
    room: str,
    text: str,
):
    text = text.replace("\r", " ").replace("\n", " ").strip()

    if not text:
        raise ValueError("Message cannot be empty.")

    if len(text) > 4096:
        raise ValueError("Message is too long. Maximum is 4096 characters.")

    nonce = time.time_ns() // 1_000_000

    signature = sign_message(
        identity,
        room,
        nonce,
        text,
    )

    url = (
        f"{BASE}/r/{quote(room, safe='')}/say-signed/"
        f"{quote(did, safe='')}/"
        f"{quote(signature, safe='')}/"
        f"{nonce}/"
        f"{quote(text, safe='')}"
    )

    req = Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "technocore-chat/1.1",
        },
    )

    with urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


class TechnocoreChat(App):
    TITLE = "Technocore Chat"
    SUB_TITLE = "Public DID-based rooms"

    CSS = """
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
        border: none;
        padding: 1;
    }

    #composer {
        height: 3;
        border-top: solid $panel;
        padding: 0 1;
    }

    #prompt {
        width: auto;
        content-align: center middle;
        padding-right: 1;
        color: $text-muted;
    }

    #message_input {
        width: 1fr;
    }

    #hint {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        identity: Ed25519PrivateKey,
        did: str,
    ):
        super().__init__()

        self.identity = identity
        self.did = did

        self.room = ROOM

        self.running = True
        self.connected = False

        self.last_seq = 0

        self.seen_dids: list[str] = [did]

        self.poll_thread: threading.Thread | None = None

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="room_header"):
            yield Label("# lobby", id="room_name")
            yield Label("● Connecting...", id="connection")

        yield Static(
            f"Identity: {short_did(self.did, self.seen_dids)}",
            id="identity",
        )

        yield RichLog(
            id="messages",
            wrap=True,
            markup=False,
        )

        with Container(id="composer"):
            with Horizontal():
                yield Label(">", id="prompt")

                yield Input(
                    placeholder="Type a message...",
                    id="message_input",
                )

        yield Static(
            "/help   /tutorial   /from   /seen   /full   /quit",
            id="hint",
        )

        yield Footer()

    def on_mount(self) -> None:
        messages = self.query_one("#messages", RichLog)

        messages.write("Welcome to Technocore Chat")
        messages.write("")
        messages.write(
            "Messages in this room are public and cryptographically signed."
        )
        messages.write("")
        messages.write(f"Your DID: {self.did}")
        messages.write("")
        messages.write("Connecting to #lobby...")

        self.query_one("#message_input", Input).focus()

        self.load_initial_messages()

    def load_initial_messages(self) -> None:
        try:
            payload = read_room(
                self.room,
                limit=50,
            )

            self.process_messages(
                payload,
                initial=True,
            )

            self.connected = True
            self.update_connection("● Connected")

            self.start_polling()

        except Exception as exc:
            self.connected = False
            self.update_connection("● Offline")

            self.write_message(
                f"Could not connect to lobby: {exc}"
            )

            self.start_polling()

    def start_polling(self) -> None:
        if self.poll_thread and self.poll_thread.is_alive():
            return

        self.poll_thread = threading.Thread(
            target=self.poll_loop,
            daemon=True,
        )

        self.poll_thread.start()

    def poll_loop(self) -> None:
        while self.running:
            try:
                payload = read_room(
                    self.room,
                    since=self.last_seq,
                    limit=50,
                    wait=10,
                )

                self.connected = True

                self.call_from_thread(
                    self.update_connection,
                    "● Connected",
                )

                self.call_from_thread(
                    self.process_messages,
                    payload,
                    False,
                )

            except Exception as exc:
                self.connected = False

                self.call_from_thread(
                    self.update_connection,
                    "● Reconnecting...",
                )

                time.sleep(2)

    def process_messages(
        self,
        payload,
        initial=False,
    ) -> None:
        room_messages = payload.get("messages", [])

        if not room_messages:
            if "last_seq" in payload:
                self.last_seq = max(
                    self.last_seq,
                    int(payload["last_seq"]),
                )

            return

        all_dids = [
            message.get("from", "")
            for message in room_messages
            if message.get("from")
        ]

        for did in all_dids:
            if did and did not in self.seen_dids:
                self.seen_dids.append(did)

        for message in room_messages:
            seq = int(message.get("seq", 0))

            if seq <= self.last_seq:
                continue

            sender = message.get("from", "unknown")
            text = message.get("text", "")
            timestamp = message.get("ts", "")

            display_sender = short_did(
                sender,
                self.seen_dids,
            )

            self.write_message(
                f"{timestamp} {display_sender}  {text}"
            )

            self.last_seq = max(
                self.last_seq,
                seq,
            )

        if initial:
            self.write_message("")
            self.write_message(
                f"Loaded {len(room_messages)} public messages."
            )

    def write_message(self, text: str) -> None:
        messages = self.query_one(
            "#messages",
            RichLog,
        )

        messages.write(text)

    def update_connection(self, text: str) -> None:
        connection = self.query_one(
            "#connection",
            Label,
        )

        connection.update(text)

    def on_input_submitted(
        self,
        event: Input.Submitted,
    ) -> None:
        text = event.value.strip()

        event.input.value = ""

        if not text:
            return

        if text.startswith("/"):
            self.handle_command(text)
            return

        self.send_message(text)

    def handle_command(self, command: str) -> None:
        parts = command.split(maxsplit=1)

        name = parts[0].lower()

        argument = (
            parts[1]
            if len(parts) > 1
            else ""
        )

        if name == "/quit":
            self.exit_chat()
            return

        if name == "/help":
            self.write_message(
                "Commands: /help /tutorial /from /seen /full /quit"
            )
            return

        if name == "/tutorial":
            self.write_message(
                "Type a message and press Enter to send it."
            )
            self.write_message(
                "Use /from to see your DID."
            )
            self.write_message(
                "Use /seen to see identities observed in this session."
            )
            self.write_message(
                "Use /full to display your complete DID."
            )
            self.write_message(
                "Use /quit to exit."
            )
            return

        if name == "/from":
            self.write_message(
                f"You are {short_did(self.did, self.seen_dids)}"
            )
            return

        if name == "/full":
            self.write_message(
                self.did
            )
            return

        if name == "/seen":
            self.write_message(
                f"Seen identities: {len(self.seen_dids)}"
            )

            for did in self.seen_dids:
                self.write_message(
                    f"  {short_did(did, self.seen_dids)}"
                )

            return

        self.write_message(
            f"Unknown command: {name}. Try /help."
        )

    def send_message(self, text: str) -> None:
        self.write_message(
            f"You: {text}"
        )

        thread = threading.Thread(
            target=self._send_message_worker,
            args=(text,),
            daemon=True,
        )

        thread.start()

    def _send_message_worker(self, text: str) -> None:
        try:
            payload = send_signed_message(
                self.identity,
                self.did,
                self.room,
                text,
            )

            self.call_from_thread(
                self.process_messages,
                payload,
                False,
            )

        except HTTPError as exc:
            try:
                body = exc.read().decode(
                    "utf-8",
                    errors="replace",
                ).strip()
            except Exception:
                body = ""

            error = (
                f"Send failed ({exc.code})"
                + (f": {body}" if body else "")
            )

            self.call_from_thread(
                self.write_message,
                error,
            )

        except Exception as exc:
            self.call_from_thread(
                self.write_message,
                f"Send failed: {exc}",
            )

    def exit_chat(self) -> None:
        self.running = False
        self.exit()


def main():
    identity = load_identity(IDENTITY_PATH)

    did = derive_did(identity)

    print(f"Identity: {did}")

    app = TechnocoreChat(
        identity,
        did,
    )

    app.run()


if __name__ == "__main__":
    main()
