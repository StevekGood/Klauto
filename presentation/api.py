import asyncio
import os
import hmac
import hashlib
import json
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Query, Header, status
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from application.planning import PlanRunner, UserSession
from application.services import FarmService
from application.tasks import (
    CollectFactoriesTask, CollectGreenhouseFactoriesTask, VisitAndDigNeighborPlayers
)
from infrastructure.http_client import KlondikeGameClient
from infrastructure.file_repository import FileFarmRepository
from infrastructure.logger import get_logger

from presentation.telegram_user_database import TelegramUserDatabase

logger = get_logger()
tg_user_database = TelegramUserDatabase((os.environ.get("TG_USER_WHITELIST") or "").split(","), (os.environ.get("TG_USER_BLACKLIST") or "").split(","))
runner = PlanRunner(logger, asyncio.Semaphore(5))
repository = FileFarmRepository()
farm_service = FarmService(logger)

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    logger.log_truncated("System", "shutting_down")

API_TOKEN = os.environ.get("SECRET_API_TOKEN")

app = FastAPI(title="Klondike Automation API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def handle_telegram_user_register(tg_user, user_id, auth_key):
    if not tg_user or not user_id or not auth_key or not tg_user_database.register(tg_user.get("id"), user_id, auth_key):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad registration request")

    client = KlondikeGameClient(user_id, auth_key, logger=logger)
    session = UserSession(
        user_id=user_id,
        game_client=client,
        repository=repository,
        logger=logger,
        farm_service=farm_service
    )
    runner.register_user(user_id, session)

    default_master_plan = session.create_plan("Default Automation")
    default_master_plan.id = "master_plan"
    default_master_plan.interval_seconds = 600
    default_master_plan.tasks = [
        CollectFactoriesTask(target_type="all-no-greenhouses", repeat_on_pick=True),
        CollectGreenhouseFactoriesTask(
            repeat_on_pick=True,
            consumable_energy_item={
                "item_id": "CR_EXP_APPLE",
                "energy_per_item": 2
            }
        )
    ]
    session.plans[default_master_plan.id] = default_master_plan
    logger.log_truncated("System", "auto_created_master_plan", user=user_id)

    default_action_plan = session.create_plan("Default Action")
    default_action_plan.id = "action_plan"
    default_action_plan.interval_seconds = -1
    default_action_plan.tasks = [
        VisitAndDigNeighborPlayers("granary", "main", True)
    ]
    session.plans[default_action_plan.id] = default_action_plan
    logger.log_truncated("System", "auto_created_action_plan", user=user_id)

    return {
        "isAuth": True
    }

def verify_and_get_telegram_user(authorization_header: str) -> dict:
    if not authorization_header or not authorization_header.startswith("tma "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Missing Telegram authorization data"
        )
    
    init_data = authorization_header[4:]
    if init_data == "missing_telegram_init_data":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing telegram init data")

    parsed_data = dict(parse_qsl(init_data))
    if "hash" not in parsed_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing hash")
        
    received_hash = parsed_data.pop("hash")
    data_check_string = "\n".join([f"{k}={v}" for k, v in sorted(parsed_data.items())])
    secret_key = hmac.new(b"WebAppData", API_TOKEN.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Security error")
        
    user_data = json.loads(parsed_data.get("user", "{}"))
    return user_data

@app.post("/auth")
async def auth(authorization: str = Header(None)):
    tg_user = verify_and_get_telegram_user(authorization)
    tg_user_id = tg_user.get("id")
    print(f"Auth Telegram ID: {tg_user_id}")
    
    if tg_user_database.get_user(tg_user_id):
        return {"isAuth": True}
    else:
        return {"isAuth": False}


class RegisterSchema(BaseModel):
    userId: str
    authKey: str


@app.post("/register")
async def register(payload: RegisterSchema, authorization: str = Header(None)):
    tg_user = verify_and_get_telegram_user(authorization)
    tg_user_id = tg_user.get("id")
    user_input_id = payload.userId
    user_input_auth_key = payload.authKey
    print(f"Register Telegram ID: {tg_user_id}, user ID: {user_input_id}, auth key: {user_input_auth_key}")  
    return handle_telegram_user_register(tg_user, user_input_id, user_input_auth_key)

LEGACY_API_TOKEN = os.environ.get("LEGACY_API_TOKEN")

@app.get("/")
async def root(token: str = Query(...), user_id: str = Query(...)):
    if token != LEGACY_API_TOKEN:
        raise HTTPException(status_code=403)
    session = runner.sessions.get(user_id)
    if not session:
        return {"status": "not_registered"}
    return {"status": "ok", "energy": session.state.energy if session.state else None}

@app.get("/start")
async def start(token: str = Query(...), user_id: str = Query(...), plan_id: str = Query(...)):
    if token != LEGACY_API_TOKEN:
        raise HTTPException(403)
    if user_id not in runner.sessions:
        raise HTTPException(404, "User not registered")
    await runner.start_plan(user_id, plan_id)
    return {"message": "Plan started"}


@app.get("/stop")
async def stop(token: str = Query(...), user_id: str = Query(...), plan_id: str = Query(...)):
    if token != LEGACY_API_TOKEN:
        raise HTTPException(403)
    if user_id not in runner.sessions:
        raise HTTPException(404, "User not registered")
    await runner.stop_plan(user_id, plan_id)
    return {"message": "Plan stopped"}


@app.get("/logs")
async def get_logs(token: str = Query(...), log_type: str = "truncated"):
    if token != LEGACY_API_TOKEN:
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