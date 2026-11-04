"""Linux-only smoke test for a previously built Docker image; uses disposable data."""
import json
import os
import secrets
import socket
import subprocess
import time
import uuid
from urllib.request import ProxyHandler, Request, build_opener


def docker(*args):
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout.strip()


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    name = "collector-test-" + uuid.uuid4().hex
    volume = name + "-data"
    http_port, udp_port = free_port(socket.SOCK_STREAM), free_port(socket.SOCK_DGRAM)
    token = secrets.token_urlsafe(32)
    os.environ["COLLECTOR_API_TOKEN"] = token
    opener = build_opener(ProxyHandler({}))

    def request(path):
        req = Request(f"http://127.0.0.1:{http_port}" + path, headers={"Authorization": "Bearer " + token})
        with opener.open(req, timeout=3) as response:
            return json.load(response)

    def wait_ready():
        for _ in range(100):
            try:
                if request("/healthz")["status"] == "ok":
                    return
            except OSError:
                pass
            time.sleep(.1)
        raise AssertionError("Container did not become healthy")

    try:
        docker("volume", "create", volume)
        docker("run", "-d", "--name", name, "--network", "host", "--read-only", "--cap-drop=ALL",
               "--security-opt=no-new-privileges:true", "--tmpfs", "/tmp", "-v", volume + ":/data",
               "-e", "COLLECTOR_API_TOKEN", "-e", "COLLECTOR_HTTP_HOST=127.0.0.1",
               "-e", "COLLECTOR_UDP_HOST=0.0.0.0", "-e", f"COLLECTOR_HTTP_PORT={http_port}",
               "-e", f"COLLECTOR_UDP_PORT={udp_port}", "controller-event-collector:test")
        wait_ready()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.bind(("127.0.0.1", 0))
            sender.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for item in range(1, 4):
                # The entire 127/8 range is loopback; nothing reaches the prop LAN.
                sender.sendto(f"HC1|prop-controller-{item}|sequence.started|1|".encode(), ("127.255.255.255", udp_port))
        for _ in range(100):
            if request("/api/v1/status")["stored_events"] == 3:
                break
            time.sleep(.1)
        assert len(request("/api/v1/controllers")["controllers"]) == 3
        docker("exec", name, "python", "-m", "collector.healthcheck")
        assert docker("exec", name, "id", "-u") == "10001"
        docker("exec", name, "python", "-c",
               "import importlib.util, shutil, sys; "
               "assert sys.prefix == '/app/.venv'; "
               "assert importlib.util.find_spec('yaml') is None; "
               "assert shutil.which('uv') is None")
        docker("restart", "-t", "60", name)
        wait_ready()
        assert request("/api/v1/status")["stored_events"] == 3
        print("Docker smoke test passed: loopback broadcast, API, non-root, healthcheck, runtime-only virtual environment and persistent volume.")
    except BaseException:
        logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
        print(logs.stdout + logs.stderr)
        raise
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "volume", "rm", volume], capture_output=True)


if __name__ == "__main__":
    main()
