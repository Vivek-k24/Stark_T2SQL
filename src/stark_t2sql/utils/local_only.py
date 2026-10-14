"""Local destination guards for later inference and database connection owners.

No helper resolves DNS, opens sockets, probes a service or creates a client.
Consumers must use the returned canonical destination, disable proxy inheritance,
and either disable redirects or apply the same allowlist to every redirect target.
Endpoint permission always requires an explicit scheme, host and port tuple.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from stark_t2sql.errors import LocalEndpointError


_SUPPORTED_SCHEMES = frozenset({"http", "https", "postgresql"})
_BRACKETED_AUTHORITY = re.compile(r"\[([0-9A-Fa-f:.]+)\]:([0-9]+)")
_UNBRACKETED_AUTHORITY = re.compile(r"([^:\[\]]+):([0-9]+)")


def _require_safe_text(value: str, *, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise LocalEndpointError(f"{field} must be nonempty text.")
    if not value.isascii() or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        raise LocalEndpointError(f"{field} contains unsupported or control characters.")


def _require_scheme(scheme: str) -> str:
    _require_safe_text(scheme, field="Endpoint scheme")
    normalized = scheme.lower()
    if normalized not in _SUPPORTED_SCHEMES:
        raise LocalEndpointError("Endpoint scheme is not supported for local services.")
    return normalized


def _require_port(port: int) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
        raise LocalEndpointError("Endpoint port must be an integer from 1 through 65535.")
    return port


def require_loopback_host(host: str) -> str:
    """Return a numeric loopback host, rejecting names and ambiguous IP spellings.

    The sole hostname literal accepted is localhost, converted to 127.0.0.1 so
    future clients need no hostname lookup. Trailing dots, localhost suffixes,
    scoped IPv6 addresses, bracketed host strings and numeric shorthand are denied.
    Brackets belong only to URL authority syntax handled by require_allowed_url.
    """
    _require_safe_text(host, field="Endpoint host")
    if host.lower() == "localhost":
        return "127.0.0.1"
    if any(character in host for character in "%[]\\/@?#"):
        raise LocalEndpointError("Endpoint host has unsupported address syntax.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise LocalEndpointError("Endpoint host must be a literal loopback address.") from exc
    if not address.is_loopback:
        raise LocalEndpointError("Endpoint host is outside the loopback address range.")
    return address.compressed


@dataclass(frozen=True, slots=True)
class LoopbackEndpoint:
    """One explicitly configured local service endpoint, with no wildcard fields."""

    scheme: str
    host: str
    port: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "scheme", _require_scheme(self.scheme))
        object.__setattr__(self, "host", require_loopback_host(self.host))
        object.__setattr__(self, "port", _require_port(self.port))


def require_allowed_host_port(
    host: str,
    port: int,
    *,
    scheme: str,
    allowed_endpoints: Iterable[LoopbackEndpoint],
) -> LoopbackEndpoint:
    """Permit a loopback destination only when its full tuple is allowlisted.

    Later PostgreSQL connection owners can use the returned host and port rather
    than accepting a DNS name or an unchecked connection alias destination.
    """
    candidate = LoopbackEndpoint(scheme=scheme, host=host, port=port)
    try:
        allowed = tuple(allowed_endpoints)
    except TypeError as exc:
        raise LocalEndpointError("An explicit endpoint allowlist is required.") from exc
    if not allowed or any(not isinstance(endpoint, LoopbackEndpoint) for endpoint in allowed):
        raise LocalEndpointError("Endpoint allowlist must contain explicit local endpoints.")
    if candidate not in allowed:
        raise LocalEndpointError("Destination is not in the configured endpoint allowlist.")
    return candidate


def require_allowed_url(
    url: str,
    *,
    allowed_endpoints: Iterable[LoopbackEndpoint],
) -> str:
    """Return an allowlisted absolute URL with a canonical numeric authority.

    URLs require an explicit decimal port and permit no credentials, fragments,
    backslashes or whitespace. HTTP paths and queries are preserved. PostgreSQL
    query parameters are denied because they can override the guarded address.
    Endpoint errors never echo the supplied URL, preventing disclosure of user info.
    """
    _require_safe_text(url, field="Endpoint URL")
    if "\\" in url or "#" in url:
        raise LocalEndpointError("Endpoint URL may not contain backslashes or fragments.")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise LocalEndpointError("Endpoint URL is malformed.") from exc
    if not parsed.scheme or not parsed.netloc or "://" not in url:
        raise LocalEndpointError("Endpoint URL must be absolute with an explicit authority.")
    if "@" in parsed.netloc:
        raise LocalEndpointError("Endpoint URL may not contain credentials or user information.")
    if parsed.scheme.lower() == "postgresql" and parsed.query:
        raise LocalEndpointError("PostgreSQL endpoint URLs may not override connection parameters.")

    authority_pattern = (
        _BRACKETED_AUTHORITY if parsed.netloc.startswith("[") else _UNBRACKETED_AUTHORITY
    )
    authority = authority_pattern.fullmatch(parsed.netloc)
    if authority is None:
        raise LocalEndpointError("Endpoint URL requires an unambiguous host and explicit port.")
    host, port_text = authority.groups()
    try:
        port = int(port_text, 10)
    except ValueError as exc:
        raise LocalEndpointError("Endpoint URL port is malformed.") from exc
    if str(port) != port_text:
        raise LocalEndpointError("Endpoint URL port must use canonical decimal notation.")

    endpoint = require_allowed_host_port(
        host,
        port,
        scheme=parsed.scheme,
        allowed_endpoints=allowed_endpoints,
    )
    canonical_host = f"[{endpoint.host}]" if ":" in endpoint.host else endpoint.host
    canonical_authority = f"{canonical_host}:{endpoint.port}"
    return urlunsplit(
        (endpoint.scheme, canonical_authority, parsed.path, parsed.query, "")
    )
