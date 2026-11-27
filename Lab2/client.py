import argparse
import socket
import threading

from protocol import CONNECTION_TIMEOUT, HEARTBEAT_INTERVAL, LineReader, ProtocolError, send_message


def run_client(host, port, role):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(CONNECTION_TIMEOUT)
    lock = threading.Lock()
    stopped = threading.Event()

    def send(message):
        if send_message(sock, lock, message):
            return True
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        return False

    def read_keyboard():
        while not stopped.is_set():
            try:
                message = input("> ").strip()
            except EOFError:
                message = "QUIT"
            if message and (not send(message) or message.upper() == "QUIT"):
                return

    def heartbeat():
        while not stopped.wait(HEARTBEAT_INTERVAL):
            if not send("PING"):
                return

    try:
        sock.connect((host, port))
        if not send(f"HELLO {role}"):
            return
        reader = LineReader(sock)
        welcome = reader.read_message()
        print(welcome or "Server disconnected.", flush=True)
        if welcome != f"WELCOME {role}":
            return
        print("Commands: menu | order coffee 1 tea 2 | deliver coffee 20 | quit", flush=True)
        threading.Thread(target=read_keyboard, daemon=True).start()
        threading.Thread(target=heartbeat, daemon=True).start()
        while True:
            message = reader.read_message()
            if message is None:
                print("\nServer disconnected.", flush=True)
                break
            if message == "PONG":
                continue
            print(f"\n{message}", flush=True)
            if message == "BYE":
                break
    except (OSError, ProtocolError) as exc:
        print(f"\nConnection ended: {exc}", flush=True)
    except KeyboardInterrupt:
        print("\nDisconnected.", flush=True)
    finally:
        stopped.set()
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coffee shop client or provider")
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("role", nargs="?", choices=("client", "provider"), default="client")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    run_client(args.host, args.port, args.role)
