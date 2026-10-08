"""FastMCP server wrapper tests — tool registration observed via a fake SDK."""

from __future__ import annotations

import sys
import types

import pytest


# Shared registry: the fake FastMCP class is bound into `mcp_server.server`
# once, so its decorator closure must point at a module-level dict that each
# test clears, rather than a per-fixture local.
_registered: dict = {}


class FakeFastMCP:
    def __init__(self, name):
        self.name = name

    def tool(self):
        def decorator(fn):
            _registered[fn.__name__] = fn
            return fn

        return decorator

    def run(self):
        _registered["__ran__"] = True  # type: ignore[assignment]


@pytest.fixture()
def fake_mcp_sdk(monkeypatch):
    """A minimal fake `mcp` package recording registrations."""
    _registered.clear()

    fastmcp_mod = types.ModuleType("mcp.server.fastmcp")
    fastmcp_mod.FastMCP = FakeFastMCP

    mcp_mod = types.ModuleType("mcp")
    server_mod = types.ModuleType("mcp.server")
    mcp_mod.server = server_mod
    server_mod.fastmcp = fastmcp_mod

    monkeypatch.setitem(sys.modules, "mcp", mcp_mod)
    monkeypatch.setitem(sys.modules, "mcp.server", server_mod)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_mod)
    yield _registered


def test_server_registers_all_tools(fake_mcp_sdk):
    import mcp_server.server as server_mod

    # Re-run registration against the fake SDK
    server_mod.build_server()
    expected = {
        "search_library",
        "list_reports",
        "get_report",
        "list_items",
        "get_item",
        "start_research",
        "get_research",
    }
    assert expected <= set(fake_mcp_sdk)
    for name in expected - {"__ran__"}:
        assert callable(fake_mcp_sdk[name])


def test_registered_tool_delegates_to_core(fake_mcp_sdk, seeded_db):
    import mcp_server.server as server_mod

    server_mod.build_server()
    items = fake_mcp_sdk["list_items"](since_hours=48, limit=10)
    assert isinstance(items, list) and len(items) == 2
