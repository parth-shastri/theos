"""Deployment OAuth clients for remote account connectors."""

from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, model_validator


class MCPAccountSettings(BaseModel):
    """Each operator supplies a client. Each owner grants their own account access."""

    client_id: str = ""
    client_secret: SecretStr = SecretStr("")
    redirect_uri: str = ""
    scopes: list[str] | None = Field(default=None, max_length=30)

    @property
    def enabled(self):
        return bool(self.client_id)

    @model_validator(mode="after")
    def complete(self):
        values = (self.client_id, self.client_secret.get_secret_value(), self.redirect_uri)
        if any(values) and not all(values):
            raise ValueError("Set the OAuth client ID, secret, and redirect URI together.")
        if self.scopes is not None and any(
            not value or any(c.isspace() for c in value) or "," in value for value in self.scopes
        ):
            raise ValueError("Supply OAuth scopes as separate nonempty values.")
        return self

    def check_callback(self, service):
        if not self.enabled:
            return
        uri = urlsplit(self.redirect_uri)
        if (
            not uri.hostname
            or uri.username
            or uri.password
            or uri.query
            or uri.fragment
            or uri.path != f"/oauth/{service}/callback"
            or not (
                uri.scheme == "https"
                or (uri.scheme == "http" and uri.hostname in {"localhost", "127.0.0.1"})
            )
        ):
            raise ValueError(f"Use an HTTPS /oauth/{service}/callback URI, except on localhost.")
