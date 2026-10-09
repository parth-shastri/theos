"""Start the Theos HTTP server and its single scheduler."""

from theos.settings import Settings
from theos.transports.browser.app import create_app as create_app


def main():
    """Start one application worker and scheduler."""
    import uvicorn

    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        workers=1,
        access_log=False,
        timeout_graceful_shutdown=30,
    )


if __name__ == "__main__":
    main()
