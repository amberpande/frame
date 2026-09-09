from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from frame import __version__, config
from frame.api import model_router, query_router, specs_router
from frame.compile import GuardError
from frame.serve.cache import result_cache
from frame.serve.engine import get_engine

app = FastAPI(
    title="Frame",
    version=__version__,
    description=(
        "Dashboards as data. One runtime renders any spec; this service holds "
        "the semantic model, the query compiler and the serving tiers."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in config.CORS_ORIGINS if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(GuardError)
async def guard_error_handler(_: Request, exc: GuardError) -> JSONResponse:
    """A refused query is a structured answer, not a stack trace.

    The agent's planner reads `reason` and retries; the builder shows `detail`
    next to the offending control.
    """
    return JSONResponse(status_code=422, content={"error": exc.to_dict()})


app.include_router(model_router)
app.include_router(specs_router)
app.include_router(query_router)


@app.get("/api/v1/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "engine": config.ENGINE,
        "cache": result_cache.stats(),
        "warehouse": get_engine().stats(),
    }
