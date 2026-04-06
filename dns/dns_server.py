#!/usr/bin/env python3
"""
Minimal DNS server for the NDS Pokémon event server.

Two special behaviours required by the DS:

1. Type0/Class256 root query → NOERROR + SOA authority
   The DS sends a non-standard root query before connecting to DLS1.
   Real DNS servers return NOERROR with a SOA record; we do the same.
   Without this, the DS refuses to proceed to the download step.

2. Nintendo domain A queries → redirect to SERVER_IP
   All *.nintendowifi.net (and related) domains are pointed at our
   server so the DS connects to us instead of Nintendo's dead servers.

Everything else returns NXDOMAIN.
"""

import os
import socket
import struct
import threading

SERVER_IP = os.environ.get("NDS_SERVER_IP", "192.168.1.69")

# All domains (and their subdomains) that should point to SERVER_IP
REDIRECT_DOMAINS = [
    "nintendowifi.net",
    "gamestats.com",
    "gamestats2.com",
    "crl.nintendo.com",
]


def encode_name(name):
    """Encode a domain name in DNS wire format."""
    parts = name.rstrip(".").split(".")
    encoded = b""
    for part in parts:
        encoded += bytes([len(part)]) + part.encode()
    return encoded + b"\x00"


def build_soa_authority():
    """
    Build a SOA record for the root zone.
    Returned in the authority section of root query responses.
    """
    mname = encode_name("a.root-servers.net")
    rname = encode_name("nstld.verisign-grs.com")
    soa_rdata = mname + rname + struct.pack(
        ">IIIII",
        2026040400,  # serial
        1800,        # refresh  (30 min)
        900,         # retry    (15 min)
        604800,      # expire   (7 days)
        86400,       # minimum  (1 day)
    )
    # Root name = b"\x00", type SOA=6, class IN=1, ttl=86400
    return b"\x00" + struct.pack(">HHI", 6, 1, 86400) + struct.pack(">H", len(soa_rdata)) + soa_rdata


def build_a_record(qname, ip):
    """Build a DNS A record answer for qname → ip."""
    encoded = encode_name(qname)
    # type A=1, class IN=1, ttl=300, rdlength=4
    return encoded + struct.pack(">HHIH", 1, 1, 300, 4) + socket.inet_aton(ip)


def matches_redirect(qname):
    """Return True if qname is a Nintendo domain we should redirect."""
    name = qname.rstrip(".").lower()
    return any(
        name == domain or name.endswith("." + domain)
        for domain in REDIRECT_DOMAINS
    )


def handle_query(data, addr, sock):
    """Parse a DNS query and send the appropriate response."""
    if len(data) < 12:
        return

    txid    = data[:2]
    qdcount = struct.unpack(">H", data[4:6])[0]

    if qdcount == 0:
        return

    # Parse the question section
    offset      = 12
    qname_parts = []
    while offset < len(data):
        length = data[offset]
        offset += 1
        if length == 0:
            break
        if offset + length > len(data):
            return
        qname_parts.append(data[offset:offset + length].decode("ascii", errors="replace"))
        offset += length

    if offset + 4 > len(data):
        return

    qtype  = struct.unpack(">H", data[offset:offset + 2])[0]
    qclass = struct.unpack(">H", data[offset + 2:offset + 4])[0]
    qname  = ".".join(qname_parts) if qname_parts else "."

    # Preserve the original question section for the response
    question = data[12:offset + 4]

    print(f"DNS query: {qname!r} type={qtype} class={qclass} from {addr}")

    # --- Root query (Type0/Class256) → NOERROR + SOA ---
    # The DS sends this before connecting to DLS1.
    # We must reply NOERROR (not NXDOMAIN) or the DS aborts.
    if qname in (".", ""):
        authority   = build_soa_authority()
        resp_flags  = struct.pack(">H", 0x8180)   # QR+RD+RA, RCODE=NOERROR
        resp_header = txid + resp_flags + struct.pack(">HHHH", 1, 0, 1, 0)
        sock.sendto(resp_header + question + authority, addr)
        print(f"  → NOERROR + SOA (root query)")
        return

    # --- A query for Nintendo domains → redirect to our server ---
    if qtype == 1 and matches_redirect(qname):
        answer      = build_a_record(qname, SERVER_IP)
        resp_flags  = struct.pack(">H", 0x8180)
        resp_header = txid + resp_flags + struct.pack(">HHHH", 1, 1, 0, 0)
        sock.sendto(resp_header + question + answer, addr)
        print(f"  → A {SERVER_IP} for {qname}")
        return

    # --- Everything else → NXDOMAIN ---
    resp_flags  = struct.pack(">H", 0x8183)   # RCODE=NXDOMAIN
    resp_header = txid + resp_flags + struct.pack(">HHHH", 1, 0, 0, 0)
    sock.sendto(resp_header + question, addr)
    print(f"  → NXDOMAIN for {qname} type={qtype}")


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", 53))
    print(f"DNS server listening on :53 — Nintendo domains → {SERVER_IP}")

    while True:
        try:
            data, addr = sock.recvfrom(512)
            threading.Thread(
                target=handle_query,
                args=(data, addr, sock),
                daemon=True,
            ).start()
        except Exception as e:
            print(f"DNS error: {e}")


if __name__ == "__main__":
    main()