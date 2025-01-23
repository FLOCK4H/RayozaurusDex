# Dex API

import aiohttp
import asyncio, json

from typing import List, Dict, Any

GET_CHAIN_ADDR_INFO = "https://api.dexscreener.com/latest/dex/tokens"

class AsyncDex:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def get_chain_address_info(self, address: str) -> Dict[str, Any]:
        is_boosted, boosts = False, 0
        response = await self.session.get(f"{GET_CHAIN_ADDR_INFO}/{address}")
        hResponse = await response.json()
        if hResponse is not None:
            pairs = hResponse.get("pairs", [])
            if pairs is not None:
                for pair in pairs:
                    if "boosts" in pair:
                        is_boosted = True
                        boosts = int(pair["boosts"]["active"])
        return is_boosted, boosts

if __name__ == "__main__":
    # Example
    async def main():
        async with aiohttp.ClientSession() as session:
            dex = AsyncDex(session)
            is_boosted, boosts = await dex.get_chain_address_info("53b24wQ7SmfQNS4T9co2re8t5t7RqKcZcNUuQnQoVCnG")
            print(is_boosted, boosts)
            
    asyncio.run(main())