#!/usr/bin/env python3
"""
Compare Instagram followers and following CSV files to find:
1. Accounts you follow who do NOT follow you back (not_following_back_{id}.csv)
2. Accounts who follow you but you do NOT follow back (fans_{id}.csv)
3. Mutual followers

Usage:
    python compare.py                 # auto-detects user ID from existing CSVs
    python compare.py 33735762690     # specify user ID explicitly
"""

import csv
import glob
import json
import os
import random
import re
import sys
import time

# ==============================================================================
# FILTER CONFIGURATION
# ==============================================================================
# Exclude accounts with MORE followers than this limit from the "Not Following Back" list.
# (Useful for excluding celebrities, brands, influencers, meme pages, etc.)
#
# Examples:
#   MAX_FOLLOWER_COUNT = "10k"    # excludes accounts with > 10,000 followers
#   MAX_FOLLOWER_COUNT = "50k"    # excludes accounts with > 50,000 followers
#   MAX_FOLLOWER_COUNT = "100k"   # excludes accounts with > 100,000 followers
#   MAX_FOLLOWER_COUNT = "1M"     # excludes accounts with > 1,000,000 followers
#   MAX_FOLLOWER_COUNT = ""       # or None: NO FILTER - shows ALL accounts
# ==============================================================================
MAX_FOLLOWER_COUNT = ""

# Set to True to also exclude verified accounts (blue checkmark) immediately
EXCLUDE_VERIFIED = True


CACHE_FILE = "follower_counts_cache.json"
BASE = "https://www.instagram.com/api/v1"

# web_profile_info is rate-limited far more aggressively than the friendships
# endpoints the scraper uses, so lookups are paced and retried rather than fired
# back-to-back and abandoned on the first 429.
COUNT_DELAY = (1.5, 3.0)
MAX_COUNT_RETRIES = 3


def parse_follower_limit(val):
    """Convert human-readable follower limit (e.g. '1M', '500k', 100000) to an int, or None."""
    if val is None:
        return None
    val_str = str(val).strip().lower()
    if not val_str:
        return None
    try:
        if val_str.endswith("m"):
            return int(float(val_str[:-1]) * 1_000_000)
        elif val_str.endswith("k"):
            return int(float(val_str[:-1]) * 1_000)
        elif val_str.endswith("b"):
            return int(float(val_str[:-1]) * 1_000_000_000)
        return int(float(val_str))
    except ValueError:
        print(f"[Warning] Invalid MAX_FOLLOWER_COUNT value '{val}'. Filter disabled.", file=sys.stderr)
        return None


def format_count(num):
    """Format integer count nicely (e.g. 1.2M, 450K, or 850)."""
    if num is None:
        return "unknown"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M".replace(".0M", "M")
    if num >= 1_000:
        return f"{num / 1_000:.1f}k".replace(".0k", "k")
    return str(num)


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def get_follower_counts(usernames, session=None):
    """
    Fetch follower counts for a list of usernames, using cache first.
    Returns dict: {username: count_or_None}
    """
    cache = load_cache()
    missing = [u for u in usernames if u not in cache]

    if not missing:
        return cache

    # Lazy-import scrape_followers to build session if credentials exist
    if session is None:
        try:
            import scrape_followers
            session = scrape_followers.build_session()
        except Exception as e:
            print(f"[Note] Could not start session for follower counts ({e}). Using existing cached data.", file=sys.stderr)
            return cache

    print(f"\nChecking follower counts for {len(missing)} account(s)...")
    cache_updated = False

    rate_limited = False

    for i, username in enumerate(missing, 1):
        for attempt in range(1, MAX_COUNT_RETRIES + 1):
            try:
                r = session.get(
                    f"{BASE}/users/web_profile_info/",
                    params={"username": username},
                    allow_redirects=False,
                    timeout=15,
                )
            except Exception as e:
                print(f"  [{i}/{len(missing)}] @{username}: lookup failed ({e})")
                time.sleep(0.5)
                break

            if r.status_code in (301, 302, 303, 307, 308):
                print(f"  [Notice] Instagram session expired during follower count lookup.")
                rate_limited = True
                break

            if r.status_code == 200:
                if "application/json" in r.headers.get("Content-Type", "").lower():
                    try:
                        data = r.json()
                        count = data.get("data", {}).get("user", {}).get("edge_followed_by", {}).get("count")
                        cache[username] = count
                        cache_updated = True
                        print(f"  [{i}/{len(missing)}] @{username}: {format_count(count)} followers")
                        break
                    except Exception:
                        pass

            if r.status_code in (404, 400):
                cache[username] = None
                cache_updated = True
                break

            if r.status_code == 429:
                print(
                    f"  [Notice] Instagram rate limit (429) reached at @{username}. "
                    f"Stopping lookups to protect your account. Returning current results."
                )
                rate_limited = True
                break

        if rate_limited:
            break

        time.sleep(random.uniform(*COUNT_DELAY))

    if cache_updated:
        save_cache(cache)

    return cache


