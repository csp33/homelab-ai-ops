# Homelab Topology & Pinned Resources

The homelab runs a 3-node bare-metal Kubernetes cluster managed via GitOps with Argo CD.

## Physical Nodes & Attached Roles
- **`tresberto`**:
  - **Pinned Storage**: Hosts the local ZFS RAID-1 mirror storage pool (Tier 3 storage).
- **`dosberto`**:
  - **Pinned Physical Hardware**: Hosts the USB Sonoff MG24 Zigbee coordinator (`/dev` hostPath) and local-path volume pinned for `zigbee2mqtt`.
- **`humberto`**:
  - Worker compute and etcd quorum node running distributed stateless and Longhorn-backed workloads.

## Network Subnets
- **Homelab LAN**: `192.168.33.0/24` (Gateway: UniFi UDM Pro `192.168.33.1`).
- **Management & WireGuard VPN**: `192.168.1.0/24`.
