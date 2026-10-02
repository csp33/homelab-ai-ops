"""FastAPI webhook controller in infrastructure layer."""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from lyoko.domain.models import Incident


def create_webhook_router(workflow_app: Any = None) -> APIRouter:
    router = APIRouter(prefix="/webhook", tags=["webhooks"])

    @router.post("/alertmanager")
    async def handle_alertmanager_webhook(
        request: Request, background_tasks: BackgroundTasks
    ) -> dict[str, str]:
        try:
            data = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

        engine = workflow_app or getattr(request.app.state, "workflow_engine", None)
        if not engine:
            raise HTTPException(status_code=503, detail="Workflow engine is not initialized")

        alerts = data.get("alerts", [])
        for alert in alerts:
            if alert.get("status") == "firing":
                labels = alert.get("labels", {})
                incident = Incident(
                    alert_name=labels.get("alertname", "UnknownAlert"),
                    namespace=labels.get("namespace", "default"),
                    pod_name=labels.get("pod", "unknown-pod"),
                    deployment_name=labels.get("deployment") or labels.get("app"),
                    fingerprint=alert.get("fingerprint"),
                    labels=labels,
                )

                initial_state = {
                    "namespace": incident.namespace,
                    "pod_name": incident.pod_name,
                    "deployment_name": incident.deployment_name or "",
                    "alert_name": incident.alert_name,
                    "messages": [],
                    "diagnostics": {},
                    "root_cause": "",
                    "action_taken": "",
                    "is_resolved": False,
                    "requires_escalation": False,
                }

                thread_id = f"incident-{incident.fingerprint or incident.pod_name}"
                config = {"configurable": {"thread_id": thread_id}}

                background_tasks.add_task(engine.ainvoke, initial_state, config=config)

        return {"status": "accepted", "message": f"Processing {len(alerts)} alerts in background."}

    return router
