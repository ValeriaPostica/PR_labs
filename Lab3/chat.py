import argparse
import logging
import os
import queue
import select
import socket
import sys
import threading
import time
import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag

from protocol import (
    MAX_TEXT,
    MULTICAST_KINDS,
    UNICAST_KINDS,
    Packet,
    decode,
    encode,
    make_cipher,
    valid_name,
    valid_text,
)


GROUP = "239.255.42.99"
DISCOVERY_TIME = 1
HEARTBEAT_INTERVAL = 5
PEER_TIMEOUT = 15


class NameTaken(Exception):
    pass


@dataclass
class Peer:
    session: str
    endpoint: tuple[str, int]
    last_seen: float


def read_keyboard(commands):
    for line in sys.stdin:
        commands.put(line.rstrip("\r\n"))
    commands.put("/quit")


class Chat:
    def __init__(self, name, port, cipher, multicast, direct):
        self.name = name
        self.session = uuid.uuid4().hex
        self.group = (GROUP, port)
        self.cipher = cipher
        self.multicast = multicast
        self.direct = direct
        self.peers = {}
        self.joined = False

        multicast.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            multicast.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        multicast.bind(("0.0.0.0", port))
        membership = socket.inet_aton(GROUP) + socket.inet_aton("0.0.0.0")
        multicast.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)

        direct.bind(("0.0.0.0", 0))
        direct.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        direct.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

    def send(self, kind, endpoint=None, text="", recipient=None):
        endpoint = endpoint or self.group
        data = encode(Packet(kind, self.name, self.session, text), self.cipher, recipient)
        try:
            self.direct.sendto(data, endpoint)
        except OSError as error:
            logging.info("SEND_ERROR %s:%s %s %d bytes", *endpoint, kind, len(data))
            print(f"Could not send {kind}: {error}")
        else:
            logging.info("SEND %s:%s %s %d bytes", *endpoint, kind, len(data))

    def receive(self, sock):
        try:
            data, endpoint = sock.recvfrom(65535)
        except ConnectionResetError:
            return
        direct = sock is self.direct
        try:
            packet = decode(data, self.cipher, self.session, direct)
        except (ValueError, InvalidTag):
            header = data.removeprefix(b"LAN3 ")
            kind = header.partition(b" ")[0].decode("ascii", "replace")
            if kind not in MULTICAST_KINDS and kind not in UNICAST_KINDS:
                kind = "unknown"
            logging.info("DROP %s:%s %s %d bytes", *endpoint, kind, len(data))
            return
        logging.info("RECV %s:%s %s %d bytes", *endpoint, packet.kind, len(data))

        if packet.kind in {"general", "private"}:
            peer = self.peers.get(packet.name)
            if peer and peer.session == packet.session and peer.endpoint == endpoint:
                peer.last_seen = time.monotonic()
            print(f"[{packet.kind}] {packet.name}: {packet.text}")
        elif packet.session != self.session:
            self.update_presence(packet, endpoint, direct)

    def update_presence(self, packet, endpoint, direct):
        name, session = packet.name, packet.session
        if packet.kind == "probe":
            if self.joined:
                self.send("present", endpoint)
            elif name == self.name:
                # Waiting peers give the name to the smaller session ID.
                if session < self.session:
                    raise NameTaken
                if not direct:
                    self.send("probe", endpoint)
            return

        peer = self.peers.get(name)
        if packet.kind == "leave":
            if peer and peer.session == session:
                self.remove_peer(name)
        elif name == self.name:
            if not self.joined or session < self.session:
                raise NameTaken
        elif peer is None or session <= peer.session:
            self.peers[name] = Peer(session, endpoint, time.monotonic())
            if peer is None:
                print(f"* {name} joined the chat")

    def remove_peer(self, name):
        del self.peers[name]
        print(f"* {name} left the chat")

    def listen(self, timeout):
        ready, _, _ = select.select([self.multicast, self.direct], [], [], timeout)
        for sock in ready:
            self.receive(sock)

    def handle_line(self, line):
        if not line:
            return
        if line == "/users":
            print("Online: " + ", ".join(sorted([self.name, *self.peers])))
            return

        recipient = None
        if line.startswith("/"):
            parts = line.split(maxsplit=2)
            if parts[0] != "/msg" or len(parts) != 3:
                print("Commands: /msg name text, /users, /quit")
                return
            _, recipient, line = parts

        if not valid_text(line):
            print(f"Enter 1 to {MAX_TEXT} characters of text.")
        elif recipient is None:
            self.send("general", text=line)
        elif recipient == self.name:
            local_endpoint = ("127.0.0.1", self.direct.getsockname()[1])
            self.send("private", local_endpoint, line, self.session)
        elif recipient in self.peers:
            peer = self.peers[recipient]
            self.send("private", peer.endpoint, line, peer.session)
        else:
            print(f"{recipient} is not online.")

    def run(self):
        self.send("probe")
        deadline = time.monotonic() + DISCOVERY_TIME
        while (remaining := deadline - time.monotonic()) > 0:
            self.listen(remaining)

        self.joined = True
        try:
            self.send("alive")
            print(f"Joined as {self.name} on port {self.group[1]}.")
            next_heartbeat = time.monotonic() + HEARTBEAT_INTERVAL
            commands = queue.SimpleQueue()
            threading.Thread(target=read_keyboard, args=(commands,), daemon=True).start()

            while True:
                self.listen(0 if not commands.empty() else 0.1)
                now = time.monotonic()
                if now >= next_heartbeat:
                    self.send("alive")
                    next_heartbeat = now + HEARTBEAT_INTERVAL
                for name, peer in list(self.peers.items()):
                    if now - peer.last_seen >= PEER_TIMEOUT:
                        self.remove_peer(name)

                try:
                    line = commands.get_nowait()
                except queue.Empty:
                    continue
                if line == "/quit":
                    return
                self.handle_line(line)
        finally:
            self.send("leave")


def main():
    parser = argparse.ArgumentParser(description="Peer-to-peer UDP LAN chat.")
    parser.add_argument("name", help="unique chat name")
    parser.add_argument("port", type=int, help="shared UDP port")
    parser.add_argument("passphrase", help="shared secret for private messages")
    args = parser.parse_args()
    if not valid_name(args.name):
        parser.error("name must be 1 to 64 printable characters without spaces")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if not args.passphrase:
        parser.error("passphrase must not be empty")

    log_file = f"chat-{os.getpid()}.log"
    logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s %(message)s")
    print(f"Log file: {log_file}")
    try:
        cipher = make_cipher(args.passphrase, args.port)
        with (
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as multicast,
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as direct,
        ):
            Chat(args.name, args.port, cipher, multicast, direct).run()
    except NameTaken:
        print(f"The name {args.name} is already in use.", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Socket error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
