"""Domain models for tool execution output buffering and scratchpad offloading."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ScratchpadReference:
    """Reference pointer to offloaded tool output stored on disk."""

    reference_id: str
    file_path: str
    size_bytes: int
    line_count: int
    tool_name: str
    created_at_iso: str


@dataclass(frozen=True)
class SmartBufferConfig:
    """Configuration governing head-and-tail truncation and offload thresholds."""

    max_chars: int = 4000
    offload_threshold_chars: int = 15000
    head_ratio: float = 0.25
