"""Health consent verifies a linked profile before saving credentials."""

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from theos.services.errors import ServiceError
from theos.services.google.oauth import SCOPES, OAuth

from .test_oauth_gmail_health import configure


@pytest.mark.parametrize(
    "identity_status, identity",
    [(200, {"healthUserId": "linked-profile"}), (200, {}), (404, {}), (503, {})],
)
async def test_health_consent_checks_profile_before_replacing_credentials(
    settings, db, identity_status, identity
):
    configure(settings)
    requests = []

    def endpoint(request):
        requests.append(request)
        if request.url.path == "/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                    "scope": " ".join(SCOPES["health"]),
                },
            )
        assert request.url.path == "/v4/users/me/identity"
        assert request.headers["Authorization"] == "Bearer new-access"
        return httpx.Response(identity_status, json=identity)

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        oauth = OAuth(settings, db, http)
        oauth.save("alice", "health", {"access_token": "previous-access"})
        state = parse_qs(urlsplit(oauth.start("alice", "health")).query)["state"][0]
        if identity.get("healthUserId"):
            assert await oauth.callback("health", state, "one-use") == "alice"
            assert oauth.read("alice", "health")["access_token"] == "new-access"
        else:
            with pytest.raises(ServiceError, match="Health"):
                await oauth.callback("health", state, "one-use")
            assert oauth.read("alice", "health")["access_token"] == "previous-access"
        assert len(requests) == 2
        assert not db.rows("SELECT * FROM oauth_states")
        assert not db.rows("SELECT * FROM sessions")
