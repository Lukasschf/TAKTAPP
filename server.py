import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple
import threading

from flask import Flask, jsonify, request

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
QUEUE_PATH = BASE_DIR / "queue.json"
HISTORY_PATH = BASE_DIR / "history.json"
STATIC_DIR = BASE_DIR / "static"

ADMIN_PIN = "1412"
MAX_HISTORY = 100
DEFAULT_WINDOW = {"start": "06:30", "end": "16:15", "days": [1, 2, 3, 4, 5]}
DEFAULT_BREAKS = [
    {"start": "09:30", "end": "09:45"},
    {"start": "12:45", "end": "13:15"},
]
DEFAULT_FREE_DAYS: List[str] = []
DEFAULT_WARNINGS = {"warnMinutes": 10, "criticalMinutes": 5}
DEFAULT_EMPLOYEES = 1
DEFAULT_TEST_MODE = {"enabled": False, "speed": 1}


def _default_vehicle(name: str) -> Dict[str, Any]:
    return {"name": name, "hours": 1.0, "employees": 1}


def _default_dynamic() -> List[Dict[str, Any]]:
    return [_default_vehicle(f"Fzg {i}") for i in range(1, 11)]


def build_default_config() -> Dict[str, Any]:
    return {
        "window": deepcopy(DEFAULT_WINDOW),
        "breaks": deepcopy(DEFAULT_BREAKS),
        "freeDays": deepcopy(DEFAULT_FREE_DAYS),
        "warnings": deepcopy(DEFAULT_WARNINGS),
        "employees": DEFAULT_EMPLOYEES,
        "dynamic": _default_dynamic(),
        "testMode": deepcopy(DEFAULT_TEST_MODE),
    }


def build_default_queue() -> List[Any]:
    return []


def build_default_history() -> List[Any]:
    return []


class JsonStore:
    """Thread-safe JSON store with atomic writes and validation hooks."""

    def __init__(self, path: Path, default_factory, normalizer=None):
        self.path = path
        self.default_factory = default_factory
        self.normalizer = normalizer
        self._lock = threading.RLock()

    def load(self):
        with self._lock:
            data = self._read_file()
            if self.normalizer:
                data = self.normalizer(data)
                self._write_file(data)
            return data

    def save(self, data):
        with self._lock:
            if self.normalizer:
                data = self.normalizer(data)
            self._write_file(data)
            return data

    def _read_file(self):
        if not self.path.exists():
            data = self.default_factory()
            self._write_file(data)
            return data
        try:
            with self.path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            data = self.default_factory()
            self._write_file(data)
            return data

    def _write_file(self, data):
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass


def normalize_vehicle(vehicle: Dict[str, Any]) -> Dict[str, Any]:
    name = str(vehicle.get("name", "")).strip()
    hours = vehicle.get("hours", 0) or 0
    employees = vehicle.get("employees", DEFAULT_EMPLOYEES) or DEFAULT_EMPLOYEES
    try:
        hours_val = float(hours)
    except (TypeError, ValueError):
        hours_val = 0.0
    try:
        employees_val = int(employees)
    except (TypeError, ValueError):
        employees_val = DEFAULT_EMPLOYEES
    if hours_val < 0:
        hours_val = 0.0
    if employees_val < 0:
        employees_val = DEFAULT_EMPLOYEES
    return {"name": name, "hours": hours_val, "employees": employees_val}


