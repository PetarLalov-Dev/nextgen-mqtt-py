#!/usr/bin/env python3
"""Example: Get authentication tokens without connecting.

Useful for debugging or when you need the tokens for other purposes.
"""

import asyncio
import logging

from nextgen_mqtt import AuthClient, StagingEnvironment

logging.basicConfig(level=logging.INFO)


async def main():
    device_serial = "2530294"  # Change this to your device

    env = StagingEnvironment.STAGING

    async with AuthClient(env) as auth:
        # Step 1: Get OAuth2 access token (affiliate credentials)
        print("Step 1: Getting OAuth2 access token...")
        access_token = await auth.get_access_token()
        print(f"  Token type: {access_token.token_type}")
        print(f"  Expires in: {access_token.expires_in} seconds")
        print(f"  Scope: {access_token.scope}")
        print(f"  Token: {access_token.token}")
        print()

        # Step 2: Create user token for WebSocket connection
        print(f"Step 2: Creating user token for device {device_serial}...")
        user_token = await auth.create_user_token(
            device_serial=device_serial,
            ttl_seconds=3600,
            globals_config={
                "can_view_events": True,
                "can_control_devices": True,
                "can_manage_users": False,
                "can_manage_devices": False,
            },
        )
        print(f"  Expires at: {user_token.expires_at}")
        print(f"  Primary API: {user_token.primary.api}")
        print(f"  Primary WS: {user_token.primary.ws}")
        if user_token.secondary:
            print(f"  Secondary API: {user_token.secondary.api}")
            print(f"  Secondary WS: {user_token.secondary.ws}")
        print(f"  Token: {user_token.token}")
        print()

        print("WebSocket Connection Info:")
        ws_url = f"{user_token.primary.ws[0]}/v1/device/{device_serial}/ws"
        print(f"  URL: {ws_url}")
        print(f"  Authorization: Bearer {user_token.token}")
        print()

        # Step 3: Device login (alternative - for direct MQTT)
        print("Step 3: Device login (for direct MQTT - internal networks)...")
        try:
            device_token = await auth.device_login(
                device_serial=device_serial,
                device_password="123123",  # Device password
            )
            print(f"  Expires at: {device_token.expires_at}")
            print(f"  Primary MQTT: {device_token.primary.mq}")
            if device_token.secondary:
                print(f"  Secondary MQTT: {device_token.secondary.mq}")
            print(f"  Token: {device_token.token}")
        except Exception as e:
            print(f"  Device login failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
