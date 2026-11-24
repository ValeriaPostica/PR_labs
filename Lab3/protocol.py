import base64
import hashlib
import os
from typing import NamedTuple
from unicodedata import category

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MULTICAST_KINDS = {"probe", "alive", "leave", "general"}
UNICAST_KINDS = {"probe", "present", "private"}
MAX_TEXT = 500
MAX_DATAGRAM = 4096
NONCE_SIZE = 12


class Packet(NamedTuple):
    kind: str
    name: str
    session: str
    text: str

    def header(self):
        return f"LAN3 {self.kind} {self.name} {self.session} ".encode("utf-8")


def valid_name(name):
    return 1 <= len(name) <= 64 and name.isprintable() and not any(
        char.isspace() for char in name
    )


def valid_text(text):
    return 1 <= len(text) <= MAX_TEXT and all(
        char == "\t" or category(char) not in {"Cc", "Cs"} for char in text
    )


def make_cipher(passphrase, port):
    salt = b"LAN3" + port.to_bytes(2, "big")
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 600_000)
    return AESGCM(key)


def encode(packet, cipher, recipient=None):
    header = packet.header()
    body = packet.text.encode("utf-8")
    if packet.kind == "private":
        nonce = os.urandom(NONCE_SIZE)
        encrypted = cipher.encrypt(nonce, body, header + recipient.encode("ascii"))
        body = base64.b64encode(nonce + encrypted)
    return header + body


def decode(data, cipher, receiver, direct):
    if len(data) > MAX_DATAGRAM:
        raise ValueError("Datagram is too long.")
    prefix, kind, name, session, body = data.decode("utf-8").split(" ", 4)
    kinds = UNICAST_KINDS if direct else MULTICAST_KINDS
    if prefix != "LAN3" or kind not in kinds or not valid_name(name):
        raise ValueError("Invalid header.")
    if len(session) != 32 or any(char not in "0123456789abcdef" for char in session):
        raise ValueError("Invalid session ID.")

    packet = Packet(kind, name, session, body)
    if kind == "private":
        encrypted = base64.b64decode(body, validate=True)
        nonce, ciphertext = encrypted[:NONCE_SIZE], encrypted[NONCE_SIZE:]
        associated_data = packet.header() + receiver.encode("ascii")
        body = cipher.decrypt(nonce, ciphertext, associated_data).decode("utf-8")
        packet = Packet(kind, name, session, body)
    if kind in {"general", "private"}:
        if not valid_text(body):
            raise ValueError("Invalid chat text.")
    elif body:
        raise ValueError("Presence packets have no text.")
    return packet
