import ipaddress
import socket
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443})
# A redirect chain is re-checked at every hop, so a public URL cannot bounce to a private one.
MAX_REDIRECTS = 5


class OutboundURLError(URLError):
    def __init__(self, reason):
        super().__init__(reason)


def _resolved_addresses(hostname):
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise OutboundURLError(f"Could not resolve {hostname!r}.") from exc
    return {info[4][0] for info in infos}


def _address_is_public(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    # is_global is false for loopback, link-local (169.254.169.254), private, reserved and unspecified.
    return ip.is_global and not ip.is_multicast


def validate_outbound_url(url, *, allow_http=True):
    if not url or not isinstance(url, str):
        raise OutboundURLError("No URL supplied.")

    parsed = urlparse(url.strip())
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise OutboundURLError(f"Unsupported scheme {parsed.scheme!r}.")
    if parsed.scheme == "http" and not allow_http:
        raise OutboundURLError("Only https is allowed here.")

    hostname = parsed.hostname
    if not hostname:
        raise OutboundURLError("URL has no host.")

    port = parsed.port
    if port is not None and port not in ALLOWED_PORTS:
        raise OutboundURLError(f"Port {port} is not allowed.")

    addresses = _resolved_addresses(hostname)
    if not addresses:
        raise OutboundURLError(f"Could not resolve {hostname!r}.")
    # Every record has to be public: one private answer is enough to make the fetch unsafe.
    unsafe = [address for address in addresses if not _address_is_public(address)]
    if unsafe:
        raise OutboundURLError(f"{hostname!r} resolves to a non-public address.")

    return url


class _ValidatingRedirectHandler(HTTPRedirectHandler):
    """Each hop is re-checked: the first URL says nothing about where it points."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_outbound_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = build_opener(_ValidatingRedirectHandler())


def open_outbound_url(url, *, timeout, data=None, headers=None, method=None, allow_http=True):
    validate_outbound_url(url, allow_http=allow_http)
    request = Request(url, data=data, headers=headers or {}, method=method)
    return _opener.open(request, timeout=timeout)
