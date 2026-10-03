"""Copying profiles between deployments has to carry their nesting with it.

A profile names the profiles it nests by URI, and a URI identifies a row in one
deployment's database. Creating a copy mints a new URI, so without a second
pass every reference still points at the source and the nesting is lost.
"""

import json

import pytest
from typer.testing import CliRunner

from bluecore_client.cli.app import app
from bluecore_client.cli.context import Settings
from bluecore_client.resources import profiles
from tests.conftest import API_URL, KEYCLOAK_URL

runner = CliRunner()
BASE = ["--api-url", API_URL, "--keycloak-url", KEYCLOAK_URL]
CREDENTIALS = ["--username", "developer", "--password", "123456"]

REMOTE = "https://remote.bcld.info"
SINOPIA = "http://sinopia.io/vocabulary/"

CHILD = f"{REMOTE}/profiles/child"
PARENT = f"{REMOTE}/profiles/parent"
LOCAL_CHILD = "http://localhost/profiles/aaa"
LOCAL_PARENT = "http://localhost/profiles/bbb"


@pytest.fixture(autouse=True)
def fresh_settings():
    from bluecore_client.cli.context import settings

    defaults = Settings()
    for name in vars(defaults):
        setattr(settings, name, getattr(defaults, name))
    yield


def profile_doc(uri: str, resource_id: str, nests: tuple[str, ...] = ()) -> list[dict]:
    """Expanded JSON-LD for a profile, naming nested profiles by URI."""
    doc: list[dict] = [
        {
            "@id": uri,
            "@type": [f"{SINOPIA}ResourceTemplate"],
            f"{SINOPIA}hasResourceId": [{"@value": resource_id, "@language": "en"}],
        }
    ]
    for i, nested in enumerate(nests):
        doc.append(
            {
                "@id": f"_:attributes{i}",
                "@type": [f"{SINOPIA}ResourcePropertyTemplate"],
                f"{SINOPIA}hasResourceTemplateId": [{"@id": nested}],
            }
        )
    return doc


class TestRelink:
    """The document rewrite, which is pure and needs no HTTP.

    Note that a reference the remap has nothing for takes one branch whatever
    its shape -- telling a stale URI from an id string is load.py's job, and is
    tested there.
    """

    def test_a_mapped_reference_is_repointed(self):
        data = profile_doc(PARENT, "x:Parent", (CHILD,))

        rewritten, unresolved = profiles.relink(data, {CHILD: LOCAL_CHILD})

        assert profiles.references(rewritten) == {LOCAL_CHILD}
        assert unresolved == set()

    def test_an_unmapped_reference_is_kept_and_reported(self):
        data = profile_doc(PARENT, "x:Parent", (CHILD,))

        rewritten, unresolved = profiles.relink(data, {})

        assert profiles.references(rewritten) == {CHILD}
        assert unresolved == {CHILD}

    def test_the_original_is_left_alone(self):
        """load.py compares the two to decide whether a PUT is needed, so
        rewriting in place would mean nothing was ever sent back."""
        data = profile_doc(PARENT, "x:Parent", (CHILD,))
        before = json.dumps(data, sort_keys=True)

        profiles.relink(data, {CHILD: LOCAL_CHILD})

        assert json.dumps(data, sort_keys=True) == before

    def test_a_compacted_document_reads_the_same_as_an_expanded_one(self):
        """Profiles are stored unframed, so both shapes reach the client."""
        data = {
            "@context": {"sinopia": SINOPIA},
            "@id": PARENT,
            "sinopia:hasResourceTemplateId": {"@id": CHILD},
        }

        rewritten, unresolved = profiles.relink(data, {CHILD: LOCAL_CHILD})

        assert profiles.references(rewritten) == {LOCAL_CHILD}
        assert unresolved == set()


