from unittest.mock import MagicMock

from tornado.httputil import HTTPServerRequest

from jupyter_server_documents.websockets import YRoomWebsocket


class TestYRoomWebsocket:
    def _make_handler(self, mock_server_docs_app):
        app = mock_server_docs_app.serverapp.web_app
        conn = MagicMock()
        request = HTTPServerRequest(
            method="GET",
            uri="/api/collaboration/room/test",
            connection=conn,
        )
        return YRoomWebsocket(app, request)

    def test_ping_interval_is_set(self, mock_server_docs_app):
        handler = self._make_handler(mock_server_docs_app)
        assert isinstance(handler.ping_interval, (int, float))
        assert 0 < handler.ping_interval < 30

    def test_ping_timeout_is_set(self, mock_server_docs_app):
        handler = self._make_handler(mock_server_docs_app)
        assert isinstance(handler.ping_timeout, (int, float))
        assert 0 < handler.ping_timeout < 30

    def test_ping_timeout_not_greater_than_ping_interval(self, mock_server_docs_app):
        handler = self._make_handler(mock_server_docs_app)
        assert handler.ping_timeout <= handler.ping_interval

    def test_check_origin_allows_any_origin(self, mock_server_docs_app):
        """
        check_origin() must always return True. Tornado's default
        implementation enforces strict same-origin (Origin == Host), which
        403s every room websocket behind a reverse proxy that doesn't
        preserve the Host header. The actual security check is deferred to
        authentication in get() instead, mirroring
        jupyter_server_ydoc.YDocWebSocketHandler.
        """
        handler = self._make_handler(mock_server_docs_app)
        assert handler.check_origin("https://an-entirely-different-origin.example.com") is True
        assert handler.check_origin(None) is True
