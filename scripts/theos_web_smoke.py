"""Check an independently running Next.js frontend through its private API proxy."""

import argparse
import http.cookiejar
import json
import urllib.error
import urllib.request


def check(base_url, token):
    cookies = http.cookiejar.CookieJar()
    browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))

    def request(path, data=None, *, csrf=True):
        headers = {}
        if data is not None:
            headers["Content-Type"] = "application/json"
            if csrf:
                headers.update({"Origin": base_url, "X-Theos-Request": "1"})
        body = json.dumps(data).encode() if data is not None else None
        return browser.open(
            urllib.request.Request(base_url + path, data=body, headers=headers), timeout=30
        )

    with request("/") as response:
        page = response.read().decode()
        assert "/_next/static/" in page and 'id="composer"' in page
        assert "'unsafe-inline'" not in response.headers["Content-Security-Policy"]
    try:
        request("/api/auth/login", {"token": token}, csrf=False)
    except urllib.error.HTTPError as error:
        assert error.code == 403
    else:
        raise AssertionError("A login without CSRF headers was accepted.")
    with request("/api/auth/login", {"token": token}) as response:
        assert json.load(response) == {"signed_in": True}
        assert "HttpOnly" in response.headers["Set-Cookie"]
    with request("/api/me") as response:
        assert json.load(response)["id"]
    boundary = "theos-upload-boundary"
    payload = b"x" * (10 * 1024 * 1024)
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="boundary.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode()
        + payload
        + f"\r\n--{boundary}--\r\n".encode()
    )
    upload = urllib.request.Request(
        base_url + "/api/files",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Origin": base_url,
            "X-Theos-Request": "1",
        },
    )
    with browser.open(upload, timeout=30) as response:
        uploaded = json.load(response)
        assert uploaded["size"] == len(payload)
    with request("/api/files/" + uploaded["id"]) as response:
        assert "boundary.txt" in response.headers["Content-Disposition"]
        assert response.read() == payload
    with request("/api/sessions", {"title": "Next.js container acceptance"}) as response:
        session = json.load(response)
    with request("/api/sessions/" + session["id"] + "/turn", {"text": "Hello"}) as response:
        assert response.headers["Content-Type"].startswith("text/event-stream")
        assert '"status": "completed"' in response.read().decode()
    with request("/api/auth/logout", {}) as response:
        assert json.load(response)["signed_out"] is True
    try:
        request("/api/me")
    except urllib.error.HTTPError as error:
        assert error.code == 401
    else:
        raise AssertionError("Logout retained browser access.")
    print("Next.js frontend acceptance passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--token", default="container-acceptance-token-123456789")
    args = parser.parse_args()
    check(args.base_url.rstrip("/"), args.token)
