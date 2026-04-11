"""Pre-configured templates for popular MCP servers.

These templates guide users through setup by providing sensible defaults,
required environment variables, and setup hints.
"""

from app.mcp.models import MCPServerTemplate, MCPTransport

TEMPLATES: list[MCPServerTemplate] = [
    MCPServerTemplate(
        template_id="filesystem",
        name="Filesystem",
        description="Read, write, and manage files on your local filesystem",
        icon="📁",
        category="utilities",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp/mcp-workspace"],
        env_keys=[],
        setup_hint="Grants read/write access to the specified directory. Adjust the path in args to your workspace.",
    ),
    MCPServerTemplate(
        template_id="github",
        name="GitHub",
        description="Interact with GitHub repositories, issues, pull requests, and more",
        icon="🐙",
        category="developer",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env_keys=["GITHUB_PERSONAL_ACCESS_TOKEN"],
        env_descriptions={
            "GITHUB_PERSONAL_ACCESS_TOKEN": "GitHub personal access token with repo scope",
        },
        env_placeholders={
            "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxxxxxxxxxxx",
        },
        setup_hint="Create a token at github.com/settings/tokens with 'repo' scope.",
    ),
    MCPServerTemplate(
        template_id="slack",
        name="Slack",
        description="Send messages, manage channels, and interact with Slack workspaces",
        icon="💬",
        category="communication",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-slack"],
        env_keys=["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"],
        env_descriptions={
            "SLACK_BOT_TOKEN": "Slack Bot User OAuth Token (xoxb-...)",
            "SLACK_TEAM_ID": "Your Slack workspace Team ID",
        },
        env_placeholders={
            "SLACK_BOT_TOKEN": "xoxb-xxxxxxxxxxxx",
            "SLACK_TEAM_ID": "T0XXXXXXX",
        },
        setup_hint="Create a Slack app at api.slack.com/apps with necessary bot scopes.",
    ),
    MCPServerTemplate(
        template_id="brave-search",
        name="Brave Search",
        description="Web search using the Brave Search API",
        icon="🔍",
        category="research",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-brave-search"],
        env_keys=["BRAVE_API_KEY"],
        env_descriptions={
            "BRAVE_API_KEY": "Brave Search API key",
        },
        env_placeholders={
            "BRAVE_API_KEY": "BSA-xxxxxxxxxxxx",
        },
        setup_hint="Get an API key at brave.com/search/api/.",
    ),
    MCPServerTemplate(
        template_id="postgres",
        name="PostgreSQL",
        description="Query and manage PostgreSQL databases",
        icon="🐘",
        category="database",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-postgres"],
        env_keys=["POSTGRES_CONNECTION_STRING"],
        env_descriptions={
            "POSTGRES_CONNECTION_STRING": "PostgreSQL connection URI",
        },
        env_placeholders={
            "POSTGRES_CONNECTION_STRING": "postgresql://user:pass@localhost:5432/dbname",
        },
        setup_hint="Provide a full PostgreSQL connection URI.",
    ),
    MCPServerTemplate(
        template_id="puppeteer",
        name="Puppeteer",
        description="Browser automation — navigate pages, take screenshots, interact with web UIs",
        icon="🎭",
        category="automation",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-puppeteer"],
        env_keys=[],
        setup_hint="Requires Chrome/Chromium installed on the system.",
    ),
    MCPServerTemplate(
        template_id="memory",
        name="Memory",
        description="Persistent memory storage using a knowledge graph",
        icon="🧠",
        category="utilities",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-memory"],
        env_keys=[],
        setup_hint="Stores a knowledge graph in memory. Data persists across tool calls within a session.",
    ),
    MCPServerTemplate(
        template_id="brightdata",
        name="Bright Data",
        description="Web scraping, SERP, and data collection via Bright Data MCP",
        icon="🌐",
        category="research",
        command="",
        args=[],
        transport=MCPTransport.SSE,
        url_template="https://mcp.brightdata.com/mcp",
        env_keys=[],
        setup_hint="Provide the full MCP URL including your token (e.g. https://mcp.brightdata.com/mcp?token=YOUR_TOKEN).",
    ),
    MCPServerTemplate(
        template_id="custom-sse",
        name="Custom SSE Server",
        description="Connect to any MCP server using Server-Sent Events transport",
        icon="🌐",
        category="custom",
        command="",
        args=[],
        transport=MCPTransport.SSE,
        url_template="http://localhost:3000/sse",
        env_keys=[],
        setup_hint="Enter the SSE endpoint URL of your running MCP server.",
    ),
]


def get_template(template_id: str) -> MCPServerTemplate | None:
    """Look up a template by ID."""
    for t in TEMPLATES:
        if t.template_id == template_id:
            return t
    return None


def get_templates_by_category() -> dict[str, list[MCPServerTemplate]]:
    """Return templates grouped by category."""
    cats: dict[str, list[MCPServerTemplate]] = {}
    for t in TEMPLATES:
        cats.setdefault(t.category, []).append(t)
    return cats
