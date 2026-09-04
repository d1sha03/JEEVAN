"""In-process WebSocket connection manager (role-aware broadcast hub).

Production note: swap broadcast fan-out with the Redis adapter
(publish to `jeevan:events`, subscribers relay to local sockets).
"""
import asyncio
import json

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._conns: list[tuple[WebSocket, str, str]] = []  # (ws, role, user_id)
        self._lock = asyncio.Lock()
        self.main_loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket, role: str, user_id: str) -> None:
        await ws.accept()
        async with self._lock:
            self._conns.append((ws, role, user_id))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._conns = [c for c in self._conns if c[0] is not ws]

    async def _send(self, ws: WebSocket, event: dict) -> bool:
        try:
            await ws.send_text(json.dumps(event))
            return True
        except Exception:
            return False

    async def broadcast(self, event: dict, roles: list[str] | None = None) -> None:
        async with self._lock:
            targets = [c for c in self._conns if roles is None or c[1] in roles]
        dead = []
        for ws, _role, _uid in targets:
            if not await self._send(ws, event):
                dead.append(ws)
        if dead:
            async with self._lock:
                self._conns = [c for c in self._conns if c[0] not in dead]

    def broadcast_threadsafe(self, event: dict, roles: list[str] | None = None) -> None:
        """Safe from sync endpoints / background threads: marshals to main loop."""
        if self.main_loop and self.main_loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(event, roles), self.main_loop)
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.broadcast(event, roles))


manager = ConnectionManager()
