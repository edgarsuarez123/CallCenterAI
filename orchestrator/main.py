from fastapi import FastAPI
app = FastAPI(title="Orchestrator (no PHI)")
@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "orchestrator"}
