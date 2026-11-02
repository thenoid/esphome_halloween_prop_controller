import asyncio
import logging
import os
import secrets
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import uvicorn
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from collector.app import create_app
from collector.config import Settings
from collector.mcp_bridge import query

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)


class MCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_tools_query_real_http_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            token = secrets.token_urlsafe(32)
            app = create_app(Settings(api_token=token, database=Path(folder) / "events.sqlite3", udp_host="127.0.0.1", udp_port=0))
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
            task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                for _ in range(500):
                    if server.started:
                        break
                    if task.done():
                        await task
                    await asyncio.sleep(.01)
                self.assertTrue(server.started)
                udp_port = app.state.runtime.transport.get_extra_info("sockname")[1]
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                    sender.sendto(b"HC1|prop-controller-3|sequence.ready|2|stopped", ("127.0.0.1", udp_port))
                base = f"http://127.0.0.1:{port}"
                headers = {"Authorization": "Bearer " + token}
                async with httpx.AsyncClient(base_url=base, headers=headers, trust_env=False) as client:
                    for _ in range(100):
                        if (await client.get("/api/v1/status")).json()["stored_events"] == 1:
                            break
                        await asyncio.sleep(.01)
                env = {**os.environ, "COLLECTOR_URL": base, "COLLECTOR_API_TOKEN": token}
                params = StdioServerParameters(command=sys.executable, args=["-m", "collector.mcp_bridge"],
                                               env=env, cwd=str(Path(__file__).resolve().parents[1]))
                async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    self.assertIn("all controllers", initialized.instructions)
                    tools = (await session.list_tools()).tools
                    self.assertEqual({t.name for t in tools}, {"collector_status", "list_controllers", "list_events", "summarize_events"})
                    self.assertTrue(all(t.annotations.readOnlyHint for t in tools))
                    events = await session.call_tool("list_events", {"source": "prop-controller-3", "order": "asc", "after_id": 0})
                    self.assertFalse(events.isError)
                    self.assertEqual(events.structuredContent["events"][0]["reason"], "stopped")
                    self.assertEqual((await session.call_tool("collector_status")).structuredContent["stored_events"], 1)
                    self.assertEqual((await session.call_tool("list_controllers")).structuredContent["controllers"][0]["source"], "prop-controller-3")
                    self.assertEqual((await session.call_tool("summarize_events")).structuredContent["total"], 1)
                    invalid = await session.call_tool("list_events", {"limit": 1001})
                    self.assertTrue(invalid.isError)
                    self.assertNotIn(token, str(invalid))
                with patch.dict(os.environ, {"COLLECTOR_URL": base, "COLLECTOR_API_TOKEN": "wrong"}), self.assertRaisesRegex(ValueError, "HTTP 401"):
                    await query("/api/v1/events")
            finally:
                server.should_exit = True
                await asyncio.wait_for(task, 10)
                listener.close()


if __name__ == "__main__":
    unittest.main()
