"""Layer 3: Gemini agent over the soccerhub MCP tools.

``ask()`` spawns ``mcp_server.py`` as a stdio subprocess and lets Gemini call
the registered tools (hub_table, fbref_season, ...) via the SDK's built-in MCP
support — no hand-written tool schemas. Text in, text out.

Needs ``GEMINI_API_KEY`` in the environment (same convention as SUPABASE_*).
"""
import asyncio
import os
import sys

from google import genai
from google.genai import _mcp_utils, types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from soccerhub.errors import SoccerhubError

# Spawn the MCP server with the whole package import redirected to stderr, then
# run on a clean stdout. Importing soccerhub pulls in soccerdata, which logs to
# stdout at import time; on an stdio server that would corrupt the JSONRPC
# channel. mcp.run() itself runs *after* the redirect, on the real stdout.
_LAUNCH = (
    "import sys, contextlib\n"
    "with contextlib.redirect_stdout(sys.stderr):\n"
    "    import soccerhub.mcp_server as _m\n"
    "_m.mcp.run()\n"
)
# Forward the parent environment: without it stdio_client passes only a safe
# default subset, and hub_table would KeyError on SUPABASE_URL in the subprocess.
_SERVER = StdioServerParameters(
    command=sys.executable, args=["-c", _LAUNCH], env=dict(os.environ)
)
_MAX_TURNS = 5  # cap the tool-call loop so a confused model can't run forever

# Locks the answer to a fixed 5-section shape + a narrow markdown subset the
# frontend renderer (site/player.html renderAskMd) knows how to draw. Keep
# these two in sync: adding a markdown element here without frontend support
# renders as literal ###/** text.
_SYSTEM_INSTRUCTION = """\
You are a football analytics assistant. Answer using ONLY this structure, in \
this exact order, and nothing outside it (no preamble, no closing summary):

## Statistical Overview
A markdown table comparing the subject to 4-6 relevant peers on the stats \
the question calls for.

## Peer Comparison
1-3 bullet points, one sentence each.

## xG/Shot & xA/Pass
1-3 bullet points on shot volume/quality and chance creation, one sentence each.

## Key Takeaways
2-3 bullet points, one sentence each.

## Projected Fit
1-2 sentences: which team system/tactical profile he'd suit and why.

Formatting rules — use ONLY these markdown elements:
- `##` for the 5 section headers above, nothing else uses `##` or `###`.
- `**bold**` for stat values only, never whole sentences.
- `- ` for bullets, never `*` or numbered lists.
- Pipe tables (`| a | b |`) only in Statistical Overview.
- No horizontal rules (`---`), no other markdown.
Keep prose outside the table under 150 words total."""


def _tool_result_text(result) -> str:
    """Flatten an MCP CallToolResult's content blocks into one string."""
    return "".join(getattr(c, "text", "") for c in result.content)


def _root_cause(exc: BaseException) -> BaseException:
    """Unwrap anyio/asyncio ExceptionGroups to the real leaf exception, so the
    error message is actionable instead of 'unhandled errors in a TaskGroup'."""
    while (subs := getattr(exc, "exceptions", None)):
        exc = subs[0]
    return exc


def ask(
    prompt: str,
    images: list[bytes] | None = None,
    model: str = "gemini-3.6-flash",  # stable GA flash; preview/2.5 models 503/reject under load
) -> str:
    """Ask the soccerhub agent a question. Calls MCP tools as needed; returns text.

    images: optional PNG bytes (rendered chart screenshots) sent alongside the
    prompt so the model reads the visual pattern, not just numbers in the text.
    """
    try:
        return asyncio.run(_run(prompt, images or [], model))
    except SoccerhubError:
        raise
    except Exception as e:  # API / transport / unrecovered tool error
        cause = _root_cause(e)
        raise SoccerhubError(f"{type(cause).__name__}: {cause}") from e


async def _run(prompt: str, images: list[bytes], model: str) -> str:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    contents: list = [
        prompt,
        *(types.Part.from_bytes(data=img, mime_type="image/png") for img in images),
    ]
    async with stdio_client(_SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # Pass tool *declarations* (picklable) and drive the tool loop by
            # hand: genai's async generate_content deep-copies the config, which
            # can't copy a live MCP session held in tools=[session].
            tools = _mcp_utils.mcp_to_gemini_tools((await session.list_tools()).tools)
            config = types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION, tools=tools
            )
            # Last turn: disable function calling outright so the API can't
            # return another tool call — it must answer with what it has.
            final_config = types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION
                + "\n\nYou have no more tool calls left — answer now from what "
                "you've already gathered, following the structure above.",
                tools=tools,
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode="NONE")
                ),
            )
            for turn in range(_MAX_TURNS):
                is_last = turn == _MAX_TURNS - 1
                resp = await client.aio.models.generate_content(
                    model=model, contents=contents, config=final_config if is_last else config
                )
                calls = resp.function_calls
                if not calls:
                    return resp.text
                contents.append(resp.candidates[0].content)  # model's tool-call turn
                for fc in calls:
                    result = await session.call_tool(
                        name=fc.name, arguments=dict(fc.args or {})
                    )
                    key = "error" if result.isError else "result"
                    contents.append(
                        types.Content(
                            role="user",
                            parts=[types.Part.from_function_response(
                                name=fc.name,
                                response={key: _tool_result_text(result)},
                            )],
                        )
                    )
    raise SoccerhubError(f"agent exceeded {_MAX_TURNS} tool-call turns")
