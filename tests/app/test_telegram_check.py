"""Verify safe release checks without Telegram messages, updates, or credentials in errors."""

import httpx
import pytest

from theos.operations.telegram_check import TelegramCheckError, check_telegram, main

TOKEN = "123456:private-test-token"


def test_authentication_and_polling_check_never_reads_updates():
    methods = []

    def respond(request):
        methods.append(request.url.path.rsplit("/", 1)[1])
        assert request.method == "GET"
        result = {"id": 123456, "is_bot": True} if methods[-1] == "getMe" else {"url": ""}
        return httpx.Response(200, json={"ok": True, "result": result})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert check_telegram(TOKEN, client)
    assert methods == ["getMe", "getWebhookInfo"]


def test_disabled_telegram_never_contacts_api():
    def unexpected(request):
        pytest.fail("A disabled bot must not contact Telegram")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        assert not check_telegram("", client)


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_failure_hides_token_and_response_body(status):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, text=TOKEN))
    ) as client:
        with pytest.raises(TelegramCheckError) as error:
            check_telegram(TOKEN, client)
    assert TOKEN not in str(error.value)
    assert error.value.__suppress_context__
    if status in {401, 403}:
        assert "BotFather" in str(error.value)
    else:
        assert f"HTTP {status}" in str(error.value)


def test_network_failure_hides_credential_url():
    def offline(request):
        raise httpx.ConnectError(str(request.url), request=request)

    with httpx.Client(transport=httpx.MockTransport(offline)) as client:
        with pytest.raises(TelegramCheckError, match="outbound HTTPS") as error:
            check_telegram(TOKEN, client)
    assert TOKEN not in str(error.value)


def test_webhook_conflict_is_rejected_without_changing_it():
    methods = []

    def respond(request):
        method = request.url.path.rsplit("/", 1)[1]
        methods.append(method)
        result = {"id": 123456, "is_bot": True} if method == "getMe" else {"url": TOKEN}
        return httpx.Response(200, json={"ok": True, "result": result})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(TelegramCheckError, match="active webhook") as error:
            check_telegram(TOKEN, client)
    assert TOKEN not in str(error.value)
    assert methods == ["getMe", "getWebhookInfo"]


@pytest.mark.parametrize(
    "body", [[], {"ok": False}, {"ok": True, "result": []}, {"ok": True, "result": {}}]
)
def test_invalid_response_fails_closed(body):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    ) as client:
        with pytest.raises(TelegramCheckError, match="invalid"):
            check_telegram(TOKEN, client)


def test_cli_reads_selected_env_and_does_not_print_token(tmp_path, monkeypatch, capsys):
    environment = tmp_path / ".env.pi"
    environment.write_text(f"AGENT_TELEGRAM_TOKEN='{TOKEN}'\n")
    monkeypatch.setenv("AGENT_TELEGRAM_TOKEN", "different-token")
    monkeypatch.setattr("sys.argv", ["telegram-check", "--env-file", str(environment)])

    def rejected(self, url, **kwargs):
        assert TOKEN in url
        request = httpx.Request("GET", url)
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError(TOKEN, request=request, response=response)

    monkeypatch.setattr(httpx.Client, "get", rejected)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    output = capsys.readouterr()
    assert TOKEN not in output.out + output.err
    assert "BotFather" in output.err


def test_invalid_token_format_never_builds_credential_url():
    with httpx.Client() as client:
        with pytest.raises(TelegramCheckError, match="invalid format"):
            check_telegram("123:secret\ninvalid", client)
