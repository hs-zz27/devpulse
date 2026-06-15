import httpx

async def github_post(client: httpx.AsyncClient, url: str, **kwargs):
    response = await client.post(url, **kwargs)
    response.raise_for_status()
    return response

async def github_get(client: httpx.AsyncClient, url: str, **kwargs):
    response = await client.get(url, **kwargs)
    response.raise_for_status()
    return response
