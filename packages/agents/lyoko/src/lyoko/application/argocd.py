"""Helpers for Argo CD sync-status alerts.

An "Argo CD application <name> has sync status OutOfSync" alert is a well-known shape. Detecting
it lets the workflow add an explicit, app-named instruction so the diagnosis does not mistake the
live drift (a resource absent from the cluster) for a missing Git manifest.
"""

import re

_OUTOFSYNC_RE = re.compile(
    r"Argo CD application\s+[`'\"]?([A-Za-z0-9._-]+)[`'\"]?\s+has sync status OutOfSync",
    re.IGNORECASE,
)


def parse_outofsync_app(text: str) -> str | None:
    """Return the application name from an Argo CD OutOfSync alert, if present."""
    if not text:
        return None
    match = _OUTOFSYNC_RE.search(text)
    return match.group(1) if match else None


def outofsync_hint(text: str) -> str:
    """Build a mandatory instruction for an Argo CD OutOfSync diagnosis, or an empty string."""
    app = parse_outofsync_app(text)
    if not app:
        return ""
    return (
        f"\n\nThis is an Argo CD OutOfSync alert for application `{app}`. Read its "
        "`.spec.syncPolicy.automated`. If autosync is absent or disabled, that is the root cause: "
        "conclude `ACTIONABLE: yes` and plan to enable autosync. A resource absent from the cluster "
        "is the drift autosync will fix, NOT a missing Git manifest."
    )
