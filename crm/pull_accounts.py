import requests
import json
import os

BASE = "https://analyst-assessment-production.up.railway.app/api/v1"
TOKEN = "bh_tnKJMdeGm1I4br7d6ZSJ_Q"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

def pull_all_accounts():
    accounts = []
    page = 1
    while True:
        resp = requests.get(f"{BASE}/accounts", headers=HEADERS, params={"page": page}, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # ADJUST based on what the real response shape looks like
        items = data["items"] if isinstance(data, dict) else data
        if not items:
            break
        accounts.extend(items)

        if isinstance(data, dict) and "total" in data:
            if len(accounts) >= data["total"]:
                break
        page += 1

    return accounts

if __name__ == "__main__":
    accounts = pull_all_accounts()
    print(f"Pulled {len(accounts)} accounts")

    os.makedirs("data", exist_ok=True)
    with open("data/crm_accounts.json", "w") as f:
        json.dump(accounts, f, indent=2)
    print("Saved to data/crm_accounts.json")
