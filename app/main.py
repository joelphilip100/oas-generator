from fastapi import FastAPI
from app.routers import github, jira

app = FastAPI(title="AI OAS Generator API")

# Include Routers
app.include_router(github.router)
app.include_router(jira.router)

@app.get("/")
def read_root():
    return {"message": "Welcome to AI OAS Generator API"}
