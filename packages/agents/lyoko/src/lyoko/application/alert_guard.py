"""Alert Storm Protector and cascade failure deduplication service.

Prevents trace spam and token cost explosions during cascading infrastructure failures by:
1. Debouncing and grouping bursts of firing alerts into a single consolidated Incident.
2. Deduplicating in-flight investigations and suppressing flapping alerts via cooldown TTL.
3. Providing an emergency Circuit Breaker when alert velocity exceeds storm thresholds.
4. Throttling concurrent LangGraph runs using an asyncio Semaphore.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from lyoko.config import AgentSettings
from lyoko.config import settings as default_settings
from lyoko.domain.models.incident import Incident, compute_incident_key

logger = logging.getLogger("lyoko.alert_guard")


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class AlertStormProtector:
    """Guards LYOKO against alert storms, cascading trace spam, and flapping loops."""

    def __init__(
        self,
        settings: AgentSettings | None = None,
        chat_manager: Any = None,
        dispatch_callback: Callable[[Incident], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = settings or default_settings
        self._chat_manager = chat_manager
        self._dispatch_callback = dispatch_callback

        self._circuit_state = CircuitState.CLOSED
        self._circuit_tripped_at: float = 0.0
        self._recent_alert_timestamps: deque[float] = deque()

        self._in_flight_keys: set[str] = set()
        self._cooldown_cache: dict[str, float] = {}  # key -> monotonic expiry

        self._pending_alerts: list[dict[str, Any]] = []
        self._debounce_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(self._settings.max_concurrent_incidents)

    @property
    def circuit_state(self) -> CircuitState:
        """Current state of the alert storm circuit breaker."""
        now = time.monotonic()
        if (
            self._circuit_state == CircuitState.OPEN
            and now - self._circuit_tripped_at >= self._settings.alert_storm_cooldown_seconds
        ):
            self._circuit_state = CircuitState.HALF_OPEN
            logger.info("Alert storm circuit breaker transitioned to HALF_OPEN")
        return self._circuit_state

    def get_incident_key(self, incident: Incident) -> str:
        return compute_incident_key(incident)

    def is_in_flight(self, key: str) -> bool:
        return key in self._in_flight_keys

    def is_in_cooldown(self, key: str) -> bool:
        now = time.monotonic()
        expiry = self._cooldown_cache.get(key)
        if expiry is None:
            return False
        if now >= expiry:
            del self._cooldown_cache[key]
            return False
        return True

    def mark_in_flight(self, key: str) -> None:
        self._in_flight_keys.add(key)

    def mark_completed(self, key: str) -> None:
        self._in_flight_keys.discard(key)
        if self._settings.alert_dedup_cooldown_seconds > 0:
            self._cooldown_cache[key] = (
                time.monotonic() + self._settings.alert_dedup_cooldown_seconds
            )

    async def ingest_alerts(self, raw_alerts: list[dict[str, Any]]) -> None:
        """Ingest incoming raw Alertmanager alerts and apply storm protection."""
        firing_alerts = [a for a in raw_alerts if a.get("status") == "firing"]
        if not firing_alerts:
            return

        now = time.monotonic()
        async with self._lock:
            # 1. Update velocity meter
            window_start = now - self._settings.alert_storm_window_seconds
            while self._recent_alert_timestamps and self._recent_alert_timestamps[0] < window_start:
                self._recent_alert_timestamps.popleft()

            for _ in firing_alerts:
                self._recent_alert_timestamps.append(now)

            alert_count = len(self._recent_alert_timestamps)
            current_state = self.circuit_state

            # 2. Check if circuit breaker trips
            if (
                alert_count > self._settings.alert_storm_threshold
                and current_state != CircuitState.OPEN
            ):
                self._circuit_state = CircuitState.OPEN
                self._circuit_tripped_at = now
                logger.warning(
                    "Alert storm detected (%d alerts in %ds)! Tripping circuit breaker to OPEN.",
                    alert_count,
                    self._settings.alert_storm_window_seconds,
                )
                await self._notify_storm(firing_alerts, alert_count)
                # Clear pending debounce to avoid cascading executions
                self._pending_alerts.clear()
                if self._debounce_task and not self._debounce_task.done():
                    self._debounce_task.cancel()
                return

            if self.circuit_state == CircuitState.OPEN:
                logger.warning(
                    "Circuit breaker is OPEN. Dropping %d alerts to prevent trace spam.",
                    len(firing_alerts),
                )
                return

            if self._circuit_state == CircuitState.HALF_OPEN:
                self._circuit_state = CircuitState.CLOSED
                logger.info("Circuit breaker recovered to CLOSED.")

            # 3. Filter in-flight and cooldown duplicates
            filtered_alerts: list[dict[str, Any]] = []
            for alert in firing_alerts:
                labels = {str(k): str(v) for k, v in (alert.get("labels") or {}).items()}
                annotations = {str(k): str(v) for k, v in (alert.get("annotations") or {}).items()}
                candidate = Incident(
                    alert_name=labels.get("alertname", "UnknownAlert"),
                    namespace=labels.get("namespace", ""),
                    pod_name=labels.get("pod", ""),
                    deployment_name=labels.get("deployment") or labels.get("app"),
                    fingerprint=alert.get("fingerprint"),
                    labels=labels,
                    annotations=annotations,
                )
                key = self.get_incident_key(candidate)
                if self.is_in_flight(key):
                    logger.info(
                        "Alert %s (%s) is already in flight. Skipping.", candidate.alert_name, key
                    )
                    continue
                if self.is_in_cooldown(key):
                    logger.info(
                        "Alert %s (%s) is in cooldown. Skipping.", candidate.alert_name, key
                    )
                    continue
                filtered_alerts.append(alert)

            if not filtered_alerts:
                return

            # 4. Debounce and aggregate
            self._pending_alerts.extend(filtered_alerts)

            if self._settings.alert_debounce_seconds <= 0:
                await self._flush_pending_locked()
            else:
                if self._debounce_task is None or self._debounce_task.done():
                    self._debounce_task = asyncio.create_task(self._debounce_timer())

    async def _debounce_timer(self) -> None:
        try:
            await asyncio.sleep(self._settings.alert_debounce_seconds)
            async with self._lock:
                await self._flush_pending_locked()
        except asyncio.CancelledError:
            pass

    async def _flush_pending_locked(self) -> None:
        if not self._pending_alerts:
            return

        # Group alerts by namespace
        grouped: dict[str, list[dict[str, Any]]] = {}
        for alert in self._pending_alerts:
            labels = alert.get("labels") or {}
            ns = labels.get("namespace", "")
            grouped.setdefault(ns, []).append(alert)

        self._pending_alerts.clear()

        for _ns, alerts in grouped.items():
            primary_raw = alerts[0]

            correlated_raw = alerts[1:]

            primary_labels = {str(k): str(v) for k, v in (primary_raw.get("labels") or {}).items()}
            primary_annotations = {
                str(k): str(v) for k, v in (primary_raw.get("annotations") or {}).items()
            }

            correlated_list = [
                {
                    "alertname": a.get("labels", {}).get("alertname", "UnknownAlert"),
                    "namespace": a.get("labels", {}).get("namespace", ""),
                    "pod": a.get("labels", {}).get("pod", ""),
                    "labels": a.get("labels", {}),
                    "annotations": a.get("annotations", {}),
                }
                for a in correlated_raw
            ]

            incident = Incident(
                alert_name=primary_labels.get("alertname", "UnknownAlert"),
                namespace=primary_labels.get("namespace", ""),
                pod_name=primary_labels.get("pod", ""),
                deployment_name=primary_labels.get("deployment") or primary_labels.get("app"),
                fingerprint=primary_raw.get("fingerprint"),
                labels=primary_labels,
                annotations=primary_annotations,
                correlated_alerts=correlated_list,
            )

            key = self.get_incident_key(incident)
            self.mark_in_flight(key)

            if self._dispatch_callback:
                if self._settings.alert_debounce_seconds <= 0:
                    await self._dispatch_with_semaphore(incident, key)
                else:
                    asyncio.create_task(self._dispatch_with_semaphore(incident, key))

    async def _dispatch_with_semaphore(self, incident: Incident, key: str) -> None:
        try:
            async with self._semaphore:
                if self._dispatch_callback:
                    await self._dispatch_callback(incident)
        finally:
            self.mark_completed(key)

    async def _notify_storm(self, alerts: list[dict[str, Any]], count: int) -> None:
        if not self._chat_manager:
            return

        alert_names = [a.get("labels", {}).get("alertname", "UnknownAlert") for a in alerts]
        summary_text = (
            f"⚡ **Alert Storm Circuit Breaker Activated**\n\n"
            f"Received **{count} alerts** within {self._settings.alert_storm_window_seconds}s. "
            f"Automated LLM investigations are paused for {self._settings.alert_storm_cooldown_seconds}s "
            f"to prevent trace explosion and token costs.\n\n"
            f"**Recent Alerts:**\n" + "\n".join(f"- `{name}`" for name in alert_names[:10])
        )

        try:
            if hasattr(self._chat_manager, "broadcast_message"):
                await self._chat_manager.broadcast_message(summary_text)
            elif hasattr(self._chat_manager, "send_message"):
                await self._chat_manager.send_message(
                    self._settings.telegram_default_chat_id or "", summary_text
                )
        except Exception:
            logger.exception("Failed to send storm notification to chat manager")
