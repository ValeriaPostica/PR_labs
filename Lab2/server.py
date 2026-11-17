import argparse
import os
import queue
import random
import socket
import threading
from dataclasses import dataclass, field

from protocol import CONNECTION_TIMEOUT, PREPARATION_TIMES, LineReader, ProtocolError, send_message


@dataclass
class Order:
    number: int
    items: dict[str, int]
    seconds: int
    cancelled: threading.Event = field(default_factory=threading.Event)


class Connection:
    def __init__(self, sock, address):
        self.sock = sock
        self.endpoint = f"{address[0]}:{address[1]}"
        self.role = None
        self.active = True
        self.orders = {}
        # Protect outgoing messages and this connection's orders together.
        self.lock = threading.RLock()


def parse_items(arguments):
    if not arguments or len(arguments) % 2:
        raise ValueError("Use product/quantity pairs, for example: coffee 1 tea 2.")
    items = {}
    for index in range(0, len(arguments), 2):
        name, quantity = arguments[index : index + 2]
        if name not in PREPARATION_TIMES:
            raise ValueError(f"Unknown product: {name[:60]}.")
        try:
            count = int(quantity)
            if count <= 0:
                raise ValueError
        except ValueError:
            raise ValueError(f"Quantity for {name} must be a positive integer.") from None
        items[name] = items.get(name, 0) + count
    return items


def stock_text(stock):
    return " ".join(f"{name}={count}" for name, count in stock.items())


class CoffeeShopServer:
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.stock = {name: random.randint(10, 50) for name in PREPARATION_TIMES}
        self.lock = threading.Lock()
        self.order_queue = queue.Queue()
        self.next_order = 1
        self.provider = None

    def log(self, endpoint, message):
        print(f"[{endpoint}] {message}", flush=True)

    def reply(self, connection, message):
        self.log(connection.endpoint, message)
        if send_message(connection.sock, connection.lock, message):
            return True
        self.log(connection.endpoint, "ERROR: send failed.")
        self.disconnect(connection)
        return False

    def notify_provider(self):
        with self.lock:
            provider = self.provider
            low_stock = {name: count for name, count in self.stock.items() if count < 5}
        if provider:
            for name, count in low_stock.items():
                if not self.reply(provider, f"ALERT {name}={count}"):
                    break

    def place_order(self, connection, items):
        if connection.role != "client":
            raise ValueError("Only clients can order.")
        # Always take the connection lock before the stock lock.
        with connection.lock:
            with self.lock:
                if not connection.active:
                    return
                missing = {
                    name: self.stock[name]
                    for name, count in items.items()
                    if count > self.stock[name]
                }
                if not missing:
                    seconds = sum(PREPARATION_TIMES[name] * count for name, count in items.items())
                    order = Order(self.next_order, items, seconds)
                    self.next_order += 1
                    for name, count in items.items():
                        self.stock[name] -= count
                    connection.orders[order.number] = order
                    self.order_queue.put((connection, order))
            if missing:
                self.reply(connection, f"ERROR Order refused; available: {stock_text(missing)}")
                return
            self.reply(connection, f"ORDER_ACCEPTED {order.number} preparation={order.seconds}s")
        self.notify_provider()

    def deliver(self, connection, items):
        if connection.role != "provider":
            raise ValueError("Only the provider can deliver.")
        with self.lock:
            for name, count in items.items():
                self.stock[name] += count
            stock = self.stock.copy()
        self.reply(connection, f"DELIVERY_ACCEPTED {stock_text(stock)}")

    def worker(self):
        while True:
            task = self.order_queue.get()
            if task is None:
                return
            connection, order = task
            # Waiting on an event lets a disconnect stop preparation immediately.
            # Short intervals also allow quantities too large for one OS timeout.
            remaining = order.seconds
            while remaining > 0:
                interval = min(remaining, 3600)
                if order.cancelled.wait(interval):
                    break
                remaining -= interval
            with connection.lock:
                if order.number not in connection.orders:
                    continue
                if self.reply(connection, f"ORDER_READY {order.number}"):
                    del connection.orders[order.number]

    def disconnect(self, connection):
        with connection.lock:
            if not connection.active:
                return
            connection.active = False
            with self.lock:
                if self.provider is connection:
                    self.provider = None
                for order in connection.orders.values():
                    order.cancelled.set()
                    for name, count in order.items.items():
                        self.stock[name] += count
                    self.log(connection.endpoint, f"ORDER_CANCELLED {order.number}; items returned")
                connection.orders.clear()
            try:
                connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.log(connection.endpoint, "Disconnected")

    def handle_connection(self, connection):
        self.log(connection.endpoint, "Connected")
        reader = LineReader(connection.sock)
        try:
            hello = reader.read_message()
            if hello is None:
                return
            if hello not in ("HELLO client", "HELLO provider"):
                raise ProtocolError("First send HELLO client or HELLO provider.")
            connection.role = hello.split()[1]
            with connection.lock:
                with self.lock:
                    if connection.role == "provider":
                        if self.provider:
                            raise ProtocolError("A provider is already connected.")
                        self.provider = connection
                self.reply(connection, f"WELCOME {connection.role}")
            if connection.role == "provider":
                self.notify_provider()

            while connection.active:
                message = reader.read_message()
                if message is None:
                    break
                try:
                    parts = message.split()
                    command = parts[0].upper() if parts else ""
                    arguments = parts[1:]
                    if command == "ORDER":
                        self.place_order(connection, parse_items(arguments))
                    elif command == "DELIVER":
                        self.deliver(connection, parse_items(arguments))
                    elif command == "MENU" and not arguments:
                        with self.lock:
                            stock = self.stock.copy()
                        self.reply(
                            connection,
                            f"MENU {stock_text(stock)}; seconds per item: {stock_text(PREPARATION_TIMES)}",
                        )
                    elif command == "PING" and not arguments:
                        self.reply(connection, "PONG")
                    elif command == "QUIT" and not arguments:
                        self.reply(connection, "BYE")
                        break
                    else:
                        raise ValueError("Use MENU, ORDER <product> <quantity> ..., "
                                         "DELIVER <product> <quantity> ..., or QUIT.")
                except ValueError as exc:
                    self.reply(connection, f"ERROR {exc}")
        except ProtocolError as exc:
            self.reply(connection, f"ERROR {exc}")
        except socket.timeout:
            self.reply(connection, "ERROR Connection timed out.")
        except OSError as exc:
            if connection.active:
                self.log(connection.endpoint, f"ERROR {exc}")
        finally:
            self.disconnect(connection)
            # Let the receiving thread close its own socket after shutdown wakes it.
            connection.sock.close()

    def start(self):
        worker_count = os.cpu_count() or 1
        for _ in range(worker_count):
            threading.Thread(target=self.worker, daemon=True).start()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            listener.listen()
            self.log("SERVER", f"Port {self.port}; {worker_count} workers; {stock_text(self.stock)}")
            while True:
                sock, address = listener.accept()
                sock.settimeout(CONNECTION_TIMEOUT)
                connection = Connection(sock, address)
                threading.Thread(target=self.handle_connection, args=(connection,), daemon=True).start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TCP coffee shop server")
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    try:
        CoffeeShopServer("0.0.0.0", args.port).start()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    except OSError as exc:
        parser.exit(1, f"Server error: {exc}\n")
