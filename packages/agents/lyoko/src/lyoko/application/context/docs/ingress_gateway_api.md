# Ingress, Routing & Gateway API Architecture

The cluster routes ingress traffic through 3 dedicated Envoy Gateway data planes managed via Gateway API (`gateway.networking.k8s.io`):

## 1. Triple Envoy Gateway Planes
1. **`envoy-vps-ingress` (Open Public / Anti-ISP Block Bypass)**:
   - **VIP / Endpoint**: MetalLB `192.168.33.201` (TCP 80/443).
   - **Routing Architecture**: External traffic hits an Oracle Cloud Always-Free VPS Bastion (`51.170.41.131` in Madrid `eu-madrid-1`). The VPS runs HAProxy in TCP SNI passthrough mode over a WireGuard tunnel (`192.168.1.5` -> UDM Pro -> `192.168.33.201`).
   - **Security & TLS**: The VPS does NOT decrypt TLS. `cert-manager` inside the cluster terminates `wildcard-cspaez.org-tls`.
   - **Use Case**: Public services immune to Spanish ISP/LaLiga dynamic IP blocks (`cspaez.org`, `gambling-song.cspaez.org`).
2. **`envoy-cloudflare-tunnel` (Public with Zero Trust Auth)**:
   - **Routing Architecture**: Internal `cloudflared` daemon connects outbound to Cloudflare Edge.
   - **Security**: Cloudflare Access enforces Zero Trust authentication (Google Auth / mTLS).
   - **Use Case**: Administrative and self-hosted apps (`argocd.cspaez.org`, `immich.cspaez.org`, `homeassistant.cspaez.org`, `nextcloud.cspaez.org`, `grafana.cspaez.org`, `gatus.cspaez.org`, `vaultwarden.cspaez.org`, `umami.cspaez.org`).
3. **`envoy-internal` (LAN / Local WireGuard)**:
   - **VIP / Endpoint**: MetalLB `192.168.33.200` (Internal LAN / WireGuard VPN on `*.internal.cspaez.org`).
   - **Use Case**: Purely private cluster services without public exposure.

## 2. Gateway API & RBAC Capabilities
- The `lyoko` ServiceAccount is equipped with RBAC permissions on `gateway.networking.k8s.io`:
  - Resources: `httproutes`, `gateways`.
  - Verbs: `get`, `list`, `watch`.
- Use Gateway API inspection to verify `HTTPRoute` bindings, route conditions, parent Gateway references, and hostname mappings during incident investigation.
