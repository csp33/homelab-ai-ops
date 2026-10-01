"""Authentication domain models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthIdentity:
    authenticated: bool
    user: str
    auth_type: str
    name: str | None = None
