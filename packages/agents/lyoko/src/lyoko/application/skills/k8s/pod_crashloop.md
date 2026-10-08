# Kubernetes Pod CrashLoopBackOff Runbook
<!-- description: Diagnostic steps for pods restarting or crashing repeatedly in Kubernetes -->
<!-- patterns: CrashLoopBackOff, ContainerWaiting, PodFailed, Back-off restarting failed container, OOMKilled -->

## Objective
Identify why a container exits prematurely and formulate a safe remediation plan.

## Diagnostic Protocol
1. Check the previous container termination reason:
   - Call `k8s_get_pod_status` or inspect container statuses for `lastState.terminated.reason` and `exitCode`.
   - If `reason` is `OOMKilled` (exit code 137), check if memory limits are configured too tightly.
2. Read the latest logs, focusing on the last lines:
   - Call `k8s_get_pod_logs` with `previous=true` if available, or fetch recent lines.
   - Look for panic traces, missing environment variables, or database connection errors.
3. Inspect recent cluster events:
   - Check if node pressure or eviction triggered the termination.