def normalize_dynamic(dynamic: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    if isinstance(dynamic, list):
        normalized = [normalize_vehicle(v if isinstance(v, dict) else {}) for v in dynamic]
    if len(normalized) < 10:
        normalized.extend([_default_vehicle(f"Fzg {i}") for i in range(len(normalized) + 1, 11)])
    return normalized[:10]


def normalize_config(raw: Any) -> Dict[str, Any]:
    cfg = raw if isinstance(raw, dict) else {}
    cfg_window = cfg.get("window") if isinstance(cfg.get("window"), dict) else {}
    cfg_breaks = cfg.get("breaks") if isinstance(cfg.get("breaks"), list) else []
    cfg_free_days = cfg.get("freeDays") if isinstance(cfg.get("freeDays"), list) else []
    cfg_warnings = cfg.get("warnings") if isinstance(cfg.get("warnings"), dict) else {}
    cfg_test = cfg.get("testMode") if isinstance(cfg.get("testMode"), dict) else {}

    window = {
        "start": str(cfg_window.get("start", DEFAULT_WINDOW["start"])),
        "end": str(cfg_window.get("end", DEFAULT_WINDOW["end"])),
        "days": [int(d) for d in (cfg_window.get("days") or DEFAULT_WINDOW["days"])],
    }
    breaks = []
    for entry in cfg_breaks:
        if isinstance(entry, dict):
            start = str(entry.get("start", "")).strip()
            end = str(entry.get("end", "")).strip()
            if start and end:
                breaks.append({"start": start, "end": end})
    if not breaks:
        breaks = deepcopy(DEFAULT_BREAKS)

    free_days = []
    for value in cfg_free_days:
        try:
            datetime.strptime(str(value), "%Y-%m-%d")
            free_days.append(str(value))
        except (ValueError, TypeError):
            continue

    warnings = {
        "warnMinutes": int(cfg_warnings.get("warnMinutes", DEFAULT_WARNINGS["warnMinutes"])),
        "criticalMinutes": int(cfg_warnings.get("criticalMinutes", DEFAULT_WARNINGS["criticalMinutes"])),
    }

    employees = cfg.get("employees", DEFAULT_EMPLOYEES)
    try:
        employees_val = int(employees)
    except (TypeError, ValueError):
        employees_val = DEFAULT_EMPLOYEES
    if employees_val <= 0:
        employees_val = DEFAULT_EMPLOYEES

    test_mode = {
        "enabled": bool(cfg_test.get("enabled", False)),
        "speed": int(cfg_test.get("speed", DEFAULT_TEST_MODE["speed"])),
    }

    cfg_dynamic = normalize_dynamic(cfg.get("dynamic"))

    return {
        "window": window,
        "breaks": breaks,
        "freeDays": free_days,
        "warnings": warnings,
        "employees": employees_val,
        "dynamic": cfg_dynamic,
        "testMode": test_mode,
    }


def normalize_queue(raw: Any) -> List[Dict[str, Any]]:
    queue: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        queue = [normalize_vehicle(item if isinstance(item, dict) else {}) for item in raw]
    return queue


def normalize_history(raw: Any) -> List[Dict[str, Any]]:
    history: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        history = [normalize_vehicle(item if isinstance(item, dict) else {}) for item in raw]
    return history[:MAX_HISTORY]


config_store = JsonStore(CONFIG_PATH, build_default_config, normalize_config)
queue_store = JsonStore(QUEUE_PATH, build_default_queue, normalize_queue)
history_store = JsonStore(HISTORY_PATH, build_default_history, normalize_history)


app = Flask(__name__, static_folder=str(STATIC_DIR))


def error_response(message: str, status_code: int):
    response = jsonify({"error": message})
    response.status_code = status_code
    return response


def require_admin(data: Dict[str, Any]) -> Tuple[bool, Any]:
    pin = str(data.get("adminPin") or data.get("pin") or "")
    if pin != ADMIN_PIN:
        return False, error_response("Invalid admin PIN", 403)
    return True, None


@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = config_store.load()
    return jsonify(cfg)


@app.route("/api/config", methods=["PUT"])
def update_config():
    payload = request.get_json(force=True, silent=True) or {}
    allowed, error = require_admin(payload)
    if not allowed:
        return error
    config_data = payload.get("config", payload)
    updated = config_store.save(config_data)
    return jsonify(updated)


@app.route("/api/plan", methods=["GET"])
def get_plan():
    cfg = config_store.load()
    queue = queue_store.load()
    history = history_store.load()
    return jsonify({"dynamic": cfg.get("dynamic", []), "future": queue, "history": history, "employees": cfg.get("employees", DEFAULT_EMPLOYEES)})


@app.route("/api/plan", methods=["PUT"])
def update_plan():
    payload = request.get_json(force=True, silent=True) or {}
    allowed, error = require_admin(payload)
    if not allowed:
        return error
    future = payload.get("future") if isinstance(payload.get("future"), list) else payload.get("plan") or payload.get("queue")
    if future is None:
        return error_response("Missing future plan", 400)
    saved = queue_store.save(future)
    return jsonify({"future": saved})


@app.route("/api/queue", methods=["GET"])
def get_queue():
    queue = queue_store.load()
    return jsonify(queue)


@app.route("/api/history", methods=["GET"])
def get_history():
    history = history_store.load()
    return jsonify(history)


@app.route("/api/history", methods=["PUT"])
def update_history():
    payload = request.get_json(force=True, silent=True) or {}
    allowed, error = require_admin(payload)
    if not allowed:
        return error
    history = payload.get("history") if isinstance(payload.get("history"), list) else payload.get("data")
    if history is None:
        return error_response("Missing history data", 400)
    saved = history_store.save(history)
    return jsonify(saved)


@app.route("/api/band/advance", methods=["POST"])
def advance_band():
    payload = request.get_json(force=True, silent=True) or {}
    allowed, error = require_admin(payload)
    if not allowed:
        return error

    cfg = config_store.load()
    queue = queue_store.load()
    history = history_store.load()

    dynamic = cfg.get("dynamic", [])
    if dynamic:
        finished = dynamic[-1]
        if finished.get("name"):
            history.insert(0, normalize_vehicle(finished))
    history = history[:MAX_HISTORY]

    next_vehicle = queue.pop(0) if queue else _default_vehicle("")
    next_vehicle = normalize_vehicle(next_vehicle)
    shifted = [next_vehicle] + dynamic[:-1]
    cfg["dynamic"] = normalize_dynamic(shifted)

    config_store.save(cfg)
    queue_store.save(queue)
    history_store.save(history)

    return jsonify({"dynamic": cfg["dynamic"], "queue": queue, "history": history})


@app.errorhandler(404)
def not_found(_):
    return error_response("Not found", 404)


@app.errorhandler(500)
def server_error(error):
    return error_response(f"Internal server error: {error}", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
