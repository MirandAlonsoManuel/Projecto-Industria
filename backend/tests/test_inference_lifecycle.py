"""
Pruebas de `InferenceEngineLifecycle` (E02), usando exclusivamente
`SimulatedInferenceEngine` (E01). Ningún modelo real ni cámara física.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.services.inference_engine import EngineLoadError, EngineState, SimulatedInferenceEngine
from app.services.inference_lifecycle import InferenceEngineLifecycle, LifecycleState


class _CountingSimulatedEngine(SimulatedInferenceEngine):
    """Motor simulado que cuenta cuántas veces se invocó load() de verdad."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.load_calls = 0

    def load(self) -> None:
        self.load_calls += 1
        super().load()


class _SlowLoadEngine(SimulatedInferenceEngine):
    """
    Motor simulado cuya carga tarda un poco (bloqueando el hilo del
    executor, no el event loop). Existe solo para la prueba de
    cancelación: sin esta demora, `task.cancel()` llamado inmediatamente
    después de crear la tarea cancela ANTES de que `initialize()` llegue
    a ejecutar una sola línea — no probaría nada sobre la cancelación en
    sí, solo que una tarea nunca iniciada no corre.
    """

    def load(self) -> None:
        time.sleep(0.2)
        super().load()


# ─────────────────────────────────────────────────────────────────────────
# Inicialización correcta
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inicializacion_correcta_transiciona_a_available():
    lifecycle = InferenceEngineLifecycle(SimulatedInferenceEngine())

    assert lifecycle.get_status().state == LifecycleState.NOT_INITIALIZED

    await lifecycle.initialize()

    status = lifecycle.get_status()
    assert status.state == LifecycleState.AVAILABLE
    assert status.loaded_at is not None
    assert status.last_error is None


# ─────────────────────────────────────────────────────────────────────────
# Inicios repetidos (secuenciales y concurrentes)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inicios_repetidos_secuenciales_no_recargan_el_motor():
    engine = _CountingSimulatedEngine()
    lifecycle = InferenceEngineLifecycle(engine)

    await lifecycle.initialize()
    await lifecycle.initialize()
    await lifecycle.initialize()

    assert engine.load_calls == 1
    assert lifecycle.get_status().state == LifecycleState.AVAILABLE


@pytest.mark.asyncio
async def test_inicios_concurrentes_no_recargan_el_motor():
    engine = _CountingSimulatedEngine()
    lifecycle = InferenceEngineLifecycle(engine)

    await asyncio.gather(
        lifecycle.initialize(),
        lifecycle.initialize(),
        lifecycle.initialize(),
    )

    assert engine.load_calls == 1
    assert lifecycle.get_status().state == LifecycleState.AVAILABLE


# ─────────────────────────────────────────────────────────────────────────
# Carga fallida
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_carga_fallida_transiciona_a_error_y_no_deja_recursos():
    engine = SimulatedInferenceEngine(fail_on_load=True)
    lifecycle = InferenceEngineLifecycle(engine)

    with pytest.raises(EngineLoadError):
        await lifecycle.initialize()

    status = lifecycle.get_status()
    assert status.state == LifecycleState.ERROR
    assert status.last_error is not None

    # El motor subyacente no debe quedar con recursos a medio asignar:
    # la limpieza defensiva lo deja en UNLOADED.
    assert engine.get_status().state == EngineState.UNLOADED


@pytest.mark.asyncio
async def test_reintento_tras_error_puede_tener_exito():
    engine = SimulatedInferenceEngine(fail_on_load=True)
    lifecycle = InferenceEngineLifecycle(engine)

    with pytest.raises(EngineLoadError):
        await lifecycle.initialize()
    assert lifecycle.get_status().state == LifecycleState.ERROR

    engine._fail_on_load = False  # simula que la causa del fallo ya no aplica
    await lifecycle.initialize()

    assert lifecycle.get_status().state == LifecycleState.AVAILABLE


# ─────────────────────────────────────────────────────────────────────────
# Cierre: normal, repetido, tras error
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cierre_idempotente_sin_haber_inicializado():
    lifecycle = InferenceEngineLifecycle(SimulatedInferenceEngine())

    await lifecycle.shutdown()  # no debe lanzar, aunque nunca se inicializó

    assert lifecycle.get_status().state == LifecycleState.CLOSED


@pytest.mark.asyncio
async def test_cierre_idempotente_llamado_dos_veces():
    lifecycle = InferenceEngineLifecycle(SimulatedInferenceEngine())
    await lifecycle.initialize()

    await lifecycle.shutdown()
    await lifecycle.shutdown()  # segunda llamada: no debe fallar

    assert lifecycle.get_status().state == LifecycleState.CLOSED


@pytest.mark.asyncio
async def test_cierre_despues_de_error_transiciona_a_closed():
    engine = SimulatedInferenceEngine(fail_on_load=True)
    lifecycle = InferenceEngineLifecycle(engine)

    with pytest.raises(EngineLoadError):
        await lifecycle.initialize()

    await lifecycle.shutdown()  # debe poder cerrarse aunque quedó en ERROR

    assert lifecycle.get_status().state == LifecycleState.CLOSED


@pytest.mark.asyncio
async def test_initialize_despues_de_closed_lanza_error():
    lifecycle = InferenceEngineLifecycle(SimulatedInferenceEngine())
    await lifecycle.initialize()
    await lifecycle.shutdown()

    with pytest.raises(RuntimeError):
        await lifecycle.initialize()


# ─────────────────────────────────────────────────────────────────────────
# Cancelación durante la carga
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancelacion_durante_initialize_transiciona_a_error():
    engine = _SlowLoadEngine()  # load() tarda 0.2s en un hilo real
    lifecycle = InferenceEngineLifecycle(engine)

    task = asyncio.ensure_future(lifecycle.initialize())
    await asyncio.sleep(0.05)  # dejar que initialize() entre a run_in_executor
    assert lifecycle.get_status().state == LifecycleState.LOADING  # confirma que ya estaba en curso
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    status = lifecycle.get_status()
    assert status.state == LifecycleState.ERROR

    # Clave: el motor subyacente debe quedar REALMENTE sin recursos
    # (UNLOADED) en este punto, no solo el wrapper reportando ERROR.
    # Si initialize() hubiera cerrado el motor antes de que el hilo de
    # fondo (todavía con ~0.15s por correr) terminara, ese hilo habría
    # sobrescrito el estado a LOADED después del cierre — dejando el
    # motor cargado aunque el ciclo de vida diga lo contrario. Esta
    # aserción es la que detecta esa condición de carrera.
    assert engine.get_status().state == EngineState.UNLOADED

    # Debe poder cerrarse sin problema después de una inicialización cancelada.
    await lifecycle.shutdown()
    assert lifecycle.get_status().state == LifecycleState.CLOSED
    assert engine.get_status().state == EngineState.UNLOADED


# ─────────────────────────────────────────────────────────────────────────
# Reinicio con una nueva instancia
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reinicio_con_nueva_instancia_funciona_independientemente():
    first = InferenceEngineLifecycle(SimulatedInferenceEngine())
    await first.initialize()
    await first.shutdown()
    assert first.get_status().state == LifecycleState.CLOSED

    second = InferenceEngineLifecycle(SimulatedInferenceEngine())
    await second.initialize()

    assert second.get_status().state == LifecycleState.AVAILABLE
    # La segunda instancia es independiente: cerrar la primera no la afecta.
    assert first.get_status().state == LifecycleState.CLOSED
