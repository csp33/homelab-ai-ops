"""Prompt loader for LYOKO application prompts stored as markdown files."""

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


class PromptLoader:
    """Loads markdown prompt templates from the application prompts directory."""

    def __init__(self, prompts_dir: Path | None = None) -> None:
        self.prompts_dir = prompts_dir or _PROMPTS_DIR

    def load_prompt(self, filename: str) -> str:
        """Load a markdown prompt file relative to the prompts directory."""
        path = self.prompts_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8").strip()


_DEFAULT_LOADER = PromptLoader()
load_prompt = _DEFAULT_LOADER.load_prompt
