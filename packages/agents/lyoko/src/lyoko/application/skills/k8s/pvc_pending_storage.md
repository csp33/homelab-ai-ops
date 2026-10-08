# Kubernetes PersistentVolumeClaim Pending Runbook
<!-- description: Diagnostic steps for PVCs stuck in Pending or volume attachment failures -->
<!-- patterns: KubePersistentVolumeFillingUp, VolumePending, ProvisioningFailed, FailedAttachVolume, PersistentVolumeClaimPending -->

## Objective
Diagnose why a storage volume is not bound or cannot be mounted to a pod.

## Diagnostic Protocol
1. Check the PVC status and events:
   - Verify if the `StorageClass` requested exists and has an active provisioner.
   - Look for events mentioning `no volume plugin matched` or CSI driver timeouts.
2. Check capacity constraints:
   - For `KubePersistentVolumeFillingUp`, inspect current usage vs capacity threshold.
   - Determine whether disk cleanup or storage expansion (`resize`) is needed.
3. Node attachment checks:
   - Check if the volume is stuck attached to another dead node (`VolumeAttachment` status).
