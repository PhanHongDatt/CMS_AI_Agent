"""GET /autonomy — view per-action-type autonomy levels."""

from fastapi import APIRouter, Depends

from api.deps import get_autonomy_registry
from core.autonomy.level import AutonomyRegistry

router = APIRouter(prefix="/autonomy", tags=["autonomy"])


@router.get("")
async def get_autonomy(
    registry: AutonomyRegistry = Depends(get_autonomy_registry),
) -> dict:
    return registry.get_summary()
