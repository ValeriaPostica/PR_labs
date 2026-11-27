# Lab 2: run and demonstrate the coffee shop on two devices

Use one computer as the server and the second computer as a remote customer.
The provider can run in a second terminal on either computer.

This guide uses these example addresses. Replace `192.168.1.20` in every command
with the actual local IPv4 address of the server computer.

| Device / terminal | Program | Address used to connect |
| --- | --- | --- |
| Device A, terminal 1 | Server | Listens on TCP port `5000` |
| Device A, terminal 2 | Provider | `127.0.0.1:5000` |
| Device B, terminal 1 | Client 1 | `192.168.1.20:5000` |
| Device B, terminal 2 | Client 2 | `192.168.1.20:5000` |
| Additional terminals | More clients for the queue demo | The same server and port |

Only Device A runs `server.py`. All clients and the provider share that server's
stock. Extra clients are extra terminal processes; you do not need extra computers.

## 1. Prepare both devices

1. Connect both computers to the same LAN, for example the same home Wi-Fi router.
   A wired connection to that router also works when its LAN permits communication
   with Wi-Fi devices. Guest or university Wi-Fi may isolate devices from one another.
2. Copy the **current `Lab2` folder** from Device A to Device B. If you use Git
   instead, first commit and push the intended version: a fresh clone contains
   only the changes already pushed to the remote repository.
3. Keep `client.py` and `protocol.py` together on Device B. Device A needs
   `server.py`, `client.py` and the matching `protocol.py`.
4. Check that both computers have Python **3.10 or newer**:

   | Operating system | Version command | Prefix for the commands below |
   | --- | --- | --- |
   | macOS / Linux | `python3 --version` | `python3` |
   | Windows | `py -3 --version` | `py -3` |

   If Windows uses `python` instead of `py`, use `python --version` and the
   `python` prefix after confirming its version. The application uses the
   standard library; no packages need to be installed.
5. In **each new terminal**, navigate into its copy of `Lab2`. If you opened the
   terminal in the repository root, run:

   ```bash
   cd Lab2
   ```

All commands below assume that the terminal is already inside `Lab2`.
On Windows, replace `python3` with `py -3` in the examples.

## 2. Find Device A's local IPv4 address

Do this on the computer that will run the server.

**macOS:** open System Settings → Network → the active Wi-Fi/Ethernet connection
→ Details → TCP/IP, and read its IPv4 address. For example: `192.168.1.20`.

**Windows:** run this in PowerShell or Command Prompt:

```powershell
ipconfig
```

Read the IPv4 address under the active Wi-Fi or Ethernet adapter.

**Linux:** run:

```bash
ip -4 addr show
```

Read the `inet` address on the active LAN interface, omitting the `/24` or other
prefix suffix when entering it in client commands.

| Address | Meaning in this lab |
| --- | --- |
| `192.168.1.20` | Example LAN address that Device B uses to reach Device A |
| `127.0.0.1` | The computer on which that particular client program is running |
| `0.0.0.0` | The server's internal bind address: accept connections on all IPv4 interfaces |

The client on Device B needs **Device A's LAN address**. Entering `127.0.0.1`
there attempts to connect to Device B itself. Use the LAN address rather than
the router's address or an Internet/public IP.

## 3. Start the server on Device A

In Device A's first terminal:

```bash
python3 server.py 5000
```

Example output:

```text
[SERVER] Port 5000; 10 workers; coffee=30 tea=20 croissant=15
```

Your worker count depends on Device A's logical processors. Your starting stock
will differ: each product starts with a random quantity between 10 and 50.

Leave this terminal running. It displays the server log; shop commands such as
`menu` are entered in a client/provider terminal.

The server already listens on all IPv4 interfaces. If the OS asks whether Python
may accept incoming connections or access the local network, allow it for this
LAN demonstration. Firewall troubleshooting is covered in section 13.

## 4. Connect a remote client from Device B

In Device B's first terminal:

```bash
python3 client.py 192.168.1.20 5000
```

Windows equivalent:

```powershell
py -3 client.py 192.168.1.20 5000
```

