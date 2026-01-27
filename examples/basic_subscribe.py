#!/usr/bin/env python3
"""Basic example: Subscribe to a device via WebSocket and print all messages.

This uses the WebSocket connection to device-shard-api, which is the
recommended method for external access. Messages are in protobuf format.
"""

import asyncio
import logging

from nextgen_mqtt import NextGenMQTTClient

# Enable logging to see connection progress
logging.basicConfig(level=logging.INFO)


async def main():
    device_serial = "2530294"  # Change this to your device

    print(f"Subscribing to device {device_serial} via WebSocket...")

    async with NextGenMQTTClient.staging() as client:
        async with client.connect_websocket(device_serial, use_secondary=True) as conn:
            print(f"Connected! Connection type: {conn.connection.connection_type}")
            print(f"Device: {conn.device_serial}")
            # print("Waiting for messages (Ctrl+C to exit)...\n")

            print("Waiting for messages (Ctrl+C to exit)...\n")
            
            # Send protobuf message to the device
            hex_payload = '0801e2400408011001'
            payload = bytes.fromhex(hex_payload)  # Convert hex string to bytes
            print(f"Sending message to device: {hex_payload}")
            await conn.send(payload)
            print(f"Message sent! ({len(payload)} bytes)\n")
            
            message_count = 0
            async for message in conn.messages():
                print(f"[{message.received_at.isoformat()}] Received {len(message.payload)} bytes")
                # Messages are in protobuf format - raw bytes
                print(f"  Payload (hex): {message.payload[:50].hex()}...")
                print()
                
                # Optional: break after sending
                # if message_count >= 10:
                #     break
                


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
