"""Wiring smoke tests for the Layer-3 agent. No live API / subprocess.

Mocks the genai client + MCP stdio/session boundaries; asserts ask() builds
contents from the prompt (+ image Parts), drives the tool-call loop against
the MCP session, and surfaces failures as SoccerhubError.
"""
import pytest

from soccerhub.errors import SoccerhubError


class _ACM:
    """Minimal async context manager yielding a fixed value."""

    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *exc):
        return False


class _AsyncCall:
    """Async callable returning fixed results in sequence (last repeats)."""

    def __init__(self, results):
        self._results = results if isinstance(results, list) else [results]
        self._i = 0
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        r = self._results[min(self._i, len(self._results) - 1)]
        self._i += 1
        if isinstance(r, Exception):
            raise r
        return r


def _resp(text=None, calls=None):
    """Fake GenerateContentResponse. calls = [(name, args), ...] → function_calls."""
    fcs = [type("FC", (), {"name": n, "args": a})() for n, a in (calls or [])]
    candidate = type("Cand", (), {"content": "MODEL_TURN"})()
    return type(
        "Resp",
        (),
        {"text": text, "function_calls": fcs or None, "candidates": [candidate]},
    )()


def _tool_result(text, is_error=False):
    return type(
        "CallToolResult",
        (),
        {"content": [type("Text", (), {"text": text})()], "isError": is_error},
    )()


def _wire(monkeypatch, gen_results, tool_result=None):
    """Patch agent's genai/stdio/session boundaries. Returns (session, gen)."""
    from soccerhub import agent

    async def _init():
        return None

    async def _list_tools():
        return type("ListTools", (), {"tools": []})()  # no tools → empty declarations

    call_tool = _AsyncCall(tool_result or _tool_result("DATA"))
    session = type(
        "Session",
        (),
        {
            "initialize": staticmethod(_init),
            "list_tools": staticmethod(_list_tools),
            "call_tool": call_tool,
        },
    )()
    monkeypatch.setattr(agent, "stdio_client", lambda server: _ACM((None, None)))
    monkeypatch.setattr(agent, "ClientSession", lambda read, write: _ACM(session))

    gen = _AsyncCall(gen_results)
    client = type("Client", (), {})()
    client.aio = type("Aio", (), {})()
    client.aio.models = type("Models", (), {"generate_content": gen})()
    fake_genai = type("genai", (), {"Client": staticmethod(lambda api_key: client)})
    monkeypatch.setattr(agent, "genai", fake_genai)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return session, gen


def test_ask_returns_model_text(monkeypatch):
    _wire(monkeypatch, _resp(text="Messi leads with 12 xG."))

    from soccerhub.agent import ask

    assert ask("who leads La Liga in xG?") == "Messi leads with 12 xG."


def test_ask_builds_contents_from_prompt(monkeypatch):
    _session, gen = _wire(monkeypatch, _resp(text="ok"))

    from soccerhub.agent import ask

    ask("interpret this")
    assert gen.calls[0]["contents"] == ["interpret this"]  # prompt first, no images


def test_ask_sends_images(monkeypatch):
    _session, gen = _wire(monkeypatch, _resp(text="The radar shows an elite passer."))

    from soccerhub.agent import ask

    out = ask("interpret this chart", images=[b"\x89PNG-fake-bytes"])

    assert out == "The radar shows an elite passer."
    contents = gen.calls[0]["contents"]
    assert contents[0] == "interpret this chart"  # prompt first
    assert len(contents) == 2  # prompt + one image Part


def test_ask_runs_tool_loop(monkeypatch):
    # turn 1: model calls a tool; turn 2: model answers with the tool data.
    session, gen = _wire(
        monkeypatch,
        [_resp(calls=[("hub_table", {"table": "player_season"})]), _resp(text="Done.")],
        tool_result=_tool_result("row1,row2"),
    )

    from soccerhub.agent import ask

    out = ask("query the hub")

    assert out == "Done."
    assert session.call_tool.calls[0] == {
        "name": "hub_table",
        "arguments": {"table": "player_season"},
    }
    assert len(gen.calls) == 2  # looped: called the model twice
    assert len(gen.calls[1]["contents"]) > 1  # fed the tool response back


def test_root_cause_unwraps_exception_group():
    from soccerhub.agent import _root_cause

    leaf = KeyError("GEMINI_API_KEY")
    group = ExceptionGroup("unhandled errors in a TaskGroup", [leaf])
    assert _root_cause(group) is leaf


def test_server_config():
    # Guards the two integration fixes live testing surfaced:
    from soccerhub import agent

    assert agent._SERVER.args[0] == "-c"  # launcher redirects import-time stdout
    assert "PATH" in (agent._SERVER.env or {})  # parent env forwarded to subprocess


def test_ask_wraps_errors(monkeypatch):
    _wire(monkeypatch, ValueError("boom"))

    from soccerhub.agent import ask

    with pytest.raises(SoccerhubError):
        ask("q")
