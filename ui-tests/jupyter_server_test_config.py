"""Server configuration for integration tests.

!! Never use this configuration in production because it
opens the server to the world and provide access to JupyterLab
JavaScript objects through the global window variable.
"""
import os
import sys

from jupyterlab.galata import configure_jupyter_server

configure_jupyter_server(c)

# Make the test-only server extension (jsd_test_ext.py, alongside this config)
# importable, then enable it. It exposes /jsd-test/* endpoints used by the E2E
# tests to deterministically recreate document rooms.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
c.ServerApp.jpserver_extensions = {"jsd_test_ext": True}

# Uncomment to set server log level to debug level
# c.ServerApp.log_level = "DEBUG"
