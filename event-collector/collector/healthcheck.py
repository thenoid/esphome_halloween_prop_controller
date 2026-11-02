import os
from urllib.request import ProxyHandler, build_opener

if __name__ == "__main__":
    host = os.environ.get("COLLECTOR_HTTP_HOST", "0.0.0.0")
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1" if host == "0.0.0.0" else "[::1]"
    elif ":" in host:
        host = f"[{host}]"
    port = int(os.environ.get("COLLECTOR_HTTP_PORT", "8080"))
    with build_opener(ProxyHandler({})).open(f"http://{host}:{port}/healthz", timeout=5) as response:
        if response.status != 200:
            raise SystemExit(1)
