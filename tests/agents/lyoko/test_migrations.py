"""Tests for Alembic migrations in LYOKO."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_config_and_revisions():
    """Verify alembic config is valid and migration 0001 is present."""
    base_dir = Path(__file__).parent.parent.parent.parent / "packages" / "agents" / "lyoko"
    ini_path = base_dir / "alembic.ini"

    assert ini_path.exists(), f"alembic.ini not found at {ini_path}"

    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(base_dir / "migrations"))

    script_dir = ScriptDirectory.from_config(alembic_cfg)
    heads = script_dir.get_heads()

    assert len(heads) == 1
    assert heads[0] == "0001"

    rev = script_dir.get_revision("0001")
    assert rev is not None
    assert rev.doc == "create agent memory table with pgvector"


def test_alembic_url_with_special_characters_escaping():
    """Verify that URL-encoded passwords with % do not cause configparser interpolation errors."""
    from lyoko.config import AgentSettings

    settings = AgentSettings(
        postgres_user="lyoko",
        postgres_password="s0RFCk3xV2hj6t5td1Sa3lL5Xw/9QTo+MVPwVNlFkJw=",
        postgres_host="postgres.local",
        postgres_port=5432,
        postgres_db="lyoko",
    )
    db_uri = settings.get_postgres_uri()
    assert "%2F" in db_uri or "%2B" in db_uri or "%3D" in db_uri

    base_dir = Path(__file__).parent.parent.parent.parent / "packages" / "agents" / "lyoko"
    ini_path = base_dir / "alembic.ini"
    alembic_cfg = Config(str(ini_path))
    # Should not raise ValueError: invalid interpolation syntax
    alembic_cfg.set_main_option("sqlalchemy.url", db_uri.replace("%", "%%"))
    retrieved = alembic_cfg.get_main_option("sqlalchemy.url")
    assert retrieved == db_uri
