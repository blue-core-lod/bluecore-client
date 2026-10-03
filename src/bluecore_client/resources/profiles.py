"""Resource profiles, e.g. Sinopia profiles."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from bluecore_client.identifiers import extract_uuid
from bluecore_client.pagination import DEFAULT_LIMIT, Pages
from bluecore_client.resources.base import Collection


class Profiles(Collection):
    """Profiles describing how a resource should be edited."""

    path = "profiles"
    collection_key = "profiles"

    def list(self, *, limit: int = DEFAULT_LIMIT, offset: int = 0) -> Pages:
        """Page through every profile."""
        return self._paged(limit=limit, offset=offset)

    def search(self, *, limit: int = DEFAULT_LIMIT, offset: int = 0) -> Pages:
        """Page through profiles via the search index.

        Unlike :meth:`list`, this is the endpoint that carries each profile's
        full ``data``, which is what makes it the useful one for copying
        profiles between deployments.
        """
        return self._paged(limit=limit, offset=offset, path="/search/profile")

    def get(self, profile_uuid: str) -> dict[str, Any]:
        """Fetch one profile by UUID, or by its Blue Core URI."""
        return self._client.get_json(f"/{self.path}/{self._identify(profile_uuid)}")

    def _identify(self, value: str) -> str:
        """Accept either a UUID or a full Blue Core URI."""
        return extract_uuid(value, expected=self.path)

    def find(self, uri: str) -> dict[str, Any]:
        """Look a profile up by its URI."""
        return self._client.get_json(f"/{self.path}/", params={"uri": uri})

    def create(self, data: dict[str, Any] | str) -> dict[str, Any]:
        """Create a profile.

        The API mints a fresh URI and rewrites the profile's resource template
        to match, so the created profile's URI will not be the one you passed
        in.
        """
        return self._client.post_json(f"/{self.path}/", {"data": _as_text(data)})

    def update(self, profile_uuid: str, data: dict[str, Any] | str) -> dict[str, Any]:
        """Replace a profile's data."""
        return self._client.post_json(
            f"/{self.path}/{self._identify(profile_uuid)}",
            {"data": _as_text(data)},
            method="PUT",
        )

    def delete(self, profile_uuid: str) -> None:
        """Delete a profile, along with its versions and classes."""
        self._client.request("DELETE", f"/{self.path}/{self._identify(profile_uuid)}")


def _as_text(data: dict[str, Any] | str) -> str:
    """The profiles API takes ``data`` as a JSON string, not an object."""
    return data if isinstance(data, str) else json.dumps(data)


SINOPIA = "http://sinopia.io/vocabulary/"

#: The predicate a profile uses to name another profile that it nests.
HAS_RESOURCE_TEMPLATE_ID = "hasResourceTemplateId"


def _local_name(key: str) -> str:
    """The local name of a JSON-LD key, expanded or prefixed.

    A profile is stored in whatever shape it was sent -- Blue Core does not
    frame profiles -- so a predicate may arrive as the full URI or as
    ``sinopia:hasResourceId``. Matching on the local name reads both without
    having to resolve an @context.
    """
    return key.rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _objects(data: Any, local_name: str) -> list[Any]:
    """Every JSON-LD object node recorded under the given predicate."""
    found: list[Any] = []
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if _local_name(key) == local_name:
                    found.extend(value if isinstance(value, list) else [value])
                else:
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
    return found


def _written(obj: Any) -> str | None:
    """The written form of a JSON-LD object: IRI, literal, or bare string."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        value = obj.get("@id") or obj.get("@value")
        return value if isinstance(value, str) else None
    return None


def references(data: Any) -> set[str]:
    """The profiles this profile's data says it nests, as written."""
    return {
        value
        for obj in _objects(data, HAS_RESOURCE_TEMPLATE_ID)
        if (value := _written(obj))
    }


def relink(data: Any, remap: dict[str, str]) -> tuple[Any, set[str]]:
    """Point every nesting reference at its counterpart in ``remap``.

    Returns the rewritten document and the references ``remap`` had nothing
    for. The original is left alone, so a caller can tell whether anything
    changed by comparing the two.

    ``remap`` is keyed by source URI. A profile names the profiles it nests by
    URI, and a URI identifies a row in one deployment's database, so copying a
    profile anywhere else leaves those references pointing home until they are
    rewritten.
    """
    rewritten = deepcopy(data)
    unresolved = set()
    for obj in _objects(rewritten, HAS_RESOURCE_TEMPLATE_ID):
        written = _written(obj)
        if written is None:
            continue
        target = remap.get(written)
        if target is None:
            unresolved.add(written)
            continue
        if not isinstance(obj, dict):
            # A bare string cannot be rewritten in place. Expanded documents
            # always use an object node, so this is a shape worth reporting
            # rather than guessing at.
            unresolved.add(written)
            continue
        obj.pop("@value", None)
        obj.pop("@language", None)
        obj["@id"] = target
    return rewritten, unresolved
