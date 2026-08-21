# Bellhaven CRM Sync

A daily pipeline that scrapes Bellhaven Senior Living's website, matches
each listed community against the CRM, and proposes fixes for a human to
review and approve. Nothing writes to the CRM without explicit approval
through a local review app.

## Pipeline overview
scraper/scrape_bellhaven.py → data/scraped_locations.json
crm/pull_accounts.py → data/crm_accounts.json
matcher/match.py → data/match_results.json
pipeline/generate_proposals.py → data/decisions.db (pending proposals)
review_app/app.py → approve/reject UI, writes to CRM API on approve


Each stage writes its output to a file the next stage reads — this makes
every step independently re-runnable and inspectable, and means a bug in
one stage doesn't require re-scraping to fix.

## The scrape

`scraper/scrape_bellhaven.py` walks the paginated `/communities` hub page
(3 pages, 34 communities total), then follows each community's individual
detail page for full address information. City and state come split
directly from the hub page card; care type is read from the same card.

Output: 34 locations with `name`, `city`, `state`, `care_type`, `detail_url`.

## The CRM pull

`crm/pull_accounts.py` paginates `GET /api/v1/accounts` until all 121
accounts are retrieved, using the API's `total`/`page_size` fields to know
when to stop.

## Matching logic

`matcher/match.py` classifies each scraped location into one of four
buckets: **confident match**, **needs fix**, **no CRM account**, or
(from the CRM side) **orphan**.

### First pass: name + location scoring

For each scraped location, every non-parent CRM account is scored on:
- name similarity (`rapidfuzz.fuzz.token_sort_ratio`, handles word reordering)
- city match (exact, case-insensitive)
- state match (exact, case-insensitive)

**Important constraint, added after debugging a false-match problem:** a
CRM account can only be considered a *candidate* at all if its city matches
the scraped location's city. This was not the first version of the logic —
the first pass scored every account by name similarity and added city/state
match as a bonus on top, which let name-only similarity win outright. Because
most Bellhaven-branded facilities share the phrase "Bellhaven of ___", this
produced real false positives: `Bellhaven of Chagrin Falls` was scoring
higher against `Bellhaven of Marion` (a different facility, different city)
than against nothing, purely because of the shared "Bellhaven of" tokens.
Five locations were misrouted this way before the fix, including one case
(`Bellhaven of Carlisle` vs. `Bellhaven of New Carlisle`) where a substring
relationship inflated the score even within the same matching logic. Once
city match became a hard filter rather than a bonus, all five resolved
correctly — either to their true CRM counterpart or to `no_crm_account`.

Within candidates that pass the city filter, a composite score is
`name_score + (10 if state also matches)`, and only candidates scoring
**60+** on name similarity are considered a match at all. Locations below
that threshold, or with no city-matching candidate, fall to `no_crm_account`.

Of matches, a **confident match** requires: name score ≥ 90, city match,
and the CRM account already sitting under Bellhaven's parent id
(`0015QAPLGS3FVYEEEM`). Anything matched but falling short of that —
wrong parent, or a name that's drifted from the current website listing —
is **needs fix**.

### Second pass: renames that share nothing but city+state

