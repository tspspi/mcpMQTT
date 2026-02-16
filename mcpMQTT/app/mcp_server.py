"""MCP Server implementation for MQTT operations using FastMCP."""

import asyncio
import json
import logging
import os
import stat
from contextlib import asynccontextmanager, AsyncExitStack
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

from mcp.server.fastmcp import Context, FastMCP

from mcpMQTT.config.schema import Config, validate_topic_permission
from mcpMQTT.app.mqtt_client import MQTTClientManager

logger = logging.getLogger(__name__)


@dataclass
class MQTTAppContext:
    """Application context with MQTT client and configuration."""
    mqtt_manager: MQTTClientManager
    config: Config


# Global references for resources and health checks
_current_config: Optional[Config] = None
_current_mqtt_manager: Optional[MQTTClientManager] = None


@asynccontextmanager
async def mqtt_lifespan(server: FastMCP) -> AsyncIterator[MQTTAppContext]:
    """Manage MQTT connection lifecycle."""
    global _current_config, _current_mqtt_manager
    
    # Get configuration (this should be passed in somehow)
    from mcpMQTT.config.config_manager import get_config
    config = get_config()
    _current_config = config  # Store globally for resource access
    
    # Initialize MQTT client
    mqtt_manager = MQTTClientManager(config.mqtt)
    
    # Connect to MQTT broker
    if not mqtt_manager.connect():
        raise ConnectionError("Failed to connect to MQTT broker")
    
    _current_mqtt_manager = mqtt_manager
    logger.info("MCP MQTT Server initialized with MQTT connection")
    
    try:
        yield MQTTAppContext(mqtt_manager=mqtt_manager, config=config)
    finally:
        # Cleanup on shutdown
        mqtt_manager.disconnect()
        _current_config = None
        _current_mqtt_manager = None
        logger.info("MCP MQTT Server shutdown complete")


# Create FastMCP server with lifespan
mcp = FastMCP("mcpmqtt", lifespan=mqtt_lifespan)


@mcp.tool(
    annotations = {
        "title" : "Publish a message to an MQTT topic.",
        "readOnlyHint" : False,
        "destructiveHint" : True,
        "idempotentHint" : False,
        "openWorldHint" : True
    }
)
def mqtt_publish(topic: str, payload: str, qos: int = 0, ctx: Context = None) -> str:
    """Publish a message to an MQTT topic."""
    if not topic or payload is None:
        return "Error: topic and payload are required"
    
    app_ctx: MQTTAppContext = ctx.request_context.lifespan_context
    
    # Check write permission
    if not validate_topic_permission(topic, "write", app_ctx.config.topics):
        return f"Error: No write permission for topic '{topic}'"
    
    # Ensure MQTT connection
    if not app_ctx.mqtt_manager.connected:
        if not app_ctx.mqtt_manager.connect():
            return "Error: Failed to connect to MQTT broker"
    
    # Publish message
    success = app_ctx.mqtt_manager.publish(topic, payload, qos)
    if success:
        return f"Successfully published message to topic '{topic}'"
    else:
        return f"Failed to publish message to topic '{topic}'"


