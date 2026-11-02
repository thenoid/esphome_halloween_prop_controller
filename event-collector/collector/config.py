import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    api_token: str = field(repr=False)
    database: Path = Path("/data/events.sqlite3")
    udp_host: str = "0.0.0.0"
    udp_port: int = 18512
    retention_days: int = 90
    queue_size: int = 4096

    def __post_init__(self):
        if len(self.api_token) < 32 or not self.api_token.isascii() or any(c.isspace() for c in self.api_token):
            raise ValueError("COLLECTOR_API_TOKEN must contain at least 32 non-whitespace ASCII characters")
        if not 0 <= self.udp_port <= 65535:
            raise ValueError("COLLECTOR_UDP_PORT must be between 0 and 65535")
        if self.retention_days < 0 or self.queue_size < 1:
            raise ValueError("Retention must be nonnegative and queue size positive")

    @classmethod
    def from_env(cls):
        return cls(
            api_token=os.environ.get("COLLECTOR_API_TOKEN", ""),
            database=Path(os.environ.get("COLLECTOR_DATABASE", "/data/events.sqlite3")),
            udp_host=os.environ.get("COLLECTOR_UDP_HOST", "0.0.0.0"),
            udp_port=int(os.environ.get("COLLECTOR_UDP_PORT", "18512")),
            retention_days=int(os.environ.get("COLLECTOR_RETENTION_DAYS", "90")),
            queue_size=int(os.environ.get("COLLECTOR_QUEUE_SIZE", "4096")),
        )
