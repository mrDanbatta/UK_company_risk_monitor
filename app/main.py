from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import companies, dashboard

app = FastAPI(title="UK Company Risk Monitor")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard.router)
app.include_router(companies.router)