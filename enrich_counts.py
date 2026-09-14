#!/usr/bin/env python3
"""
Fill the follower_count column of a not_following_back_*.csv.

One lookup per account against web_profile_info, which is heavily rate-limited,
so this is paced, cached, and resumable: progress is written to the CSV and to
follower_counts_cache.json as it goes. If Instagram starts blocking, it stops
and saves; re-run later to continue where it left off.

Usage:
    python3 enrich_counts.py not_following_back_3623970259.csv
"""

import csv
import os
import random
import sys
import time

import compare
import scrape_followers

BASE = scrape_followers.BASE
DELAY = (1.5, 3.0)
MAX_RETRIES = 3
SAVE_EVERY = 10


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 enrich_counts.py <not_following_back_*.csv>")

    path = sys.argv[1]
    if not os.path.exists(path):
        sys.exit(f"No such file: {path}")

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if "follower_count" not in fieldnames:
        fieldnames.append("follower_count")

    cache = compare.load_cache()

    # Fill anything already known from the cache before touching the network.
    prefilled = 0
    todo = []
    for r in rows:
        if str(r.get("follower_count", "")).strip():
            continue
        username = r.get("username", "")
        if username in cache:
            val = cache[username]
            r["follower_count"] = "" if val is None else val
            prefilled += 1
        else:
            todo.append(r)

    print(f"{len(rows)} rows | {prefilled} filled from cache | {len(todo)} need lookups")
    if prefilled:
        write_csv(path, fieldnames, rows)

    if not todo:
        print("Nothing left to look up.")
        return

    s = scrape_followers.build_session()
    done = 0

    for i, r in enumerate(todo, 1):
        username = r.get("username", "")
        if not username:
            continue

        stop = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = s.get(
                    f"{BASE}/users/web_profile_info/",
                    params={"username": username},
                    timeout=15,
                )
            except Exception as e:
                print(f"  [{i}/{len(todo)}] @{username}: request failed ({e})")
                break

            if resp.status_code == 200:
                try:
                    count = (
                        resp.json()
                        .get("data", {})
                        .get("user", {})
                        .get("edge_followed_by", {})
                        .get("count")
                    )
                except ValueError:
                    print(f"  [{i}/{len(todo)}] @{username}: non-JSON reply, skipping")
                    break
                cache[username] = count
                r["follower_count"] = "" if count is None else count
                done += 1
                print(f"  [{i}/{len(todo)}] @{username}: {compare.format_count(count)}")
                break

            if resp.status_code in (404, 400):
                cache[username] = None
                r["follower_count"] = ""
                print(f"  [{i}/{len(todo)}] @{username}: unavailable ({resp.status_code})")
                break

            if resp.status_code == 429:
                if attempt == MAX_RETRIES:
                    print(
                        f"  [Notice] Still rate-limited at @{username} after {attempt} "
                        f"attempts. Saving and stopping; {len(todo) - i + 1} remain."
                    )
                    stop = True
                    break
                wait = 30 * attempt
                print(f"  [Notice] 429 at @{username} — waiting {wait}s "
                      f"(attempt {attempt}/{MAX_RETRIES})")
                time.sleep(wait)
                continue

            print(f"  [{i}/{len(todo)}] @{username}: HTTP {resp.status_code}")
            break

        if done and done % SAVE_EVERY == 0:
            write_csv(path, fieldnames, rows)
            compare.save_cache(cache)

        if stop:
            break

        time.sleep(random.uniform(*DELAY))

    write_csv(path, fieldnames, rows)
    compare.save_cache(cache)

    filled = sum(1 for r in rows if str(r.get("follower_count", "")).strip())
    print(f"\nLooked up {done} this run. {filled}/{len(rows)} rows now have a count.")
    print(f"Saved -> {path}")


if __name__ == "__main__":
    main()
