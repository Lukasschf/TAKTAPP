# TAKTAPP Planner

Flask-basierte Planner-/Admin-Anwendung für eine Produktionslinie mit 10 Stationen. Das Backend hält Bandzustand, Queue, History und Konfiguration in SQLite (später Postgres/MySQL möglich). Ein schlankes HTML/JS-Frontend dient als Bedienoberfläche. CSV-Exporte und ein SQL-taugliches Schema erleichtern Grafana/BI-Anbindung.

## Inhalt
- [Überblick](#überblick)
- [Schnellstart](#schnellstart)
- [Datenbank & Schema](#datenbank--schema)
- [Migration alter JSON-Daten](#migration-alter-json-daten)
- [API-Referenz](#api-referenz)
- [CSV-Exporte](#csv-exporte)
- [Grafana-Anbindung](#grafana-anbindung)
- [Frontend](#frontend)
- [Testplan (manuell)](#testplan-manuell)
- [Troubleshooting](#troubleshooting)

## Überblick
- **Backend**: Python 3 + Flask, Persistenz via **SQLite** und **SQLAlchemy** (`data.db`).
- **Frontend**: HTML/CSS/Vanilla JS unter `static/` ohne Build-Tooling.
- **Planner-Logik**: Band (10 Stationen), Queue, History, Konfiguration (Arbeitszeiten, Pausen, Feiertage, Mitarbeiterzahl) im Backend. Frontend konsumiert REST-API.
- **Exports & BI**: CSV-Exports für Excel/Power BI; Datenmodell ist für direkte Grafana-SQL-Abfragen ausgelegt.

## Schnellstart
1. **Umgebung vorbereiten**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install flask sqlalchemy
   ```
2. **Datenbank anlegen** (legt Defaults und 10 Band-Slots an):
   ```bash
   python server.py --init-db
   ```
3. **Server starten**
   ```bash
   python server.py
   # läuft auf http://0.0.0.0:8000
   ```
4. **Planner-UI öffnen**: http://localhost:8000/

## Datenbank & Schema
Die SQLite-Datei `data.db` enthält folgende Tabellen:
- `settings`: Arbeitsfenster (Start/Ende), Arbeitstage (Mo–So-Flags), Mitarbeiterzahl, Admin-PIN.
- `break_periods`: Pause(n) mit Start-/Endzeit (pro Tag gleich angewendet).
- `holidays`: freie Tage als Datum.
- `vehicles`: Stammdaten je Fahrzeugeintrag (Name, Stunden, Mitarbeiterzahl optional).
- `band_slots`: 10 Zeilen (station 1–10) mit `vehicle_id`-FK.
- `queue_entries`: geordnete Queue mit `position` und `vehicle_id`-FK.
- `history_entries`: fertige Fahrzeuge mit `finished_at`, `hours`, `employees`, `band_employees`, `station`.

> Hinweis: Das Schema ist flach gehalten, damit Grafana/SQL-Clients ohne Views direkt darauf zugreifen können. Der Wechsel auf Postgres/MySQL ist über SQLAlchemy migrationsfähig; vorerst reicht SQLite.

## Migration alter JSON-Daten
Wenn noch `config.json`, `queue.json`, `history.json` existieren:
```bash
python migrate_from_json.py
```
- Importiert Konfiguration, Band/Queue und History (bis `MAX_HISTORY`).
- Anlage der Datenbank erfolgt automatisch, falls nicht vorhanden.

## API-Referenz
**Auth:** Schreibende Endpunkte erwarten `X-Admin-Pin` (Default: `1412`).

- `GET /api/plan` → aktueller Bandzustand (Station 1–10) + Queue + Mitarbeiterzahl.
- `POST /api/plan` → Band/Queue setzen (kompletter Plan). Header: `X-Admin-Pin`.
- `POST /api/band/advance` → Bandvorschub: Station 10 → History, Queue[0] → Station 1. Header: `X-Admin-Pin`.
- `GET /api/config` → Konfiguration lesen (Arbeitsfenster, Arbeitstage, Pausen, Feiertage, Mitarbeiterzahl).
- `PUT /api/config` → Konfiguration setzen. Header: `X-Admin-Pin`.
- `POST /api/queue` → Fahrzeug zur Queue hinzufügen. Header: `X-Admin-Pin`.
- `GET /api/history?limit=100&offset=0` → History-Einträge (paginiert).
- `GET /export/history.csv` → fertige Fahrzeuge als CSV.
- `GET /export/plan.csv` → aktueller Band + Queue als CSV.

## CSV-Exporte
- **History** (`/export/history.csv`): `finished_at, vehicle_name, hours, employees, band_employees, station`
- **Plan** (`/export/plan.csv`): `type (band/queue), station, position, vehicle_name, hours, employees`

## Grafana-Anbindung
So bindest du die Anwendung als SQL-Data-Source an Grafana an.

1. **Datenquelle anlegen**
   - Grafana → *Configuration* → *Data sources* → *Add data source*.
   - Typ **SQLite** (oder später Postgres/MySQL; Schema bleibt identisch). 
   - Pfad zur `data.db` angeben (lokal) oder via SQLite-Proxy/Host-Path bereitstellen.

2. **Rechte**
   - Nur Leserechte nötig. Schreibende API-Aufrufe erfolgen über die Anwendung, nicht über Grafana.

3. **Beispiel-SQL-Queries**
   - Aktuelle Bandbelegung:
     ```sql
     SELECT s.station, v.name, v.hours, v.employees
     FROM band_slots s
     LEFT JOIN vehicles v ON v.id = s.vehicle_id
     ORDER BY s.station;
     ```
   - Fertige Fahrzeuge pro Tag:
     ```sql
     SELECT date(finished_at) AS tag, COUNT(*) AS anzahl
     FROM history_entries
     GROUP BY date(finished_at)
     ORDER BY tag DESC;
     ```
   - Ø Stunden pro Fahrzeug (History):
     ```sql
     SELECT AVG(hours) AS avg_hours FROM history_entries;
     ```
   - Ø Mitarbeiter am Band pro Abschluss:
     ```sql
     SELECT AVG(band_employees) AS avg_band_employees FROM history_entries;
     ```
   - Queue-Länge über Zeit (Snapshot via Panel-Refresh):
     ```sql
     SELECT COUNT(*) AS queue_len FROM queue_entries;
     ```
   - Durchsatz nach Station (optional, wenn `station` in History gepflegt):
     ```sql
     SELECT station, COUNT(*) AS fertig
     FROM history_entries
     GROUP BY station
     ORDER BY station;
     ```

4. **Panels / Dashboards**
   - *Table Panel*: aktuelle Bandbelegung (Query 1).
   - *Stat/Bar Panel*: Fertige Fahrzeuge pro Tag (Query 2) mit Zeitachse.
   - *Stat Panel*: Ø Stunden / Fahrzeug (Query 3).
   - *Gauge*: Ø Mitarbeiter am Band pro Abschluss (Query 4).

5. **Refresh/Timing**
   - SQLite ist dateibasiert; für dauerhafte Nutzung im Mehrbenutzerbetrieb empfiehlt sich Postgres/MySQL. 
   - Für Demozwecke ist ein Refresh-Intervall von 5–30 Sekunden meist ausreichend.

## Frontend
- `static/planner.html` – UI für Band, Queue, History, Konfiguration.
- `static/planner.js` – API-Anbindung (fetch), Bandvorschub, Queue-Add, Config-Update.
- `static/planner.css` – schlichtes Dark-UI.

## Testplan (manuell)
1. **DB-Init**: `python server.py --init-db` → Datei `data.db` vorhanden.
2. **API Smoke**:
   - `curl http://localhost:8000/api/plan`
   - `curl -X POST -H "X-Admin-Pin: 1412" http://localhost:8000/api/band/advance -d '{}' -H 'Content-Type: application/json'`
3. **Queue hinzufügen**: POST `/api/queue` mit Admin-PIN, danach `GET /api/plan` prüfen.
4. **Config speichern**: PUT `/api/config` mit neuem Arbeitsfenster; `GET /api/config` prüfen.
5. **Exports**: Browser/Excel öffnet `/export/history.csv` und `/export/plan.csv` fehlerfrei.
6. **UI**: Planner-Page lädt Band/Queue/History, Buttons lösen entsprechende API-Calls aus.

## Troubleshooting
- **"database is locked"**: Bei parallelen Zugriffen auf SQLite kurz warten oder auf Postgres/MySQL migrieren.
- **Admin-PIN falsch**: Header `X-Admin-Pin` prüfen (Default `1412`).
- **Grafana findet DB nicht**: Pfad zur `data.db` in der Data Source validieren oder DB als Host-Volume bereitstellen.
