"""Detection of recovery / resolution notifications posted by monitoring systems.

A monitoring or alerting system posts both activations ("has been triggered", "is OutOfSync")
and recoveries ("has been resolved", "passing successfully"). A recovery needs no investigation:
there is nothing broken to diagnose. Recognizing it deterministically lets the graph answer with
a one-line acknowledgement instead of delegating to specialists and burning tool calls.
"""

import re

# Strong recovery signals only. A bare "resolved" would match "unresolved" or "not resolved", so
# every pattern requires explicit phrasing.
_RECOVERY_PATTERNS = (
    re.compile(r"\bhas been resolved\b", re.IGNORECASE),
    re.compile(r"\bhas been cleared\b", re.IGNORECASE),
    re.compile(r"\bhas been recovered\b", re.IGNORECASE),
    re.compile(r"\bis now resolved\b", re.IGNORECASE),
    re.compile(r"\bpassing successfully\b", re.IGNORECASE),
    re.compile(r"\bno active incidents?\b", re.IGNORECASE),
    re.compile(r"\bstatus:\s*resolved\b", re.IGNORECASE),
    re.compile(r"\[resolved\]", re.IGNORECASE),
)

RECOVERY_ACKNOWLEDGEMENT = (
    "✅ Noted: this is a recovery notification, the alert is resolved. No action needed."
)


def is_recovery_notification(text: str) -> bool:
    """Return True when the text announces that an alert has recovered or is no longer active."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _RECOVERY_PATTERNS)
