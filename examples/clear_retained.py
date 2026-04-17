#!/usr/bin/env python3
"""Collect and clear retained MQTT messages for a device.

Connects via direct MQTT, collects all retained messages delivered on subscribe,
then publishes empty payloads with retain=True to clear them.

Usage:
    python examples/clear_retained.py 2530294 123123
    python examples/clear_retained.py 2530294 123123 --dry-run   # list only, don't clear
"""

import argparse
import asyncio
import logging

from nextgen_mqtt import NextGenMQTTClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect and clear retained MQTT messages.")
    parser.add_argument("device_serial", help="Target device serial (e.g. 2530294)")
    parser.add_argument("device_password", help="Device password")
    parser.add_argument("--dry-run", action="store_true", help="List retained messages without clearing")
    parser.add_argument("--wait", type=float, default=5.0, help="Seconds to wait for retained messages (default: 5)")
    return parser.parse_args()


async def main(device_serial: str, device_password: str, dry_run: bool, wait: float) -> None:
    print(f"Connecting to device {device_serial} via direct MQTT...")

    async with NextGenMQTTClient.staging() as client:
        async with client.connect_mqtt(device_serial, device_password) as conn:
            print(f"Connected. Subscribed to: {conn.topics}")
            print(f"Collecting retained messages for {wait}s...\n")

            retained_topics: list[str] = []

            try:
                async with asyncio.timeout(wait):
                    async for msg in conn.messages():
                        # Strip device serial prefix to get topic suffix
                        topic = str(msg.topic)
                        suffix = topic.removeprefix(f"{device_serial}/")
                        retained_topics.append(suffix)
                        print(f"  RETAINED: {topic} ({len(msg.payload)}B) hex={msg.payload.hex()[:80]}")
            except TimeoutError:
                pass

            if not retained_topics:
                print("No retained messages found.")
                return

            print(f"\nFound {len(retained_topics)} retained message(s).")

            if dry_run:
                print("Dry run — not clearing.")
                return

            print("Clearing retained messages...")
            for suffix in retained_topics:
                await conn.clear_retained(suffix)
                print(f"  CLEARED: {device_serial}/{suffix}")

            print(f"\nDone. Cleared {len(retained_topics)} retained message(s).")


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(main(args.device_serial, args.device_password, args.dry_run, args.wait))
    except KeyboardInterrupt:
        print("\nAborted.")
    except Exception as e:
        print(f"\nFailed: {e}")
        print("Tip: Direct MQTT (port 8883) may only work from internal networks.")
