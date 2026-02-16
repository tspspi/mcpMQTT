"""Configuration schema definitions using Pydantic for validation."""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field, validator, root_validator
import re


class MQTTConfig(BaseModel):
    """MQTT server configuration."""
    host: str = Field(default="localhost", description="MQTT broker hostname")
    port: int = Field(default=1883, ge=1, le=65535, description="MQTT broker port")
    username: Optional[str] = Field(default=None, description="MQTT username")
    password: Optional[str] = Field(default=None, description="MQTT password")
    keepalive: int = Field(default=60, ge=1, description="Connection keepalive in seconds")


class TopicConfig(BaseModel):
    """Topic permission configuration."""
    pattern: str = Field(description="MQTT topic pattern (supports + and # wildcards)")
    permissions: List[Literal["read", "write"]] = Field(description="Allowed permissions")
    description: Optional[str] = Field(default=None, description="Human-readable description")

    @validator('pattern')
    def validate_mqtt_topic_pattern(cls, v):
        """Validate MQTT topic pattern syntax."""
        if not v:
            raise ValueError("Topic pattern cannot be empty")
        
        # Check for invalid characters
        if any(char in v for char in ['\0', '\n', '\r']):
            raise ValueError("Topic pattern contains invalid characters")
        
        # Validate wildcard usage
        parts = v.split('/')
        for i, part in enumerate(parts):
            if part == '#':
                # # wildcard must be last and alone
                if i != len(parts) - 1:
                    raise ValueError("# wildcard must be the last part of topic pattern")
            elif '#' in part:
                raise ValueError("# wildcard must be alone in topic level")
            elif '+' in part and part != '+':
                raise ValueError("+ wildcard must be alone in topic level")
        
        return v

    @validator('permissions')
    def validate_permissions_not_empty(cls, v):
        """Ensure at least one permission is specified."""
        if not v:
            raise ValueError("At least one permission must be specified")
        return v


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level"
    )
    logfile: Optional[str] = Field(
        default=None,
        description="Path to log file. If None, logs to console only. File will be appended to."
    )


class RemoteServerConfig(BaseModel):
    """Remote HTTP/UDS server configuration."""

    api_key: str = Field(description="Shared secret required for remote MCP access")
    host: str = Field(
        default="0.0.0.0",
        description="Host/IP to bind when using TCP (ignored when port is not set)"
    )
    port: Optional[int] = Field(
        default=None,
        ge=1,
        le=65535,
        description="TCP port for remote MCP access"
    )
    uds: str = Field(
        default="/var/run/mcpmqtt.sock",
        description="Unix domain socket path used when TCP is not configured"
    )

    @validator('api_key')
    def validate_api_key_present(cls, v):
        if not v:
            raise ValueError("API key must be provided for remote server access")
        return v

    @validator('uds')
    def validate_uds_path(cls, v):
        if not v:
            raise ValueError("UDS path cannot be empty")
        return v

    # root validator defaults host when TCP port is configured
    @root_validator(skip_on_failure=True)
    def validate_tcp_settings(cls, values):
        port = values.get('port')
        host = values.get('host')
        if port is not None and not host:
            values['host'] = "0.0.0.0"
        return values


class Config(BaseModel):
    """Main application configuration."""
    mqtt: MQTTConfig = Field(default_factory=MQTTConfig)
    topics: List[TopicConfig] = Field(default_factory=list, description="Allowed topic patterns")
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    remote_server: Optional[RemoteServerConfig] = Field(
        default=None,
        description="Remote MCP server transport settings"
    )

    @validator('topics')
    def validate_topics_not_empty(cls, v):
        """Ensure at least one topic is configured."""
        if not v:
            raise ValueError("At least one topic configuration must be specified")
        return v


def mqtt_wildcard_match(pattern: str, topic: str) -> bool:
    """
    Check if a topic matches an MQTT wildcard pattern.
    
    Args:
        pattern: MQTT topic pattern with wildcards (+ for single level, # for multi-level)
        topic: Exact topic to match
        
    Returns:
        bool: True if topic matches pattern
        
    Examples:
        mqtt_wildcard_match("sensors/+/temperature", "sensors/room1/temperature") -> True
        mqtt_wildcard_match("sensors/#", "sensors/room1/temperature") -> True
        mqtt_wildcard_match("sensors/+", "sensors/room1/temperature") -> False
    """
    # Convert MQTT pattern to regex
    regex_pattern = pattern.replace('+', '[^/]+').replace('#', '.*')
    
    # Ensure exact match
    regex_pattern = f'^{regex_pattern}$'
    
    return bool(re.match(regex_pattern, topic))


def validate_topic_permission(topic: str, required_permission: str, config_topics: List[TopicConfig]) -> bool:
    """
    Validate if a topic has the required permission.
    
    Args:
        topic: The exact topic to check
        required_permission: 'read' or 'write'
        config_topics: List of topic configuration objects
        
    Returns:
        bool: True if permission is granted
    """
    for topic_config in config_topics:
        if mqtt_wildcard_match(topic_config.pattern, topic):
            if required_permission in topic_config.permissions:
                return True
    return False
