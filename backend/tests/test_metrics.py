"""
Pruebas de métricas operativas de cámara y streaming — M12 (OMC-93).

Sin cámara física: cada apertura entrega una cámara con un guion exacto de
lecturas (frames buenos, vacíos o errores del driver). Al terminar el guion,
la lectura se queda esperando, así que los contadores quedan fijos y se
pueden comparar contra lo que realmente ocurrió.

Criterios cubiertos:
  C1  Las métricas son consultables y corresponden al estado real.
  C2  La cantidad de clientes solo puede ser 0 o 1.
  C3  Los contadores no exponen credenciales ni datos sensibles.

Ejecutar:
    cd backend
    python -m pytest tests/test_metrics.py -v
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import cameras as cameras_router
from app.api.routers import stream as stream_router
from app.services import camera_session_manager as manager_module
from app.services.camera_session_manager import (
    CameraSessionManager,
    SessionBusyError,
    SessionCameraError,
)
from app.services.redaction import redact_source, redact_text

CLAVE = "Sup3rClave"
TOKEN = "T0k3nSecreto"
URL_SECRETA = f"rtsp://admin:{CLAVE}@10.0.0.5:554/stream?token={TOKEN}&canal=1"
SECRETOS = (CLAVE, TOKEN)


# ── Cámara con guion exacto ──────────────────────────────────────────────────

class ScriptedCapture:
    """
    Lee un guion de tokens: "ok" (frame válido), "empty" (frame vacío) o
    "error" (el driver lanza una excepción que menciona la fuente, como hacen
    muchos drivers reales). Al terminar el guion aplica `then`: "block" (la
    lectura espera hasta el final de la prueba), "ok" o "empty" indefinidamente.
    """

    is_opened = True

    def __init__(self, source: str, script: list[str], then: str, fin: threading.Event,
                 stats: "Stats") -> None:
        self.source = source
        self.script = list(script)
        self.then = then
        self.fin = fin
        self.stats = stats
        self.exhausted = threading.Event()
        self._released = False
        stats.opened += 1
        stats.active += 1

    def read_frame(self):
        time.sleep(0.002)
        if self.script:
            token = self.script.pop(0)
        else:
            self.exhausted.set()
            if self.then == "block":
                self.fin.wait(timeout=10)
                return None
            token = self.then
        if token == "ok":
            return np.zeros((8, 8, 3), dtype=np.uint8)
        if token == "empty":
            return None
        raise RuntimeError(f"fallo simulado leyendo {self.source}")

    def release(self) -> None:
        if not self._released:
            self._released = True
            self.stats.active -= 1


class Stats:
    def __init__(self) -> None:
        self.opened = 0
        self.active = 0
        self.sources: list[str] = []


class Guiones(list):
    """Un guion por apertura: (tokens, then). Vacío = frames buenos sin fin."""

    def __init__(self) -> None:
        super().__init__()
        self.fin = threading.Event()
        self.capturas: list[ScriptedCapture] = []


@pytest.fixture
def stats() -> Stats:
    return Stats()


@pytest.fixture
def guiones(monkeypatch, stats):
    g = Guiones()

    def fake_open_camera(source: str):
        stats.sources.append(source)
        script, then = g.pop(0) if g else ([], "ok")
        captura = ScriptedCapture(source, script, then, g.fin, stats)
        g.capturas.append(captura)
        return captura

    monkeypatch.setattr(manager_module, "open_camera", fake_open_camera)
    monkeypatch.setattr(manager_module, "FRAME_STALE_TIMEOUT_S", 0.3)
    yield g
    g.fin.set()


@pytest.fixture
def manager() -> CameraSessionManager:
    # Umbral alto: estas pruebas no buscan disparar recuperaciones
    return CameraSessionManager(stale_timeout_s=30, watchdog_interval_s=0.05)


def run(coro):
    return asyncio.run(coro)


async def esperar(condicion, limite: float = 3.0) -> None:
    fin = time.monotonic() + limite
    while not condicion():
        assert time.monotonic() < fin, "la condición no se cumplió a tiempo"
        await asyncio.sleep(0.01)


async def esperar_guion(captura: ScriptedCapture) -> None:
    await asyncio.get_running_loop().run_in_executor(None, captura.exhausted.wait, 3)
    await asyncio.sleep(0.05)  # la captura procesa la última lectura


async def cerrar(manager: CameraSessionManager, guiones: Guiones) -> None:
    guiones.fin.set()
    if manager.session is not None:
        await manager.stop()


def sin_secretos(*objetos) -> bool:
    texto = json.dumps(objetos, default=str)
    return not any(secreto in texto for secreto in SECRETOS)


# ── C1: consultables y fieles al estado real ─────────────────────────────────

def test_c1_frames_capturados_perdidos_y_errores_exactos(manager, guiones):
    guiones.append((["ok"] * 10 + ["empty"] * 3 + ["error"] * 2, "block"))

    async def escenario():
        await manager.connect_client("0", "c1")
        await esperar_guion(guiones.capturas[0])
        metricas = manager.get_metrics()
        await cerrar(manager, guiones)
        return metricas

    m = run(escenario())

    assert m["frames"]["session"]["captured"] == 10
    assert m["frames"]["session"]["dropped"] == 5          # 3 vacíos + 2 errores del driver
    assert m["errors"]["session"] == 2                      # los vacíos no son errores
    assert m["frames"]["since_start"]["captured"] == 10
    assert "fallo simulado" in m["last_error"]["message"]


def test_c1_estado_de_la_camara_coincide_con_el_ciclo_de_vida(manager, guiones):
    async def escenario():
        vacia = manager.get_metrics()
        await manager.start("0")
        corriendo = manager.get_metrics()
        await manager.connect_client("0", "c1")
        transmitiendo = manager.get_metrics()
        await cerrar(manager, guiones)
        return vacia, corriendo, transmitiendo, manager.get_metrics()

    vacia, corriendo, transmitiendo, detenida = run(escenario())

    assert vacia["camera"]["state"] == "idle" and vacia["camera"]["camera_id"] is None
    assert corriendo["camera"]["state"] == "running"
    assert corriendo["camera"]["started_by"] == "operator"
    assert transmitiendo["camera"]["state"] == "streaming"
    assert transmitiendo["camera"]["health"] == "ok"
    assert detenida["camera"]["state"] == "idle"
    assert detenida["service"]["sessions_started"] == 1


def test_c1_los_acumulados_sobreviven_al_cierre_de_la_sesion(manager, guiones):
    guiones.append((["ok"] * 4, "block"))
    guiones.append((["ok"] * 3 + ["empty"], "block"))

    async def escenario():
        await manager.connect_client("0", "c1")
        await esperar_guion(guiones.capturas[0])
        guiones.fin.set()
        await manager.disconnect_client("c1")
        tras_primera = manager.get_metrics()

        guiones.fin.clear()
        await manager.connect_client("0", "c2")
        await esperar_guion(guiones.capturas[1])
        durante_segunda = manager.get_metrics()
        await cerrar(manager, guiones)
        return tras_primera, durante_segunda

    tras_primera, durante_segunda = run(escenario())

    assert tras_primera["frames"]["session"]["captured"] == 0
    assert tras_primera["frames"]["since_start"]["captured"] == 4
    assert durante_segunda["frames"]["session"] == {
        "captured": 3, "dropped": 1, "sent": 0, "skipped": 0,
    }
    assert durante_segunda["frames"]["since_start"]["captured"] == 7
    # Acumulado = sesiones cerradas + sesión actual (la lectura que quedó esperando
    # al cerrar la primera terminó sin imagen y también cuenta como perdida)
    assert (
        durante_segunda["frames"]["since_start"]["dropped"]
        == tras_primera["frames"]["since_start"]["dropped"] + 1
    )
    assert durante_segunda["service"]["sessions_started"] == 2
    assert durante_segunda["client"]["connections_total"] == 2


def test_c1_recuperaciones_reflejan_lo_ocurrido(guiones):
    manager = CameraSessionManager(
        stale_timeout_s=0.15, watchdog_interval_s=0.02, recovery_backoff_s=0.01
    )
    guiones.append(([], "empty"))     # se estanca
    guiones.append(([], "ok"))        # la reapertura funciona

    async def escenario():
        await manager.connect_client("0", "c1")
        await esperar(lambda: manager.get_metrics()["recoveries"]["session"]["recovered"] == 1)
        metricas = manager.get_metrics()
        await cerrar(manager, guiones)
        return metricas, manager.get_metrics()

    durante, despues = run(escenario())

    assert durante["recoveries"]["session"] == {"recovered": 1, "failed": 0}
    assert despues["recoveries"]["since_start"] == {"recovered": 1, "failed": 0}
    assert durante["client"]["connected"] == 1  # el cliente sobrevivió


def test_c1_enviados_coinciden_con_lo_que_recibe_el_cliente(monkeypatch, manager, guiones):
    guiones.append((["ok"] * 6, "block"))
    monkeypatch.setattr(stream_router, "camera_session_manager", manager)
    monkeypatch.setattr(cameras_router, "camera_session_manager", manager)
    app = FastAPI()
    app.include_router(stream_router.router)
    app.include_router(cameras_router.router)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/stream?camera_id=0") as ws:
            ws.receive_json()
            guiones.capturas and guiones.capturas[0].exhausted.wait(3)
            time.sleep(0.2)
            metricas = client.get("/cameras/metrics").json()["data"]
            enviados = metricas["frames"]["session"]["sent"]
            recibidos = [ws.receive_bytes() for _ in range(enviados)]
            guiones.fin.set()

    frames = metricas["frames"]["session"]
    assert frames["captured"] == 6
    assert len(recibidos) == enviados >= 1
    assert frames["sent"] + frames["skipped"] <= frames["captured"]


# ── C2: el cliente solo puede ser 0 o 1 ──────────────────────────────────────

def test_c2_sin_cliente_cero_con_cliente_uno(manager, guiones):
    async def escenario():
        await manager.start("0")
        sin_cliente = manager.get_metrics()["client"]
        await manager.connect_client("0", "c1")
        con_cliente = manager.get_metrics()["client"]
        await manager.disconnect_client("c1")
        de_nuevo_sin = manager.get_metrics()["client"]
        await cerrar(manager, guiones)
        return sin_cliente, con_cliente, de_nuevo_sin

    sin_cliente, con_cliente, de_nuevo_sin = run(escenario())

    assert sin_cliente["connected"] == 0 and sin_cliente["client_id"] is None
    assert con_cliente["connected"] == 1 and con_cliente["client_id"] == "c1"
    assert con_cliente["connected_since"] is not None
    assert de_nuevo_sin["connected"] == 0 and de_nuevo_sin["connected_since"] is None


def test_c2_bajo_concurrencia_nunca_hay_mas_de_un_cliente(manager, guiones):
    observados: list[int] = []
    resultados = {"aceptados": 0, "rechazados": 0}

    async def muestreo(alto: asyncio.Event) -> None:
        while not alto.is_set():
            observados.append(manager.get_metrics()["client"]["connected"])
            await asyncio.sleep(0)

    async def cliente(nombre: str) -> None:
        for _ in range(4):
            try:
                await manager.connect_client("0", nombre)
            except SessionBusyError:
                resultados["rechazados"] += 1
                await asyncio.sleep(0.001)
                continue
            resultados["aceptados"] += 1
            await asyncio.sleep(0.002)
            await manager.disconnect_client(nombre)

    async def escenario():
        alto = asyncio.Event()
        muestra = asyncio.create_task(muestreo(alto))
        await asyncio.gather(*(cliente(f"c{i}") for i in range(8)))
        alto.set()
        await muestra
        await cerrar(manager, guiones)
        return manager.get_metrics()["client"]

    final = run(escenario())

    assert set(observados) <= {0, 1}
    assert 1 in observados
    assert final["connections_total"] == resultados["aceptados"]
    assert final["rejections_total"] == resultados["rechazados"]


# ── C3: sin credenciales ni datos sensibles ──────────────────────────────────

@pytest.mark.parametrize(
    "fuente, esperado",
    [
        ("0", "0"),
        ("C:/videos/linea1.mp4", "C:/videos/linea1.mp4"),
        ("rtsp://10.0.0.5/stream", "rtsp://10.0.0.5/stream"),
        ("rtsp://admin:clave@10.0.0.5:554/stream", "rtsp://***@10.0.0.5:554/stream"),
        ("rtsp://soloUsuario@10.0.0.5/s", "rtsp://***@10.0.0.5/s"),
        ("rtsp://u:p@ss@10.0.0.5/s", "rtsp://***@10.0.0.5/s"),
        ("http://h/v?canal=2&password=x&api_token=y", "http://h/v?canal=2&password=***&api_token=***"),
    ],
)
def test_c3_enmascaramiento_de_fuentes(fuente, esperado):
    assert redact_source(fuente) == esperado


def test_c3_enmascaramiento_en_texto_libre():
    texto = f"No se pudo conectar a {URL_SECRETA} (timeout); reintente con http://u:p@h/x?key=z"
    limpio = redact_text(texto, URL_SECRETA)
    assert sin_secretos(limpio)
    assert "p@h" not in limpio and "key=z" not in limpio
    assert "10.0.0.5" in limpio  # se conserva lo útil para diagnosticar


def test_c3_el_driver_recibe_la_url_real_pero_ninguna_salida_la_contiene(manager, guiones, caplog):
    guiones.append((["ok"] * 3 + ["error"] * 2, "block"))
    caplog.set_level(logging.DEBUG)

    async def escenario():
        await manager.connect_client(URL_SECRETA, "c1")
        await esperar_guion(guiones.capturas[0])
        salidas = (manager.get_metrics(), manager.get_status(), manager.get_lifecycle_status())
        await cerrar(manager, guiones)
        return salidas + (manager.get_metrics(), manager.get_lifecycle_status())

    salidas = run(escenario())

    assert guiones.capturas[0].source == URL_SECRETA      # la cámara se abrió con la URL real
    assert sin_secretos(*salidas)
    assert sin_secretos(caplog.text)
    assert "10.0.0.5" in json.dumps(salidas[0])            # la fuente sigue identificable


def test_c3_errores_al_abrir_no_filtran_credenciales(monkeypatch, manager, caplog):
    def driver_que_falla(source: str):
        raise ConnectionError(f"no se pudo conectar a {source}")

    monkeypatch.setattr(manager_module, "open_camera", driver_que_falla)
    caplog.set_level(logging.DEBUG)

    with pytest.raises(SessionCameraError) as info:
        run(manager.connect_client(URL_SECRETA, "c1"))

    assert sin_secretos(str(info.value), caplog.text, manager.get_lifecycle_status())


def test_c3_websocket_y_rest_no_devuelven_credenciales(monkeypatch, manager, guiones):
    monkeypatch.setattr(stream_router, "camera_session_manager", manager)
    monkeypatch.setattr(cameras_router, "camera_session_manager", manager)
    app = FastAPI()
    app.include_router(stream_router.router)
    app.include_router(cameras_router.router)
    respuestas = []

    with TestClient(app) as client:
        with client.websocket_connect("/ws/stream", params={"camera_id": URL_SECRETA}) as ws:
            bienvenida = ws.receive_json()
            frame = ws.receive_bytes()
            longitud = int.from_bytes(frame[:4], "big")
            metadatos = json.loads(frame[4:4 + longitud])

            with client.websocket_connect("/ws/stream", params={"camera_id": URL_SECRETA}) as otro:
                respuestas.append(otro.receive_json())       # CAMERA_BUSY
            respuestas.append(client.get("/cameras/session").json())
            respuestas.append(client.get("/cameras/metrics").json())
        respuestas.append(client.post("/cameras/session/start", params={"camera_id": URL_SECRETA}).json())
        respuestas.append(client.post("/cameras/session/start", params={"camera_id": URL_SECRETA}).json())
        guiones.fin.set()

    assert bienvenida["camera_id"] == redact_source(URL_SECRETA)
    assert metadatos["camera_id"] == redact_source(URL_SECRETA)
    assert respuestas[0]["error"] == "CAMERA_BUSY"
    assert respuestas[-1]["error"] == "SESSION_ALREADY_ACTIVE"
    assert sin_secretos(bienvenida, metadatos, *respuestas)


# ── Endpoint ──────────────────────────────────────────────────────────────────

def test_endpoint_de_metricas_tiene_estructura_estable(monkeypatch, manager, guiones):
    monkeypatch.setattr(cameras_router, "camera_session_manager", manager)
    app = FastAPI()
    app.include_router(cameras_router.router)

    with TestClient(app) as client:
        cuerpo = client.get("/cameras/metrics").json()

    assert cuerpo["error"] is None
    datos = cuerpo["data"]
    assert set(datos) == {
        "timestamp", "camera", "client", "frames", "recoveries", "errors",
        "last_error", "service",
    }
    assert set(datos["frames"]["session"]) == {"captured", "dropped", "sent", "skipped"}
    assert datos["client"]["connected"] == 0
    assert datos["last_error"] is None
