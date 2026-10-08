---
name: pvc_pending_storage
description: Use when PersistentVolumeClaims are stuck in Pending, volume attachments fail, or PVCs fill up
patterns:
  - KubePersistentVolumeFillingUp
  - VolumePending
  - ProvisioningFailed
  - FailedAttachVolume
  - PersistentVolumeClaimPending
  - Multi-Attach error
---

# Kubernetes PVC Pending & Storage Runbook

## Overview
Diagnostic protocol for unattached volumes, pending claims, and distributed storage deadlocks (Longhorn).

## When to Use
- PVCs remain in `Pending` phase without binding to a PersistentVolume.
- Pod scheduling or startup fails with `FailedAttachVolume` or `Multi-Attach error for volume`.
- Prometheus alerts trigger `KubePersistentVolumeFillingUp`.
- When NOT to use: Pod terminates due to internal application errors (use `k8s-pod-crashloop`).

## Diagnostic Protocol
1. **PVC Binding Status & Events**:
   - Inspect PVC resource and events to identify if the requested `StorageClass` is available and has an active provisioner.
   - Look for CSI driver timeouts or missing physical volumes.
2. **Volume Attachment Deadlock Check (Longhorn RWO)**:
   - For single-replica workloads (`replicas: 1`) mounting `ReadWriteOnce` (RWO) Longhorn volumes, check `strategy.type`.
   - Single-replica RWO deployments **must** configure `strategy.type: Recreate` instead of `RollingUpdate` to prevent multi-attach deadlocks.
3. **Volume Capacity Inspection**:
   - For `KubePersistentVolumeFillingUp`, compare filesystem usage against PVC capacity threshold.
   - Determine whether data prune or volume size expansion (`spec.resources.requests.storage`) is necessary.

## Quick Reference
| Symptom | Error Pattern | Resolution |
|---|---|---|
| Multi-Attach Deadlock | `Multi-Attach error for volume` | Change Deployment strategy to `type: Recreate` |
| Missing Provisioner | `no volume plugin matched` | Verify CSI driver status and StorageClass provisioner |
| Storage Exhaustion | `KubePersistentVolumeFillingUp` | Prune cache files or increase PVC capacity |

## Common Mistakes
- Leaving `strategy.type: RollingUpdate` on single-replica workloads with Longhorn RWO volumes, causing attach-detach deadlocks during deployments.
