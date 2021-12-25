import aiohttp
import logging
from lavaplayer.exceptions import NodeError
from .objects import (
    Info, 
    PlayerUpdate,
    TrackStartEvent, 
    TrackEndEvent, 
    TrackExceptionEvent, 
    TrackStuckEvent,
    WebSocketClosedEvent,
)
from .emitter import Emitter
import typing

if typing.TYPE_CHECKING:
    from .client import LavalinkClient

class WS:
    def __init__(
        self,
        client: "LavalinkClient",
        host: str,
        port: int,
        is_ssl: bool = False,
    ) -> None:
        self.ws = None
        self.ws_url = f"{'wss' if is_ssl else 'ws'}://{host}:{port}"
        self.client = client
        self._headers = client._headers
        self._loop = client._loop
        self.emitter: Emitter = client.event_manger
    
    async def _connect(self):
        async with aiohttp.ClientSession(headers=self._headers, loop=self._loop) as session:
            self.client.session = session
            self.session = session
            self.ws = await self.session.ws_connect(self.ws_url)
            logging.info("lavalink is connection")
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self.callback(msg.json())
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logging.error("close")
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logging.error(msg.data)
                    break

    async def callback(self, pyload: dict):
        if pyload["op"] == "stats":
            self.client.info = Info(
                playingPlayers=pyload["playingPlayers"],
                memory_used=pyload["memory"]["used"],
                memory_free=pyload["memory"]["free"],
                players=pyload["players"],
                uptime=pyload["uptime"]
            )

        elif pyload["op"] == "playerUpdate":
            data = PlayerUpdate(
                guild_id=pyload["guildId"],
                time=pyload["state"]["time"],
                position=pyload["state"].get("position"),
                connected=pyload["state"]["connected"],
            )
            self.emitter.emit("playerUpdate", data)

        elif pyload["op"] == "event":

            if not pyload.get("track"):
                return
            track = await self.client._decodetrack(pyload["track"])
            guild_id = int(pyload["guildId"])
            try:
                node = await self.client.get_guild_node(guild_id)
            except NodeError:
                node = None

            if pyload["type"] == "TrackStartEvent":
                self.emitter.emit("TrackStartEvent", TrackStartEvent(track, guild_id))

            elif pyload["type"] == "TrackEndEvent":
                self.emitter.emit("TrackEndEvent", TrackEndEvent(track, guild_id, pyload["reason"]))
                if not node:
                    return
                if not node.queue:
                    return
                if node.repeat:
                    await self.client.play(guild_id, track, node.queue[0].requester, True)
                    return
                del node.queue[0]
                await self.client.set_guild_node(guild_id, node)
                if len(node.queue) != 0:
                    await self.client.play(guild_id, node.queue[0], node.queue[0].requester, True)

            elif pyload["type"] == "TrackExceptionEvent":
                print(pyload)
                self.emitter.emit("TrackExceptionEvent", TrackExceptionEvent(track, guild_id, pyload["exception"], pyload["message"], pyload["severity"], pyload["cause"]))

            elif pyload["type"] == "TrackStuckEvent":
                self.emitter.emit("TrackStuckEvent", TrackStuckEvent(track, guild_id, pyload["thresholdMs"]))

            elif pyload["type"] == "WebSocketClosedEvent":
                self.emitter.emit("WebSocketClosedEvent", WebSocketClosedEvent(track, guild_id, pyload["code"], pyload["reason"], pyload["byRemote"]))

    async def send(self, pyload):  # only dict
        await self.ws.send_json(pyload)        
