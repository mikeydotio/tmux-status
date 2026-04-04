"""
Scraper module for tmux-status-server.

Provides read_session_key() and fetch_quota() for retrieving Claude API
usage quota data from claude.ai. Uses curl_cffi for HTTP requests with
Chrome TLS fingerprint impersonation to bypass Cloudflare.

All errors are returned as dicts with machine-readable error codes — no raw
exception text is ever exposed.
"""

import json
import logging
import os
import stat
import time

logger = logging.getLogger(__name__)

REQUEST_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "anthropic-client-platform": "web_claude_ai",
    "anthropic-client-version": "1.0.0",
    "Origin": "https://claude.ai",
    "Referer": "https://claude.ai/settings/usage",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


def _error_bridge(status, error_code):
    """Build an error-state bridge dict with 'X' utilization values."""
    return {
        "status": status,
        "five_hour": {"utilization": "X", "resets_at": None},
        "seven_day": {"utilization": "X", "resets_at": None},
        "error": error_code,
        "timestamp": int(time.time()),
    }


def read_session_key(path):
    """Read and validate a session key JSON file.

    Args:
        path: Filesystem path to the session key JSON file.

    Returns:
        Dict with ``sessionKey`` and optional ``expiresAt`` on success,
        or an error dict with ``error`` key on failure.
    """
    try:
        file_stat = os.stat(path)
    except FileNotFoundError:
        return {"error": "no_key"}
    except OSError:
        return {"error": "no_key"}

    # Reject files readable by group or other.
    if file_stat.st_mode & 0o077 != 0:
        return {"error": "insecure_permissions"}

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError):
        return {"error": "invalid_json"}
    except OSError:
        return {"error": "no_key"}

    if not isinstance(data, dict) or "sessionKey" not in data:
        return {"error": "invalid_json"}

    result = {"sessionKey": data["sessionKey"]}
    if "expiresAt" in data:
        result["expiresAt"] = data["expiresAt"]
    return result


def _http_get(url, session_key):
    """Perform an HTTPS GET with Chrome TLS fingerprint impersonation.

    Args:
        url: The URL to fetch.
        session_key: Session key value for the Cookie header.

    Returns:
        Tuple of (status_code, parsed_json_or_None).
    """
    from curl_cffi import requests as cffi_requests

    headers = {**REQUEST_HEADERS, "Cookie": f"sessionKey={session_key}"}
    r = cffi_requests.get(url, headers=headers, impersonate="chrome131", timeout=15)

    try:
        body = r.json()
    except Exception:
        body = None

    return r.status_code, body


def fetch_quota(session_key, org_uuid=None):
    """Fetch Claude API usage quota for the given session key.

    Args:
        session_key: The claude.ai session key string.
        org_uuid: Cached organization UUID, or None to discover.

    Returns:
        Tuple of (bridge_dict, org_uuid). The org_uuid may be updated
        (discovered) or cleared (on 401/403).
    """
    status_map = {401: "session_key_expired", 403: "blocked", 429: "rate_limited"}

    try:
        if not org_uuid:
            http_status, orgs = _http_get(
                "https://claude.ai/api/organizations", session_key
            )
            if http_status != 200:
                error_code = status_map.get(http_status, "upstream_error")
                return _error_bridge(error_code, error_code), None
            if not isinstance(orgs, list) or len(orgs) == 0:
                return _error_bridge("upstream_error", "upstream_error"), None
            org_uuid = orgs[0]["uuid"]

        http_status, usage = _http_get(
            f"https://claude.ai/api/organizations/{org_uuid}/usage",
            session_key,
        )
        if http_status != 200:
            new_org_uuid = None if http_status in (401, 403) else org_uuid
            error_code = status_map.get(http_status, "upstream_error")
            return _error_bridge(error_code, error_code), new_org_uuid

        def extract_window(data, name):
            w = data.get(name) or {}
            return {
                "utilization": w.get("utilization"),
                "resets_at": w.get("resets_at"),
            }

        return {
            "status": "ok",
            "org_uuid": org_uuid,
            "five_hour": extract_window(usage, "five_hour"),
            "seven_day": extract_window(usage, "seven_day"),
            "timestamp": int(time.time()),
        }, org_uuid

    except ImportError:
        return _error_bridge("upstream_error", "upstream_error"), org_uuid
    except Exception:
        return _error_bridge("upstream_error", "upstream_error"), org_uuid
