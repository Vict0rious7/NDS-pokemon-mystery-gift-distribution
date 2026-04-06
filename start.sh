#!/bin/bash
# start.sh — NDS Pokémon Mystery Gift Server startup helper
#
# 1. Auto-detects your LAN IP address (macOS and Linux)
# 2. Prints DS configuration instructions
# 3. Validates prerequisites (Docker, certs, event files)
# 4. Launches the Docker stack with SERVER_IP exported

set -e

# ---------------------------------------------------------------------------
# Detect LAN IP
# Works by finding the interface used for the default route.
# ---------------------------------------------------------------------------
detect_lan_ip() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        INTERFACE=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
        ipconfig getifaddr "$INTERFACE" 2>/dev/null
    else
        # Linux
        INTERFACE=$(ip route show default 2>/dev/null | awk '/default/{print $5}' | head -1)
        ip -4 addr show "$INTERFACE" 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | head -1
    fi
}

LAN_IP=$(detect_lan_ip)

# ---------------------------------------------------------------------------
# Print setup instructions
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  NDS Pokémon Mystery Gift Server"
echo "============================================================"
echo ""

if [ -z "$LAN_IP" ]; then
    echo "  WARNING: Could not auto-detect your LAN IP."
    echo "  Find it manually (e.g. System Settings → Wi-Fi → Details on macOS,"
    echo "  or run: ip addr | grep 'inet ')"
    echo "  Then set that IP as the DNS server on your DS."
else
    echo "  Your server IP: $LAN_IP"
    echo ""
    echo "  Configure your DS:"
    echo "  ─────────────────────────────────────────────────────────"
    echo "  1. Connect your DS to an open or WEP Wi-Fi network"
    echo "     that is on the same subnet as this machine."
    echo "     (Gen 4: WEP or open only — WPA/WPA2 not supported)"
    echo "     (Gen 5 on DSi/3DS: WPA2 works fine)"
    echo ""
    echo "  2. In the Nintendo WFC connection settings, set:"
    echo "       Primary DNS:   $LAN_IP"
    echo "       Secondary DNS: $LAN_IP"
    echo ""
    echo "  3. Open Mystery Gift → Receive via Nintendo WFC."
    echo ""
    echo "  ─────────────────────────────────────────────────────────"
    echo "  Health check (after startup):"
    echo "  http://localhost:8080/health"
    echo "============================================================"
    echo ""
fi

# ---------------------------------------------------------------------------
# Check Docker is running
# ---------------------------------------------------------------------------
if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker is not running. Start Docker Desktop and try again."
    exit 1
fi

# ---------------------------------------------------------------------------
# Check required certificates are present
# ---------------------------------------------------------------------------
MISSING_CERTS=0
for f in certs/server-chain.crt certs/server.key; do
    if [ ! -f "$f" ]; then
        echo "ERROR: Missing certificate file: $f"
        MISSING_CERTS=1
    fi
done
if [ "$MISSING_CERTS" -eq 1 ]; then
    echo "See the 'Certificate setup' section in README.md."
    exit 1
fi

# ---------------------------------------------------------------------------
# Check at least one event file is present
# Gen 4: .myg (WiFi distribution format)
# Gen 5: .pgf
# ---------------------------------------------------------------------------
EVENT_COUNT=$(find server/events -name "*.myg" -o -name "*.pgf" 2>/dev/null | wc -l | tr -d ' ')
if [ "$EVENT_COUNT" -eq 0 ]; then
    echo "WARNING: No event files found in server/events/"
    echo "  Add .myg files to server/events/gen4/ before connecting your DS."
    echo "  See README.md → Event files for sources."
    echo ""
fi

# ---------------------------------------------------------------------------
# Launch the Docker stack
# SERVER_IP is consumed by docker-compose.yml → dns container (NDS_SERVER_IP)
# ---------------------------------------------------------------------------
echo "Starting Docker stack..."
echo ""
export SERVER_IP="$LAN_IP"
docker compose up