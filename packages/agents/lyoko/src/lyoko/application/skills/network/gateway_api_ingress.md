---
name: gateway_api_ingress
description: Use when HTTPRoute resolution fails, Envoy Gateway ingress drops traffic, or Cloudflare/VPS tunnels disconnect
patterns:
  - IngressDegraded
  - GatewayNotProgrammed
  - HTTPRouteNotAccepted
  - CloudflareTunnelDown
  - EnvoyGatewayDown
---

# Gateway API & Homelab Ingress Runbook

## Overview
Diagnostic protocol for the 3-plane Envoy Gateway ingress architecture, HTTPRoutes, and ingress tunnels.

## When to Use
- HTTPRoute resources report `Accepted: False` or `Programmed: False`.
- Ingress traffic to `*.cspaez.org` or `*.internal.cspaez.org` fails or drops connections.
- Cloudflare Tunnel daemon reports disconnected status.
- When NOT to use: Workload container crashes behind a functional ingress (use `k8s-pod-crashloop`).

## Ingress Planes Reference
1. **`envoy-vps-ingress` (Public / Anti-ISP Block Bypass)**:
   - Endpoint: MetalLB `192.168.33.201` (TCP 80/443).
   - Upstream: HAProxy on Oracle Cloud Always-Free VPS (`51.170.41.131` in Madrid) forwarding via WireGuard (`192.168.1.5`).
   - TLS: In-cluster `cert-manager` terminates `wildcard-cspaez.org-tls`.
2. **`envoy-cloudflare-tunnel` (Public with Zero Trust Auth)**:
   - Daemon: Internal `cloudflared` connecting outbound to Cloudflare Edge.
   - Security: Cloudflare Access Zero Trust authentication.
3. **`envoy-internal` (LAN / Local WireGuard)**:
   - Endpoint: MetalLB `192.168.33.200` (`*.internal.cspaez.org`).

## Diagnostic Protocol
1. **HTTPRoute Inspection**:
   - Query `httproutes` in `gateway.networking.k8s.io`: check `status.parents` for `Accepted` and `Programmed` conditions.
2. **Gateway Plane Status**:
   - Verify Envoy Gateway controller pods and proxy daemonsets in `envoy-gateway-system`.
3. **Tunnel Health Check**:
   - For public apps, verify `cloudflared` pod logs or VPS WireGuard tunnel interface ping.

## Common Mistakes
- Modifying Envoy Gateway configs directly instead of declarative `HTTPRoute` resources in GitOps.
