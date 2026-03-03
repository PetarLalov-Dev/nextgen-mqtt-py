#!/usr/bin/env python3
"""Example: Send data to device via WebSocket.

This example demonstrates sending protobuf messages through WebSocket connection.
"""

import asyncio
import argparse
from contextlib import suppress
import logging

from nextgen_mqtt import NextGenMQTTClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a raw hex payload to a device over WebSocket.")
    parser.add_argument("device_serial", help="Target device serial (e.g. 2530294)")
    parser.add_argument(
        "hex_payload",
        help="Hex payload string, spaces allowed (e.g. '08 01 1a 04 31 32 33 34 ba 40 04 08 01 10 05')",
    )
    return parser.parse_args()


async def main(device_serial: str, hex_payload: str):

    print(f"Connecting to device {device_serial} via WebSocket...")

    async with NextGenMQTTClient.staging() as client:
        async with client.connect_websocket(device_serial, use_secondary=False) as conn:
            print(f"Connected! Connection type: {conn.connection.connection_type}")
            print(f"Device: {conn.device_serial}")
            
            # Wait a moment for connection to stabilize
            await asyncio.sleep(1)
            
            normalized_hex = "".join(hex_payload.split())
            payload = bytes.fromhex(normalized_hex)
            
            messages_to_send = [
                (payload, f"protobuf from hex: {normalized_hex}"),
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
            
            # Try to collect responses 40 times with 1 second delay between tries
            print("\nChecking for responses (40 tries, 1 second between tries)...")
            responses = []
            message_stream = conn.messages().__aiter__()
            pending_receive = None
            loop = asyncio.get_running_loop()

            for attempt in range(1, 41):
                attempt_started = loop.time()
                if pending_receive is None:
                    pending_receive = asyncio.create_task(message_stream.__anext__())
                try:
                    # Shield the receive task so timeout does not cancel the stream.
                    message = await asyncio.wait_for(asyncio.shield(pending_receive), timeout=1.0)
                    pending_receive = None
                    responses.append(message)
                    print(f"\nResponse received (attempt {attempt}/40):")
                    print(f"  Time: {message.received_at.isoformat()}")
                    print(f"  Topic: {message.topic}")
                    print(f"  Payload ({len(message.payload)} bytes): {message.payload.hex()}")
                except asyncio.TimeoutError:
                    print(f"No response on attempt {attempt}/40")
                except StopAsyncIteration:
                    print("Response stream closed by server.")
                    pending_receive = None
                    break
                except Exception as e:
                    print(f"Receive error: {e}")
                    pending_receive = None
                    break

                if attempt < 40:
                    elapsed = loop.time() - attempt_started
                    await asyncio.sleep(max(0, 1.0 - elapsed))

            if pending_receive is not None and not pending_receive.done():
                pending_receive.cancel()
                with suppress(asyncio.CancelledError):
                    await pending_receive
            
            print(f"\nTotal responses received: {len(responses)}")
            
            if responses:
                print("\nResponse topics:")
                unique_topics = set(msg.topic for msg in responses)
                for topic in unique_topics:
                    count = sum(1 for msg in responses if msg.topic == topic)
                    print(f"  {topic}: {count} messages")


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(main(args.device_serial, args.hex_payload))
    except KeyboardInterrupt:
        print("\nExiting...")
