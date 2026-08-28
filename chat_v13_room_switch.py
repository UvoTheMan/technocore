# PATCH REQUIRED: In handle_send_success, immediately fetch the active room feed after a successful send.
# This file is intentionally a patch marker because the previous full-file update must not be overwritten blindly.
# Use the existing chat_v13_room_switch.py and replace handle_send_success with:
#
# def handle_send_success(self, payload, sent_text: str) -> None:
#     if not self.running:
#         return
#     if isinstance(payload, dict):
#         self.process_messages(payload, initial=False)
#     else:
#         self.write_message("Message accepted by server. Refreshing room feed...")
#     try:
#         with self.state_lock:
#             current_room = self.room
#             current_seq = self.last_seq
#         refreshed = read_room(current_room, since=current_seq, limit=READ_LIMIT)
#         self.process_messages(refreshed, initial=False)
#     except Exception as exc:
#         self.write_message(f"Room refresh after send failed: {exc}")
