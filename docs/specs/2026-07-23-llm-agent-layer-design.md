# Data Hub — LLM Agent Layer (Layer 3) — Design Spec

_Plan · Project #2 addendum · created 2026-07-23_

## Overview

`soccerhub`'s design doc (`2026-07-14-soccerhub-data-layer-design.md`) scoped a
three-layer architecture and explicitly deferred Layer 3 ("LLM agent over MCP")
as future work. Layer 1 (readers/pipelines) and Layer 2 (`mcp_server.py`) are
built and in production use (player card xG, hub queries). This spec adds
Layer 3: a Gemini-backed agent, `soccerhub.agent.ask()`, that answers
natural-language questions over hub data, interprets charts (data + rendered
image), and generates summaries — by calling the *existing* MCP tools, no new
data pipeline.

## Goals

- One function, `ask(prompt, images=None) -> str`, covering all three use
  cases (data query, chart interpretation, summary generation) — they're the
  same shape (text/image in, model decides whether to call a tool, text out).
- Zero duplication of tool logic: the agent calls `mcp_server.py`'s tools as
  an MCP client, it does not re-import Layer 1 or redefine schemas.
- Backend-first: importable/CLI-runnable now; site wiring (`player.html`
  button → HTTP endpoint → `ask()`) is explicitly out of scope for this spec.

## Non-goals (explicit YAGNI)

- HTTP endpoint / web wiring for `site/*.html`.
- Conversation memory or multi-turn session state across separate `ask()` calls.
- Streaming responses.
- Non-Gemini providers / fallback routing.
- Renaming existing MCP tool names (`hub_table`, `fbref_season`, etc.) — Layer 2
  is shipped; renaming breaks nothing to fix, so it stays snake_case as-is.

## Architecture

```
Layer 1  soccerhub readers/pipelines        ← unchanged
Layer 2  mcp_server.py (FastMCP, stdio)     ← unchanged tools, adds annotations
                                               + ToolError wrapping (this spec)
Layer 3  soccerhub/agent.py  ask()          ← NEW: Gemini + MCP client
```

`ask()` spawns `mcp_server.py` as a stdio subprocess (via a launcher that keeps
the JSONRPC channel clean), opens an `mcp.ClientSession`, converts the server's
tools to Gemini function declarations, and drives the tool-call loop **by hand**
— calling `session.call_tool` on each `FunctionCall` and feeding the result back.
The live session is deliberately **not** passed into the config; see As-built.

## Data flow (as built)

```
soccerhub.ask(prompt, images=None, model="gemini-3-flash-preview")
        │
        ▼
  contents = [prompt, *Part.from_bytes(png) for png in images]   (text + chart imgs)
        │
        ▼
  spawn MCP server subprocess (StdioServerParameters)
    command: python -c _LAUNCH        env=dict(os.environ) ──► SUPABASE_* forwarded
    _LAUNCH: with redirect_stdout(stderr):                       (fix: hub_table env)
               import soccerhub.mcp_server   ← import-time logs → STDERR (channel clean)
             mcp.run()                        ← JSONRPC protocol on clean STDOUT
        │                                       server also drops stdout log handlers
        ▼                                       → runtime soccerdata logs → STDERR
  stdio_client → ClientSession → await initialize()
        │
        ▼
  tools = mcp_to_gemini_tools( (await session.list_tools()).tools )  ← picklable decls
  config = GenerateContentConfig(tools=tools)                          (NOT the session —
        │                                                               avoids deepcopy)
        ▼
  ┌──────────────── manual tool loop (≤ _MAX_TURNS = 8) ────────────────────┐
  │  resp = await client.aio.models.generate_content(contents, config)      │
  │        │                                                                │
  │   resp.function_calls?                                                 │
  │     │ no ─────────────────────────────► return resp.text ──────────────┼─► str
  │     │ yes                                                               │
  │     ▼                                                                  │
  │  contents.append(resp.candidates[0].content)        # model tool turn  │
  │  for fc in resp.function_calls:                                        │
  │     result = await session.call_tool(name=fc.name, arguments=…)        │
  │        │                                                               │
  │        ├─ hub_table        → read_hub → Supabase REST (RLS, anon key)  │
  │        ├─ fbref_season     → soccerdata → parquet cache               │
  │        ├─ statsbomb_events → kloppy    → parquet cache               │
  │        └─ transfermarkt_…  → pre-scraped snapshot                     │
  │        │   (each @mcp.tool: ToolAnnotations + SoccerhubError→ToolError)│
  │        ▼                                                              │
  │  contents.append(Content(role="user", parts=[                        │
  │     Part.from_function_response(name=fc.name,                         │
  │        response={"result"|"error": tool_text})]))                     │
  │        └───────────────────── loop back ──────────────────────────────┘
  │
  loop exceeds _MAX_TURNS → raise SoccerhubError

ERROR PATHS:
  tool raises SoccerhubError → mcp_server.py re-raises as ToolError(str(e))
      → returned in CallToolResult(isError=True) → fed back as {"error": text},
      model may retry with corrected args or explain the failure
  MCP subprocess dies / transport error → ask() raises SoccerhubError
  Gemini API error (rate limit / auth)  → ask() raises SoccerhubError
  cache write mid-fetch fails → Layer-1 atomic-write guarantee holds (no poison)
```

