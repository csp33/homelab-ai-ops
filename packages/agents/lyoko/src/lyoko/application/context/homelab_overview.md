# Homelab Architecture & Hardware Topology

The homelab runs a 3-node bare-metal Kubernetes cluster managed via GitOps with Argo CD.

## Physical Bare-Metal Server Nodes
- **`tresberto`** (Primary Compute & Storage Node):
  - **CPU**: Intel Core 13th Gen (24 threads / vCPUs).
  - **Memory**: 64 GB DDR4 RAM.
  - **Storage**: NVMe SSD (OS + host-path cache) + 2x 4TB Enterprise HDDs configured as ZFS RAID-1 mirror (`3.6 TB` usable pool).
  - **Attached Hardware**: Sonoff Zigbee 3.0 USB Plus dongle (passed to Zigbee2MQTT / Home Assistant workloads).
- **`humberto`** (Worker & etcd Quorum Node):
  - **CPU**: Intel Core 7th Gen (4 threads / vCPUs).
  - **Memory**: 16 GB DDR4 RAM.
  - **Storage**: High-speed SATA SSD.
- **`dosberto`** (Worker & etcd Quorum Node):
  - **CPU**: Intel Core 6th Gen (4 threads / vCPUs).
  - **Memory**: 28 GB DDR4 RAM.
  - **Storage**: High-speed SATA SSD.

## Cluster Summary
- **Total Compute**: 28 vCPUs / 108 GB RAM across 3 physical chassis.
- **High Availability**: 100% 3-node etcd quorum with distributed control plane.
- **Network Fabric**: UniFi UDM Pro gateway, UniFi switches, and dedicated VLANs (`192.168.33.0/24` Homelab LAN, `192.168.1.0/24` Management/WireGuard).
