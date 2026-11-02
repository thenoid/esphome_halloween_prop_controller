import asyncio
import logging
from contextlib import suppress
from dataclasses import asdict, dataclass

from .config import Settings
from .protocol import decode
from .store import Store, utc_now

LOG = logging.getLogger(__name__)


@dataclass
class Counters:
    packets_received: int = 0
    invalid_packets: int = 0
    queue_overflows: int = 0
    events_written: int = 0
    write_errors: int = 0
    udp_errors: int = 0
    events_purged: int = 0


class Receiver(asyncio.DatagramProtocol):
    def __init__(self, runtime):
        self.runtime = runtime

    def connection_made(self, transport):
        self.runtime.udp_listening = True

    def connection_lost(self, exc):
        self.runtime.udp_listening = False

    def error_received(self, exc):
        self.runtime.counters.udp_errors += 1
        LOG.warning("UDP receive error: %s", type(exc).__name__)

    def datagram_received(self, data, addr):
        state = self.runtime
        state.counters.packets_received += 1
        state.last_packet_at = utc_now()
        try:
            event = decode(data)
        except ValueError:
            state.counters.invalid_packets += 1
            return
        try:
            state.queue.put_nowait((event, state.last_packet_at, addr))
        except asyncio.QueueFull:
            state.counters.queue_overflows += 1


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = Store(settings.database)
        self.queue = asyncio.Queue(maxsize=settings.queue_size)
        self.counters = Counters()
        self.started_at = utc_now()
        self.last_packet_at = None
        self.last_event_at = None
        self.storage_error = None
        self.retention_error = None
        self.udp_listening = False
        self.transport = None
        self.writer = None
        self.cleaner = None

    async def start(self):
        try:
            self.counters.events_purged += await asyncio.to_thread(self.store.purge, self.settings.retention_days)
            self.transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
                lambda: Receiver(self), local_addr=(self.settings.udp_host, self.settings.udp_port),
            )
            self.writer = asyncio.create_task(self.write_loop())
            self.cleaner = asyncio.create_task(self.retention_loop())
        except BaseException:
            self.store.close()
            raise

    async def stop(self):
        if self.transport:
            self.transport.close()
            await asyncio.sleep(0)
        if self.cleaner:
            self.cleaner.cancel()
            with suppress(asyncio.CancelledError):
                await self.cleaner
        # Stop accepting packets first, then commit all queued events before exit.
        await self.queue.join()
        if self.writer:
            self.writer.cancel()
            with suppress(asyncio.CancelledError):
                await self.writer
        await asyncio.to_thread(self.store.close)

    async def write_loop(self):
        while True:
            event, received_at, sender = await self.queue.get()
            try:
                await asyncio.to_thread(self.store.insert, event, received_at, sender)
                self.counters.events_written += 1
                self.last_event_at = received_at
                self.storage_error = None
            except Exception as exc:
                self.counters.write_errors += 1
                self.storage_error = type(exc).__name__
                LOG.error("Event could not be stored: %s", self.storage_error)
            finally:
                self.queue.task_done()

    async def retention_loop(self):
        while True:
            await asyncio.sleep(3600)
            try:
                self.counters.events_purged += await asyncio.to_thread(self.store.purge, self.settings.retention_days)
                self.retention_error = None
            except Exception as exc:
                self.retention_error = type(exc).__name__
                LOG.error("Retention failed: %s", self.retention_error)

    def healthy(self):
        return self.udp_listening and self.writer is not None and not self.writer.done() and not (
            self.storage_error or self.retention_error
        )

    def status(self):
        return {
            "started_at": self.started_at, "udp_listening": self.udp_listening,
            "udp_port": self.transport.get_extra_info("sockname")[1] if self.transport else None,
            "queue_depth": self.queue.qsize(), "queue_capacity": self.settings.queue_size,
            "last_packet_at": self.last_packet_at, "last_event_at": self.last_event_at,
            "storage_error": self.storage_error, "retention_error": self.retention_error,
            "retention_days": self.settings.retention_days, "counters": asdict(self.counters),
        }
