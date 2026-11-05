"""The library has to work without the CLI's dependencies installed.

Services such as Airflow plugins install plain ``bluecore-client``, with no
``[cli]`` extra. These tests can't simply uninstall typer, rich and
python-dotenv, and this interpreter already has them imported, so each one runs
a fresh interpreter with them blocked.
"""

import subprocess
import sys

import pytest

from bluecore_client.cli import INSTALL_HINT

CLI_PACKAGES = ("typer", "rich", "dotenv")


def run(script, *, blocked=CLI_PACKAGES):
    """Run ``script`` in a new interpreter, as if ``blocked`` weren't installed.

    A ``None`` in ``sys.modules`` makes any import of that name raise
    ModuleNotFoundError, which is what a missing package does.
    """
    block = "import sys\n" + "".join(
        f"sys.modules[{name!r}] = None\n" for name in blocked
    )
    return subprocess.run(
        [sys.executable, "-c", block + script],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )


def test_the_library_imports_and_builds_a_client_without_the_cli_extra():
    """import bluecore_client and BluecoreClient() work with no CLI packages.

    load_dotenv=True is the default, so this also checks that a missing
    python-dotenv is skipped rather than raising.
    """
    result = run(
        "import bluecore_client\n"
        "client = bluecore_client.BluecoreClient(load_dotenv=True, anonymous=True)\n"
        "print(client.api_url)\n"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://dev.bcld.info/api"


@pytest.mark.parametrize("package", ["typer", "rich"])
def test_the_command_says_how_to_install_what_it_needs(package):
    """Without the cli extra, bluecore names the missing package and the fix.

    It exits 1 with a message instead of a traceback. The message names the
    top-level package -- "rich", never "rich.console" -- since that is what
    someone would install.
    """
    result = run("from bluecore_client.cli import main\nmain()\n", blocked=[package])

    assert result.returncode == 1
    assert result.stderr.startswith(f"{package} is not installed.")
    assert INSTALL_HINT in result.stderr
