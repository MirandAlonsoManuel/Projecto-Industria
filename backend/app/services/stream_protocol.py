"""
Serialización de mensajes del stream WebSocket.

Formato binario por mensaje:
  [4 bytes uint32 big-endian = longitud JSON] [JSON metadata UTF-8] [JPEG bytes]
"""

from __future__ import annotations

import json
import struct
import time
from typing import Optional

import cv2
import numpy as np


def encode_ws_message(
    frame: np.ndarray,
    detections: list,
    fps: float,
    camera_id: str,
    jpeg_quality: int = 70,
    seq: int = 0,
    captured_at: Optional[float] = None,
) -> bytes:
    """
    Serializa frame + metadatos al protocolo binario del WebSocket.

    `timestamp` es el instante de captura del frame cuando se conoce (si no,
    el de serialización), de modo que el cliente pueda medir la latencia real
    de extremo a extremo.
    """
    metadata = {
        "connected": True,
        "camera_id": camera_id,
        "fps": round(fps, 2),
        "timestamp": captured_at if captured_at is not None else time.time(),
        "seq": seq,
        "detections": detections,
    }
    json_bytes = json.dumps(metadata).encode("utf-8")
    header = struct.pack(">I", len(json_bytes))
    _, jpeg_buf = cv2.imencode(
        ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
    )
    return header + json_bytes + jpeg_buf.tobytes()
