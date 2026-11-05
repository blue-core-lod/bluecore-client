"""Redirects are refused unless the caller asks for them.

A followed redirect can re-send the token and body somewhere the caller didn't
choose, or turn a POST into a GET, so by default a 3xx raises instead.
"""

import pytest

from bluecore_client import BluecoreClient, Redirected
from tests.conftest import API_URL, KEYCLOAK_URL

WORK = f"{API_URL}/works/w1"
SLASHED = f"{WORK}/"
ELSEWHERE = "https://elsewhere.example/works/w1"


def redirect(httpx_mock, url, *, method="GET", status_code=307, to=SLASHED):
    """Answer ``url`` with a redirect to ``to``."""
    httpx_mock.add_response(
        url=url, method=method, status_code=status_code, headers={"Location": to}
    )


@pytest.fixture
def following(token_response):
    """A client with credentials that follows redirects, as the CLI's does.

    conftest's ``client`` fixture can't take ``follow_redirects``, so this
    mirrors its arguments and differs only in that one setting.
    """
    token_response()
    with BluecoreClient(
        api_url=API_URL,
        keycloak_url=KEYCLOAK_URL,
        username="developer",
        password="123456",
        load_dotenv=False,
        follow_redirects=True,
    ) as client:
        yield client


def test_a_redirect_raises_and_its_target_is_never_requested(httpx_mock, client):
    """By default a 3xx raises Redirected, and the Location is never requested.

    This is the guarantee a plugin forwarding a user's token relies on. The
    exception carries the location, status and raw response, so a caller can
    still decide what to do, and its message says how to opt in.
    """
    redirect(httpx_mock, WORK)

    with pytest.raises(Redirected, match="follow_redirects=True") as caught:
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


def test_a_redirect_is_followed(httpx_mock, following):
    """With follow_redirects=True the redirect is followed, token included.

    The redirect stays on the same host, like the API's slash redirects, so the
    Authorization header is kept and authenticated CLI commands keep working.
    """
    redirect(httpx_mock, WORK)
    httpx_mock.add_response(url=SLASHED, json={"@id": "w1"})

    assert following.works.get("w1") == {"@id": "w1"}
    assert httpx_mock.get_request(url=SLASHED).headers["Authorization"]


def test_the_token_is_dropped_on_the_way_to_another_host(httpx_mock, following):
    """Following a redirect to another host drops the Authorization header.

    That is httpx's behaviour, not ours, but the README relies on it when it
    says the risk is re-sending the body, not leaking the token across hosts.
    Pinning it here means an httpx upgrade that changed it fails this test
    rather than going unnoticed.
    """
    redirect(httpx_mock, WORK, to=ELSEWHERE)
    httpx_mock.add_response(url=ELSEWHERE, json={"@id": "w1"})

    following.works.get("w1")

    assert "Authorization" not in httpx_mock.get_request(url=ELSEWHERE).headers
