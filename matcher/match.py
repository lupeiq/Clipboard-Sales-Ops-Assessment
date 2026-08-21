import json
from collections import Counter, defaultdict
from rapidfuzz import fuzz

BELLHAVEN_PARENT_ID = "0015QAPLGS3FVYEEEM"  # confirmed from CRM browser + data pull


def load(path):
    with open(path) as f:
        return json.load(f)


def score_pair(location, account):
    name_score = fuzz.token_sort_ratio(location["name"], account["name"])
    city_match = (location.get("city") or "").strip().lower() == (account.get("billing_city") or "").strip().lower()
    state_match = (location.get("state") or "").strip().lower() == (account.get("billing_state") or "").strip().lower()
    return name_score, city_match, state_match


def classify(location, crm_accounts):
    best_account = None
    best_composite = -1
    best_signals = (0, False, False)

    for account in crm_accounts:
        if "(Parent Account)" in account["name"]:
            continue

        name_score, city_match, state_match = score_pair(location, account)
        composite = name_score + (30 if city_match else 0) + (10 if state_match else 0)

        if composite > best_composite:
            best_composite = composite
            best_account = account
            best_signals = (name_score, city_match, state_match)

    name_score, city_match, state_match = best_signals

    if best_account is None or name_score < 60:
        return {
            "location": location,
            "matched_account": None,
            "bucket": "no_crm_account",
            "evidence": {
                "best_candidate": best_account["name"] if best_account else None,
                "name_score": name_score,
            },
        }

    correct_parent = best_account.get("parent_id") == BELLHAVEN_PARENT_ID

    if name_score >= 90 and city_match and correct_parent:
        bucket = "confident_match"
    else:
        bucket = "needs_fix"

    return {
        "location": location,
        "matched_account": best_account,
        "bucket": bucket,
        "evidence": {
            "name_score": name_score,
            "city_match": city_match,
            "state_match": state_match,
            "correct_parent": correct_parent,
