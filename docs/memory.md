# Self-host Mem0 or use managed Mem0

Theos stores conversation history and personal records in its local database.
Optional memory tools call a separate Mem0 service.
The application retrieves relevant facts before private-chat model calls when memory is enabled.
Automatic consolidation requires per-user opt-in and approval.
Explicit memory tools remain available.

## Automatic retrieval and consolidation

Retrieval searches with the current message and the authenticated owner.
It adds up to five memories as labeled, untrusted reference data for the turn.
It does not save that reference block into conversation history.
Current user corrections take precedence over retrieved facts.
Groups do not receive automatic retrieval or consolidation.
An unavailable memory service does not stop normal chat.

Ask “Enable automatic memory consolidation” in a private conversation, then approve the policy change.
The `configure_memory_automation` tool controls retrieval and consolidation independently.
The `get_memory_automation_status` tool reports the policy and queue status counts.
Disabling consolidation removes pending queued copies but does not reverse an in-flight write or delete existing remote memories.

After opt-in, completed private turns enqueue their new user text.
The worker sends a batch after five queued messages or ten minutes, whichever comes first.
Each remote request contains at most five messages of 4,000 characters each.
Each owner can have at most 100 pending messages.
The worker submits user messages and source IDs to Mem0 OSS `/memories`.
Mem0's configured model extracts and merges facts.
Theos does not create authoritative personal records from these facts.

Assistant output, tool output, scheduled prompts, and group messages never enter this queue.
Turns that pause for approval do not enqueue the original message on later approval-only continuation.
Common credential patterns cause retrieval and consolidation to skip a message.
This filter cannot detect every secret in free text.
Completed, discarded, and uncertain batches retain metadata but erase their queued text.
Original chat history follows the normal conversation retention policy.

The worker records each attempt before the HTTP write.
An interrupted or failed write becomes `unknown` and is not retried automatically.
Inspect the remote memory before requesting an explicit save again.
The scheduler handles consolidation separately from reminders and Health work.

| Setting | Default | Purpose |
| --- | --- | --- |
| `AGENT_MEMORY__AUTO_RETRIEVE` | `true` | Default retrieval policy when memory is enabled |
| `AGENT_MEMORY__RETRIEVAL_LIMIT` | `5` | Maximum retrieved facts |
| `AGENT_MEMORY__RETRIEVAL_CHARS` | `4000` | Maximum fact text characters, excluding labels and JSON |
| `AGENT_MEMORY__RETRIEVAL_TIMEOUT` | `3` | Retrieval deadline in seconds |
| `AGENT_MEMORY__CONSOLIDATION_TURNS` | `5` | Queued-message threshold for consolidation |
| `AGENT_MEMORY__CONSOLIDATION_INTERVAL` | `600` | Maximum wait in seconds before a partial batch becomes due |

An explicit user policy overrides the default retrieval policy.
There is no deployment flag that grants consolidation consent to all users.
This feature does not index and retrieve complete past conversations as episodes.

The [speech hosting guide](speech-hosting.md) uses the same service boundary.
It describes separate services, private endpoints, Tailscale access, and live checks.
This guide describes the Mem0 options and the current Theos client limits.

## Choose a deployment

| Option | Service owner | Theos support | Data location |
| --- | --- | --- | --- |
| Self-hosted Mem0 OSS | You run the Mem0 API, dashboard, and database | Supported by the current REST client | Your Mac mini and its database volume |
| Managed Mem0 Platform | Mem0 runs the service and database | Needs a Theos Platform adapter | Mem0 Platform |

The current Theos client targets the Mem0 open-source REST API.
The hosted Platform API uses different paths, request shapes, and authentication.
Changing only the endpoint or key does not make Platform work with this client.

## Current client contract

Theos registers these tools when `AGENT_MEMORY__ENABLED=true`:

| User action | Tool |
| --- | --- |
| Save information on request | `save_memory` |
| Find related facts | `search_memory` |
| List saved facts | `get_all_memories` |
| Read a selected fact | `get_memory` |
| Replace a saved fact | `update_memory` |
| Remove a saved fact | `delete_memory` |

