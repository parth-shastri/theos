# Remote sandbox

The sandbox service runs code, commands, and browser actions outside the assistant container.
Theos uses the [OpenSandbox Python SDK](https://open-sandbox.ai/sdks/) for command execution.
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
AGENT_SANDBOX__IMAGE=theos/sandbox-skills:v1.1.0-20261019-18e1cc81d4c3
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
AGENT_SANDBOX__IMAGE=theos/sandbox-skills:v1.1.0-20261019-18e1cc81d4c3
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

Build the ARM64 image on the Mac mini. It keeps the OpenSandbox code-interpreter entrypoint and adds the tools declared by the eight shared skills: PDF and spreadsheet libraries, arXiv and Papers with Code clients, DOCX support, LibreOffice, Pandoc, Poppler, OCR, Chromium, and `agent-browser`. The report style files live at `/opt/theos/report-style`, with Python dependencies and the `theos-report` command ready to use. Bundled Space Grotesk fonts remove external font downloads. Matplotlib supplies numeric charts through headless Agg. Its default PDF fonts are embedded, and SVG text uses paths.

The dependency lock is `skills/sandbox-runtime/requirements.lock`. It targets Python 3.14, which the code-interpreter kernel uses. The image exposes the locked packages to both that kernel and shell commands. Update the lock from `requirements.in` with `uv pip compile` when skill dependencies change. Copy both skill directories to the Mac mini, then build the image there:

```sh
rsync -a --delete skills/sandbox-runtime/ parths-mac-mini:/Volumes/extssd/opensandbox/theos-production-18e1cc81d4c3/skills/sandbox-runtime/
rsync -a --delete skills/report-style/ parths-mac-mini:/Volumes/extssd/opensandbox/theos-production-18e1cc81d4c3/skills/report-style/
rsync skills/.dockerignore parths-mac-mini:/Volumes/extssd/opensandbox/theos-production-18e1cc81d4c3/skills/.dockerignore
ssh parths-mac-mini 'docker image inspect theos/sandbox-skills:v1.1.0-20261019-18e1cc81d4c3 >/dev/null 2>&1 || docker build -f /Volumes/extssd/opensandbox/theos-production-18e1cc81d4c3/skills/sandbox-runtime/Dockerfile -t theos/sandbox-skills:v1.1.0-20261019-18e1cc81d4c3 /Volumes/extssd/opensandbox/theos-production-18e1cc81d4c3/skills'
```

Update the image tag in the Pi deployment environment when the runtime changes, then recreate Theos. The image stays in the Mac mini's local Docker store because OpenSandbox and its container runtime use that Docker host. New sandboxes use the new image. Existing sandboxes retain their files and old image until they expire or are explicitly replaced.

Use a new revision tag for each runtime build. Keep image records while running sandboxes reference them.
Rebuilding a reused tag removed an old image record during local Docker Desktop acceptance testing.
The container kept running, but OpenSandbox status requests returned HTTP 500 when they inspected the missing image.

## Browser dependencies

The shared runtime image installs `agent-browser` 0.38.1 and Chromium.
The model calls standalone browser commands through `run_command`. The runtime routes these commands to an owner-scoped browser sandbox.
Each conversation uses its own tab. The runtime serializes browser actions for the same owner.
Task sandbox replacement does not replace the browser sandbox.
Browser sandbox replacement restores the encrypted profile, including saved authentication state.

Use Browser sign-in in Connections to open a website and complete login or verification.
Select a field in the screenshot, then use Private input to enter text.
Use Next field and Press Enter for keyboard navigation. Refresh updates the screenshot.
Clear saved browser login destroys the owner's browser and deletes its saved profile.
These controls do not send conversation messages or model tool calls.

Profile capture briefly pauses browser writers. A watchdog resumes them if capture exits or exceeds its deadline.
Snapshots include SQLite recovery journals and exclude cache directories and process locks.
The application stores encrypted snapshots in SQLite. Keep `browser.key` with stopped-application backups.
The profile and encryption key never enter task workspaces or response attachments.
A site can still expire a login or require verification.

## Tools and approval

| Area | Interface |
| --- | --- |
| Shell, Python, and filesystem work | `run_command(command)` |
| Model image inspection | `run_command(inspect_images=["/workspace/chart.png"])` |
| Browser | `run_command(command="agent-browser snapshot -i")` |
| Browser screenshot inspection | `run_command(command="agent-browser screenshot /workspace/page.png", inspect_images=["/workspace/page.png"])` |
| Response attachment | `attach_file(path="/workspace/report.pdf")` |

Sandbox execution does not require approval.
The runtime stages selected uploads and downloaded Gmail attachments automatically.
The model uses the returned workspace paths without transfer calls.
`attach_file` keeps an immutable file version for transport delivery and checkpoint recovery.
Inspection supplies pixels to the model. It does not send an attachment to the user.
The former file-management and execution tools are absent from new tool registries.
History read and search tools remain separate.

Browser commands must be standalone calls. Use separate calls instead of shell pipes or compound browser commands.
Use `agent-browser download SELECTOR /workspace/file` for downloads.
Use `agent-browser upload SELECTOR /workspace/file` for uploads.
Profile, session, connection, and provider options belong to the runtime.

## Lifetime and recovery

Each conversation owns a remote sandbox ID.
The application saves the ID and reconnects after an application restart.
A saved ID does not guarantee that the remote sandbox still exists.
Routine startup, reconnection, expiry handling, and checkpoint restoration are automatic. The model has no workspace lifecycle control tool.

The default lifetime is one hour from creation. Reconnection and activity do not reset this deadline.
The client checks cached instances before execution and replaces confirmed missing or expired instances automatically.
Transient connection failures retain the existing reference. They do not trigger replacement or repeat a command.
Managed workspaces restore saved files before saving a replacement instance.
SQLite and R2 retain versioned `/workspace` checkpoints. Unsaved work in a dead sandbox cannot be recovered.

Large, normalized Gmail search, message, thread, and draft results, plus Health summary and export-status results, can be staged under `/tmp/theos-results` when they exceed 8 KiB. Staging stops at 1 MiB. The runtime does not checkpoint this directory, so staged results disappear when the sandbox is replaced or expires. If staging fails, the provider tool returns a bounded preview and the model can repeat the read with narrower arguments.

## Credential boundary

Theos supplies no application credentials or host mounts to the sandbox.
The server credential authenticates the client connection from the application.
It does not become an environment credential inside generated code.
Keep model, Google, Telegram, and storage secrets out of uploaded files and command arguments.

Source: [sandbox service](../src/theos/services/sandbox/).
See [acceptance](runtime/acceptance.md#live-service-checks) for the pending live lifecycle check.
