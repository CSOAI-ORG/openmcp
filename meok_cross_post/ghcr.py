"""GHCR probe for the audit's D-distribution category.

This is a network probe used by the monthly cron (not the PR hot path).
Cached for 6h at ~/.meok/audit-cache/ghcr/<owner>/<image>/<tag>.json.

Per AGENTS.md, tests must be hermetic. The cache directory is only
written when MEOK_ALLOW_NETWORK=1 is set in the environment.
"""

from __future__ import annotations

import hashlib
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


CACHE_TTL_SEC = 6 * 3600  # 6 hours


def _cache_path(owner: str, image: str, tag: str) -> Path:
    """Path to the cache file. Only created if MEOK_ALLOW_NETWORK=1."""
    base = Path.home() / ".meok" / "audit-cache" / "ghcr" / owner / image
    base.mkdir(parents=True, exist_ok=True)
    safe_tag = hashlib.sha256(tag.encode()).hexdigest()[:16]
    return base / f"{safe_tag}.json"


def probe(owner: str, image: str, tag: str = "latest") -> dict:
    """Probe GHCR for the image's visibility + existence.

    Returns a dict suitable for the audit's `evidence` field:
        {"found": True, "public": True, "tag": tag, "cached_at": ..., "latency_ms": ...}
    or
        {"found": False, "reason": "401/404/etc", "latency_ms": ...}
    """
    if os.environ.get("MEOK_ALLOW_NETWORK") != "1":
        return {"found": False, "reason": "network disabled (set MEOK_ALLOW_NETWORK=1)"}

    cache = _cache_path(owner, image, tag)
    if cache.exists():
        age = time.time() - cache.stat().st_mtime
        if age < CACHE_TTL_SEC:
            import json
            return json.loads(cache.read_text())

    # The GHCR manifest endpoint returns 200 for public images with no auth,
    # 401 for private. We send Accept headers to elicit a clear response.
    url = f"https://ghcr.io/v2/{owner}/{image}/manifests/{tag}"
    start = time.time()
    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.oci.image.manifest.v1+json,"
                      "application/vnd.docker.distribution.manifest.v2+json,"
                      "application/vnd.docker.distribution.manifest.list.v2+json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            latency = int((time.time() - start) * 1000)
            result = {
                "found": True,
                "public": True,
                "tag": tag,
                "latency_ms": latency,
                "cached_at": time.time(),
            }
    except urllib.error.HTTPError as e:
        latency = int((time.time() - start) * 1000)
        result = {
            "found": False,
            "public": False,
            "tag": tag,
            "reason": f"HTTP {e.code}",
            "latency_ms": latency,
            "cached_at": time.time(),
        }
    except (urllib.error.URLError, TimeoutError) as e:
        result = {"found": False, "reason": f"connection error: {e}", "cached_at": time.time()}

    try:
        import json
        cache.write_text(json.dumps(result))
    except OSError:
        pass  # Cache write failure is non-fatal.
    return result