Some site listings had renamed so completely that even a same-city match
never scored above the 60 threshold (e.g. CRM's `Riverbend Manor Care
Center` is now listed on the site as `Bellhaven of Chagrin Falls` — no
shared words at all). For these, a second pass pairs up remaining
`no_crm_account` locations against remaining CRM orphans purely by
city+state, and only commits the pairing when it's unambiguous (exactly
one candidate on each side). This caught 3 of the initial 6 apparent
orphans and reclassified them correctly as `needs_fix` renames rather than
locations that had disappeared from the CRM's radar.

### Final counts

| Bucket | Count |
|---|---|
| Confident match | 19 |
| Needs fix | 12 |
| No CRM account (new) | 3 |
| CRM orphan (Needs Review) | 4 |
| Duplicate pair | 1 (2 records) |

**No CRM account** (new accounts proposed): Bellhaven of Batavia,
Bellhaven of Carlisle, and a site listing for "Amberly Manor" in Hudson, OH
— the only existing CRM account named Amberly Manor belongs to an unrelated
company (Juniper Point Healthcare, Colorado Springs), so this is treated as
a genuinely new, unmatched location rather than a rename.

**Orphans remaining** (no corresponding site listing found, flagged
`Needs Review` rather than auto-deactivated): Bellhaven Care Center of
Alliance, Bellhaven of Coldwater, Bellhaven of Owosso (the duplicate loser
— see below), Bellhaven of Sandusky. These are left for a human to confirm
closure/rebrand rather than assumed inactive, since the pipeline has no way
to distinguish "closed" from "temporarily off the site" from "renamed in a
way even the second pass couldn't infer."

**Needs fix** notably includes two accounts under the wrong parent
entirely: `Bellhaven of Marietta` and `Bellhaven of Tiffin`, both
currently parented under **Cedar Trail Communities** rather than Bellhaven,
despite being clearly Bellhaven-branded and listed on Bellhaven's own site.

## Duplicate handling

The CRM contains two nearly identical records for **Bellhaven of Owosso**
(`001EGU7BMJ942ZTRE6` and `001QU150PM4Z15UA71`) — same address (one
abbreviated, one spelled out), same zip, same care type, both with
`lifetime_revenue: 0` and `outstanding_ar: 0`. Since neither has billing
history to protect, the tiebreaker used was: whichever record the live
website listing actually matched to is treated as the surviving record.
`001EGU7BMJ942ZTRE6` matched the current site listing and survives;
`001QU150PM4Z15UA71` is proposed as `duplicate_of_account:
001EGU7BMJ942ZTRE6`, `status: Inactive`.

If a duplicate pair is found where the "loser" record *does* carry
revenue/AR history, the pipeline does not auto-resolve it — it flags both
records `Needs Review` with a note, since deactivating a record with real
billing history requires a judgment call the automation shouldn't make
unattended.

## The CHOW / revenue rule

Applied whenever a `needs_fix` case requires re-parenting an account:

- If the account has **both** `lifetime_revenue > 0` **and**
  `outstanding_ar > 0`, the existing account is left untouched. A new
  account is proposed under the correct parent instead, and once that
  create is approved, `chow_current_account` on the old account is set to
  the new account's id — the review app performs this link automatically
  as the second half of approving a CHOW-flagged proposal.
- If either condition fails (no revenue, or no outstanding AR), the
  existing account is re-parented directly via `parent_id` update — no new
  account needed, since there's no billing history at risk.

This distinction matters because a straight `parent_id` overwrite on an
account with live AR would sever that history from its billing thread;
the CHOW path preserves the old record exactly as-is while still getting
the facility correctly organized going forward.

## Idempotency / re-run safety

Every proposal is assigned a deterministic id: a SHA-256 hash of
`(account_id, action, payload)`, truncated to 16 characters. Before
inserting a new proposal, the pipeline checks whether a proposal with that
exact id already exists in `data/decisions.db` and has a **decided**
status (`approved` or `rejected`) — if so, it's skipped, not re-inserted.
Still-`pending` proposals are refreshed in place (evidence updated) rather
than duplicated.

This means: running the full pipeline twice in a row produces the same
proposal set, not double the rows. Once a proposal is approved or
rejected, later runs will never re-surface it, even if the underlying
match logic re-derives the same finding — the ledger is where "already
decided" state lives, separate from the (re-derivable) match output.

One practical case this caught during development: when the matcher's
scoring logic changed (the city-match fix above), previously-generated
`pending` proposals from the old, buggy logic remained in the ledger
alongside the new correct ones, since nothing had decided them yet. This
is expected behavior, not a bug — the fix was to clear undecided pending
rows before regenerating, which is safe specifically because "pending"
means no CRM write has happened and no human decision is being discarded.

## The review app

`review_app/app.py` — a local Flask app (`localhost:5001`). Lists every
pending proposal with its full evidence (why the pipeline proposed it).
Approve triggers the real CRM write (`PATCH` for field updates,
`POST` for new accounts) and only marks the proposal `approved` if the API
call succeeds; a failed write is marked `failed`, not `approved`, so it
doesn't silently disappear. Reject marks the proposal `rejected` without
ever calling the API. Nothing else in the pipeline has write access to the
CRM — only this app does, and only on explicit human action.

## What was approved

*[Fill in after going through the review app: how many of the 20
proposals you approved vs. rejected, and call out anything you overrode —
e.g. if you disagreed with a `needs_fix` rename or chose to leave an
orphan as-is rather than approve the Needs Review flag. This is the part
that shows the CRM's end state reflects your actual judgment, not just
the pipeline's.]*

## Running it

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python scraper/scrape_bellhaven.py
python crm/pull_accounts.py
python matcher/match.py
python pipeline/generate_proposals.py
python review_app/app.py   # open http://localhost:5001, approve/reject
```

## Schedule

See `.github/workflows/daily.yml` — runs the scrape → pull → match →
generate-proposals steps daily. Review and approval are intentionally left
manual and local, per the requirement that nothing writes to the CRM
without a human in the loop; the scheduled job only ever produces fresh
*pending* proposals for a person to later review, it never calls a write
endpoint itself.
