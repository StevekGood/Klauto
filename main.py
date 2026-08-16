import asyncio
from fastapi import FastAPI
import uvicorn
# from dotenv import load_dotenv
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

# load_dotenv()

client = KlondikeGameClient()
data = FarmDataManager()
actions = FarmActionManager(client, data)
scheduler = FarmTaskScheduler(client, data, actions)

# Create a global reusable background plan
global_plan = scheduler.create_plan("Фоновая Индустриализация 24/7")
global_plan.interval_seconds = 1800

# Load modular instruction instances sequence
global_plan.instructions.extend([
    HarvestGreenhousesTask(),
    DigGreenhousesTask(),
    PlantGreenhousesTask(recipe_id="P_WHEAT"),
    CollectFactoriesTask(repeat_on_pick=True)
])

# === WEB INTERFACE FOR REMOTE CONTROL ===
app = FastAPI(title="Klondike Automation Core API")
background_loop_task = None

@app.get("/")
def read_root():
    """Healthcheck endpoint to keep free hosting providers from sleeping."""
    return {
        "status": "online",
        "level": data.level,
        "energy": data.energy,
        "plan_active": global_plan.is_active
    }

@app.get("/start")
def start_automation():
    """Remote API command to fire up the background task loops."""
    global background_loop_task
    if global_plan.is_active:
        return {"message": "Automation loop is already running actively."}
    
    # Spawn the async loop task in the web server background safely
    background_loop_task = asyncio.create_task(
        scheduler.start_plan_loop(global_plan.id, delay_seconds=0)
    )
    return {"message": "Automation successfully triggered and running in background."}

@app.get("/stop")
def stop_automation():
    """Remote API command to securely halt active worker routines."""
    if not global_plan.is_active:
        return {"message": "Automation is already resting."}
    
    global_plan.is_active = False
    return {"message": "Termination signal dispatched. Scheduler will halt after current step."}

if __name__ == "__main__":
    # Render.com automatically populates the PORT environment variable
    import os
    port = int(os.environ.get("PORT", 8000))
    # Run the high performance web server gateway
    uvicorn.run(app, host="0.0.0.0", port=port)
