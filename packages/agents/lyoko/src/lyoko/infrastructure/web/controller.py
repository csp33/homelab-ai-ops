"""FastAPI web controllers for webhooks and operator feedback."""

import hashlib
import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from lyoko.domain.interfaces.tracer import TracerInterface
from lyoko.domain.models.incident import Incident
from lyoko.domain.models.memory import FeedbackRequest, MemoryEntry

_MAX_KEY_LENGTH = 24


def _incident_key(incident: Incident) -> str:
    """Short, stable identifier for an incident.

    The key ends up in Telegram button callback data, which Telegram limits to 64 bytes, so a
    long value (for example a pod name) is replaced by a hash of the alert's labels.
    """
    key = incident.fingerprint or incident.pod_name
    if key and len(key) <= _MAX_KEY_LENGTH:
        return key
    digest_input = json.dumps(incident.labels, sort_keys=True) + (key or "")
    return hashlib.sha1(digest_input.encode(), usedforsecurity=False).hexdigest()[:16]


def create_webhook_router(
    workflow_app: Any = None,
    tracer: TracerInterface | None = None,
) -> APIRouter:
    """Router handling Prometheus / Alertmanager incoming webhooks."""
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
        active_tracer = tracer or getattr(request.app.state, "tracer", None)

        if not engine:
            raise HTTPException(status_code=503, detail="Workflow engine is not initialized")

        alerts = data.get("alerts", [])
        for alert in alerts:
            if alert.get("status") == "firing":
                labels = {str(k): str(v) for k, v in (alert.get("labels") or {}).items()}
                annotations = {str(k): str(v) for k, v in (alert.get("annotations") or {}).items()}
                incident = Incident(
                    alert_name=labels.get("alertname", "UnknownAlert"),
                    namespace=labels.get("namespace", ""),
                    pod_name=labels.get("pod", ""),
                    deployment_name=labels.get("deployment") or labels.get("app"),
                    fingerprint=alert.get("fingerprint"),
                    labels=labels,
                    annotations=annotations,
                )

                thread_id = f"incident-{_incident_key(incident)}"

                initial_state = {
                    "event_type": "alert",
                    "event_id": thread_id,
                    "session_id": thread_id,
                    "alert_name": incident.alert_name,
                    "labels": labels,
                    "annotations": annotations,
                    "root_cause": "",
                    "action_taken": "",
                    "is_resolved": False,
                    "requires_escalation": False,
                }

                trace_name = f"lyoko-{incident.alert_name}-{_incident_key(incident)}"
                tags = ["lyoko", f"alert:{incident.alert_name}"]
                metadata = {
                    "alert_name": incident.alert_name,
                    "fingerprint": incident.fingerprint or "",
                }
                if incident.namespace:
                    tags.insert(1, f"ns:{incident.namespace}")
                    metadata["namespace"] = incident.namespace
                if incident.pod_name:
                    metadata["pod_name"] = incident.pod_name

                if active_tracer:
                    config = active_tracer.get_trace_config(
                        session_id=thread_id,
                        user_id=f"alert:{incident.alert_name}",
                        trace_name=trace_name,
                        tags=tags,
                        metadata=metadata,
                    )
                    config.setdefault("configurable", {})["thread_id"] = thread_id
                else:
                    config = {
                        "configurable": {"thread_id": thread_id},
                        "tags": tags,
                        "metadata": metadata,
                        "run_name": trace_name,
                    }

                background_tasks.add_task(engine.ainvoke, initial_state, config=config)

        return {"status": "accepted", "message": f"Processing {len(alerts)} alerts in background."}

    return router


def create_feedback_router() -> APIRouter:
    """Router handling human operator feedback and lessons learned."""
    router = APIRouter(prefix="/api/v1/feedback", tags=["feedback", "memory"])

    @router.post("")
    async def submit_feedback(request: Request, payload: FeedbackRequest) -> dict[str, Any]:
        memory_repo = getattr(request.app.state, "memory_repository", None)
        if not memory_repo:
            raise HTTPException(
                status_code=503,
                detail="PostgreSQL memory repository is not available or configured.",
            )

        embeddings_service = getattr(request.app.state, "embeddings_service", None)
        embedding = None

        if embeddings_service:
            text_to_embed = (
                f"{payload.alert_name or ''} {payload.service_name} {payload.namespace} "
                f"{payload.incident_pattern} {payload.operator_feedback}"
            )
            embedding = await embeddings_service.embed_text(text_to_embed)

        entry = MemoryEntry(
            namespace=payload.namespace,
            service_name=payload.service_name,
            alert_name=payload.alert_name,
            incident_pattern=payload.incident_pattern,
            operator_feedback=payload.operator_feedback,
            action_rule=payload.action_rule,
        )

        memory_id = await memory_repo.save_memory(entry, embedding=embedding)
        return {
            "status": "success",
            "memory_id": memory_id,
            "message": "Operator feedback recorded into persistent agent memory.",
        }

    @router.get("")
    async def get_feedback_list(
        request: Request, limit: int = Query(default=50, ge=1, le=100)
    ) -> dict[str, Any]:
        memory_repo = getattr(request.app.state, "memory_repository", None)
        if not memory_repo:
            return {"memories": [], "count": 0}

        memories = await memory_repo.list_recent_memories(limit=limit)
        return {
            "memories": [m.model_dump() for m in memories],
            "count": len(memories),
        }

    return router
