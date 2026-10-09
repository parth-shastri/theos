# Troubleshooting

Start with container status and readiness:

```sh
docker compose ps
curl --fail http://127.0.0.1:8080/ready
docker compose logs --tail=100 theos
```

Application events use a separate file.
See [observability](base-infra/observability.md#read-application-events) for the command.
Do not repeat an uncertain external write until you check the target service.

## Environment values do not apply

The application reads only the `AGENT_` namespace.
Older `THEOS_` values do not configure the application.
A Compose process restart does not replace the container environment.

1. Compare variable names with the [configuration guide](base-infra/environment-variables.md).
2. Check the JSON syntax of lists and maps.
3. Check for shell variables that override Compose interpolation.
4. Recreate the service.

   ```sh
   docker compose config --quiet
   docker compose up -d --force-recreate
   ```

`--env-file` alone does not replace the service `env_file: .env` declaration.
The Compose file also overrides `AGENT_HOST`, `AGENT_PORT`, and `AGENT_DATA_DIR` inside the container.

## Startup rejects settings

| Error area | Corrective action |
| --- | --- |
| Name | Use 1 to 100 characters after trimming whitespace |
| Browser token | Use unique tokens with at least 32 characters |
| Administrator | Add the user to `AGENT_USERS` first |
| Telegram | Use an enrollment limit from 1 to 50 |
| OAuth | Set all three fields for each enabled Google service |
| Encryption key | Supply a valid Fernet key for configured Gmail, Health, or Zepto accounts |
| R2 | Set all four storage fields together |
| Timezone | Use a valid zone such as `Asia/Kolkata` or `UTC` |

## The model turn fails

1. Check `AGENT_PROVIDER`, `AGENT_MODEL`, and `AGENT_API_KEY`.
2. Check access to the provider from the application host.
3. Use `AGENT_REASONING=default` if the model rejects explicit reasoning effort.
4. Check `AGENT_MODEL_BASE_URL` for the OpenAI, OpenRouter, or llama client path.
5. Read the `turn_failed` event and the conversation result.

Readiness only checks whether a required key is nonempty.
It does not authenticate the key with the provider.
The fake provider helps isolate local chat behavior from provider access.

## The browser is unreachable

1. Check `/live` on the server itself.
2. Check `HOST_BIND_IP` and `HOST_PORT`.
3. Use the [SSH tunnel](DEPLOYMENT.md#private-browser-access) for a loopback deployment.
4. Check the reverse proxy if the direct local request succeeds.

If another process occupies port 8080, change `HOST_PORT`.
Then recreate the service.
For local Python, change `AGENT_PORT` instead.
Browser API status `401` means the token does not identify a configured user.
Dashboard status `403` means the user lacks administrator access.

## Telegram does not respond

1. Check the bot token in `AGENT_TELEGRAM_TOKEN`.
2. If `AGENT_TELEGRAM_USERS` is nonempty, check that it includes the sender ID.
3. For a group, check its ID in `AGENT_TELEGRAM_CHATS`.
4. Stop any other process that polls the same bot.
5. Check outbound access to the Telegram API.
6. Check model access with a short text message.

An unauthorized update receives no model turn.
Send `/start` in a private chat and complete timezone setup before ordinary chat.
If the bot requests an access code, send `/start <access-code>` with the value configured by the operator.
The operator sets `AGENT_TELEGRAM_ACCESS_CODE` in private `.env` and restarts the application to apply changes.
Changing the code requires existing users to authorize again.
A registration-full response means the database has reached `AGENT_TELEGRAM_MAX_USERS`.
Incomplete setup and existing private users count toward that limit.
A configured token does not prove that Telegram accepts it.
The transport uses polling and has no webhook setup path.
After a delivery failure, inspect saved conversation state before sending the same action again.

## Photos or voice notes fail

The default file limit is 10 MiB.
Images also have a 25-million-pixel limit and content checks.
A vision request needs a model that accepts images.
Voice notes need `AGENT_TRANSCRIPTION_URL` and a working transcription service.
The base URL must include `/v1` when the service expects it.
See [files and voice](files-and-voice.md).

## Another application owns the database

The error `This database already has an application process. Use one worker.` indicates an active process lock.

1. Stop the extra application process or container.
2. Run one worker for that data directory.
3. Start the selected service again.

Deleting `process.lock` does not safely stop the process that owns its lock.
Use a separate data directory for an independent development instance.

## State appears missing

1. Check `AGENT_DATA_VOLUME` in the Compose environment.
2. Check the mounted volume in the container configuration.
3. For local Python, check `AGENT_DATA_DIR` and the current working directory.
4. Check the authenticated owner and conversation transport.

Different browser IDs, private Telegram IDs, groups, and topics can expose different records.
A name change does not migrate or rename the data directory.
Do not restore over an active volume.
Use the [restore procedure](operations.md#restore).

## A volume rejects writes

The application runs as user `10001` inside the container.
A custom mount must permit that user to write.
The supplied named volume uses the image directory ownership.
For restored data, use the ownership step in the restore procedure.
Do not change unrelated host directory permissions.

## A Google account fails to connect

1. Check the exact redirect URI in `.env` and the Google client configuration.
2. Check that the callback reaches the application.
3. Start authorization again from browser Connections or an allowed private Telegram chat.
4. Grant all scopes requested by that service.
5. Restore the original encryption key if saved tokens cannot decrypt.

Authorization state expires after ten minutes and works once.
For `redirect_uri_mismatch`, compare the scheme, hostname, port, and complete callback path.
The callback must match both the registered Google URI and the reachable Theos address.
For local HTTP on port 8080, use `http://localhost:8080/oauth/gmail/callback` and `http://localhost:8080/oauth/health/callback`.
Recreate the container after changing `.env`, then start a new authorization.
If Google returns no refresh token, revoke the previous grant and connect again.
See [Gmail](gmail.md) and [Google Health](google-health.md).

## Meal exports stop

A saved local meal can have a pending or failed remote export.
Do not log the same meal again to retry its export.
Ask for `get_meal_sync_status`, then use `retry_meal_sync` after correcting the service problem.
An earlier failed job can block later jobs for the same owner and kind.
Read [export recovery](google-health.md#export-status-and-retries) before changing account state.

## An optional service fails

| Service | Check |
| --- | --- |
| Memory | Endpoint, credential header, timeout, and returned ownership metadata |
| Search | Exa or Brave credential and outbound access |
| Sandbox | Server address, credential, image, and remote sandbox lifetime |
| Browser automation | `agent-browser` and browser dependencies in the remote image |
| R2 | Endpoint, bucket, all credentials, and object permissions |
| Speech | Kokoro URL, voice, and `/audio/speech` support |
| Zepto | Trusted HTTPS MCP endpoint, encryption key, and private account connection |

Container loopback points to the assistant container.
A service on another host needs an address reachable from that container.
Ordinary chat does not require memory or Zepto discovery to succeed.
See [Zepto setup](zepto-mcp.md) for callback and connection checks.
