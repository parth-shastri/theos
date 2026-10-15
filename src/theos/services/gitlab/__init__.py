"""Connect private GitLab accounts to the official remote MCP server."""

from theos.services.mcp_accounts.account import AccountSpec, MCPAccount

READ_TOOLS = frozenset(
    [
        "get_mcp_server_version",
        "get_project",
        "list_projects",
        "list_groups",
        "get_repository_file",
        "list_repository_tree",
        "get_commit",
        "list_commits",
        "list_branches",
        "list_releases",
        "list_tags",
        "get_merge_request",
        "list_merge_requests",
        "get_work_item",
        "list_work_items",
        "get_work_item_types",
        "get_pipeline",
        "list_pipelines",
        "get_pipeline_jobs",
        "get_job",
        "get_job_log",
        "get_artifact_file",
        "search",
        "search_labels",
        "get_issue",
        "get_merge_request_commits",
        "get_merge_request_diffs",
        "get_merge_request_pipelines",
        "get_merge_request_notes",
        "get_workitem_notes",
        "list_project_members",
        "get_user",
    ]
)


def create_account(settings, db, http):
    config = settings.gitlab
    origin = config.instance_url
    endpoint = origin + "/api/v4/mcp"
    authorization_url = origin + "/oauth/authorize"
    token_url = origin + "/oauth/token"
    account = AccountSpec(
        name="gitlab",
        label="GitLab",
        endpoint=endpoint,
        authorization_url=authorization_url,
        token_url=token_url,
        read_tools=READ_TOOLS,
        scopes=("mcp",),
        headers={
            "X-Gitlab-Enabled-Mcp-Server-Toolsets": "meta,core,merge_requests,work_items,repository,ci"
        },
        methods={},
        scope_separator=" ",
        token_basic_auth=False,
    )
    return MCPAccount(settings, config, account, db, http)
