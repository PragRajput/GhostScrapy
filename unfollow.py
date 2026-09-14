#!/usr/bin/env python3
"""
Unfollow a single Instagram account, using the session cookies in .env.

Dry-run by default: it looks up the account and reports what it WOULD do,
without touching anything. Pass --confirm to actually unfollow.

Usage:
    python3 unfollow.py 15735543416            # dry run
    python3 unfollow.py 15735543416 --confirm  # actually unfollow
    python3 unfollow.py some_username          # username also works (costs a lookup)

Every real unfollow is appended to unfollow_log.csv.
"""

import csv
import os
import sys
import time

import scrape_followers

BASE = scrape_followers.BASE
DEFAULT_LOG_FILE = os.path.join("data", "unfollow_log.csv")


def _json(r):
    """Parse a response as JSON, or None — IG returns HTML on challenges/blocks."""
    try:
        return r.json()
    except ValueError:
        return None


def friendship_status(s, user_id):
    """Return the friendship dict for user_id, or None if it can't be read."""
    r = s.get(f"{BASE}/friendships/show/{user_id}/", timeout=30)
    if r.status_code == 200:
        data = _json(r)
        if data is not None:
            return data
        print(
            "Friendship status came back as non-JSON (login page or challenge) — "
            "your session cookies may be stale.",
            file=sys.stderr,
        )
        return None
    print(f"Could not read friendship status: HTTP {r.status_code}", file=sys.stderr)
    return None


def user_info(s, user_id):
    """Best-effort username/full_name for display. Returns {} if unavailable."""
    try:
        r = s.get(f"{BASE}/users/{user_id}/info/", timeout=30)
    except Exception:
        return {}
    if r.status_code != 200:
        return {}
    data = _json(r)
    return (data or {}).get("user", {}) or {}


def log_unfollow(user_id, username, log_dir=None):
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "unfollow_log.csv")
    else:
        os.makedirs("data", exist_ok=True)
        log_file = DEFAULT_LOG_FILE

    new_file = not os.path.exists(log_file)
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["pk", "username", "unfollowed_at"])
        w.writerow([user_id, username, time.strftime("%Y-%m-%d %H:%M:%S")])


def unfollow(s, user_id):
    """POST the unfollow. Returns (outcome, detail), outcome in ok|unknown|failed.

    Uses the web endpoint, not /api/v1/friendships/destroy/ — the latter is the
    mobile app API and answers a web session with an HTML page instead of acting.
    """
    r = s.post(
        f"https://www.instagram.com/web/friendships/{user_id}/unfollow/",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.instagram.com/",
            "Origin": "https://www.instagram.com",
            "X-Requested-With": "XMLHttpRequest",
            "X-Instagram-AJAX": "1",
        },
        timeout=30,
    )

    if r.status_code == 200:
        body = _json(r)
        if body is None:
            return "unknown", (
                "Instagram returned HTTP 200 with a non-JSON body (challenge or login "
                "page), so the response can't be trusted either way."
            )
        if body.get("status") == "ok":
            return "ok", body.get("friendship_status", {})
        return "failed", f"Instagram returned status={body.get('status')}: {body}"

    if r.status_code in (400, 429):
        # A block/limit on a write endpoint — do NOT retry, that escalates it.
        return "failed", (
            f"HTTP {r.status_code} — Instagram is blocking or rate-limiting this "
            f"action. Stop and wait before trying again. Body: {r.text[:300]}"
        )

    return "failed", f"HTTP {r.status_code}: {r.text[:300]}"


def main():
    args = [a for a in sys.argv[1:]]
    confirm = "--confirm" in args
    targets = [a for a in args if not a.startswith("--")]

    if len(targets) != 1:
        sys.exit(
            "Usage: python3 unfollow.py <user_id|username> [--confirm]\n\n"
            "  Without --confirm it is a dry run and changes nothing."
        )

    target = targets[0].lstrip("@")
    s = scrape_followers.build_session()

    me = os.environ.get("IG_DS_USER_ID", "?")
    user_id = target if target.isdigit() else scrape_followers.resolve_user_id(s, target)

    info = user_info(s, user_id)
    username = info.get("username") or (target if not target.isdigit() else str(user_id))
    full_name = info.get("full_name") or ""

    status = friendship_status(s, user_id)
    if status is None:
        sys.exit("Aborting: could not confirm the current follow state.")

    following = status.get("following", False)
    followed_by = status.get("followed_by", False)

    print("=" * 60)
    print(f"Acting as account : {me}")
    print(f"Target            : @{username} ({full_name}) [{user_id}]")
    print(f"You follow them   : {following}")
    print(f"They follow you   : {followed_by}")
    print("=" * 60)

    if not following:
        print("You are not following this account — nothing to do.")
        return

    if not confirm:
        print("\nDRY RUN — nothing was changed.")
        print(f"To actually unfollow, re-run:\n  python3 unfollow.py {user_id} --confirm")
        return

    print("\nUnfollowing...")
    outcome, detail = unfollow(s, user_id)

    if outcome == "failed":
        sys.exit(f"Unfollow FAILED: {detail}")
    if outcome == "unknown":
        print(f"Warning: {detail}")

    # The response body is not authoritative — re-read the friendship to see
    # what actually happened before logging anything.
    print("Verifying...")
    time.sleep(2)
    after = friendship_status(s, user_id)

    if after is None:
        sys.exit("Could not verify the result — check the Instagram app before retrying.")

    if after.get("following") is False:
        log_unfollow(user_id, username)
        print(f"Verified: unfollowed @{username} (following=False). Logged to {LOG_FILE}")
    else:
        sys.exit(
            f"Unfollow did NOT take effect — still following=@{after.get('following')}. "
            f"Do not retry immediately; Instagram may be blocking write actions."
        )


if __name__ == "__main__":
    main()
