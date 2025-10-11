from fastapi import FastAPI
from services.database import Base, engine
from routes.tokens import router as tokens_router

app = FastAPI(title="Clinic PHI Gateway (Azure-Mode Tokenization)")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "gateway"}

app.include_router(tokens_router)
