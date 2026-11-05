"""Config resolution: arguments, then environment, then derived defaults."""

from dotenv import load_dotenv as real_load_dotenv

from bluecore_client import config


def test_derives_api_and_keycloak_from_bluecore_url():
    resolved = config.resolve(bluecore_url="https://bcld.info/", load_dotenv=False)

    assert resolved.api_url == "https://bcld.info/api"
    assert resolved.keycloak_url == "https://bcld.info/keycloak"


def test_derivation_tolerates_a_missing_trailing_slash():
    resolved = config.resolve(bluecore_url="https://bcld.info", load_dotenv=False)

    assert resolved.api_url == "https://bcld.info/api"


def test_explicit_api_url_wins_over_derivation():
    """The dev server serves the API at the bare root, not under /api."""
    resolved = config.resolve(
        bluecore_url="http://localhost:3000/",
        api_url="http://localhost:3000",
        keycloak_url="http://localhost:8081/keycloak/",
        load_dotenv=False,
    )

    assert resolved.api_url == "http://localhost:3000"
    assert resolved.keycloak_url == "http://localhost:8081/keycloak"


def test_reads_the_environment(monkeypatch):
    monkeypatch.setenv("BLUECORE_URL", "https://stage.bcld.info/")
    monkeypatch.setenv("API_KEYCLOAK_USER", "someone")
    monkeypatch.setenv("API_KEYCLOAK_PASSWORD", "secret")

    resolved = config.resolve(load_dotenv=False)

    assert resolved.api_url == "https://stage.bcld.info/api"
    assert resolved.username == "someone"
    assert resolved.has_credentials


def test_arguments_beat_the_environment(monkeypatch):
    monkeypatch.setenv("API_KEYCLOAK_USER", "from-env")

    resolved = config.resolve(
        bluecore_url="https://bcld.info/", username="from-arg", load_dotenv=False
    )

    assert resolved.username == "from-arg"


def test_falls_back_to_the_default_deployment(monkeypatch):
    """BluecoreClient() with nothing configured should still work."""
    for name in ("BLUECORE_URL", "API_URL", "KEYCLOAK_EXTERNAL_URL"):
        monkeypatch.delenv(name, raising=False)

    resolved = config.resolve(load_dotenv=False)

    assert resolved.api_url == "https://dev.bcld.info/api"
    assert resolved.keycloak_url == "https://dev.bcld.info/keycloak"


def test_the_environment_still_beats_the_default(monkeypatch):
    monkeypatch.setenv("BLUECORE_URL", "http://localhost:3000/")

    resolved = config.resolve(load_dotenv=False)

    assert resolved.api_url == "http://localhost:3000/api"


def test_token_url_matches_the_apis_own():
    """This path is hardcoded in bluecore_api's cli.py; it must match."""
    resolved = config.resolve(bluecore_url="https://bcld.info/", load_dotenv=False)

    assert resolved.token_url == (
        "https://bcld.info/keycloak/realms/bluecore/protocol/openid-connect/token"
    )


class TestDotenvDiscovery:
    """A .env has to be found where the user is working.

    python-dotenv's find_dotenv() searches upward from the file that called it
    by default -- this package, inside site-packages -- so without usecwd the
    CLI never sees the .env sitting next to the user.
    """

    def resolve_in(self, monkeypatch, directory):
        """Resolve with dotenv loading really enabled, from `directory`.

        The suite-wide fixture stubs load_dotenv out, so the genuine function
        has to be the one captured at import time -- by now the module
        attribute is the stub.
        """
        monkeypatch.setattr("dotenv.load_dotenv", real_load_dotenv)
        monkeypatch.chdir(directory)
        return config.resolve()

    def test_a_dotenv_in_the_working_directory_is_read(self, monkeypatch, tmp_path):
        (tmp_path / ".env").write_text(
            "BLUECORE_URL=https://from-dotenv.example.org\n"
            "API_KEYCLOAK_USER=dotenv-user\n"
            "API_KEYCLOAK_PASSWORD=dotenv-pass\n"
        )

        resolved = self.resolve_in(monkeypatch, tmp_path)

        assert resolved.api_url == "https://from-dotenv.example.org/api"
        assert resolved.username == "dotenv-user"
        assert resolved.has_credentials, "so a write command won't prompt"

    def test_a_real_environment_variable_beats_the_dotenv(self, monkeypatch, tmp_path):
        (tmp_path / ".env").write_text("API_KEYCLOAK_USER=dotenv-user\n")
        monkeypatch.setenv("API_KEYCLOAK_USER", "real-env-user")

        assert self.resolve_in(monkeypatch, tmp_path).username == "real-env-user"

    def test_no_dotenv_is_not_an_error(self, monkeypatch, tmp_path):
        resolved = self.resolve_in(monkeypatch, tmp_path)

        assert resolved.api_url  # the default deployment
        assert not resolved.has_credentials


def test_client_id_defaults_to_the_one_the_api_expects():
    resolved = config.resolve(bluecore_url="https://bcld.info/", load_dotenv=False)

    assert resolved.client_id == "bluecore_api"
