from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import select
from pathlib import Path
import json

from .db import init_db, get_session
from .models import Vehicle, Incident
from .services.broadcast import WSHub

app = FastAPI(title="Alarmmonitor API")
hub = WSHub()
BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
UPLOADS = BASE.parents[1] / "uploads"

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/vehicles")
def list_vehicles(session=Depends(get_session)):
    return session.exec(select(Vehicle)).all()


@app.post("/api/vehicles")
def create_vehicle(v: Vehicle, session=Depends(get_session)):
    session.add(v)
    session.commit()
    session.refresh(v)
    return v


@app.post("/api/vehicles/{vid}/status")
def set_status(vid: int, payload: dict, session=Depends(get_session)):
    v = session.get(Vehicle, vid)
    if not v:
        return {"error": "not_found"}
    prev = v.status
    v.status = payload.get("code", v.status)
    session.add(v)
    session.commit()
    return {"ok": True, "from": prev, "to": v.status}


@app.get("/api/incidents")
def list_incidents(session=Depends(get_session)):
    return session.exec(select(Incident)).all()


@app.post("/api/incidents")
def create_incident(payload: dict, session=Depends(get_session)):
    inc = Incident(
        number=payload.get("number"),
        priority=payload.get("priority", 2),
        keyword=payload["keyword"],
        subtitle=payload.get("subtitle"),
        address_json=json.dumps(payload.get("address", {})),
        details=payload.get("details"),
    )
    session.add(inc)
    session.commit()
    session.refresh(inc)
    return inc


@app.post("/api/incidents/{iid}/activate")
async def activate_incident(iid: int, session=Depends(get_session)):
    inc = session.get(Incident, iid)
    if not inc:
        return {"error": "not_found"}
    inc.status = "ACTIVE"
    session.add(inc)
    session.commit()
    await hub.send_json({
        "type": "monitor.alarm",
        "incident": {
            "id": inc.id,
            "keyword": inc.keyword,
            "subtitle": inc.subtitle,
            "address": json.loads(inc.address_json),
        }
    })
    return {"ok": True}


@app.websocket("/ws/monitor")
async def ws_monitor(ws: WebSocket):
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(ws)


@app.get("/")
def index():
    return HTMLResponse((STATIC / "dispatch.html").read_text("utf-8"))


@app.get("/monitor")
def monitor():
    return HTMLResponse((STATIC / "monitor.html").read_text("utf-8"))
