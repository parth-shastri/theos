"""Errors shared by workspace lifecycle and tool handling."""

from theos.services.errors import ServiceError


class WorkspaceUnavailable(ServiceError):
    """The workspace could not be reached before an operation began."""
