"""
Restricciones operativas del servidor.

Cada constante controla un aspecto independiente del sistema.
Para habilitar concurrencia multi-cámara o multi-cliente en el futuro
basta con ajustar los valores aquí y actualizar CameraSessionManager
para gestionar una colección de sesiones en lugar de una sola.
"""

# ── Concurrencia ──────────────────────────────────────────────────────────────
MAX_CONCURRENT_CAMERAS: int = 1   # fuentes de video abiertas simultáneamente
MAX_CONCURRENT_CLIENTS: int = 1   # clientes WebSocket activos simultáneamente

# ── Historial de errores ──────────────────────────────────────────────────────
MAX_ERROR_HISTORY: int = 50       # errores almacenados por sesión (circular)

# ── Métricas ──────────────────────────────────────────────────────────────────
FPS_WINDOW_FRAMES: int = 30       # tamaño de ventana deslizante para FPS promedio

# ── Watchdog ──────────────────────────────────────────────────────────────────
FRAME_STALE_TIMEOUT_S: float = 5.0   # segundos sin frames antes de considerar stream congelado

# ── Rendimiento ───────────────────────────────────────────────────────────────
TARGET_FPS: int = 30              # FPS objetivo del loop de captura
