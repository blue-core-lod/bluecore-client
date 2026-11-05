"""The command line interface.

These drive the real Typer app against a mocked transport, so they cover the
wiring between commands and the client as well as the output itself.
"""

import json

import pytest
from typer.testing import CliRunner

from bluecore_client.cli.app import app
from bluecore_client.cli.context import Settings
from tests.conftest import API_URL, KEYCLOAK_URL

runner = CliRunner()

GLOBAL_OPTIONS = [
    "--api-url",
    API_URL,
    "--keycloak-url",
    KEYCLOAK_URL,
    "--username",
    "developer",
    "--password",
    "123456",
]

WORK_GRAPH = {
    "@id": "https://bcld.info/works/w1",
    "@type": ["Work"],
    "title": [{"mainTitle": "Le mal joli"}],
}


@pytest.fixture(autouse=True)
def fresh_settings():
    """Reset the shared Settings between invocations.

    Every command module imported this one object by name, so it has to be
    reset in place -- swapping in a new instance would leave the modules
    pointing at the old one.
    """
    from bluecore_client.cli.context import settings

    defaults = Settings()
    for name in vars(defaults):
        setattr(settings, name, getattr(defaults, name))
    yield


def invoke(*args):
    return runner.invoke(app, [*GLOBAL_OPTIONS, *args])


class TestWorkCommands:
    def test_view_prints_the_graph(self, httpx_mock, token_response):
        token_response()
        httpx_mock.add_response(url=f"{API_URL}/works/w1", json=WORK_GRAPH)

        result = invoke("work", "view", "w1")

        assert result.exit_code == 0
        assert "Le mal joli" in result.stdout

    def test_view_follows_the_apis_redirects(self, httpx_mock, token_response):
        """The CLI follows redirects, so a slash redirect doesn't break a command.

        The library refuses redirects by default; the CLI opts back in, since
        the API redirects between slashed and unslashed collection paths.
        """
        token_response()
        httpx_mock.add_response(
            url=f"{API_URL}/works/w1",
            status_code=307,
            headers={"Location": f"{API_URL}/works/w1/"},
        )
        httpx_mock.add_response(url=f"{API_URL}/works/w1/", json=WORK_GRAPH)

        result = invoke("work", "view", "w1")

        assert result.exit_code == 0, result.output
        assert "Le mal joli" in result.stdout

    def test_view_with_json_emits_parseable_output(self, httpx_mock, token_response):
        token_response()
        httpx_mock.add_response(url=f"{API_URL}/works/w1", json=WORK_GRAPH)

        result = runner.invoke(
            app, [*GLOBAL_OPTIONS, "-o", "json", "work", "view", "w1"]
        )

        assert result.exit_code == 0
        assert json.loads(result.stdout) == WORK_GRAPH

    def test_view_of_something_missing_fails_cleanly(self, httpx_mock, token_response):
        token_response()
        httpx_mock.add_response(
            url=f"{API_URL}/works/nope",
            status_code=404,
            json={"detail": "Work nope not found"},
        )

        result = invoke("work", "view", "nope")

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_view_in_turtle_prints_raw_text(self, httpx_mock, token_response):
        token_response()
        httpx_mock.add_response(
            url=f"{API_URL}/works/w1", text="<https://bcld.info/works/w1> a bf:Work ."
        )

        result = runner.invoke(
            app, [*GLOBAL_OPTIONS, "-o", "turtle", "work", "view", "w1"]
        )

        assert result.exit_code == 0
        assert "a bf:Work" in result.stdout

    def test_create_reads_a_json_ld_file(self, httpx_mock, token_response, tmp_path):
        token_response()
        source = tmp_path / "work.jsonld"
        source.write_text(json.dumps(WORK_GRAPH))
        httpx_mock.add_response(
            url=f"{API_URL}/works/",
            method="POST",
            status_code=201,
            json={"uuid": "w1", "uri": "https://bcld.info/works/w1"},
        )

        result = invoke("work", "create", str(source))

        assert result.exit_code == 0
        assert "Created work w1" in result.output

    def test_create_rejects_a_file_that_is_not_json(
        self, httpx_mock, token_response, tmp_path
    ):
        token_response()
        source = tmp_path / "broken.jsonld"
        source.write_text("{not json")

        result = invoke("work", "create", str(source))

        assert result.exit_code == 1
        assert "not valid JSON" in result.output

    def test_delete_asks_first(self, httpx_mock, token_response):
        token_response()

        result = invoke("work", "delete", "w1")

        assert result.exit_code != 0, "should abort without confirmation"

    def test_delete_with_yes_goes_ahead(self, httpx_mock, token_response):
        token_response()
        httpx_mock.add_response(
            url=f"{API_URL}/works/w1", method="DELETE", status_code=204
        )

        result = invoke("work", "delete", "w1", "--yes")

        assert result.exit_code == 0
        assert "Deleted work w1" in result.output


