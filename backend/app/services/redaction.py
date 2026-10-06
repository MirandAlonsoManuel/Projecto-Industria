"""
Enmascaramiento de credenciales en fuentes de video (M12).

Las cámaras IP suelen llevar usuario y contraseña dentro de la URL
(`rtsp://admin:clave@192.168.1.50/stream`) o en parámetros
(`...?token=abc`). El gestor necesita la URL real para abrir la cámara, pero
nada de lo que sale del gestor (estado, métricas, eventos, errores, logs o
mensajes del WebSocket) debe contenerla.

Regla: lo que sale hacia afuera pasa por `redact_source` o `redact_text`.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MASK = "***"

# Nombres de parámetro que suelen llevar credenciales
_SENSITIVE_PARAM = re.compile(
    r"(pass(word|wd)?|pwd|token|secret|key|auth|credential|user(name)?|login|session|sig(nature)?)",
    re.IGNORECASE,
)

# "esquema://usuario:clave@" o "esquema://usuario@" en cualquier texto
_USERINFO_IN_TEXT = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)[^/\s@'\"]+@")

# "?token=valor" o "&password=valor" en cualquier texto
_SENSITIVE_PARAM_IN_TEXT = re.compile(
    r"(?P<prefix>[?&](?:[a-zA-Z0-9_]*?)"
    r"(?:pass(?:word|wd)?|pwd|token|secret|key|auth|credential|user(?:name)?|login|session|sig(?:nature)?)"
    r"[a-zA-Z0-9_]*=)[^&\s'\"]+",
    re.IGNORECASE,
)


def redact_source(source: str | None) -> str | None:
    """
    Versión pública de una fuente de video, sin credenciales.

    - `0`, `1`, rutas de archivo → se devuelven tal cual.
    - `rtsp://admin:clave@host/stream` → `rtsp://***@host/stream`
    - `rtsp://host/stream?user=a&token=b&canal=1` → `rtsp://host/stream?user=***&token=***&canal=1`
    """
    if source is None or "://" not in source:
        return source
    try:
        parts = urlsplit(source)
    except ValueError:
        return _USERINFO_IN_TEXT.sub(lambda m: f"{m.group('scheme')}{MASK}@", source)

    netloc = parts.netloc
    if "@" in netloc:
        netloc = f"{MASK}@{netloc.rsplit('@', 1)[1]}"

    query = parts.query
    if query:
        pairs = parse_qsl(query, keep_blank_values=True)
        query = urlencode(
            [(k, MASK if _SENSITIVE_PARAM.search(k) else v) for k, v in pairs],
            safe="*",
        )

    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def redact_text(text: str | None, *sources: str | None) -> str | None:
    """
    Enmascara credenciales dentro de un texto libre (mensajes de error, logs).

    Reemplaza cada aparición literal de las fuentes indicadas por su versión
    pública y, por si el texto trae otra URL, enmascara cualquier
    `usuario:clave@` que encuentre.
    """
    if not text:
        return text
    for source in sources:
        public = redact_source(source)
        if source and public != source:
            text = text.replace(source, public)
    text = _USERINFO_IN_TEXT.sub(lambda m: f"{m.group('scheme')}{MASK}@", text)
    return _SENSITIVE_PARAM_IN_TEXT.sub(lambda m: f"{m.group('prefix')}{MASK}", text)
