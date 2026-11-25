"""
Pruebas de MaxBodySizeMiddleware — BUG-18 (KIKE-8): sin límite de tamaño de subida.

Se prueba a nivel ASGI puro (sin TestClient), porque lo que importa es CUÁNTO
cuerpo llega a leer la aplicación:
  - Content-Length mayor al límite  -> 413 sin leer ni un byte del cuerpo.
  - Sin Content-Length (chunked)    -> 413 en cuanto se cuentan más bytes que el límite.
  - Content-Length que miente       -> igual: manda el conteo real.
  - Dentro del límite               -> la petición llega intacta a la aplicación.

La aplicación interna imita a FastAPI: lee el formulario con `request.form()` de
Starlette y convierte cualquier excepción de lectura en un 400 "There was an
error parsing the body" (es lo que hace FastAPI y lo que QA vio antes del arreglo).
"""

from __future__ import annotations

import asyncio
import json

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.middleware import MULTIPART_OVERHEAD_BYTES, MaxBodySizeMiddleware

LIMIT = 1024 * 1024  # 1 MiB por imagen, para que las pruebas sean rápidas
BOUNDARY = "frontera-de-prueba"


def multipart_body(payload: bytes, field: str = "image") -> bytes:
    head = (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="foto.jpg"\r\n'
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode()
    tail = f"\r\n--{BOUNDARY}--\r\n".encode()
    return head + payload + tail


def multipart_two_files(first: bytes, second: bytes) -> bytes:
    def part(name: str, data: bytes) -> bytes:
        return (
            f"--{BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{name}.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode() + data + b"\r\n"

    return part("image", first) + part("reference_image", second) + f"--{BOUNDARY}--\r\n".encode()


async def form_app(scope, receive, send):
    """Imita un endpoint de FastAPI que recibe un archivo multipart."""
    request = Request(scope, receive)
    try:
        form = await request.form()
    except Exception:  # FastAPI: cualquier fallo al leer el cuerpo -> 400
        response = JSONResponse({"detail": "There was an error parsing the body"}, status_code=400)
    else:
        sizes = {name: len(await upload.read()) for name, upload in form.items() if hasattr(upload, "read")}
        response = JSONResponse({"ok": True, "sizes": sizes})
    await response(scope, receive, send)


class Result:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.receive_calls = 0
        self.bytes_delivered = 0

    @property
    def statuses(self) -> list[int]:
        return [m["status"] for m in self.messages if m["type"] == "http.response.start"]

    @property
    def status(self) -> int:
        assert len(self.statuses) == 1, f"se esperaba una sola respuesta, hubo {self.statuses}"
        return self.statuses[0]

    @property
    def headers(self) -> dict[str, str]:
        start = next(m for m in self.messages if m["type"] == "http.response.start")
        return {k.decode().lower(): v.decode() for k, v in start["headers"]}

    @property
    def json(self) -> dict:
        body = b"".join(m.get("body", b"") for m in self.messages if m["type"] == "http.response.body")
        return json.loads(body)


def run(
    app,
    body: bytes,
    *,
    path: str = "/inference/localization",
    content_length: str | int | None = "auto",
    chunk_size: int = 16 * 1024,
    method: str = "POST",
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> Result:
    """Envía `body` a `app` en trozos y devuelve lo que la app respondió/leyó."""
    result = Result()
    headers = [(b"content-type", f"multipart/form-data; boundary={BOUNDARY}".encode())]
    if content_length == "auto":
        headers.append((b"content-length", str(len(body)).encode()))
    elif content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    else:
        headers.append((b"transfer-encoding", b"chunked"))
    headers.extend(extra_headers or [])
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 5000),
    }
    chunks = [body[i : i + chunk_size] for i in range(0, len(body), chunk_size)] or [b""]
    pending = list(chunks)

    async def receive():
        result.receive_calls += 1
        if not pending:
            await asyncio.sleep(0)
            return {"type": "http.disconnect"}
        chunk = pending.pop(0)
        result.bytes_delivered += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": bool(pending)}

    async def send(message):
        result.messages.append(message)

    asyncio.run(app(scope, receive, send))
    return result


def middleware(max_bytes: int = LIMIT, inner=form_app, **kwargs) -> MaxBodySizeMiddleware:
    return MaxBodySizeMiddleware(inner, max_bytes=max_bytes, **kwargs)


# ---------------------------------------------------------------- Content-Length

def test_content_length_mayor_al_limite_responde_413_sin_leer_el_cuerpo():
    body = multipart_body(b"x" * (LIMIT + MULTIPART_OVERHEAD_BYTES + 10))
    result = run(middleware(), body)
    assert result.status == 413
    assert "tamaño máximo" in result.json["detail"]
    # No se leyó ni un byte: el rechazo ocurre antes de invocar la aplicación.
    assert result.receive_calls == 0
    assert result.bytes_delivered == 0


def test_imagen_de_30_mb_con_limite_de_25_mib_responde_413():
    # El caso exacto del reporte de QA: 30 MB contra el límite por defecto.
    limit = 25 * 1024 * 1024
    body = multipart_body(b"\x00" * (30 * 1000 * 1000))
    result = run(middleware(max_bytes=limit), body, chunk_size=1024 * 1024)
    assert result.status == 413


def test_la_respuesta_413_no_depende_de_la_aplicacion_interna():
    llamadas = []

    async def app_que_no_debe_correr(scope, receive, send):
        llamadas.append(1)

    body = multipart_body(b"x" * (LIMIT * 2))
    result = run(middleware(inner=app_que_no_debe_correr), body)
    assert result.status == 413
    assert llamadas == []


# ------------------------------------------------------- sin Content-Length (chunked)

def test_cuerpo_chunked_sin_content_length_que_excede_el_limite_responde_413():
    body = multipart_body(b"x" * (LIMIT * 3))
    result = run(middleware(), body, content_length=None)
    assert result.status == 413
    assert "tamaño máximo" in result.json["detail"]
    # Se corta cerca del límite: no se consumió el cuerpo completo.
    assert result.bytes_delivered < len(body)
    assert result.bytes_delivered <= LIMIT + MULTIPART_OVERHEAD_BYTES + 16 * 1024


def test_413_gana_aunque_la_aplicacion_responda_400_al_ver_la_lectura_cortada():
    # form_app convierte la desconexión en un 400. Solo debe salir UNA respuesta: el 413.
    body = multipart_body(b"x" * (LIMIT * 3))
    result = run(middleware(), body, content_length=None)
    assert result.statuses == [413]


def test_content_length_que_miente_no_evita_el_limite():
    body = multipart_body(b"x" * (LIMIT * 3))
    result = run(middleware(), body, content_length=100)
    assert result.status == 413


def test_content_length_no_numerico_no_evita_el_limite():
    body = multipart_body(b"x" * (LIMIT * 3))
    result = run(middleware(), body, content_length="abc")
    assert result.status == 413


# --------------------------------------------------------------- dentro del límite

def test_imagen_dentro_del_limite_llega_intacta():
    payload = b"\xff\xd8" + b"y" * 5000
    result = run(middleware(), multipart_body(payload))
    assert result.status == 200
    assert result.json == {"ok": True, "sizes": {"image": len(payload)}}


def test_imagen_de_exactamente_el_limite_pasa_pese_al_envoltorio_multipart():
    # El envoltorio multipart suma bytes al cuerpo; una imagen que mide justo el
    # límite NO debe rechazarse por eso.
    payload = b"z" * LIMIT
    result = run(middleware(), multipart_body(payload))
    assert result.status == 200
    assert result.json["sizes"]["image"] == LIMIT


def test_imagen_de_exactamente_el_limite_pasa_tambien_sin_content_length():
    payload = b"z" * LIMIT
    result = run(middleware(), multipart_body(payload), content_length=None)
    assert result.status == 200
    assert result.json["sizes"]["image"] == LIMIT


def test_anomaly_acepta_dos_imagenes_del_tamano_maximo():
    body = multipart_two_files(b"a" * LIMIT, b"b" * LIMIT)
    result = run(middleware(), body, path="/inference/anomaly")
    assert result.status == 200
    assert result.json["sizes"] == {"image": LIMIT, "reference_image": LIMIT}


def test_anomaly_tambien_rechaza_lo_que_excede_dos_imagenes():
    body = multipart_two_files(b"a" * LIMIT, b"b" * (LIMIT * 2))
    result = run(middleware(), body, path="/inference/anomaly")
    assert result.status == 413


def test_una_ruta_de_una_imagen_no_acepta_el_doble_del_limite():
    body = multipart_two_files(b"a" * LIMIT, b"b" * LIMIT)
    result = run(middleware(), body, path="/inference/localization")
    assert result.status == 413


# -------------------------------------------------------------- lo que NO se toca

def test_rutas_fuera_de_inference_no_se_limitan():
    body = multipart_body(b"x" * (LIMIT * 2))
    result = run(middleware(), body, path="/cameras")
    assert result.status == 200


def test_conexiones_que_no_son_http_pasan_sin_cambios():
    visto = []

    async def app(scope, receive, send):
        visto.append(scope["type"])

    scope = {"type": "websocket", "path": "/inference/ws", "headers": []}

    async def nada(*args, **kwargs):
        return {}

    asyncio.run(middleware(inner=app)(scope, nada, nada))
    assert visto == ["websocket"]


def test_el_413_lleva_encabezados_cors_con_el_orden_de_create_app():
    # Mismo orden que app/main.py: primero el límite, después CORS (capa externa).
    from starlette.applications import Starlette
    from starlette.middleware.cors import CORSMiddleware
    from starlette.routing import Route

    async def endpoint(request: Request):
        await request.form()  # la ruta lee el cuerpo, como un endpoint con UploadFile
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/inference/localization", endpoint, methods=["POST"])])
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=LIMIT, path_prefixes=("/inference",))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    body = multipart_body(b"x" * (LIMIT * 3))
    origin = [(b"origin", b"http://localhost:5173")]
    for content_length in ("auto", None):  # con y sin Content-Length
        result = run(app, body, content_length=content_length, extra_headers=origin)
        assert result.status == 413
        assert result.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_limite_invalido_se_rechaza_al_construir():
    import pytest

    with pytest.raises(ValueError):
        MaxBodySizeMiddleware(form_app, max_bytes=0)
