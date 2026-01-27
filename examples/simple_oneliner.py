#!/usr/bin/env python3
"""Simplest example: One-liner subscription using convenience function."""

import asyncio
import logging

from nextgen_mqtt import subscribe_websocket

logging.basicConfig(level=logging.INFO)


async def main():
    device_serial = "2530294"  # Change this to your device

    print(f"Subscribing to {device_serial}...")

    # Simple one-liner approach via WebSocket
    async for message in subscribe_websocket(device_serial):
        print(f"Received {len(message.payload)} bytes: {message.payload[:50].hex()}...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
