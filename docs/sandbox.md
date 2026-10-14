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
AGENT_SANDBOX__IMAGE=opensandbox/code-interpreter:v1.0.1
AGENT_SANDBOX__TIMEOUT_SECONDS=3600
```

The image must provide `/opt/code-interpreter/code-interpreter.sh`.
Theos supplies this entrypoint because the SDK default does not start the interpreter.
The timeout ranges from 60 to 3600 seconds.
The client requests one CPU and 512 MiB for each new sandbox.
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
AGENT_SANDBOX__IMAGE=opensandbox/code-interpreter:v1.1.0
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

## Browser dependencies

`sandbox_browser` invokes `agent-browser` inside the remote sandbox.
Use an image that includes that command and its browser dependencies.
The default code-interpreter image does not guarantee those dependencies.
Installing browser software in the assistant container does not install it in the remote sandbox.

## Tools and approval

| Area | Tools |
| --- | --- |
| Execution | `sandbox_run_command`, `sandbox_execute_code` |
| Text files | `sandbox_write_file`, `sandbox_read_file`, `sandbox_list_files` |
| File transfer | `sandbox_upload_file`, `sandbox_send_file_to_user` |
| Images | `sandbox_view_image` |
| Browser | `sandbox_browser` |
| Lifetime | `sandbox_lifecycle` |

Sandbox execution does not require approval.
Uploaded files remain bound to the authenticated owner.
Generated files enter the local private catalog before delivery.
The model can receive a checked sandbox image through `sandbox_view_image`.

## Lifetime and recovery

Each conversation owns a remote sandbox ID.
The application saves the ID and reconnects after an application restart.
A saved ID does not guarantee that the remote sandbox still exists.
Use `sandbox_lifecycle` with `status`, `restart`, `destroy`, or `forget`.
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
