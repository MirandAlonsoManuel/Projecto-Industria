"""
Límite de tamaño de las peticiones de subida de imágenes (BUG-18, KIKE-8).

Por qué es un middleware ASGI y no una dependencia del endpoint
----------------------------------------------------------------
FastAPI/Starlette lee y procesa TODO el cuerpo `multipart/form-data` antes de
llamar al endpoint. Una validación dentro del endpoint (o de una dependencia)
llega tarde: el servidor ya recibió y almacenó los 30 MB. El límite tiene que
aplicarse antes, a nivel de la capa ASGI.

Dos defensas, porque el encabezado `Content-Length` lo declara el cliente y
puede faltar (`Transfer-Encoding: chunked`) o mentir:

1. Si `Content-Length` ya excede el límite, se responde 413 sin invocar la
   aplicación: no se lee ni un byte del cuerpo.
2. Si no hay `Content-Length` (o es menor que lo que realmente llega), se
   cuentan los bytes conforme se reciben. Al pasar el límite se responde 413 y
   a la aplicación se le avisa con `http.disconnect` para que deje de leer.

Detalle importante de (2): NO se lanza una excepción desde `receive`. FastAPI
convierte cualquier excepción ocurrida al leer el formulario en un
`400 "There was an error parsing the body"`, que es justo el comportamiento
que reportó QA. Por eso la respuesta 413 la envía este middleware
directamente, y lo que la aplicación intente enviar después se descarta.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Iterable

logger = logging.getLogger("uvicorn.error")

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

# Holgura para el "envoltorio" del multipart (boundaries, encabezados de cada
# parte, nombres de campo). Sin ella, una imagen que mide EXACTAMENTE el límite
# se rechazaría por unos cientos de bytes de sobrecarga.
MULTIPART_OVERHEAD_BYTES = 64 * 1024

# Rutas que reciben dos imágenes en la misma petición.
_TWO_FILE_SUFFIXES = ("/anomaly",)


class MaxBodySizeMiddleware:
    """
    Rechaza con 413 las peticiones a `path_prefixes` cuyo cuerpo exceda el
    límite.

    `max_bytes` es el tamaño máximo de UNA imagen. El límite del cuerpo es
    `max_bytes` (por imagen que la ruta acepte) más una holgura fija para el
    envoltorio multipart; `/inference/anomaly` recibe dos imágenes.
    """

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        max_bytes: int,
        path_prefixes: Iterable[str] = ("/inference",),
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes debe ser mayor que cero.")
        self.app = app
        self.max_bytes = int(max_bytes)
        self.path_prefixes = tuple(path_prefixes)

    def _applies(self, scope: Scope) -> bool:
        path = scope.get("path", "")
        return any(path.startswith(prefix) for prefix in self.path_prefixes)

    def body_limit(self, path: str) -> int:
        files = 2 if path.rstrip("/").endswith(_TWO_FILE_SUFFIXES) else 1
        return self.max_bytes * files + MULTIPART_OVERHEAD_BYTES

    @staticmethod
    def _declared_length(scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    return None
                return declared if declared >= 0 else None
        return None

    async def _reject(self, send: Send, limit: int) -> None:
        megabytes = self.max_bytes / (1024 * 1024)
        body = json.dumps(
            {"detail": f"La imagen supera el tamaño máximo permitido ({megabytes:g} MiB)."}
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    # Pide cerrar la conexión: el cuerpo restante no se va a leer.
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._applies(scope):
            await self.app(scope, receive, send)
            return

        limit = self.body_limit(scope.get("path", ""))

        declared = self._declared_length(scope)
        if declared is not None and declared > limit:
            logger.warning(
                "Petición rechazada por tamaño (413): %s declara %d bytes, límite %d.",
                scope.get("path"),
                declared,
                limit,
            )
            await self._reject(send, limit)
            return

        received = 0
        response_started = False
        answered = False  # ya respondimos 413 nosotros

        async def limited_receive() -> Message:
            nonlocal received, answered
            if answered:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    logger.warning(
                        "Petición rechazada por tamaño (413): %s superó %d bytes sin Content-Length válido.",
                        scope.get("path"),
                        limit,
                    )
                    if not response_started:
                        answered = True
                        await self._reject(send, limit)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if answered:
                # Ya respondimos 413: lo que la app intente enviar (p. ej. un
                # 400 por la lectura interrumpida) se descarta.
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not answered:
                raise
            # Ya respondimos 413 y cortamos la lectura con `http.disconnect`: la
            # aplicación puede fallar con ClientDisconnect (o equivalente) al ver
            # el cuerpo incompleto. Ese fallo es consecuencia del rechazo, no un
            # error del servidor: no debe subir como 500 ni ensuciar el log.
            logger.debug("Excepción de la aplicación tras rechazar con 413.", exc_info=True)
