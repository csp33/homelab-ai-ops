# Storage Subsystem & GitOps Lifecycle

## 1. 3-Tier Storage Architecture
- **Tier 1 (Host Local NVMe / Fast Cache)**:
  - Local SSD/NVMe host paths for ephemeral scratch space, temp processing, and fast caches.
- **Tier 2 (Distributed Block Storage - Longhorn)**:
  - Synchronous 3-replica distributed block storage across `tresberto`, `humberto`, and `dosberto`.
  - Used for dynamic persistent volumes across cluster services requiring node-migration resilience.
- **Tier 3 (High-Capacity Resilient Pool - ZFS RAID-1)**:
  - Dedicated `3.6 TB` usable ZFS RAID-1 mirror on `tresberto` (2x 4TB Enterprise HDDs).
  - Used for large media libraries (Immich, Jellyfin, Nextcloud primary data) and backup archives.

## 2. Storage Operational Constraints (Critical Rule)
- **Deployment Strategy for RWO Volumes**:
  - Single-replica applications (`replicas: 1`) mounting `ReadWriteOnce` (RWO) PersistentVolumeClaims (specifically via Longhorn) **MUST** configure `strategy.type: Recreate` rather than `RollingUpdate`.
  - *Reason*: Default `RollingUpdate` spins up a new pod before terminating the old one, causing Kubernetes and Longhorn attach-detach controllers to fail with a `Multi-Attach error for volume` deadlock.

## 3. GitOps & Argo CD Lifecycle
- **Declarative Source of Truth**:
  - All deployments, Helm values, and manifests originate from the GitOps charts repository (`k8s-at-home-charts`).
  - Live resource patches (`kubectl patch`) can be reverted by Argo CD reconciliation. Prefer non-conflicting mutation techniques (scaling, rollout restarts, Argo CD sync/refresh) or proposing Git changes.
- **Argo CD RBAC Permissions (`argoproj.io`)**:
  - The `lyoko` ServiceAccount has RBAC permissions on `argoproj.io`:
    - Resources: `applications`, `applicationsets`, `appprojects`.
    - Verbs: `get`, `list`, `watch`, `patch`, `update`.
  - Use these permissions to inspect application sync status, health status, sync diffs, and trigger sync operations or refresh when needed.
- **Renovate Container Image Conventions**:
  - Vaultwarden uses Alpine tags (`*-alpine`).
  - Nextcloud uses Apache tags (`*-apache`).
  - Immich ML uses OpenVINO tags (`*-openvino`).
