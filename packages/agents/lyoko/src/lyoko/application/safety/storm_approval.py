"""Factory for formatting storm protection approval requests and notifications."""

from typing import Any

from lyoko.domain.models.chat import ApprovalAction, ApprovalRequest
from lyoko.domain.models.incident import Incident

FORCE_ACTION = ApprovalAction(
    action_id="force",
    label="🚀 Procesar de todas formas",
    style="primary",
)


class AlertStormApprovalFactory:
    """Creates approval requests for circuit breaker alert storms and suppression cooldowns."""

    @staticmethod
    def build_storm_approval_request(
        storm_key: str,
        alerts: list[dict[str, Any]],
        count: int,
        window_seconds: int,
        cooldown_seconds: int,
        default_chat_id: str,
    ) -> tuple[Incident, ApprovalRequest]:
        """Construct a consolidated storm incident and approval request."""
        names = [a.get("labels", {}).get("alertname", "UnknownAlert") for a in alerts]
        primary_labels = alerts[0].get("labels", {})
        storm_incident = Incident(
            alert_name=names[0],
            namespace=primary_labels.get("namespace", ""),
            labels=primary_labels,
            annotations={"summary": f"Alert storm with {count} alerts"},
            correlated_alerts=[
                {"alertname": a.get("labels", {}).get("alertname", "UnknownAlert")}
                for a in alerts[1:]
            ],
        )
        details = (
            f"Received **{count} alerts** within {window_seconds}s. "
            f"Automated investigations paused for {cooldown_seconds}s.\n\n"
            f"**Recent Alerts:**\n" + "\n".join(f"- `{n}`" for n in names[:10])
        )
        req = ApprovalRequest(
            incident_id=storm_key,
            title="Alert Storm Circuit Breaker Activated",
            details=details,
            chat_id=default_chat_id,
            actions=[FORCE_ACTION],
        )
        return storm_incident, req

    @staticmethod
    def build_suppressed_approval_request(
        key: str,
        incident: Incident,
        default_chat_id: str,
    ) -> ApprovalRequest:
        """Construct an approval request for a suppressed cooldown alert."""
        target = incident.pod_name or incident.namespace or "resource"
        return ApprovalRequest(
            incident_id=key,
            title=f"Alert {incident.alert_name} Suppressed",
            details=f"Alert for `{target}` was suppressed due to recent resolution cooldown.",
            chat_id=default_chat_id,
            actions=[FORCE_ACTION],
        )
