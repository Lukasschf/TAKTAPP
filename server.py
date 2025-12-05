import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, Response, jsonify, request, send_from_directory
from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, create_engine, func
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

BASE_DIR = Path(__file__).parent
DATABASE_PATH = BASE_DIR / "data.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

ADMIN_PIN = "1412"
DEFAULT_WINDOW = {"start": "06:30", "end": "16:15", "days": [1, 2, 3, 4, 5]}
DEFAULT_BREAKS = [
    {"start": "09:30", "end": "09:45"},
    {"start": "12:45", "end": "13:15"},
]
DEFAULT_EMPLOYEES = 1
MAX_HISTORY = 1000

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Base = declarative_base()


class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    employees = Column(Integer, default=DEFAULT_EMPLOYEES)
    window_start = Column(String(8), default=DEFAULT_WINDOW["start"])
    window_end = Column(String(8), default=DEFAULT_WINDOW["end"])
    work_days = Column(String(20), default=",".join(str(d) for d in DEFAULT_WINDOW["days"]))


class BreakPeriod(Base):
    __tablename__ = "break_periods"

    id = Column(Integer, primary_key=True)
    start_time = Column(String(8), nullable=False)
    end_time = Column(String(8), nullable=False)


class Holiday(Base):
    __tablename__ = "holidays"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, unique=True)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    hours = Column(Float, default=0.0)
    employees = Column(Integer, default=DEFAULT_EMPLOYEES)
    created_at = Column(DateTime, default=datetime.utcnow)


class BandSlot(Base):
    __tablename__ = "band_slots"

    station = Column(Integer, primary_key=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=True)

    vehicle = relationship("Vehicle")


class QueueEntry(Base):
    __tablename__ = "queue_entries"

    id = Column(Integer, primary_key=True)
    position = Column(Integer, nullable=False)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)

    vehicle = relationship("Vehicle")
    __table_args__ = (UniqueConstraint("position", name="uq_queue_position"),)


class HistoryEntry(Base):
    __tablename__ = "history_entries"

    id = Column(Integer, primary_key=True)
    vehicle_name = Column(String(200), nullable=False)
    hours = Column(Float, default=0.0)
    employees = Column(Integer, default=DEFAULT_EMPLOYEES)
    finished_at = Column(DateTime, default=datetime.utcnow, index=True)
    station = Column(Integer, default=10)
    band_employees = Column(Integer, default=DEFAULT_EMPLOYEES)


app = Flask(__name__, static_folder=str(BASE_DIR / "static"))


# Helpers

def require_admin() -> Optional[Response]:
    pin = request.headers.get("X-Admin-Pin") or request.json and request.json.get("adminPin")
    if pin and str(pin) == ADMIN_PIN:
        return None
    if request.method.lower() == "get":
        return None
    response = jsonify({"error": "Invalid admin PIN"})
    response.status_code = 403
    return response


def init_db(with_defaults: bool = True):
    Base.metadata.create_all(engine)
    if not with_defaults:
        return
    with SessionLocal() as session:
        if session.query(Setting).count() == 0:
            session.add(Setting())
        existing_breaks = session.query(BreakPeriod).count()
        if existing_breaks == 0:
            for entry in DEFAULT_BREAKS:
                session.add(BreakPeriod(start_time=entry["start"], end_time=entry["end"]))
        existing_slots = session.query(BandSlot).count()
        if existing_slots == 0:
            for station in range(1, 11):
                session.add(BandSlot(station=station, vehicle_id=None))
        session.commit()


def serialize_vehicle(vehicle: Optional[Vehicle]) -> Optional[Dict[str, object]]:
    if not vehicle:
        return None
    return {
        "id": vehicle.id,
        "name": vehicle.name,
        "hours": vehicle.hours,
        "employees": vehicle.employees,
    }


def get_config_payload(session) -> Dict[str, object]:
    setting = session.query(Setting).first()
    breaks = [
        {"id": br.id, "start": br.start_time, "end": br.end_time}
        for br in session.query(BreakPeriod).order_by(BreakPeriod.start_time)
    ]
    holidays = [h.date.isoformat() for h in session.query(Holiday).order_by(Holiday.date)]
    return {
        "window": {
            "start": setting.window_start if setting else DEFAULT_WINDOW["start"],
            "end": setting.window_end if setting else DEFAULT_WINDOW["end"],
            "days": [int(d) for d in (setting.work_days.split(",") if setting else DEFAULT_WINDOW["days"])],
        },
        "breaks": breaks,
        "freeDays": holidays,
        "employees": setting.employees if setting else DEFAULT_EMPLOYEES,
    }


def get_band_payload(session) -> List[Dict[str, object]]:
    slots = session.query(BandSlot).order_by(BandSlot.station).all()
    return [
        {
            "station": slot.station,
            "vehicle": serialize_vehicle(slot.vehicle),
        }
        for slot in slots
    ]


