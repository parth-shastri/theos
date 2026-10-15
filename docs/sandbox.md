# Remote sandbox

The sandbox service runs code, commands, and browser actions outside the assistant container.
Theos uses the [OpenSandbox Python SDK](https://open-sandbox.ai/sdks/) and code interpreter client.
The operator deploys the sandbox server separately.

## Configure

1. Deploy an OpenSandbox server with appropriate resource and network limits.
2. Set an address reachable from the assistant container.
3. Configure the server credential and remote image.
4. Enable the tools.
5. Recreate the application container.

```dotenv
AGENT_SANDBOX__ENABLED=true
AGENT_SANDBOX__DOMAIN=sandbox.example.internal:8080
AGENT_SANDBOX__API_KEY=replace-me
AGENT_SANDBOX__USE_SERVER_PROXY=false
AGENT_SANDBOX__IMAGE=theos/sandbox-skills:v1.1.0-20261015
AGENT_SANDBOX__TIMEOUT_SECONDS=3600
```

The image must provide `/opt/code-interpreter/code-interpreter.sh`.
Theos supplies this entrypoint because the SDK default does not start the interpreter.
The timeout ranges from 60 to 3600 seconds.
The client requests one CPU and 512 MiB for each new sandbox. Live PDF, DOCX, XLSX, OCR, and browser checks passed at this limit. Existing sandboxes keep their original image and resource limit until they are replaced.
The server, image registry, and remote network remain operator responsibilities.
Container loopback does not reach a sandbox server on another host.

## Mac mini over Tailscale

Theos can run on one Mac while OpenSandbox and Docker run on the Mac mini.
Use server proxy mode so only the OpenSandbox server port needs access from Theos.

1. Run `tailscale ip -4` on the Mac mini.
2. Edit the existing sections in `/Volumes/extssd/opensandbox/config.toml` on the Mac mini.
3. Use the Mac mini's Tailscale address in the Theos client configuration.
4. Set a generated API key in the server configuration.

```toml
[server]
host = "0.0.0.0"
port = 8085
api_key = "replace-with-generated-key"

[proxy]
resolve_internal = false

[docker]
network_mode = "bridge"
host_ip = "127.0.0.1"
publish_host = "127.0.0.1"

[store]
type = "sqlite"
path = "/Volumes/extssd/opensandbox/opensandbox.db"
```

Preserve the other generated sections, including `[runtime]`.
The server proxy uses local published ports because macOS cannot directly route to Docker bridge addresses.
Keep Docker Desktop's disk image on the external SSD to store container files there.

5. For a manual installation, start the server on the Mac mini.

```sh
uvx --from opensandbox-server==1.1.1 opensandbox-server --config /Volumes/extssd/opensandbox/config.toml
```

6. Configure Theos on its own host with the same key.

```dotenv
AGENT_SANDBOX__ENABLED=true
AGENT_SANDBOX__DOMAIN=100.x.y.z:8085
AGENT_SANDBOX__API_KEY=replace-with-generated-key
AGENT_SANDBOX__USE_SERVER_PROXY=true
AGENT_SANDBOX__IMAGE=theos/sandbox-skills:v1.1.0-20261015
AGENT_SANDBOX__TIMEOUT_SECONDS=3600
```

7. Permit the Theos machine to reach TCP port 8085 under the tailnet access rules.
8. Restart Theos after editing its environment.
9. Check the server from the Theos machine.

```sh
curl --fail http://100.x.y.z:8085/health
```

10. Ask Theos to execute `print(2 + 2)` in the sandbox and approve the request.

Health checks do not verify authentication, sandbox creation, or execution.
The live Tailscale workflow remains pending until these operations succeed.
See the [OpenSandbox configuration reference](https://github.com/opensandbox-group/OpenSandbox/blob/main/server/configuration.md) for proxy and Docker settings.

### Operator deployment

The active launch agent uses `/Volumes/extssd/opensandbox/config.toml` and OpenSandbox server `1.1.1`.
The database and server logs also use `/Volumes/extssd/opensandbox`.
The earlier Application Support configuration remains as an inactive copy.
Use the existing launch agent instead of starting a second server on port 8085.

The agent label is `com.parthshastri.theos-opensandbox`.
Its plist lives under `/Users/parthshastri/Library/LaunchAgents`.
Keep its working directory under the user's home directory.
Keep its console logs under `/Users/parthshastri/Library/Logs`.
macOS blocks launchd from opening console logs on the removable volume.
The application access log and server log remain on the SSD.

The active server binds to `0.0.0.0` and publishes sandbox ports on `127.0.0.1`.
This lets the native server proxy reach local ports when `resolve_internal=false`.
The Pi still uses the Mac mini's Tailscale address for the server connection.
Preload both runtime images before executing code:

```sh
docker pull opensandbox/code-interpreter:v1.1.0
docker pull opensandbox/execd:v1.1.0
```

On 2026-10-11, a direct Pi SDK check passed creation, Python execution, file retrieval, and destruction.
The check explicitly used the interpreter entrypoint `/opt/code-interpreter/code-interpreter.sh`.
Theos now supplies that entrypoint when creating a sandbox.
A patched application client check from the Pi passed Python execution, file retrieval, reconnection, and destruction in 10.57 seconds.
A separate range execution reached its deadline after interpreter readiness.
The checks did not cover Telegram delivery or browser automation.

## Shared skill runtime image

Build the ARM64 image on the Mac mini. It keeps the OpenSandbox code-interpreter entrypoint and adds the tools declared by the eight shared skills: PDF and spreadsheet libraries, arXiv and Papers with Code clients, DOCX support, LibreOffice, Pandoc, Poppler, OCR, Chromium, and `agent-browser`. The report style files live at `/opt/theos/report-style`, with Python dependencies and the `theos-report` command ready to use. Local fonts remove the renderer's external font downloads.

The dependency lock is `skills/sandbox-runtime/requirements.lock`. It targets Python 3.14, which the code-interpreter kernel uses. The image exposes the locked packages to both that kernel and shell commands. Update the lock from `requirements.in` with `uv pip compile` when skill dependencies change. Copy both skill directories to the Mac mini, then build the image there:

```sh
rsync -a --delete skills/sandbox-runtime/ parths-mac-mini:/Volumes/extssd/opensandbox/theos-skill-build/skills/sandbox-runtime/
rsync -a --delete skills/report-style/ parths-mac-mini:/Volumes/extssd/opensandbox/theos-skill-build/skills/report-style/
ssh parths-mac-mini 'docker build -f /Volumes/extssd/opensandbox/theos-skill-build/skills/sandbox-runtime/Dockerfile -t theos/sandbox-skills:v1.1.0-20261015 /Volumes/extssd/opensandbox/theos-skill-build/skills'
```

Update the image tag in the Pi deployment environment when the runtime changes, then recreate Theos. The image stays in the Mac mini's local Docker store because OpenSandbox and its container runtime use that Docker host. New sandboxes use the new image. Existing sandboxes retain their files and old image until they expire or are explicitly replaced.

## Browser dependencies

`browser` invokes `agent-browser` inside the remote sandbox. The shared skill runtime image installs the CLI and Chromium. Installing browser software in the assistant container does not install it in the remote sandbox.

## Tools and approval

| Area | Tools |
| --- | --- |
| Execution | `run_command`, `execute_code` |
| Text files | `write_file`, `read_file`, `list_files` |
| File transfer | `upload_file`, `send_file_to_user` |
| Images | `view_image` |
| Browser | `browser` |
| Lifetime | `manage_workspace` |

Sandbox execution does not require approval.
Uploaded files remain bound to the authenticated owner.
Generated files enter the local private catalog before delivery.
The model can receive a checked workspace image through `view_image`.

## Lifetime and recovery

Each conversation owns a remote sandbox ID.
The application saves the ID and reconnects after an application restart.
A saved ID does not guarantee that the remote sandbox still exists.
Routine startup, reconnection, and checkpoint restoration are automatic. Use `manage_workspace` with `status`, `restart`, `destroy`, or `forget` only when the user asks to inspect or control the workspace.
The legacy `renew` action returns status without extending expiry.
`forget` removes the saved connection reference without destroying a remote instance.

The default lifetime is one hour from creation. Reconnection and activity do not reset this deadline.
The client checks cached instances before execution and replaces confirmed missing or expired instances automatically.
Transient connection failures retain the existing reference. They do not trigger replacement or repeat a command.
Managed workspaces restore saved files before saving a replacement instance.
Download important generated files before destroying the remote environment.
SQLite and R2 retain versioned workspace checkpoints. Unsaved work in a dead sandbox cannot be recovered.

## Credential boundary

Theos supplies no application credentials or host mounts to the sandbox.
The server credential authenticates the client connection from the application.
It does not become an environment credential inside generated code.
Keep model, Google, Telegram, and storage secrets out of uploaded files and command arguments.

Source: [sandbox service](../src/theos/services/sandbox/).
See [acceptance](runtime/acceptance.md#live-service-checks) for the pending live lifecycle check.