@pytest.fixture
def copying(httpx_mock, token_response):
    """Wire up a copy of one parent and the child it nests.

    The created responses carry the minted ``@id`` the API re-homes each
    document onto, which is what the relink pass has to preserve.
    """

    def _copy(
        nests: tuple[str, ...] = (CHILD,),
        expect_put: bool = True,
        expect_create: bool = True,
    ):
        token_response()
        httpx_mock.add_response(
            url=f"{REMOTE}/api/search/profile?limit=50&offset=0",
            json={
                "results": [
                    {"uri": CHILD, "data": profile_doc(CHILD, "x:Child")},
                    {"uri": PARENT, "data": profile_doc(PARENT, "x:Parent", nests)},
                ],
                "total": 2,
            },
        )
        if expect_create:
            for uuid, local, doc in (
                ("aaa", LOCAL_CHILD, profile_doc(LOCAL_CHILD, "x:Child")),
                ("bbb", LOCAL_PARENT, profile_doc(LOCAL_PARENT, "x:Parent", nests)),
            ):
                httpx_mock.add_response(
                    url=f"{API_URL}/profiles/",
                    method="POST",
                    status_code=201,
                    json={"id": 1, "uuid": uuid, "uri": local, "data": doc},
                )
        if expect_put:
            httpx_mock.add_response(
                url=f"{API_URL}/profiles/bbb", method="PUT", json={"uuid": "bbb"}
            )
        return httpx_mock

    return _copy


def puts(httpx_mock) -> list:
    return [r for r in httpx_mock.get_requests() if r.method == "PUT"]


def put_body(httpx_mock) -> list[dict]:
    return json.loads(json.loads(puts(httpx_mock)[0].content)["data"])


class TestLoadProfiles:
    """The command, end to end over mocked HTTP."""

    def test_nesting_survives_the_copy(self, copying):
        """The bug: before the relink pass, the copy kept pointing at the source.

        Also guards what gets sent back -- it has to be the document the API
        stored, with its minted @id, not the one the source handed over.
        """
        mock = copying()

        result = runner.invoke(app, [*BASE, *CREDENTIALS, "load", "profiles", REMOTE])

        assert result.exit_code == 0, result.output
        assert len(puts(mock)) == 1, "only the profile that nests anything is sent back"
        body = put_body(mock)
        assert profiles.references(body) == {LOCAL_CHILD}
        subjects = {node.get("@id") for node in body}
        assert LOCAL_PARENT in subjects and PARENT not in subjects

    def test_a_profile_with_nothing_to_relink_is_not_put_back(self, copying):
        mock = copying(nests=(), expect_put=False)

        result = runner.invoke(app, [*BASE, *CREDENTIALS, "load", "profiles", REMOTE])

        assert result.exit_code == 0, result.output
        assert puts(mock) == []

    @pytest.mark.parametrize(
        ("reference", "expected"),
        [
            # An id string means the source predates the move to URI
            # references, which is a different problem from a dangling one.
            ("pcc:bf2:Role", "migrat"),
            ("https://stage.bcld.info/profiles/never-copied", "not copied"),
        ],
        ids=["id-string", "uri-outside-the-batch"],
    )
    def test_an_unresolvable_reference_is_explained(self, copying, reference, expected):
        mock = copying(nests=(reference,), expect_put=False)

        result = runner.invoke(app, [*BASE, *CREDENTIALS, "load", "profiles", REMOTE])

        assert result.exit_code == 0, result.output
        assert puts(mock) == []
        assert expected in result.output

    def test_dry_run_writes_nothing_at_all(self, copying):
        mock = copying(expect_put=False, expect_create=False)

        result = runner.invoke(
            app, [*BASE, *CREDENTIALS, "load", "profiles", REMOTE, "--dry-run"]
        )

        assert result.exit_code == 0, result.output
        written = [r for r in mock.get_requests() if r.method in ("POST", "PUT")]
        assert [r for r in written if "profiles" in str(r.url)] == []