Expected output:

```text
WELCOME client
Commands: menu | order coffee 1 tea 2 | deliver coffee 20 | quit
> 
```

Device A's server log should show Device B's address, for example:

```text
[192.168.1.30:55124] Connected
[192.168.1.30:55124] WELCOME client
```

Here `192.168.1.30` is an example address for Device B. Its source port `55124`
is chosen automatically and usually differs between connections. You only
specify the server's port, `5000`.

Seeing the remote address in the server log and receiving `WELCOME client` on
Device B confirms a real connection between the two computers.

## 5. Connect the provider

In a **second terminal on Device A**:

```bash
python3 client.py 127.0.0.1 5000 provider
```

Expected first reply:

```text
WELCOME provider
```

Alternatively, run the provider in another terminal on Device B:

```bash
python3 client.py 192.168.1.20 5000 provider
```

Choose one location. The implementation permits one provider connection at a
time. A second provider receives `ERROR A provider is already connected.`

Clients and providers send a heartbeat every 15 seconds and handle `PONG` replies
silently. Order updates and stock alerts can appear while you are typing. The
keyboard remains active.

## 6. Demonstrate the menu and an order — Task 1

In the running **client on Device B**, type:

```text
menu
```

For the example starting stock, expect:

```text
MENU coffee=30 tea=20 croissant=15; seconds per item: coffee=4 tea=3 croissant=2
```

Place an order:

```text
order coffee 1 tea 1 croissant 2
```

Expected immediate reply, if this is the server's first accepted order:

```text
ORDER_ACCEPTED 1 preparation=11s
```

Calculation: `1 × 4 + 1 × 3 + 2 × 2 = 11 seconds`.

Before those 11 seconds pass, enter `menu` again. With the example stock, expect:

```text
MENU coffee=29 tea=19 croissant=13; seconds per item: coffee=4 tea=3 croissant=2
```

The products have already been reserved. When preparation finishes:

```text
ORDER_READY 1
```

The ready message appears without another request, even while you are typing.
The preparation time excludes queueing; with a free worker this example takes
about 11 seconds. Subsequent orders have different numbers.

Let this order finish before continuing, so it does not affect the next demos.

### Check refused and invalid orders

In the client, try these commands one at a time:

| Command | Expected result |
| --- | --- |
| `order coffee 999999` | Refusal showing the coffee stock currently available |
| `order latte 1` | `ERROR Unknown product: latte.` |
| `order tea 0` | Error requiring a positive integer |
| `order tea -1` | Error requiring a positive integer |
| `order tea 1.5` | Error requiring a positive integer |
| `order tea` | Error requiring product/quantity pairs |
| `something` | Error listing the supported commands |
| `deliver coffee 20` | `ERROR Only the provider can deliver.` |

These inputs leave stock unchanged and keep the connection open. Check with
`menu` afterward. Product names are lowercase; quantities count whole items.

## 7. Demonstrate delivery and low-stock alerts — Task 3

In the **provider terminal**, enter:

```text
deliver coffee 20 tea 10 croissant 10
```

Continuing the example above, expect:

```text
DELIVERY_ACCEPTED coffee=49 tea=29 croissant=23
```

In the client, `menu` must show the increased quantities immediately.

Now demonstrate an unsolicited alert:

1. Keep other clients idle and check the current coffee stock with `menu`.
2. If it is `N`, order `N - 4` coffees to leave exactly 4. For example, if the
   stock is 49, enter:

   ```text
   order coffee 45
   ```

3. The client immediately receives an acceptance with `preparation=180s`.
4. The provider receives this without sending a request:

   ```text
   ALERT coffee=4
   ```

To show that alerts arrive while typing, start typing `menu` in the provider
without pressing Enter, then place that order in the client. The alert should
appear while the unfinished input is still open.

Replenish coffee from the provider:

```text
deliver coffee 20
```

The example stock rises from 4 to 24 immediately. In the next step, cancel the
long client order before it finishes.

## 8. Demonstrate cancellation and refunds — Task 4

While that long coffee order is still being prepared, press **Ctrl+C in its
client terminal**. Leave the server and provider running.

