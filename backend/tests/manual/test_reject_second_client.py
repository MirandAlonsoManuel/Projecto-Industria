"""
Prueba manual: verifica que un segundo cliente conectándose a la misma
cámara es rechazado (código 1013) mientras el primero sigue activo.

Requiere:
    pip install websockets

Uso:
    1. Levanta el servidor en otra terminal: uvicorn app.main:app --reload
    2. Ajusta CAMERA_ID abajo (índice USB real, o ruta a un archivo de video
       si no tienes webcam a la mano — camera_service.py acepta ambos).
    3. Corre este script: python tests/manual/test_reject_second_client.py
"""

import asyncio

import websockets

CAMERA_ID = "0"
URL = f"ws://127.0.0.1:8000/ws/stream?camera_id={CAMERA_ID}"


async def client_a() -> None:
    print("[Cliente A] conectando...")
    async with websockets.connect(URL) as ws:
        first = await ws.recv()
        print(f"[Cliente A] primer mensaje: {first}")

        for i in range(5):
            msg = await ws.recv()
            kind = "texto/JSON" if isinstance(msg, str) else f"binario ({len(msg)} bytes)"
            print(f"[Cliente A] mensaje {i + 1}: {kind}")

        print("[Cliente A] sigo conectado 5s más para que Cliente B choque...")
        await asyncio.sleep(5)
    print("[Cliente A] desconectado limpiamente.")


async def client_b() -> None:
    # Espera a que A ya esté recibiendo frames antes de intentar conectar.
    await asyncio.sleep(2)
    print("[Cliente B] intentando conectar (debería ser rechazado)...")
    try:
        async with websockets.connect(URL) as ws:
            msg = await ws.recv()
            print(f"[Cliente B] mensaje recibido: {msg}")
            # Si llega aquí sin excepción, el servidor debería cerrar
            # la conexión justo después de este mensaje de rechazo.
            await ws.wait_closed()
            print(
                f"[Cliente B] conexión cerrada por el servidor: "
                f"code={ws.close_code}, reason={ws.close_reason}"
            )
    except websockets.exceptions.ConnectionClosed as e:
        print(f"[Cliente B] conexión cerrada: code={e.code}, reason={e.reason}")


async def main() -> None:
    await asyncio.gather(client_a(), client_b())


if __name__ == "__main__":
    asyncio.run(main())
