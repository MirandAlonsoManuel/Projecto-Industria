"""
Abstracción de hardware de cámara y utilidades del pipeline de captura.

Implementa el patrón Strategy (CameraCapture) para desacoplar la lógica
de streaming de la fuente de video concreta (USB, RTSP, archivo).
"""

from __future__ import annotations

import json
import struct
import time
from abc import ABC, abstractmethod
from typing import Optional

import cv2
import numpy as np

_BACKEND = cv2.CAP_ANY


class CameraCapture(ABC):
    """Interfaz unificada para cualquier fuente de video."""

    @abstractmethod
    def read_frame(self) -> Optional[np.ndarray]:
        """Captura y retorna el frame más reciente, o None si falla."""

    @abstractmethod
    def release(self) -> None:
        """Libera los recursos asociados a la cámara."""

    @property
    @abstractmethod
    def is_opened(self) -> bool:
        """Indica si la fuente de video está activa."""


class OpenCVCapture(CameraCapture):
    """Adaptador para cámaras USB industriales y webcams."""

    def __init__(self, index: int = 0) -> None:
        self._cap = cv2.VideoCapture(index, _BACKEND)
        self._index = index

    def read_frame(self) -> Optional[np.ndarray]:
        ret, frame = self._cap.read()
        return frame if ret else None

    def release(self) -> None:
        self._cap.release()

    @property
    def is_opened(self) -> bool:
        return self._cap.isOpened()


class RTSPCapture(CameraCapture):
    """Adaptador para cámaras IP y NVRs via RTSP."""

    def __init__(self, url: str) -> None:
        self._cap = cv2.VideoCapture(url)
        self._url = url

    def read_frame(self) -> Optional[np.ndarray]:
        ret, frame = self._cap.read()
        return frame if ret else None

    def release(self) -> None:
        self._cap.release()

    @property
    def is_opened(self) -> bool:
        return self._cap.isOpened()


class FileCapture(CameraCapture):
    """Adaptador para archivos de video — modo simulado en desarrollo."""

    def __init__(self, path: str) -> None:
        self._cap = cv2.VideoCapture(path)

    def read_frame(self) -> Optional[np.ndarray]:
        ret, frame = self._cap.read()
        if not ret:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self._cap.read()
        return frame if ret else None

    def release(self) -> None:
        self._cap.release()

    @property
    def is_opened(self) -> bool:
        return self._cap.isOpened()


def open_camera(source: str) -> Optional[CameraCapture]:
    """
    Instancia el adaptador correcto según el tipo de fuente e intenta abrirla.

    Returns:
        CameraCapture abierta, o None si la fuente no está disponible.
    """
    if source.isdigit():
        cam: CameraCapture = OpenCVCapture(int(source))
    elif source.startswith("rtsp://") or source.startswith("rtmp://"):
        cam = RTSPCapture(source)
    else:
        cam = FileCapture(source)

    return cam if cam.is_opened else None


def detect_available_cameras(max_index: int = 4) -> list[dict]:
    """
    Prueba los primeros `max_index` índices USB y retorna los que abren.

    Nota: en Windows con DirectShow, probar índices inexistentes tarda ~500 ms
    cada uno, por eso el rango se limita a 4.
    """
    result = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, _BACKEND)
        if cap.isOpened():
            result.append(
                {
                    "id": str(i),
                    "type": "usb",
                    "source_url": str(i),
                    "status": "available",
                }
            )
        cap.release()
    return result


def encode_ws_message(
    frame: np.ndarray,
    detections: list,
    fps: float,
    camera_id: str,
    jpeg_quality: int = 70,
) -> bytes:
    """
    Serializa frame + metadatos al protocolo binario del WebSocket.

    Formato:
      [4 bytes uint32 BE — longitud del JSON] [JSON UTF-8] [JPEG bytes]
    """
    metadata = {
        "connected": True,
        "camera_id": camera_id,
        "fps": round(fps, 2),
        "timestamp": time.time(),
        "detections": detections,
    }
    json_bytes = json.dumps(metadata).encode("utf-8")
    header = struct.pack(">I", len(json_bytes))
    _, jpeg_buf = cv2.imencode(
        ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
    )
    return header + json_bytes + jpeg_buf.tobytes()
