#!/usr/bin/env python3
"""Listen to all MQTT messages for a device via direct MQTT connection.

Connects directly to the MQTT broker using device credentials and prints
every incoming message in real time. Unlike ws_listen.py (which uses the
WebSocket proxy), this sees the actual MQTT messages the device publishes.

Usage:
    python examples/mqtt_listen.py 2530294
    python examples/mqtt_listen.py 2530294 --password SECRET
    python examples/mqtt_listen.py 2530294 --raw        # hex only, no Helix decode
    python examples/mqtt_listen.py 2530294 --verbose     # enable debug logging
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

from google.protobuf.json_format import MessageToDict

from nextgen_mqtt import NextGenMQTTClient
from nextgen_mqtt.models import MQTTMessage, TopicType

LOG_FILE = "mqtt_listen.log"
TOPIC_LABELS = {
    TopicType.COMMAND: "CMD",
    TopicType.RESPONSE: "RSP",
    TopicType.EVENT: "EVT",
    TopicType.CONFIG: "CFG",
    TopicType.CONFIG_DESIRED: "CDS",
    TopicType.STATUS: "STS",
    TopicType.INFO: "INF",
    TopicType.UNKNOWN: "???",
}


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3)
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Listen to all MQTT messages for a device via direct MQTT.")
    parser.add_argument("device_serial", help="Target device serial (e.g. 2530294)")
    parser.add_argument("--password", default="123123", help="Device password (default: 123123)")
    parser.add_argument("--raw", action="store_true", help="Show raw hex only, skip Helix decode")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging to file")
    parser.add_argument("--secondary", action="store_true", help="Use secondary shard (1-B)")
    return parser.parse_args()


def format_message(msg: MQTTMessage, raw: bool) -> str:
    topic_type = msg.topic_type
    label = TOPIC_LABELS.get(topic_type, "???")
    ts = msg.received_at.strftime("%H:%M:%S.%f")[:-3]
    header = f"[{ts}] [{label}] {msg.topic} ({len(msg.payload)}B)"

    if raw or msg.helix is None:
        return f"{header}\n  hex: {msg.payload.hex()}"

    helix = msg.helix
    decoded = MessageToDict(helix.message, preserving_proto_field_name=True)
    pretty = json.dumps(decoded, indent=2)
    indented = "\n".join(f"  {line}" for line in pretty.splitlines())
    return f"{header} msg_id={helix.msg_id} [{helix.message_name}]\n{indented}"


async def listen(device_serial: str, password: str, raw: bool, secondary: bool) -> None:
    logger = logging.getLogger(__name__)
    count = 0

    print(f"Connecting to device {device_serial} via direct MQTT...")

    async with NextGenMQTTClient.staging() as client:
        async with client.connect_mqtt(device_serial, password, use_secondary=secondary) as conn:
            print(f"Connected. Subscribed to: {', '.join(conn.topics)}")
            print(f"Listening for messages on {device_serial} (Ctrl+C to stop)\n")
            logger.info("Connected to device %s, listening", device_serial)

            async for msg in conn.messages():
                count += 1
                print(f"#{count} {format_message(msg, raw)}\n")
                logger.info(
                    "Message #%d topic=%s bytes=%d hex=%s",
                    count,
                    msg.topic,
                    len(msg.payload),
                    msg.payload.hex(),
                )


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    try:
        asyncio.run(listen(args.device_serial, args.password, args.raw, args.secondary))
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
