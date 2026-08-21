import requests

BASE = "https://analyst-assessment-production.up.railway.app/api/v1"
TOKEN = "bh_tnKJMdeGm1I4br7d6ZSJ_Q"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def update_account(account_id, fields: dict):
    """PATCH an existing account. `fields` is whatever subset of columns you're changing."""
    resp = requests.patch(f"{BASE}/accounts/{account_id}", headers=HEADERS, json=fields, timeout=15)
    resp.raise_for_status()
    return resp.json()


def create_account(fields: dict):
    resp = requests.post(f"{BASE}/accounts", headers=HEADERS, json=fields, timeout=15)
    resp.raise_for_status()
    return resp.json()
