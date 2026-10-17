"""Ephemeral server-side records; no tokens are placed in browser cookies."""
import hashlib
import json
import time

from redis.asyncio import Redis


def record_key(kind: str, value: str) -> str:
    return "oakgate:" + kind + ":" + hashlib.sha256(value.encode()).hexdigest()


class MemoryStore:
    """Single-process development only. Restarting logs everyone out."""
    def __init__(self):
        self.records = {}

    async def put(self, key, value, ttl):
        now = time.time()
        self.records = {k: v for k, v in self.records.items() if v[0] > now}
        if len(self.records) >= 10000:
            raise ValueError("Development session capacity exceeded")
        self.records[key] = (now + ttl, value)

    async def get(self, key):
        entry = self.records.get(key)
        if entry is None:
            return None
        if entry[0] <= time.time():
            self.records.pop(key, None)
            return None
        return entry[1]

    async def pop(self, key):
        value = await self.get(key)
        self.records.pop(key, None)
        return value

    async def delete(self, key):
        self.records.pop(key, None)

    async def close(self):
        pass


class RedisStore:
    def __init__(self, url):
        self.client = Redis.from_url(url, decode_responses=True, socket_timeout=3,
                                     socket_connect_timeout=3)

    async def put(self, key, value, ttl):
        await self.client.set(key, json.dumps(value), ex=ttl)

    async def get(self, key):
        value = await self.client.get(key)
        return json.loads(value) if value else None

    async def pop(self, key):
        # Atomically consume state: concurrent/replayed callbacks cannot reuse it.
        value = await self.client.getdel(key)
        return json.loads(value) if value else None

    async def delete(self, key):
        await self.client.delete(key)

    async def close(self):
        await self.client.aclose()
