# Copyright 2024 Marimo. All rights reserved.
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from marimo import _loggers
from marimo._server.api.auth import (
    RANDOM_SECRET,
    CustomAuthenticationMiddleware,
    CustomSessionMiddleware,
    on_auth_error,
)
from marimo._server.api.middleware import (
    AuthBackend,
    OpenTelemetryMiddleware,
    ProxyMiddleware,
    SkewProtectionMiddleware,
    TimeoutMiddleware,
)
from marimo._server.api.router import build_routes
from marimo._server.api.status import (
    HTTPException as MarimoHTTPException,
)
from marimo._server.errors import handle_error
from marimo._server.lsp import LspServer
from marimo._server.registry import MIDDLEWARE_REGISTRY

if TYPE_CHECKING:
    from collections.abc import Iterator

    from starlette.types import Lifespan

LOGGER = _loggers.marimo_logger()


@dataclass
class LspPorts:
    pylsp: Optional[int]
    copilot: Optional[int]


# Create app
def create_starlette_app(
    *,
    base_url: str,
    host: Optional[str] = None,
    middleware: Optional[list[Middleware]] = None,
    lifespan: Optional[Lifespan[Starlette]] = None,
    enable_auth: bool = True,
    allow_origins: Optional[tuple[str, ...]] = None,
    lsp_servers: Optional[list[LspServer]] = None,
    skew_protection: bool = True,
    timeout: Optional[float] = None,
) -> Starlette:
    final_middlewares: list[Middleware] = []

    # DEV FORK: Check if dev mode is enabled for permissive CORS
    dev_mode = os.environ.get("MARIMO_DEV_MODE", "").lower() in ("1", "true", "yes")

    # DEV FORK: Always override allow_origins in dev mode to enable cross-origin requests
    if dev_mode:
        # Allow all origins in dev mode for external tool integration (Flask apps, etc.)
        allow_origins = ("*",)
    elif allow_origins is None:
        allow_origins = ("localhost", "127.0.0.1") + (
            (host,) if host is not None else ()
        )

    if enable_auth:
        final_middlewares.extend(
            [
                Middleware(
                    CustomSessionMiddleware,
                    secret_key=RANDOM_SECRET,
                ),
            ]
        )

    final_middlewares.extend(
        [
            Middleware(OpenTelemetryMiddleware),
            Middleware(
                CustomAuthenticationMiddleware,
                backend=AuthBackend(should_authenticate=enable_auth),
                on_error=on_auth_error,
            ),
            Middleware(
                CORSMiddleware,
                allow_origins=allow_origins,
                # DEV FORK: Disable credentials in dev mode to allow wildcard origins
                # CORS spec disallows credentials with origin "*"
                allow_credentials=not dev_mode,
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        ]
    )

    if skew_protection:
        final_middlewares.append(Middleware(SkewProtectionMiddleware))

    if lsp_servers is not None:
        final_middlewares.extend(
            _create_lsps_proxy_middleware(servers=lsp_servers)
        )

    if middleware:
        final_middlewares.extend(middleware)

    final_middlewares.extend(MIDDLEWARE_REGISTRY.get_all())

    app = Starlette(
        routes=build_routes(base_url=base_url),
        middleware=final_middlewares,
        lifespan=lifespan,
        exception_handlers={
            Exception: handle_error,
            HTTPException: handle_error,
            MarimoHTTPException: handle_error,
            ModuleNotFoundError: handle_error,
        },
    )
    if timeout is not None:
        app.add_middleware(
            TimeoutMiddleware,
            app_state=app.state,
            timeout_duration_minutes=timeout,
        )
    return app


def _create_lsps_proxy_middleware(
    *, servers: list[LspServer]
) -> Iterator[Middleware]:
    return (
        Middleware(
            ProxyMiddleware,
            proxy_path=f"/lsp/{server.id}",
            target_url=f"http://localhost:{server.port}",
        )
        for server in servers
    )
