import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from minilog.api.router import api_router
from minilog.config import get_settings
from minilog.database import PrivateDatabaseBusyError

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
        if not request_origin_is_allowed(request):
            response = JSONResponse(status_code=400, content={"detail": "origin_not_allowed"})
            await response(scope, receive, send)
            return
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


def request_origin_is_allowed(request: Request) -> bool:
    if request.url.path in {"/api/v1/health/live", "/api/v1/health/ready"}:
        return True
    configured = urlsplit(str(get_settings().public_origin))
    if request.headers.get("host", "").lower() != configured.netloc.lower():
        return False
    supplied_origin = request.headers.get("origin")
    if supplied_origin is None:
        return True
    candidate = urlsplit(supplied_origin)
    return (
        candidate.scheme.lower() == configured.scheme.lower()
        and candidate.netloc.lower() == configured.netloc.lower()
        and candidate.path in {"", "/"}
        and not candidate.query
        and not candidate.fragment
    )


app = FastAPI(
    title="Minilog API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(RequestContextMiddleware)
app.include_router(api_router)


@app.exception_handler(PrivateDatabaseBusyError)
async def private_database_busy_handler(
    _request: Request, _exc: PrivateDatabaseBusyError
) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": "database_busy_retry"},
        headers={"Retry-After": "1"},
    )


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": get_settings().app_name, "status": "ok"}
