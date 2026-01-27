#!/usr/bin/env python3
"""Example: Direct MQTT connection using device credentials.

NOTE: Direct MQTT (port 8883) may only be accessible from internal networks.
For external access, use WebSocket connection instead (see basic_subscribe.py).

This method requires device credentials (serial + password), not affiliate credentials.
"""

import asyncio
import logging

from nextgen_mqtt import NextGenMQTTClient

logging.basicConfig(level=logging.INFO)


async def main():
    device_serial = "2530295"  # Change this to your device
    device_password = "123123"  # Device password (not affiliate credentials)

    print(f"Connecting to device {device_serial} via direct MQTT...")
    print("NOTE: This may fail if MQTT port 8883 is not accessible from your network.")

    async with NextGenMQTTClient.staging() as client:
        try:
            async with client.connect_mqtt(device_serial, device_password) as conn:
                print(f"Connected! Connection type: {conn.connection.connection_type}")
                print(f"Subscribed topics: {conn.topics[:3]}...")
                print("Waiting for messages (Ctrl+C to exit)...\n")

                async for message in conn.messages():
                    print(f"[{message.received_at.isoformat()}] {message.topic}")
                    print(f"  Payload: {message.payload[:100]!r}")
                    print()
        except Exception as e:
            print(f"\nConnection failed: {e}")
            print("\nTip: If MQTT port 8883 is not accessible, use WebSocket instead:")
            print("  async with client.connect_websocket(device_serial) as conn:")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
