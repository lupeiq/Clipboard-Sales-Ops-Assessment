import sqlite3
import hashlib
import json
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "decisions.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposals (
            proposal_id TEXT PRIMARY KEY,
            account_id TEXT,
            action TEXT,
            payload TEXT,
            evidence TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            decided_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def make_proposal_id(account_id, action, payload):
    # deterministic: same intended change always hashes to the same id
    key = f"{account_id}|{action}|{json.dumps(payload, sort_keys=True)}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def upsert_proposal(account_id, action, payload, evidence):
    conn = get_conn()
    pid = make_proposal_id(account_id, action, payload)

    existing = conn.execute(
        "SELECT status FROM proposals WHERE proposal_id = ?", (pid,)
    ).fetchone()

    if existing and existing["status"] in ("approved", "rejected"):
        # already decided — do not touch it, do not re-propose
        conn.close()
        return "skipped_already_decided"

    conn.execute("""
        INSERT INTO proposals (proposal_id, account_id, action, payload, evidence, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
        ON CONFLICT(proposal_id) DO UPDATE SET
            evidence = excluded.evidence,
            payload = excluded.payload
    """, (pid, account_id or "", action, json.dumps(payload), json.dumps(evidence)))
    conn.commit()
    conn.close()
    return "upserted"
