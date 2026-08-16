import asyncio
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
import uvicorn
from klone_game_client import KlondikeGameClient
from farm_data_manager import FarmDataManager
from farm_action_manager import FarmActionManager
from farm_scheduler import (
    FarmTaskScheduler, 
    HarvestGreenhousesTask, 
    DigGreenhousesTask, 
    PlantGreenhousesTask, 
    CollectFactoriesTask,
    CraftFactoryTask
)

API_TOKEN = os.environ.get("SECRET_API_TOKEN")

client = KlondikeGameClient() 
data = FarmDataManager()
actions = FarmActionManager(client, data)
scheduler = FarmTaskScheduler(client, data, actions)

global_plan = scheduler.create_plan("Render Cloud Core Automation")
global_plan.interval_seconds = 1800

global_plan.instructions.extend([
    HarvestGreenhousesTask(),
    DigGreenhousesTask(),
    PlantGreenhousesTask(recipe_id="P_WHEAT"),
    CollectFactoriesTask(repeat_on_pick=True),
])

app = FastAPI(title="Secure Klondike Automation Gateway")
background_task_holder = None

def verify_token(token: str):
    """Internal helper to drop illegal unauthorized web requests."""
    if token != API_TOKEN:
        raise HTTPException(status_code=403, detail="Access Denied: Invalid Security Token Configuration.")

@app.get("/")
def read_root(token: str = Query(...)):
    verify_token(token)
    return {
        "status": "online",
        "level": data.level,
        "energy": data.energy,
        "plan_active": global_plan.is_active
    }

@app.get("/start")
def start_automation(token: str = Query(...)):
    verify_token(token)
    global background_task_holder
    
    if global_plan.is_active:
        return {"message": "Automation worker loop is already actively executing tasks."}
        
    global_plan.is_active = True
    background_task_holder = asyncio.ensure_future(
        scheduler.start_plan_loop(global_plan.id, delay_seconds=0)
    )
    
    print("[Web Gateway]: Asynchronous background loop task successfully detached.")
    return {"message": "Automation successfully triggered and running securely in background."}

@app.get("/stop")
def stop_automation(token: str = Query(...)):
    verify_token(token)
    if not global_plan.is_active:
        return {"message": "Automation is already in a resting status."}
        
    global_plan.is_active = False
    return {"message": "Halt signal received. Scheduler background loops will suspend immediately."}

@app.get("/view-logs", response_class=PlainTextResponse)
def view_network_logs(token: str = Query(...), lines: int = 100):
    """Convenient secure endpoint to read the tail of client_network.log directly in browser."""
    verify_token(token)
    log_path = "client_network.log"
    if not os.path.exists(log_path):
        return "Log storage matrix is empty or file hasn't been instantiated yet."
        
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.readlines()
            return "".join(content[-lines:])
    except Exception as e:
        return f"Failed to retrieve log stream blocks: {str(e)}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
