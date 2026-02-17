# Configuration management for the MCP server

import argparse
import json
import logging
import logging.handlers
import os
from typing import Optional

from pydantic import ValidationError

from mcpMQTT.config.api_keys import (
    derive_argon2id_hash,
    ensure_kdf_defaults,
    ensure_kdf_salt,
    generate_random_api_key,
)
from mcpMQTT.config.schema import Config, TopicConfig, MQTTConfig, LoggingConfig


logger = logging.getLogger(__name__)
_cached_config: Optional[Config] = None
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/mcpmqtt/config.json")


def setup_logging(logging_config: LoggingConfig):
    """
    Set up logging configuration with optional file output.
    
    Args:
        logging_config: LoggingConfig object with level and optional logfile
    """
    # Clear any existing handlers to avoid duplication
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Set up the formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Set up console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Set up file handler if logfile is specified
    if logging_config.logfile:
        try:
            # Create directory if it doesn't exist
            log_dir = os.path.dirname(os.path.abspath(logging_config.logfile))
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            
            # Create file handler that appends to the file
            file_handler = logging.FileHandler(logging_config.logfile, mode='a')
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
            
            logger.info(f"Logging to file: {logging_config.logfile}")
        except (OSError, IOError) as e:
            logger.warning(f"Could not set up file logging to {logging_config.logfile}: {e}")
    
    # Set the logging level
    log_level = getattr(logging, logging_config.level.upper())
    root_logger.setLevel(log_level)
    
    logger.info(f"Logging configured - Level: {logging_config.level}, File: {logging_config.logfile or 'Console only'}")


def load_config(config_path: Optional[str] = None) -> Config:
    """
    Load and validate configuration from JSON file.
    
    Args:
        config_path: Optional path to configuration file
        
    Returns:
        Config: Validated configuration object
        
    Raises:
        ValidationError: If configuration is invalid
        FileNotFoundError: If configuration file doesn't exist and no defaults work
    """
    path = config_path or DEFAULT_CONFIG_PATH

    # Try to load from file
    config_data = {}
    try:
        with open(path, 'r') as config_file:
            config_data = json.load(config_file)
        logger.info(f"Configuration loaded from {path}")
    except FileNotFoundError:
        logger.warning(f"Configuration file not found at {path}. Using default settings.")
        # Use default configuration with at least one topic
        config_data = {
            "topics": [
                {
                    "pattern": "test/+",
                    "permissions": ["read", "write"],
                    "description": "Default test topic pattern"
                }
            ]
        }
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in configuration file {path}: {e}")
        raise ValidationError(f"Invalid JSON in configuration file: {e}", Config)

    # Validate configuration using Pydantic
    try:
        config = Config(**config_data)
        logger.info("Configuration validation successful")
        return config
    except ValidationError as e:
        logger.error(f"Configuration validation failed: {e}")
        raise


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="MCP MQTT Server")
    parser.add_argument('--config', type=str, help='Path to the configuration file')
    parser.add_argument('--log-level', type=str, default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                       help='Set the logging level')
    parser.add_argument('--logfile', type=str, help='Path to log file (appends to existing file)')
    parser.add_argument('--transport', type=str, default='stdio',
                       choices=['stdio', 'remotehttp'],
                       help='Select MCP transport (stdio for local, remotehttp for FastAPI/uvicorn)')
    parser.add_argument('--genkey', action='store_true',
                        help='Generate a new API key, store its Argon2id hash in the config, then exit')
    args = parser.parse_args()
    return args


def get_config(parsed_args: Optional[argparse.Namespace] = None) -> Config:
    """
    Get configuration from command line arguments and file.
    
    Returns:
        Config: Validated configuration object
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    args = parsed_args or parse_arguments()
    
    # Load config first to get all settings
    config = load_config(args.config)
    
    # Override config with CLI arguments if provided
    if args.logfile:
        config.logging.logfile = args.logfile
    if args.log_level != 'INFO':  # Only override if explicitly set
        config.logging.level = args.log_level.upper()
    
    # Set up logging with final configuration
    setup_logging(config.logging)
    
    _cached_config = config
    return config


def create_default_config_file(path: str):
    """
    Create a default configuration file at the specified path.
    
    Args:
        path: Path where to create the configuration file
    """
    default_config = {
        "mqtt": {
            "host": "localhost",
            "port": 1883,
            "keepalive": 60
        },
        "topics": [
            {
                "pattern": "sensors/+/temperature",
                "permissions": ["read", "write"],
                "description": "Temperature sensor data from any location"
            },
            {
                "pattern": "actuators/#",
                "permissions": ["write"],
                "description": "All actuator control topics"
            },
            {
                "pattern": "status/system",
                "permissions": ["read"],
                "description": "System status information"
            }
        ],
        "logging": {
            "level": "INFO",
            "logfile": None
        }
    }
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    with open(path, 'w') as f:
        json.dump(default_config, f, indent=2)
    
    logger.info(f"Default configuration file created at {path}")


def generate_and_store_api_key(config_path: Optional[str] = None) -> str:
    """Generate a new API key, derive its hash, and persist it to the config file."""
    path = config_path or DEFAULT_CONFIG_PATH

    try:
        with open(path, 'r', encoding='utf-8') as config_file:
            config_data = json.load(config_file)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Configuration file not found at {path}. Provide --config or create one first."
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in configuration file {path}: {exc}") from exc

    remote_server = config_data.get('remote_server')
    if not remote_server:
        raise ValueError("remote_server block must exist in configuration to generate an API key")

    kdf_block = ensure_kdf_defaults(remote_server.get('api_key_kdf'))
    ensure_kdf_salt(kdf_block)

    new_key = generate_random_api_key()
    kdf_block['hash'] = derive_argon2id_hash(new_key, kdf_block)
    remote_server['api_key_kdf'] = kdf_block
    remote_server.pop('api_key', None)
    config_data['remote_server'] = remote_server

    # Validate to ensure we did not break the configuration
    Config(**config_data)

    config_dir = os.path.dirname(path)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as config_file:
        json.dump(config_data, config_file, indent=2)
        config_file.write('\n')

    logger.info(f"Updated API key hash in {path}")
    return new_key
