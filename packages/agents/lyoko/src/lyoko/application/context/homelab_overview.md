# Homelab Topology & Pinned Resources

The homelab runs a 3-node bare-metal Kubernetes cluster managed via GitOps with Argo CD.

## Physical Nodes & Attached Hardware Roles
- **`tresberto`**:
  - **Pinned Storage**: Hosts the local ZFS RAID-1 mirror storage pool.
  - **Pinned Physical Hardware**: Sonoff Zigbee 3.0 USB Plus coordinator dongle attached locally via USB serial passthrough. Workloads requiring Zigbee (e.g. Zigbee2MQTT / Home Assistant) are node-pinned here.
- **`humberto` & `dosberto`**:
  - General compute and etcd quorum nodes running distributed stateless and Longhorn-backed workloads.

## Network Subnets
- **Homelab LAN**: `192.168.33.0/24` (Gateway: UniFi UDM Pro `192.168.33.1`).
- **Management & WireGuard VPN**: `192.168.1.0/24`.
