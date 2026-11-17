import json
import os
import queue
import random
import socket
import sys
import threading
import time
from datetime import datetime

from protocol import PRODUCTS, LineReader, ProtocolError, send_msg

STOCK_FILE = "stock_state.json"
LOW_STOCK_THRESHOLD = 5
CLIENT_IDLE_TIMEOUT = 120.0  # Detects silent network drops (half-open TCP)


class ClientContext:
    def __init__(self, sock: socket.socket, addr: tuple[str, int]):
        self.sock = sock
        self.addr_str = f"{addr[0]}:{addr[1]}"
        self.send_lock = threading.Lock()
        self.role: str | None = None
        self.connected = True
        self.active_orders: dict[int, dict] = {}
        self.orders_lock = threading.Lock()


class CoffeeShopServer:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.running = True

        self.stock_lock = threading.Lock()
        self.stock: dict[str, int] = self._load_or_init_stock()

        self.order_seq_lock = threading.Lock()
        self.next_order_id = 1

        self.order_queue: queue.Queue = queue.Queue()

        self.provider_lock = threading.Lock()
        self.provider_ctx: ClientContext | None = None
        self.pending_alerts: dict[str, int] = {}

        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def log(self, endpoint: str, message: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [{endpoint}] {message}", flush=True)

    # --- Bonus 2: Stock Persistence ---
    def _load_or_init_stock(self) -> dict[str, int]:
        if os.path.exists(STOCK_FILE):
            try:
                with open(STOCK_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if all(k in data and isinstance(data[k], int) and data[k] >= 0 for k in PRODUCTS):
                    self.log("SERVER", f"Loaded persisted stock from {STOCK_FILE}: {data}")
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        initial = {item: random.randint(10, 50) for item in PRODUCTS}
        self._save_stock_unlocked(initial)
        self.log("SERVER", f"Initialized random stock: {initial}")
        return initial

    def _save_stock_unlocked(self, stock_snapshot: dict[str, int]):
        try:
            with open(STOCK_FILE, "w", encoding="utf-8") as f:
                json.dump(stock_snapshot, f, indent=2)
        except OSError as exc:
            self.log("SERVER", f"Warning: could not persist stock: {exc}")

    # --- Low-Stock Alerting (Task 3) ---
    def _notify_low_stock(self, product: str, remaining: int):
        alert_msg = {
            "type": "ALERT",
            "product": product,
            "remaining": remaining,
            "msg": f"LOW STOCK ALERT: '{product}' has fallen to {remaining} units!",
        }
        with self.provider_lock:
            if self.provider_ctx and self.provider_ctx.connected:
                sent = send_msg(self.provider_ctx.sock, self.provider_ctx.send_lock, alert_msg)
                if sent:
                    self.log(self.provider_ctx.addr_str, f"Sent low-stock alert for {product} ({remaining} left)")
                    return
            # Provider offline: store latest count to deliver upon connection
            self.pending_alerts[product] = remaining

    def _flush_pending_alerts(self, ctx: ClientContext):
        with self.provider_lock:
            if not self.pending_alerts:
                return
            alerts_to_send = list(self.pending_alerts.items())
            self.pending_alerts.clear()

        for product, remaining in alerts_to_send:
            alert_msg = {
                "type": "ALERT",
                "product": product,
                "remaining": remaining,
                "msg": f"LOW STOCK ALERT (queued): '{product}' is at {remaining} units!",
            }
            send_msg(ctx.sock, ctx.send_lock, alert_msg)
            self.log(ctx.addr_str, f"Flushed queued low-stock alert for {product} ({remaining} left)")

    # --- Worker Pool (Task 2 & Task 4) ---
    def _worker_loop(self, worker_id: int):
        while self.running:
            try:
                task = self.order_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            order_id, ctx, items, prep_time, cancel_event = task

            if cancel_event.is_set() or not ctx.connected:
                self.log(ctx.addr_str, f"Worker-{worker_id} skipped already-cancelled Order #{order_id}")
                self.order_queue.task_done()
                continue

            self.log(ctx.addr_str, f"Worker-{worker_id} started preparing Order #{order_id} ({prep_time}s)")

            # Sleep in small intervals so client disconnect aborts preparation immediately
            elapsed = 0.0
            step = 0.1
            aborted = False
            while elapsed < prep_time:
                if cancel_event.is_set() or not ctx.connected:
                    aborted = True
                    break
                time.sleep(min(step, prep_time - elapsed))
                elapsed += step

            if aborted:
                self.log(ctx.addr_str, f"Worker-{worker_id} aborted Order #{order_id} (client disconnected)")
                self.order_queue.task_done()
                continue

            # Atomically verify order wasn't cancelled at the final millisecond
            with ctx.orders_lock:
                if order_id not in ctx.active_orders or cancel_event.is_set():
                    self.log(ctx.addr_str, f"Worker-{worker_id} discarded Order #{order_id} upon completion")
                    self.order_queue.task_done()
                    continue
                del ctx.active_orders[order_id]

            self.log(ctx.addr_str, f"Order #{order_id} READY (prepared by Worker-{worker_id})")
            send_msg(
                ctx.sock,
                ctx.send_lock,
                {
                    "type": "ORDER_READY",
                    "order_id": order_id,
                    "msg": f"Order #{order_id} is ready! Enjoy your order.",
                },
            )
            self.order_queue.task_done()

    # --- Order & Delivery Handlers ---
    def _handle_order(self, ctx: ClientContext, msg: dict):
        if ctx.role != "client":
            self.log(ctx.addr_str, "Error: non-client attempted to place an order")
            send_msg(ctx.sock, ctx.send_lock, {"type": "ERROR", "msg": "Only clients can place orders."})
            return

        items = msg.get("items")
        if not isinstance(items, dict) or not items:
            self.log(ctx.addr_str, "Error: invalid or empty order items")
            send_msg(ctx.sock, ctx.send_lock, {"type": "ERROR", "msg": "Order must specify a non-empty dictionary of items."})
            return

        # Validate product names and positive integer quantities
        clean_items: dict[str, int] = {}
        for prod, qty in items.items():
            if prod not in PRODUCTS:
                self.log(ctx.addr_str, f"Error: unknown product '{prod}'")
                send_msg(ctx.sock, ctx.send_lock, {"type": "ERROR", "msg": f"Unknown product: '{prod}'."})
                return
            if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
                self.log(ctx.addr_str, f"Error: invalid quantity '{qty}' for '{prod}'")
                send_msg(ctx.sock, ctx.send_lock, {"type": "ERROR", "msg": f"Quantity for '{prod}' must be a positive integer."})
                return
            clean_items[prod] = qty

        low_stock_triggers: list[tuple[str, int]] = []

        # Critical Section: Check and deduct stock atomically
        with self.stock_lock:
            for prod, qty in clean_items.items():
                available = self.stock[prod]
                if qty > available:
                    self.log(
                        ctx.addr_str,
                        f"Order REFUSED: requested {qty} {prod}, only {available} in stock",
                    )
                    send_msg(
                        ctx.sock,
                        ctx.send_lock,
                        {
                            "type": "ERROR",
                            "msg": f"Order refused: insufficient '{prod}' (requested {qty}, available {available}).",
                        },
                    )
                    return

            for prod, qty in clean_items.items():
                before = self.stock[prod]
                after = before - qty
                self.stock[prod] = after
                if after < LOW_STOCK_THRESHOLD:
                    low_stock_triggers.append((prod, after))

            self._save_stock_unlocked(self.stock)

        with self.order_seq_lock:
            order_id = self.next_order_id
            self.next_order_id += 1

        prep_time = sum(PRODUCTS[prod] * qty for prod, qty in clean_items.items())
        cancel_event = threading.Event()

        with ctx.orders_lock:
            if not ctx.connected:
                # Client disconnected right as stock was reserved; rollback immediately
                with self.stock_lock:
                    for prod, qty in clean_items.items():
                        self.stock[prod] += qty
                    self._save_stock_unlocked(self.stock)
                return
            ctx.active_orders[order_id] = {
                "items": clean_items,
                "cancel_event": cancel_event,
            }

        self.log(ctx.addr_str, f"Order #{order_id} ACCEPTED: {clean_items} (prep time: {prep_time}s)")
        send_msg(
            ctx.sock,
            ctx.send_lock,
            {
                "type": "ORDER_ACCEPTED",
                "order_id": order_id,
                "prep_time": prep_time,
                "msg": f"Order #{order_id} accepted! Estimated preparation time: {prep_time}s.",
            },
        )

        self.order_queue.put((order_id, ctx, clean_items, prep_time, cancel_event))

        for prod, remaining in low_stock_triggers:
            self._notify_low_stock(prod, remaining)

    def _handle_deliver(self, ctx: ClientContext, msg: dict):
        if ctx.role != "provider":
            self.log(ctx.addr_str, "Error: non-provider attempted a delivery")
            send_msg(ctx.sock, ctx.send_lock, {"type": "ERROR", "msg": "Unauthorized: only the provider can deliver stock."})
            return

        items = msg.get("items")
        if not isinstance(items, dict) or not items:
            self.log(ctx.addr_str, "Error: invalid delivery payload")
            send_msg(ctx.sock, ctx.send_lock, {"type": "ERROR", "msg": "Delivery must specify a non-empty dictionary of items."})
            return

        clean_items: dict[str, int] = {}
        for prod, qty in items.items():
            if prod not in PRODUCTS:
                self.log(ctx.addr_str, f"Error: unknown product '{prod}' in delivery")
                send_msg(ctx.sock, ctx.send_lock, {"type": "ERROR", "msg": f"Unknown product: '{prod}'."})
                return
            if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
                self.log(ctx.addr_str, f"Error: invalid delivery quantity '{qty}' for '{prod}'")
                send_msg(ctx.sock, ctx.send_lock, {"type": "ERROR", "msg": f"Quantity for '{prod}' must be a positive integer."})
                return
            clean_items[prod] = qty

        with self.stock_lock:
            for prod, qty in clean_items.items():
                self.stock[prod] += qty
            current_stock = dict(self.stock)
            self._save_stock_unlocked(self.stock)

        # Clear pending alerts for products replenished to >= 5
        with self.provider_lock:
            for prod, count in current_stock.items():
                if count >= LOW_STOCK_THRESHOLD:
                    self.pending_alerts.pop(prod, None)

        self.log(ctx.addr_str, f"DELIVERY received: {clean_items}. Updated stock: {current_stock}")
        send_msg(
            ctx.sock,
            ctx.send_lock,
            {
                "type": "OK",
                "msg": f"Delivery accepted. Current stock: {current_stock}",
            },
        )

    # --- Client Lifecycle & Cleanup (Task 4) ---
    def _cleanup_connection(self, ctx: ClientContext):
        ctx.connected = False

        if ctx.role == "provider":
            with self.provider_lock:
                if self.provider_ctx is ctx:
                    self.provider_ctx = None
            self.log(ctx.addr_str, "Provider disconnected. Shop continues with existing stock.")

        # Cancel all pending/in-progress orders and return items to stock
        with ctx.orders_lock:
            orders_to_cancel = list(ctx.active_orders.items())
            ctx.active_orders.clear()

        if orders_to_cancel:
            restored_totals: dict[str, int] = {}
            for order_id, order_info in orders_to_cancel:
                order_info["cancel_event"].set()
                for prod, qty in order_info["items"].items():
                    restored_totals[prod] = restored_totals.get(prod, 0) + qty
                self.log(ctx.addr_str, f"Cancelled Order #{order_id} due to client disconnect")

            with self.stock_lock:
                for prod, qty in restored_totals.items():
                    self.stock[prod] += qty
                self._save_stock_unlocked(self.stock)
            self.log(ctx.addr_str, f"Returned items to stock: {restored_totals}")

        try:
            ctx.sock.close()
        except OSError:
            pass
        self.log(ctx.addr_str, "Connection closed")

    def _client_thread(self, sock: socket.socket, addr: tuple[str, int]):
        ctx = ClientContext(sock, addr)
        sock.settimeout(CLIENT_IDLE_TIMEOUT)
        reader = LineReader(sock)
        self.log(ctx.addr_str, "New connection established")

        try:
            # First message must be HELLO handshake identifying role
            first_msg = reader.read_message()
            if first_msg is None:
                return
            if first_msg.get("cmd") != "HELLO" or first_msg.get("role") not in ("client", "provider"):
                self.log(ctx.addr_str, f"Error: invalid handshake {first_msg}")
                send_msg(sock, ctx.send_lock, {"type": "ERROR", "msg": "First command must be HELLO with role 'client' or 'provider'."})
                return

            role = first_msg["role"]
            if role == "provider":
                with self.provider_lock:
                    if self.provider_ctx is not None and self.provider_ctx.connected:
                        self.log(ctx.addr_str, "Error: duplicate provider rejected")
                        send_msg(sock, ctx.send_lock, {"type": "ERROR", "msg": "A provider is already connected."})
                        return
                    ctx.role = "provider"
                    self.provider_ctx = ctx
                self.log(ctx.addr_str, "Registered as PROVIDER")
                send_msg(sock, ctx.send_lock, {"type": "WELCOME", "msg": "Connected as PROVIDER."})
                self._flush_pending_alerts(ctx)
            else:
                ctx.role = "client"
                self.log(ctx.addr_str, "Registered as CLIENT")
                send_msg(sock, ctx.send_lock, {"type": "WELCOME", "msg": "Connected as CLIENT."})

            # Main command loop
            while self.running:
                msg = reader.read_message()
                if msg is None:
                    break

                cmd = msg.get("cmd")
                if cmd == "MENU":
                    with self.stock_lock:
                        stock_copy = dict(self.stock)
                    send_msg(
                        sock,
                        ctx.send_lock,
                        {
                            "type": "MENU",
                            "stock": stock_copy,
                            "prep_times": PRODUCTS,
                        },
                    )
                elif cmd == "ORDER":
                    self._handle_order(ctx, msg)
                elif cmd == "DELIVER":
                    self._handle_deliver(ctx, msg)
                elif cmd == "QUIT":
                    send_msg(sock, ctx.send_lock, {"type": "OK", "msg": "Goodbye!"})
                    break
                else:
                    self.log(ctx.addr_str, f"Error: unknown command '{cmd}'")
                    send_msg(sock, ctx.send_lock, {"type": "ERROR", "msg": f"Unknown command: '{cmd}'."})

        except ProtocolError as exc:
            self.log(ctx.addr_str, f"Protocol error: {exc}")
            send_msg(sock, ctx.send_lock, {"type": "ERROR", "msg": f"Protocol error: {exc}"})
        except socket.timeout:
            self.log(ctx.addr_str, "Connection timed out (idle/unresponsive peer)")
        except OSError as exc:
            self.log(ctx.addr_str, f"Socket error: {exc}")
        finally:
            self._cleanup_connection(ctx)

    def start(self):
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(64)
        self.server_sock.settimeout(1.0)

        num_workers = os.cpu_count() or 4
        for i in range(1, num_workers + 1):
            t = threading.Thread(target=self._worker_loop, args=(i,), daemon=True)
            t.start()

        self.log("SERVER", f"Listening on {self.host}:{self.port} with {num_workers} worker threads")

        try:
            while self.running:
                try:
                    client_sock, addr = self.server_sock.accept()
                except socket.timeout:
                    continue
                t = threading.Thread(target=self._client_thread, args=(client_sock, addr), daemon=True)
                t.start()
        except KeyboardInterrupt:
            self.log("SERVER", "Shutting down...")
        finally:
            self.running = False
            self.server_sock.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python server.py <port> [bind_host]")
        sys.exit(1)

    bind_port = int(sys.argv[1])
    # Default 0.0.0.0 allows connections from other machines on the same LAN (Bonus 1)
    bind_host = sys.argv[2] if len(sys.argv) >= 3 else "0.0.0.0"

    server = CoffeeShopServer(bind_host, bind_port)
    server.start()