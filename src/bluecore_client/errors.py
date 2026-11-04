"""Exceptions raised by the Blue Core client.

Every error carries the API's own ``detail`` message where it sent one, since
that is usually more useful than the status code alone.
"""

from __future__ import annotations

import httpx


class BluecoreError(Exception):
    """Base class for every error this library raises."""


class ConfigError(BluecoreError):
    """Something needed to reach Blue Core is missing or unusable."""


class ConnectionFailed(BluecoreError):
    """The API could not be reached at all: refused, unresolved, or timed out."""


class APIError(BluecoreError):
    """The API returned an unsuccessful status code."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response: httpx.Response | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class AuthError(APIError):
    """Keycloak refused the credentials, or the API refused the token.

    An :class:`APIError` so that ``except APIError`` covers a 401 alongside
    every other failing status. ``status_code`` and ``response`` are unset when
    the failure came from Keycloak rather than from the API.
    """


class NotFound(APIError):
    """The requested resource does not exist."""


class ValidationError(APIError):
    """The API rejected the request body or parameters."""


class PermissionDenied(APIError):
    """The token is valid but lacks the role this operation requires."""


class Redirected(APIError):
    """The API answered with a redirect the client was not told to follow.

    Not following is the default, because a redirect would carry the caller's
    token to whatever host ``Location`` names. ``location`` is where the API
    pointed, and ``response`` is the 3xx itself, for a caller that wants to
    decide for itself.
    """

    def __init__(
        self,
        message: str,
        *,
        location: str,
        status_code: int | None = None,
        response: httpx.Response | None = None,
    ):
        super().__init__(message, status_code=status_code, response=response)
        self.location = location


def _detail(response: httpx.Response) -> str:
    """Pull FastAPI's ``detail`` out of an error response, readably.

    ``detail`` is a plain string for HTTPException, but a list of per-field
    dicts for a 422 from Pydantic validation, so both shapes are handled.
    """
    try:
        body = response.json()
    except ValueError:
        body = None

    # A gateway or proxy can answer with a JSON array or string rather than the
    # object FastAPI would send, and losing the real status to an AttributeError
    # raised in here would be worse than saying nothing.
    detail = body.get("detail") if isinstance(body, dict) else None

    if detail is None:
        return response.text.strip() or response.reason_phrase

    if isinstance(detail, str):
        return detail

    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict):
                location = ".".join(str(p) for p in item.get("loc", ()))
                message = item.get("msg", "invalid")
                parts.append(f"{location}: {message}" if location else message)
            else:
                parts.append(str(item))
        return "; ".join(parts)

    return str(detail)


def raise_for_status(response: httpx.Response) -> None:
    """Raise the most specific error that fits ``response``."""
    if response.is_redirect:  # False if follow_redirects=True
        request = response.request
        location = response.headers["Location"]
        raise Redirected(
            f"{response.status_code} redirect to {location} was not followed "
            f"({request.method} {request.url}); pass follow_redirects=True to "
            "BluecoreClient to follow it",
            location=location,
            status_code=response.status_code,
            response=response,
        )

    if not response.is_error:
        return

    message = _detail(response)
    status = response.status_code
    request = response.request

    if status == 404:
        raise NotFound(
            f"{message} ({request.method} {request.url})",
            status_code=status,
            response=response,
        )
    if status == 401:
        raise AuthError(
            f"{message} ({request.method} {request.url})",
            status_code=status,
            response=response,
        )
    if status == 403:
        raise PermissionDenied(
            f"{message} ({request.method} {request.url})",
            status_code=status,
            response=response,
        )
    if status == 422:
        raise ValidationError(message, status_code=status, response=response)

    raise APIError(
        f"{status} {message} ({request.method} {request.url})",
        status_code=status,
        response=response,
    )
