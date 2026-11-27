# Lab 2: A Coffee Shop Server

Python 3.10+ and the standard library only. Implements Tasks 1–4 using TCP sockets directly.

For a complete two-device setup and defense walkthrough, see [LAN_GUIDE.md](LAN_GUIDE.md).

## Run

From the repository root, run `cd Lab2` in each terminal.

```bash
python3 server.py 5000
python3 client.py 127.0.0.1 5000
python3 client.py 127.0.0.1 5000 provider
```

Run each command in its own terminal. Open more client terminals as needed.
For another computer on the same network, replace `127.0.0.1` with the server's LAN IP.

Client commands:

```text
menu
order coffee 1 tea 1 croissant 2
quit
```

Provider commands:

```text
menu
deliver coffee 20 croissant 10
quit
```

Quantities are positive integers. Product names are lowercase. The example order
above takes 11 seconds. Clients can ask for the menu or order again while waiting.
Press Ctrl+C to stop a program. Closing a client cancels its unfinished orders.

## How it works

| File | Purpose |
| --- | --- |
| `server.py` | Stock, client/provider connections, FIFO queue and workers |
| `client.py` | One interactive console for either role |
| `protocol.py` | Text message framing, preparation times and timeouts |
| `test_server.py` | Checks for the required behavior |

Stock starts with 10–50 of each product. Preparation takes 4 seconds per coffee,
3 per tea and 2 per croissant. The server starts one worker per logical processor;
each worker prepares a whole order. Busy workers leave new orders in the FIFO queue.

The server's lock protects stock, the order counter and the provider connection.
Each connection's lock protects its outgoing messages and unfinished orders. When
both locks are needed, the connection lock comes first. Network sends happen
outside the stock lock. The connection lock is reentrant because sending and
failed-send cleanup can reuse it.

Accepted orders reserve stock immediately and get a number and preparation time.
A worker sends readiness later. Refused orders show the available quantities.
Stock below 5 triggers an unsolicited provider alert; a provider joining while
stock is low receives the current alerts. Only the provider can deliver.

Disconnect cleanup cancels queued/running orders and refunds all their products.
Workers wake immediately on cancellation. Completed orders stay consumed, and
future orders always wait their full preparation time. The server logs connections,
orders, deliveries and errors with the peer's endpoint.

## Messages and failures

The protocol is plain UTF-8 text, one message per line, up to 4096 bytes before
the newline. `LineReader` buffers partial messages and retains extra messages
between reads. The console automatically starts with `HELLO client` or
`HELLO provider`. Replies start with `WELCOME`, `MENU`, `ORDER_ACCEPTED`,
`ORDER_READY`, `DELIVERY_ACCEPTED`, `ALERT`, `ERROR`, `PONG` or `BYE`.

Bad commands and parameters get an error; the connection stays open. Invalid
UTF-8, oversized lines, incomplete messages and invalid handshakes get an error
and close that connection. Other clients continue normally.

The keyboard runs in a daemon thread while the main thread receives messages.
A heartbeat thread sends `PING` every 15 seconds. The console handles the server's
`PONG` reply silently.
Socket operations time out after 30 seconds, allowing silent network failures to
be detected. EOF or a reset usually reveals a closed/killed peer immediately.
Consoles exit on server disconnection without waiting for keyboard input.

## Check and defend

```bash
python3 test_server.py
```

These checks use local socket pairs and two workers. They cover the server's
handlers, framing, stock races, FIFO orders, cancellation, provider alerts and
failures. Verify actual TCP startup and both interactive consoles using the run
commands above.

For the required live demo, open more clients than the worker count printed by
the server. Have the provider deliver enough coffee, then place long orders in
each client (for example, `order coffee 15`, taking 60 seconds). Observe that some
orders wait until a worker becomes free.

Send this Git repository's link to the teacher before the defense. Tasks 1–4 cover
the coding requirements through grade 8; higher grades also require control answers.
Optional bonus features such as stock persistence and a second language are omitted.

## Control answers

1. **Sockets:** one listening socket accepts connections. Five clients and a
   provider add six separate connected sockets.
2. **TCP messages:** TCP carries bytes, not messages. Newline framing and the
   receive buffer handle split and combined messages.
3. **EOF/reset:** empty `recv()` means the peer closed its sending side; a reset
   raises a socket error. Both lead to cancellation and cleanup.
4. **Producer–consumer:** connection threads add orders to the queue; workers take
   and prepare them. FIFO applies to queue removal, not completion order.
5. **Waiting threads:** blocked receives use little CPU, but every client still
   needs a thread and socket. Thousands of clients would favor nonblocking I/O.
6. **Race:** without the stock lock, two clients could both see the last croissant
   and reserve it. The same lock protects checking, subtracting, delivering and
   refunding, so these changes cannot overwrite one another.
7. **Connection identity:** source IP/port plus destination IP/port. Clients on the
   same computer use different source ports to share one server port.
