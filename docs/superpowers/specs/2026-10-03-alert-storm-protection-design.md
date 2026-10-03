# Alert Storm Protection & Cascade Trace Spam Prevention Design

## 1. Problem Statement

In Kubernetes and distributed homelab environments, an infrastructure failure (e.g., a node going offline, a network partition, or a core dependency failing) triggers cascading failure modes. Prometheus Alertmanager dispatches multiple firing alerts across many pods, services, and probes within seconds.

Currently, LYOKO's webhook receiver (`handle_alertmanager_webhook`) iterates through every firing alert in `payload["alerts"]` and immediately schedules an independent LangGraph agent execution (`engine.ainvoke`). Each execution spins up a multi-agent LangGraph run (Supervisor + Domain Specialists for Diagnose, Remediate, and Verify) with independent Langfuse traces. This causes:
1. **Severe Token Spend & API Cost Explosion**: Dozens of LLM reasoning loops running concurrently.
2. **Langfuse Trace Spam**: Cluttering observability dashboards with duplicate or redundant traces.
3. **Remediation Race Conditions**: Multiple agents attempting simultaneous mutations on the same Kubernetes deployments or nodes.

## 2. Architectural Objectives

1. **Debouncing & Batching**: Buffer incoming alerts across a short sliding window (e.g., 10 seconds) and aggregate related alerts into a single consolidated `Incident` with primary and correlated symptoms, launching **1 LangGraph trace** instead of $N$.
2. **In-Flight Deduplication & Cooldown**: Prevent launching duplicate investigation traces for resources (`namespace`, `resource`, or `fingerprint`) that are currently being remediated or recently resolved (flapping suppression).
3. **Global Concurrency Throttling**: Limit maximum simultaneous LangGraph incident investigations (default: 2).
4. **Circuit Breaker for Alert Storms**: If alert frequency exceeds a high-velocity threshold (e.g., >8 alerts in 60s), trip the circuit breaker: pause automated LLM investigations, aggregate the storm, and dispatch a single consolidated warning to Telegram.
5. **Strict Clean Architecture Compliance**: The protection logic must reside in the `application` layer (`AlertStormProtector`), domain models in `domain`, and FastAPI endpoints in `infrastructure/web/controller.py`. Zero vendor imports in domain/application layers.

---

## 3. System Architecture & Components

```
Alertmanager Webhook (HTTP POST /webhook/alertmanager)
                       │
                       ▼
         [ FastAPI Webhook Controller ]
                       │
                       ▼
       [ AlertStormProtector (Application Service) ]
       ┌──────────────────────────────────────────────┐
       │ 1. Velocity Monitor & Circuit Breaker        │
       │    - Tripped? -> Post Telegram Storm Alert   │
       │                                              │
       │ 2. In-Flight Lock & Cooldown Checker         │
       │    - Active / Cooldown? -> Drop / Correlate  │
       │                                              │
       │ 3. Debounce & Aggregation Buffer (10s)       │
       │    - Group by (namespace / root cause)       │
       │    - Emit single consolidated Incident       │
       │                                              │
       │ 4. Concurrency Semaphore (max 2 incidents)   │
       └──────────────────────────────────────────────┘
                       │ (Dispatches 1 Trace)
                       ▼
          [ LangGraph Incident Workflow ]
    (Diagnose -> Remediate -> Verify -> Notify)
```

### 3.1. Domain Models (`lyoko.domain.models.incident`)
- `Incident`:
  - `alert_name: str`
  - `namespace: str = ""`
  - `pod_name: str = ""`
  - `deployment_name: str | None = None`
  - `fingerprint: str | None = None`
  - `labels: dict[str, str]`
  - `annotations: dict[str, str]`
  - `correlated_alerts: list[dict[str, Any]] = field(default_factory=list)`: List of secondary alerts grouped into this incident during the debounce window.

### 3.2. Application Service: `AlertStormProtector` (`lyoko.application.alert_guard`)
The protector orchestrates the safety harness before any LangGraph workflow is initiated:

1. **Velocity Meter & Circuit Breaker**:
   - Tracks a sliding window of alert timestamps.
   - States:
     - `CLOSED`: Normal operation.
     - `OPEN`: Storm threshold exceeded. Automated LLM runs paused. Alerts are collected and periodically batched into a single Telegram notification.
     - `HALF_OPEN`: Transition state after cooldown period without new excessive alerts.
2. **In-Flight Lock & Flapping Cooldown**:
   - `in_flight_keys: set[str]`: Active incident keys (e.g., `incident-{fingerprint}` or `incident-{namespace}-{deployment}`).
   - `cooldown_cache: dict[str, float]`: Expiration timestamps for recently completed incidents.
3. **Debounce Buffer (`AsyncBatcher`)**:
   - Collects incoming alerts for `debounce_seconds` (default: 10s).
   - Groups alerts by namespace and primary target.
   - Selects the most critical alert as the primary `Incident` and attaches the rest as `correlated_alerts`.
4. **Concurrency Limiter (`asyncio.Semaphore`)**:
   - Bounds concurrent LangGraph executions to `max_concurrent_incidents`.

### 3.3. Configuration (`lyoko.config.AgentSettings`)
- `alert_debounce_seconds: float = 10.0`
- `alert_storm_threshold: int = 8`
- `alert_storm_window_seconds: int = 60`
- `alert_storm_cooldown_seconds: int = 120`
- `alert_dedup_cooldown_seconds: int = 300`
- `max_concurrent_incidents: int = 2`

---

## 4. LangGraph Incident Context & Prompt Updates

When `correlated_alerts` are present in `Incident`, `lyoko.application.workflow._incident_context` formats them into the prompt for the supervisor and domain specialists:

```text
Alert: KubeNodeNotReady
Namespace: default
Pod: (none)
Deployment: (none)
Labels:
- alertname: KubeNodeNotReady
- node: k8s-worker-1

Correlated / Cascade Symptoms (3):
- KubePodCrashLooping (namespace: monitoring, pod: prometheus-k8s-0)
- TargetDown (job: node-exporter, instance: 192.168.1.50)
- IngressControllerDegraded (namespace: ingress-nginx)
```
This allows the LLM to immediately identify that the node failure is the root cause without investigating each symptom independently.

---

## 5. Verification & Testing Plan

1. **Unit Tests (`tests/agents/lyoko/test_alert_guard.py`)**:
   - Test debounce window grouping multiple alerts into a single incident.
   - Test in-flight lock rejecting duplicate alerts for active incidents.
   - Test cooldown rejecting flapping alerts within the cooldown TTL.
   - Test circuit breaker opening when receiving > threshold alerts in the window.
   - Test circuit breaker sending consolidated Telegram alert and resetting after cooldown.
2. **Integration Tests (`tests/agents/lyoko/test_webhook_controller.py`)**:
   - Test sending a batch of 20 alerts via `/webhook/alertmanager`: verify only 1 batched workflow or circuit breaker notification is triggered.
3. **Clean Architecture Tests**:
   - Run `pytest tests/test_clean_architecture.py` to ensure zero boundary leaks and 0-byte `__init__.py` files.