The server should log messages like:

```text
[192.168.1.30:55124] ORDER_CANCELLED 2; items returned
[192.168.1.30:55124] Disconnected
```

The order number and endpoint will depend on your run.

Open another client terminal on Device B:

```bash
python3 client.py 192.168.1.20 5000
```

Enter `menu`. In the preceding example, coffee should be **69**:

```text
49 before the order - 45 reserved + 20 delivered + 45 refunded = 69
```

This demonstrates that a concurrent delivery is preserved and all cancelled
products return to stock. The worker stops waiting on the cancelled order.

For several unfinished orders belonging to one connection, send several long
orders from that same client, then disconnect it. Every unfinished order must
be logged as cancelled and all its quantities refunded. Completed orders remain
consumed. A future order always waits its full preparation time again.

## 9. Demonstrate an offline provider

1. Ensure earlier unfinished orders are cancelled or completed.
2. In the provider terminal, type `quit`. Expect `BYE` and a return to the shell.
3. In the client, check the current stock and reserve enough coffee to leave 4,
   using the same `N - 4` calculation as before. Keep that client connected.
4. Restart the provider with its original command.
5. It should receive `WELCOME provider`, followed by `ALERT coffee=4`.
6. Cancel the pending client order or replenish stock, then continue.

The server continues serving customers while the provider is disconnected.
The connecting provider is alerted about products that are currently below 5.

## 10. Demonstrate multiple clients and FIFO workers — Task 2

Two physical computers can run any number of client terminal processes.

1. Read the worker count `W` printed by the **server on Device A**.
2. Open at least **W + 1 client terminals**. For example, 10 workers require
   at least 11 clients. Each terminal uses the same remote client command.
   The provider is a separate role and does not count as a customer here.
3. Before ordering, have the provider supply enough coffee for every order.
   For `W + 1` orders of 15 coffees, you need `15 × (W + 1)` coffee in stock.
   For the 10-worker example, this delivery is sufficient:

   ```text
   deliver coffee 200
   ```

4. Open all client connections first. Then, within less than a minute, enter
   this command once in each client:

   ```text
   order coffee 15
   ```

5. Each receives `ORDER_ACCEPTED <number> preparation=60s` immediately.
6. The first `W` orders occupy workers. The remaining order waits in the FIFO
   queue until a worker finishes, then needs its own full 60 seconds.

The waiting order's total delay includes its queue wait. Its ready message will
therefore arrive later than those in the first wave. Completion order can differ
when orders have different preparation times.

You can run some extra clients on Device A using `127.0.0.1` if terminal space is
more convenient there. Keep at least one client on Device B to demonstrate LAN
communication. Use the real worker count; the automated checks simulate only two.

To test queued cancellation, close a client whose order is still waiting before
any worker becomes free. Its products must be refunded and it must never finish.
Closing a client whose order is preparing must also refund its products and free
that worker. Remaining connected clients continue normally.

### Optional stock-race demonstration

When no other orders are changing croissant stock, read its current count `C`.
If it is at least 2, use a separate client to order `C - 1` croissants, leaving 1.
Keep that reservation's client connected. Have two other clients both order
`croissant 1` almost simultaneously. Exactly one gets acceptance; the other is
refused with `croissant=0`. Keep the accepted clients connected until the two
responses arrive. The automated checks also exercise this race concurrently.

## 11. Demonstrate server disappearance

Leave one or more client/provider programs connected. You can leave an unfinished
line in their input prompts to show that no extra Enter key is required.

Press **Ctrl+C in the server terminal on Device A**. Connected programs should
exit with `Server disconnected.` or a connection-error message, depending on how
their socket closes. Their shell prompts return even if keyboard input was open.

A closed process is usually detected through EOF/reset immediately. Turning off
Wi-Fi can instead produce a silent network failure: allow roughly 30 seconds
after the last received data, plus scheduling/OS variation. Heartbeats keep an
idle but connected console alive. Restarting the server chooses new random stock;
restart the clients/provider as well, because they do not reconnect automatically.

## 12. What to show at the defense