class TestAuthOnlyWhenNeeded:
    """Reads work with nothing configured; writes ask for credentials."""

    def read_only_options(self):
        return ["--api-url", API_URL, "--keycloak-url", KEYCLOAK_URL]

    def test_a_read_does_not_prompt_or_log_in(self, httpx_mock):
        httpx_mock.add_response(url=f"{API_URL}/works/w1", json=WORK_GRAPH)

        result = runner.invoke(
            app, [*self.read_only_options(), "work", "view", "w1"], input=""
        )

        assert result.exit_code == 0
        assert "username" not in result.output.lower()
        token_calls = [r for r in httpx_mock.get_requests() if "keycloak" in str(r.url)]
        assert token_calls == [], "a read should not contact Keycloak"

    def test_a_read_sends_no_authorization_header(self, httpx_mock):
        httpx_mock.add_response(url=f"{API_URL}/works/w1", json=WORK_GRAPH)

        runner.invoke(app, [*self.read_only_options(), "work", "view", "w1"])

        assert "Authorization" not in httpx_mock.get_requests()[-1].headers

    def test_search_works_with_nothing_configured(self, httpx_mock):
        """The first thing anyone runs shouldn't demand a password."""
        httpx_mock.add_response(
            url=f"{API_URL}/search/?q=emma&type=all&limit=20&offset=0",
            json={"results": [{"uuid": "w1"}], "total": 1},
        )

        result = runner.invoke(app, [*self.read_only_options(), "search", "emma"])

        assert result.exit_code == 0
        assert "w1" in result.stdout

    def test_a_write_prompts_for_credentials(
        self, httpx_mock, token_response, tmp_path
    ):
        token_response()
        source = tmp_path / "work.jsonld"
        source.write_text(json.dumps(WORK_GRAPH))
        httpx_mock.add_response(
            url=f"{API_URL}/works/", method="POST", status_code=201, json={"uuid": "w1"}
        )

        result = runner.invoke(
            app,
            [*self.read_only_options(), "work", "create", str(source)],
            input="developer\n123456\n",
        )

        assert result.exit_code == 0
        assert "username" in result.output.lower()

    def test_an_unauthorized_read_explains_what_to_do(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{API_URL}/works/w1", status_code=401, json={"detail": "Unauthorized"}
        )

        result = runner.invoke(app, [*self.read_only_options(), "work", "view", "w1"])

        assert result.exit_code == 1
        assert "API_KEYCLOAK_USER" in result.output


class TestConnectionFailures:
    def test_a_timeout_is_reported_not_raised(self, httpx_mock):
        import httpx

        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))

        result = runner.invoke(
            app,
            [
                "--api-url",
                API_URL,
                "--keycloak-url",
                KEYCLOAK_URL,
                "work",
                "view",
                "w1",
            ],
        )

        assert result.exit_code == 1
        assert "Could not reach" in result.output
        assert "ReadTimeout" in result.output

    def test_verbose_narrates_the_request(self, httpx_mock):
        httpx_mock.add_response(url=f"{API_URL}/works/w1", json=WORK_GRAPH)

        result = runner.invoke(
            app,
            [
                "--api-url",
                API_URL,
                "--keycloak-url",
                KEYCLOAK_URL,
                "--verbose",
                "work",
                "view",
                "w1",
            ],
        )

        assert result.exit_code == 0
        assert f"{API_URL}/works/w1" in result.output
        assert "anonymous" in result.output


