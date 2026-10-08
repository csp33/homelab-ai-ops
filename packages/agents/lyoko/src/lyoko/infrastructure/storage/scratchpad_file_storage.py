"""Local filesystem adapter for scratchpad tool output offloading."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from lyoko.domain.interfaces.scratchpad import ScratchpadStorageInterface
from lyoko.domain.models.scratchpad import ScratchpadReference


class ScratchpadFileStorage(ScratchpadStorageInterface):
    """Stores oversized tool outputs as files on disk and returns references."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        if base_dir is None:
            self._base_dir = Path(".lyoko") / "scratchpad"
        else:
            self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    @property
    def base_dir(self) -> Path:
        """The root directory where scratchpad files reside."""
        return self._base_dir

    async def store_output(
        self,
        tool_name: str,
        raw_output: str,
        session_id: str | None = None,
    ) -> ScratchpadReference:
        """Save raw tool output to a file and return a reference metadata object."""
        ref_id = f"scratch_{uuid.uuid4().hex[:12]}"
        safe_tool = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in tool_name)
        filename = f"{ref_id}_{safe_tool}.log"
        file_path = self._base_dir / filename

        file_path.write_text(raw_output, encoding="utf-8")
        line_count = len(raw_output.splitlines())
        size_bytes = file_path.stat().st_size
        created_at = datetime.now(UTC).isoformat()

        return ScratchpadReference(
            reference_id=ref_id,
            file_path=str(file_path.resolve()),
            size_bytes=size_bytes,
            line_count=line_count,
            tool_name=tool_name,
            created_at_iso=created_at,
        )

    async def read_output(self, reference_id: str) -> str | None:
        """Retrieve output content given a reference identifier."""
        matched = list(self._base_dir.glob(f"{reference_id}_*.log"))
        if not matched:
            return None
        return matched[0].read_text(encoding="utf-8")