## Interface

```python
# src/soccerhub/agent.py
def ask(
    prompt: str,
    images: list[bytes] | None = None,
    model: str = "gemini-3-flash-preview",
) -> str:
    """Ask the soccerhub agent a question. Calls MCP tools as needed."""
```

- `images`: optional list of PNG bytes (rendered chart screenshots), sent as
  multimodal `Part`s alongside the text prompt — Gemini reads both the
  underlying data (passed in `prompt`) and the visual pattern in the image.
- Raises `SoccerhubError` on any failure (API, transport, or an unrecovered
  tool error) — same convention as Layer 1 readers.
- One function covers all three use cases; which one happens is a function of
  what the caller puts in `prompt`/`images`, not a code branch.

## MCP server changes (`mcp_server.py`)

Two additions to the 4 existing tools, no behavior change to their logic:

1. **Tool annotations** — all 4 tools are pure reads:
   ```python
   from mcp.types import ToolAnnotations

   @mcp.tool(annotations=ToolAnnotations(
       readOnlyHint=True, destructiveHint=False, openWorldHint=False))
   def hub_table(...):   # reads own Supabase — closed world

   @mcp.tool(annotations=ToolAnnotations(
       readOnlyHint=True, destructiveHint=False, openWorldHint=True))
   def fbref_season(...):        # scrapes external site — open world
   def statsbomb_events(...):    # same
   def transfermarkt_values(...): # same
   ```
2. **Error wrapping** — catch `SoccerhubError`, re-raise as
   `mcp.server.fastmcp.exceptions.ToolError` so Gemini gets an actionable
   message instead of FastMCP's default masked generic error:
   ```python
   from mcp.server.fastmcp.exceptions import ToolError

   @mcp.tool(annotations=...)
   def statsbomb_events(match_id: str) -> dict:
       try:
           return asdict(fetch_statsbomb_events(match_id))
       except SoccerhubError as e:
           raise ToolError(str(e)) from e
   ```

Confirmed against installed `mcp==1.28.1`: `FastMCP.tool()` accepts
`annotations: ToolAnnotations`, and `ToolError` is importable — no version
bump needed for this.

## Config & dependencies

- New env var `GEMINI_API_KEY`, same pattern as existing `SUPABASE_*` vars
  (exported in shell / sourced `.env`, no dotenv library — matches repo
  convention, see `db/write.py`).
- `pyproject.toml`: add `google-genai>=1.9` (installed and verified against
  `google-genai==2.14.0`).
- The MCP server subprocess inherits `env=dict(os.environ)` — it needs
  `SUPABASE_URL` + `SUPABASE_PUBLISHABLE_KEY` for `hub_table`. `GEMINI_API_KEY`
  is used by the parent (agent) only; the server never needs it.

## Testing

