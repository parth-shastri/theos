# Gmail

The Gmail connector uses a separate OAuth grant for each browser or allowed private Telegram user.
OAuth means Open Authorization.
The connector supports search, message reads, threads, attachments, drafts, and labels.
Sending a draft requires approval of its current contents.

## Configure the service

These steps belong to the deployment operator.
A self-hosted owner uses their own Google project.
A hosted service operator configures one project for the service.
Each user then authorizes their own mailbox.
See [deployment options](DEPLOYMENT.md#choose-a-deployment-option).

1. Enable Gmail API access for your Google project.
2. Add `https://www.googleapis.com/auth/gmail.modify` under **Google Auth Platform > Data Access > Add or remove scopes**.
3. Save the scopes without removing permissions that your other applications require.
4. Open **Google Auth Platform > Clients**.
5. Create or select a **Web application** client.
6. Register the exact application callback URI under **Authorized redirect URIs**.
7. Copy the client ID and secret into the Gmail fields in `.env`.
8. Generate a Fernet encryption key on a trusted computer.

   ```sh
   uv run --extra server python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
   ```

9. Save the key as `AGENT_TOKEN_ENCRYPTION_KEY`.
10. Recreate the application container.

```dotenv
AGENT_GMAIL__CLIENT_ID=replace-me
AGENT_GMAIL__CLIENT_SECRET=replace-me
AGENT_GMAIL__REDIRECT_URI=https://assistant.example.com/oauth/gmail/callback
AGENT_TOKEN_ENCRYPTION_KEY=replace-with-generated-fernet-key
```

The callback must reach the application.
HTTPS is required except for HTTP callbacks on `localhost` or `127.0.0.1`.
The application does not derive the Gmail URI from Health settings.
All three Gmail fields must exist together.

For authorization on a phone, use a reachable HTTPS callback on the Theos server.
`localhost` on the phone points to the phone, not your server.
The Android and iOS clients belong to the mobile application.
The server uses the Web client.
Gmail and Health can use the same Web client ID and secret, with separate callback URLs.
Theos stores a separate account connection for each service and user.

Google shows a new client secret only when it creates the secret.
Use your saved credential JSON, or add a secret under the client's **Client Secrets** section.
Keep existing secrets active while other applications still use them.
See [Google's Web client setup](https://developers.google.com/identity/protocols/oauth2/web-server)
and [secret creation instructions](https://developers.google.com/health/codelabs/make-your-first-api-call-using-oauth2-playground).

If Health already uses an encryption key, keep that same key.
Replacing it makes existing account tokens unreadable.

## Connect an account

These steps belong to each user, after the operator configures the service.
Users need no application credentials.

Browser users select **Connections > Gmail > Connect**, then **Continue sign-in**.
Return to the browser workspace after consent.
Ask for a message search to check access.

For Telegram, complete `/start` and timezone setup in the bot's private chat first.

1. Send `/connect_gmail` in an allowed private Telegram chat.
2. Open the returned Google authorization link.
3. Grant the requested `gmail.modify` scope.
4. Return to Telegram after the callback succeeds.
5. Ask for a message search to check access.

Authorization state expires after ten minutes and works once.
The callback checks the service and a Proof Key for Code Exchange (PKCE) verifier.
The application requires a refresh token and the requested scope.
It encrypts access and refresh tokens in SQLite.
Browser and private Telegram conversations receive configured Gmail tools.
Groups and terminal sessions receive no Gmail tools.

If the operator adds permissions, connect again to grant the additional access.
Saving scopes in Google Console does not change an existing account grant.

## Use drafts

1. Ask the assistant to create a draft.
2. Read its recipients, subject, body, and attachment list.
3. Ask the assistant to send that draft.
4. Read the approval preview.
5. Select **Approve** only if the contents are correct.

The approval includes a hash of the complete raw draft.
The application reads the draft again during approval and immediately before sending.
A changed draft requires a new review.
Keep the draft unchanged until the send operation ends.
Gmail cannot lock the draft against another client during the final request.

If delivery has an unknown outcome, check Gmail before sending again.
The application does not automatically repeat an uncertain send.

## Supported operations

| Area | Tools |
| --- | --- |
| Account | `gmail_connect`, `gmail_disconnect` |
| Messages | `gmail_search_messages`, `gmail_get_message`, `gmail_get_thread` |
| Attachments | `gmail_download_attachment` |
| Drafts | `gmail_list_drafts`, `gmail_get_draft`, `gmail_create_draft`, `gmail_send_draft` |
| Labels | `gmail_list_labels`, `gmail_create_label`, `gmail_modify_labels` |

Spam and Trash access remain restricted.
Downloaded attachments enter the private file catalog.
They do not require a sandbox.
The connector does not automatically execute an attachment.
Message content can enter model requests and persistent conversation history.

## Disconnect

Send `/disconnect_gmail` from the private chat.
The application deletes local credentials and pending authorization state.
It also attempts to revoke the remote grant.
Local disconnection succeeds even if Google revocation fails.
Existing conversation history and downloaded files remain local records.

Source: [Gmail service](../src/theos/services/gmail/) and [OAuth service](../src/theos/services/google/oauth.py).
Live account checks remain in the [acceptance checklist](runtime/acceptance.md#live-service-checks).
