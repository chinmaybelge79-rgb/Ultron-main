"""Day 7 hardening: filesystem scope and network egress validation.

Two first-line defenses, evaluated before any tool call reaches the
PermissionGate:

- **Filesystem scope** — any path argument must resolve (via
  ``Path.resolve()``, which follows symlinks) to somewhere under the user's
  home directory or an explicit allowlist. ``/etc``, ``/System``, and other
  users' directories are rejected by default.

- **Network egress** — outbound HTTP requests are restricted to an explicit
  domain allowlist (e.g. the local Ollama endpoint). Anything else is
  rejected before a socket is ever opened.

These are hard mechanical checks; the Day 4 approval prompt remains the
*last* line of defense, not the first.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

# TLD/domain suffixes that are always local and inherently allowed.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


class ScopeViolation(PermissionError):
    """Raised when a path or host falls outside the permitted scope."""


def allowed_fs_roots(extra_roots: tuple[str | Path, ...] = ()) -> tuple[Path, ...]:
    """Return the resolved filesystem roots tools may touch.

    Defaults to the user's home directory; extra roots can be added via
    extra_roots or the ``ULTRON_FS_ALLOW_ROOTS`` env var (comma-separated).
    """
    roots: list[Path] = [Path.home().resolve()]
    env = os.environ.get("ULTRON_FS_ALLOW_ROOTS", "").strip()
    if env:
        roots.extend(Path(p).expanduser().resolve() for p in env.split(",") if p.strip())
    roots.extend(Path(r).expanduser().resolve() for r in extra_roots)
    return tuple(roots)


def validate_fs_path(path: str | Path, extra_roots: tuple[str | Path, ...] = ()) -> Path:
    """Resolve ``path`` and verify it stays inside an allowed root.

    Returns the resolved path on success, raises :class:`ScopeViolation`
    otherwise (including for paths outside the home directory such as
    ``/etc``, ``/System``, or another user's directory).
    """
    resolved = Path(path).expanduser().resolve()
    for root in allowed_fs_roots(extra_roots):
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise ScopeViolation(
        f"Path {resolved} is outside the allowed filesystem scope "
        f"({', '.join(str(r) for r in allowed_fs_roots(extra_roots))})."
    )


def allowed_network_domains(extra_domains: tuple[str, ...] = ()) -> frozenset[str]:
    """Return the set of permitted outbound hostnames (lowercase).

    Always includes localhost names; extras come from the argument or the
    ``ULTRON_NET_ALLOW_DOMAINS`` env var (comma-separated).
    """
    domains = set(_LOCAL_HOSTS)
    env = os.environ.get("ULTRON_NET_ALLOW_DOMAINS", "").strip()
    if env:
        domains.update(d.strip().lower() for d in env.split(",") if d.strip())
    domains.update(d.strip().lower() for d in extra_domains if d.strip())
    return frozenset(domains)


def validate_network_domain(url_or_host: str, extra_domains: tuple[str, ...] = ()) -> str:
    """Verify an outbound target is on the allowlist.

    Accepts a full URL or a bare hostname. Returns the lowercase hostname on
    success, raises :class:`ScopeViolation` otherwise.
    """
    if "://" in url_or_host:
        host = urlparse(url_or_host).hostname or ""
    else:
        host = url_or_host.split("/", 1)[0].split(":", 1)[0]
    host = host.strip().lower()
    if not host:
        raise ScopeViolation(f"Could not determine host in {url_or_host!r}.")
    allowlist = allowed_network_domains(extra_domains)
    if host in allowlist:
        return host
    # Allow subdomains of allowlisted domains (e.g. api.openrouter.ai under openrouter.ai).
    for domain in allowlist:
        if host.endswith(f".{domain}"):
            return host
    raise ScopeViolation(
        f"Host {host} is not on the network egress allowlist. "
        "Set ULTRON_NET_ALLOW_DOMAINS to permit it explicitly."
    )
