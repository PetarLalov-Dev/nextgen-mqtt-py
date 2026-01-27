#!/usr/bin/env python3
"""Example: Send commands to device using direct MQTT connection.

This example shows how to send commands to a device using the MQTT publish method.
Note: Direct MQTT requires device credentials and may only work on internal networks.
"""

import asyncio
import logging

from nextgen_mqtt import NextGenMQTTClient

logging.basicConfig(level=logging.INFO)


async def main():
    device_serial = "2530294"  # Change this to your device
    device_password = "123123"  # Device password (not affiliate credentials)

    print(f"Connecting to device {device_serial} via direct MQTT...")

    async with NextGenMQTTClient.staging() as client:
        try:
            async with client.connect_mqtt(device_serial, device_password, use_secondary=True) as conn:
                print(f"Connected! Connection type: {conn.connection.connection_type}")
                
                # Send an empty protobuf message using send_command
                print("\nSending empty command...")
                await conn.send_command('0801e2400408011001')  # Example command payload
                print("Command sent!")
                
                # Or publish to a specific topic
                print("\nPublishing to command topic...")
                await conn.publish("c", b'0801e2400408011001')  # "c" is the command topic
                print("Published to command topic!")
                
                # # Listen for responses
                # print("\nListening for responses (Ctrl+C to exit)...")
                # message_count = 0
                # async for message in conn.messages():
                #     print(f"[{message.received_at.isoformat()}] Topic: {message.topic}")
                #     print(f"  Payload ({len(message.payload)} bytes): {message.payload[:50].hex()}...")
                    
                #     message_count += 1
                #     if message_count >= 5:  # Exit after 5 messages
                #         break
                        
        except Exception as e:
            print(f"\nConnection failed: {e}")
            print("\nIf MQTT port 8883 is not accessible, WebSocket sending might not work")
            print("as expected. The device might only accept commands via direct MQTT.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")