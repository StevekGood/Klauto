import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from application.planning import PlanRunner, UserSession
from application.services import FarmService
from application.tasks import CollectFactoriesTask, CollectGreenhouseFactoriesTask
from infrastructure.http_client import KlondikeGameClient
from infrastructure.file_repository import FileFarmRepository
from infrastructure.logger import get_logger

logger = get_logger()
runner = PlanRunner(logger, asyncio.Semaphore(5))
repository = FileFarmRepository()
farm_service = FarmService(logger)

API_TOKEN = os.environ.get("SECRET_API_TOKEN", "secret")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("AUTO_CREATE_MASTER_PLAN", "").lower() == "true":
        user_id = os.environ.get("KLONDIKE_USER_ID")
        auth_key = os.environ.get("KLONDIKE_AUTH_KEY")
        if user_id and auth_key:
            client = KlondikeGameClient(user_id, auth_key, logger=logger)
            session = UserSession(
                user_id=user_id,
                game_client=client,
                repository=repository,
                logger=logger,
                farm_service=farm_service
            )
            print("registered")
            runner.register_user(user_id, session)

            plan = session.create_plan("Default Automation")
            plan.id = "master_plan"
            plan.interval_seconds = 600
            plan.tasks = [
                CollectFactoriesTask(target_type="all-no-greenhouses", repeat_on_pick=True),
                CollectGreenhouseFactoriesTask(
                    repeat_on_pick=True,
                    consumable_energy_item={
                        "item_id": "CR_EXP_APPLE",
                        "energy_per_item": 2
                    }
                )
            ]
            session.plans[plan.id] = plan
            logger.log_truncated("System", "auto_created_master_plan", user=user_id)
        else:
            logger.log_truncated("System", "auto_create_master_plan_missing_env_vars")

    yield
    logger.log_truncated("System", "shutting_down")


app = FastAPI(title="Klondike Automation API", lifespan=lifespan)


@app.get("/")
async def root(token: str = Query(...), user_id: str = Query(...)):
    if token != API_TOKEN:
        raise HTTPException(status_code=403)
    session = runner.sessions.get(user_id)
    if not session:
        return {"status": "not_registered"}
    return {"status": "ok", "energy": session.state.energy if session.state else None}


@app.get("/register")
async def register(token: str = Query(...), user_id: str = Query(...), auth_key: str = Query(...)):
    if token != API_TOKEN:
        raise HTTPException(403)
    client = KlondikeGameClient(user_id, auth_key, logger=logger)
    session = UserSession(
        user_id=user_id,
        game_client=client,
        repository=repository,
        logger=logger,
        farm_service=farm_service
    )
    runner.register_user(user_id, session)
    return {"message": f"User {user_id} registered"}


@app.get("/start")
async def start(token: str = Query(...), user_id: str = Query(...), plan_id: str = Query(...)):
    if token != API_TOKEN:
        raise HTTPException(403)
    if user_id not in runner.sessions:
        raise HTTPException(404, "User not registered")
    await runner.start_plan(user_id, plan_id)
    return {"message": "Plan started"}


@app.get("/stop")
async def stop(token: str = Query(...), user_id: str = Query(...), plan_id: str = Query(...)):
    if token != API_TOKEN:
        raise HTTPException(403)
    if user_id not in runner.sessions:
        raise HTTPException(404, "User not registered")
    await runner.stop_plan(user_id, plan_id)
    return {"message": "Plan stopped"}


@app.get("/logs")
async def get_logs(token: str = Query(...), log_type: str = "truncated"):
    if token != API_TOKEN:
        raise HTTPException(403)
    if log_type == "truncated":
        path = "logs/truncated.log"
    elif log_type == "full":
        path = "logs/full.log"
    else:
        raise HTTPException(400, "Invalid log type")
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, media_type="text/plain")