#!/usr/bin/env python3
"""
Instagram followers and following scraper.

Hits the private web endpoints your browser uses:
    GET /api/v1/friendships/{user_id}/followers/?count=...&max_id=...
    GET /api/v1/friendships/{user_id}/following/?count=...&max_id=...

Auth = your own logged-in session cookies. Paginates via `next_max_id` until
Instagram stops handing one back. Resilient: saves its cursor so you can resume
after a 429/crash, dedupes by pk, and retries transient errors.

Usage:
    export IG_SESSIONID='<your_session_id>'      # value of the `sessionid` cookie
    export IG_CSRFTOKEN='<your_csrf_token>'
    export IG_DS_USER_ID='<your_user_id>'
    export IG_MID='<your_mid>'

    python scrape_followers.py <user_id>               # scrape followers (default)
    python scrape_followers.py <user_id> following     # scrape following
    python scrape_followers.py <user_id> both          # scrape followers AND following
    python scrape_followers.py username 500            # limit to ~500 followers
    python scrape_followers.py username following 500

To find who doesn't follow you back:
    python compare.py <user_id>
"""

import csv
import json
import os
import random
import sys
import time
import uuid

from urllib.parse import urlparse

import requests

APP_ID = "936619743392459"  # Instagram web app id; required header
BASE = "https://www.instagram.com/api/v1"
PAGE_SIZE = 50               # Fetch 50 accounts per request for faster pagination
DELAY = (2.0, 5.0)           # randomized pause between pages (seconds)
MAX_RETRIES = 5              # per-request retries on 429/5xx/network errors
MAX_PASSES = 12              # IG returns a partial, shuffled sample per full pagination
DRY_PASSES = 2               # consecutive passes finding nothing before the list counts as complete


def normalize_rur(rur):
    """Normalize rur routing cookie by stripping quotes and unescaping octal comma."""
    if not rur:
        return ""
    rur = str(rur).strip()
    rur = rur.strip('"\'')
    rur = rur.replace(r"\054", ",").replace("\\054", ",")
    return rur


def build_session(cookies_dict=None):
    """Build a requests.Session carrying auth cookies + required headers.
    Dynamic session cookies must be passed in (no .env reliance).
    """
    if not cookies_dict or not isinstance(cookies_dict, dict):
        raise ValueError(
            "Missing auth credentials. Please authenticate via the GhostScrapy web UI."
        )

    sessionid = normalize_sessionid(cookies_dict.get("sessionid"))
    csrftoken = cookies_dict.get("csrftoken")
    ds_user_id = cookies_dict.get("ds_user_id")
    mid = cookies_dict.get("mid", "")

    if not (sessionid and ds_user_id):
        raise ValueError(
            "Incomplete session cookies (sessionid and ds_user_id are required)."
        )

    s = requests.Session()
    s.cookies.set("sessionid", sessionid, domain=".instagram.com")
    if csrftoken:
        s.cookies.set("csrftoken", str(csrftoken), domain=".instagram.com")
    if ds_user_id:
        s.cookies.set("ds_user_id", str(ds_user_id), domain=".instagram.com")
    if mid:
        s.cookies.set("mid", str(mid), domain=".instagram.com")
    for k, v in cookies_dict.items():
        if k not in ("sessionid", "csrftoken", "ds_user_id", "mid") and v:
            val = normalize_rur(v) if k == "rur" else str(v)
            s.cookies.set(k, val, domain=".instagram.com")

    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            ),
            "X-IG-App-ID": APP_ID,
            "X-CSRFToken": csrftoken or "",
            "X-Requested-With": "XMLHttpRequest",
            "X-ASBD-ID": "129477",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.instagram.com/",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
    )

    # Clean any incoming rur cookie
    if "rur" in s.cookies:
        clean_rur = normalize_rur(s.cookies.get("rur"))
        s.cookies.set("rur", clean_rur, domain=".instagram.com")

    return s


USER_ID_CACHE_FILE = "user_id_cache.json"


