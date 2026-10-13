from fastapi import FastAPI # Imports the main class

app = FastAPI(title = "TPO Mini CDP") #creates app object

@app.get("/api/health") # Registers function to handle GET requests
def health(): # A "health check" for Railway to ping to confrim app is running
    return {"status": "ok"} # Converts to JSON