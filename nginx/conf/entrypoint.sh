#!/bin/sh
# Entrypoint for the SSL termination container.
#
# Responsibilities:
#   - Copy TLS certificates into the stunnel config directory
#   - Start socat to proxy plain HTTP (port 80) to the event server
#   - Wait for the event server to be reachable, then start stunnel
#
# Port layout:
#   80  → socat → event-server:8080  (plain HTTP, for conntest)
#   443 → stunnel → event-server:8080 (SSLv3/RC4, for NAS + DLS1)

set -e

# Copy certs from the Docker volume mount into stunnel's config dir
cp /etc/nginx/certs/server-chain.crt /etc/stunnel/certs/server-chain.crt
cp /etc/nginx/certs/server.key       /etc/stunnel/certs/server.key

# Proxy port 80 → event-server:8080 (DS conntest uses plain HTTP)
socat TCP-LISTEN:80,fork,reuseaddr TCP:event-server:8080 &

# Wait for the event-server container to be ready before starting stunnel
echo "Waiting for event-server..."
until nslookup event-server > /dev/null 2>&1; do sleep 1; done
echo "event-server resolved, starting stunnel"

exec /opt/stunnel/bin/stunnel /etc/stunnel/stunnel.conf