def _load_user_id_cache():
    if os.path.exists(USER_ID_CACHE_FILE):
        try:
            with open(USER_ID_CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_user_id_cache(cache):
    with open(USER_ID_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def resolve_user_id(s, username):
    """Turn a username into the numeric pk the endpoints need. Cached, retried on 429/5xx."""
    cache = _load_user_id_cache()
    entry = cache.get(username)

    if isinstance(entry, dict) and "retry_after" in entry:
        wait_left = entry["retry_after"] - time.time()
        if wait_left > 0:
            raise RuntimeError(
                f"Instagram is still rate-limiting lookups for @{username}. "
                f"Try again in ~{int(wait_left)}s."
            )
    elif entry is not None:
        return entry

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = s.get(
                f"{BASE}/users/web_profile_info/",
                params={"username": username},
                timeout=30,
            )
            is_login = ("login" in r.url.lower()) or any(
                "login" in resp.headers.get("Location", "").lower() for resp in r.history
            )
            if is_login:
                raise RuntimeError(
                    f"Instagram session expired while resolving @{username} (redirected to login)."
                )
            if r.status_code == 429 or r.status_code >= 500:
                wait = min(30 * attempt, 120)
                cache[username] = {"retry_after": time.time() + wait}
                _save_user_id_cache(cache)
                print(
                    f"  HTTP {r.status_code} resolving @{username} "
                    f"(attempt {attempt}/{MAX_RETRIES}) — backing off {wait}s",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            r.raise_for_status()

            content_type = r.headers.get("Content-Type", "").lower()
            if "application/json" not in content_type:
                raise RuntimeError(
                    f"Instagram returned non-JSON response while resolving @{username}. Session may be expired."
                )

            user_id = r.json()["data"]["user"]["id"]
            cache[username] = user_id
            _save_user_id_cache(cache)
            return user_id
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            wait = min(15 * attempt, 60)
            cache[username] = {"retry_after": time.time() + wait}
            _save_user_id_cache(cache)
            print(
                f"  network error resolving @{username}: {e} "
                f"(attempt {attempt}/{MAX_RETRIES}) — retry in {wait}s",
                file=sys.stderr,
            )
            time.sleep(wait)

    raise RuntimeError(
        f"Instagram is rate-limiting lookups for @{username}. Wait a few minutes before trying again."
    )


def normalize_sessionid(sid):
    """Return the sessionid as-is, only repairing accidental double-encoding.

    The sessionid is sent verbatim (the same value the browser and the working
    profile-fetch path use). We must NOT re-encode a raw ':' to '%3A' — the colon
    is the structural delimiter in "{user_id}:{token}", and rewriting it corrupts
    the value so Instagram rejects the session (302 to the homepage). The only
    safe fix is undoing a double-encoded '%253A'.
    """
    if not sid:
        return ""
    sid = str(sid).strip()
    if "%253A" in sid.upper():
        sid = sid.replace("%253A", "%3A").replace("%253a", "%3A")
    return sid


def get_page(s, user_id, max_id, rel_type="followers", rank_token=None):
    """Fetch one page with retry/backoff. Returns parsed JSON or raises."""
    # search_surface is required — without it IG routes the followers/following
    # query to the homepage (302) instead of returning the JSON list.
    params = {"count": PAGE_SIZE, "search_surface": "follow_list_page"}
    if max_id:
        params["max_id"] = max_id

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = s.get(
                f"{BASE}/friendships/{user_id}/{rel_type}/",
                params=params,
                allow_redirects=False,
                timeout=30,
            )

            # 1. Rate-limit check (HTTP 429) or Server error (5xx)
            if r.status_code == 429 or r.status_code >= 500:
                wait = min(60 * attempt, 300)
                print(
                    f"  HTTP {r.status_code} (attempt {attempt}/{MAX_RETRIES}) "
                    f"— backing off {wait}s",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue

            # 2. Auth error (HTTP 401 / 403)
            if r.status_code in (401, 403):
                raise RuntimeError(
                    f"Instagram session unauthorized (HTTP {r.status_code}). Please re-connect with fresh cookies."
                )

            # 3. Handle redirects (301/302)
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location", "")
                low = loc.lower()
                path = urlparse(loc).path or "/"
                # Login / challenge redirects mean invalid session
                if "login" in low or "challenge" in low or "checkpoint" in low:
                    raise RuntimeError(
                        "Instagram session expired or flagged (redirected to login). "
                        "Reconnect with fresh cookies in the web UI, then try again."
                    )
                # Homepage redirect indicates temporary endpoint throttling
                if path in ("", "/"):
                    raise RuntimeError(
                        f"Instagram is temporarily rate-limiting the {rel_type} list for this "
                        f"account (redirected to homepage). Try again later."
                    )
                # Regional routing redirect: refresh cookies and retry
                if "rur" in s.cookies:
                    clean_rur = normalize_rur(s.cookies.get("rur"))
                    s.cookies.set("rur", clean_rur, domain=".instagram.com")
                print(f"  [Scraper Debug] routing redirect -> {loc}. Updating routing cookies...", file=sys.stderr)
                time.sleep(1.0)
                continue

            # 4. HTTP 200 handling
            content_type = r.headers.get("Content-Type", "").lower()
            if r.status_code == 200:
                if "application/json" not in content_type:
                    raise RuntimeError(
                        "Instagram session expired: received HTML page instead of JSON API response. "
                        "Please re-enter your session credentials in the web UI."
                    )
                data = r.json()
                if data.get("status") == "fail":
                    msg = data.get("message", "Instagram API error")
                    if "login_required" in msg.lower() or "checkpoint" in msg.lower():
                        raise RuntimeError(f"Instagram session expired: {msg}. Please re-connect.")
                return data

            r.raise_for_status()

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            wait = min(15 * attempt, 120)
            print(
                f"  network error: {e} (attempt {attempt}/{MAX_RETRIES}) "
                f"— retry in {wait}s",
                file=sys.stderr,
            )
            time.sleep(wait)

    raise RuntimeError("exhausted retries on a page")


def load_state(state_path):
    """Return the saved state of a prior run, or defaults."""
    if os.path.exists(state_path):
        with open(state_path) as f:
            st = json.load(f)
        return {
            "next_max_id": st.get("next_max_id"),
            "count": st.get("count", 0),
            "rank_token": st.get("rank_token"),
            "done": st.get("done", False),
        }
    return {"next_max_id": None, "count": 0, "rank_token": None, "done": False}


def save_state(state_path, next_max_id, count, rank_token, done=False):
    with open(state_path, "w") as f:
        json.dump(
            {
                "next_max_id": next_max_id,
                "count": count,
                "rank_token": rank_token,
                "done": done,
            },
            f,
        )


def load_seen(csv_path):
    """Load already-saved pks so reruns don't duplicate rows."""
    seen = set()
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                seen.add(row["pk"])
    return seen


def scrape_relationship(s, user_id, rel_type="followers", max_users=None, max_passes=MAX_PASSES, output_dir=None, progress_callback=None):
    """Scrape either followers or following for user_id.

    One full pagination returns only a partial, shuffled sample of the list —
    two passes over the same account yield different subsets — so passes repeat
    (each with a fresh cursor and rank_token) until one adds nothing new.
    """
    if not output_dir:
        output_dir = os.path.join("data", str(user_id))
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, f"{rel_type}_{user_id}.csv")
    state_path = os.path.join(output_dir, f"state_{rel_type}_{user_id}.json")

    fields = ["pk", "username", "full_name", "is_private", "is_verified"]

    seen = load_seen(csv_path)
    st = load_state(state_path)
    max_id = st["next_max_id"]
    rank_token = st["rank_token"] or str(uuid.uuid4())
    total = len(seen)

    if st["done"]:
        print(
            f"Already finished scraping {rel_type} for {user_id} ({total} saved). "
            f"Delete {csv_path} and {state_path} to re-scrape from scratch.",
            file=sys.stderr,
        )
        return total

    if total:
        print(
            f"Resuming {rel_type}: {total} already saved, cursor={'set' if max_id else 'none'}",
            file=sys.stderr,
        )
    print(f"Scraping {rel_type} of user_id={user_id}", file=sys.stderr)

    new_file = not os.path.exists(csv_path)
    converged = False
    dry = 0
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if new_file:
            writer.writeheader()

        for pass_num in range(1, max_passes + 1):
            pass_added = 0
            page = 0

            while True:
                data = get_page(s, user_id, max_id, rel_type=rel_type, rank_token=rank_token)
                users = data.get("users", [])
                page += 1

                added = 0
                for u in users:
                    pk = str(u.get("pk"))
                    if pk in seen:
                        continue
                    seen.add(pk)
                    writer.writerow({
                        "pk": pk,
                        "username": u.get("username"),
                        "full_name": u.get("full_name"),
                        "is_private": u.get("is_private"),
                        "is_verified": u.get("is_verified"),
                    })
                    added += 1
                    total += 1
                    pass_added += 1
                    if max_users and total >= max_users:
                        break
                f.flush()

                next_max_id = data.get("next_max_id")
                print(
                    f"  pass {pass_num} page {page}: {len(users)} returned, +{added} new "
                    f"(total {total}) | next_max_id={'yes' if next_max_id else 'NONE'}",
                    file=sys.stderr,
                )

                save_state(state_path, next_max_id, total, rank_token)

                if progress_callback:
                    try:
                        progress_callback({
                            "type": "progress",
                            "rel_type": rel_type,
                            "pass": pass_num,
                            "page": page,
                            "added": added,
                            "total": total
                        })
                    except Exception:
                        pass

                if max_users and total >= max_users:
                    print(f"Reached max_users ({max_users}).", file=sys.stderr)
                    save_state(state_path, None, total, rank_token, done=True)
                    print(f"Done -> {csv_path} ({total} {rel_type})", file=sys.stderr)
                    return total
                if not next_max_id:
                    break

                max_id = next_max_id
                time.sleep(random.uniform(*DELAY))

            dry = dry + 1 if pass_added == 0 else 0
            print(
                f"  pass {pass_num} done: +{pass_added} new this pass (total {total})"
                f"{f' | dry {dry}/{DRY_PASSES}' if dry else ''}",
                file=sys.stderr,
            )

            if dry >= DRY_PASSES:
                converged = True
                print(
                    f"{DRY_PASSES} passes found nothing new — {rel_type} list is complete.",
                    file=sys.stderr,
                )
                break

            max_id = None
            rank_token = str(uuid.uuid4())
            save_state(state_path, None, total, rank_token)
            time.sleep(random.uniform(*DELAY))
        else:
            print(
                f"Stopped after {max_passes} passes still finding new accounts — "
                f"re-run to keep accumulating.",
                file=sys.stderr,
            )

    save_state(state_path, None, total, rank_token, done=converged)
    print(f"Done -> {csv_path} ({total} {rel_type})", file=sys.stderr)
    return total


def parse_cli_args():
    if len(sys.argv) < 2:
        sys.exit(
            "Usage: python scrape_followers.py <username|user_id> [followers|following|both] [max_users]\n\n"
            "Examples:\n"
            "  python scrape_followers.py <user_id>\n"
            "  python scrape_followers.py <user_id> following\n"
            "  python scrape_followers.py <user_id> both\n"
            "  python scrape_followers.py username both 500"
        )

    target = sys.argv[1]
    rel_type = "followers"
    max_users = None

    if len(sys.argv) > 2:
        arg2 = sys.argv[2].lower()
        if arg2 in ("followers", "following", "both"):
            rel_type = arg2
            if len(sys.argv) > 3 and sys.argv[3].isdigit():
                max_users = int(sys.argv[3])
        elif arg2.isdigit():
            max_users = int(arg2)
        else:
            sys.exit(f"Unknown option '{sys.argv[2]}'. Expected 'followers', 'following', 'both', or a numeric limit.")

    return target, rel_type, max_users


def main():
    target, rel_type, max_users = parse_cli_args()

    s = build_session()
    user_id = target if target.isdigit() else resolve_user_id(s, target)

    if rel_type == "both":
        scrape_relationship(s, user_id, "followers", max_users)
        time.sleep(random.uniform(*DELAY))
        scrape_relationship(s, user_id, "following", max_users)
    else:
        scrape_relationship(s, user_id, rel_type, max_users)

    if os.path.exists(f"followers_{user_id}.csv") and os.path.exists(f"following_{user_id}.csv"):
        print("\nBoth followers and following data exist!", file=sys.stderr)
        print(f"Run: python compare.py {user_id}\nto see who doesn't follow you back.\n", file=sys.stderr)


if __name__ == "__main__":
    main()