import time
import uuid

from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .database import AsyncSessionLocal
from manga_tracker.utils.logging import get_logger


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        request_id = str(uuid.uuid4())
        log = get_logger("api.middleware").bind(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start) * 1000
        log.info("request", status=response.status_code, duration_ms=round(duration_ms, 2))

        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    text("""
                        INSERT INTO audit.api_requests
                            (request_id, ts, method, path, query_string,
                             status_code, duration_ms, client_ip, user_agent)
                        VALUES
                            (:request_id, now(), :method, :path, :qs,
                             :status, :duration, :ip, :ua)
                    """),
                    {
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "qs": str(request.url.query) or None,
                        "status": response.status_code,
                        "duration": duration_ms,
                        "ip": request.client.host if request.client else None,
                        "ua": request.headers.get("user-agent"),
                    },
                )
                await db.commit()
        except Exception as exc:
            log.warning("audit_write_failed", error=str(exc))

        response.headers["X-Request-Id"] = request_id
        return response
