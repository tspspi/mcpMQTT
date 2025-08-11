# Configuration management for the MCP server

import json
import os
import argparse
import logging
import logging.handlers
from typing import Optional
from pydantic import ValidationError

from mcpMQTT.config.schema import Config, TopicConfig, MQTTConfig, LoggingConfig


logger = logging.getLogger(__name__)


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
    default_path = os.path.expanduser("~/.config/mcpmqtt/config.json")
    path = config_path or default_path

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
    args = parser.parse_args()
    return args


def get_config() -> Config:
    """
    Get configuration from command line arguments and file.
    
    Returns:
        Config: Validated configuration object
    """
    args = parse_arguments()
    
    # Load config first to get all settings
    config = load_config(args.config)
    
    # Override config with CLI arguments if provided
    if args.logfile:
        config.logging.logfile = args.logfile
    if args.log_level != 'INFO':  # Only override if explicitly set
        config.logging.level = args.log_level.upper()
    
    # Set up logging with final configuration
    setup_logging(config.logging)
    
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
            "logfile": null
        }
    }
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    with open(path, 'w') as f:
        json.dump(default_config, f, indent=2)
    
    logger.info(f"Default configuration file created at {path}")