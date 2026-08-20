import re
import socket
import time

_HEALTH_TTL = 60
_health_cache: dict[str, tuple[float, str | None]] = {}


def parse_tg_proxy(url: str):
    if not url or not url.startswith("tg://proxy?"):
        return None, None, None
    query = url[len("tg://proxy?"):]
    params = {}
    for part in query.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k] = v
    server = params.get("server")
    port = int(params.get("port", 0)) if params.get("port") else None
    secret = params.get("secret")
    return server, port, secret


def check_socks5(
    proxy_url: str, test_host: str = "api.ipify.org", test_port: int = 80
) -> str | None:
    """Full SOCKS5 check: RFC 1928 handshake + RFC 1929 auth + real HTTP request.

    Returns the exit IP on success, None on any failure.
    """
    m = re.match(r"socks5://([^:@]+)(?::([^@]+))?@([^:]+):(\d+)", proxy_url)
    if not m:
        m = re.match(r"socks5://([^:]+):(\d+)", proxy_url)
        if not m:
            return None
        user, pwd, host, port = None, None, m.group(1), int(m.group(2))
    else:
        user, pwd, host, port = m.group(1), m.group(2), m.group(3), int(m.group(4))
    try:
        s = socket.create_connection((host, port), timeout=5)
        s.settimeout(8)
        s.sendall(b"\x05\x02\x00\x02" if user else b"\x05\x01\x00")
        resp = s.recv(2)
        if len(resp) != 2 or resp[0] != 0x05:
            s.close()
            return None
        if resp[1] == 0x02 and user:
            u = user.encode()
            p = (pwd or "").encode()
            s.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
            if s.recv(2) != b"\x01\x00":
                s.close()
                return None
        elif resp[1] != 0x00:
            s.close()
            return None
        host_b = test_host.encode()
        s.sendall(
            b"\x05\x01\x00\x03" + bytes([len(host_b)]) + host_b + test_port.to_bytes(2, "big")
        )
        header = s.recv(4)
        if len(header) != 4 or header[:2] != b"\x05\x00":
            s.close()
            return None
        atyp = header[3]
        if atyp == 0x01:
            s.recv(6)
        elif atyp == 0x03:
            ln = s.recv(1)[0]
            s.recv(ln + 2)
        elif atyp == 0x04:
            s.recv(18)
        else:
            s.close()
            return None
        s.sendall(
            f"GET / HTTP/1.1\r\nHost: {test_host}\r\nUser-Agent: curl/8\r\n"
            f"Connection: close\r\n\r\n".encode()
        )
        data = s.recv(1024).decode(errors="ignore")
        s.close()
        if not data.startswith("HTTP/"):
            return None
        lines = data.splitlines()
        return lines[-1].strip() if lines else None
    except Exception:
        return None


def socks5_health(proxy_url: str, ttl: float = _HEALTH_TTL) -> str | None:
    """Cached exit IP for a proxy; re-checks only after `ttl` seconds."""
    cached = _health_cache.get(proxy_url)
    if cached and time.monotonic() - cached[0] < ttl:
        return cached[1]
    exit_ip = check_socks5(proxy_url)
    _health_cache[proxy_url] = (time.monotonic(), exit_ip)
    return exit_ip
