"""Local web interface. Binds 127.0.0.1 only."""

from .server import WebServer, find_frontend, serve

__all__ = ["WebServer", "serve", "find_frontend"]
