import os

import uvicorn

if __name__ == "__main__":
    # Exactly one worker: every worker would otherwise bind the same UDP socket.
    uvicorn.run("collector.app:app", host=os.environ.get("COLLECTOR_HTTP_HOST", "0.0.0.0"),
                port=int(os.environ.get("COLLECTOR_HTTP_PORT", "8080")), workers=1,
                proxy_headers=False, access_log=False, timeout_graceful_shutdown=25)
