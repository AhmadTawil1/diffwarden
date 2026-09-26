from fastapi import FastAPI

app = FastAPI(title="DiffWarden")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
