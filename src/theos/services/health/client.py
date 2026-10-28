"""Google Health authentication and service entry points."""


class Health:
    """Own the Google Health client and expose its service workflows."""

    def __init__(self, oauth, settings, db, http):
        self.oauth = oauth
        self.settings = settings
        self.db = db
        self.http = http

    async def request(self, owner, method, path, allow_missing=False, **kwargs):
        """Call Google Health with the selected owner token."""
        token = await self.oauth.access_token(owner, "health")
        response = await self.http.request(
            method,
            "https://health.googleapis.com/v4/" + path,
            headers={"Authorization": "Bearer " + token},
            **kwargs,
        )
        if allow_missing and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json() if response.content else {}

    async def import_summary(self, owner, start_date=None, end_date=None, *, save=True):
        """Import a bounded date range into complete daily summaries."""
        from .imports import import_summary

        return await import_summary(self, owner, start_date, end_date, save=save)

    async def read_summary(self, owner, start_date=None, end_date=None, *, refresh=False):
        """Read the requested summary and refresh caches that predate vitals support."""
        from .imports import read_summary

        return await read_summary(self, owner, start_date, end_date, refresh=refresh)

    def backfill(self, owner):
        """Queue saved meals that have no export marker."""
        from .nutrition import backfill

        return backfill(self, owner)

    async def export(self, job):
        """Advance one export. A remote read resolves uncertain creates and deletes."""
        from .nutrition import export

        return await export(self, job)

    async def tick(self):
        """Run bounded background work from the application's single scheduler."""
        from .jobs import tick

        return await tick(self)

    def tools(self, owner, *, result_stager=None):
        """Build tools bound to the authenticated owner."""
        from .tools import health_tools

        return health_tools(self, owner, result_stager=result_stager)
