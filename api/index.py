"""Vercel Python entrypoint."""

from newsie.web.app import app

# Vercel Python ASGI discovers `app`
__all__ = ["app"]
