"""The Blue Core client."""

from __future__ import annotations

import json as jsonlib
from types import TracebackType
from typing import Any, Self

import httpx

from bluecore_client import config as config_module
from bluecore_client import formats
from bluecore_client.auth import KeycloakAuth
from bluecore_client.config import Config
from bluecore_client.errors import (
    AuthError,
    BluecoreError,
    ConnectionFailed,
    raise_for_status,
)
from bluecore_client.resources.batches import Batches
from bluecore_client.resources.change_documents import ChangeDocuments
from bluecore_client.resources.convert import Convert
from bluecore_client.resources.export import Export
from bluecore_client.resources.hubs import Hubs
from bluecore_client.resources.instances import Instances
from bluecore_client.resources.other_resources import OtherResources
from bluecore_client.resources.profiles import Profiles
from bluecore_client.resources.search import Search
from bluecore_client.resources.works import Works

#: JSON-LD is what create and update bodies are sent as, since the API accepts
#: a raw graph under that content type and wraps it for us.
JSONLD_CONTENT_TYPE = "application/ld+json"

DEFAULT_TIMEOUT = 30.0

#: Distinguishes "not fetched yet" from a deployment that has no context.
_UNFETCHED = object()


class BluecoreClient:
    """Talk to a Blue Core API.

    The simplest useful form reads everything it needs from the environment::

        client = BluecoreClient()
        work = client.works.get(uuid)

    ``work`` is a plain dictionary of JSON-LD.

    Settings can also be passed directly::

        client = BluecoreClient(
            bluecore_url="https://bcld.info/",
            username="me",
            password="...",
        )

    Pass ``api_url`` instead of ``bluecore_url`` when the API isn't under
    ``/api`` -- notably the development server on ``http://localhost:3000``.

    Pass ``anonymous=True`` to skip authentication entirely, which works for
    another deployment's public read endpoints.

    Redirects are never followed. The client's paths match the API's routes,
    so a redirect means the configured URL is wrong (``http://`` rather than
    ``https://``, say) and raises :class:`~bluecore_client.errors.Redirected`
    with the ``Location`` the server gave.
    """

    def __init__(
        self,
        *,
        api_url: str | None = None,
        bluecore_url: str | None = None,
        keycloak_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        client_id: str | None = None,
        token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        load_dotenv: bool = True,
        anonymous: bool = False,
        event_hooks: dict[str, list] | None = None,
    ):
        self.config: Config = config_module.resolve(
            api_url=api_url,
            bluecore_url=bluecore_url,
            keycloak_url=keycloak_url,
            username=username,
            password=password,
            client_id=client_id,
            token=token,
            load_dotenv=load_dotenv,
        )
        # Reads of another deployment's public endpoints need no credentials,
        # which is what anonymous is for -- see `bluecore load profiles`.
        self.auth = (
            None
            if anonymous
            else KeycloakAuth(self.config, transport=transport, event_hooks=event_hooks)
        )
        self._http = httpx.Client(
            base_url=self.config.api_url,
            auth=self.auth,
            timeout=timeout,
            transport=transport,
            # Never follow: on a 301/302 httpx turns a POST into a GET and
            # drops the body. raise_for_status() raises Redirected instead.
            follow_redirects=False,
            event_hooks=event_hooks or {},
        )

        self._context: Any = _UNFETCHED

        self.works = Works(self)
        self.instances = Instances(self)
        self.hubs = Hubs(self)
        self.resources = OtherResources(self)
        self.profiles = Profiles(self)
        self.search = Search(self)
        self.changes = ChangeDocuments(self)
        self.batches = Batches(self)
        self.export = Export(self)
        self.convert = Convert(self)

    @property
    def api_url(self) -> str:
        return self.config.api_url

    def context(self) -> dict[str, Any] | None:
        """The deployment's JSON-LD context, fetched once and remembered.

        Responses reference the context by URL rather than inlining it. Any
        RDF conversion needs the actual terms, and fetching it per document
        would mean one HTTP request per record, so it is cached here.

        Returns ``None`` if the deployment doesn't serve one, which just means
        RDF conversion falls back to letting rdflib resolve it.
        """
        if self._context is not _UNFETCHED:
            return self._context

        try:
            body = self.request("GET", "/context.jsonld").json()
        except (BluecoreError, ValueError):
            # ValueError covers a body that isn't JSON at all -- a deployment
            # whose content negotiation falls through returns an HTML page.
            self._context = None
            return None

        # A context can legally be an array or a string; neither is usable as
        # an inline substitute, so fall back to letting rdflib resolve it.
        if isinstance(body, dict):
            term_map = body.get("@context", body)
            self._context = term_map if isinstance(term_map, dict) else None
        else:
            self._context = None
        return self._context

    def login(self) -> str:
        """Authenticate now and return the access token."""
        if self.auth is None:
            raise AuthError("This client was created anonymous, so it cannot log in.")
        return self.auth.login()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        content: bytes | str | None = None,
        files: Any = None,
        accept: str | None = None,
        content_type: str | None = None,
    ) -> httpx.Response:
        """Make a request, raising a useful error if it fails.

        Always sends an explicit ``Accept``. Without one the API falls through
        its content negotiation and returns an HTML page, which is never what a
        program wants.
        """
        headers = {"Accept": accept or "application/json"}
        if content_type:
            headers["Content-Type"] = content_type

        try:
            response = self._http.request(
                method,
                path,
                params=params,
                json=json,
                content=content,
                files=files,
                headers=headers,
            )
        except httpx.HTTPError as error:
            # A timeout or refused connection shouldn't surface as a traceback.
            raise ConnectionFailed(
                f"Could not reach {self.config.api_url} "
                f"({type(error).__name__}: {error or 'no response'})"
            ) from error

        raise_for_status(response)
        return response

    def fetch(
        self,
        path: str,
        *,
        format: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Fetch a resource in a chosen serialization.

        JSON formats come back parsed; the rest come back as text.
        """
        fmt = formats.lookup(format)
        response = self.request("GET", path, params=params, accept=fmt.media_type)
        return response.json() if fmt.is_json else response.text

    def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """GET a path expecting a JSON response."""
        return self.request("GET", path, params=params).json()

    def post_json(self, path: str, body: Any, *, method: str = "POST") -> Any:
        """Send a JSON body."""
        return self.request(method, path, json=body).json()

    def post_jsonld(
        self, path: str, graph: dict[str, Any], *, method: str = "POST"
    ) -> Any:
        """Send a raw JSON-LD graph as the request body.

        The API unwraps this for us, so callers pass the graph itself rather
        than an envelope with a JSON-encoded string inside it.
        """
        return self.request(
            method,
            path,
            content=jsonlib.dumps(graph),
            content_type=JSONLD_CONTENT_TYPE,
        ).json()

    def as_rdf(self, items: Any, output: str = "turtle") -> str:
        """Serialize results as turtle, RDF/XML, or N-Triples.

        Accepts whatever a search or list gave back -- an iterable of records,
        a single record, or a bare JSON-LD graph::

            client.as_rdf(client.search("moon", limit=10).first())
            client.as_rdf(client.works.get(uuid), "ntriples")

        The API serializes a single resource itself, so prefer
        ``works.get(uuid, format="ttl")`` when that's all you need. This is for
        result sets, which the API only returns as JSON-LD.
        """
        from bluecore_client import rdf

        if isinstance(items, dict):
            records: list[Any] = [items]
        else:
            records = list(items)

        return rdf.serialize(rdf.graphs_of(records), output, context=self.context())

    def close(self) -> None:
        """Close the underlying connection pool."""
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"BluecoreClient({self.config.api_url!r})"
