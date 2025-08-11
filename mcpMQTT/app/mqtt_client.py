# MQTT client logic using Paho-MQTT

import paho.mqtt.client as mqtt
import logging
import asyncio
import time
from typing import Optional, Callable, Dict, Any
from threading import Lock
from mcpMQTT.config.schema import MQTTConfig

logger = logging.getLogger(__name__)


class MQTTClientManager:
    """Enhanced MQTT client with authentication and async support."""
    
    def __init__(self, config: MQTTConfig):
        self.config = config
        self.client: Optional[mqtt.Client] = None
        self.connected = False
        self.message_handlers: Dict[str, Callable] = {}
        self.pending_responses: Dict[str, asyncio.Future] = {}
        self._lock = Lock()
        
    def create_client(self) -> mqtt.Client:
        """Create and configure MQTT client."""
        client = mqtt.Client()
        
        # Set authentication if provided
        if self.config.username and self.config.password:
            client.username_pw_set(self.config.username, self.config.password)
            logger.info("MQTT authentication configured")
        
        # Set callbacks
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.on_log = self._on_log
        
        self.client = client
        return client
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback for successful connection."""
        if rc == 0:
            self.connected = True
            logger.info(f"Connected to MQTT broker at {self.config.host}:{self.config.port}")
        else:
            self.connected = False
            error_messages = {
                1: "Connection refused - incorrect protocol version",
                2: "Connection refused - invalid client identifier",
                3: "Connection refused - server unavailable",
                4: "Connection refused - bad username or password",
                5: "Connection refused - not authorised"
            }
            error_msg = error_messages.get(rc, f"Connection refused - unknown error ({rc})")
            logger.error(f"Failed to connect to MQTT broker: {error_msg}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback for disconnection."""
        self.connected = False
        if rc != 0:
            logger.warning(f"Unexpected disconnection from MQTT broker (code: {rc})")
        else:
            logger.info("Disconnected from MQTT broker")
    
    def _on_message(self, client, userdata, msg):
        """Callback for received messages."""
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        
        logger.debug(f"Received message on topic '{topic}': {payload}")
        
        # Check for pending response futures
        with self._lock:
            if topic in self.pending_responses:
                future = self.pending_responses[topic]  # Don't pop here, let wait_for_message handle cleanup
                if not future.done():
                    # CRITICAL FIX: Schedule the future completion on the correct event loop thread
                    try:
                        loop = future.get_loop()
                        loop.call_soon_threadsafe(future.set_result, payload)
                        logger.debug(f"Scheduled future completion (thread-safe) for topic '{topic}': {payload}")
                    except Exception as e:
                        logger.error(f"Error scheduling future completion: {e}")
                        # Fallback - this might not work reliably across threads
                        future.set_result(payload)
            else:
                logger.debug(f"No pending response for topic '{topic}'")
        
        # Call custom handlers
        if topic in self.message_handlers:
            try:
                logger.debug(f"Trying to execute message handler for topic '{topic}'")
                self.message_handlers[topic](topic, payload)
            except Exception as e:
                logger.error(f"Error in message handler for topic '{topic}': {e}")
        else:
            logger.debug(f"No message handler for topic '{topic}'")
    
    def _on_log(self, client, userdata, level, buf):
        """Callback for MQTT client logs."""
        if level == mqtt.MQTT_LOG_DEBUG:
            logger.debug(f"MQTT: {buf}")
        elif level == mqtt.MQTT_LOG_INFO:
            logger.info(f"MQTT: {buf}")
        elif level == mqtt.MQTT_LOG_WARNING:
            logger.warning(f"MQTT: {buf}")
        elif level == mqtt.MQTT_LOG_ERR:
            logger.error(f"MQTT: {buf}")
    
    def connect(self) -> bool:
        """Connect to MQTT broker."""
        if not self.client:
            self.create_client()
        
        try:
            logger.info(f"Connecting to MQTT broker at {self.config.host}:{self.config.port}")
            self.client.connect(self.config.host, self.config.port, self.config.keepalive)
            self.client.loop_start()
            
            # Wait for connection with timeout
            timeout = 10
            start_time = time.time()
            while not self.connected and (time.time() - start_time) < timeout:
                time.sleep(0.1)
            
            if self.connected:
                logger.info("Successfully connected to MQTT broker")
                return True
            else:
                logger.error("Failed to connect to MQTT broker within timeout")
                return False
                
        except Exception as e:
            logger.error(f"Error connecting to MQTT broker: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from MQTT broker."""
        if self.client and self.connected:
            self.client.loop_stop()
            self.client.disconnect()
            logger.info("Disconnected from MQTT broker")
    
    def publish(self, topic: str, payload: str, qos: int = 0) -> bool:
        """
        Publish message to topic.
        
        Args:
            topic: MQTT topic
            payload: Message payload
            qos: Quality of Service level (0, 1, or 2)
            
        Returns:
            bool: True if message was published successfully
        """
        if not self.connected:
            logger.error("Not connected to MQTT broker")
            return False
        
        try:
            result = self.client.publish(topic, payload, qos)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Published message to topic '{topic}': {payload}")
                return True
            else:
                logger.error(f"Failed to publish message to topic '{topic}': {result.rc}")
                return False
        except Exception as e:
            logger.error(f"Error publishing message to topic '{topic}': {e}")
            return False
    
    def subscribe(self, topic: str, qos: int = 0) -> bool:
        """
        Subscribe to topic.
        
        Args:
            topic: MQTT topic pattern
            qos: Quality of Service level
            
        Returns:
            bool: True if subscription was successful
        """
        if not self.connected:
            logger.error("Not connected to MQTT broker")
            return False
        
        try:
            result = self.client.subscribe(topic, qos)
            if result[0] == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Subscribed to topic '{topic}'")
                return True
            else:
                logger.error(f"Failed to subscribe to topic '{topic}': {result[0]}")
                return False
        except Exception as e:
            logger.error(f"Error subscribing to topic '{topic}': {e}")
            return False
    
    def unsubscribe(self, topic: str) -> bool:
        """Unsubscribe from topic."""
        if not self.connected:
            logger.error("Not connected to MQTT broker")
            return False
        
        try:
            result = self.client.unsubscribe(topic)
            if result[0] == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Unsubscribed from topic '{topic}'")
                return True
            else:
                logger.error(f"Failed to unsubscribe from topic '{topic}': {result[0]}")
                return False
        except Exception as e:
            logger.error(f"Error unsubscribing from topic '{topic}': {e}")
            return False
    
    async def wait_for_message(self, topic: str, timeout: float = 5.0) -> Optional[str]:
        """
        Wait for a message on specific topic.
        
        Args:
            topic: Topic to wait for
            timeout: Timeout in seconds
            
        Returns:
            str: Message payload or None if timeout
        """
        if not self.connected:
            logger.error("Not connected to MQTT broker")
            return None
        
        # Note: Subscription should be handled by the caller to avoid double subscription
        # Create future for this topic
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        
        with self._lock:
            # Check if there's already a pending response for this topic
            if topic in self.pending_responses:
                logger.warning(f"Overwriting existing pending response for topic '{topic}'")
            self.pending_responses[topic] = future
        
        try:
            # Wait for message with timeout
            result = await asyncio.wait_for(future, timeout)
            logger.debug(f"Successfully received message for topic '{topic}': {result}")
            return result
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for message on topic '{topic}'")
            return None
        except Exception as e:
            logger.error(f"Error waiting for message on topic '{topic}': {e}")
            return None
        finally:
            # Clean up pending response
            with self._lock:
                removed_future = self.pending_responses.pop(topic, None)
                if removed_future:
                    logger.debug(f"Cleaned up pending response for topic '{topic}'")
    
    async def request_response(self, request_topic: str, response_topic: str,
                              payload: str, timeout: float = 5.0) -> Optional[str]:
        """
        Send request and wait for response.
        
        Args:
            request_topic: Topic to send request
            response_topic: Topic to listen for response
            payload: Request payload
            timeout: Response timeout
            
        Returns:
            str: Response payload or None if timeout/error
        """
        # Start listening for response first
        response_task = asyncio.create_task(self.wait_for_message(response_topic, timeout))
        
        # Small delay to ensure subscription is active
        await asyncio.sleep(0.1)
        
        # Send request
        if not self.publish(request_topic, payload):
            response_task.cancel()
            return None
        
        # Wait for response
        try:
            response = await response_task
            return response
        except asyncio.CancelledError:
            return None


# Legacy function compatibility
def create_mqtt_client():
    """Legacy function for backward compatibility."""
    logger.warning("create_mqtt_client() is deprecated. Use MQTTClientManager instead.")
    return mqtt.Client()

def connect_to_server(client, host, port=1883, keepalive=60):
    """Legacy function for backward compatibility."""
    logger.warning("connect_to_server() is deprecated. Use MQTTClientManager instead.")
    client.connect(host, port, keepalive)
    client.loop_start()

def subscribe_to_topic(client, topic):
    """Legacy function for backward compatibility."""
    logger.warning("subscribe_to_topic() is deprecated. Use MQTTClientManager instead.")
    client.subscribe(topic)

def publish_message(client, topic, payload):
    """Legacy function for backward compatibility."""
    logger.warning("publish_message() is deprecated. Use MQTTClientManager instead.")
    client.publish(topic, payload)