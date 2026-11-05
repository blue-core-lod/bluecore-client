"""Loading data in bulk.

Loading is asynchronous, the API hands the work to Airflow and returns a
workflow id, so a success here means "accepted", not "loaded".
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from bluecore_client.cli import ui
from bluecore_client.cli.context import client, die, settings
from bluecore_client.errors import BluecoreError
from bluecore_client.resources import profiles

app = typer.Typer(name="load", help="Load BIBFRAME data in bulk.", no_args_is_help=True)


@app.command("url")
def load_url(
    url: Annotated[str, typer.Argument(help="URL of a JSON-LD document to load")],
) -> None:
    """Load a JSON-LD document from a URL."""
    try:
        target = client(require_auth=True)
        with ui.working(f"Submitting {url}"):
            result = target.batches.from_url(url)
    except BluecoreError as error:
        die(error)
        return

    _report(result, f"Queued {url}")


@app.command("file")
def load_file(
    file: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="RDF file (JSON-LD, turtle, RDF/XML, N-Triples) or an archive",
        ),
    ],
) -> None:
    """Upload a file to load.

    Accepts any RDF serialization -- JSON-LD, turtle, RDF/XML, N-Triples -- or a
    .zip / .tar.gz archive of them. Anything that isn't already JSON-LD is
    converted first, since the loading workflow only reads JSON-LD.

    So output redirected from this tool can be fed straight back in:

        bluecore -o turtle search moon --all > moon.ttl
        bluecore load file moon.ttl
    """
    try:
        target = client(require_auth=True)
        with ui.working(f"Uploading {file.name}"):
            result = target.batches.upload(file)
    except BluecoreError as error:
        die(error)
        return

    _report(result, f"Uploaded {file.name}")


@app.command("profiles")
def load_profiles(
    host: Annotated[
        str, typer.Argument(help="Blue Core host to copy profiles from")
    ] = "https://dev.bcld.info",
    page_size: Annotated[
        int, typer.Option("--page-size", help="How many to fetch at a time")
    ] = 50,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Report what would be loaded")
    ] = False,
) -> None:
    """Copy resource profiles from another Blue Core instance.

    Each profile is created through the API, so the local instance mints its own
    URI and rewrites the profile's resource template to match. Note this
    creates profiles rather than updating existing ones, so running it twice
    will load two copies.

    A profile names the profiles it nests by URI, and the API does not rewrite
    those on create -- so copied profiles arrive still pointing at the source
    deployment. A second pass repoints them at their local counterparts, which
    is what lets the nesting survive the copy.
    """
    from bluecore_client import BluecoreClient

    target = client(require_auth=True)
    # The remote read hits a public endpoint, so don't try to log in there.
    source = BluecoreClient(bluecore_url=host, anonymous=True, load_dotenv=False)

    loaded = 0
    try:
        with ui.working(f"Reading profiles from {host}"):
            incoming = list(source.profiles.search(limit=page_size))
    except BluecoreError as error:
        die(f"Could not read profiles from {host}: {error}")
        return
    finally:
        source.close()

    if dry_run:
        for profile in incoming:
            ui.note(f"  would load {profile.get('uri', '')}")
        ui.warn(f"Dry run: {len(incoming)} profiles, nothing written")
        return

    # Source URI -> what the local instance minted for it, which is what the
    # second pass rewrites references through.
    remap: dict[str, str] = {}
    created_profiles = []

    for profile in incoming:
        data = profile.get("data")
        if data is None:
            ui.failure(f"{profile.get('uri', '')}: no profile data to copy")
            continue
        try:
            created = target.profiles.create(data)
        except BluecoreError as error:
            ui.failure(f"{profile.get('uri', '')}: {error}")
            continue
        loaded += 1
        created_profiles.append(created)
        source_uri, local_uri = profile.get("uri"), created.get("uri")
        if source_uri and local_uri:
            remap[source_uri] = local_uri
        if settings.verbose:
            ui.note(f"  {profile.get('uri', '')} {ui.ARROW} {created.get('uri', '')}")

    if loaded == len(incoming):
        ui.success(f"Loaded {ui.count(loaded, 'profile')}")
    else:
        ui.warn(f"Loaded {loaded} of {len(incoming)} profiles")

    _relink(target, created_profiles, remap, host)


def _relink(
    target, created_profiles: list[dict], remap: dict[str, str], host: str
) -> None:
    """Repoint each copied profile's nesting references at their local counterparts.

    This has to run after everything is created: a reference names a profile by
    URI, and the local URI is not known until the API mints it.

    Rewrites what the API stored rather than what the source sent. Creating a
    profile re-homes its own ``@id`` onto the minted URI, and sending the source
    document back would undo that.
    """
    relinked = 0
    missing: set[str] = set()
    not_a_uri: set[str] = set()

    for created in created_profiles:
        data = created.get("data")
        if data is None:
            continue
        rewritten, unresolved = profiles.relink(data, remap)
        not_a_uri |= {ref for ref in unresolved if not ref.startswith("http")}
        missing |= {ref for ref in unresolved if ref.startswith("http")}
        if rewritten == data:
            continue
        uuid = created.get("uuid")
        if not uuid:
            continue
        try:
            target.profiles.update(str(uuid), rewritten)
        except BluecoreError as error:
            ui.failure(f"{created.get('uri', '')}: could not relink: {error}")
            continue
        relinked += 1

    if relinked:
        ui.success(f"Relinked {ui.count(relinked, 'profile')}")
    if missing:
        ui.warn(
            "1 reference names a profile that was not copied"
            if len(missing) == 1
            else f"{len(missing)} references name profiles that were not copied"
        )
        if settings.verbose:
            for ref in sorted(missing):
                ui.note(f"  {ref}")
    if not_a_uri:
        # bluecore-models resolves nesting by URI only. A hasResourceId string
        # means the source still holds pre-0.34.0 data, so there is nothing
        # here to repoint -- say that rather than reporting it as missing.
        counted = (
            "1 reference is an id rather than a URI"
            if len(not_a_uri) == 1
            else f"{len(not_a_uri)} references are ids rather than URIs"
        )
        ui.warn(
            f"{counted}; {host} may need migrating before its nesting can be copied"
        )
        if settings.verbose:
            for ref in sorted(not_a_uri):
                ui.note(f"  {ref}")


def _report(result: dict, message: str) -> None:
    """Report a queued batch, including the workflow that will run it."""
    if settings.wants_document:
        ui.emit_json(result)
        return

    ui.success(message)
    workflow_id = result.get("workflow_id")
    if workflow_id:
        ui.note(f"  workflow {workflow_id}")
