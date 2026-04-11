from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("service.starting")
    yield
    log.info("service.stopping")
