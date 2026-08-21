import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ledger.db import upsert_proposal, init_db

BELLHAVEN_PARENT_ID = "0015QAPLGS3FVYEEEM"


def propose_reparent(account, correct_parent_id):
    """Apply the CHOW/revenue rule from the brief."""
    has_revenue = (account.get("lifetime_revenue") or 0) > 0
    has_ar = (account.get("outstanding_ar") or 0) > 0

    if has_revenue and has_ar:
        return [{
            "action": "create_account",
            "account_id": None,
            "payload": {
                "name": account["name"],
                "parent_id": correct_parent_id,
                "billing_street": account.get("billing_street"),
                "billing_city": account.get("billing_city"),
                "billing_state": account.get("billing_state"),
                "billing_zip": account.get("billing_zip"),
                "care_type": account.get("care_type"),
                "status": "Active",
            },
            "evidence": {
                "reason": "CHOW: old account has revenue history and outstanding AR, "
                          "must be preserved. Creating new account under correct parent; "
                          "chow_current_account will be set on the old account once this is approved.",
                "old_account_id": account["account_id"],
                "lifetime_revenue": account.get("lifetime_revenue"),
                "outstanding_ar": account.get("outstanding_ar"),
            },
            "chow_link_source": account["account_id"],
        }]
    else:
        return [{
            "action": "update_field",
            "account_id": account["account_id"],
            "payload": {"field": "parent_id", "new_value": correct_parent_id},
            "evidence": {
                "reason": "No revenue history / no outstanding AR — safe to re-parent directly.",
                "old_parent": account.get("parent_name"),
                "lifetime_revenue": account.get("lifetime_revenue"),
                "outstanding_ar": account.get("outstanding_ar"),
            },
        }]


def propose_duplicate_resolution(duplicate_group, match_results):
    """Given a group of CRM duplicates, decide survivor vs loser and propose accordingly."""
    matched_ids = {
        r["matched_account"]["account_id"]
        for r in match_results["results"]
        if r.get("matched_account")
    }

    survivors = [a for a in duplicate_group if a["account_id"] in matched_ids]
    losers = [a for a in duplicate_group if a["account_id"] not in matched_ids]

    if len(survivors) != 1 or not losers:
        # ambiguous — more than one or zero records matched the live site;
        # don't guess, flag all for manual review instead
        return [{
            "action": "update_field",
            "account_id": a["account_id"],
            "payload": {"field": "status", "new_value": "Needs Review",
                        "note": "Possible duplicate account — could not automatically determine "
                                "which record should survive. Manual review needed."},
            "evidence": {"reason": "Duplicate group detected but survivor is ambiguous.",
                         "group_ids": [x["account_id"] for x in duplicate_group]},
        } for a in duplicate_group]

    survivor = survivors[0]
    proposals = []
    for loser in losers:
        has_revenue = (loser.get("lifetime_revenue") or 0) > 0
        has_ar = (loser.get("outstanding_ar") or 0) > 0

        if has_revenue and has_ar:
            # protected — even as a "loser," can't just deactivate it if it has billing history.
            # Flag for manual review rather than guessing.
            proposals.append({
                "action": "update_field",
                "account_id": loser["account_id"],
                "payload": {"field": "status", "new_value": "Needs Review",
                            "note": f"Likely duplicate of {survivor['account_id']} but has revenue "
                                    f"history and outstanding AR — do not mark Inactive without "
                                    f"billing team review."},
                "evidence": {"reason": "Duplicate with billing history — cannot auto-resolve.",
                             "survivor_id": survivor["account_id"]},
            })
        else:
            proposals.append({
                "action": "mark_duplicate",
                "account_id": loser["account_id"],
                "payload": {
                    "duplicate_of_account": survivor["account_id"],
                    "status": "Inactive",
                },
                "evidence": {
                    "reason": "Duplicate CRM record — matched location on live website corresponds "
                              "to the survivor account. This record has no revenue/AR history.",
                    "survivor_id": survivor["account_id"],
                    "survivor_name": survivor["name"],
                },
            })
    return proposals


def generate_all(match_results):
    proposals = []

    for r in match_results["results"]:
        bucket = r["bucket"]
        loc = r["location"]
        acct = r.get("matched_account")

        if bucket == "no_crm_account":
            proposals.append({
                "action": "create_account",
                "account_id": None,
                "payload": {
                    "name": loc["name"],
                    "parent_id": BELLHAVEN_PARENT_ID,
                    "billing_city": loc.get("city"),
                    "billing_state": loc.get("state"),
                    "care_type": loc.get("care_type"),
                    "status": "Active",
                },
                "evidence": {"reason": "No matching CRM account found for this website location.",
                             "source_url": loc.get("detail_url")},
            })

        elif bucket == "needs_fix":
            if not r["evidence"].get("correct_parent"):
                proposals.extend(propose_reparent(acct, BELLHAVEN_PARENT_ID))
            else:
                proposals.append({
                    "action": "update_field",
                    "account_id": acct["account_id"],
                    "payload": {"field": "name", "new_value": loc["name"]},
                    "evidence": {"reason": "Name on file differs from current website listing.",
                                 "old_name": acct["name"], "new_name": loc["name"],
                                 "name_score": r["evidence"].get("name_score")},
                })

    for orphan in match_results["orphans"]:
        proposals.append({
            "action": "update_field",
            "account_id": orphan["account_id"],
            "payload": {"field": "status", "new_value": "Needs Review",
                        "note": "No longer listed on Bellhaven website as of latest scrape. "
                                "Verify whether closed, sold, or rebranded before deactivating."},
            "evidence": {"reason": "CRM account under Bellhaven parent not found on current website.",
                         "account_name": orphan["name"], "city": orphan.get("billing_city")},
        })

    for group in match_results.get("duplicates", []):
        proposals.extend(propose_duplicate_resolution(group, match_results))

    return proposals


if __name__ == "__main__":
    init_db()
    with open("data/match_results.json") as f:
        match_results = json.load(f)

    proposals = generate_all(match_results)

    counts = {"upserted": 0, "skipped_already_decided": 0}
    for p in proposals:
        result = upsert_proposal(p["account_id"], p["action"], p["payload"], p["evidence"])
        counts[result] = counts.get(result, 0) + 1

    print(f"Generated {len(proposals)} proposals")
    print(counts)
