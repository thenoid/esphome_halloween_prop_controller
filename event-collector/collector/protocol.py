"""Wire rules mirror packages/controller-events.h. HC1 is a version, not a device."""
import re
from dataclasses import dataclass

EVENT_TYPES = (
    "sensor.triggered", "sensor.released", "sequence.started",
    "sequence.cooling_down", "sequence.ready",
)
MAX_PACKET_SIZE = 128


@dataclass(frozen=True)
class Event:
    source: str
    event: str
    item: int
    reason: str
    raw_packet: str


def decode(packet: bytes) -> Event:
    if len(packet) > MAX_PACKET_SIZE:
        raise ValueError("Packet too large")
    try:
        raw = packet.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("Non-ASCII packet") from exc
    fields = raw.split("|")
    if len(fields) != 5 or fields[0] != "HC1":
        raise ValueError("Unsupported packet format")
    _, source, event, item, reason = fields
    if re.fullmatch(r"[a-z0-9-]{1,63}", source) is None or item not in ("1", "2", "3", "4"):
        raise ValueError("Invalid source or item")
    if event not in EVENT_TYPES or (
        reason not in ("cooldown_finished", "stopped") if event == "sequence.ready" else reason != ""
    ):
        raise ValueError("Invalid event or reason")
    return Event(source, event, int(item), reason, raw)
