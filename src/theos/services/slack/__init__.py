"""Connect private Slack accounts to the official remote MCP server."""

from theos.services.mcp_accounts.account import AccountSpec, MCPAccount

READ_TOOLS = frozenset(
    [
        "slack_list_workspaces",
        "slack_list_user_channels",
        "slack_list_user_conversations",
        "slack_search_public",
        "slack_search_public_and_private",
        "slack_search_channels",
        "slack_search_users",
        "slack_read_channel",
        "slack_read_thread",
        "slack_read_user_profile",
        "slack_list_channel_members",
        "slack_read_file",
        "slack_read_canvas",
        "slack_read_list",
        "slack_get_reactions",
        "slack_search_emojis",
        "slack_list_user_groups",
        "slack_list_starred_items",
    ]
)


def create_account(settings, db, http):
    config = settings.slack
    endpoint = "https://mcp.slack.com/mcp"
    authorization_url = "https://slack.com/oauth/v2_user/authorize"
    token_url = "https://slack.com/api/oauth.v2.user.access"
    account = AccountSpec(
        name="slack",
        label="Slack",
        endpoint=endpoint,
        authorization_url=authorization_url,
        token_url=token_url,
        read_tools=READ_TOOLS,
        scopes=(
            "search:read.public",
            "search:read.users",
            "channels:read",
            "channels:history",
            "users:read",
        ),
        headers={},
        methods={},
        scope_separator=",",
        token_basic_auth=True,
        pkce=False,
    )
    return MCPAccount(settings, config, account, db, http)
