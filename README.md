# NDS Pokémon Mystery Gift Server

A self-hosted server that distributes Pokémon Mystery Gift events to a real Nintendo DS over Wi-Fi — no ROM patches required.

Works by exploiting **nds-constrain't**, a bug in the Nintendo DS SSL library that allows any Nintendo-signed certificate to act as a certificate authority. Combined with custom DNS, this lets a local machine fully impersonate Nintendo's Wi-Fi Connection servers.

**Currently supported:** Generation 4 games (Diamond, Pearl, Platinum, HeartGold, SoulSilver) on original DS/DS Lite/DSi/3DS hardware.

---

## How it works

When you trigger Mystery Gift on your DS, the game:

1. Checks internet connectivity via `conntest.nintendowifi.net`
2. Authenticates with Nintendo's server at `nas.nintendowifi.net`
3. Asks for the download server location (`dls1.nintendowifi.net`)
4. Downloads the gift in three steps: `count` → `list` → `contents`

This server handles all four steps locally. Custom DNS redirects all Nintendo domains to your machine, and a patched SSL library accepts the DS's ancient SSLv3/RC4 connection.

---

## Requirements

### Hardware

**A computer** running Docker. Tested on macOS; should work on Linux. Windows with WSL2 should work but is untested.

**A Wi-Fi access point with WEP security or no security.** This is the biggest hurdle — Gen 4 games only support WEP and open (unsecured) networks. WPA/WPA2 will not work with the original DS, DS Lite, or Gen 4 games on DSi/3DS.

Your options:

- **Android phone hotspot** (recommended): Most Android phones can create an open (no password) hotspot. Enable it, set it to 2.4 GHz, and optionally hide the SSID.
- **Router in AP mode with WEP or open security**: Dedicated access point configured for open or WEP. Keep this network isolated — WEP is insecure.
- **macOS Internet Sharing**: Share your ethernet/other Wi-Fi connection via a new Wi-Fi hotspot. Set security to "None" in Wireless Options. Note that macOS may not allow open hotspots on all versions.
- **Existing router with guest network**: Some routers allow a guest network with no security — check your router settings.

> **Note:** The computer running the server and the DS must be on the **same local network** — i.e., reachable at the same subnet. For example, if your router is at `192.168.x.1`, your computer might be `192.168.x.10` and your DS `192.168.x.20`. They just need to be able to reach each other.

**Your Nintendo DS** (original DS, DS Lite, DSi, or 3DS) with a Gen 4 cartridge that has Mystery Gift unlocked.

> To unlock Mystery Gift in Diamond/Pearl/Platinum: speak to the TV producer on the 3rd floor of Jubilife TV and enter "EVERYONE HAPPY" then "WI-FI CONNECTION". In HeartGold/SoulSilver it unlocks automatically after receiving the Pokédex.

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- The **Wii NWC Prod 1 certificate** (`WII_NWC_1_CERT.p12`, password: `alpine`) — included in this repository under `certs/`
- OpenSSL (usually pre-installed on macOS/Linux)

---

## Project structure

```
nds-server/
├── certs/                    # TLS certificates (see Certificate Setup)
│   ├── WII_NWC_1_CERT.p12    # Wii client cert — source for the exploit
│   ├── NWC.crt               # Extracted Wii cert (intermediate CA)
│   ├── NWC.key               # Extracted Wii private key
│   ├── NWC.srl               # OpenSSL serial file
│   ├── server.csr            # Certificate signing request
│   ├── server.crt            # Signed server certificate
│   └── server-chain.crt      # server.crt + NWC.crt (used by stunnel)
│   └── server.key            # Server private key (used by stunnel)
├── dns/                      # Custom DNS server
│   ├── dns_server.py         # Python DNS — redirects Nintendo domains
│   └── Dockerfile
├── nginx/                    # SSL termination (stunnel)
│   ├── Dockerfile            # Builds custom OpenSSL + stunnel
│   └── conf/
│       ├── stunnel.conf
│       └── entrypoint.sh
├── server/                   # Flask event server
│   ├── app.py                # NAS auth + DLS1 download protocol
│   ├── Dockerfile
│   ├── requirements.txt
│   └── events/
│       ├── gen4/             # Place .myg files here for Gen 4
│       └── gen5/             # Place .pgf files here for Gen 5
├── docker-compose.yml
└── start.sh                  # Auto-detects your LAN IP and launches
```