def load_csv(filepath):
    """Load a CSV file into a dictionary keyed by pk."""
    users = {}
    if not os.path.exists(filepath):
        return None
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pk = row.get("pk")
            if pk:
                users[pk] = row
    return users


def save_csv(filepath, users, fieldnames):
    """Save a list of user dicts to a CSV file."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for u in users:
            writer.writerow(u)


def load_unfollowed_pks(data_dir=None):
    """Return the set of pks already unfollowed, read from unfollow_log.csv.

    This log is the durable record of unfollow actions, so the 'unfollowed'
    flag survives a re-scrape/re-analyze that rewrites the results CSV.
    """
    log_path = os.path.join(data_dir, "unfollow_log.csv") if data_dir else "unfollow_log.csv"
    pks = set()
    if not os.path.exists(log_path):
        return pks
    try:
        with open(log_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pk = str(row.get("pk", "")).strip()
                if pk:
                    pks.add(pk)
    except Exception:
        pass
    return pks


def find_user_ids():
    """Find user IDs present in data/<user_id>/ or local CSV files."""
    ids = set()
    patterns = [
        "data/*/followers_*.csv",
        "data/*/following_*.csv",
        "followers_*.csv",
        "following_*.csv",
    ]
    for pattern in patterns:
        for f in glob.glob(pattern):
            m = re.search(r"(?:followers|following)_(\d+)\.csv", f)
            if m:
                ids.add(m.group(1))
    return sorted(list(ids))


def compare(user_id, max_followers_filter=MAX_FOLLOWER_COUNT, data_dir=None, session=None, exclude_verified=EXCLUDE_VERIFIED):
    if not data_dir:
        data_dir = os.path.join("data", str(user_id))
    os.makedirs(data_dir, exist_ok=True)

    followers_file = os.path.join(data_dir, f"followers_{user_id}.csv")
    following_file = os.path.join(data_dir, f"following_{user_id}.csv")
    out_not_following = os.path.join(data_dir, f"not_following_back_{user_id}.csv")
    out_fans = os.path.join(data_dir, f"fans_{user_id}.csv")
    out_excluded = os.path.join(data_dir, f"excluded_big_accounts_{user_id}.csv")

    followers = load_csv(followers_file)
    following = load_csv(following_file)

    if followers is None and following is None:
        sys.exit(
            f"Error: Neither {followers_file} nor {following_file} was found.\n"
            f"Run scraper first:\n"
            f"  python scrape_followers.py {user_id} both"
        )

    if followers is None:
        sys.exit(
            f"Error: Missing {followers_file}.\n"
            f"Scrape followers first:\n"
            f"  python scrape_followers.py {user_id} followers"
        )

    if following is None:
        sys.exit(
            f"Error: Missing {following_file}.\n"
            f"Scrape following first:\n"
            f"  python scrape_followers.py {user_id} following"
        )

    fieldnames = ["pk", "username", "full_name", "follower_count", "is_private", "is_verified", "unfollowed"]
    unfollowed_pks = load_unfollowed_pks(data_dir)

    if len(followers) == 0 and len(following) > 0:
        raise ValueError(
            f"Followers list for user {user_id} is empty (0 records), but you are following {len(following)} accounts. "
            f"Please ensure your followers list is scraped before running the comparison."
        )

    # People you follow who do not follow you back (following - followers)
    raw_not_following = [
        u for pk, u in following.items() if pk not in followers
    ]

    # People who follow you whom you don't follow back (followers - following)
    fans = [
        u for pk, u in followers.items() if pk not in following
    ]

    # Mutual followers
    mutual = [
        u for pk, u in following.items() if pk in followers
    ]

    # Apply filters if configured
    follower_limit = parse_follower_limit(max_followers_filter)
    filtered_not_following = []
    excluded_big_accounts = []

    candidates = []
    for u in raw_not_following:
        is_verified = str(u.get("is_verified", "")).lower() in ("true", "1")
        if exclude_verified and is_verified:
            u["follower_count"] = u.get("follower_count", "")
            excluded_big_accounts.append(u)
        else:
            candidates.append(u)

    if follower_limit is not None and candidates:
        usernames = [u["username"] for u in candidates]
        counts = get_follower_counts(usernames, session=session)

        for u in candidates:
            count = counts.get(u["username"])
            u["follower_count"] = count if count is not None else ""
            if count is not None and count > follower_limit:
                excluded_big_accounts.append(u)
            else:
                filtered_not_following.append(u)
    else:
        # No follower limit filter: keep all candidates
        for u in candidates:
            u["follower_count"] = u.get("follower_count", "")
            filtered_not_following.append(u)

    # Flag rows already unfollowed so they persist across re-analysis.
    for u in filtered_not_following:
        u["unfollowed"] = "True" if str(u.get("pk")) in unfollowed_pks else "False"

    save_csv(out_not_following, filtered_not_following, fieldnames)
    save_csv(out_fans, fans, ["pk", "username", "full_name", "is_private", "is_verified"])
    if excluded_big_accounts:
        save_csv(out_excluded, excluded_big_accounts, fieldnames)

    print("\n" + "=" * 62)
    print(f" Instagram Relationship Analysis for User ID: {user_id}")
    print("=" * 62)
    print(f"Total Following:             {len(following):>6}")
    print(f"Total Followers:             {len(followers):>6}")
    print("-" * 62)
    print(f"All Not Following Back:      {len(raw_not_following):>6}")
    if follower_limit is not None:
        print(f"Filter applied:              Exclude accounts > {format_count(follower_limit)} followers")
        print(f"Excluded Big Accounts:       {len(excluded_big_accounts):>6}  -> saved to {out_excluded}")
    print(f"DON'T FOLLOW YOU BACK:       {len(filtered_not_following):>6}  -> saved to {out_not_following}")
    print(f"FANS (you don't follow back):{len(fans):>6}  -> saved to {out_fans}")
    print("=" * 62)

    if filtered_not_following:
        print(f"\nAccounts that DO NOT follow you back ({len(filtered_not_following)}):")
        for i, u in enumerate(filtered_not_following, 1):
            name = f" ({u['full_name']})" if u.get("full_name") else ""
            fc = f" [{format_count(u.get('follower_count'))} followers]" if u.get("follower_count") else ""
            print(f"  {i:>3}. @{u['username']}{name}{fc}")
            if i >= 100:
                remaining = len(filtered_not_following) - 100
                if remaining > 0:
                    print(f"  ... and {remaining} more (see {out_not_following})")
                break
    else:
        print("\nNo matching accounts found! 🎉")

    if excluded_big_accounts:
        print(f"\nSample excluded big accounts (>{format_count(follower_limit)} followers):")
        for u in excluded_big_accounts[:10]:
            fc = f" ({format_count(u.get('follower_count'))} followers)" if u.get("follower_count") else ""
            print(f"  • @{u['username']}{fc}")
        if len(excluded_big_accounts) > 10:
            print(f"  ... and {len(excluded_big_accounts) - 10} more in {out_excluded}")

    print()

    return {
        "user_id": user_id,
        "total_following": len(following),
        "total_followers": len(followers),
        "mutual": len(mutual),
        "not_following_back": filtered_not_following,
        "all_not_following": raw_not_following,
        "fans": fans,
        "excluded_big": excluded_big_accounts,
    }


def main():
    user_id = None
    max_filter = MAX_FOLLOWER_COUNT

    # Check CLI args
    args = sys.argv[1:]
    for arg in args:
        if arg.isdigit() and len(arg) > 5:
            user_id = arg
        elif arg.lower() in ("none", "all", "false"):
            max_filter = None
        else:
            # Check if user passed limit as an argument e.g. "1M", "500k"
            parsed = parse_follower_limit(arg)
            if parsed is not None:
                max_filter = arg

    if not user_id:
        available_ids = find_user_ids()
        if len(available_ids) == 1:
            user_id = available_ids[0]
            print(f"Auto-detected user ID: {user_id}")
        elif len(available_ids) > 1:
            sys.exit(
                f"Multiple user IDs found: {', '.join(available_ids)}.\n"
                f"Please specify one: python compare.py <user_id>"
            )
        else:
            sys.exit(
                "No followers_*.csv or following_*.csv files found.\n"
                "Usage: python compare.py <user_id>"
            )

    compare(user_id, max_filter)


if __name__ == "__main__":
    main()
