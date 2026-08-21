import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, redirect, url_for
from ledger.db import get_conn
from crm.client import update_account, create_account

app = Flask(__name__)


@app.route("/")
def index():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM proposals WHERE status = 'pending' ORDER BY created_at"
    ).fetchall()
    conn.close()

    proposals = []
    for r in rows:
        proposals.append({
            "proposal_id": r["proposal_id"],
            "account_id": r["account_id"],
            "action": r["action"],
            "payload": json.loads(r["payload"]),
            "evidence": json.loads(r["evidence"]),
        })
    return render_template("index.html", proposals=proposals)


@app.route("/approve/<proposal_id>", methods=["POST"])
def approve(proposal_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()

    if row is None or row["status"] != "pending":
        conn.close()
        return redirect(url_for("index"))

    payload = json.loads(row["payload"])
    action = row["action"]

    try:
        if action == "update_field":
            field = payload["field"]
            value = payload["new_value"]
            body = {field: value}
            if payload.get("note"):
                body["note"] = payload["note"]
            update_account(row["account_id"], body)

        elif action == "mark_duplicate":
            update_account(row["account_id"], {
                "duplicate_of_account": payload["duplicate_of_account"],
                "status": payload["status"],
            })

        elif action == "create_account":
            new_account = create_account(payload)
            new_id = new_account.get("account_id") or new_account.get("id")

            # if this create was part of a CHOW flow, link the old account to the new one
            evidence = json.loads(row["evidence"])
            old_account_id = evidence.get("old_account_id")
            if old_account_id:
                update_account(old_account_id, {"chow_current_account": new_id})

        conn.execute(
            "UPDATE proposals SET status = 'approved', decided_at = CURRENT_TIMESTAMP WHERE proposal_id = ?",
            (proposal_id,),
        )
        conn.commit()
    except Exception as e:
        # do NOT mark approved if the API call failed
        conn.execute(
            "UPDATE proposals SET status = 'failed', decided_at = CURRENT_TIMESTAMP WHERE proposal_id = ?",
            (proposal_id,),
        )
        conn.commit()
        print(f"Approval failed for {proposal_id}: {e}")
    finally:
        conn.close()

    return redirect(url_for("index"))


@app.route("/reject/<proposal_id>", methods=["POST"])
def reject(proposal_id):
    conn = get_conn()
    conn.execute(
        "UPDATE proposals SET status = 'rejected', decided_at = CURRENT_TIMESTAMP WHERE proposal_id = ?",
        (proposal_id,),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
