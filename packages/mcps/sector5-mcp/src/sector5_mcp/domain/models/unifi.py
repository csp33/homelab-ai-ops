"""UniFi domain models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkClient:
    hostname: str
    ip: str | None
    mac: str
    is_wired: bool = False
    network: str | None = None
    rx_bytes: int = 0
    tx_bytes: int = 0
    uptime_seconds: int = 0


@dataclass(frozen=True)
class NetworkDevice:
    name: str
    model: str | None
    type: str | None
    ip: str | None
    mac: str
    state: int | None = None
    version: str | None = None
    uptime_seconds: int = 0
    cpu_usage: float | None = None
    memory_usage: float | None = None