def get_queue_payload(session) -> List[Dict[str, object]]:
    entries = session.query(QueueEntry).order_by(QueueEntry.position).all()
    return [serialize_vehicle(entry.vehicle) for entry in entries if entry.vehicle]


def create_vehicle_from_payload(session, payload: Dict[str, object]) -> Vehicle:
    vehicle = Vehicle(
        name=str(payload.get("name", "")).strip(),
        hours=float(payload.get("hours", 0) or 0),
        employees=int(payload.get("employees", DEFAULT_EMPLOYEES) or DEFAULT_EMPLOYEES),
    )
    session.add(vehicle)
    session.flush()
    return vehicle


def update_config_from_payload(session, payload: Dict[str, object]):
    config_data = payload.get("config", payload)
    setting = session.query(Setting).first()
    if not setting:
        setting = Setting()
        session.add(setting)
    window = config_data.get("window", {})
    days = window.get("days", DEFAULT_WINDOW["days"])
    setting.window_start = str(window.get("start", setting.window_start or DEFAULT_WINDOW["start"]))
    setting.window_end = str(window.get("end", setting.window_end or DEFAULT_WINDOW["end"]))
    setting.work_days = ",".join(str(int(d)) for d in days)
    employees_val = config_data.get("employees")
    if employees_val is not None:
        try:
            setting.employees = max(1, int(employees_val))
        except (TypeError, ValueError):
            setting.employees = setting.employees or DEFAULT_EMPLOYEES

    breaks = config_data.get("breaks")
    if isinstance(breaks, list):
        session.query(BreakPeriod).delete()
        for entry in breaks:
            start, end = entry.get("start"), entry.get("end")
            if start and end:
                session.add(BreakPeriod(start_time=str(start), end_time=str(end)))

    holidays = config_data.get("freeDays")
    if isinstance(holidays, list):
        session.query(Holiday).delete()
        for raw in holidays:
            try:
                parsed = datetime.strptime(str(raw), "%Y-%m-%d").date()
                session.add(Holiday(date=parsed))
            except ValueError:
                continue
    session.commit()


def set_band_and_queue(session, band: List[Dict[str, object]], queue: List[Dict[str, object]]):
    # Update band
    session.query(BandSlot).delete()
    for station_idx in range(1, 11):
        vehicle_payload = band[station_idx - 1].get("vehicle") if station_idx - 1 < len(band) else None
        vehicle = None
        if vehicle_payload and vehicle_payload.get("name"):
            vehicle = create_vehicle_from_payload(session, vehicle_payload)
        session.add(BandSlot(station=station_idx, vehicle=vehicle))

    # Update queue
    session.query(QueueEntry).delete()
    for position, payload in enumerate(queue, start=1):
        if payload and payload.get("name"):
            vehicle = create_vehicle_from_payload(session, payload)
            session.add(QueueEntry(position=position, vehicle=vehicle))
    session.commit()


def advance_band(session):
    band = session.query(BandSlot).order_by(BandSlot.station).all()
    queue_entries = session.query(QueueEntry).order_by(QueueEntry.position).all()
    setting = session.query(Setting).first()
    employees_count = setting.employees if setting else DEFAULT_EMPLOYEES

    finished_vehicle = band[-1].vehicle if band else None
    if finished_vehicle and finished_vehicle.name:
        history_entry = HistoryEntry(
            vehicle_name=finished_vehicle.name,
            hours=finished_vehicle.hours,
            employees=finished_vehicle.employees,
            band_employees=employees_count,
            finished_at=datetime.utcnow(),
            station=band[-1].station,
        )
        session.add(history_entry)

    shifted = [None] * 10
    # shift vehicles down the band
    for i in range(8, -1, -1):
        shifted[i + 1] = band[i].vehicle if band and band[i] else None

    # new vehicle from queue
    next_vehicle = None
    if queue_entries:
        first_entry = queue_entries.pop(0)
        next_vehicle = first_entry.vehicle
        session.delete(first_entry)
        for new_pos, entry in enumerate(queue_entries, start=1):
            entry.position = new_pos
    shifted[0] = next_vehicle

    # persist shifted band
    session.query(BandSlot).delete()
    for station_idx in range(1, 11):
        session.add(BandSlot(station=station_idx, vehicle=shifted[station_idx - 1]))

    session.commit()
    enforce_history_limit(session)


def enforce_history_limit(session):
    count = session.query(HistoryEntry).count()
    if count > MAX_HISTORY:
        excess = count - MAX_HISTORY
        oldest = (
            session.query(HistoryEntry)
            .order_by(HistoryEntry.finished_at)
            .limit(excess)
            .all()
        )
        for entry in oldest:
            session.delete(entry)
        session.commit()