| Demonstration | Evidence |
| --- | --- |
| Two-device TCP connection | Device B shows `WELCOME`; Device A logs Device B's LAN IP |
| Menu and one order | Current stock, immediate acceptance, later ready message |
| Input validation | Invalid commands/quantities and insufficient-stock errors |
| Shared stock | Another client's menu reflects reservations and deliveries |
| Provider | Successful delivery and an unsolicited low-stock alert |
| Offline provider | Alert received immediately after reconnection while stock is low |
| Many clients | More clients than workers; later orders wait in FIFO order |
| Failure handling | Running/queued orders cancelled and refunded on client loss |
| Responsive consoles | Messages arrive while typing; server closure ends consoles |

The program uses real preparation delays, so plan time for long-order and queue
demonstrations. Send the repository link to the teacher before the defense and
be ready to explain the code and answer the PDF's questions.

## 13. Troubleshooting

| Symptom | What to check |
| --- | --- |
| `python3` is not found on Windows | Use `py -3`, or the installed Python command after checking its version |
| `client.py` or `protocol.py` is missing | Check the current terminal directory and copy the latest files together |
| Error asking for `HELLO`, or JSON-related output | The two devices may have different code versions; copy the current folder again |
| `Connection refused` | Check that the server is still running and the IP/port match; a firewall can also reject connections |
| Connection times out | Check server LAN IP, firewall, local-network permissions, and whether the network isolates devices |
| `Address already in use` | Another program owns the port; stop your old server or choose a free port such as `5050` everywhere |
| A second provider is rejected | Type `quit` in the first provider before starting a replacement |
| An order is refused unexpectedly | Read `menu`; other clients may have reserved stock, or the server may have restarted |
| Ready takes longer than the displayed preparation time | The order may be waiting for a free worker |

### Test the port from Device B

With the server running, Windows PowerShell can check the actual TCP port:

```powershell
Test-NetConnection -ComputerName 192.168.1.20 -Port 5000
```

Look for `TcpTestSucceeded : True`. A ping result alone does not establish that
the application port is reachable.

On macOS/Linux, use this Python check:

```bash
python3 -c "import socket; s = socket.create_connection(('192.168.1.20', 5000), timeout=5); print('TCP connection successful'); s.close()"
```

The probe creates and closes a connection without placing an order. A corresponding
connect/disconnect pair in the server log is normal. After a successful probe,
run the actual interactive client.

### macOS permissions on the relevant device

- For incoming connections on the server Mac: System Settings → Network →
  Firewall → Options. Allow incoming connections for the Python application
  running the server. Match it to the interpreter you actually launch.
- For local-network access: System Settings → Privacy & Security → Local Network.
  Enable the relevant terminal/app if it is listed and was denied access.

### If Device A runs Windows

If its firewall blocks inbound TCP, an administrator PowerShell terminal can
create a rule limited to the private network and local subnet:

```powershell
New-NetFirewallRule -Name "CoffeeShopLab5000" -DisplayName "Coffee Shop Lab TCP 5000" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5000 -Profile Private -RemoteAddress LocalSubnet
```

This rule applies when the active network profile is Private. Use your own
trusted LAN for the demonstration; a managed network may require administrator
configuration. If you choose another port, update both the rule and every program
command to that port.

If local clients on Device A work but Device B still cannot connect, concentrate
on the LAN IP, the firewall and network isolation. Guest/student Wi-Fi and some
hotspots can prevent device-to-device connections even when both have Internet.

### Official OS references

- [Apple: TCP/IP settings](https://support.apple.com/en-nz/guide/mac-help/mh14129/27/mac/27)
- [Apple: firewall settings](https://support.apple.com/en-mo/guide/mac-help/mh11783/mac)
- [Apple: local-network access](https://support.apple.com/en-gb/guide/mac-help/mchla4f49138/mac)
- [Microsoft: ipconfig](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/ipconfig)
- [Microsoft: Test-NetConnection](https://learn.microsoft.com/powershell/module/nettcpip/test-netconnection)
- [Microsoft: New-NetFirewallRule](https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule)
