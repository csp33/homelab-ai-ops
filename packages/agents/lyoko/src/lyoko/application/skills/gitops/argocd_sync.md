# ArgoCD OutOfSync & SyncFailed Runbook
<!-- description: Diagnostic steps for ArgoCD application synchronization failures and drift -->
<!-- patterns: ArgoAppOutOfSync, ArgoAppSyncFailed, ComparisonError, GitOpsDrift -->

## Objective
Identify git commit drift, manifest validation errors, or resource pruning blocks in ArgoCD.

## Diagnostic Protocol
1. Check the application sync status:
   - Identify whether the status is `OutOfSync` or `SyncFailed`.
2. Inspect the difference:
   - Verify whether live cluster resources were manually mutated (causing drift with Git).
   - Check if an upstream CRD schema mismatch prevents applying the manifest.
3. Check Git repository accessibility:
   - Verify if credentials or webhook connectivity to GitHub/GitLab failed.