One smoke test, `tests/test_agent.py`, matching the repo's "one test per unit"
pattern (`tests/test_cache.py`, `tests/test_understat.py`): mock the
`genai.Client` and `mcp.ClientSession`, assert `ask()` builds the correct
`Part` list (text, or text+image) and returns the mocked model's text. No real
API calls in tests — this is a wiring test, not an eval of Gemini's answers.

## Key decisions

| Concern | Decision | Rationale |
|---|---|---|
| LLM provider | Google Gemini free tier | AWS Bedrock / Azure OpenAI have no real free inference tier (trial credits only); Gemini free tier + native multimodal covers chart-image interpretation |
| Tool wiring | MCP client against existing `mcp_server.py` | Matches original Layer-3-over-MCP design; zero duplicate tool schemas; same server also usable by Claude Desktop/other MCP clients later |
| Tool-call loop | Manual (not SDK's `tools=[session]` passthrough) | genai 2.14.0 deep-copies the config before extracting MCP sessions; a live `ClientSession` can't be deep-copied. Pass declarations, execute via `session.call_tool`. See As-built. |
| Interface shape | One function `ask(prompt, images=None)` | All three use cases (query/chart/summary) are the same text-and-optional-image-in, text-out shape — no reason to branch in code |
| Chart interpretation input | Both structured data (in prompt) and rendered screenshot (image) | User wants the model reading numbers and visual pattern, not one or the other |
| MCP tool naming | Unchanged (`hub_table`, `fbref_season`, ...) | Already shipped; renaming has no functional benefit and risks breaking other MCP clients |
| New code naming | snake_case, prefer one-word names (`ask`) | Matches repo's PEP8 convention; user asked for concise naming, not camelCase |
| Site wiring | Deferred | User chose backend-first; needs a real backend host since `site/*.html` is static + direct Supabase calls today, no server to add an endpoint to yet |
| Tool annotations / error wrapping | Add to `mcp_server.py` now | Prerequisite for a *model* being the caller instead of a human — masked/vague errors block the model's ability to self-correct (e.g. retry a bad `match_id`) |

## As-built notes (bugs found in live testing)

The mocked smoke tests passed, but the first live end-to-end call surfaced three
integration bugs invisible to mocks. All three are fixed; verified live against
La Liga 2023 data through `hub_table` → Supabase.

1. **Deepcopy of a live MCP session.** genai 2.14.0's async `generate_content`
   runs `config.model_copy(deep=True)` *before* extracting MCP sessions
   (`models.py:8735`). A live `ClientSession` holds an `asyncio.Future`, which
   `deepcopy` can't copy → `TypeError: cannot pickle '_asyncio.Future'`. So the
   documented `tools=[session]` pattern is unusable here. Fix: convert tools with
   `_mcp_utils.mcp_to_gemini_tools` (picklable declarations) and run the tool
   loop by hand, executing each call via `session.call_tool`.

2. **stdout pollution corrupts the JSONRPC channel.** `soccerdata/_config.py:92`
   is a module-level `logger.info` to stdout. `python -m soccerhub.mcp_server`
   runs `__init__.py` (which imports the soccerdata-backed readers) *before*
   `mcp_server.py`'s body, so an in-module redirect is too late — the import-time
   log lands on the protocol stream. Fix (two parts): (a) spawn via a `python -c`
   launcher that wraps the *whole* import in `redirect_stdout(sys.stderr)` and
   only then calls `mcp.run()` on clean stdout; (b) in the server, drop the
   stdout console log handlers on the root and `"root"` loggers so runtime logs
   also go to stderr.

3. **Subprocess missing environment.** `stdio_client` with `env=None` passes only
   a safe default subset (PATH/HOME), so `hub_table` → `read_hub` hit
   `KeyError: 'SUPABASE_URL'` in the subprocess. Fix: `env=dict(os.environ)` on
   `StdioServerParameters`, forwarding `SUPABASE_*` (and everything else).

### Config impact
- **Supabase:** none. The agent reads through the existing publishable (anon)
  key + select-only RLS; no new tables, policies, or service-role exposure.
- **GitHub:** none beyond the `.env` staying gitignored (it holds
  `GEMINI_API_KEY`).
