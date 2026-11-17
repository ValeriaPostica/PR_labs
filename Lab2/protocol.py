"""One UTF-8 text message per line."""

MAX_MESSAGE_SIZE = 4096
HEARTBEAT_INTERVAL = 5
CONNECTION_TIMEOUT = 30
PREPARATION_TIMES = {"coffee": 4, "tea": 3, "croissant": 2}


class ProtocolError(ValueError):
    pass


def send_message(sock, lock, message):
    with lock:
        try:
            sock.sendall((message + "\n").encode("utf-8"))
            return True
        except OSError:
            return False


class LineReader:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = bytearray()

    def read_message(self):
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                if newline > MAX_MESSAGE_SIZE:
                    raise ProtocolError("Message is too long.")
                line = bytes(self.buffer[:newline])
                del self.buffer[: newline + 1]
                try:
                    return line.decode("utf-8")
                except UnicodeDecodeError:
                    raise ProtocolError("Message must be UTF-8 text.") from None
            if len(self.buffer) > MAX_MESSAGE_SIZE:
                raise ProtocolError("Message is too long.")
            chunk = self.sock.recv(1024)
            if not chunk:
                if self.buffer:
                    raise ProtocolError("Incomplete message.")
                return None
            self.buffer.extend(chunk)