---

## Certificate setup

> **The certificates are already included in `certs/` and work out of the box. You do not need to run any of the commands below.** This section is only relevant if you need to regenerate them from scratch — for example if you want to use a different Wii NWC certificate.

<details>
<summary>How to regenerate the certificates</summary>

The nds-constrain't exploit works because the DS doesn't check whether an intermediate certificate is allowed to sign other certificates. The Wii's client certificate is signed by Nintendo's CA, and the DS trusts Nintendo's CA — so we use the Wii cert to sign our own server certificate.

**Step 1: Extract the Wii certificate and key from the p12**

```bash
cd certs/
openssl pkcs12 -in WII_NWC_1_CERT.p12 \
  -passin pass:alpine -passout pass:alpine \
  -out keys.txt
# Copy the certificate block into NWC.crt
# Copy the private key block into NWC.key
```

**Step 2: Generate a server key and certificate signing request**

```bash
# 1024-bit RSA key (weak, but required — the DS can't handle larger)
openssl genrsa -out server.key 1024

# CN=*.*.* makes the cert valid for all Nintendo subdomains
openssl req -new -key server.key -out server.csr \
  -subj "/CN=*.*.*"
```

**Step 3: Sign the server certificate with the Wii cert**

```bash
# Must use SHA-1 — the DS doesn't support SHA-256
openssl x509 -req \
  -in server.csr \
  -CA NWC.crt -CAkey NWC.key \
  -CAcreateserial \
  -out server.crt \
  -days 3650 \
  -sha1
```

**Step 4: Build the certificate chain**

stunnel needs to present both the server cert and the Wii intermediate cert so the DS can verify the chain of trust back to Nintendo's root CA.

```bash
cat server.crt NWC.crt > server-chain.crt
```

</details>

---

## Event files

The server distributes `.myg` files (Gen 4) and `.pgf` files (Gen 5). These are the original Nintendo WiFi distribution format — different from the `.pgt`/`.pcd` pairs commonly found in preservation archives (those are save-file injection formats).

Place your event files in:
- `server/events/gen4/` — `.myg` files for Diamond, Pearl, Platinum, HeartGold, SoulSilver
- `server/events/gen5/` — `.pgf` files for Black, White, Black 2, White 2

The server picks a random file from the folder each time the DS requests a gift.

### The `_list.txt` file

