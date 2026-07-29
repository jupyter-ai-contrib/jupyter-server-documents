from unittest.mock import MagicMock

from tornado.httputil import HTTPHeaders, HTTPServerRequest

from jupyter_server_documents.websockets import YRoomWebsocket


class TestYRoomWebsocket:
    def _make_handler(self, mock_server_docs_app, headers=None):
        app = mock_server_docs_app.serverapp.web_app
        conn = MagicMock()
        request = HTTPServerRequest(
            method="GET",
            uri="/api/collaboration/room/test",
            headers=HTTPHeaders(headers or {}),
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

    def test_check_origin_honors_wildcard_allow_origin(self, mock_server_docs_app):
        """
        With ``allow_origin='*'`` a room websocket is accepted regardless of the
        request's Origin. This is what unblocks JupyterLab behind a reverse proxy
        that doesn't preserve the Host header (Origin != Host at the backend);
        bare Tornado's default check_origin 403s it. check_origin delegates to
        JupyterHandler.check_origin (not Tornado's, which precedes it in the MRO),
        mirroring jupyter_server_ydoc.YDocWebSocketHandler.
        """
        handler = self._make_handler(
            mock_server_docs_app,
            headers={"Host": "backend:8888", "Origin": "https://proxy.example.com"},
        )
        handler.settings["allow_origin"] = "*"
        assert handler.check_origin("https://proxy.example.com") is True

    def test_check_origin_honors_explicit_allow_origin(self, mock_server_docs_app):
        """
        A configured ``allow_origin`` is honored: the matching origin is allowed
        and an untrusted cross-origin request is still blocked. This is the
        security property a blanket ``return True`` would break -- e.g. for
        deployments that embed JupyterLab in an iframe with SameSite=None cookies.
        """
        # Force the origin check to actually run (i.e. don't skip it as a
        # token-authenticated request would).
        idp = MagicMock()
        idp.should_check_origin.return_value = True

        allowed = self._make_handler(
            mock_server_docs_app,
            headers={"Host": "backend:8888", "Origin": "https://proxy.example.com"},
        )
        allowed.settings["allow_origin"] = "https://proxy.example.com"
        allowed.settings["identity_provider"] = idp
        assert allowed.check_origin("https://proxy.example.com") is True

        blocked = self._make_handler(
            mock_server_docs_app,
            headers={"Host": "backend:8888", "Origin": "https://evil.example.com"},
        )
        blocked.settings["allow_origin"] = "https://proxy.example.com"
        blocked.settings["identity_provider"] = idp
        assert blocked.check_origin("https://evil.example.com") is False
