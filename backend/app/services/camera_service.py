
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Optional

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

    Si la fuente no llega a abrirse, el objeto de OpenCV se libera aquí mismo:
    así ningún intento fallido deja un manejador del dispositivo colgado.
    """
    if source.isdigit():
        cam: CameraCapture = OpenCVCapture(int(source))
    elif source.startswith("rtsp://") or source.startswith("rtmp://"):
        cam = RTSPCapture(source)
    else:
        cam = FileCapture(source)

    if cam.is_opened:
        return cam

    cam.release()
    return None


def detect_available_cameras(
    max_index: int = 4,
    exclude: Optional[Iterable[str]] = None,
) -> list[dict]:
    skip = set(exclude or ())
    result = []
    for i in range(max_index):
        if str(i) in skip:
            continue
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
