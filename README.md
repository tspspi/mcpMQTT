# MCP MQTT Server

An MCP (Model Context Protocol) server that provides MQTT operations to LLM agent pipelines through a discoverable interface. The server supports fine-grained topic permissions with wildcard matching and provides comprehensive MQTT functionality for MCP clients.

## Features

- **MCP Server Interface**: MCP server implementation for MQTT operations
- **Topic Permissions**: Fine-grained read/write permissions with MQTT wildcard support (`+` and `#`)
- **Authentication**: MQTT broker authentication support
- **Discoverable**: MCP resources for topic discovery and examples
- **Configurable**: JSON-based configuration with schema validation
- **Async Support**: Full async/await support for non-blocking operations

## Architecture

```
┌─────────────────┐    ┌──────────────────────────────────┐
│   MCP Client    │    │         mcpMQTT Application      │
│                 │    │                                  │
│  ┌───────────┐  │    │  ┌─────────────┐                 │
│  │   Agent   │  │◄──►│  │ MCP Server  │                 │
│  └───────────┘  │    │  └─────────────┘                 │
└─────────────────┘    │         │                        │
                       │  ┌─────────────────────────────┐ │
┌─────────────────┐    │  │   Topic Permission Manager  │ │
│  MQTT Broker    │◄──►│  └─────────────────────────────┘ │
└─────────────────┘    │         │                        │
                       │  ┌─────────────┐                 │
                       │  │ MQTT Client │                 │
                       │  │  Manager    │                 │
                       │  └─────────────┘                 │
                       └──────────────────────────────────┘
```

## Installation

```
pip install mcpMQTT
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
  }
}
```

### Configuration Sections

- **`mqtt`**: MQTT broker connection settings
- **`topics`**: Topic patterns with permissions and descriptions
- **`logging`**: Application logging level

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

**Or using the module directly:**

```bash
python -m mcpMQTT.app.mcp_server
```

**With custom configuration:**

```bash
mcpMQTT --config /path/to/config.json --log-level DEBUG
# or
python -m mcpMQTT.app.mcp_server --config /path/to/config.json --log-level DEBUG
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

## Development

### Project Structure

```
mcpMQTT/
├── app/
│   ├── __init__.py
│   ├── mcp_server.py        # MCP server implementation and entry point
│   └── mqtt_client.py       # Enhanced MQTT client manager
├── config/
│   ├── config_manager.py    # Configuration loading and validation
│   ├── schema.py           # Pydantic models and validation
│   ├── example_config.json # Example configuration file
│   └── example_with_logging.json # Example with logging configuration
├── examples/
│   ├── example_config.json        # Basic configuration example
│   └── example_with_logging.json  # Configuration with file logging
├── pyproject.toml
├── LOGGING_USAGE.md        # Detailed logging documentation
└── README.md
```

### Configuration Examples

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
