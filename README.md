# RaaS Core

**Requirements as a Service** - Core library and solo developer deployment.

## Quick Start (Solo Developers)

Get up and running in 5 minutes:

```bash
git clone --recursive https://github.com/Originate-Group/originate-raas-core.git
cd originate-raas-core
docker compose up
```

Access the API at: **http://localhost:8000/docs**

### MCP Integration (Claude Desktop)

Configure MCP stdio server in Claude Desktop:

```json
{
  "mcpServers": {
    "raas": {
      "command": "docker",
      "args": ["compose", "exec", "-T", "api", "python", "-m", "tarka_mcp.server"],
      "env": {
        "API_BASE_URL": "http://api:8000/api/v1"
      }
    }
  }
}
```

Now you can use Claude to manage requirements:
- Create organizations and projects
- Define epics, components, features, and requirements
- Track dependencies and lifecycle status
- Generate requirement templates

---

## For Teams (Self-Hosted with Authentication)

Use **[originate-raas-team](https://github.com/Originate-Group/originate-raas-team)** for:
- OAuth 2.1 + Keycloak authentication
- Personal Access Tokens (PAT)
- Multi-user organizations
- Remote MCP service

---

## Overview

RaaS Core provides the foundational components for AI-native requirements management:

- **🐳 Container-First**: Docker deployment for development and production
- **Database Models**: SQLAlchemy models for Users, Organizations, Projects, and Requirements
- **CRUD Operations**: Complete data access layer for all entities
- **FastAPI Routers**: REST API endpoints (no authentication in core, auth added by team deployment)
- **Markdown Utilities**: YAML frontmatter parsing and requirement template system
- **4-Level Hierarchy**: Epic → Component → Feature → Requirement structure
- **MCP Server**: Model Context Protocol integration for AI assistants

---

## For Contributors (Library Development)

```bash
# Clone with git
git clone https://github.com/Originate-Group/originate-raas-core.git
cd originate-raas-core

# Install dependencies
pip install -e .

# Install with MCP support
pip install -e ".[mcp]"
```

### Package Structure

```
src/
├── tarka_core/
│   ├── models.py           # SQLAlchemy models
│   ├── crud.py             # CRUD operations
│   ├── schemas.py          # Pydantic schemas
│   ├── markdown_utils.py   # Markdown/YAML parsing
│   └── database.py         # Database connection
└── tarka_mcp/
    └── server.py           # MCP protocol server
```

### Usage in Deployment Repos

RaaS Core is typically used as a git submodule or PyPI dependency:

```python
from tarka_core import (
    create_requirement,
    get_requirement,
    RequirementCreate,
    RequirementResponse,
)
```

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.

## Contributing

Contributions welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
