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
AGENT_SANDBOX__TIMEOUT_SECONDS=600
```

The timeout ranges from 60 to 3600 seconds.
The client requests one CPU and 512 MiB for each new sandbox.
The server, image registry, and remote network remain operator responsibilities.
Container loopback does not reach a sandbox server on another host.

## Mac mini over Tailscale

Theos can run on one Mac while OpenSandbox and Docker run on the Mac mini.
Use server proxy mode so only the OpenSandbox server port needs access from Theos.

1. Run `tailscale ip -4` on the Mac mini.
2. Edit the existing sections in `/Volumes/extssd/opensandbox/config.toml` on the Mac mini.
3. Replace `100.x.y.z` with the Mac mini's Tailscale address.
4. Set a generated API key in the server configuration.

```toml
[server]
host = "100.x.y.z"
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

5. Start the server on the Mac mini.

```sh
uvx opensandbox-server --config /Volumes/extssd/opensandbox/config.toml
```

6. Configure Theos on its own host with the same key.

```dotenv
AGENT_SANDBOX__ENABLED=true
AGENT_SANDBOX__DOMAIN=100.x.y.z:8085
AGENT_SANDBOX__API_KEY=replace-with-generated-key
AGENT_SANDBOX__USE_SERVER_PROXY=true
AGENT_SANDBOX__IMAGE=opensandbox/code-interpreter:v1.1.0
AGENT_SANDBOX__TIMEOUT_SECONDS=600
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

Shell, Python, and browser execution require approval.
Uploaded files remain bound to the authenticated owner.
Generated files enter the local private catalog before delivery.
The model can receive a checked sandbox image through `sandbox_view_image`.

## Lifetime and recovery

Each conversation owns a remote sandbox ID.
The application saves the ID and reconnects after an application restart.
A saved ID does not guarantee that the remote sandbox still exists.
Use `sandbox_lifecycle` with `status`, `renew`, `destroy`, or `forget`.
`forget` removes the saved connection reference without destroying a remote instance.

A missing sandbox requires an explicit lifecycle reset before replacement.
Download important generated files before destroying the remote environment.
The application backup does not snapshot the remote sandbox filesystem.

## Credential boundary

Theos supplies no application credentials or host mounts to the sandbox.
The server credential authenticates the client connection from the application.
It does not become an environment credential inside generated code.
Keep model, Google, Telegram, and storage secrets out of uploaded files and command arguments.

Source: [sandbox service](../src/theos/services/sandbox/).
See [acceptance](runtime/acceptance.md#live-service-checks) for the pending live lifecycle check.
