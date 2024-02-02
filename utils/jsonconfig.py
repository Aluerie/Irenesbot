"""
Inspired by RoboDanny's `config.py`. So all credit to Danny.
Very educational though.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from json import JSONDecodeError
from typing import TYPE_CHECKING, Any, Generic, TypeVar, override

if TYPE_CHECKING:
    from .database import PoolTypedWithAny

_T = TypeVar("_T")


class Config(Generic[_T]):
    """The 'Database' objects based on `.json` files :D"""

    def __init__(
        self,
        filename: str,
        pool: PoolTypedWithAny | None = None,
        *,
        encoder: type[json.JSONEncoder] | None = None,
    ) -> None:
        self.filename = f".alubot/{filename}"
        self.pool = pool
        self.encoder = encoder
        self.loop = asyncio.get_running_loop()
        self.lock = asyncio.Lock()
        self._json: dict[str, _T | Any] = {}
        if self.load_from_file():
            pass
        elif pool:
            self.loop.create_task(self.load_from_database())
            self.loop.create_task(self.save())

    def load_from_file(self) -> bool:
        try:
            with open(self.filename, encoding="utf-8") as f:  # noqa: PTH123
                self._json = json.load(f)
                return True
        except FileNotFoundError:
            return False
        except JSONDecodeError:
            return False

    async def load_from_database(self) -> None:
        ...

    def _dump(self) -> None:
        temp = f"{self.filename}-{uuid.uuid4()}.tmp"
        with open(temp, "w", encoding="utf-8") as tmp:  # noqa: PTH123
            json.dump(self._json.copy(), tmp, ensure_ascii=True, cls=self.encoder, separators=(",", ":"))
        # atomically move the file
        os.replace(temp, self.filename)  # noqa: PTH105

    async def save(self) -> None:
        async with self.lock:
            await self.loop.run_in_executor(None, self._dump)

    def get(self, key: Any, default: Any = None) -> Any:
        """Retrieves a config entry"""
        return self._json.get(str(key), default)

    async def put_into_database(self, key: Any, value: _T | Any) -> None:
        ...

    async def put(self, key: Any, value: _T | Any) -> None:
        """Edits a config entry"""
        self._json[str(key)] = value
        await self.put_into_database(key, value)
        await self.save()

    async def remove_from_database(self, key: Any) -> None:
        ...

    async def remove(self, key: Any) -> None:
        """Removes a config entry."""
        del self._json[str(key)]
        await self.remove_from_database(key)
        await self.save()

    def __contains__(self, item: Any) -> bool:
        return str(item) in self._json

    def __getitem__(self, item: Any) -> _T | Any:
        return self._json[str(item)]

    def __len__(self) -> int:
        return len(self._json)

    def all(self) -> dict[Any, _T | Any]:
        return self._json


class PrefixConfig(Config[Any]):
    """Prefix Config"""

    if TYPE_CHECKING:
        pool: PoolTypedWithAny

    def __init__(self, pool: PoolTypedWithAny) -> None:
        super().__init__(filename="prefixes.json", pool=pool)

    @override
    async def load_from_database(self) -> None:
        query = "SELECT id, prefix FROM guilds"
        rows = await self.pool.fetch(query) or []
        self._json = {r.id: r.prefix for r in rows if r.prefix is not None}

    @override
    async def put_into_database(self, guild_id: int, new_prefix: str) -> None:
        query = "UPDATE guilds SET prefix=$1 WHERE id=$2"
        await self.pool.execute(query, new_prefix, guild_id)

    @override
    async def remove_from_database(self, guild_id: int) -> None:
        query = "UPDATE guilds SET prefix=NULL WHERE id=$1"
        await self.pool.execute(query, guild_id)
