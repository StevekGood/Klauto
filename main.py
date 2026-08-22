import asyncio
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import uvicorn

from dotenv import load_dotenv
load_dotenv() 

from farm_scheduler import FarmTaskScheduler, CollectFactoriesTask, CollectGreenhouseFactoriesTask

scheduler = FarmTaskScheduler()
API_TOKEN = os.environ.get("SECRET_API_TOKEN")
USER_ID = os.environ.get("KLONDIKE_USER_ID")
AUTH_KEY = os.environ.get("KLONDIKE_AUTH_KEY")

@asynccontextmanager
async def lifespan(app: FastAPI):
    if USER_ID and AUTH_KEY:
        print(f"[System]: Automatically registering master session for UID: {USER_ID}")
        session = scheduler.register_user(USER_ID, AUTH_KEY)
        plan = session.create_plan("Render Cloud Core Automation")
        plan.id = "master_plan" 
        session.plans["master_plan"] = plan
        plan.interval_seconds = 600
        plan.instructions.extend([
            CollectFactoriesTask(target_type="all-no-greenhouses", repeat_on_pick=True),
            CollectGreenhouseFactoriesTask(repeat_on_pick=True, consumable_energy_item={
                "item_id": "CR_MONKEYBREAD",
                "energy_per_item": 5
            })
        ])
        print("[System]: 'master_plan' successfully mapped inside user storage registry.")
        
    yield
    print("[System]: Web gateway shutting down. Sweeping session states...")

app = FastAPI(title="Multi-User Klondike Engine", lifespan=lifespan)

@app.get("/")
def read_root(token: str = Query(...), user_id: str = Query(...)):
    if token != API_TOKEN: raise HTTPException(status_code=403)
    session = scheduler.sessions.get(user_id)
    if not session: return {"status": "User session not initialized. Send /register or use login sequence."}
    return {
        "status": "online",
        "user_id": user_id,
        "level": session.data.level,
        "energy": session.data.energy
    }

@app.get("/register")
def register_new_user(token: str = Query(...), user_id: str = Query(...), auth_key: str = Query(...)):
    if token != API_TOKEN: raise HTTPException(status_code=403)
    session = scheduler.register_user(user_id, auth_key)
    plan = session.create_plan("Render Cloud Core Automation")
    plan.id = "master_plan" 
    session.plans["master_plan"] = plan
    plan.interval_seconds = 600
    plan.instructions.extend([
        CollectFactoriesTask(target_type="all-no-greenhouses", repeat_on_pick=True),
        CollectGreenhouseFactoriesTask(repeat_on_pick=True, consumable_energy_item={
            "item_id": "CR_MONKEYBREAD",
            "energy_per_item": 5
        })
    ])
    return {"message": f"User {user_id} successfully initialized in multi-threaded environment."}

@app.get("/start")
async def start_automation(token: str = Query(...), user_id: str = Query(...)):
    if token != API_TOKEN: raise HTTPException(status_code=403)
    session = scheduler.sessions.get(user_id)
    if not session: raise HTTPException(status_code=404, detail="User not registered")

    plan = session.plans.get("master_plan")
    if not plan: 
        raise HTTPException(status_code=404, detail="Automation plan 'master_plan' not found for this user.")

    if plan.is_active: 
        return {"message": "Already running."}
    
    asyncio.create_task(scheduler.start_plan_loop(user_id, "master_plan"))
    return {"message": f"Automation triggered for user {user_id}."}

@app.get("/stop")
async def stop_automation(token: str = Query(...), user_id: str = Query(...)):
    if token != API_TOKEN: 
        raise HTTPException(status_code=403, detail="Invalid API token.")
        
    session = scheduler.sessions.get(user_id)
    if not session:
        raise HTTPException(status_code=404, detail="User session not registered.")
    
    plan = session.plans.get("master_plan")
    if not plan:
        raise HTTPException(status_code=404, detail="Automation plan not found.")
        
    if not plan.is_active: 
        return {"message": f"Automation for user {user_id} is already in a resting status."}
        
    plan.is_active = False
    print(f"[Web Gateway]: Dispatched stop signal for user: {user_id}")
    return {"message": f"Halt signal received. Automation loop for user {user_id} will suspend immediately."}

@app.get("/view-logs")
def download_network_logs(token: str = Query(...)):
    if token != API_TOKEN: raise HTTPException(status_code=403)
    log_path = "client_network.log"
    if not os.path.exists(log_path): raise HTTPException(status_code=404)
    return FileResponse(path=log_path, filename="client_network.log", media_type="text/plain")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
