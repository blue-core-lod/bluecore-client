"""A Python client for the Blue Core API.

Reads return JSON-LD as plain dictionaries. Other RDF serializations are
available on request.

    >>> from bluecore_client import BluecoreClient
    >>> client = BluecoreClient()
    >>> work = client.works.get("4403fbce-ba01-5a4e-a8fc-03fc71caf56d")
"""

from bluecore_client.client import BluecoreClient
from bluecore_client.config import Config
from bluecore_client.errors import (
    APIError,
    AuthError,
    BluecoreError,
    ConfigError,
    ConnectionFailed,
    NotFound,
    PermissionDenied,
    Redirected,
    ValidationError,
)
from bluecore_client.pagination import Page, Pages
from bluecore_client.resources.search import SearchType

__all__ = [
    "APIError",
    "AuthError",
    "BluecoreClient",
    "BluecoreError",
    "Config",
    "ConfigError",
    "ConnectionFailed",
    "NotFound",
    "Page",
    "Pages",
    "PermissionDenied",
    "Redirected",
    "SearchType",
    "ValidationError",
]
