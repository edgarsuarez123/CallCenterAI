from fastapi import FastAPI
app = FastAPI(title="Clinic PHI Gateway (dev)")
@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "gateway"}
