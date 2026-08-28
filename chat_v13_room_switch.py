from pathlib import Path
from getpass import getpass
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import base64
import json
import re
import threading
import time
from collections import deque

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Footer, Header, Input, Label, RichLog, Static

IDENTITY_PATH = Path("identity.pem")
BASE = "https://technocore.chat"
ROOM = "lobby"
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
MAX_MESSAGE_LENGTH = 4096
READ_LIMIT = 50
INITIAL_READ_LIMIT = 20
POLL_WAIT = 10
RECONNECT_DELAY = 2
REQUEST_TIMEOUT = 20
MAX_RESPONSE_BYTES = 512 * 1024
MAX_DISPLAYED_MESSAGES = 300
DISPLAY_INTERVAL = 0.25
MAX_DISPLAY_QUEUE = 500
MAX_ROOM_LENGTH = 64
ROOM_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def base58btc_encode(data: bytes) -> str:
    number = int.from_bytes(data, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = ALPHABET[remainder] + encoded
    leading_zeroes = len(data) - len(data.lstrip(b"\x00"))
    return "1" * leading_zeroes + (encoded or "")


def load_identity(path: Path, passphrase: str | None = None) -> Ed25519PrivateKey:
    if not path.exists():
        raise SystemExit(f"Identity file not found: {path}")
    data = path.read_bytes()
    password = None
    if b"ENCRYPTED" in data:
        raw = passphrase if passphrase is not None else getpass("Passphrase for identity.pem: ")
        password = raw.encode()
    try:
        key = serialization.load_pem_private_key(data, password=password)
    except ValueError as exc:
        raise SystemExit("Could not decrypt identity.pem. Check the passphrase or path.") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("identity.pem is not an Ed25519 key")
    return key


def derive_did(key: Ed25519PrivateKey) -> str:
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "did:key:z" + base58btc_encode(b"\xed\x01" + public)


def short_did(full: str, seen: list[str], min_chars: int = 8, max_chars: int = 16) -> str:
    key = full.removeprefix("did:key:")
    for length in range(min_chars, max_chars + 1, 2):
        suffix = key[-length:]
        matches = [did for did in set(seen) if did.removeprefix("did:key:")[-length:] == suffix]
        if len(matches) <= 1:
            return "…" + suffix
    return full


def request_json(url: str, *, method: str = "GET"):
    req = Request(url, method=method, headers={"Accept": "application/json", "User-Agent": "technocore-chat/1.3"})
    with urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        raw_bytes = response.read(MAX_RESPONSE_BYTES + 1)
        content_type = response.headers.get("Content-Type", "")
    if len(raw_bytes) > MAX_RESPONSE_BYTES:
        raise ValueError(f"Server response is too large. Maximum is {MAX_RESPONSE_BYTES} bytes.")
    raw = raw_bytes.decode("utf-8", errors="replace")
    if "application/json" in content_type:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Server returned an invalid response.")
        return payload
    return raw


def read_room(room: str, *, since=None, limit=READ_LIMIT, wait=None):
    query = {"format": "json", "limit": str(limit)}
    if since is not None:
        query["since"] = str(since)
    if wait is not None and since is not None:
        query["wait"] = str(wait)
    return request_json(f"{BASE}/r/{quote(room, safe='')}?{urlencode(query)}")


def sign_message(identity: Ed25519PrivateKey, room: str, nonce: int, text: str) -> str:
    signature = identity.sign(f"{room}|{nonce}|{text}".encode("utf-8"))
    return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")


def send_signed_message(identity: Ed25519PrivateKey, did: str, room: str, text: str):
    text = text.replace("\r", " ").replace("\n", " ").strip()
    if not text:
        raise ValueError("Message cannot be empty.")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"Message is too long. Maximum is {MAX_MESSAGE_LENGTH} characters.")
    nonce = time.time_ns() // 1_000_000
    signature = sign_message(identity, room, nonce, text)
    url = (f"{BASE}/r/{quote(room, safe='')}/say-signed/"
           f"{quote(did, safe='')}/{quote(signature, safe='')}/"
           f"{nonce}/{quote(text, safe='')}")
    return request_json(url)


def validate_room_name(room: str) -> str:
    room = room.strip()
    if not ROOM_PATTERN.fullmatch(room):
        raise ValueError("Invalid room name. Use 1-64 letters, numbers, hyphens, or underscores.")
    return room


