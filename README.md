# MCP MQTT Server

An MCP (Model Context Protocol) server that provides MQTT operations to LLM agent pipelines through a discoverable interface. The server supports fine-grained topic permissions with wildcard matching and provides comprehensive MQTT functionality for MCP clients.

The MCP MQTT server allows operation in `stdio` mode as well as HTTP streamable remote operation via Unix domain sockets (recommended) or TCP/IP.

## Installation

```
pip install mcpMQTT
```

To run the remote HTTP/UDS server, install the optional FastAPI/uvicorn extras:

```
pip install "mcpMQTT[remote]"
```

## Configuration

### Configuration File Structure

Create a configuration file at `~/.config/mcpmqtt/config.json` or specify a custom path when launching the utility on the command line using the ```--config``` parameter:

```json
{
  "mqtt": {
    "host": "localhost",
    "port": 1883,
    "username": null,
    "password": null,
    "keepalive": 60
  },
  "topics": [
    {
      "pattern": "sensors/+/temperature",
      "permissions": ["read"],
      "description": "Temperature sensor data from any location (+ matches single level like 'room1', 'room2'. Known rooms are 'exampleroom1' and 'exampleroom2'). Use subscribe, not read on this topic. Never publish."
    },
    {
      "pattern": "sensors/+/humidity",
      "permissions": ["read"],
      "description": "Humidity sensor data from any location. (+ matches single level like 'room1', 'room2'. Known rooms are 'exampleroom1' and 'exampleroom2'). Use subscribe, not read on this topic. Never publish. Data returned as %RH"
    },
    {
      "pattern": "actuators/#",
      "permissions": ["write"],
      "description": "All actuator control topics (# matches multiple levels like 'lights/room1'. To enable a light you write any payload to 'lights/room1/on', to disable you write to 'lights/room1/off')"
    },
    {
      "pattern": "status/system",
      "permissions": ["read"],
      "description": "System status information - exact topic match"
    },
    {
      "pattern": "commands/+/request",
      "permissions": ["write"],
      "description": "Command request topics for request/response patterns"
    },
    {
      "pattern": "commands/+/response",
      "permissions": ["read"],
      "description": "Command response topics for request/response patterns"
    }
  ],
  "logging": {
    "level": "INFO",
    "logfile": null
  },
  "remote_server": {
    "api_key": "replace-me",
    "uds": "/var/run/mcpmqtt.sock",
    "host": "0.0.0.0",
    "port": null
  }
}
```

Note that the API key is entered in plain text in this implementation, this will be fixed soon.

### Configuration Sections

- **`mqtt`**: MQTT broker connection settings
- **`topics`**: Topic patterns with permissions and descriptions
- **`logging`**: Application logging level
- **`remote_server`** *(optional when using stdio transport)*: Remote FastAPI settings, including the shared `api_key` plus bind configuration. Leaving `port` as `null` keeps the Unix domain socket default (`/var/run/mcpmqtt.sock`). Setting a TCP `port` automatically switches to TCP mode and `host` defaults to `0.0.0.0` if omitted.

### Remote Server Settings

- **Authentication**: The API key must accompany every MCP call via `Authorization: Bearer <key>`, `X-API-Key: <key>`, or `?api_key=<key>`. The `/status` endpoint intentionally skips authentication so external health probes can call it.
- **Binding**: Unix domain sockets are used by default (`/var/run/mcpmqtt.sock`). Provide a TCP `port` (and optionally `host`) to listen on TCP instead; the host defaults to all interfaces.
- **Mount path**: The FastMCP Starlette application is mounted at `/mcp`
- **Status endpoint**: `GET /status` returns `{ "running": true, "mqtt_connected": <bool> }`, exposing reachability and MQTT connectivity.
- **Dependencies**: Install FastAPI/uvicorn extras when using remote mode: `pip install "mcpMQTT[remote]"`.

### Topic Patterns and Permissions

**Wildcard Support:**
- `+`: Single-level wildcard (matches one topic level)
- `#`: Multi-level wildcard (matches multiple levels, must be last)

**Permissions:**
- `read`: Can subscribe to topics and receive messages
- `write`: Can publish messages to topics
- Both permissions can be combined: `["read", "write"]`

**Examples:**
- `sensors/+/temperature` matches `sensors/room1/temperature`, `sensors/kitchen/temperature`
- `actuators/#` matches `actuators/lights`, `actuators/lights/room1/brightness`
- `status/system` matches exactly `status/system`

## Usage

### Running the MCP Server

**Using the installed script:**

```bash
mcpMQTT
```

**Remote HTTP/UDS mode:**

```bash
mcpMQTT --transport remotehttp
```

**With custom configuration:**

```bash
mcpMQTT --config /path/to/config.json --log-level DEBUG
```

### MCP Tools

The MCP server provides three tools for MQTT operations:

#### `mqtt_publish`

Publish messages to MQTT topics.

```json
{
  "topic": "sensors/room1/temperature",
  "payload": "22.5",
  "qos": 0
}
```

#### `mqtt_subscribe`

Subscribe to topics and collect messages.

```json
{
  "topic": "sensors/+/temperature",
  "timeout": 30,
  "max_messages": 5
}
```

#### `mqtt_read`

Subscribe to a topic and wait for a single message.

```json
{
  "topic" : "sensors/+/temperature",
  "timeout" : 5
}
```

#### `mqtt_query`

Request/response pattern for MQTT communication.

```json
{
  "request_topic": "commands/room1/request",
  "response_topic": "commands/room1/response",
  "payload": "get_status",
  "timeout": 5
}
```

### MCP Resources

#### `mcpmqtt://topics/allowed`

Get allowed topic patterns with permissions and descriptions.

#### `mcpmqtt://topics/examples`

Get examples of how to use topic patterns with wildcards.

## Configuration Examples

For detailed configuration examples, see the [`examples/`](examples/) folder:

- [`example_config.json`](examples/example_config.json) - Basic configuration with multiple topic patterns
- [`example_with_logging.json`](examples/example_with_logging.json) - Configuration with file logging enabled

## Examples

### MCP Client Integration

This MCP server uses the ```stdio``` protocol. This means that it should be launched by your LLM orchestrator.

A typical configuration (```mcp.json```) may look like the following:

```
{
  "mcpServers": {
    "mqtt": {
      "command": "mcpMQTT",
      "args": [
        "--config /usr/local/etc/mcpMQTT.conf"
      ],
      "env": {
        "PYTHONPATH": "/just/an/example/path/"
      },
      "timeout": 300,
      "alwaysAllow": [
        "mqtt_read"
      ]
    }
  }
}
```

## Security Considerations

Keep in mind that this MCP allows an agent to subscribe to and publish to all topics that are exposed to the user associated with him on the MQTT broker. You have to perform fine grained configuration on your MQTT broker to limit which features the MCP can actually access or manipulate.

## License

See LICENSE.md
