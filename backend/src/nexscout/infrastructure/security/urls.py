"""Outbound URL safety (SSRF protection) shared by provider endpoints and, later, fetchers."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from nexscout.domain.errors import ValidationFailed

# Cloud metadata endpoints are never reachable, even when private networks are allowed.
_ALWAYS_BLOCKED = (
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fd00:ec2::254/128"),
    ipaddress.ip_network("100.100.100.200/32"),
)


def _blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_private: bool) -> bool:
    if any(ip in net for net in _ALWAYS_BLOCKED):
        return True
    if ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return True
    return bool(
        not allow_private
        and (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip in ipaddress.ip_network("100.64.0.0/10")
        )
    )


def resolve_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValidationFailed(f"Can't resolve host “{host}”.") from exc
    return [ipaddress.ip_address(str(info[4][0]).split("%")[0]) for info in infos]


def check_outbound_url(url: str, *, allow_private: bool, resolve: bool = True) -> str:
    """Validate scheme/host and (optionally) every resolved address. Returns the URL."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValidationFailed("Use an http(s) address with a host name.")
    if parts.username or parts.password:
        raise ValidationFailed("Addresses must not contain a username or password.")
    host = parts.hostname
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        ips = resolve_ips(host) if resolve else []
    for ip in ips:
        if _blocked(ip, allow_private):
            raise ValidationFailed("That address points to a restricted network location.")
    return url.strip()


def is_local_address(url: str) -> bool:
    """True when the endpoint runs on this machine (data does not leave the device)."""
    host = urlsplit(url).hostname or ""
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