Each game code folder in the [DLS1-Files repository](https://github.com/InternalLoss/DLS1-Files) contains a `_list.txt` file. This file is **not used by this server** — it was used by the original AltWFC server to map dates to specific gifts. You can ignore it or keep it in the folder; the server will skip it automatically since it only serves `.myg` and `.pgf` files.

For reference, the format of `_list.txt` entries is tab-separated:

```
filename.myg					936
```

Where `936` is the file size in bytes. This is also the exact format returned by the server's `list` action to the DS — one tab-separated line per gift offering.

### Where to find event files

- [InternalLoss/DLS1-Files](https://github.com/InternalLoss/DLS1-Files) — the best source of `.myg` files, organised by 4-letter game code (e.g. `IPGE` = SoulSilver English, `CPUE` = Platinum English). These are the exact files Wiimmfi serves.
- [projectpokemon/EventsGallery](https://github.com/projectpokemon/EventsGallery) — large archive of `.pcd`/`.pgt` pairs. Use [MysteryGiftConvert](https://github.com/AdmiralCurtiss/MysteryGiftConvert) to convert `.pcd` → `.myg` before use.

> **Important:** Download the files from the folder matching your game code. The server automatically identifies your game from the code the DS sends in each request, and serves files from the corresponding `gen4/` or `gen5/` folder. All `.myg` files in the folder are available regardless of game code — it is your responsibility to put only compatible files in.

---

## Running the server

**Step 1: Clone the repository**

```bash
git clone https://github.com/yourusername/nds-server.git
cd nds-server
```

**Step 2: Add event files**

Copy your `.myg` files into `server/events/gen4/`. At least one file is required.

**Step 3: Connect your computer to the same network as your DS**

Your computer and DS must be on the same subnet. Connect your computer to the same Wi-Fi access point the DS will use, or connect via ethernet to the same router.

**Step 4: Start the server**

```bash
chmod +x start.sh
./start.sh
```

`start.sh` automatically detects your local IP address and launches all three containers (DNS, SSL terminator, event server).

You should see output like:

```
Detected server IP: 192.168.x.10
Starting Docker stack...
...
nds-nginx         | event-server resolved, starting stunnel
nds-event-server  | Serving on port 8080 with HTTP/1.0
```

Leave this running while you use the DS.

**Step 5: Configure your DS**

On your DS, connect to your open/WEP Wi-Fi access point and set the DNS manually:

- **Primary DNS:** your computer's IP (shown at startup by `start.sh`, e.g. `192.168.x.10`)
- **Secondary DNS:** same IP, or leave blank

For Gen 4 games, DNS is configured through the in-game Nintendo WFC Settings menu (not system settings). Access it from the main menu after the title screen.

> **DSi/3DS users:** For Gen 4 games, use connection slots 1–3 via the in-game menu or via System Settings → Internet → Nintendo DS Connections. Do NOT use the normal system connection settings for Gen 4 games.

Test the connection — it should succeed.

**Step 6: Receive a Mystery Gift**

On the DS main menu, select **Mystery Gift → Receive Gift → Via Nintendo WFC**. The game will connect to your server, and after a few seconds will offer you a gift to download.

If multiple `.myg` files are present, one is chosen at random each time. You can repeat the process to get different gifts (you cannot receive the same gift twice on the same save).

---

## Troubleshooting

**"No gift was found"**
No `.myg` files found in `server/events/gen4/`. Make sure files are in the correct folder and have the `.myg` extension.

**"A gift was found, but it cannot be received with this version"**
The `.myg` file is not compatible with your game version. Download the file for your specific game code from the DLS1-Files repository.

**Connection test fails on DS**
- Confirm your computer's IP matches the DNS you entered
- Confirm the server is running (`docker ps` should show three containers)
- Confirm your DS is on the same Wi-Fi network as your computer
- Confirm the access point uses WEP or no security (not WPA/WPA2) for Gen 4 games

**Error code 20110**
The DS reached Nintendo's real servers instead of yours — the DNS isn't pointing to your machine. Double-check the DNS settings in-game.

**Error code 31020**
The DS reached your server but the HTTP exchange failed. Check Docker logs: `docker compose logs nds-event-server`.

**"A communication error has occurred" (no error code)**
Usually means the DS received an HTTP/1.1 response instead of HTTP/1.0. Make sure the server is running via `start.sh` and not a modified configuration.

---

## Stopping the server

```bash
docker compose down
```

Reset your DS DNS settings back to automatic when done.

---

## Technical background

- **nds-constrain't** — the SSL exploit that makes this possible. Discovered by shutterbug2000. [Original writeup](https://www.github.com) | [flewkey's blog post](https://flewkey.com/blog/2020-07-12-nds-constraint.html)
- **DLS1 protocol** — Nintendo's HTTP-based download protocol. Uses Nintendo base64 encoding and a three-step count/list/contents flow.
- **MYG format** — 936-byte WiFi distribution format. A 856-byte PCD wonder card with an 80-byte distribution header prepended.
- **Custom OpenSSL** — SSLv3 and RC4 ciphers are re-enabled via source patches, since modern OpenSSL removes them for security reasons.

---

## Acknowledgements

- **shutterbug2000** for discovering nds-constrain't
- **flewkey**, **Lauren Kelly**, and **jaames** for documenting the exploit
- **Wiimmfi / Poke** for the DLS1 server implementation and event file collection
- **InternalLoss** for the DLS1-Files repository
- **ProjectPokemon** community for event preservation

## License

GPL-3.0 (see `LICENSE`). If you share a modified version, its source must stay open under the same licence.
