"""Bounded ASGI receive BEFORE JSON/multipart parsing, including chunked requests."""

import asyncio

from fastapi.responses import JSONResponse


class BodyLimit:
    def __init__(self, app):
        self.app = app
        self.slots = asyncio.Semaphore(4)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        limit = 11 * 1024**2 if scope["path"] == "/api/v1/uploads" else 384 * 1024
        async with self.slots:
            blocks, size = [], 0
            try:
                async with asyncio.timeout(15):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        block = message.get("body", b"")
                        size += len(block)
                        if size > limit:
                            raise ValueError("quota")
                        blocks.append(block)
                        if not message.get("more_body", False):
                            break
            except (TimeoutError, ValueError):
                response = JSONResponse(
                    status_code=413,
                    content={
                        "schema_version": "api-v1",
                        "error": {
                            "code": "WEB_BODY_LIMIT",
                            "message": "Request exceeds receive quota",
                            "retryable": False,
                            "manual_action_required": False,
                        },
                    },
                )
                return await response(scope, receive, send)
            consumed = False

            async def bounded_receive():
                nonlocal consumed
                if consumed:
                    return await receive()
                consumed = True
                return {"type": "http.request", "body": b"".join(blocks), "more_body": False}

            return await self.app(scope, bounded_receive, send)
