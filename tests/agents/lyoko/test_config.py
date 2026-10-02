"""Unit tests for LYOKO agent configuration and database URI generation."""

from lyoko.config import AgentSettings


def test_postgres_uri_not_set():
    settings = AgentSettings(postgres_password="")
    assert settings.get_postgres_uri() is None


def test_postgres_uri_constructed_from_components():
    settings = AgentSettings(
        postgres_host="pg.internal",
        postgres_port=5432,
        postgres_user="testuser",
        postgres_password="secretpassword",
        postgres_db="testdb",
    )
    assert (
        settings.get_postgres_uri()
        == "postgresql://testuser:secretpassword@pg.internal:5432/testdb"
    )


def test_postgres_uri_explicit_override():
    settings = AgentSettings(
        postgres_uri="postgresql://custom:custom@localhost:5433/customdb",
        postgres_password="ignoredpassword",
    )
    assert settings.get_postgres_uri() == "postgresql://custom:custom@localhost:5433/customdb"


def test_postgres_uri_with_special_characters():
    settings = AgentSettings(
        postgres_host="pg.internal",
        postgres_port=5432,
        postgres_user="user/name",
        postgres_password="p+w/d=123",
        postgres_db="testdb",
    )
    assert (
        settings.get_postgres_uri()
        == "postgresql://user%2Fname:p%2Bw%2Fd%3D123@pg.internal:5432/testdb"
    )
