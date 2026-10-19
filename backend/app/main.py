import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .config import get_settings
from .db import close_pool, get_meta, get_pool, migrate
from .services.encoder import get_encoder
from .services.entity_linker import EntityLinker
from .services.search import SearchService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("api")
state: dict = {"ready": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    migrate()
    pool = get_pool()
    encoder = await run_in_threadpool(get_encoder, settings)
    linker = EntityLinker(pool)
    aliases = linker.reload()
    llm = None
    if settings.anthropic_api_key:
        from .services.llm import LlmPlanner
        llm = LlmPlanner(settings.anthropic_api_key, settings.llm_model, settings.llm_timeout_s)
    service = SearchService(settings, pool, encoder, linker, llm)
    with pool.connection() as conn:
        snap = get_meta(conn, "snapshot", "{}")
    service.snapshot = hashlib.sha256(snap.encode()).hexdigest()[:12]
    await run_in_threadpool(encoder.encode_texts, ["warm up"])  # first call is slow
    state.update(service=service, ready=True, aliases=aliases, encoder=getattr(encoder, "name", "?"))
    log.info("ready: %s aliases, encoder %s, snapshot %s", aliases, state["encoder"], service.snapshot)
    yield
    state["ready"] = False
    close_pool()


app = FastAPI(title="Image Retrieval (Capstone B)", lifespan=lifespan)
settings = get_settings()
if settings.media_dir.exists():
    # Nginx serves /media in Docker; this mount is for running the API alone.
    app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=20, ge=1, le=50)
    selected_entity_ids: list[str] = Field(default_factory=list, max_length=10)


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    if not state.get("ready"):
        return JSONResponse({"status": "starting"}, status_code=503)
    return {"status": "ready", "encoder": state["encoder"], "aliases": state["aliases"]}


def _service() -> SearchService:
    if not state.get("ready"):
        raise HTTPException(503, "service is starting")
    return state["service"]


@app.post("/api/search")
def search(req: SearchRequest, nocache: bool = Query(False, include_in_schema=False)):
    started = time.perf_counter()
    result = _service().search(req.query.strip(), req.top_k, req.selected_entity_ids, use_cache=not nocache)
    log.info(json.dumps({"event": "search", "query_type": result["query_type"], "status": result["status"],
                         "parser": result["interpretation"]["parser"], "ms": result["metrics"]["server_ms"],
                         "cache_hit": result["metrics"]["cache_hit"], "llm_calls": result["metrics"]["llm_calls"]},
                        ensure_ascii=False))
    if (time.perf_counter() - started) * 1000 > settings.request_deadline_ms:
        result["warnings"].append("deadline_exceeded")
    return result


@app.get("/api/entities/suggest")
def suggest(q: str = Query(min_length=1, max_length=100)):
    return [e.__dict__ for e in _service().linker.suggest(q)]


@app.get("/api/corpus/stats")
def stats():
    return _service().stats()

