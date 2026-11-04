"""Working out where Blue Core is and who we are.

Settings resolve in the order: explicit argument, then environment variable,
then a value derived from ``BLUECORE_URL``. The environment variable names
match the ones ``bluecore_api`` already documents in its README, so an existing
``.env`` works unchanged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

#: Keycloak realm the API authenticates against.
REALM = "bluecore"

#: Default Keycloak client id. ``bluecore_api``'s CLI hardcodes this value.
DEFAULT_CLIENT_ID = "bluecore_api"

#: Where to look when nothing is configured. This deployment serves the API at
#: ``/api`` and Keycloak at ``/keycloak``, which is what gets derived below.
#: It's also the host ``bluecore_api``'s own load-profiles command defaults to.
DEFAULT_BLUECORE_URL = "https://dev.bcld.info"


def _join(base: str, path: str) -> str:
    """Join a base URL and path with exactly one slash between them."""
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


@dataclass
class Config:
    """Resolved connection settings."""

    api_url: str
    keycloak_url: str
    username: str | None = None
    password: str | None = None
    client_id: str = DEFAULT_CLIENT_ID
    token: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def token_url(self) -> str:
        """The Keycloak endpoint that issues access tokens."""
        return _join(self.keycloak_url, f"realms/{REALM}/protocol/openid-connect/token")

    @property
    def has_credentials(self) -> bool:
        return bool(self.username and self.password)

    def can_authenticate(self) -> bool:
        return bool(self.token) or self.has_credentials


def resolve(
    *,
    api_url: str | None = None,
    bluecore_url: str | None = None,
    keycloak_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    client_id: str | None = None,
    token: str | None = None,
    load_dotenv: bool = True,
) -> Config:
    """Build a :class:`Config`, filling gaps from the environment.

    ``bluecore_url`` is the root of a Blue Core deployment. In production the
    API hangs off it at ``/api``, so that is the default we derive; pass
    ``api_url`` explicitly for a local dev server, which serves the API at the
    bare root of ``localhost:3000``.

    With nothing configured at all, this points at
    :data:`DEFAULT_BLUECORE_URL`, so ``BluecoreClient()`` does something useful
    out of the box.

    ``load_dotenv`` first reads a ``.env`` from the working directory. That
    needs python-dotenv, which comes with the ``cli`` extra; without it the
    environment is used as it stands.
    """
    if load_dotenv:
        try:
            import dotenv
        except ModuleNotFoundError:
            # python-dotenv comes with the cli extra. A library caller without
            # it configures through arguments or the real environment, so
            # there is no .env to read.
            dotenv = None
        if dotenv is not None:
            # usecwd=True matters. Without it python-dotenv searches upward
            # from the file that called it -- this module, inside
            # site-packages -- so a .env in the directory you are actually
            # working in is never found.
            dotenv.load_dotenv(dotenv.find_dotenv(usecwd=True))

    env = os.environ.get

    def derive(argument: str | None, variable: str, suffix: str) -> str:
        """Resolve one URL, keeping arguments ahead of the environment.

        An explicitly passed ``bluecore_url`` has to beat ``API_URL`` from the
        environment, not lose to it -- otherwise asking for one deployment
        quietly reads from another. That matters most for ``load profiles``,
        whose whole job is copying between two instances.
        """
        if argument:
            return argument
        if bluecore_url:
            return _join(bluecore_url, suffix)
        from_environment = env(variable)
        if from_environment:
            return from_environment
        return _join(env("BLUECORE_URL") or DEFAULT_BLUECORE_URL, suffix)

    resolved_api = derive(api_url, "API_URL", "api")
    resolved_keycloak = derive(keycloak_url, "KEYCLOAK_EXTERNAL_URL", "keycloak")

    return Config(
        api_url=resolved_api.rstrip("/"),
        keycloak_url=resolved_keycloak.rstrip("/"),
        username=username or env("API_KEYCLOAK_USER"),
        password=password or env("API_KEYCLOAK_PASSWORD"),
        client_id=client_id or env("API_KEYCLOAK_CLIENT_ID") or DEFAULT_CLIENT_ID,
        token=token or env("BLUECORE_TOKEN"),
    )
