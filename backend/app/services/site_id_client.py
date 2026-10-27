import httpx

from app.config import config

SITE_ID_API = config("SITE_ID_API", default="http://localhost:8800")


async def lookup_site(subnet: str) -> dict:
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.get(f"{SITE_ID_API}/site-id", params={"subnet": subnet})
        response.raise_for_status()
        return response.json()