class TestUriArguments:
    """A UUID or a full Blue Core URI, so you can paste what you found."""

    def test_view_accepts_a_full_uri(self, httpx_mock, token_response):
        token_response()
        httpx_mock.add_response(url=f"{API_URL}/works/w1", json=WORK_GRAPH)

        result = invoke("work", "view", "https://dev.bcld.info/works/w1")

        assert result.exit_code == 0
        assert "Le mal joli" in result.stdout

    def test_view_accepts_a_uri_with_the_api_prefix(self, httpx_mock, token_response):
        token_response()
        httpx_mock.add_response(url=f"{API_URL}/works/w1", json=WORK_GRAPH)

        result = invoke("work", "view", "https://bcld.info/api/works/w1")

        assert result.exit_code == 0

    def test_a_uri_for_the_wrong_type_is_caught_early(self, httpx_mock, token_response):
        """No request should go out -- the mistake is obvious from the URI."""
        token_response()

        result = invoke("work", "view", "https://bcld.info/instances/i1")

        assert result.exit_code == 1
        assert "points at instances, not works" in result.output
        assert [r for r in httpx_mock.get_requests() if "works" in str(r.url)] == []

    def test_delete_accepts_a_uri(self, httpx_mock, token_response):
        token_response()
        httpx_mock.add_response(
            url=f"{API_URL}/works/w1", method="DELETE", status_code=204
        )

        result = invoke("work", "delete", "https://dev.bcld.info/works/w1", "--yes")

        assert result.exit_code == 0


class TestTitleExtraction:
    """BIBFRAME nests the title, and compaction makes its shape inconsistent.

    In bluecore_api's own sample/batch-small.jsonld, one Work has `title` as a
    dict and the next has it as a list, so both have to work.
    """

    def test_a_title_given_as_a_dict(self):
        from bluecore_client.cli.commands.search import _title_of

        assert _title_of({"title": {"mainTitle": "Le mal joli"}}) == "Le mal joli"

    def test_a_title_given_as_a_list(self):
        from bluecore_client.cli.commands.search import _title_of

        assert _title_of({"title": [{"mainTitle": "Le mal joli"}]}) == "Le mal joli"

    def test_a_title_nested_under_data(self):
        from bluecore_client.cli.commands.search import _title_of

        item = {"data": {"title": {"mainTitle": "Le mal joli"}}}
        assert _title_of(item) == "Le mal joli"

    def test_a_main_title_that_is_itself_a_list(self):
        from bluecore_client.cli.commands.search import _title_of

        assert _title_of({"title": [{"mainTitle": ["First", "Second"]}]}) == "First"

    def test_a_main_title_wrapped_as_a_typed_literal(self):
        from bluecore_client.cli.commands.search import _title_of

        item = {"title": [{"mainTitle": {"@value": "Le mal joli"}}]}
        assert _title_of(item) == "Le mal joli"

    def test_no_title_at_all(self):
        from bluecore_client.cli.commands.search import _title_of

        assert _title_of({}) == ""

    def test_a_title_that_is_already_a_string(self):
        from bluecore_client.cli.commands.search import _title_of

        assert _title_of({"title": "Le mal joli"}) == "Le mal joli"

    def test_skips_an_empty_entry_to_find_a_real_title(self):
        """The sample data really does contain empty title objects."""
        from bluecore_client.cli.commands.search import _title_of

        assert _title_of({"title": [{}, {"mainTitle": "Le mal joli"}]}) == "Le mal joli"


