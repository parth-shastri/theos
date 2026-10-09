# First deployment

This procedure runs Theos from source with Docker Compose.
Run commands from the repository root.
The Compose service name is `theos`, regardless of `AGENT_NAME`.

## Before you start

You need a Linux server, Docker with the Compose plugin, and a copy of this repository.
You also need a model credential and a Telegram bot token for Telegram use.
The image uses Python 3.13. CI checks Linux amd64, arm64, 386, ARMv7, PPC64LE, s390x, and RISC-V64 builds.
See [architecture coverage](releases.md#architecture-coverage) for native and emulated checks and deployment limits.
The default resource limits are one CPU and 768 MiB of memory.
These limits are not measured minimum requirements.

The [acceptance checklist](runtime/acceptance.md) records container checks.
A real Raspberry Pi workload and live Telegram delivery remain pending checks.

## Choose a deployment option

Theos supports self-hosted installations and a hosted service for Telegram users.
Both options use the same server and account services.
The deployment operator configures application credentials.
Each user authorizes their own Google accounts.

| Responsibility | Self-hosted installation | Hosted service |
| --- | --- | --- |
| Server, bot, and model credential | Each installation owner | The service operator |
| Google project and Web OAuth client | Each installation owner | The service operator |
| Callback URLs and token encryption key | Each installation owner | The service operator |
| Account consent | Each user through browser Connections or private Telegram | Each user through browser Connections or private Telegram |
| Token and personal record storage | The installation database | The service database, scoped to each user |

For self-hosting, complete this deployment procedure with your own credentials.
Then configure [Gmail](gmail.md) and [Google Health](google-health.md) if required.
Do not include your Web client secret in a distributed installation package.

For a hosted service, complete this procedure once as the operator.
Configure Google credentials and reachable HTTPS callbacks on your server.
Give users the bot username and the deployment access code, if configured.
Users complete `/start` and authorize accounts with `/connect_gmail`, `/connect_health`, and `/connect_zepto`.
Users do not need a Google Cloud project, application secrets, or access to `.env`.

The current server allows at most 50 Telegram users per database.
This limit also counts incomplete registrations.
Use one application worker and scheduler per database, and one poller per bot token.
This setup does not implement a service for thousands of users or a central OAuth broker for independent installations.

## Prepare hosted Google access

The service operator must complete Google's requirements before offering Google connections to the public.
Personal or limited testing access does not prove public approval.
Gmail uses a restricted scope.
Google requires scope verification and a server security assessment unless an exception applies.
See [Google's verification requirements](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification).

An External Google app in Testing only accepts configured test users.
Its Gmail and Health refresh tokens expire after seven days.
See [Google's token expiration rules](https://developers.google.com/identity/protocols/oauth2#expiration).

Google currently does not onboard new Health API projects.
Check [Health availability](https://developers.google.com/health/get-started) before promising access to new self-hosted installations.
An existing mobile login does not prove approval for the server's additional Google scopes.
Complete the [live account checks](runtime/acceptance.md#live-service-checks) before public launch.

## Configure the application

1. Copy the minimal configuration.

   ```sh
   cp .env.minimal .env
   ```

2. Restrict access to the file.

   ```sh
   chmod 600 .env
   ```

3. Generate a browser token on a trusted computer with Python.

   ```sh
   python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
   ```

4. Set `AGENT_NAME` to the assistant name.
5. Replace `AGENT_API_KEY` with the model credential.
6. Replace the token in `AGENT_USERS` with the generated value.
7. Set `AGENT_TIMEZONE` to your timezone.
8. Configure the bot and allowlist with the [Telegram guide](telegram-setup.md).

The default model configuration is:

```dotenv
AGENT_NAME=Theos
AGENT_PROVIDER=openai
AGENT_MODEL=gpt-6-luna
```

`AGENT_ADMINS` must contain only user IDs from `AGENT_USERS`.
Every browser token must be unique and contain at least 32 characters.
For Telegram alone, set `AGENT_USERS={}` and `AGENT_ADMINS=[]`.
That configuration disables browser account access.

The [full sample](../.env.full.example) includes optional integrations.
The [configuration guide](base-infra/environment-variables.md) explains every setting.

## Build and start

1. Check the Compose configuration.

   ```sh
   docker compose config --quiet
   ```

2. Build and start the service.

   ```sh
   docker compose up --build -d
   ```

3. Check the container status.

   ```sh
   docker compose ps
   ```

4. Check application readiness.

   ```sh
   curl --fail http://127.0.0.1:8080/ready
   ```

5. Send `/start` to the bot from an allowed Telegram account.
6. Send a short message to check the model response.
7. Inspect resource use.

   ```sh
   docker stats --no-stream
   ```

Readiness checks the database and basic model configuration.
It does not prove that a model credential or optional service works.
For a local check without model charges, set `AGENT_PROVIDER=fake`.
The fake provider returns a fixed answer and does not call tools.

## Private browser access

The host port binds to `127.0.0.1` by default.
The application listens on `0.0.0.0:8080` inside the container.

1. Create a Secure Shell (SSH) tunnel from your computer.

   ```sh
   ssh -L 8080:127.0.0.1:8080 user@your-server
   ```

2. Open `http://127.0.0.1:8080` on your computer.
3. Enter the browser token.

For a private network, set `HOST_BIND_IP` to the server address on that network.
Use an HTTPS reverse proxy when traffic crosses an untrusted network.
Telegram polling needs outbound HTTPS and no public webhook.
Google account connections need a reachable callback URL.

## Terminal access to the deployment

Install `theos[client]` on your computer or VPS host.
Use the same server URL and browser token for the terminal client.

```sh
theos --server http://127.0.0.1:8080
```

This URL works on the VPS or through the existing localhost tunnel.
For direct Tailscale access, use the server's reachable Tailscale address and published port.
Compose binds localhost by default. Use the existing tunnel or set `HOST_BIND_IP` to the VPS Tailscale address.
The client shares the browser user's conversations and account-tool permissions.
The deployment retains its single runtime, database, and scheduler when terminal clients connect or disconnect.
Do not start a standalone runtime against the deployment volume.
Read the [terminal guide](terminal.md#connect-to-a-deployment) for saved configuration, SSH use, and disconnect recovery.

## After the first start

1. Create a backup with the [operations procedure](operations.md#back-up).
2. Complete the [live checks](runtime/acceptance.md#live-service-checks) for each enabled service.
3. Record the source revision and image ID for recovery.

Uploads, concurrent turns, and long histories increase memory use.
Use one worker and one scheduler for each data directory.
Do not scale the Compose service above one replica.
For a small machine, set `AGENT_MAX_CONCURRENT_TURNS=1` before increasing the workload.
