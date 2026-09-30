"""
Router de diagnóstico y estado del servicio.

Agrupa los endpoints destinados a verificar la disponibilidad de la API,
utilizados típicamente por load balancers, orquestadores (k8s) y monitores.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get(
    "/signal",
    response_model=dict,
    summary="Verificar conectividad de la API",
    description=(
        "Endpoint de señal que confirma si la API está activa y respondiendo. "
        "Retorna `connected: true` cuando el servicio opera con normalidad."
    ),
)
def signal() -> dict:
    """
    Indica si la API está en línea y disponible.

    Returns:
        dict: `{"connected": true}` cuando el servicio responde correctamente.
    """
    return {"connected": True}
