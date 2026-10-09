# Zepto MCP

Theos connects to a remote Zepto MCP server.
Each browser or private Telegram user connects their own Zepto account with OAuth.
The user does not paste a lasting token into Telegram.

## Configure the endpoint

Set the trusted MCP endpoint and the shared account encryption key in `.env`:

```dotenv
AGENT_ZEPTO_URL=https://mcp.zepto.co.in/mcp
AGENT_ZEPTO_REDIRECT_URI=http://localhost/callback
AGENT_TOKEN_ENCRYPTION_KEY=replace-with-a-generated-fernet-key
```

The endpoint must support Streamable HTTP, OAuth discovery, and dynamic client registration.
Theos discovers the authorization endpoints and registers a public client automatically.
The MCP client uses PKCE for each authorization.
Use the endpoint that your Zepto MCP provider documents.
The [Zepto MCP guide](https://github.com/zeptonow/mcp) lists its current endpoint and sign-in flow.

Generate a Fernet key on a trusted computer:

```sh
uv run --extra server python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Keep the key in the deployment's private `.env` file.
Use the same key after every restart.
Theos cannot read saved tokens after the key changes.

The default callback uses `http://localhost/callback`.
It works when the server runs on a VPS or Raspberry Pi without public inbound access.
In this flow, `localhost` points to the user's phone or computer browser.

For a public HTTPS callback, set the full Theos callback URI:

```dotenv
AGENT_ZEPTO_REDIRECT_URI=https://assistant.example.com/oauth/zepto/callback
```

The Zepto provider must allow this exact callback URI.
The HTTPS endpoint must route `/oauth/zepto/callback` to Theos.
Use a public HTTPS tunnel or reverse proxy when a Raspberry Pi needs this mode.

Recreate the application after changing `.env`:

```sh
docker compose config --quiet
docker compose up -d --force-recreate
```

## Connect an account in the browser

1. Select **Connections > Zepto > Connect**.
2. Select **Continue sign-in**.
3. Complete the provider's sign-in procedure.
4. If the provider returns to localhost, copy the full address-bar URL.
5. Paste that URL into the connection form.
6. Select **Finish connection**.
7. Check that the view shows **Connected**.

The localhost browser can show a connection error after sign-in.
Theos receives the short-lived return through its authenticated endpoint.
The return URL does not enter model history.
An approved public HTTPS callback completes the handoff directly.
Use **Cancel setup** or **Disconnect** to remove pending setup and local credentials.
Use provider account settings to revoke remote access when needed.
Unfinished setup expires after ten minutes and does not survive a server restart.

## Connect an account in Telegram

Complete `/start` and timezone setup before connecting an account.
Use an allowed private chat with the bot.

1. Send `/connect_zepto`.
2. Open the **Sign in to Zepto** link.
3. Sign in with your Zepto phone number and one-time password.
4. If the browser returns to `localhost`, copy the full address-bar URL.
5. Send `/zepto_finish <url>` in the same private Telegram chat.
6. Wait for Theos to confirm the connection.

The browser may show a connection error after sign-in.
This is expected when the user device has no service on `localhost`.
The return URL contains a short-lived authorization code.
Theos exchanges that code from the server with the saved PKCE verifier.

When you use a public HTTPS callback, Zepto returns to Theos directly.
Return to Telegram and wait for the connection message.

Theos binds each authorization to the Telegram owner and a one-use state value.
It encrypts the access token, refresh token, and OAuth client data in SQLite.
It encrypts the pasted return URL before it saves the Telegram inbox update.
It removes the encrypted return URL after processing and attempts to delete the Telegram message.
The return URL does not enter model history.

An unfinished sign-in expires after ten minutes.
Start again with `/connect_zepto` if the application restarts before you finish.
Saved credentials remain available after an application restart.

Send `/disconnect_zepto` to remove local Zepto credentials from Theos.
Use Zepto's account settings to revoke remote authorization when needed.

## Use Zepto tools

The runtime discovers remote tools for connected users in browser and private Telegram conversations.
It excludes the `zepto_shop` wrapper.
It adds the `zepto_` prefix and validates arguments against each remote schema.

Every Zepto call requires approval, including reads and cart changes.
The approval binds to the saved tool and arguments.
It expires after 15 minutes.

Product search requires a selected delivery store.
Order history can work before a store is selected.
Ask Theos to list saved addresses and select the address you want for delivery.
The `zepto_list_saved_addresses` and `zepto_select_saved_address` tools support this procedure.
For a new delivery location, use `zepto_get_location_serviceability` with its latitude and longitude.
Review each setup approval, then request the product search.
Theos explains this prerequisite when Zepto reports `Store not selected`.
It does not select an address or retry a remote action automatically.
Theos retains one MCP session per account and sends its calls in order.
The selected store applies across that owner's private conversations.
Account reconnection, disconnection, application restart, or a failed connection ends this session.
Select the delivery address again when the session loses its store context.

1. Ask for a specific read or action in the private chat.
2. Review the complete approval preview.
3. Select **Approve** or **Deny**.
4. Check the returned result before requesting another action.

Zepto orders are real purchases.
Review the exact items and price before you approve an order or payment.
The application tests do not place live orders.

Shopping prompts, tool arguments, and results can enter model requests and local conversation history.
Zepto tokens stay out of model requests, tool arguments, and conversation history.

If MCP discovery fails, normal chat can continue without Zepto tools.
Check the endpoint, encryption key, private account access, and connection status.
The MCP client refreshes saved access tokens when the provider supports refresh tokens.

Source: [Zepto tools](../src/theos/services/zepto/tools.py), [Zepto OAuth](../src/theos/services/zepto/auth.py), [MCP sessions](../src/theos/services/zepto/session.py), and [approval policy](../src/theos/runtime/approvals.py).
See the [acceptance checklist](runtime/acceptance.md#live-service-checks) for live checks.
