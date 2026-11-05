"""Redirects are never followed.

The client's paths match the API's routes, so a 3xx means a misconfigured URL,
and following one could turn a POST into a GET. A 3xx raises instead.
"""

import pytest

from bluecore_client import Redirected
from tests.conftest import API_URL

WORK = f"{API_URL}/works/w1"
SLASHED = f"{WORK}/"


def redirect(httpx_mock, url, *, method="GET", status_code=307, to=SLASHED):
    """Answer ``url`` with a redirect to ``to``."""
    httpx_mock.add_response(
        url=url, method=method, status_code=status_code, headers={"Location": to}
    )


def test_a_redirect_raises_and_its_target_is_never_requested(httpx_mock, client):
    """A 3xx raises Redirected, and the Location is never requested.

    The exception carries the location, status and raw response, and its
    message points at the configured URL, the usual cause.
    """
    redirect(httpx_mock, WORK)

    with pytest.raises(Redirected, match="check that the Blue Core URL") as caught:
        client.request("GET", "/works/w1")

    assert caught.value.location == SLASHED
    assert caught.value.status_code == 307
    assert caught.value.response is not None
    assert not httpx_mock.get_requests(url=SLASHED)


@pytest.mark.parametrize(
    "method, call",
    [
        ("GET", lambda client: client.works.get("w1")),
        ("DELETE", lambda client: client.works.delete("w1")),
    ],
    ids=["get", "delete"],
)
def test_resource_methods_raise_too(httpx_mock, client, method, call):
    """Resource methods raise Redirected too, not only client.request().

    get() goes through fetch() and parses the body; delete() calls request()
    and ignores it. If only the JSON helpers checked, a redirected delete would
    return normally, as if the work had been deleted.
    """
    redirect(httpx_mock, WORK, method=method)

    with pytest.raises(Redirected):
        call(client)


def test_a_create_is_not_quietly_turned_into_a_get(httpx_mock, client):
    """A POST answered with a 302 raises instead of being re-sent as a GET.

    A client that followed it would drop the body, GET the collection, and
    hand back the listing as if it were the newly created work.
    """
    redirect(httpx_mock, f"{API_URL}/works/", method="POST", status_code=302)

    with pytest.raises(Redirected):
        client.works.create({"@id": "https://bcld.info/works/new"})

    assert not httpx_mock.get_requests(method="GET")
