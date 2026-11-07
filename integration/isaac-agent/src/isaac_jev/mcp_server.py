from __future__ import annotations

import json
import sys
from typing import Any

from .runtime import BridgeRuntime


TOOLS = [
    {"name": "autopilot_status", "description": "Read local controller and game-connection status.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "autopilot_enable", "description": "Allow the local Lua mod to override input.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "autopilot_disable", "description": "Return all input to the local player.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "emergency_stop", "description": "Disable the autopilot immediately.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "latest_state", "description": "Read the latest received frame number and selected action.", "inputSchema": {"type": "object", "properties": {}}},
]


def _result(request_id: Any, payload: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _tool_result(status: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(status, ensure_ascii=False)}]}


def main() -> None:
    runtime = BridgeRuntime()
    runtime.start()
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                method = request.get("method")
                request_id = request.get("id")
                if method == "initialize":
                    response = _result(request_id, {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "isaac-jev", "version": "0.1.0"}})
                elif method == "tools/list":
                    response = _result(request_id, {"tools": TOOLS})
                elif method == "tools/call":
                    name = request.get("params", {}).get("name")
                    if name == "autopilot_enable":
                        status = runtime.controller.set_autopilot(True)
                    elif name in {"autopilot_disable", "emergency_stop"}:
                        status = runtime.controller.set_autopilot(False)
                    elif name in {"autopilot_status", "latest_state"}:
                        status = runtime.controller.status()
                    else:
                        response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
                        print(json.dumps(response), flush=True)
                        continue
                    response = _result(request_id, _tool_result(status))
                elif request_id is None:
                    continue
                else:
                    response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}
                print(json.dumps(response), flush=True)
            except json.JSONDecodeError:
                continue
    finally:
        runtime.stop()
