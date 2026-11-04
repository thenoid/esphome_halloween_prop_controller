# Controller event collector

A passive, Dockerized archive for **all** Halloween controllers. `HC1` is the wire-protocol version, not controller 1. No firmware changes or Home Assistant connection are required. The service never sends UDP packets or operates props.

It includes a browser timeline, SQLite persistence, controller/event/item/time filters, paginated JSON and CSV export, summary counts, OpenAPI documentation, health checks, and an optional read-only MCP bridge for assistant clients.

## Start with Docker Compose

Use native Docker Engine on an always-on **Linux host attached to the controllers' broadcast network**. Copy this whole `event-collector` directory to that host. From inside it:

```sh
cp .env.example .env
python3 - <<'PY'
from pathlib import Path
import secrets
path = Path('.env')
path.write_text(path.read_text().replace('COLLECTOR_API_TOKEN=\n', 'COLLECTOR_API_TOKEN=' + secrets.token_urlsafe(32) + '\n', 1))
path.chmod(0o600)
PY
docker compose -f docker-compose.yaml up -d --build
docker compose -f docker-compose.yaml ps
```

Open `http://YOUR-LINUX-HOST:8080/` and paste the token from `.env`. The browser keeps it in page memory, not local storage or URLs. Reloading the page requires reconnecting. The archive starts empty: trigger an event to see a source controller appear. Each page displays 200 observations; **Load older events** pauses automatic refresh. CSV export includes up to the newest 1,000 matching events and reports truncation.

Default ports are **18512/UDP** for ingestion and **8080/TCP** for the UI/API. Compose uses `network_mode: host`, so there is no `ports:` mapping. The named volume `collector-data` persists across container replacement and ordinary `docker compose down`; `down -v` deletes it. The process runs as UID/GID 10001 with a read-only root filesystem. Bind-mounted data directories, if used instead, must be writable by that UID.

The token is required (at least 32 non-whitespace ASCII characters). `docker compose config` resolves and displays it: do not paste that output into public issues. Keep HTTP access on a trusted network, or terminate HTTPS at a reverse proxy and restrict direct HTTP access. The token protects queries; the existing UDP protocol itself is unauthenticated and claimed controller names are not verified identities.

## Network placement

The current firmware broadcasts to `255.255.255.255:18512`. A receiver on another VLAN/subnet will not ordinarily see these packets, and a published Docker bridge port does not guarantee receipt of LAN broadcasts. Native Linux host networking avoids that extra NAT boundary. Wi-Fi client isolation and broadcast filtering can still prevent reception.

For a collector on a routed network, explicitly add its unicast IPv4 address to the existing controller `udp.addresses` list alongside `255.255.255.255`, keeping the same port. That is an optional firmware change, not necessary on the same broadcast network. Allow the traffic through the intervening firewall. Avoid generic broadcast forwarding, which could also forward controller commands.

Docker Desktop uses a VM. Its optional host-networking feature is not a substitute for verifying LAN broadcast delivery; use native Linux for unattended collection. Tests use only loopback addresses and never send test packets onto the props' network. See [Docker host networking](https://docs.docker.com/engine/network/drivers/host/).

## REST API

Interactive documentation: `/docs`; machine-readable schema: `/openapi.json`. These and the UI assets are public, but every `/api/v1` endpoint requires `Authorization: Bearer TOKEN`. The Swagger documentation uses CDN-hosted assets; the review page works without Internet access.

| Method/path | Purpose |
| --- | --- |
| `GET /healthz` | Minimal unauthenticated readiness; 200 `ok` or 503 `degraded` |
| `GET /api/v1/status` | Listener/storage health, retained archive size, process counters and queue depth |
| `GET /api/v1/controllers` | Every source in retained history, counts and first/last receipt times |
| `GET /api/v1/events` | Filtered, cursor-paginated observations; newest first by default |
| `GET /api/v1/summary` | Filtered counts grouped by source, event and item |
| `GET /api/v1/events.csv` | Same filters and pagination as events; up to 1,000 records per request |

