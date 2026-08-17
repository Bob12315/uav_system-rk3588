from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from web_ui.context import WebContext
from web_ui.dto import LoginRequest
from web_ui.security import SESSION_COOKIE


def build_router(ctx: WebContext) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.post("/login")
    def login(payload: LoginRequest, request: Request):
        source = request.client.host if request.client else ""
        try:
            result = ctx.security.login(payload.password, source)
        except RuntimeError as exc:
            if str(exc) == "rate_limited":
                raise HTTPException(status_code=429, detail="rate limited") from exc
            raise
        if result is None:
            raise HTTPException(status_code=401, detail="invalid credentials")
        session_id, csrf = result
        response = JSONResponse(
            {"ok": True, "operator": "operator", "role": "operator", "csrf_token": csrf}
        )
        response.set_cookie(
            SESSION_COOKIE, session_id, httponly=True,
            secure=request.url.scheme == "https", samesite="strict",
            max_age=int(ctx.security.session_ttl_sec), path="/",
        )
        return response

    @router.post("/logout")
    def logout(request: Request):
        ctx.security.logout(request.cookies.get(SESSION_COOKIE))
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    return router
