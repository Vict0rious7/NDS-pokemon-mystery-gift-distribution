# Minimal DNS server for redirecting Nintendo WFC domains to our server.
# Uses a custom Python implementation (dns_server.py) instead of dnsmasq
# because it needs to handle the DS's non-standard Type0/Class256 root query.
FROM python:3.12-alpine

COPY dns_server.py /dns_server.py

CMD ["python3", "/dns_server.py"]