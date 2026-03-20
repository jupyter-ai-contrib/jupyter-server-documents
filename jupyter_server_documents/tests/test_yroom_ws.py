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

    def test_ping_timeout_less_than_interval(self, mock_server_docs_app):
        handler = self._make_handler(mock_server_docs_app)
        assert handler.ping_timeout < handler.ping_interval
