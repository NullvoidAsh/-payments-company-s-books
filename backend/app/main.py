"""FastAPI application factory."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.services.database import init_db
from app.routers import reconciliation, health

app = FastAPI(title="Payment Reconciliation API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reconciliation.router, prefix="/api")
app.include_router(health.router)


@app.on_event("startup")
def on_startup():
    init_db()
