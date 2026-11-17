import json
import socket
import threading
import time

HOST = "127.0.0.1"
PORT = 5000


def send_json(sock: socket.socket, obj: dict):
    sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))


def recv_line(sock: socket.socket) -> dict:
    buf = bytearray()
    while b"\n" not in buf:
        chunk = sock.recv(1024)
        if not chunk:
            return {"type": "EOF"}
        buf.extend(chunk)
    line, _ = buf.split(b"\n", 1)
    return json.loads(line.decode("utf-8"))


def test_race_condition_and_workers():
    """Spawns 8 concurrent clients ordering at the exact same instant (Task 2)."""
    barrier = threading.Barrier(8)
    results = []
    lock = threading.Lock()

    def client_worker(idx: int):
        s = socket.create_connection((HOST, PORT), timeout=15)
        send_json(s, {"cmd": "HELLO", "role": "client"})
        recv_line(s)  # WELCOME

        barrier.wait()  # Release all 8 threads simultaneously
        send_json(s, {"cmd": "ORDER", "items": {"coffee": 5}})
        resp = recv_line(s)
        with lock:
            results.append((idx, resp))
        s.close()

    threads = [threading.Thread(target=client_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for idx, res in sorted(results):
        print(f"Client {idx}: {res}")


def test_disconnect_rollback():
    """Places an order and immediately disconnects to verify stock rollback (Task 4)."""
    s = socket.create_connection((HOST, PORT), timeout=5)
    send_json(s, {"cmd": "HELLO", "role": "client"})
    recv_line(s)  # WELCOME

    send_json(s, {"cmd": "MENU"})
    before = recv_line(s)["stock"]["tea"]

    send_json(s, {"cmd": "ORDER", "items": {"tea": 3}})
    print("Accepted:", recv_line(s))
    time.sleep(0.5)  # Let a worker start preparing
    s.close()  # Abruptly disconnect mid-preparation

    time.sleep(0.5)
    s2 = socket.create_connection((HOST, PORT), timeout=5)
    send_json(s2, {"cmd": "HELLO", "role": "client"})
    recv_line(s2)
    send_json(s2, {"cmd": "MENU"})
    after = recv_line(s2)["stock"]["tea"]
    s2.close()
    print(f"Tea stock before={before}, after disconnect rollback={after}")


if __name__ == "__main__":
    print("--- Testing Disconnect Rollback ---")
    test_disconnect_rollback()
    print("\n--- Testing 8 Simultaneous Clients ---")
    test_race_condition_and_workers()