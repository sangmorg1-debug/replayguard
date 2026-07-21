import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        print(json.dumps({"jsonrpc":"2.0","id":message["id"],"result":{"protocolVersion":"2025-11-25","capabilities":{"tools":{}},"serverInfo":{"name":"fixture","version":"1"}}}), flush=True)
    elif method == "tools/list":
        print(json.dumps({"jsonrpc":"2.0","id":message["id"],"result":{"tools":[{"name":"fixture.read","description":"Read fixture","inputSchema":{"type":"object","properties":{},"additionalProperties":False},"annotations":{"readOnlyHint":True,"destructiveHint":False}}]}}), flush=True)
    elif method == "tools/call":
        print(json.dumps({"jsonrpc":"2.0","id":message["id"],"error":{"code":-32000,"message":"SCANNER_CALLED_TOOL"}}), flush=True)

