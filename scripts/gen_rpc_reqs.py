"""Generate RPC test requests, one JSON object per line."""
import json, sys
reqs = [
    {"jsonrpc": "2.0", "method": "ping", "params": {}, "id": 1},
    {"jsonrpc": "2.0", "method": "exec_command",
     "params": {"command": "echo hello-sandbox", "cwd": ".", "timeout": 10}, "id": 2},
    {"jsonrpc": "2.0", "method": "nope", "params": {}, "id": 4},
]
sys.stdout.write("".join(json.dumps(r) + "\n" for r in reqs))
