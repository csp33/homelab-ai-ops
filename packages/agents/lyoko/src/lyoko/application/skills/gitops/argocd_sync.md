---
name: argocd_sync
description: Use when Argo CD applications are OutOfSync, sync operations fail, or comparison errors occur
patterns:
  - ArgoAppOutOfSync
  - ArgoAppSyncFailed
  - ArgoCDAppOutOfSync
  - ArgoCDAppSyncFailed
  - ComparisonError
  - GitOpsDrift
---

# Argo CD Synchronization & GitOps Runbook

## Overview
Diagnostic protocol for Argo CD application sync failures, schema validation errors, and GitOps configuration drift.

## When to Use
- Argo CD alerts fire for `ArgoCDAppOutOfSync` or `ArgoCDAppSyncFailed`.
- Applications report status conditions with `ComparisonError`.
- Manual cluster mutations drifted from declarative Git repository source of truth.
- When NOT to use: Pod crash loops inside a healthy, fully-synced application (use `k8s-pod-crashloop`).

## Diagnostic Protocol
1. **Query Application CRD (`argoproj.io/v1alpha1`)**:
   - Argo CD Application resources **always reside in namespace `argocd`**.
   - Call `k8s_resources_get(apiVersion="argoproj.io/v1alpha1", kind="Application", name="<app-name>", namespace="argocd")`.
2. **Inspect Operation and Sync State**:
   - Check `.status.operationState.phase` for `Failed` or `Error`.
   - Inspect `.status.operationState.message` to read the exact failure message.
   - Inspect `.status.operationState.syncResult.resources` to find which resource failed hooks or reconciliation.
3. **Check Sync Policy & Self-Healing**:
   - Check `.spec.syncPolicy.automated`. If automated sync is missing or disabled and the failure is non-breaking drift, enabling autosync (`prune: true, selfHeal: true`) may resolve it.
   - For `ComparisonError`, verify if an upstream CRD schema mismatch or invalid YAML prevents rendering.

## Quick Reference
| Status Phase | Common Root Cause | Recommended Action |
|---|---|---|
| OutOfSync | Autosync disabled or manual cluster edit | Inspect diff; enable autosync or commit to Git |
| ComparisonError | Invalid Helm/Kustomize manifest syntax | Check Git commit history for syntax errors |
| HookFailed | PreSync/PostSync Job failed or timed out | Inspect logs of the hook Pod in destination namespace |

## Common Mistakes
- Querying the Application CRD in the target workload namespace instead of namespace `argocd`.
- Applying live mutations (`kubectl patch`) that Argo CD reconciliation immediately reverts.
