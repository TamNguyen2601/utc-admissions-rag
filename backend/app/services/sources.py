"""Source permissions and URL gates. This checkpoint never fetches a URL."""
import ipaddress
import posixpath
import re
import socket
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException
from pydantic import ValidationError

from app.models.knowledge import DataSource

WEB_KINDS = {"utc", "topcv", "career"}
FETCH_KINDS = {"utc", "topcv"}
TRACKING = {"fbclid", "gclid", "msclkid"}


def canonical_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        if (parts.scheme.lower() != "https" or not host or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443)
                or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value):
            raise ValueError("Invalid URL")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or host.endswith((".localhost", ".local", ".internal")):
                raise ValueError("Private host")
            if not re.fullmatch(r"[a-z0-9.-]+", host):
                raise ValueError("Invalid host")
        else:
            if not address.is_global:
                raise ValueError("Private address")
        path = parts.path or "/"
        decoded = path
        for _ in range(4):
            expanded = unquote(decoded)
            if expanded == decoded: break
            decoded = expanded
        # Reject ambiguous encoded separators/traversal, rather than checking one path
        # and letting a future requests/server interpret a different one.
        if ("\\" in decoded or "%" in decoded or "//" in decoded
                or any(segment in {".", ".."} for segment in decoded.split("/"))):
            raise ValueError("Ambiguous path")
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in TRACKING]
        return urlunsplit(("https", f"[{host}]" if ":" in host else host, path, urlencode(sorted(query)), ""))
    except (ValueError, UnicodeError):
        raise ValueError("Invalid public HTTPS URL") from None


def validate_source(source):
    if source.permission_status == "allowed" and (not source.reuse_basis or not source.checked_at):
        raise ValueError("Allowed requires reuse basis and checked time")
    if source.enabled and source.permission_status != "allowed":
        raise ValueError("Permission required")
    if source.kind in WEB_KINDS and not (source.base_url and source.allowed_paths):
        raise ValueError("Web scope required")
    if source.kind in WEB_KINDS and source.permission_status == "allowed" and not (source.robots_url and source.terms_url):
        raise ValueError("Robots and terms review required")
    for value in (source.base_url, source.robots_url, source.terms_url):
        if value is not None: canonical_url(value)
    if source.base_url:
        host = urlsplit(canonical_url(source.base_url)).hostname
        if source.kind == "utc" and host != "tuyensinh.utc.edu.vn":
            raise ValueError("UTC host mismatch")
        if source.kind == "topcv" and host not in {"topcv.vn", "www.topcv.vn"}:
            raise ValueError("TopCV host mismatch")
    for path in source.allowed_paths:
        if (not path.startswith("/") or "?" in path or "#" in path
                or unquote(path) != path or "\\" in path or "//" in path
                or posixpath.normpath(path) != path.rstrip("/") and path != "/"):
            raise ValueError("Invalid allowed path")


def require_usable(source):
    if source is None:
        raise HTTPException(404)
    if not source.enabled or source.permission_status != "allowed" or not source.reuse_basis or not source.checked_at:
        raise HTTPException(422)


def validate_source_url(source, value: str, *, resolve: bool = False) -> str:
    require_usable(source)
    try:
        url = canonical_url(value)
        parts = urlsplit(url)
        if source.base_url:
            base = urlsplit(canonical_url(source.base_url))
            if parts.hostname != base.hostname:
                raise ValueError("Host outside scope")
            decoded_path = unquote(parts.path)
            if not any(path == "/" or decoded_path == path.rstrip("/")
                       or decoded_path.startswith(path.rstrip("/") + "/")
                       for path in source.allowed_paths_json):
                raise ValueError("Path outside scope")
        if resolve:
            addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
                raise ValueError("Private destination")
        return url
    except (ValueError, OSError):
        raise HTTPException(422) from None


def checked_fetch_url(source, value: str) -> str:
    """Future adapters must call before every request AND redirect (auto redirects off).

    Resolves all addresses to reject private destinations. No requests are issued here;
    adapter transport/DNS rebinding protection belongs to T020.
    """
    if source.kind not in FETCH_KINDS:
        raise HTTPException(422)
    return validate_source_url(source, value, resolve=True)


def source_response(source):
    return {field: getattr(source, "allowed_paths_json" if field == "allowed_paths" else field)
            for field in ("id", "name", "kind", "base_url", "allowed_paths", "enabled", "permission_status",
                          "robots_url", "terms_url", "reuse_basis", "checked_at", "min_interval_seconds",
                          "retry_not_before", "last_success_at")}


def save_source(db, payload, source=None):
    if source is None:
        source = DataSource()
        db.add(source)
    for field, value in payload.model_dump().items():
        if field in {"base_url", "robots_url", "terms_url"} and value is not None:
            value = canonical_url(value)
        setattr(source, "allowed_paths_json" if field == "allowed_paths" else field, value)
    db.commit()
    return source


def patch_source(db, source, changes):
    from app.schemas.document import SourceInput
    if not isinstance(changes, dict) or not changes or set(changes) - set(SourceInput.model_fields):
        raise HTTPException(422)
    current = {key: value for key, value in source_response(source).items() if key in SourceInput.model_fields}
    try:
        payload = SourceInput.model_validate(current | changes)
    except ValidationError:
        raise HTTPException(422) from None
    return save_source(db, payload, source)
