# marks

Free Kraken tentacle. MIT. Do not import `kraken.core`.

Local bookmarks. A bookmarklet talks only to `127.0.0.1` with a token kept under `$KRAKEN_HOME`. Tracking query params are stripped. Folders default to the registrable host.

```
JSON in → policy → exec → JSON out
```

## Docs

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Store, token, why window.open not fetch |
| [docs/USAGE.md](docs/USAGE.md) | Actions, bookmarklet install |
| [docs/SUCKERS.md](docs/SUCKERS.md) | marks-file + workflows |
| [docs/SECURITY.md](docs/SECURITY.md) | Loopback, token mode, mixed content |
| [docs/TESTING.md](docs/TESTING.md) | Suites |
| [docs/DIRECTORY.md](docs/DIRECTORY.md) | Catalog listing plan |
| [../KRAKEN_DIRECTORY_PLAN.md](../KRAKEN_DIRECTORY_PLAN.md) | Shared watch + marks directory plan |

## Install

```bash
./build.sh
kraken tentacle add .
kraken tentacle add examples/tentacles/marks-file
kraken run marks ping
kraken run marks bookmarklet
kraken run marks listen --payload '{"once":true}'
```

## Command shapes

```bash
kraken run marks add --payload '{"url":"https://kraken.topta.co/?utm_source=x","tags":["cli"]}'
kraken run marks search --payload '{"q":"kraken","folder":"kraken.topta.co"}'
kraken workflow run workflows/save-and-file.yaml
kraken workflow run workflows/watch-then-mark.yaml
```
