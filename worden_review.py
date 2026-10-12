"""Observaciones visuales de Worden sin alterar confirmaciones históricas."""

from contextlib import closing
from datetime import datetime, timezone
import sqlite3
import json


class WordenReviewRepository:
    def __init__(self, database):
        self.database = database
        with closing(sqlite3.connect(database)) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS alert_worden_reviews ("
                "id INTEGER PRIMARY KEY, alert_id INTEGER NOT NULL, created_at TEXT NOT NULL, "
                "observed_at TEXT NOT NULL, status TEXT NOT NULL, evidence_id INTEGER, notes TEXT NOT NULL, "
                "authority TEXT NOT NULL, FOREIGN KEY(alert_id) REFERENCES strategy_alerts(id))"
            )
            db.commit()

    def record(self, alert_id, *, observed_at, status, evidence_id=None, notes=""):
        if observed_at.tzinfo is None:
            raise ValueError("La observación debe incluir zona horaria.")
        now = datetime.now(timezone.utc)
        if observed_at > now:
            raise ValueError("La observación no puede estar en el futuro.")
        if status not in {"CRUCE_OBSERVADO", "SIN_CRUCE", "NO_EVALUABLE"}:
            raise ValueError("Estado visual inválido.")
        with closing(sqlite3.connect(self.database)) as db:
            db.row_factory = sqlite3.Row
            alert = db.execute("SELECT trigger_timestamp,payload_json FROM strategy_alerts WHERE id=?", (alert_id,)).fetchone()
            if alert is None:
                raise ValueError("No existe la alerta.")
            evaluations = json.loads(alert["payload_json"]).get("strategies", {}).get("evaluations", [])
            if not any(str(item.get("strategy_id", "")).startswith("EFECTO_IMAN_") for item in evaluations):
                raise ValueError("La alerta no contiene una evaluación de Efecto Imán.")
            if evidence_id is not None:
                evidence = db.execute("SELECT alert_id,timeframe,indicators_json FROM alert_visual_evidence WHERE id=?", (evidence_id,)).fetchone()
                if evidence is None or evidence["alert_id"] != alert_id or evidence["timeframe"] != "1H":
                    raise ValueError("La captura debe ser de Hora y pertenecer a esta alerta.")
                if "WORDEN" not in json.loads(evidence["indicators_json"]):
                    raise ValueError("La captura debe declarar Worden visible.")
            cursor = db.execute(
                "INSERT INTO alert_worden_reviews (alert_id,created_at,observed_at,status,evidence_id,notes,authority) VALUES (?,?,?,?,?,?,?)",
                (alert_id, now.isoformat(), observed_at.astimezone(timezone.utc).isoformat(), status,
                 evidence_id, notes.strip(), "OBSERVACION_VISUAL_NO_MODIFICA_SENAL"),
            )
            db.commit()
            return cursor.lastrowid

    def recent(self, alert_id):
        with closing(sqlite3.connect(self.database)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM alert_worden_reviews WHERE alert_id=? ORDER BY id DESC", (alert_id,))]
