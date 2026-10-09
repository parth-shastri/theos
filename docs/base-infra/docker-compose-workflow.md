# Docker Compose workflow

[compose.yaml](../../compose.yaml) defines one service named `theos`.
It includes the source build, host port, named volume, and resource limits.
[compose.dev.yaml](../../compose.dev.yaml) adds source mounts for development.
There is no production overlay file.

## Resolve configuration

Run from the repository root:

```sh
docker compose config --quiet
```

Compose uses `.env` for interpolation and as the service environment file.
Explicit service environment values override values from that file.
These overrides fix the container host, port, and data path.

`--env-file` changes Compose interpolation input.
It does not replace `env_file: .env` inside the service definition.
Use `.env` for the documented deployment path.
Avoid printing the full resolved configuration because it can include credentials.

## Source build

```sh
docker compose up --build -d
```

The default image tag is `theos:local`.
`AGENT_IMAGE` changes that tag.
A source build does not require a published registry image.

## Prebuilt image

1. Set `AGENT_IMAGE` to an image reference that you control and can pull.
2. Pull the selected image.

   ```sh
   docker compose pull theos
   ```

3. Start it without a local build.

   ```sh
   docker compose up --no-build -d
   ```

The repository does not establish a public image registry contract.
Pin an immutable image reference when reproducibility matters.

## Network and state

| Setting | Value |
| --- | --- |
| Application bind inside the container | `0.0.0.0:8080` |
| Host mapping | `${HOST_BIND_IP:-127.0.0.1}:${HOST_PORT:-8080}:8080` |
| Application data | `/data` |
| Default named volume | `theos-data` |
| Application workers | One |
| Scheduler instances | One per data directory |

The host binding also applies with the development overlay.
Telegram uses outbound polling.
The [deployment guide](../DEPLOYMENT.md#private-browser-access) explains private browser access.

## Runtime limits

The container uses a read-only root filesystem and a 64 MiB temporary filesystem at `/tmp`.
It drops all Linux capabilities and enables `no-new-privileges`.
The process limit is 128.
The default limits are one CPU and 768 MiB of memory.
`AGENT_CPU_LIMIT` and `AGENT_MEMORY_LIMIT` change those limits.

The restart policy is `unless-stopped`.
Compose allows 45 seconds for shutdown.
The JSON log driver rotates at 5 MB with at most three files.
Application log rotation uses separate settings described in [observability](observability.md).

## Lifecycle commands

| Task | Command |
| --- | --- |
| Start from source | `docker compose up --build -d` |
| Read status | `docker compose ps` |
| Read container output | `docker compose logs --tail=100 theos` |
| Restart the process | `docker compose restart theos` |
| Apply environment changes | `docker compose up -d --force-recreate` |
| Stop the service | `docker compose stop theos` |
| Start a stopped container | `docker compose start theos` |
| Remove containers and network | `docker compose down` |

`down` retains the named volume unless you request volume removal.
See [operations](../operations.md) before deleting state.

## Development mounts

```sh
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

The overlay mounts `src/theos`, `src/harness`, `src/renderer`, and `src/config` as read-only source directories.
It sets `PYTHONPATH=/app/src`.
Restart after Python changes.
Rebuild after changes to dependencies or the Dockerfile.
The overlay does not configure automatic reload.
