"""Modular homelab context loader for injecting infrastructure architecture into LYOKO agents."""

from pathlib import Path

_CONTEXT_DIR = Path(__file__).parent


def load_context(filename: str) -> str:
    """Load a markdown context document from the context directory."""
    path = _CONTEXT_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Homelab context file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def get_homelab_context(
    include_overview: bool = True,
    include_ingress: bool = True,
    include_storage: bool = True,
) -> str:
    """Combine selected homelab architectural context sections."""
    sections: list[str] = []

    if include_overview:
        sections.append(load_context("homelab_overview.md"))
    if include_ingress:
        sections.append(load_context("ingress_gateway_api.md"))
    if include_storage:
        sections.append(load_context("storage_and_gitops.md"))

    if not sections:
        return ""

    body = "\n\n".join(sections)
    return f"--- HOMELAB ARCHITECTURAL CONTEXT ---\n{body}\n--------------------------------------"


def build_agent_context(role: str) -> str:
    """Build tailored architecture context based on the agent's domain or role."""
    normalized_role = role.strip().lower()
    if normalized_role in {"k8s", "kubernetes", "diagnose", "remediate", "chat", "supervisor"}:
        return get_homelab_context(
            include_overview=True, include_ingress=True, include_storage=True
        )
    if normalized_role in {"network", "unifi"}:
        return get_homelab_context(
            include_overview=True, include_ingress=True, include_storage=False
        )
    if normalized_role in {"smarthome", "homeassistant"}:
        return get_homelab_context(
            include_overview=True, include_ingress=False, include_storage=False
        )
    if normalized_role in {"observability", "grafana", "prometheus"}:
        return get_homelab_context(
            include_overview=True, include_ingress=False, include_storage=True
        )

    return get_homelab_context()