@mcp.tool(
    annotations = {
        "title" : "Subscribe to a topic and return messages received during a given time if time expires or max_messages number of messages are reached.",
        "readOnlyHint" : True,
        "destructiveHint" : False,
        "idempotentHint" : False,
        "openWorldHint" : True
    }
)
async def mqtt_subscribe(topic: str, timeout: float = 30, max_messages: int = 1, ctx: Context = None) -> str:
    """Subscribe to an MQTT topic and return messages."""
    if not topic:
        return "Error: topic is required"
    
    app_ctx: MQTTAppContext = ctx.request_context.lifespan_context
    
    # Check read permission
    if not validate_topic_permission(topic, "read", app_ctx.config.topics):
        return f"Error: No read permission for topic '{topic}'"
    
    # Ensure MQTT connection
    if not app_ctx.mqtt_manager.connected:
        if not app_ctx.mqtt_manager.connect():
            return "Error: Failed to connect to MQTT broker"
    
    # Subscribe and collect messages
    messages = []
    try:
        # Subscribe to topic
        if not app_ctx.mqtt_manager.subscribe(topic):
            return f"Failed to subscribe to topic '{topic}'"
        
        await ctx.info(f"Subscribed to topic '{topic}', waiting for messages...")
        
        # Collect messages
        start_time = asyncio.get_event_loop().time()
        while len(messages) < max_messages and (asyncio.get_event_loop().time() - start_time) < timeout:
            remaining_timeout = timeout - (asyncio.get_event_loop().time() - start_time)
            message = await app_ctx.mqtt_manager.wait_for_message(topic, min(remaining_timeout, 1))
            if message is not None:
                messages.append({
                    "topic": topic,
                    "payload": message,
                    "timestamp": asyncio.get_event_loop().time()
                })
                await ctx.debug(f"Received message {len(messages)}/{max_messages}")
            else:
                break
        
        result = {
            "topic": topic,
            "messages_received": len(messages),
            "messages": messages
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        return f"Error subscribing to topic '{topic}': {str(e)}"


@mcp.tool(
    annotations = {
        "title" : "Subscribe to a topic and return the first message received. If not message is returned until timeout, no message is returned",
        "readOnlyHint" : True,
        "destructiveHint" : False,
        "idempotentHint" : False,
        "openWorldHint" : True
    }
)
async def mqtt_read(response_topic: str, timeout: float = 5, ctx: Context = None) -> str:
    """Subscribe to a topic and wait for a message."""

    logger.debug(f"MCP MQTT mqtt_read: Request for {response_topic} with timeout of {timeout} seconds")

    if not response_topic:
        logger.error("MCP MQTT mqtt_read: No response_topic supplied")
        return "Error: response_topic is required"
    
    app_ctx: MQTTAppContext = ctx.request_context.lifespan_context
    
    # Check read permission only
    if not validate_topic_permission(response_topic, "read", app_ctx.config.topics):
        logger.error("MCP MQTT mqtt_read: No read permissions for this topic")
        return f"Error: No read permission for response topic '{response_topic}'"
    
    # Ensure MQTT connection
    if not app_ctx.mqtt_manager.connected:
        if not app_ctx.mqtt_manager.connect():
            return "Error: Failed to connect to MQTT broker"
    
    # Subscribe and wait for message
    try:
        await ctx.info(f"Subscribing to '{response_topic}' and waiting for message...")
        
        # Subscribe to the response topic
        if not app_ctx.mqtt_manager.subscribe(response_topic):
            return f"Failed to subscribe to topic '{response_topic}'"
        
        # Wait for message
        logger.debug(f"MCP MQTT waiting for response on {response_topic}")
        response = await app_ctx.mqtt_manager.wait_for_message(response_topic, timeout)
        logger.debug(f"MCP MQTT received response on {response_topic}")
        
        # Unsubscribe from the topic after receiving message or timeout
        app_ctx.mqtt_manager.unsubscribe(response_topic)
        
        if response is not None:
            result = {
                "response_topic": response_topic,
                "response_payload": response,
                "success": True
            }
            return json.dumps(result, indent=2)
        else:
            result = {
                "response_topic": response_topic,
                "error": "Timeout waiting for message",
                "success": False
            }
            return json.dumps(result, indent=2)
            
    except Exception as e:
        # Ensure we unsubscribe even on error
        try:
            app_ctx.mqtt_manager.unsubscribe(response_topic)
        except:
            pass
        return f"Error waiting for message on topic '{response_topic}': {str(e)}"


@mcp.tool(
    annotations = {
        "title" : "Subscribe to a response_topic, publish a message to a request_topic with a specified payload as query and wait for a response. Return the first message received. If no message is returned until timeout, no message is returned",
        "readOnlyHint" : False,
        "destructiveHint" : True,
        "idempotentHint" : False,
        "openWorldHint" : True
    }
)
async def mqtt_query(request_topic: str, response_topic: str, payload: str, timeout: float = 5, ctx: Context = None) -> str:
    """Send a request and wait for response on specified topics."""
    if not request_topic or not response_topic or payload is None:
        return "Error: request_topic, response_topic, and payload are required"
    
    app_ctx: MQTTAppContext = ctx.request_context.lifespan_context
    
    # Check permissions
    if not validate_topic_permission(request_topic, "write", app_ctx.config.topics):
        return f"Error: No write permission for request topic '{request_topic}'"
    
    if not validate_topic_permission(response_topic, "read", app_ctx.config.topics):
        return f"Error: No read permission for response topic '{response_topic}'"
    
    # Ensure MQTT connection
    if not app_ctx.mqtt_manager.connected:
        if not app_ctx.mqtt_manager.connect():
            return "Error: Failed to connect to MQTT broker"
    
    # Send request and wait for response
    try:
        await ctx.info(f"Sending request to '{request_topic}' and waiting for response on '{response_topic}'")
        
        response = await app_ctx.mqtt_manager.request_response(
            request_topic, response_topic, payload, timeout
        )
        
        if response is not None:
            result = {
                "request_topic": request_topic,
                "response_topic": response_topic,
                "request_payload": payload,
                "response_payload": response,
                "success": True
            }
            return json.dumps(result, indent=2)
        else:
            result = {
                "request_topic": request_topic,
                "response_topic": response_topic,
                "request_payload": payload,
                "error": "Timeout waiting for response",
                "success": False
            }
            return json.dumps(result, indent=2)
            
    except Exception as e:
        return f"Error in request/response: {str(e)}"


@mcp.resource("mcpmqtt://topics/allowed")
def get_allowed_topics() -> str:
    """Get allowed topics resource."""
    if _current_config is None:
        return json.dumps({"error": "Configuration not available"}, indent=2)
    
    topics_info = []
    for topic_config in _current_config.topics:
        topics_info.append({
            "pattern": topic_config.pattern,
            "permissions": topic_config.permissions,
            "description": topic_config.description or "No description provided"
        })
    
    result = {
        "topics": topics_info,
        "mqtt_info": {
            "host": _current_config.mqtt.host,
            "port": _current_config.mqtt.port,
            "requires_auth": bool(_current_config.mqtt.username)
        }
    }
    
    return json.dumps(result, indent=2)


@mcp.resource("mcpmqtt://topics/examples")
def get_topic_examples() -> str:
    """Get topic usage examples resource."""
    if _current_config is None:
        return json.dumps({"error": "Configuration not available"}, indent=2)
    
    examples = []
    
    for topic_config in _current_config.topics:
        example = {
            "pattern": topic_config.pattern,
            "permissions": topic_config.permissions,
            "description": topic_config.description or "No description provided",
            "examples": []
        }
        
        # Generate example topics based on pattern
        if "+" in topic_config.pattern:
            example_topic = topic_config.pattern.replace("+", "example")
            example["examples"].append({
                "topic": example_topic,
                "usage": f"This matches the pattern '{topic_config.pattern}' where + is replaced with 'example'"
            })
        elif "#" in topic_config.pattern:
            base_topic = topic_config.pattern.replace("#", "subtopic/data")
            example["examples"].append({
                "topic": base_topic,
                "usage": f"This matches the pattern '{topic_config.pattern}' where # matches multiple levels"
            })
        else:
            example["examples"].append({
                "topic": topic_config.pattern,
                "usage": f"Exact topic match for '{topic_config.pattern}'"
            })
        
        examples.append(example)
    
    result = {
        "examples": examples,
        "wildcard_info": {
            "+": "Single-level wildcard (matches one topic level)",
            "#": "Multi-level wildcard (matches multiple topic levels, must be last)"
        }
    }
    
    return json.dumps(result, indent=2)


def _build_remote_fastapi_app(config: Config):
    """Create FastAPI application that wraps the MCP Starlette app."""
    remote_config = config.remote_server
    if remote_config is None:
        raise RuntimeError("Remote transport selected but remote_server config is missing")

    try:
        # We do imports here so we do not require the packages to be installed when using just stdio mode
        from fastapi import FastAPI, Request, HTTPException
        from fastapi.responses import JSONResponse
        from starlette.middleware.base import BaseHTTPMiddleware
    except ImportError as exc:  # pragma: no cover - import guarded for stdio-only installs
        raise RuntimeError(
            "Remote HTTP transport requires FastAPI. Install optional extras: 'pip install mcpMQTT[remote]'"
        ) from exc

    API_KEY_QUERY_PARAM = "api_key"
    STATUS_PATH = "/status"
    MCP_MOUNT_PATH = "/mcp"

    mcp_http_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def fastapi_lifespan(app):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_http_app.router.lifespan_context(mcp_http_app))
            yield

    fastapi_app = FastAPI(title="mcpMQTT Remote Server", version="1.0", lifespan=fastapi_lifespan)

    class APIKeyMiddleware(BaseHTTPMiddleware):
        """Validate Bearer, X-API-Key, or api_key query tokens."""

        def __init__(self, app):
            super().__init__(app)
            self._api_key = remote_config.api_key

        async def dispatch(self, request: Request, call_next):
            if request.url.path == STATUS_PATH:
                return await call_next(request)

            token = None
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1].strip()
            if not token:
                token = request.headers.get("x-api-key")
            if not token:
                token = request.query_params.get(API_KEY_QUERY_PARAM)
            if token != self._api_key:
                raise HTTPException(status_code=401, detail="Invalid or missing API key")
            return await call_next(request)

    fastapi_app.add_middleware(APIKeyMiddleware)

    @fastapi_app.get(STATUS_PATH)
    async def status():
        """Unprotected health endpoint."""
        mqtt_connected = bool(_current_mqtt_manager and _current_mqtt_manager.connected)
        return JSONResponse({"running": True, "mqtt_connected": mqtt_connected})

    fastapi_app.mount(MCP_MOUNT_PATH, mcp_http_app)
    return fastapi_app


