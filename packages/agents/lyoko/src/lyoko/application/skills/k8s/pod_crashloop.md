---
name: pod_crashloop
description: Use when pods are restarting repeatedly, failing to start, or reporting CrashLoopBackOff or OOMKilled
patterns:
  - CrashLoopBackOff
  - ContainerWaiting
  - PodFailed
  - Back-off restarting failed container
  - OOMKilled
---

# Kubernetes Pod CrashLoopBackOff Runbook

## Objective
Diagnostic protocol for investigating premature container terminations and restart loops in Kubernetes workloads.

## When to Use
- Pod container status indicates `CrashLoopBackOff` or `ContainerWaiting`.
- Pod termination reason is `OOMKilled` or non-zero exit code (e.g. 1, 137, 139).
- When NOT to use: Pod is stuck in `Pending` due to PVC volume binding or node scheduling constraints.

## Diagnostic Protocol
1. **Container Termination State**:
   - Call `k8s_pods_get` or inspect container statuses for `lastState.terminated.reason` and `exitCode`.
   - If `reason` is `OOMKilled` (exit code 137), compare working set memory against configured `limits.memory`.
2. **Container Logs**:
   - Call `k8s_pods_logs` with `previous=true` to retrieve logs from the terminated instance before restart.
   - Search for panic traces, missing environment variables, or database connection refusals.
3. **Cluster Events**:
   - Inspect warning events for the pod namespace to rule out node pressure, evictions, or failed liveness probes.

## Quick Reference
| Symptom | Exit Code | Action |
|---|---|---|
| OOMKilled | 137 | Increase memory limit or tune heap size |
| Configuration Error | 1 | Verify Secret/ConfigMap mounts and environment variables |
| Failed Liveness Probe | - | Check endpoint latency or increase `initialDelaySeconds` |

## Common Mistakes
- Checking current live logs instead of `previous=true` logs after a container has already restarted.
- Restarting a crashlooping pod without inspecting the prior termination exit code and reason.
