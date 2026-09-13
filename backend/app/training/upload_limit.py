"""Bound the complete multipart request before the framework spools uploaded files."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.training.validation import MAX_BYTES


class TrainingRequestLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not scope.get("path", "").startswith(
                ("/api/training-datasets", "/api/training-runs", "/api/model-adapters")
            )
        ):
            await self.app(scope, receive, send)
            return
        limit = (
            64 * 1024
            if scope.get("path", "").startswith(("/api/training-runs", "/api/model-adapters"))
            else MAX_BYTES + 64 * 1024
        )
        body = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            chunk = event.get("body", b"")
            if len(body) + len(chunk) > limit:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "data": None,
                        "error": {
                            "code": "FILE_TOO_LARGE",
                            "message": "训练数据请求超出大小限制。",
                        },
                    },
                )
                await response(scope, receive, send)
                return
            body.extend(chunk)
            if not event.get("more_body", False):
                break
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, bounded_receive, send)