class TestSearch:
    def test_search_tabulates_results(self, httpx_mock, token_response):
        token_response()
        httpx_mock.add_response(
            url=f"{API_URL}/search/?q=emma&type=all&limit=20&offset=0",
            json={
                "results": [
                    {"uuid": "w1", "type": "Work", "data": WORK_GRAPH},
                ],
                "total": 1,
            },
        )

        result = invoke("search", "emma")

        assert result.exit_code == 0
        assert "w1" in result.stdout
        assert "Le mal joli" in result.stdout

    def test_search_with_no_matches_says_so(self, httpx_mock, token_response):
        token_response()
        httpx_mock.add_response(
            url=f"{API_URL}/search/?q=zzz&type=all&limit=20&offset=0",
            json={"results": [], "total": 0},
        )

        result = invoke("search", "zzz")

        assert result.exit_code == 0
        assert "No results" in result.output

    def test_search_json_includes_the_total(self, httpx_mock, token_response):
        token_response()
        # A full page, so the limit is satisfied without a second request.
        httpx_mock.add_response(
            url=f"{API_URL}/search/?q=emma&type=all&limit=20&offset=0",
            json={
                "results": [{"uuid": f"w{n}"} for n in range(20)],
                "total": 42,
            },
        )

        result = runner.invoke(app, [*GLOBAL_OPTIONS, "-o", "json", "search", "emma"])

        payload = json.loads(result.stdout)
        assert payload["total"] == 42
        assert len(payload["results"]) == 20

    def test_search_notes_when_it_is_showing_a_subset(self, httpx_mock, token_response):
        token_response()
        httpx_mock.add_response(
            url=f"{API_URL}/search/?q=a&type=all&limit=20&offset=0",
            json={"results": [{"uuid": f"w{n}"} for n in range(20)], "total": 500},
        )

        result = invoke("search", "a")

        assert "Showing 20 of 500" in result.output


class TestLoad:
    def test_load_url(self, httpx_mock, token_response):
        token_response()
        httpx_mock.add_response(
            url=f"{API_URL}/batches/",
            method="POST",
            json={"uri": "https://example.org/x.jsonld", "workflow_id": "wf-1"},
        )

        result = invoke("load", "url", "https://example.org/x.jsonld")

        assert result.exit_code == 0
        assert "Queued" in result.output
        assert "wf-1" in result.output

    def test_load_file(self, httpx_mock, token_response, tmp_path):
        token_response()
        upload = tmp_path / "batch.jsonld"
        upload.write_text('{"@id": "x"}')
        httpx_mock.add_response(
            url=f"{API_URL}/batches/upload/",
            method="POST",
            json={"workflow_id": "wf-2"},
        )

        result = invoke("load", "file", str(upload))

        assert result.exit_code == 0
        assert "Uploaded batch.jsonld" in result.output

    def test_the_old_flat_names_still_work(self, httpx_mock, token_response):
        """Scripts written against bluecore_api's CLI shouldn't break."""
        token_response()
        httpx_mock.add_response(
            url=f"{API_URL}/batches/", method="POST", json={"workflow_id": "wf-3"}
        )

        result = invoke("load-url", "https://example.org/x.jsonld")

        assert result.exit_code == 0
        assert "now `bluecore load url`" in result.output


class TestToken:
    def test_token_prints_only_the_token(self, httpx_mock, token_response):
        """It has to be safe to capture in a shell variable."""
        token_response(access_token="a-real-token")

        result = invoke("token")

        assert result.exit_code == 0
        assert result.stdout == "a-real-token"

    def test_a_bad_login_fails_with_a_message(self, httpx_mock):
        httpx_mock.add_response(
            url=f"{KEYCLOAK_URL}/realms/bluecore/protocol/openid-connect/token",
            method="POST",
            status_code=401,
            json={"error_description": "Invalid user credentials"},
        )

        result = invoke("token")

        assert result.exit_code == 1
        assert "Invalid user credentials" in result.output


class TestChanges:
    def test_list_walks_the_feed(self, httpx_mock, token_response):
        token_response()
        httpx_mock.add_response(
            url=f"{API_URL}/change_documents/works/page/1",
            json={
                "orderedItems": [
                    {
                        "published": "2026-01-01T00:00:00Z",
                        "type": "Update",
                        "object": {"id": "https://bcld.info/works/w1"},
                    }
                ]
            },
        )
        httpx_mock.add_response(
            url=f"{API_URL}/change_documents/works/page/2",
            status_code=404,
            json={"detail": "not found"},
        )

        result = invoke("changes", "list", "works")

        assert result.exit_code == 0
        assert "Update" in result.stdout

    def test_an_unknown_feed_is_rejected(self, httpx_mock, token_response):
        token_response()

        result = invoke("changes", "feed", "hubs")

        assert result.exit_code == 1
        assert "works" in result.output


class TestWhoami:
    def test_whoami_shows_where_it_points(self, httpx_mock, token_response):
        token_response()

        result = invoke("whoami")

        assert result.exit_code == 0
        assert API_URL in result.stdout
        assert "developer" in result.stdout