The client calls the unversioned OSS routes: `POST /memories`, `POST /search`, and `GET /memories`.
It also uses `GET`, `PUT`, and `DELETE /memories/{id}` for one record.
See the [Mem0 OSS REST API](https://docs.mem0.ai/open-source/features/rest-api) and the [memory client](../src/theos/services/memory/client.py).

Theos sends the authenticated owner as `user_id` for saves, searches, and lists.
It hides search and list results without matching top-level owner metadata.
It checks the remote owner before it reads, updates, or deletes a record.
The OSS API authenticates the API key but does not bind `user_id` to that key.
An authorized API caller can request a different `user_id`.
Restrict the API to the Theos host and trusted administrators with Tailscale policy.
Add an owner-scoping gateway before you give API access to other clients.

The memory service manages its own model, embedding, and vector-store dependencies.
Memory failures return tool errors and do not stop ordinary chat.
The [live acceptance checklist](runtime/acceptance.md#live-service-checks) still requires a real save, search, edit, delete, and cross-user check.

## Self-hosted Mem0 on a Mac mini

The Mem0 OSS setup can run the API, dashboard, and PostgreSQL with pgvector in a separate Compose project.
Its `postgres_db` volume belongs to Mem0 and stays separate from Theos storage.
See the [Mem0 OSS setup guide](https://docs.mem0.ai/open-source/setup) for the current install steps.
Run Mem0 and Tailscale commands on the Mac mini.

### Configure OpenRouter

Mem0 OSS uses OpenRouter for chat when you set `OPENROUTER_API_KEY`.
The OpenAI-compatible embedding adapter reads `OPENAI_API_KEY` and `OPENAI_BASE_URL`.
Set both keys to your OpenRouter key when OpenRouter supplies both models.
Choose model IDs from the [OpenRouter model catalog](https://openrouter.ai/models).
See the [Mem0 chat adapter](https://github.com/mem0ai/mem0/blob/main/mem0/llms/openai.py) and [embedding adapter](https://github.com/mem0ai/mem0/blob/main/mem0/embeddings/openai.py) for these settings.

Add these values to the Mem0 server `.env` file:

```dotenv
POSTGRES_PASSWORD=replace-with-long-postgres-password
JWT_SECRET=replace-with-random-secret
OPENROUTER_API_KEY=replace-with-openrouter-key
OPENROUTER_API_BASE=https://openrouter.ai/api/v1
OPENAI_API_KEY=replace-with-the-same-openrouter-key
OPENAI_BASE_URL=https://openrouter.ai/api/v1
MEM0_DEFAULT_LLM_MODEL=replace-with-openrouter-chat-model-id
MEM0_DEFAULT_EMBEDDER_MODEL=replace-with-openrouter-embedding-model-id
```

Mem0 needs a chat model and an embedding model.
Check the OpenRouter catalog for a model that supports embeddings before you select it.
The OpenRouter key here belongs to the Mem0 server.
Theos still uses its own model-provider settings.
Keep authentication enabled and leave `AUTH_DISABLED=false`.
Mem0 requires `POSTGRES_PASSWORD` and `JWT_SECRET` for this deployment.
Generate `JWT_SECRET` with `openssl rand -base64 48` and save the result in the Mem0 `.env` file.

### Configure the Compose services

Keep the Compose ports bound to Mac mini loopback when only tailnet clients need access.
In the Mem0 Compose file, use these host bindings:

```yaml
ports:
  - "127.0.0.1:8888:8000" # Mem0 API
```

Use `127.0.0.1:3000:3000` for the dashboard and `127.0.0.1:8432:5432` for PostgreSQL.
These mappings do not require a Dockerfile change.
Tailscale Serve forwards each local port to a tailnet endpoint.

Add this value to the `mem0.environment` list for API CORS:

```yaml
- DASHBOARD_URL=https://MEM0_HOST.TAILNET.ts.net:8443
```

Set these values in the `mem0-dashboard.environment` list:

```yaml
- NEXT_PUBLIC_API_URL=https://MEM0_HOST.TAILNET.ts.net:9443
- API_INTERNAL_URL=http://mem0:8000
```

Replace `MEM0_HOST.TAILNET.ts.net` with the Mac mini's Tailscale DNS name.
The dashboard uses the HTTPS API address from the browser.
The dashboard container uses `API_INTERNAL_URL` to reach the API on the Compose network.
Recreate the dashboard after you change `NEXT_PUBLIC_API_URL`.
The Mem0 API uses `DASHBOARD_URL` to allow the dashboard's browser origin.

### Start Mem0 and keep its key

On a fresh install, run these commands from the Mem0 server directory:

```bash
docker compose config --quiet
make bootstrap
docker compose ps
```

`make bootstrap` starts the stack and creates the first admin account and programmatic API key.
Save the admin login and API key because the command shows the full credentials once.
The programmatic API key uses the `X-API-Key` header.
The key authenticates the Theos service, not each Theos user.
Keep it in Theos's private `.env` file and do not give it to end users.
Do not use the legacy `ADMIN_API_KEY` as the Theos memory key.
Do not run `docker compose down -v` unless you intend to delete the database volume.

If you already started Mem0, apply Compose changes from its server directory:

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

### Publish Mem0 through Tailscale Serve

Run these commands on the Mac mini.
If the earlier port `443` rule sends traffic to Mem0, remove that rule first.

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8888 off
```

Start the API, dashboard, and PostgreSQL forwarding rules:

```bash
tailscale serve --bg --https=9443 http://127.0.0.1:8888
tailscale serve --bg --https=8443 http://127.0.0.1:3000
tailscale serve --bg --tcp=5432 tcp://127.0.0.1:8432
tailscale serve status
```

Use the tailnet HTTPS endpoint for the API and dashboard.
Use the Mac mini Tailscale DNS name and port `5432` for PostgreSQL clients.
Tailscale access follows your tailnet access policy.
See [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve).

### Connect Theos

Set these values in Theos's private `.env` file:

```dotenv
AGENT_MEMORY__ENABLED=true
AGENT_MEMORY__ENDPOINT=https://MEM0_HOST.TAILNET.ts.net:9443
AGENT_MEMORY__API_KEY=replace-with-mem0-programmatic-key
AGENT_MEMORY__AUTH_HEADER=X-API-Key
AGENT_MEMORY__AUTH_PREFIX=
AGENT_MEMORY__TIMEOUT=15
```

Replace the host and key values with your settings.
Use the Mem0 API endpoint without a `/v1` suffix.
The Theos client adds the OSS paths shown above.
Keep the API and database private to your tailnet.
The [speech hosting guide](speech-hosting.md#connect-either-deployment-over-tailscale) shows the same Serve pattern for voice services.

### Check the service

1. Check the API and dashboard in `tailscale serve status`.
2. Open the dashboard from a device on your tailnet.
3. Check that the dashboard can call the API at port `9443`.
4. Recreate Theos so it reads the new environment values.
5. Run the external-memory checks in the [acceptance checklist](runtime/acceptance.md#live-service-checks).

The Mem0 containers use their Compose restart policy after Docker starts.
Enable Docker Desktop at login on the Mac mini.
Back up the Mem0 database volume separately from Theos data.

## Managed Mem0 Platform

Mem0 Platform runs the API and data store for you.
Create an account and API key with the [Platform quickstart](https://docs.mem0.ai/platform/quickstart).
The [Platform API reference](https://docs.mem0.ai/api-reference) describes current routes and authentication.
Platform requests use `Authorization: Token <key>` and versioned routes.

The current Theos client cannot call Platform directly.
Its `/search` request and unversioned `/memories` routes do not match the Platform API.
The client also expects OSS response fields and ownership metadata.
Do not set `AGENT_MEMORY__ENDPOINT=https://api.mem0.ai` as a working configuration.

Theos needs a Platform adapter before this option can work.
That adapter must translate paths, methods, request and response shapes, authentication, and owner scope.
The live acceptance check must then confirm that Platform rejects access to another user's memories.
Until that work is complete, use the OSS service for Theos memory tools.

## Framework status

![Memory framework](architecture/theos-memory.png)

The diagram shows the broader target framework.
Current behavior includes harness context handling, explicit memory tools, automatic fact retrieval, and consented consolidation through Mem0.
Complete conversation retrieval and a separate Theos extraction model remain future work.

Source: [memory client](../src/theos/services/memory/client.py) and [memory tools](../src/theos/services/memory/tools.py).
