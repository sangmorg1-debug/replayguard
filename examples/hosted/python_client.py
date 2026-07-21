"""Minimal metadata-only upload. Set REPLAYGUARD_API_KEY first."""
import json
import os
import urllib.request

payload = {"run": {"id": "python-example", "name": "Python agent", "status": "ok", "events": []}}
request = urllib.request.Request("http://127.0.0.1:8787/v1/traces",
    data=json.dumps(payload).encode(), method="POST",
    headers={"Content-Type": "application/json", "X-ReplayGuard-Key": os.environ["REPLAYGUARD_API_KEY"]})
with urllib.request.urlopen(request) as response:
    print(response.read().decode())

