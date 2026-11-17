"""Checks for the lab requirements using connected local sockets."""

import socket
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from protocol import LineReader, PREPARATION_TIMES, send_message
from server import CoffeeShopServer, Connection


class Peer:
    def __init__(self, shop, role="client", timeout=30):
        self.sock, server_socket = socket.socketpair()
        self.sock.settimeout(6)
        server_socket.settimeout(timeout)
        self.connection = Connection(server_socket, ("local", server_socket.fileno()))
        self.thread = threading.Thread(
            target=shop.handle_connection, args=(self.connection,), daemon=True,
        )
        self.thread.start()
        self.reader = LineReader(self.sock)
        self.send(f"HELLO {role}")
        self.welcome = self.receive()

    def send(self, message):
        self.sock.sendall((message + "\n").encode("utf-8"))

    def receive(self):
        return self.reader.read_message()

    def close(self):
        self.sock.close()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.shop = CoffeeShopServer("127.0.0.1", 0)
        self.shop.log = lambda *args: None
        self.shop.stock = {name: 10 for name in PREPARATION_TIMES}
        self.peers = []
        # Simulate two logical processors to make queueing easy to check.
        self.workers = [threading.Thread(target=self.shop.worker, daemon=True) for _ in range(2)]
        for worker in self.workers:
            worker.start()

    def tearDown(self):
        for peer in self.peers:
            peer.close()
            self.shop.disconnect(peer.connection)
        for _ in self.workers:
            self.shop.order_queue.put(None)
        for thread in self.workers + [peer.thread for peer in self.peers]:
            thread.join(2)
            self.assertFalse(thread.is_alive())

    def connect(self, role="client", timeout=30):
        peer = Peer(self.shop, role, timeout)
        self.peers.append(peer)
        self.assertEqual(peer.welcome, f"WELCOME {role}")
        return peer

    def wait_for_stock(self, expected):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with self.shop.lock:
                if self.shop.stock == expected:
                    return
            time.sleep(0.01)
        self.fail(f"Expected stock {expected}, got {self.shop.stock}")

    def test_menu_acceptance_and_preparation(self):
        client = self.connect()
        client.send("MENU")
        self.assertIn("coffee=10 tea=10 croissant=10", client.receive())
        started = time.monotonic()
        client.send("ORDER croissant 1")
        self.assertEqual(client.receive(), "ORDER_ACCEPTED 1 preparation=2s")
        self.assertLess(time.monotonic() - started, 1)
        client.send("MENU")
        self.assertIn("croissant=9", client.receive())
        self.assertEqual(client.receive(), "ORDER_READY 1")
        self.assertGreaterEqual(time.monotonic() - started, 1.9)
        client.send("ORDER croissant 2 tea 1 coffee 1")
        self.assertIn("preparation=11s", client.receive())

    def test_invalid_commands_quantities_and_roles(self):
        client = self.connect()
        commands = [
            "", "UNKNOWN", "MENU extra", "ORDER", "ORDER tea", "ORDER unknown 1",
            "ORDER tea 0", "ORDER tea -1", "ORDER tea 1.5", "ORDER tea true",
            "DELIVER tea 1", "ORDER " + "x" * 4000 + " 1",
        ]
        for command in commands:
            with self.subTest(command=command[:40]):
                client.send(command)
                self.assertTrue(client.receive().startswith("ERROR"))
        client.send("ORDER tea 11 coffee 1")
        self.assertIn("available: tea=10", client.receive())
        self.assertEqual(self.shop.stock["coffee"], 10)
        provider = self.connect("provider")
        provider.send("ORDER coffee 1")
        self.assertTrue(provider.receive().startswith("ERROR"))
        provider.send("DELIVER tea 0")
        self.assertTrue(provider.receive().startswith("ERROR"))
        provider.send("DELIVER tea 20")
        self.assertIn("tea=30", provider.receive())
        duplicate = Peer(self.shop, "provider")
        self.peers.append(duplicate)
        self.assertTrue(duplicate.welcome.startswith("ERROR"))
        self.assertIsNone(duplicate.receive())

    def test_provider_alerts_delivery_and_reconnection(self):
        client = self.connect()
        client.send("ORDER coffee 7")
        self.assertTrue(client.receive().startswith("ORDER_ACCEPTED"))
        provider = self.connect("provider")
        self.assertEqual(provider.receive(), "ALERT coffee=3")
        provider.send("DELIVER coffee 20")
        self.assertIn("coffee=23", provider.receive())
        client.send("ORDER tea 7")
        self.assertTrue(client.receive().startswith("ORDER_ACCEPTED"))
        self.assertEqual(provider.receive(), "ALERT tea=3")
        provider.send("QUIT")
        self.assertEqual(provider.receive(), "BYE")
        self.assertIsNone(provider.receive())
        replacement = self.connect("provider")
        self.assertEqual(replacement.receive(), "ALERT tea=3")
        client.send("MENU")
        self.assertIn("coffee=23 tea=3", client.receive())

    def test_only_one_client_gets_the_last_item(self):
        self.shop.stock["croissant"] = 1
        clients = [self.connect() for _ in range(8)]
        barrier = threading.Barrier(len(clients))

        def order(client):
            barrier.wait(timeout=2)
            client.send("ORDER croissant 1")
            return client.receive().split()[0]

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(order, clients))
        self.assertEqual(responses.count("ORDER_ACCEPTED"), 1)
        self.assertEqual(responses.count("ERROR"), 7)

    def test_delivery_and_order_do_not_lose_stock(self):
        client, provider = self.connect(), self.connect("provider")
        barrier = threading.Barrier(2)

        def request(peer, command):
            barrier.wait(timeout=2)
            peer.send(command)
            return peer.receive()

        with ThreadPoolExecutor(max_workers=2) as pool:
            order = pool.submit(request, client, "ORDER coffee 1")
            delivery = pool.submit(request, provider, "DELIVER coffee 7")
            self.assertTrue(order.result().startswith("ORDER_ACCEPTED"))
            self.assertTrue(delivery.result().startswith("DELIVERY_ACCEPTED"))
        self.assertEqual(self.shop.stock["coffee"], 16)

    def test_fifo_with_more_clients_than_workers(self):
        clients = [self.connect() for _ in range(4)]
        started = time.monotonic()
        for number, client in enumerate(clients, 1):
            client.send("ORDER croissant 1")
            self.assertEqual(client.receive(), f"ORDER_ACCEPTED {number} preparation=2s")
        for number, client in enumerate(clients, 1):
            self.assertEqual(client.receive(), f"ORDER_READY {number}")
            if number == 2:
                self.assertLess(time.monotonic() - started, 3.5)
        self.assertGreaterEqual(time.monotonic() - started, 3.9)

    def test_disconnect_cancels_running_and_waiting_orders(self):
        client = self.connect()
        for _ in range(3):
            client.send("ORDER coffee 1")
            self.assertTrue(client.receive().startswith("ORDER_ACCEPTED"))
        with client.connection.lock:
            orders = list(client.connection.orders.values())
        client.close()
        self.wait_for_stock({name: 10 for name in PREPARATION_TIMES})
        self.assertTrue(all(order.cancelled.is_set() for order in orders))
        observer = self.connect()
        started = time.monotonic()
        observer.send("ORDER croissant 1")
        self.assertTrue(observer.receive().startswith("ORDER_ACCEPTED"))
        self.assertTrue(observer.receive().startswith("ORDER_READY"))
        self.assertTrue(1.9 <= time.monotonic() - started < 3.5)

    def test_timeout_refunds_unfinished_orders(self):
        client = self.connect(timeout=0.2)
        client.send("ORDER tea 1")
        self.assertTrue(client.receive().startswith("ORDER_ACCEPTED"))
        self.assertIn("timed out", client.receive())
        self.assertIsNone(client.receive())
        self.wait_for_stock({name: 10 for name in PREPARATION_TIMES})

    def test_failed_ready_message_refunds_order(self):
        def fail_ready(sock, lock, message):
            return False if message.startswith("ORDER_READY") else send_message(sock, lock, message)

        client = self.connect()
        with patch("server.send_message", side_effect=fail_ready):
            client.send("ORDER croissant 1")
            self.assertTrue(client.receive().startswith("ORDER_ACCEPTED"))
            self.assertIsNone(client.receive())
        self.wait_for_stock({name: 10 for name in PREPARATION_TIMES})

    def test_stream_framing_and_invalid_bytes(self):
        client = self.connect()
        client.sock.sendall(b"ME")
        time.sleep(0.02)
        client.sock.sendall(b"NU\nPING\n")
        self.assertTrue(client.receive().startswith("MENU"))
        self.assertEqual(client.receive(), "PONG")
        for payload in (b"\xff\n", b"x" * 4097, b"incomplete"):
            with self.subTest(payload=payload[:20]):
                bad = self.connect()
                bad.sock.sendall(payload)
                if payload == b"incomplete":
                    bad.sock.shutdown(socket.SHUT_WR)
                self.assertTrue(bad.receive().startswith("ERROR"))
                self.assertIsNone(bad.receive())
        client.send("MENU")
        self.assertTrue(client.receive().startswith("MENU"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