Supported query filters: `source`, `event`, `item` (1–4), `reason`, `since`, `until`, `after_id`, `before_id`. Times must include a timezone; `since` is inclusive and `until` exclusive. `order=asc|desc` and `limit=1..1000` apply to events and CSV. Summary applies the filters before grouping. Unknown sources return empty results. Invalid filters return 422.

For example, with the token in your shell environment:

```sh
curl --fail --silent --show-error \
  -H "Authorization: Bearer ${COLLECTOR_API_TOKEN}" \
  'http://YOUR-LINUX-HOST:8080/api/v1/events?event=sequence.started&limit=100'
```

Example response (documentation values only):

```json
{
  "events": [{
    "id": 42,
    "received_at": "2026-10-31T18:00:00Z",
    "source": "prop-controller-3",
    "event": "sequence.ready",
    "item": 2,
    "reason": "stopped",
    "sender_ip": "192.0.2.3",
    "sender_port": 18512,
    "raw_packet": "HC1|prop-controller-3|sequence.ready|2|stopped"
  }],
  "has_more": false,
  "next_after_id": null,
  "next_before_id": 42
}
```

For integration polling, request `order=asc&after_id=0&limit=1000`, process the records, and persist `next_after_id` only after successful processing. Keep fetching while `has_more` is true; when caught up, poll again with the last processed ID. An empty page has null cursors: keep your previous cursor. For descending history, pass `before_id=next_before_id`. IDs increase across restarts and retention deletes, but are local to a database; reset consumers if replacing the database. Concurrent inserts can change summary counts between requests; there is no multi-request snapshot guarantee.

CSV returns `X-Has-More`, `X-Next-After-Id` and `X-Next-Before-Id` headers. Use the corresponding ID filter for subsequent pages. Controller names starting with spreadsheet formula characters are prefixed with an apostrophe in CSV only.

There are no event injection, deletion, relay-control or arbitrary-SQL endpoints.

## Assistant integration with MCP

The optional stdio bridge exposes `collector_status`, `list_controllers`, `list_events`, and `summarize_events` as read-only tools. It authenticates to the REST API and has no direct database or controller access. Starting it does not start another collector.

