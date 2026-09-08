"""MTProto multi-connection sender pool for high-throughput chunk fetching."""

import asyncio
import copy
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from telethon import TelegramClient, errors, functions
from telethon.crypto import AuthKey
from telethon.network import MTProtoSender
from telethon.tl.alltlobjects import LAYER

from tg_downloader.core.errors import DownloadError, RateLimitError
from tg_downloader.engine.dc_storage import DCKeyStorage
from tg_downloader.utils.formatting import format_duration

logger = logging.getLogger(__name__)


async def wait_for_dc_cooldown(
    wait_seconds: int,
    dc_id: int,
    console: Console | None = None,
) -> None:
    """Render a visual countdown progress bar while waiting for Telegram DC cooldown to elapse."""
    c = console or Console()
    c.print(
        f"\n[bold yellow]⏳ Telegram rate limit active on DC {dc_id} (ExportAuthorization FloodWait).[/]\n"
        f"[cyan]Waiting {format_duration(wait_seconds)} before resuming automatically...[/]"
    )
    with Progress(
        SpinnerColumn(spinner_name="dots"),
        TextColumn("[bold yellow]Cooldown DC {task.fields[dc_id]}:"),
        BarColumn(bar_width=30, complete_style="yellow", finished_style="green"),
        TextColumn("[bold cyan]{task.fields[remaining_str]} remaining"),
        console=c,
        transient=True,
    ) as p:
        task_id = p.add_task(
            "cooldown",
            total=wait_seconds,
            completed=0,
            dc_id=dc_id,
            remaining_str=format_duration(wait_seconds),
        )
        end_time = time.time() + wait_seconds
        while True:
            remaining = max(0, int(end_time - time.time()))
            if remaining <= 0:
                p.update(task_id, completed=wait_seconds, remaining_str="00:00")
                break
            completed = wait_seconds - remaining
            p.update(
                task_id,
                completed=completed,
                remaining_str=format_duration(remaining),
            )
            await asyncio.sleep(min(1.0, max(0.1, remaining)))

    c.print(f"[bold green]✓ Cooldown for DC {dc_id} completed! Resuming download...[/]\n")


