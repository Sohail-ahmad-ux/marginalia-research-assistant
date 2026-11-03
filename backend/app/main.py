import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import api, db, store
from .config import ROOT

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    threading.Thread(target=store.warmup, daemon=True).start()  # preload BM25 + reranker
    yield


app = FastAPI(title="AI Research Paper Assistant", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(api.router, prefix="/api")

dist = ROOT.parent / "frontend" / "dist"  # after `npm run build`, FastAPI serves the UI itself
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="ui")