init_db()


@app.route("/")
def serve_planner():
    return send_from_directory(app.static_folder, "planner.html")


@app.route("/api/config", methods=["GET", "PUT"])
def config_route():
    admin_error = require_admin()
    if admin_error:
        return admin_error
    with SessionLocal() as session:
        if request.method == "GET":
            return jsonify(get_config_payload(session))
        payload = request.get_json(force=True, silent=True) or {}
        update_config_from_payload(session, payload)
        return jsonify(get_config_payload(session))


@app.route("/api/plan", methods=["GET", "POST"])
def plan_route():
    if request.method == "GET":
        with SessionLocal() as session:
            config_data = get_config_payload(session)
            band = get_band_payload(session)
            queue = get_queue_payload(session)
            return jsonify({"band": band, "queue": queue, "employees": config_data.get("employees")})

    admin_error = require_admin()
    if admin_error:
        return admin_error
    payload = request.get_json(force=True, silent=True) or {}
    band_payload = payload.get("band") or []
    queue_payload = payload.get("queue") or []
    with SessionLocal() as session:
        set_band_and_queue(session, band_payload, queue_payload)
        if "employees" in payload:
            update_config_from_payload(session, {"employees": payload.get("employees")})
        return jsonify({"band": get_band_payload(session), "queue": get_queue_payload(session)})


@app.route("/api/band/advance", methods=["POST"])
def band_advance():
    admin_error = require_admin()
    if admin_error:
        return admin_error
    with SessionLocal() as session:
        advance_band(session)
        return jsonify({"band": get_band_payload(session), "queue": get_queue_payload(session)})


@app.route("/api/history", methods=["GET"])
def history_route():
    limit = min(int(request.args.get("limit", 100)), MAX_HISTORY)
    offset = int(request.args.get("offset", 0))
    with SessionLocal() as session:
        entries = (
            session.query(HistoryEntry)
            .order_by(HistoryEntry.finished_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jsonify(
            [
                {
                    "id": entry.id,
                    "vehicle_name": entry.vehicle_name,
                    "hours": entry.hours,
                    "employees": entry.employees,
                    "band_employees": entry.band_employees,
                    "finished_at": entry.finished_at.isoformat(),
                    "station": entry.station,
                }
                for entry in entries
            ]
        )


@app.route("/export/history.csv", methods=["GET"])
def export_history():
    def generate():
        yield "finished_at,vehicle_name,hours,employees,band_employees,station\n"
        with SessionLocal() as session:
            entries = session.query(HistoryEntry).order_by(HistoryEntry.finished_at.desc()).all()
            for entry in entries:
                yield f"{entry.finished_at.isoformat()},{entry.vehicle_name},{entry.hours},{entry.employees},{entry.band_employees},{entry.station}\n"

    return Response(generate(), mimetype="text/csv")


@app.route("/export/plan.csv", methods=["GET"])
def export_plan():
    def generate():
        yield "type,station,position,vehicle_name,hours,employees\n"
        with SessionLocal() as session:
            for slot in session.query(BandSlot).order_by(BandSlot.station):
                vehicle = serialize_vehicle(slot.vehicle)
                if vehicle:
                    yield f"band,{slot.station},,{vehicle['name']},{vehicle['hours']},{vehicle['employees']}\n"
                else:
                    yield f"band,{slot.station},,,,,\n"
            for entry in session.query(QueueEntry).order_by(QueueEntry.position):
                vehicle = serialize_vehicle(entry.vehicle)
                yield f"queue,,{entry.position},{vehicle['name']},{vehicle['hours']},{vehicle['employees']}\n"

    return Response(generate(), mimetype="text/csv")

@app.route("/api/queue", methods=["POST"])
def queue_add():
    admin_error = require_admin()
    if admin_error:
        return admin_error
    payload = request.get_json(force=True, silent=True) or {}
    vehicle_data = payload.get("vehicle") or payload
    with SessionLocal() as session:
        vehicle = create_vehicle_from_payload(session, vehicle_data)
        max_position = session.query(func.max(QueueEntry.position)).scalar() or 0
        session.add(QueueEntry(position=max_position + 1, vehicle=vehicle))
        session.commit()
        return jsonify({"queue": get_queue_payload(session)})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.errorhandler(404)
def not_found(_):
    response = jsonify({"error": "Not found"})
    response.status_code = 404
    return response


@app.errorhandler(500)
def server_error(error):
    response = jsonify({"error": f"Internal server error: {error}"})
    response.status_code = 500
    return response


def main():
    parser = argparse.ArgumentParser(description="TAKTAPP Planner Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--init-db", action="store_true", help="Initialise database and exit")
    args = parser.parse_args()

    init_db()
    if args.init_db:
        print("Database initialised at", DATABASE_PATH)
        return

    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
