import asyncio
from nextgen_mqtt import NextGenMQTTClient

async def main():
    async with NextGenMQTTClient.staging() as client:
        result = await client.cleanup_device('2530294')
        print(result)

asyncio.run(main())
