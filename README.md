# Blue Core Client

[![Test](https://github.com/blue-core-lod/bluecore-client/actions/workflows/test.yml/badge.svg)](https://github.com/blue-core-lod/bluecore-client/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/bluecore-client)](https://pypi.org/project/bluecore-client/)

A command line tool and Python library for the [Blue Core API].

Blue Core describes library resources using [BIBFRAME]. Reads return JSON-LD as
plain Python dictionaries; turtle, RDF/XML and N-Triples are available too.

## Install

For the `bluecore` command and the library:

```shell
pip install 'bluecore-client[cli]'
```

Or, with [uv], to get the `bluecore` command on its own without installing into
a project:

```shell
uv tool install 'bluecore-client[cli]'
```

To use only the Python library, as a service or plugin would, leave off
`[cli]`. That skips typer, rich and python-dotenv. Without python-dotenv a
`.env` file isn't read, so pass settings directly or set them in the
environment.

## Try it

By default everything points at `https://dev.bcld.info`, and reading
needs no credentials, so you can start looking around straight away:

```shell
bluecore search moon
```

```
Moon handbooks
  https://dev.bcld.info/works/d18a81bf-42ac-4ee5-b71b-b9de61833c62
Moon sign book
  https://dev.bcld.info/works/395f1ae0-7e93-46c0-bf76-5b5b3d98841a
Moon Atlantic Canada
  https://dev.bcld.info/works/3801e757-10a5-40e6-9fa9-af9c64ad5187
```

On a wide enough terminal the same results are laid out in columns. Either way
the URI is never truncated, because copying it is the point.

Then follow your nose. Any command taking a UUID will also take a full Blue
Core URI, so you can paste what you just found:

```shell
bluecore work view 4403fbce-ba01-5a4e-a8fc-03fc71caf56d
bluecore work view https://dev.bcld.info/works/d18a81bf-42ac-4ee5-b71b-b9de61833c62
```

## Command line

```shell
# Look around
bluecore search moon
bluecore search moon --type works --all
bluecore search '"le mal joli"'          # quoted: match the words in order

# Read
bluecore work view <uuid-or-uri>
bluecore work view <uuid-or-uri> --expand
bluecore -o turtle work view <uuid-or-uri>
bluecore instance view <uuid-or-uri>
bluecore hub view <uuid-or-uri>
bluecore resource list
bluecore profile list

# History
bluecore changes list works
bluecore changes feed instances

# Write
bluecore work create record.jsonld
bluecore work update <uuid-or-uri> record.jsonld
bluecore work delete <uuid-or-uri>

# Load in bulk
bluecore load url https://example.org/records.jsonld
bluecore load file records.ttl        # converted to JSON-LD before upload
bluecore load file records.zip
bluecore load profiles

# Convert MARC, without storing anything
bluecore convert bibframe record.mrc
bluecore convert marcxml record.mrc

# Where am I pointed, and as whom?
bluecore whoami
```

### Listing and paging

`--all` walks every page, printing results as each page arrives rather than
collecting everything first, so output starts immediately:

```shell
bluecore search moon --all          # all 1095, streaming
bluecore profile list --all
bluecore changes list works --all
```

With `--all` the client asks for the largest page the endpoint allows -- 100 for
search, per the API's own schema -- to keep the number of round trips down. The
count at the end reports what actually printed, not what the API predicted.

### When something goes wrong

`--verbose` narrates each request, which is the quickest way to tell a slow API
from a wrong URL:

```shell
$ bluecore --verbose search moon
api      https://dev.bcld.info/api
keycloak https://dev.bcld.info/keycloak
auth     anonymous
→ GET https://dev.bcld.info/api/search/?q=moon&type=all&limit=20&offset=0
200 in 0.34s
```

`--timeout` caps how long to wait, rather than sitting there:

```shell
$ bluecore --timeout 10 search moon
✗ Could not reach https://dev.bcld.info/api (ReadTimeout: The read operation timed out)
```

### Output serializations

`-o` / `--output` is global, so it works with any command:

| `-o` | What you get |
|---|---|
| *(default)* | Human-readable: one record per line, or pretty JSON-LD for a single resource |
| `json` | The API's own response, with `total` and per-record metadata |
| `jsonld` | The records as one merged JSON-LD graph |
| `turtle` | Turtle |
| `rdfxml` | RDF/XML |
| `ntriples` | N-Triples |
| `sinopia` | `application/vnd.sinopia+json` |

```shell
bluecore -o json search moon | jq -r '.results[].uri'
bluecore -o turtle work view <uuid-or-uri>
bluecore -o turtle search moon --all > moon.ttl
bluecore -o ntriples search moon --type instances
```

For a single resource the API does the serializing, so you get the deployment's
own output. For a result set the API only offers JSON-LD, so the client merges
the results into one graph and serializes that, which can't
stream, unlike the default output. Change feeds are Activity Streams rather
than BIBFRAME, so `-o jsonld` leaves them as they are and the other RDF
serializations are refused.

`json` and `jsonld` differ on purpose: `json` is the API's response as it came,
with `total` and each record's `uri`, `uuid` and timestamps, which is what you
want for scripting. `jsonld` is the RDF those records describe, merged into one
graph, which is the same graph as `turtle`, just in a different syntax.

### Round tripping

Because `jsonld` is a graph rather than an envelope, anything you save can be
loaded back:

```shell
bluecore -o turtle search moon --all > moon.ttl
bluecore load file moon.ttl
```

`load file` takes JSON-LD, turtle, RDF/XML or N-Triples. The loading workflow
only reads JSON-LD, so anything else is converted before it is sent.

The same applies to a single resource:

```shell
bluecore -o jsonld work view <uuid> > work.jsonld
bluecore work update <uuid> work.jsonld
```

Data goes to stdout and status messages to stderr, so `-o turtle ... > out.ttl`
gives you a clean file.

`bluecore token` prints an access token and nothing else, so it can be captured
directly:

```shell
curl -H "Authorization: Bearer $(bluecore token)" \
  https://dev.bcld.info/api/works/<uuid>
```

Run `bluecore --help`, or `bluecore <command> --help`, for the rest.

## Credentials

Reading is anonymous, so `search`, `view`, and `list` need nothing configured.
Anything that writes, such as `create`, `update`, `delete`, `load`, `export`,
`convert`, and `token`, do need credentials, and will prompt for them if it
can't find any. Point it at another deployment the same way:

```shell
bluecore --bluecore-url https://bcld.info/ --username me search moon
```

To avoid being prompted, set these in your environment, or in a `.env` file in
the directory you're working in:

| Variable | What it's for |
|---|---|
| `BLUECORE_URL` | Root of the deployment; the API and Keycloak are derived from it |
| `API_KEYCLOAK_USER` | Username |
| `API_KEYCLOAK_PASSWORD` | Password |
| `API_URL` | The API directly, when it isn't at `BLUECORE_URL/api` |
| `KEYCLOAK_EXTERNAL_URL` | Keycloak directly, when it isn't at `BLUECORE_URL/keycloak` |
| `BLUECORE_TOKEN` | An access token, instead of logging in |

Setting `API_KEYCLOAK_USER` and `API_KEYCLOAK_PASSWORD` is enough to stop the
prompt appearing; `BLUECORE_TOKEN` skips the Keycloak login as well. A real
environment variable takes precedence over a `.env` entry, and either can be
overridden per command with `--username` and `--password`.

These are the same names [Blue Core API] uses, so an existing `.env` works
as-is. For a local development server, which serves the API at the bare root
rather than under `/api`:

```shell
bluecore --api-url http://localhost:3000 \
         --keycloak-url http://localhost:8081/keycloak/ \
         search ""
```

# Using it as a library

Everything the CLI does is available in Python, and it's meant to be useful 
in a Jupyter notebook.

```python
from bluecore_client import BluecoreClient

client = BluecoreClient()
work = client.works.get("4403fbce-ba01-5a4e-a8fc-03fc71caf56d")

work["@id"]  # 'https://dev.bcld.info/works/4403fbce-...'
work["@type"]  # ['Work', 'Text', 'Monograph']
```

`work` is a dictionary. Index it, `json.dumps` it, put it in a dataframe.

As on the command line, a URI works anywhere a UUID does:

```python
client.works.get("https://dev.bcld.info/works/4403fbce-...")
```

## Connecting

```python
client = BluecoreClient()  # the default deployment

client = BluecoreClient(  # somewhere else
    bluecore_url="https://bcld.info/",
    username="me",
    password="...",
)

client = BluecoreClient(  # a local dev server
    api_url="http://localhost:3000",
    keycloak_url="http://localhost:8081/keycloak/",
)

client = BluecoreClient(token="...")  # a token you already have
```

The client logs in and refreshes the token before it expires. You never have to
handle one. Pass `anonymous=True` to skip authentication entirely, which is
enough for reads. It's also a context manager, if you'd like the connection pool
closed promptly:

```python
with BluecoreClient() as client:
    ...
```

Redirects aren't followed unless you ask. A redirect can re-send your token
and request body somewhere you didn't choose, or quietly turn a POST into a
GET, so a 3xx raises `Redirected` instead. Pass `follow_redirects=True` if you
want them followed; the `bluecore` command does.

## Reading

```python
client.works.get(uuid)  # a dict of JSON-LD
client.works.get(uuid, expand=True)  # with referenced resources included
client.works.get(uuid, format="ttl")  # Turtle, as a string
client.instances.get(uuid)
client.instances.cbd(uuid)  # concise bounded description
client.hubs.get(uuid)
client.resources.get(resource_id)
client.profiles.get(uuid)
```

JSON formats come back parsed; everything else comes back as text. Available
formats: `jsonld`, `json`, `ttl`, `rdf`, `nt`, `cbd.jsonld`, `cbd.xml`,
`vnd.sinopia.json`.

For a result set, which the API only returns as JSON-LD, `as_rdf` merges the
records into one graph and serializes it:

```python
page = client.search("moon", limit=50).first()

print(client.as_rdf(page))  # turtle
print(client.as_rdf(page, "ntriples"))
client.as_rdf(client.works.get(uuid))  # a single graph works too
```

Or work with the graph directly:

```python
from bluecore_client import rdf

graph = rdf.to_graph(rdf.graphs_of(page.items), context=client.context())
len(graph)  # an rdflib Graph
```

## Searching and paging

Search returns a lazily-paged result set. Iterate it and pages are fetched as
you reach them, so this is safe on a large result set:

```python
for result in client.search("moon"):
    print(result["uri"])
```

Work a page at a time when you'd rather control the fetching:

```python
pages = client.search("moon", limit=50)
first = pages.first()
first.total  # how many matches there are altogether
len(first)  # how many are on this page

for page in pages.pages():
    ...
```

The same applies to `client.profiles.list()` and `client.resources.list()`.

> **Note:** the API has no collection endpoint for Works, Instances, or Hubs --
> there is no `GET /works/` -- so there is no `client.works.list()`. To
> enumerate them, use `client.search("")` or read the change document feeds.

## Change feeds

The Activity Streams feeds are an append-only history, which makes them the
dependable way to harvest a deployment:

```python
client.changes.feed("works")  # the collection document
client.changes.page(1, "works")  # one page
for activity in client.changes.activities():  # every activity, oldest first
    ...
```

## Writing

Create and update take a JSON-LD graph as a dictionary. No string-encoding
needed:

```python
client.works.create(
    {
        "@context": {"@vocab": "http://id.loc.gov/ontologies/bibframe/"},
        "@type": ["Work", "Text"],
        "title": [{"@type": "Title", "mainTitle": "Le mal joli"}],
    }
)

client.works.update(uuid, graph)
client.works.delete(uuid)
```

## Loading in bulk

Loading is handed off to Airflow, so these return a workflow id rather than
waiting for the load to finish:

```python
client.batches.from_url("https://example.org/records.jsonld")
client.batches.upload("records.ttl")  # converted to JSON-LD first
client.batches.upload("records.zip")
client.batches.upload("odd.txt", convert=False)  # send the bytes as they are
```

## Errors

Everything raises a subclass of `BluecoreError`, carrying the API's own message:

```python
from bluecore_client import NotFound

try:
    client.works.get("nope")
except NotFound as error:
    print(error)  # Work nope not found (GET .../works/nope)
```

`AuthError`, `PermissionDenied`, `ValidationError`, `ConnectionFailed`, and
`APIError` are the others. `APIError` keeps the `status_code` and the underlying
`response`; `ConnectionFailed` means the API couldn't be reached at all, so a
timeout or refused connection never surfaces as a bare traceback.

## Development

```shell
uv sync
uv run ruff format
uv run ruff check
uv run ty check
uv run pytest
```

CI runs those four in that order, so a formatting or typing problem fails
before the suite does.

Integration tests are excluded from the default run. To run them, start Blue
Core locally (see the [Blue Core API] README), then:

```shell
export BLUECORE_TEST_API_URL=http://localhost:3000
export KEYCLOAK_EXTERNAL_URL=http://localhost:8081/keycloak/
export API_KEYCLOAK_USER=developer
export API_KEYCLOAK_PASSWORD=123456
uv run pytest -m integration
```

## Status

Sync only for now. An `AsyncBluecoreClient` is planned, as a real
`httpx.AsyncClient` twin rather than a wrapper -- a sync facade that called
`asyncio.run()` internally would fail inside a notebook's running event loop.

[Blue Core API]: https://github.com/blue-core-lod/bluecore_api
[BIBFRAME]: https://id.loc.gov/ontologies/bibframe.html
[uv]: https://github.com/astral-sh/uv
