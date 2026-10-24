"""Verify the linked Health profile before publishing new account credentials."""

import httpx

from theos.services.errors import ServiceError


async def verify_profile(http, access_token):
    """Use the existing Health scope to verify the selected account's identity."""
    try:
        response = await http.get(
            "https://health.googleapis.com/v4/users/me/identity",
            headers={"Authorization": "Bearer " + access_token},
        )
        if response.status_code in {400, 404}:
            raise ServiceError(
                "This Google account has no accessible Health profile. Open the Google Health app, "
                "complete its profile setup or Fitbit migration, then connect again."
            )
        if response.status_code in {401, 403}:
            raise ServiceError(
                "Google Health access could not be verified. Connect again and grant all requested permissions."
            )
        response.raise_for_status()
        identity = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise ServiceError("Google Health is unavailable. Try connecting again later.") from error
    if (
        not isinstance(identity, dict)
        or not isinstance(identity.get("healthUserId"), str)
        or not identity["healthUserId"].strip()
    ):
        raise ServiceError(
            "This Google account has no linked Health profile. Complete profile setup in the Google Health app, then connect again."
        )
