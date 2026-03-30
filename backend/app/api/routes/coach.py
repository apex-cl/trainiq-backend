from typing import AsyncGenerator, Union
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.database import async_session, get_db
from app.api.dependencies import get_current_user, get_current_user_or_guest
from app.models.user import User
from app.models.guest import GuestSession
from app.services.coach_agent import CoachAgent
from app.services.ai_memory import AIMemoryService
from app.core.config import settings

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class ChatRequest(BaseModel):
    message: str
    extra_context: str | None = None  # z.B. Mahlzeit-Analyse-Ergebnis


async def _stream_with_own_session(
    message: str, user_id: str, extra_context: str | None = None
) -> AsyncGenerator[str, None]:
    from app.services.langchain_agent import LangChainCoachAgent

    async with async_session() as db:
        agent = LangChainCoachAgent()
        full_message = message
        if extra_context:
            full_message = (
                f"{message}\n\n[Zusatz-Kontext für den Coach]:\n{extra_context}"
            )
        async for chunk in agent.stream(full_message, user_id, db):
            yield chunk
        await db.commit()


@router.post("/chat")
@limiter.limit("30/minute")
async def chat(
    request: Request,
    chat_request: ChatRequest,
    current: Union[User, GuestSession] = Depends(get_current_user_or_guest),
    db: AsyncSession = Depends(get_db),
):
    """Send a message to the AI coach. Returns SSE stream. Gäste haben Nachrichten-Limit."""
    if not settings.active_llm_api_key:
        raise HTTPException(status_code=503, detail="Coach nicht konfiguriert")

    is_guest = isinstance(current, GuestSession)

    if is_guest:
        if current.message_count >= settings.guest_max_messages:
            raise HTTPException(
                status_code=403,
                detail=f"Gast-Limit erreicht ({settings.guest_max_messages} Nachrichten). Bitte registrieren für mehr.",
            )
        # Atomic increment für Race Condition Prevention
        await db.execute(
            update(GuestSession)
            .where(GuestSession.id == current.id)
            .values(message_count=GuestSession.message_count + 1)
        )
        await db.commit()
        # Lokalen State aktualisieren für Response
        current.message_count += 1
        user_id = f"guest:{current.id}"
    else:
        user_id = str(current.id)

    return StreamingResponse(
        _stream_with_own_session(
            chat_request.message,
            user_id,
            extra_context=chat_request.extra_context,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            **(
                {
                    "X-Guest-Messages-Remaining": str(
                        settings.guest_max_messages - current.message_count
                    )
                }
                if is_guest
                else {}
            ),
        },
    )


@router.get("/history")
async def history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the last 50 coach conversation messages."""
    agent = CoachAgent()
    messages = await agent.get_history(str(current_user.id), db)
    return messages


@router.delete("/history")
async def delete_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete all coach conversation history."""
    agent = CoachAgent()
    await agent.clear_history(str(current_user.id), db)
    return {"status": "deleted"}


# ─── AI Memory (Long-Term) ────────────────────────────────────────────────────


@router.get("/memories")
async def get_memories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Gibt alle Langzeit-Erinnerungen der KI zurück."""
    memory_service = AIMemoryService()
    memories = await memory_service.get_all_memories(str(current_user.id), db)
    return {"memories": memories, "count": len(memories)}


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Löscht eine spezifische Erinnerung."""
    memory_service = AIMemoryService()
    await memory_service.delete_memory(memory_id, str(current_user.id), db)
    return {"status": "deleted"}


@router.delete("/memories")
async def clear_memories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Löscht alle Langzeit-Erinnerungen."""
    memory_service = AIMemoryService()
    await memory_service.clear_all_memories(str(current_user.id), db)
    return {"status": "all_deleted"}


# ─── Meal Plan ────────────────────────────────────────────────────────────────


class MealPlanRequest(BaseModel):
    kalorien_ziel: int = 2200
    protein_ziel_g: int = 150


@router.post("/meal-plan")
@limiter.limit("5/minute")
async def generate_meal_plan(
    request: Request,
    meal_request: MealPlanRequest,
    current_user: User = Depends(get_current_user),
):
    """Generiert einen 7-Tage Speiseplan mit Rezepten via KI."""
    if not settings.active_llm_api_key:
        raise HTTPException(status_code=503, detail="Coach nicht konfiguriert")
    from app.services.meal_planner import MealPlanner

    planner = MealPlanner()
    meal_plan = await planner.generate_weekly_plan(
        str(current_user.id), meal_request.kalorien_ziel, meal_request.protein_ziel_g
    )
    return {"meal_plan": meal_plan}


@router.get("/nutrition-gaps")
async def get_nutrition_gaps(
    kalorien_ziel: int = 2200,
    protein_ziel_g: int = 150,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Analysiert Nährstofflücken und gibt Lebensmittelempfehlungen."""
    from app.services.meal_planner import MealPlanner
    from app.models.nutrition import NutritionLog
    from datetime import datetime, timedelta, timezone

    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    result = await db.execute(
        select(NutritionLog).where(
            NutritionLog.user_id == current_user.id,
            NutritionLog.logged_at >= seven_days_ago,
        )
    )
    logs = result.scalars().all()
    days = len(logs) or 1  # Vermeidet Division durch Null
    avg_cal = sum(n.calories or 0 for n in logs) / days
    avg_protein = sum(n.protein_g or 0 for n in logs) / days
    avg_carbs = sum(n.carbs_g or 0 for n in logs) / days
    avg_fat = sum(n.fat_g or 0 for n in logs) / days
    planner = MealPlanner()
    analysis = await planner.analyze_nutrient_gaps(
        avg_cal, avg_protein, avg_carbs, avg_fat, kalorien_ziel, protein_ziel_g
    )
    return {
        "analysis": analysis,
        "averages": {
            "kalorien": round(avg_cal),
            "protein_g": round(avg_protein, 1),
            "kohlenhydrate_g": round(avg_carbs, 1),
            "fett_g": round(avg_fat, 1),
        },
    }


@router.post("/trigger-monitor")
async def trigger_monitor(
    current_user: User = Depends(get_current_user),
):
    """Triggert den autonomen Monitor manuell (für Tests). Nur im Dev-Modus verfügbar."""
    if not settings.dev_mode:
        raise HTTPException(status_code=403, detail="Nur im Dev-Modus verfügbar")
    from app.services.autonomous_monitor import run_autonomous_monitor
    import asyncio

    asyncio.create_task(run_autonomous_monitor())
    return {"status": "Monitor gestartet (läuft im Hintergrund)"}