class TechnocoreChat(App):
    TITLE = "Technocore Chat"
    SUB_TITLE = "Public DID-based rooms"
    CSS = """
    Screen { background: $background; }
    #room_header { height: 3; padding: 0 1; border-bottom: solid $panel; }
    #room_name { width: 1fr; content-align: left middle; text-style: bold; }
    #connection { width: auto; content-align: right middle; }
    #identity { height: 1; padding: 0 1; color: $text-muted; }
    #messages { height: 1fr; border: none; padding: 1; }
    #composer { height: 3; border-top: solid $panel; padding: 0 1; }
    #prompt { width: auto; content-align: center middle; padding-right: 1; color: $text-muted; }
    #message_input { width: 1fr; }
    #hint { height: 1; padding: 0 1; color: $text-muted; }
    """

    def __init__(self, identity: Ed25519PrivateKey, did: str):
        super().__init__()
        self.identity = identity
        self.did = did
        self.room = ROOM
        self.running = True
        self.connected = False
        self.last_seq = 0
        self.seen_dids: list[str] = [did]
        self.displayed_seqs: set[int] = set()
        self.state_lock = threading.Lock()
        self.queue_lock = threading.Lock()
        self.display_queue = deque()
        self.queue_notice_pending = False
        self.queue_notice_count = 0
        self.poll_thread: threading.Thread | None = None
        self.display_timer = None
        self.room_generation = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="room_header"):
            yield Label(f"# {self.room}", id="room_name")
            yield Label("● Connecting...", id="connection")
        yield Static(f"Identity: {short_did(self.did, self.seen_dids)}", id="identity")
        yield RichLog(id="messages", wrap=True, markup=False, auto_scroll=True, max_lines=MAX_DISPLAYED_MESSAGES)
        with Container(id="composer"):
            with Horizontal():
                yield Label(">", id="prompt")
                yield Input(placeholder="Type a message...", id="message_input")
        yield Static("/help   /tutorial   /join <room>   /from   /seen   /full   /quit", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        for line in ("Welcome to Technocore Chat", "", "Messages in this room are public and cryptographically signed.", "", f"Your DID: {self.did}", "", f"Connecting to #{self.room}..."):
            self.write_message(line)
        self.query_one("#message_input", Input).focus()
        self.display_timer = self.set_interval(DISPLAY_INTERVAL, self.flush_display_queue)
        self.load_initial_messages()

    def load_initial_messages(self) -> None:
        try:
            payload = read_room(self.room, limit=INITIAL_READ_LIMIT)
            self.process_messages(payload, initial=True)
            self.connected = True
            self.update_connection("● Connected")
            self.start_polling()
        except HTTPError as exc:
            self.connected = False
            self.update_connection("● Offline")
            self.write_message(self.format_http_error("Initial connection failed", exc))
            self.start_polling()
        except (URLError, TimeoutError) as exc:
            self.connected = False
            self.update_connection("● Offline")
            self.write_message(f"Initial connection failed: {self.format_network_error(exc)}")
            self.start_polling()
        except Exception as exc:
            self.connected = False
            self.update_connection("● Offline")
            self.write_message(f"Initial connection failed: {exc}")
            self.start_polling()

    def start_polling(self) -> None:
        if self.poll_thread and self.poll_thread.is_alive():
            return
        self.poll_thread = threading.Thread(target=self.poll_loop, name="technocore-poller", daemon=True)
        self.poll_thread.start()

    def poll_loop(self) -> None:
        generation = self.room_generation
        while self.running:
            if generation != self.room_generation:
                return
            try:
                with self.state_lock:
                    current_seq = self.last_seq
                    current_room = self.room
                payload = read_room(current_room, since=current_seq, limit=READ_LIMIT, wait=POLL_WAIT)
                if self.running and generation == self.room_generation:
                    self.call_from_thread(self.handle_poll_success, payload, generation)
            except HTTPError as exc:
                if not self.running: break
                if generation != self.room_generation: return
                self.call_from_thread(self.handle_poll_http_error, exc, generation)
                self.stop_or_wait(RECONNECT_DELAY)
            except (URLError, TimeoutError) as exc:
                if not self.running: break
                if generation != self.room_generation: return
                self.call_from_thread(self.handle_poll_network_error, exc, generation)
                self.stop_or_wait(RECONNECT_DELAY)
            except Exception as exc:
                if not self.running: break
                if generation != self.room_generation: return
                self.call_from_thread(self.handle_poll_error, exc, generation)
                self.stop_or_wait(RECONNECT_DELAY)

    def handle_poll_success(self, payload, generation=None) -> None:
        if self.running and (generation is None or generation == self.room_generation):
            self.connected = True
            self.update_connection("● Connected")
            self.process_messages(payload, initial=False)

    def handle_poll_http_error(self, exc: HTTPError, generation=None) -> None:
        if generation is not None and generation != self.room_generation: return
        self.connected = False
        if exc.code == 429:
            self.update_connection("● Rate limited")
            self.write_message("Server rate limit reached. Retrying soon.")
        elif 500 <= exc.code <= 599:
            self.update_connection("● Server error")
            self.write_message(self.format_http_error("Server error", exc))
        else:
            self.update_connection("● Reconnecting...")
            self.write_message(self.format_http_error("Connection error", exc))

    def handle_poll_network_error(self, exc: Exception, generation=None) -> None:
        if generation is not None and generation != self.room_generation: return
        self.connected = False
        self.update_connection("● Reconnecting...")
        self.write_message(f"Network error: {self.format_network_error(exc)}")

    def handle_poll_error(self, exc: Exception, generation=None) -> None:
        if generation is not None and generation != self.room_generation: return
        self.connected = False
        self.update_connection("● Reconnecting...")
        self.write_message(f"Polling error: {exc}")

    def stop_or_wait(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while self.running:
            remaining = end - time.monotonic()
            if remaining <= 0: return
            time.sleep(min(0.25, remaining))

    def normalize_messages(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Received an invalid server response.")
        room_messages = payload.get("messages", [])
        if not isinstance(room_messages, list):
            raise ValueError("Server returned invalid message data.")
        normalized = []
        for message in room_messages:
            if not isinstance(message, dict): continue
            try: seq = int(message.get("seq", 0))
            except (TypeError, ValueError): continue
            if seq > 0: normalized.append((seq, message))
        normalized.sort(key=lambda item: item[0])
        return normalized

    def process_messages(self, payload, initial=False) -> None:
        try:
            normalized = self.normalize_messages(payload)
        except ValueError as exc:
            self.write_message(str(exc))
            return
        unseen = []
        with self.state_lock:
            current_last_seq = self.last_seq
        for seq, message in normalized:
            if seq <= current_last_seq or seq in self.displayed_seqs:
                continue
            sender = message.get("from", "unknown")
            text = message.get("text", "")
            timestamp = message.get("ts", "")
            if not isinstance(sender, str): sender = "unknown"
            if not isinstance(text, str): text = str(text)
            if not isinstance(timestamp, str): timestamp = str(timestamp)
            if sender and sender not in self.seen_dids: self.seen_dids.append(sender)
            unseen.append((seq, timestamp, sender, text))
        if not unseen:
            server_last_seq = payload.get("last_seq")
            if server_last_seq is not None:
                try:
                    with self.state_lock: self.last_seq = max(self.last_seq, int(server_last_seq))
                except (TypeError, ValueError): pass
            if initial:
                self.write_message("")
                self.write_message("Loaded 0 new public messages.")
            return
        to_queue = unseen[-INITIAL_READ_LIMIT:] if initial else unseen
        skipped = len(unseen) - len(to_queue)
        with self.queue_lock:
            for item in to_queue:
                if len(self.display_queue) >= MAX_DISPLAY_QUEUE:
                    self.display_queue.popleft()
                    skipped += 1
                self.display_queue.append(item)
        highest_seq = max(seq for seq, *_ in unseen)
        with self.state_lock:
            self.last_seq = max(self.last_seq, highest_seq)
        if initial:
            self.write_message("")
            self.write_message(f"Loaded {len(to_queue)} public messages.")

    def queue_display_item(self, item) -> None:
        seq = item[0]
        with self.queue_lock:
            if seq in self.displayed_seqs:
                return False
            if len(self.display_queue) >= MAX_DISPLAY_QUEUE:
                self.display_queue.popleft()
                self.queue_notice_pending = True
                self.queue_notice_count += 1
            self.display_queue.append(item)
        return True

    def flush_display_queue(self) -> None:
        if not self.running: return
        notice = None
        with self.queue_lock:
            if self.queue_notice_pending:
                notice = f"[{self.queue_notice_count} messages skipped from the live display because traffic was too fast]"
                self.queue_notice_pending = False
                self.queue_notice_count = 0
            item = self.display_queue.popleft() if self.display_queue else None
        if notice: self.write_message(notice)
        if item:
            seq, timestamp, sender, text = item
            self.displayed_seqs.add(seq)
            self.write_message(self.format_message(timestamp, sender, text))

    def format_message(self, timestamp: str, sender: str, text: str) -> str:
        display_sender = "You" if sender == self.did else short_did(sender, self.seen_dids)
        return f"{timestamp} {display_sender}  {text}"

    def format_http_error(self, prefix: str, exc: HTTPError) -> str:
        try: body = exc.read().decode("utf-8", errors="replace").strip()
        except Exception: body = ""
        result = f"{prefix} ({exc.code})"
        if body: result += f": {body}"
        return result

    def format_network_error(self, exc: Exception) -> str:
        reason = getattr(exc, "reason", None)
        return str(reason) if reason else str(exc)

    def write_message(self, text: str) -> None:
        if self.running: self.query_one("#messages", RichLog).write(text)

    def update_connection(self, text: str) -> None:
        if self.running: self.query_one("#connection", Label).update(text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text: return
        if text.startswith("/"): self.handle_command(text)
        else: self.send_message(text)

    def handle_command(self, command: str) -> None:
        parts = command.split(maxsplit=1)
        name = parts[0].lower()
        if name == "/quit": self.exit_chat(); return
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
        if name == "/from": self.write_message(f"You are {short_did(self.did, self.seen_dids)}"); return
        if name == "/full": self.write_message(self.did); return
        if name == "/seen":
            self.write_message(f"Seen identities: {len(self.seen_dids)}")
            for did in self.seen_dids: self.write_message(f"  {short_did(did, self.seen_dids)}")
            return
        self.write_message(f"Unknown command: {name}")

    def switch_room(self, new_room: str) -> None:
        try:
            new_room = validate_room_name(new_room)
        except ValueError as exc:
            self.write_message(str(exc))
            return
        if new_room == self.room:
            self.write_message(f"Already in #{new_room}.")
            return
        self.room_generation += 1
        self.room = new_room
        with self.state_lock:
            self.last_seq = 0
        with self.queue_lock:
            self.display_queue.clear()
            self.queue_notice_pending = False
            self.queue_notice_count = 0
        self.displayed_seqs.clear()
        self.seen_dids = [self.did]
        self.connected = False
        self.query_one("#room_name", Label).update(f"# {self.room}")
        self.update_connection("● Connecting...")
        self.write_message("")
        self.write_message(f"Switching to #{self.room}...")
        try:
            payload = read_room(self.room, limit=INITIAL_READ_LIMIT)
            self.process_messages(payload, initial=True)
            self.connected = True
            self.update_connection("● Connected")
            self.start_polling()
        except HTTPError as exc:
            self.update_connection("● Offline")
            self.write_message(self.format_http_error("Room connection failed", exc))
            self.start_polling()
        except (URLError, TimeoutError) as exc:
            self.update_connection("● Offline")
            self.write_message(f"Room connection failed: {self.format_network_error(exc)}")
            self.start_polling()
        except Exception as exc:
            self.update_connection("● Offline")
            self.write_message(f"Room connection failed: {exc}")
            self.start_polling()

    def send_message(self, text: str) -> None:
        threading.Thread(target=self.send_worker, args=(text,), name="technocore-sender", daemon=True).start()

    def send_worker(self, text: str) -> None:
        try:
            payload = send_signed_message(self.identity, self.did, self.room, text)
            if self.running:
                self.call_from_thread(self.handle_send_success, payload, text)
        except HTTPError as exc:
            if self.running: self.call_from_thread(self.handle_send_http_error, exc)
        except (URLError, TimeoutError) as exc:
            if self.running: self.call_from_thread(self.write_message, f"Send failed: {self.format_network_error(exc)}")
        except Exception as exc:
            if self.running: self.call_from_thread(self.write_message, f"Send failed: {exc}")

    def handle_send_success(self, payload, sent_text: str) -> None:
        if not self.running: return
        if isinstance(payload, dict):
            self.process_messages(payload, initial=False)
            return
        self.write_message("Message accepted by server. Waiting for room feed...")

    def handle_send_http_error(self, exc: HTTPError) -> None:
        if self.running: self.write_message(self.format_http_error("Send failed", exc))

    def exit_chat(self) -> None:
        self.running = False
        self.exit()


def main():
    identity = load_identity(IDENTITY_PATH)
    did = derive_did(identity)
    print(f"Identity: {did}")
    app = TechnocoreChat(identity, did)
    app.run()


if __name__ == "__main__":
    main()
