#!/usr/bin/env python3
"""Example: Send data to device via WebSocket.

This example demonstrates sending protobuf messages through WebSocket connection.
"""

import asyncio
import logging

from nextgen_mqtt import NextGenMQTTClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


async def main():
    device_serial = "2530294"  # Change this to your device

    print(f"Connecting to device {device_serial} via WebSocket...")

    async with NextGenMQTTClient.staging() as client:
        async with client.connect_websocket(device_serial, use_secondary=False) as conn:
            print(f"Connected! Connection type: {conn.connection.connection_type}")
            print(f"Device: {conn.device_serial}")
            
            # Wait a moment for connection to stabilize
            await asyncio.sleep(1)
            
            # Use the same hex payload as the working JavaScript code
            hex_payload = '0801e2400408011001'
            payload = bytes.fromhex(hex_payload)  # Convert hex string to bytes
            
            messages_to_send = [
                (payload, f"protobuf from hex: {hex_payload}"),
            ]
            
            # Collect initial messages that might be already waiting
            initial_messages = []
            print("Collecting any initial messages...")
            try:
                async with asyncio.timeout(0.5):
                    async for message in conn.messages():
                        initial_messages.append(message)
                        print(f"Initial message - Topic: {message.topic}, Payload: {message.payload.hex()}")
            except asyncio.TimeoutError:
                pass
            
            print(f"\nReceived {len(initial_messages)} initial messages")
            
            for msg, description in messages_to_send:
                print(f"\nSending {description}: {msg.hex()}")
                print(f"Sending {len(msg)} bytes to WebSocket")
                
                # The WebSocket connection doesn't have a specific topic - it's just a raw WebSocket
                # The device-shard-api handles routing to the device
                print(f"Note: WebSocket messages are sent directly to device {device_serial}")
                print("      (not to a specific MQTT topic)")
                
                try:
                    await conn.send(msg)
                    print(f"Sent successfully!")
                except Exception as e:
                    print(f"Failed to send: {e}")
            
            # Wait 5 seconds and collect any responses
            print("\nWaiting 5 seconds for responses...")
            responses = []
            
            try:
                async with asyncio.timeout(5):
                    async for message in conn.messages():
                        responses.append(message)
                        print(f"\nResponse received:")
                        print(f"  Time: {message.received_at.isoformat()}")
                        print(f"  Topic: {message.topic}")
                        print(f"  Payload ({len(message.payload)} bytes): {message.payload.hex()}")
            except asyncio.TimeoutError:
                pass
            
            print(f"\nTotal responses received: {len(responses)}")
            
            if responses:
                print("\nResponse topics:")
                unique_topics = set(msg.topic for msg in responses)
                for topic in unique_topics:
                    count = sum(1 for msg in responses if msg.topic == topic)
                    print(f"  {topic}: {count} messages")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")