"""Exercise authenticated HTTP chat in a running container without provider credentials."""

import argparse
import json
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--check-restart", action="store_true")
parser.add_argument("--base-url", default="http://127.0.0.1:8080")
args = parser.parse_args()


def request(path, data=None):
    headers = {"Authorization": "Bearer container-acceptance-token-123456789"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    payload = json.dumps(data).encode() if data is not None else None
    with urllib.request.urlopen(
        urllib.request.Request(args.base_url + path, data=payload, headers=headers), timeout=30
    ) as response:
        return response.read().decode()


assert json.loads(request("/ready"))["status"] == "ready"
if args.check_restart:
    sessions = json.loads(request("/api/sessions"))
    assert sessions
    history = json.loads(request("/api/sessions/" + sessions[0]["id"]))["history"]
    assert len(history) >= 2
else:
    session = json.loads(request("/api/sessions", {"title": "Container acceptance"}))
    response = request("/api/sessions/" + session["id"] + "/turn", {"text": "Hello"})
    assert '"type": "text"' in response
    assert '"status": "completed"' in response
print("Container acceptance passed.")
