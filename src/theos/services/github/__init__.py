"""Connect private GitHub accounts to the official remote MCP server."""

from theos.services.mcp_accounts.account import AccountSpec, MCPAccount

READ_TOOLS = frozenset(
    [
        "get_me",
        "search_repositories",
        "list_branches",
        "get_file_contents",
        "get_repository_tree",
        "get_commit",
        "list_commits",
        "list_tags",
        "list_releases",
        "get_latest_release",
        "get_release_by_tag",
        "get_tag",
        "issue_read",
        "list_issues",
        "search_issues",
        "pull_request_read",
        "list_pull_requests",
        "search_pull_requests",
        "actions_list",
        "actions_get",
        "get_job_logs",
        "search_code",
        "search_commits",
    ]
)


def create_account(settings, db, http):
    config = settings.github
    endpoint = "https://api.githubcopilot.com/mcp/"
    authorization_url = "https://github.com/login/oauth/authorize"
    token_url = "https://github.com/login/oauth/access_token"
    account = AccountSpec(
        name="github",
        label="GitHub",
        endpoint=endpoint,
        authorization_url=authorization_url,
        token_url=token_url,
        read_tools=READ_TOOLS,
        scopes=(),
        headers={
            "X-MCP-Readonly": "true",
            "X-MCP-Toolsets": "context,repos,git,issues,pull_requests,actions",
        },
        methods={
            "issue_read": frozenset(
                ["get", "get_comments", "get_sub_issues", "get_parent", "get_labels"]
            ),
            "pull_request_read": frozenset(
                [
                    "get",
                    "get_diff",
                    "get_status",
                    "get_files",
                    "get_commits",
                    "get_review_comments",
                    "get_reviews",
                    "get_comments",
                    "get_check_runs",
                ]
            ),
            "actions_list": frozenset(
                [
                    "list_workflows",
                    "list_workflow_runs",
                    "list_workflow_jobs",
                    "list_workflow_run_artifacts",
                ]
            ),
            "actions_get": frozenset(
                [
                    "get_workflow",
                    "get_workflow_run",
                    "get_workflow_run_usage",
                    "get_workflow_run_logs_url",
                    "get_workflow_job",
                ]
            ),
        },
        scope_separator=" ",
        token_basic_auth=False,
    )
    return MCPAccount(settings, config, account, db, http)
