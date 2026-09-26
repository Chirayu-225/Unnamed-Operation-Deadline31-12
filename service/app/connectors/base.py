"""
Connector adapter interface.

Every connector's only job is: given credentials/config, produce
CanonicalTable objects. Nothing about the source's native API, auth
model, or format should leak past `extract()`. This is the interface
that makes the system genuinely source-agnostic rather than
Salesforce-shaped with other sources bolted on.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from app.canonical.models import CanonicalTable


class ConnectorConfig(BaseModel):
    tenant_id: str
    source_id: str
    # Connector-specific settings (file path, connection string, OAuth
    # tokens, etc.) live here as an opaque dict validated by the
    # concrete connector, not by this base class.
    settings: dict[str, Any] = {}


class Connector(ABC):
    """Base class every connector (CSV, SQL, REST, Salesforce, ...)
    must implement."""

    def __init__(self, config: ConnectorConfig):
        self.config = config

    @abstractmethod
    def test_connection(self) -> bool:
        """Cheap check that credentials/config are valid, without
        pulling data. Used by the UI before a full scan."""
        raise NotImplementedError

    @abstractmethod
    def extract(self) -> list[CanonicalTable]:
        """Pull data from the source and return it already normalized
        into the canonical shape. This is the one method every
        connector must get right — everything downstream trusts its
        output completely."""
        raise NotImplementedError
