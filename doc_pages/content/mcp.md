# MCP Integration


Connect to external tool servers using the Model Context Protocol (MCP).
  LARS supports both stdio and HTTP transports with automatic tool discovery.
On This Page
- [Overview](#overview)
- [Configuration](#configuration)
- [Stdio Servers](#stdio)
- [HTTP Servers](#http)
- [CLI Commands](#cli)


## Overview


MCP (Model Context Protocol) allows LARS to connect to external tool servers.
  Tools from MCP servers are automatically discovered and registered in the skill registry.


#### Stdio Transport


Run tools as local processes, communicate via stdin/stdout


#### HTTP Transport


Connect to remote servers via HTTP/HTTPS

## Configuration


MCP servers are configured via `config/mcp_servers.yaml`:

```config/mcp_servers.yaml
# Filesystem server (stdio)
- name: filesystem
  transport: stdio
  command: npx
  args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
  enabled: true

# Brave Search (stdio with env)
- name: brave-search
  transport: stdio
  command: npx
  args: ["-y", "@modelcontextprotocol/server-brave-search"]
  env:
    BRAVE_API_KEY: ${BRAVE_API_KEY}
  enabled: true

# HTTP server example
- name: github
  transport: http
  url: http://localhost:3000/mcp
  headers:
    Authorization: Bearer ${GITHUB_TOKEN}
  enabled: false
```

## Stdio Servers


Stdio servers run as child processes. LARS manages their lifecycle:

```stdio configuration
- name: my-server
  transport: stdio
  command: /path/to/server
  args: ["--config", "config.json"]
  env:
    API_KEY: ${MY_API_KEY}
  cwd: /working/directory  # Optional working dir
  enabled: true
  timeout: 30  # Startup timeout in seconds
```

## HTTP Servers


Connect to remote MCP servers over HTTP:

```http configuration
- name: remote-tools
  transport: http
  url: https://tools.example.com/mcp
  headers:
    Authorization: Bearer ${API_TOKEN}
    X-Custom-Header: value
  enabled: true
  retry:
    max_attempts: 3
    backoff: exponential
```

## CLI Commands


```mcp management
# List configured servers
lars mcp list

# Check server status
lars mcp status

# List tools from a specific server
lars mcp introspect filesystem

# Show all MCP tools in manifest
lars mcp manifest

# Re-discover tools from all servers
lars mcp refresh

# Test a specific tool
lars mcp test filesystem read_file --args '{"path": "/tmp/test.txt"}'
```

### Environment Variables


```environment
# Enable/disable MCP integration
LARS_MCP_ENABLED=true

# Alternative: inline YAML config
LARS_MCP_SERVERS_YAML='
- name: my-server
  transport: stdio
  command: my-tool
  enabled: true
'
```

### Using MCP Tools in Cascades


MCP tools are automatically prefixed with the server name:

```using mcp tools
- name: file_operations
  instructions: "Read the config file and update settings"
  skills:
    - filesystem:read_file    # server_name:tool_name
    - filesystem:write_file
    - filesystem:list_directory
```


> **TIP: Tool Discovery**
>
> 
> Use `lars mcp introspect <server>` to see all available tools
>     from a server, including their parameters and descriptions.
> 


## Further Reading
- [MCP Specification](https://modelcontextprotocol.io)
- [Official MCP Servers](https://github.com/modelcontextprotocol/servers)
- [Tools (Skills)](#tools) - Overview of LARS's tool system
