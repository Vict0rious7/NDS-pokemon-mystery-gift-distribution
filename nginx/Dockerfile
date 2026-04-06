# Two-stage build:
#   Stage 1 (builder): compile custom OpenSSL + stunnel with SSLv3/RC4 support
#   Stage 2 (runtime): minimal image with only the compiled binaries
#
# Why custom OpenSSL?
#   The DS only supports SSLv3 with RC4-SHA or RC4-MD5 ciphers.
#   Modern OpenSSL disables these by default for security reasons,
#   so we must compile a patched version that re-enables them.
#
# Why custom stunnel?
#   stunnel acts as the SSLv3 terminator: it accepts encrypted connections
#   from the DS and forwards plain HTTP to the event-server container.
#   Several patches are applied to make it work with the DS's quirky SSL:
#     - DEFAULT_SECURITY_LEVEL 0: allows weak ciphers
#     - timeout_close=0: don't wait for SSL close_notify (DS never sends it)
#     - timeout_close → timeout_idle: prevents premature connection teardown

FROM debian:bookworm-slim AS builder

RUN apt-get update && apt-get install -y \
    build-essential wget libpcre3-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

ARG OPENSSL_VERSION=1.1.1w
ARG STUNNEL_VERSION=5.72

# Download sources
RUN wget -q https://www.openssl.org/source/openssl-${OPENSSL_VERSION}.tar.gz && \
    tar xzf openssl-${OPENSSL_VERSION}.tar.gz && \
    wget -q https://www.stunnel.org/archive/5.x/stunnel-${STUNNEL_VERSION}.tar.gz && \
    tar xzf stunnel-${STUNNEL_VERSION}.tar.gz

# Build OpenSSL with SSLv3 and weak cipher support re-enabled.
# The sed patches force SSLv3 through the version/security checks that
# would otherwise reject it even when explicitly configured.
RUN cd openssl-${OPENSSL_VERSION} && \
    ./config \
        enable-ssl3 enable-ssl3-method enable-weak-ssl-ciphers \
        -DOPENSSL_TLS_SECURITY_LEVEL=0 \
        --prefix=/opt/openssl --openssldir=/opt/openssl && \
    sed -i 's/if (ssl_get_min_max_version(s, \&ver_min, \&ver_max, NULL) != 0)/if (0)/' ssl/statem/statem_lib.c && \
    sed -i 's/} else if (ver_max >= c->min_tls \&\& ver_max <= c->max_tls) {/} else if (1) {/' ssl/statem/statem_lib.c && \
    sed -i 's/if (client_version <= SSL3_VERSION)/if (0) \/\* patched for NDS SSLv3 support \*\//' ssl/statem/statem_lib.c && \
    sed -i 's/if ((s->options \& method->mask) != 0)/if (method->version != SSL3_VERSION \&\& (s->options \& method->mask) != 0)/' ssl/statem/statem_lib.c && \
    sed -i 's/ssl_security(s, SSL_SECOP_VERSION, 0, version, NULL) == 0/ssl_security(s, SSL_SECOP_VERSION, 0, version, NULL) == 0 \&\& version != SSL3_VERSION/' ssl/statem/statem_lib.c && \
    make -j$(nproc) && make install_sw

# Build stunnel against our custom OpenSSL.
# Patches:
#   - Security level 0: permit RC4 and other weak ciphers
#   - timeout_close=0: DS never sends SSL close_notify, so don't wait for it
#   - timeout_close → timeout_idle: use idle timeout instead of close timeout
#     so stunnel doesn't drop the connection before the DS finishes reading
RUN cd stunnel-${STUNNEL_VERSION} && \
    sed -i 's/#define DEFAULT_SECURITY_LEVEL 2/#define DEFAULT_SECURITY_LEVEL 0/' src/common.h && \
    sed -i 's/section->timeout_close=60;/section->timeout_close=0;/' src/options.c && \
    sed -i 's/            timeout=c->opt->timeout_close;/            timeout=c->opt->timeout_idle;/' src/client.c && \
    ./configure \
        --with-ssl=/opt/openssl \
        --prefix=/opt/stunnel \
        --disable-libwrap --disable-systemd && \
    make -j$(nproc) && make install

# ---- Runtime image ----
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    libpcre3 zlib1g socat dnsutils \
    && rm -rf /var/lib/apt/lists/*

# Copy only the compiled binaries from the builder stage
COPY --from=builder /opt/openssl /opt/openssl
COPY --from=builder /opt/stunnel /opt/stunnel

COPY conf/stunnel.conf /etc/stunnel/stunnel.conf
COPY conf/entrypoint.sh /entrypoint.sh

# Register our custom OpenSSL so all processes use it
RUN echo "/opt/openssl/lib" > /etc/ld.so.conf.d/openssl.conf && ldconfig

RUN chmod +x /entrypoint.sh && \
    mkdir -p /var/log/stunnel /etc/stunnel/certs

EXPOSE 80 443

ENTRYPOINT ["/entrypoint.sh"]