import json
import socket

MAX_LINE_LENGTH = 4096
PRODUCTS = {
    "coffee": 4,
    "tea": 3,
    "croissant": 2,
}


class ProtocolError(Exception):
    """Raised when incoming data violates protocol rules or length limits."""


def send_msg(sock: socket.socket, send_lock, payload: dict) -> bool:
    """Thread-safe JSON line sender using sendall()."""
    raw = (json.dumps(payload) + "\n").encode("utf-8")
    with send_lock:
        try:
            sock.sendall(raw)
            return True
        except OSError:
            return False


class LineReader:
    """
    Buffers raw TCP chunks and extracts complete '\n'-terminated lines.
    Handles TCP fragmentation (1 message in 2 recv calls) and coalescing
    (2 messages in 1 recv call).
    """

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.buffer = bytearray()

    def read_message(self) -> dict | None:
        """
        Returns a parsed JSON dict, or None on clean EOF (recv == 0).
        Raises ProtocolError on invalid JSON, non-UTF8, or oversized lines.
        Raises OSError / socket.timeout on network errors.
        """
        while True:
            newline_idx = self.buffer.find(b"\n")
            if newline_idx != -1:
                line_bytes = bytes(self.buffer[:newline_idx])
                del self.buffer[: newline_idx + 1]

                if len(line_bytes) > MAX_LINE_LENGTH:
                    raise ProtocolError("Message exceeds maximum length.")

                try:
                    text = line_bytes.decode("utf-8").strip()
                    data = json.loads(text)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ProtocolError("Malformed JSON or invalid UTF-8.") from exc

                if not isinstance(data, dict):
                    raise ProtocolError("Message payload must be a JSON object.")
                return data

            if len(self.buffer) > MAX_LINE_LENGTH:
                raise ProtocolError("Line buffer overflow (missing newline).")

            chunk = self.sock.recv(1024)
            if not chunk:
                # Peer closed connection cleanly
                return None
            self.buffer.extend(chunk)