class MTProtoSenderPool:
    """Manages a pool of MTProtoSender connections to a target DC for parallel chunk downloads."""

    def __init__(
        self,
        client: TelegramClient,
        dc_id: int | None,
        max_connections: int = 4,
        max_flood_sleep: int = 3600,
        session_path: Path | None = None,
        auto_wait: bool = True,
        console: Console | None = None,
    ) -> None:
        self.client = client
        client_dc = getattr(client.session, "dc_id", 1) if client.session else 1
        self.client_dc = client_dc
        self.dc_id = dc_id or client_dc
        self.max_connections = max(1, min(max_connections, 16))
        self.max_flood_sleep = max_flood_sleep
        self.session_path = session_path
        self.auto_wait = auto_wait
        self.console = console or Console()
        self._is_home_dc = self.dc_id == client_dc
        self._senders: list[MTProtoSender] = []
        self._sender_queue: asyncio.Queue[MTProtoSender] = asyncio.Queue()
        self._home_semaphore = asyncio.Semaphore(self.max_connections)
        self._initialized = False
        self._lock = asyncio.Lock()
        self._flood_until: float = 0.0

    async def _try_connect_with_key(self, auth_key: AuthKey) -> MTProtoSender | None:
        """Attempt to connect an MTProtoSender using a previously saved AuthKey."""
        try:
            dc = await self.client._get_dc(self.dc_id)
            sender = MTProtoSender(auth_key, loggers=self.client._log)
            await sender.connect(
                self.client._connection(
                    dc.ip_address,
                    dc.port,
                    dc.id,
                    loggers=self.client._log,
                    proxy=self.client._proxy,
                    local_addr=self.client._local_addr,
                )
            )
            # Verify connectivity on target DC
            init_req = copy.copy(self.client._init_request)
            init_req.query = functions.help.GetNearestDcRequest()
            req = functions.InvokeWithLayerRequest(LAYER, init_req)
            await sender.send(req)
            logger.info("Successfully connected to DC %d using saved auth key.", self.dc_id)
            return sender
        except (errors.AuthKeyUnregisteredError, errors.AuthKeyInvalidError) as inv_err:
            logger.warning("Saved auth key for DC %d invalidated: %s", self.dc_id, inv_err)
            if self.session_path:
                DCKeyStorage.remove_key(self.session_path, self.dc_id, auth_key)
            return None
        except Exception as e:
            logger.debug("Failed to connect with saved key for DC %d: %s", self.dc_id, e)
            return None

    async def initialize(self) -> None:
        """Initialize connection pool to target DC with persistent key reuse and auto-wait."""
        async with self._lock:
            if self._initialized:
                return

            if self._is_home_dc:
                logger.debug(
                    "Target file is on Home DC %d: pipelining via primary sender with concurrency %d",
                    self.dc_id,
                    self.max_connections,
                )
                self._initialized = True
                return

            logger.info(
                "Connecting MTProto sender pool: up to %d parallel connections to DC %d...",
                self.max_connections,
                self.dc_id,
            )

            # Step 1: Check for persistent on-disk keys
            saved_keys = DCKeyStorage.load_keys(self.session_path, self.dc_id)
            for key in saved_keys:
                if len(self._senders) >= self.max_connections:
                    break
                sender = await self._try_connect_with_key(key)
                if sender:
                    self._senders.append(sender)

            # Step 2: If no saved keys connected, export authorization
            while not self._senders:
                now = time.time()
                if now < self._flood_until:
                    remaining = int(self._flood_until - now)
                    if self.auto_wait and remaining <= self.max_flood_sleep:
                        await wait_for_dc_cooldown(remaining, self.dc_id, console=self.console)
                        self._flood_until = 0.0
                    else:
                        raise RateLimitError(
                            f"DC {self.dc_id} is temporarily rate-limited by Telegram (FloodWait: {remaining}s remaining)."
                        )

                try:
                    primary = await self.client._borrow_exported_sender(self.dc_id)
                    self._senders.append(primary)
                    if self.session_path and getattr(primary, "auth_key", None):
                        DCKeyStorage.save_key(self.session_path, self.dc_id, primary.auth_key)
                    logger.debug("Acquired primary exported sender for DC %d", self.dc_id)
                    break
                except (errors.FloodWaitError, errors.FloodPremiumWaitError) as flood_err:
                    self._flood_until = time.time() + flood_err.seconds
                    logger.warning(
                        "FloodWait when exporting authorization to DC %d: required wait %ds.",
                        self.dc_id,
                        flood_err.seconds,
                    )
                    if self.auto_wait and flood_err.seconds <= self.max_flood_sleep:
                        await wait_for_dc_cooldown(
                            flood_err.seconds, self.dc_id, console=self.console
                        )
                        self._flood_until = 0.0
                        continue
                    raise RateLimitError(
                        f"Telegram FloodWait {flood_err.seconds}s required for DC {self.dc_id} export authorization."
                    ) from flood_err
                except Exception as e:
                    logger.warning("Failed to export authorization for DC %d: %s", self.dc_id, e)
                    raise DownloadError(
                        f"Unable to establish MTProto connection to DC {self.dc_id}: {e}"
                    ) from e

            # Step 3: Establish additional connections for parallel chunk throughput
            for i in range(len(self._senders), self.max_connections):
                try:
                    sender = await self.client._create_exported_sender(self.dc_id)
                    self._senders.append(sender)
                    if self.session_path and getattr(sender, "auth_key", None):
                        DCKeyStorage.save_key(self.session_path, self.dc_id, sender.auth_key)
                    logger.debug(
                        "Initialized additional exported sender %d/%d to DC %d",
                        i + 1,
                        self.max_connections,
                        self.dc_id,
                    )
                except (errors.FloodWaitError, errors.FloodPremiumWaitError) as flood_err:
                    self._flood_until = time.time() + flood_err.seconds
                    logger.warning(
                        "FloodWait when creating extra connection %d to DC %d (wait %ds). "
                        "Continuing with %d active sender(s).",
                        i + 1,
                        self.dc_id,
                        flood_err.seconds,
                        len(self._senders),
                    )
                    break
                except Exception as e:
                    logger.warning(
                        "Failed to initialize extra sender %d to DC %d: %s. Continuing with %d active sender(s).",
                        i + 1,
                        self.dc_id,
                        e,
                        len(self._senders),
                    )
                    break

            if not self._senders:
                raise DownloadError(
                    f"No active MTProto connections could be established to DC {self.dc_id}."
                )

            # Distribute max_connections tokens across active senders for maximum concurrency
            for idx in range(self.max_connections):
                sender = self._senders[idx % len(self._senders)]
                await self._sender_queue.put(sender)

            self._initialized = True

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        """Borrow a connected sender from the pool, returning it upon completion."""
        if not self._initialized:
            await self.initialize()

        if self._is_home_dc:
            async with self._home_semaphore:
                yield self.client._sender
        else:
            sender = await self._sender_queue.get()
            try:
                # Reconnect socket if it dropped while idle
                if hasattr(sender, "is_connected") and not sender.is_connected():
                    logger.debug("Reconnecting idle sender to DC %d...", self.dc_id)
                    dc = await self.client._get_dc(self.dc_id)
                    await sender.connect(
                        self.client._connection(
                            dc.ip_address,
                            dc.port,
                            dc.id,
                            loggers=self.client._log,
                            proxy=self.client._proxy,
                            local_addr=self.client._local_addr,
                        )
                    )
                yield sender
            finally:
                await self._sender_queue.put(sender)

    async def close(self) -> None:
        """Disconnect and cleanup all exported senders in the pool."""
        async with self._lock:
            # Drain queue
            while not self._sender_queue.empty():
                try:
                    self._sender_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

            # Disconnect senders
            for idx, sender in enumerate(self._senders):
                try:
                    if idx == 0 and hasattr(self.client, "_return_exported_sender"):
                        with suppress(Exception):
                            await self.client._return_exported_sender(sender)
                    await sender.disconnect()
                except Exception as e:
                    logger.debug("Error disconnecting sender: %s", e)

            self._senders.clear()
            self._initialized = False
