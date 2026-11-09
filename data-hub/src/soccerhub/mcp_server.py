import logging
import sys
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from soccerhub.db.read import read_hub
from soccerhub.readers.fbref import fetch_fbref_season
from soccerhub.readers.statsbomb import fetch_statsbomb_events
from soccerhub.readers.transfermarkt import fetch_transfermarkt_values

# soccerdata attaches a rich console handler (writes to stdout, resolved at
# write time) to both the true root and the "root" logger. On an MCP stdio
# server that stream is the JSONRPC channel, so runtime logs would corrupt it.
# Drop the non-file (console) handlers and route logs to stderr; keep the
# info/error file handlers. (Import-time logs are handled by the launcher in
# agent.py, which redirects stdout while importing this package.)
for _lg in (logging.getLogger(), logging.getLogger("root")):
    _lg.handlers = [h for h in _lg.handlers if isinstance(h, logging.FileHandler)]
    _lg.addHandler(logging.StreamHandler(sys.stderr))

mcp = FastMCP("soccerhub")

# All tools are pure reads. openWorld=True for tools that hit external
# sites (FBref/StatsBomb/Transfermarkt); False for hub_table (own Supabase).
_READ_CLOSED = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
_READ_OPEN = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)


@mcp.tool(annotations=_READ_CLOSED)
def hub_table(
    table: str,
    select: str = "*",
    league: str | None = None,
    season: str | None = None,
    tm_id: int | None = None,
    max_rows: int = 1000,
) -> list[dict]:
    """Read the Supabase source of truth (player_season, transfers, player_xref).
    Filter by league/season/tm_id; unfiltered tables truncate at max_rows."""
    filters = {
        k: v
        for k, v in {"league": league, "season": season, "tm_id": tm_id}.items()
        if v is not None
    }
    try:
        return read_hub(table, select, **filters).head(max_rows).to_dict("records")
    except Exception as e:  # surface an actionable message to the model caller
        raise ToolError(str(e)) from e


@mcp.tool(annotations=_READ_OPEN)
def fbref_season(league: str, season: str) -> dict:
    """Fetch + cache FBref player season stats; returns a manifest."""
    try:
        return asdict(fetch_fbref_season(league, season))
    except Exception as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=_READ_OPEN)
def statsbomb_events(match_id: str) -> dict:
    """Fetch + cache StatsBomb open-data match events; returns a manifest."""
    try:
        return asdict(fetch_statsbomb_events(match_id))
    except Exception as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=_READ_OPEN)
def transfermarkt_values(competition: str) -> dict:
    """Fetch + cache Transfermarkt valuations for a competition; returns a manifest."""
    try:
        return asdict(fetch_transfermarkt_values(competition))
    except Exception as e:
        raise ToolError(str(e)) from e


if __name__ == "__main__":
    mcp.run()
