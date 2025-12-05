import json
from datetime import datetime
from pathlib import Path

from server import (
    MAX_HISTORY,
    DEFAULT_EMPLOYEES,
    HistoryEntry,
    SessionLocal,
    init_db,
    set_band_and_queue,
    update_config_from_payload,
)

BASE_DIR = Path(__file__).parent
CONFIG_JSON = BASE_DIR / "config.json"
QUEUE_JSON = BASE_DIR / "queue.json"
HISTORY_JSON = BASE_DIR / "history.json"


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def migrate():
    init_db()
    cfg = load_json(CONFIG_JSON, {})
    queue = load_json(QUEUE_JSON, [])
    history = load_json(HISTORY_JSON, [])

    dynamic_list = cfg.get("dynamic") if isinstance(cfg.get("dynamic"), list) else []
    band_payload = [{"vehicle": v} for v in dynamic_list]
    while len(band_payload) < 10:
        band_payload.append({"vehicle": None})

    with SessionLocal() as session:
        update_config_from_payload(session, cfg if isinstance(cfg, dict) else {})
        set_band_and_queue(session, band_payload, queue if isinstance(queue, list) else [])

        session.query(HistoryEntry).delete()
        if isinstance(history, list):
            for entry in history[:MAX_HISTORY]:
                name = str(entry.get("name", entry.get("vehicle_name", "")))
                if not name:
                    continue
                hours = float(entry.get("hours", 0) or 0)
                employees = int(entry.get("employees", DEFAULT_EMPLOYEES) or DEFAULT_EMPLOYEES)
                session.add(
                    HistoryEntry(
                        vehicle_name=name,
                        hours=hours,
                        employees=employees,
                        band_employees=cfg.get("employees", DEFAULT_EMPLOYEES),
                        finished_at=datetime.utcnow(),
                    )
                )
        session.commit()

    print("Migration abgeschlossen. Datenbank liegt unter data.db")


if __name__ == "__main__":
    migrate()
