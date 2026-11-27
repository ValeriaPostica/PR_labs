# Lab 3 — A Local Network Chat

An interactive peer-to-peer chat using IPv4 UDP sockets. Each peer runs the same program.

## Run

With Python 3.10 or newer, set up the environment on each computer from the repository root.

```bash
cd Lab3
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, use `py -m venv .venv` to create the environment, then run the install and chat commands with `.\.venv\Scripts\python.exe` in place of `python`.

Run each peer in its own terminal in `Lab3` using the virtual environment's Python. For the defense, run Ana and Ion on the first computer and Maria on the second. Use the same network, port, and passphrase for all three peers. A phone hotspot can help if the Wi-Fi blocks multicast.

```bash
python chat.py Ana   5000 'lab-demo-passphrase'
python chat.py Ion   5000 'lab-demo-passphrase'
python chat.py Maria 5000 'lab-demo-passphrase'
```

If UDP multicast is filtered but the network passes broadcasts, add `--broadcast`
with the subnet broadcast address to every peer's command. For example, on a
hotspot using `172.20.10.0/28`:

```bash
python chat.py Ana 5000 'lab-demo-passphrase' --broadcast 172.20.10.15
```

| Input | What it does |
| --- | --- |
| `Hello everyone` | Sends to the general channel |
| `/msg Ion Hello Ion` | Sends an encrypted private message to Ion |
| `/users` | Lists online names, including your own |
| `/quit` | Announces departure and closes both sockets |

Messages can contain up to 500 characters. Each process writes a `chat-<pid>.log` in the current directory. Entries include the time, UDP endpoint, message kind, and datagram size in bytes.

## How it works

`chat.py` handles the sockets, online list, and commands. `protocol.py` handles packet encoding, validation, and encryption.

| Socket | Role |
| --- | --- |
| Shared port on `0.0.0.0` | Receives the discovery and general-channel datagrams sent to `239.255.42.99` or the configured subnet broadcast address. |
| OS-assigned port on `0.0.0.0` | Sends every datagram and receives direct discovery replies and private messages. Peers learn this endpoint from the sender address returned by `recvfrom`. |

A new peer sends a discovery probe to the LAN and listens for direct replies for one second before announcing itself. An existing peer keeps its name. If two peers claim the same name during discovery, the smaller session ID wins. Each peer announces its presence every five seconds. A goodbye removes it immediately upon receipt, and fifteen seconds of silence removes a peer whose goodbye did not arrive.

The passphrase and chat port are used to derive a shared key with PBKDF2-HMAC-SHA256. Each private message uses AES-GCM with a fresh random nonce. The recipient checks the authentication tag before displaying the message. General messages remain readable on the network.

## Defense demo

1. Send a general message from Ana. It should appear once in all three terminals.
2. Run `/users` and try starting a fourth peer called `Ana`. The duplicate should exit.
3. Send `/msg Ion Hello Ion` from Ana. Ion should be the only peer to display it, even though Ana and Ion share a computer. Sending to an unknown name should show an error.
4. Have Ion run `/quit` and check that the others see him leave. Restart Ion, then terminate the process without `/quit` and wait up to 15 seconds after his last datagram to see him disappear.
5. Inspect the logs for sends and receives. Try a peer with a different passphrase and send it a private message. Its log should show a `DROP` for that packet.

Send the repository link to the teacher before the defense.
