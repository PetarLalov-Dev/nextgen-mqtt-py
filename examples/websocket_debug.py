#!/usr/bin/env python3
"""Debug WebSocket connection to check close codes and connection behavior."""

import asyncio
import logging
import websockets
from websockets.exceptions import ConnectionClosed

from nextgen_mqtt.auth import AuthClient
from nextgen_mqtt.config import StagingEnvironment

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def main():
    device_serial = "2530294"
    env = StagingEnvironment.STAGING
    
    # Get authentication token
    print("Getting authentication token...")
    async with AuthClient(env) as auth:
        access_token = await auth.get_access_token()
        user_token = await auth.create_user_token(device_serial, ttl_seconds=3600)
    
    # Construct WebSocket URL
    ws_url = f"{user_token.primary.ws[0]}/v1/device/{device_serial}/ws"
    headers = {"Authorization": f"Bearer {user_token.token}"}
    
    print(f"Connecting to: {ws_url}")
    
    ws = None
    try:
        # Connect to WebSocket
        ws = await websockets.connect(ws_url, additional_headers=headers)
        logger.info(f"WebSocket connected! State: {ws.state}")
        
        # Send the protobuf message
        hex_payload = '0801e2400408011001'
        payload = bytes.fromhex(hex_payload)
        
        logger.info(f"Sending {len(payload)} bytes: {hex_payload}")
        await ws.send(payload)
        logger.info("Message sent successfully!")
        
        # Wait for responses
        print("\nWaiting for responses...")
        message_count = 0
        
        try:
            async with asyncio.timeout(5):
                async for message in ws:
                    message_count += 1
                    if isinstance(message, bytes):
                        logger.info(f"Received message #{message_count}: {message.hex()} ({len(message)} bytes)")
                    else:
                        logger.info(f"Received text message #{message_count}: {message}")
                    
        except asyncio.TimeoutError:
            logger.info("Timeout reached after 5 seconds")
        
        logger.info(f"Total messages received: {message_count}")
        
        # Try to close cleanly
        logger.info("Attempting clean close...")
        close_code = 1000
        close_reason = "Normal closure"
        
        await ws.close(close_code, close_reason)
        logger.info(f"Close frame sent with code {close_code}")
        
        # Wait for close to complete
        logger.info("Waiting for close to complete...")
        await ws.wait_closed()
        
    except ConnectionClosed as e:
        logger.error(f"WebSocket closed unexpectedly! Code: {e.code}, Reason: {e.reason}")
        
    except Exception as e:
        logger.error(f"Error: {type(e).__name__}: {e}")
        
    finally:
        if ws:
            logger.info(f"Final WebSocket state: {ws.state}")
            logger.info(f"Close code: {ws.close_code}")
            logger.info(f"Close reason: {ws.close_reason}")
            
            if ws.close_code and ws.close_code != 1000:
                logger.warning(f"Abnormal close detected! Code: {ws.close_code}")
                if ws.close_code == 1006:
                    logger.warning("Code 1006: Abnormal closure - connection lost without close frame")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")