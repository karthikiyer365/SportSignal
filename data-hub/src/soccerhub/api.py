"""HTTP wrapper exposing the agent for the site. Run:

    uvicorn soccerhub.api:app --host 0.0.0.0 --port $PORT

The /ask handler is a plain ``def`` on purpose: ``ask()`` calls
``asyncio.run()``, which must not run inside an already-running event loop.
FastAPI runs sync handlers in a threadpool, giving ``asyncio.run()`` a clean
thread. Needs GEMINI_API_KEY + SUPABASE_* in the server environment.
"""
import os
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from soccerhub.agent import ask
from soccerhub.errors import SoccerhubError

_MODELS = Literal[
    "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash"
]

app = FastAPI(title="soccerhub agent")

# Comma-separated allowed origins (the site). Default "*" for local dev; set
# AGENT_CORS_ORIGINS to the real site origin in production.
_origins = os.getenv("AGENT_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["POST"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    # length cap: this is a public trust boundary, keep prompts bounded
    prompt: str = Field(min_length=1, max_length=2000)
    model: _MODELS = "gemini-3.6-flash"


@app.post("/ask")
def ask_route(req: AskRequest) -> dict:
    # ponytail: no auth/rate-limit yet — add both before this is truly public.
    try:
        return {"answer": ask(req.prompt, model=req.model)}
    except SoccerhubError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/health")
def health() -> dict:
    return {"ok": True}
