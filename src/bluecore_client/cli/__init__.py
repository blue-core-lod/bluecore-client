"""The ``bluecore`` command line interface."""

from __future__ import annotations

import sys

#: Packages the command imports at startup that the library itself does not
#: need. python-dotenv is in the cli extra too, but it is imported lazily, so a
#: missing copy can't stop the command from starting.
_CLI_PACKAGES = frozenset({"typer", "rich"})

INSTALL_HINT = (
    "The bluecore command needs the cli extra:\n"
    "  pip install 'bluecore-client[cli]'\n"
    "or, to install the command on its own:\n"
    "  uv tool install 'bluecore-client[cli]'"
)


def main() -> None:
    """Run ``bluecore``, or say how to install what it needs."""
    try:
        from bluecore_client.cli.app import app
    except ModuleNotFoundError as error:
        package = (error.name or "").partition(".")[0]
        if package not in _CLI_PACKAGES:
            raise
        sys.exit(f"{package} is not installed. {INSTALL_HINT}")
    app()