def _prepare_uds_socket(path: str):
    """Ensure the UDS path is ready for binding."""
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            logger.warning(f"Could not create directory for UDS path {path}: {exc}")
    if os.path.exists(path):
        try:
            current_stat = os.stat(path)
            if stat.S_ISSOCK(current_stat.st_mode):
                os.remove(path)
            else:
                raise RuntimeError(f"UDS path {path} exists and is not a socket")
        except OSError as exc:
            raise RuntimeError(f"Failed to prepare existing UDS path {path}: {exc}") from exc


def _run_remote_transport(config: Config):
    """Launch FastAPI/uvicorn server for remote MCP transport."""
    remote_config = config.remote_server
    if remote_config is None:
        raise RuntimeError("remote_server configuration is required for remote transport")

    app = _build_remote_fastapi_app(config)

    try:
        # We import here so one can use stdiomode without having uvicorn installed (its a rather heavy dependency)
        import uvicorn
    except ImportError as exc:  # pragma: no cover - guarded for stdio installs
        raise RuntimeError(
            "Remote HTTP transport requires uvicorn. Install optional extras: 'pip install mcpMQTT[remote]'"
        ) from exc

    uvicorn_kwargs: Dict[str, Any] = {
        "app": app,
        "lifespan": "on",
        "log_config": None,
    }

    if remote_config.port is not None:
        uvicorn_kwargs["host"] = remote_config.host or "0.0.0.0"
        uvicorn_kwargs["port"] = remote_config.port
        logger.info(
            "Starting remote MCP server over TCP at %s:%s",
            uvicorn_kwargs["host"],
            uvicorn_kwargs["port"],
        )
    else:
        uds_path = remote_config.uds
        _prepare_uds_socket(uds_path)
        uvicorn_kwargs["uds"] = uds_path
        logger.info("Starting remote MCP server over UDS at %s", uds_path)

    uvicorn.run(**uvicorn_kwargs)


# Helper function to run the server (for compatibility with existing code)
def run_mcp_server():
    """Run the MCP server over stdio (default) or remote HTTP."""
    from mcpMQTT.config.config_manager import get_config, parse_arguments

    args = parse_arguments()
    config = get_config(args)

    try:
        if args.transport == 'remotehttp':
            if not config.remote_server:
                raise RuntimeError(
                    "remotehttp transport selected but remote_server configuration block is missing"
                )
            _run_remote_transport(config)
        else:
            mcp.run()
    except KeyboardInterrupt:
        logger.info("MCP server shutting down...")


if __name__ == "__main__":
    # Direct execution - run the MCP server
    run_mcp_server()
