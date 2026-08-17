import asyncio
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
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
global_plan.interval_seconds = 900

global_plan.instructions.extend([
    CollectFactoriesTask(repeat_on_pick=True)
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
async def start_automation(token: str = Query(...)):
    verify_token(token)
    global background_task_holder
    
    if global_plan.is_active:
        return {"message": "Automation worker loop is already actively executing tasks."}
        
    global_plan.is_active = True
    background_task_holder = asyncio.create_task(
        scheduler.start_plan_loop(global_plan.id, delay_seconds=0)
    )
    
    print("[Web Gateway]: Background loop safely detached in the main execution thread.")
    return {"message": "Automation successfully triggered and running securely in background."}

@app.get("/stop")
async def stop_automation(token: str = Query(...)):
    verify_token(token)
    if not global_plan.is_active:
        return {"message": "Automation is already in a resting status."}
        
    global_plan.is_active = False
    return {"message": "Halt signal received. Scheduler background loops will suspend immediately."}


@app.get("/view-logs")
def download_network_logs(token: str = Query(...)):
    """Forces the browser to securely download the entire, unfiltered client_network.log file."""
    verify_token(token)
    log_path = "client_network.log"
    
    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail="Log file has not been created yet.")
        
    return FileResponse(
        path=log_path, 
        filename="client_network.log", 
        media_type="text/plain"
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
