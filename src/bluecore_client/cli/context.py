"""Turning global CLI options into a client.

Reads don't require credentials, so they don't ask for any -- ``bluecore
search`` works on a fresh install with nothing configured. Writes do, so those
prompt up front rather than failing after the work has started.

Prompting is a CLI behaviour only. The library never blocks on input, since a
notebook shouldn't stall on a hidden ``input()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import typer

from bluecore_client import BluecoreClient
from bluecore_client import config as config_module
from bluecore_client.errors import AuthError, BluecoreError, PermissionDenied
from bluecore_client.formats import Output


@dataclass
class Settings:
    """Global options, collected by the top-level callback."""

    api_url: str | None = None
    bluecore_url: str | None = None
    keycloak_url: str | None = None
    username: str | None = None
    password: str | None = None
    token: str | None = None
    output: Output = Output.TEXT
    verbose: bool = False
    timeout: float = 30.0
    _client: BluecoreClient | None = field(default=None, repr=False)
    _client_anonymous: bool = field(default=False, repr=False)

    def client(self, *, require_auth: bool = False) -> BluecoreClient:
        """Build the client, asking for credentials only when they're needed.

        ``require_auth`` should be set by commands that write. Everything else
        connects anonymously and lets the API decide.
        """
        # An anonymous client won't do for a write, so rebuild in that case.
        if self._client is not None and not (require_auth and self._client_anonymous):
            return self._client

        resolved = config_module.resolve(
            api_url=self.api_url,
            bluecore_url=self.bluecore_url,
            keycloak_url=self.keycloak_url,
            username=self.username,
            password=self.password,
            token=self.token,
        )

        username, password = resolved.username, resolved.password
        anonymous = False

        if not resolved.can_authenticate():
            if require_auth:
                from bluecore_client.cli import ui

                # Any spinner has to come down first, or it redraws over the
                # prompt and over what's being typed.
                with ui.pause():
                    ui.note(f"Sign in to {resolved.api_url}")
                    ui.note(
                        "  Set API_KEYCLOAK_USER and API_KEYCLOAK_PASSWORD, or "
                        "BLUECORE_TOKEN, to skip this."
                    )
                    username = username or typer.prompt("Blue Core username")
                    password = password or typer.prompt(
                        "Blue Core password", hide_input=True
                    )
            else:
                anonymous = True

        if self._client is not None:
            self._client.close()

        if self.verbose:
            from bluecore_client.cli import ui

            ui.note(f"api      {resolved.api_url}")
            ui.note(f"keycloak {resolved.keycloak_url}")
            ui.note(
                "auth     "
                + (
                    "anonymous"
                    if anonymous
                    else f"as {username}"
                    if username
                    else "supplied token"
                )
            )

        self._client = BluecoreClient(
            api_url=resolved.api_url,
            keycloak_url=resolved.keycloak_url,
            username=username,
            password=password,
            token=resolved.token,
            client_id=resolved.client_id,
            anonymous=anonymous,
            timeout=self.timeout,
            load_dotenv=False,
            event_hooks=_trace_hooks() if self.verbose else None,
        )
        self._client_anonymous = anonymous
        return self._client

    @property
    def wants_document(self) -> bool:
        """Whether the whole result should be emitted as one document."""
        return self.output.is_document

    @property
    def is_anonymous(self) -> bool:
        return self._client is not None and self._client_anonymous


def _trace_hooks() -> dict[str, list]:
    """Imported lazily so context stays importable without the ui module."""
    from bluecore_client.cli import ui

    return ui.trace_hooks()


#: Filled in by the top-level callback before any command runs.
settings = Settings()


def client(*, require_auth: bool = False) -> BluecoreClient:
    """The configured client for this invocation."""
    return settings.client(require_auth=require_auth)


def die(error: BluecoreError | str) -> None:
    """Report a failure the way a CLI should and stop."""
    from bluecore_client.cli import ui

    ui.failure(str(error))

    # An auth failure on an anonymous read is worth explaining, since the user
    # was never asked for credentials.
    if isinstance(error, (AuthError, PermissionDenied)) and settings.is_anonymous:
        ui.note(
            "  This needs credentials. Pass --username, or set "
            "API_KEYCLOAK_USER and API_KEYCLOAK_PASSWORD."
        )

    raise typer.Exit(1)
