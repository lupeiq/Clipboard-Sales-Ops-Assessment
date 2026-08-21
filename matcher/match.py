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

        # require city match to be a candidate in the first pass —
        # name-only similarity produces false matches across different towns
        # (e.g. "Bellhaven of Carlisle" vs "Bellhaven of New Carlisle",
        # or "Bellhaven of X" vs "Bellhaven of Y" sharing the "Bellhaven of" tokens)
        if not city_match:
            continue

        composite = name_score + (10 if state_match else 0)

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
            "current_parent_name": best_account.get("parent_name"),
        },
    }


def find_orphans(results, crm_accounts):
    matched_ids = {r["matched_account"]["account_id"] for r in results if r.get("matched_account")}
    return [
        a for a in crm_accounts
        if a.get("parent_id") == BELLHAVEN_PARENT_ID and a["account_id"] not in matched_ids
    ]


def second_pass_by_city_state(results, orphans):
    """Catch renames the name-similarity pass missed, using city+state as the anchor."""
    still_unmatched_locations = [
        r["location"] for r in results if r["bucket"] == "no_crm_account"
    ]

    rename_matches = []
    remaining_orphans = []
    used_location_names = set()

    for orphan in orphans:
        o_city = (orphan.get("billing_city") or "").strip().lower()
        o_state = (orphan.get("billing_state") or "").strip().lower()

        candidates = [
            loc for loc in still_unmatched_locations
            if (loc.get("city") or "").strip().lower() == o_city
            and (loc.get("state") or "").strip().lower() == o_state
            and loc["name"] not in used_location_names
        ]

        if len(candidates) == 1:
            matched_loc = candidates[0]
            used_location_names.add(matched_loc["name"])
            rename_matches.append({
                "location": matched_loc,
                "matched_account": orphan,
                "bucket": "needs_fix",
                "evidence": {
                    "reason": "Matched by city+state only — name changed substantially from CRM record.",
                    "old_name": orphan["name"],
                    "new_name": matched_loc["name"],
                    "correct_parent": True,
                },
            })
        else:
            remaining_orphans.append(orphan)

    return rename_matches, remaining_orphans


def find_duplicates(crm_accounts):
    """Flag CRM accounts under Bellhaven that share name+city+state with another."""
    groups = defaultdict(list)
    for a in crm_accounts:
        if a.get("parent_id") != BELLHAVEN_PARENT_ID:
            continue
        key = (
            a["name"].strip().lower(),
            (a.get("billing_city") or "").strip().lower(),
            (a.get("billing_state") or "").strip().lower(),
        )
        groups[key].append(a)
    return [g for g in groups.values() if len(g) > 1]


if __name__ == "__main__":
    locations = load("data/scraped_locations.json")
    crm_accounts = load("data/crm_accounts.json")

    results = [classify(loc, crm_accounts) for loc in locations]
    orphans = find_orphans(results, crm_accounts)

    # second pass: catch renames the fuzzy name match missed
    rename_matches, orphans = second_pass_by_city_state(results, orphans)
    results.extend(rename_matches)

    # remove the now-matched locations from the no_crm_account bucket
    renamed_location_names = {rm["location"]["name"] for rm in rename_matches}
    results = [
        r for r in results
        if not (r["bucket"] == "no_crm_account" and r["location"]["name"] in renamed_location_names)
    ]

    duplicates = find_duplicates(crm_accounts)

    counts = Counter(r["bucket"] for r in results)
    print("Bucket counts:", dict(counts))

    print(f"\nOrphans remaining (genuinely not found on site): {len(orphans)}")
    for o in orphans:
        print("  -", o["name"], "|", o.get("billing_city"), o.get("billing_state"))

    print(f"\nDuplicate groups found: {len(duplicates)}")
    for group in duplicates:
        print("  ", [(a["account_id"], a["name"], a.get("lifetime_revenue"), a.get("outstanding_ar")) for a in group])

    print(f"\nno_crm_account locations:")
    for r in results:
        if r["bucket"] == "no_crm_account":
            print("  -", r["location"]["name"], "|", r["location"].get("city"), r["location"].get("state"))

    with open("data/match_results.json", "w") as f:
        json.dump({"results": results, "orphans": orphans, "duplicates": duplicates}, f, indent=2)
    print("\nSaved to data/match_results.json")
