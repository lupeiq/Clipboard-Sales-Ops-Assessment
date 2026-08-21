import json
from rapidfuzz import fuzz

def load(path):
    with open(path) as f:
        return json.load(f)

def find_bellhaven_parent_id(crm_accounts):
    for a in crm_accounts:
        if a["name"].strip().lower() == "bellhaven senior living":
            return a["id"]
    raise ValueError("Could not find Bellhaven Senior Living parent account")

def score_pair(location, account):
    name_score = fuzz.token_sort_ratio(location["name"], account["name"])  # 0-100
    city_match = (location.get("city") or "").strip().lower() == (account.get("city") or "").strip().lower()
    state_match = (location.get("state") or "").strip().lower() == (account.get("state") or "").strip().lower()
    return name_score, city_match, state_match

def classify(location, crm_accounts, bellhaven_id):
    best_account = None
    best_score = -1
    for account in crm_accounts:
        name_score, city_match, state_match = score_pair(location, account)
        # weight city/state match heavily since it's a hard signal, name_score is fuzzy
        composite = name_score + (30 if city_match else 0) + (10 if state_match else 0)
        if composite > best_score:
            best_score = composite
            best_account = account
            best_signals = (name_score, city_match, state_match)

    if best_account is None or best_signals[0] < 60:
        return {
            "location": location,
            "bucket": "no_crm_account",
            "evidence": {"best_candidate": best_account["name"] if best_account else None,
                         "name_score": best_signals[0] if best_account else None},
        }

    name_score, city_match, state_match = best_signals
    correct_parent = best_account.get("parent_id") == bellhaven_id

    if name_score >= 90 and city_match and correct_parent:
        bucket = "confident_match"
    else:
        bucket = "needs_fix"

    return {
        "location": location,
        "matched_account": best_account,
        "bucket": bucket,
        "evidence": {"name_score": name_score, "city_match": city_match,
                     "state_match": state_match, "correct_parent": correct_parent},
    }

def find_orphans(results, crm_accounts, bellhaven_id):
    matched_account_ids = {
        r["matched_account"]["id"] for r in results if r.get("matched_account")
    }
    orphans = [
        a for a in crm_accounts
        if a.get("parent_id") == bellhaven_id and a["id"] not in matched_account_ids
    ]
    return orphans

if __name__ == "__main__":
    locations = load("data/scraped_locations.json")
    crm_accounts = load("data/crm_accounts.json")
    bellhaven_id = find_bellhaven_parent_id(crm_accounts)

    results = [classify(loc, crm_accounts, bellhaven_id) for loc in locations]
    orphans = find_orphans(results, crm_accounts, bellhaven_id)

    from collections import Counter
    counts = Counter(r["bucket"] for r in results)
    print("Bucket counts:", dict(counts))
    print(f"Orphans (CRM accounts under Bellhaven not found on site): {len(orphans)}")

    output = {"results": results, "orphans": orphans}
    with open("data/match_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print("Saved to data/match_results.json")