On the computer running your MCP client, install [uv](https://docs.astral.sh/uv/getting-started/installation/) **0.13.6**, then create the locked Python 3.13 runtime environment from this directory:

```sh
uv sync --locked --no-dev
```

The client must launch `.venv/bin/python -m collector.mcp_bridge` with this directory as its working directory, `COLLECTOR_URL` set to the reachable collector URL, and `COLLECTOR_API_TOKEN` set to the same token. No OpenAI API key is needed by the bridge.

For Codex, the following is a configuration **example**, not a change automatically made by this project:

```toml
[mcp_servers.controller_events]
command = "/absolute/path/event-collector/.venv/bin/python"
args = ["-m", "collector.mcp_bridge"]
cwd = "/absolute/path/event-collector"
env_vars = ["COLLECTOR_API_TOKEN"]

[mcp_servers.controller_events.env]
COLLECTOR_URL = "http://YOUR-LINUX-HOST:8080"
```

Make the token available in the environment used to launch the client, or configure it through your client's supported secret environment settings. The collector's `.env` is read by Docker Compose, not automatically by the MCP bridge. Restart/reconnect the client after configuration. This follows [official OpenAI MCP configuration documentation](https://learn.chatgpt.com/docs/extend/mcp). The current chat is not automatically connected by creating these files.

Alternatively, run the bridge from a locally built container image, without mounting the archive volume:

```sh
docker run --rm -i --env-file .env \
  -e COLLECTOR_URL=http://YOUR-LINUX-HOST:8080 \
  controller-event-collector:local python -m collector.mcp_bridge
```

Use `-i` without a TTY for stdio MCP. The URL must be reachable from the bridge container; `127.0.0.1` there refers to the bridge container itself. Build the image on that client machine first if it is different from the collection host. The image name is local, not a published registry image.

## Storage, health and limitations

SQLite lives at `/data/events.sqlite3` with WAL and full synchronization. A bounded queue keeps database writes outside the UDP event loop. Graceful shutdown stops reception, then drains the queue. Only one application worker/container may own a given UDP listening address/port; conflicting binds fail startup. Keep the database on a local Docker volume, not a network filesystem.

Retention defaults to **90 days**, purged at startup and hourly. Set `COLLECTOR_RETENTION_DAYS=0` to disable purging. Deleted pages may be reused, so the database file need not shrink immediately. To back up, stop the collector and copy the data volume, including any WAL files; then restart it. Do not copy only the live main database file. Protect backups as private activity history.

`/api/v1/status` distinguishes retained `stored_events` from process-lifetime counters: `packets_received`, `invalid_packets`, `events_written`, `queue_overflows`, `write_errors`, `udp_errors`, `events_purged`. Counters reset on restart. Overflow and failed writes are lost observations, explicitly counted; they are not retried. A current write/retention error or failed listener/writer makes readiness degraded. Previous error/loss counters remain visible after recovery. Docker health checks report readiness; Docker's restart policy restarts exited processes, not merely unhealthy ones.

No traffic is a valid idle condition. `last_packet_at` includes malformed packets; `last_event_at` is the last successfully stored valid receipt in this process; `newest_received_at` includes earlier runs. Controller last-seen timestamps are not connectivity checks. Use API monitoring to alert on losses and collection failures separately from quiet props.

The wire format has no device timestamp, event ID, sequence-run ID, authentication, acknowledgement or replay. `received_at` is UTC **collector receipt time**, not device occurrence time. Duplicates are kept because repeated legitimate events cannot reliably be distinguished from duplicate packets. Events missed while the network/collector is unavailable cannot be recovered. Actual device operation is not guaranteed by any event. Existing sensor simulation events are indistinguishable from real contacts, and not every relay transition or discarded trigger has an event.

## Development and verification

Use uv **0.13.6**; the project enforces this tested version. Python 3.13 is selected by `.python-version` and the project's Python constraint. uv can install that Python version if it is not already available locally.

```sh
uv sync --locked
uv run --locked --no-sync python -m unittest discover -s tests -v
```

A C++17 compiler is required to compare packet acceptance against the firmware's actual decoder. Tests also cover packets from multiple controllers, malformed and duplicate packets, HTTP authentication, filters, pagination, CSV export, retention, restart persistence, queue/storage failures, shutdown draining, port conflicts, and a complete stdio MCP → HTTP → SQLite query. All credentials and archives are disposable.

`pyproject.toml` declares the runtime dependencies and the development group; `uv.lock` pins the complete dependency graph and package artifact hashes. Commit both together. `uv sync --locked` includes development dependencies for tests; `uv sync --locked --no-dev` installs only runtime dependencies for the MCP bridge and production image. A stale lockfile fails the sync instead of being silently rewritten. To deliberately update a dependency, use `uv add 'package==version'` or `uv lock --upgrade-package package`, inspect the lockfile diff and rerun the tests.

Docker uses pinned uv **0.13.6** in a dependency-build stage, with a BuildKit cache mount. The final image contains the runtime virtual environment and launches Python directly; startup performs no uv sync, package downloads or dependency resolution. No uv installation is needed on the Docker host. The Compose commands and persistent volume remain unchanged. The `.dockerignore` allowlist includes only the project metadata, lockfile, Python selection and application sources, keeping local virtual environments and credentials out of the build context.

For the Linux container smoke test:

```sh
docker build -t controller-event-collector:test .
uv run --locked --no-sync python tests/docker_smoke.py
```

It creates a temporary container/volume, sends broadcasts only within Linux's loopback network (`127.255.255.255`), checks API results and non-root execution, restarts to verify persistence, and removes its temporary resources. Public CI runs both suites and validates Compose with a disposable token.
