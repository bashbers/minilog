import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from minilog.api.router import api_router
from minilog.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("minilog")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = str(uuid.uuid4())
        started = time.monotonic()
        response_started = False
        response_status = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started, response_status
            if message["type"] == "http.response.start":
                response_started = True
                response_status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            logger.error(
                json.dumps(
                    {
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "event": "http_request",
                        "exception": type(exc).__name__,
                        "method": request.method,
                        "request_id": request_id,
                        "route": route_template(request),
                        "status": 500,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            if not response_started:
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "internal_server_error"},
                    headers={"X-Request-ID": request_id},
                )
                await response(scope, receive, send)
            return

        logger.info(
            json.dumps(
                {
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "event": "http_request",
                    "method": request.method,
                    "request_id": request_id,
                    "route": route_template(request),
                    "status": response_status,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )


def route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if not isinstance(path, str):
        return "unmatched"
    if request.url.path.startswith("/api/v1/") and not path.startswith("/api/v1/"):
        return f"/api/v1{path}"
    return path


app = FastAPI(
    title="Minilog API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(RequestContextMiddleware)
app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": get_settings().app_name, "status": "ok"}
