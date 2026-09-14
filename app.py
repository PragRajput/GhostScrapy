#!/usr/bin/env python3
"""
GhostScrapy - Generic Multi-User Web Application
Flask backend providing Instagram authentication, per-session data isolation,
follower scraping, and non-reciprocal relationship analysis.
"""

import csv
import os
import secrets
import json
from flask import Flask, request, jsonify, render_template, send_from_directory, session

import auth
import scrape_followers
import compare

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")

# Persist secret key across server restarts so browser session is never dropped
SECRET_KEY_FILE = os.path.join(DATA_DIR, ".flask_secret")
if not os.path.exists(SECRET_KEY_FILE):
    with open(SECRET_KEY_FILE, "w") as f:
        f.write(secrets.token_hex(32))
with open(SECRET_KEY_FILE, "r") as f:
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", f.read().strip())

app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
)


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    return response


def get_user_data_dir(user_id):
    """Return a path to a directory isolated for this user."""
    path = os.path.join(DATA_DIR, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def save_user_credentials(user_id, cookies):
    """Save user credentials to isolated user directory."""
    user_dir = get_user_data_dir(user_id)
    creds_file = os.path.join(user_dir, "credentials.json")
    with open(creds_file, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)


def load_user_credentials(user_id):
    """Load saved user credentials if available."""
    user_dir = get_user_data_dir(user_id)
    creds_file = os.path.join(user_dir, "credentials.json")
    if os.path.exists(creds_file):
        try:
            with open(creds_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def mark_unfollowed_in_csv(user_id, pk):
    """Set unfollowed=True for one pk in not_following_back_<user_id>.csv (live update),
    so the cached list shows it as unfollowed on the next load without re-analyzing."""
    user_dir = get_user_data_dir(user_id)
    path = os.path.join(user_dir, f"not_following_back_{user_id}.csv")
    if not os.path.exists(path):
        return
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not fieldnames:
        return
    if "unfollowed" not in fieldnames:
        fieldnames.append("unfollowed")
    for r in rows:
        if str(r.get("pk")) == str(pk):
            r["unfollowed"] = "True"
        elif not r.get("unfollowed"):
            r["unfollowed"] = "False"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def sanitize_cookie_val(v, key=None):
    """Strip quotes, whitespace, and accidental key-prefixes from cookie input."""
    if not v:
        return ""
    v = str(v).strip()
    # Strip wrapping quotes
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1].strip()
    # Strip key prefix if user typed "sessionid=xyz" or "ds_user_id=123"
    if key and v.lower().startswith(f"{key.lower()}="):
        v = v[len(key) + 1:].strip()
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1].strip()
    return v


def get_active_credentials(user_id=None):
    """
    Retrieve active Instagram credentials.
    Checks:
    1. Active Flask session
    2. Explicit user_id from data/<user_id>/credentials.json
    3. Any existing saved credentials in data/<ds_user_id>/credentials.json
    """
    # 1. From active Flask session
    cookies = session.get("ig_cookies")
    if cookies and cookies.get("sessionid") and cookies.get("ds_user_id"):
        return cookies

    # 2. If user_id specified, load that account's saved creds.
    # NOTE: multi-user caveat — anyone who knows a saved account's numeric ID can
    # load its session this way. Acceptable only among people you trust; a fresh
    # visitor with no session of their own is NOT silently logged in as anyone.
    if user_id:
        creds = load_user_credentials(str(user_id))
        if creds and creds.get("sessionid") and creds.get("ds_user_id"):
            session["ig_cookies"] = creds
            return creds

    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/auth/status", methods=["GET"])
def auth_status():
    creds = get_active_credentials()
    if not creds:
        return jsonify({"authenticated": False})

    cached_profile = session.get("ig_profile")
    if cached_profile:
        return jsonify({"authenticated": True, "user": cached_profile})

    try:
        s = scrape_followers.build_session(creds)
        profile = auth.get_user_profile(s, creds.get("ds_user_id"))
        session["ig_profile"] = profile
        return jsonify({"authenticated": True, "user": profile})
    except Exception:
        return jsonify({
            "authenticated": True,
            "user": {
                "user_id": creds.get("ds_user_id"),
                "username": creds.get("ds_user_id"),
            }
        })


@app.route("/api/user/profile", methods=["GET"])
@app.route("/api/user/profile/<user_id>", methods=["GET"])
def get_profile(user_id=None):
    """
    Hit Instagram's user info API live and return up-to-date account details:
    Followers, Following, Posts, Bio, Full Name, Verification status.
    """
    creds = get_active_credentials(user_id=user_id)
    if not creds:
        return jsonify({"status": "error", "message": "Not authenticated. Connect with Instagram first."}), 401

    target_id = str(user_id or creds.get("ds_user_id"))

    try:
        s = scrape_followers.build_session(creds)
        profile = auth.get_user_profile(s, target_id)
        if profile and profile.get("follower_count") is not None:
            session["ig_profile"] = profile
            return jsonify({
                "status": "success",
                "profile": profile
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Could not fetch profile details for account {target_id}."
            }), 400
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        # Endpoint throttled but session still valid — do NOT prompt reconnect.
        if "rate-limiting" in low or "temporarily" in low:
            return jsonify({"status": "rate_limited", "message": msg}), 429
        # Session genuinely dead — prompt reconnect.
        if "expired" in low or "flagged" in low or "reconnect" in low or "unauthorized" in low:
            return jsonify({"status": "error", "message": msg, "auth_expired": True}), 401
        return jsonify({"status": "error", "message": msg}), 500


@app.route("/api/auth/check_user", methods=["POST"])
def auth_check_user():
    """
    Check if we have saved credentials for this user ID.
    If yes, test if they are still valid.
    If valid -> auto-login to session and return profile.
    If expired -> return status 'expired'.
    If not found -> return status 'not_found'.
    """
    data = request.get_json() or {}
    raw_user_id = str(data.get("user_id", "")).strip()
    if not raw_user_id:
        return jsonify({"status": "error", "message": "User ID is required."}), 400

    user_id = sanitize_cookie_val(raw_user_id, "ds_user_id")

    # If target is username instead of ID, check cache or profile
    if not user_id.isdigit():
        cache = scrape_followers._load_user_id_cache()
        cached_pk = cache.get(user_id)
        if cached_pk:
            user_id = cached_pk

    saved_creds = load_user_credentials(user_id)
    if not saved_creds:
        return jsonify({
            "status": "not_found",
            "user_id": user_id,
            "message": f"No saved credentials found for User ID {user_id}. Please enter your session cookies."
        })

    # Validate saved credentials with Instagram
    is_valid, profile_or_err = auth.verify_session(saved_creds)
    if is_valid:
        session["ig_cookies"] = saved_creds
        session["ig_profile"] = profile_or_err

        # Cache username -> user_id to prevent any web_profile_info 429 lookups
        if profile_or_err and profile_or_err.get("username"):
            cache = scrape_followers._load_user_id_cache()
            cache[profile_or_err["username"].lower()] = str(user_id)
            scrape_followers._save_user_id_cache(cache)

        return jsonify({
            "status": "valid",
            "user_id": user_id,
            "profile": profile_or_err,
            "message": "Saved session is valid."
        })
    else:
        return jsonify({
            "status": "expired",
            "user_id": user_id,
            "message": f"Saved session for User ID {user_id} has expired ({profile_or_err}). Please re-enter your session credentials."
        })


@app.route("/api/auth/connect_cookies", methods=["POST"])
def auth_connect_cookies():
    """
    Validate provided session cookies strictly against Instagram.
    If invalid: DO NOT save, DO NOT allow moving forward.
    If valid: save to data/<user_id>/credentials.json, set session, and return profile.
    """
    data = request.get_json() or {}
    raw_cookie_str = data.get("cookie_string", "").strip()

    cookies = {}
    if raw_cookie_str:
        if raw_cookie_str.lower().startswith("cookie:"):
            raw_cookie_str = raw_cookie_str[7:].strip()
        for part in raw_cookie_str.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                k = k.strip()
                cookies[k] = sanitize_cookie_val(v, k)
    else:
        cookies = {
            "sessionid": sanitize_cookie_val(data.get("sessionid", ""), "sessionid"),
            "csrftoken": sanitize_cookie_val(data.get("csrftoken", ""), "csrftoken"),
            "ds_user_id": sanitize_cookie_val(data.get("ds_user_id", ""), "ds_user_id"),
            "mid": sanitize_cookie_val(data.get("mid", ""), "mid"),
        }

    sessionid = cookies.get("sessionid")
    ds_user_id = cookies.get("ds_user_id")

    if not sessionid or not ds_user_id:
        return jsonify({
            "status": "error",
            "message": "Both User ID (ds_user_id) and Session ID (sessionid) are required."
        }), 400

    # Strictly verify with Instagram - NO redirects followed
    is_valid, profile_or_err = auth.verify_session(cookies)
    if not is_valid:
        # DO NOT SAVE, DO NOT SET SESSION
        return jsonify({
            "status": "error",
            "message": profile_or_err
        }), 400

    # Session is valid: save credentials to isolated user directory
    save_user_credentials(ds_user_id, cookies)
    session["ig_cookies"] = cookies
    session["ig_profile"] = profile_or_err

    # Cache username -> user_id to prevent any web_profile_info 429 lookups
    if profile_or_err and profile_or_err.get("username"):
        cache = scrape_followers._load_user_id_cache()
        cache[profile_or_err["username"].lower()] = str(ds_user_id)
        scrape_followers._save_user_id_cache(cache)

    return jsonify({
        "status": "success",
        "user_id": ds_user_id,
        "profile": profile_or_err
    })


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"status": "success"})


def is_valid_csv(filepath):
    """Check if a CSV file exists, is non-empty, and contains at least one data row."""
    if not os.path.exists(filepath):
        return False
    if os.path.getsize(filepath) <= 0:
        return False
    try:
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for _ in reader:
                return True
    except Exception:
        return False
    return False


@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json() or {}
    raw_target = str(data.get("target", "")).strip()

    creds = get_active_credentials(user_id=raw_target if raw_target.isdigit() else None)
    if not creds:
        return jsonify({"error": "Not authenticated. Please connect your Instagram session first.", "auth_expired": True}), 401

    target = raw_target or creds.get("ds_user_id")
    max_followers = data.get("max_followers", "10k")
    exclude_verified = bool(data.get("exclude_verified", True))
    force_refresh = bool(data.get("force_refresh", False))

    s = scrape_followers.build_session(creds)

    # Resolve username to user_id (prioritize numeric ID & cache to prevent 429)
    if target.isdigit():
        user_id = target
    elif not target or target.lower() in ("self", "me", "my_account") or target == creds.get("ds_user_id"):
        user_id = str(creds.get("ds_user_id"))
    elif creds.get("ds_user_id") and target.lower() == str(session.get("ig_profile", {}).get("username", "")).lower():
        user_id = str(creds.get("ds_user_id"))
    else:
        cache = scrape_followers._load_user_id_cache()
        cached = cache.get(target.lower())
        if isinstance(cached, str) and cached.isdigit():
            user_id = cached
        else:
            try:
                user_id = scrape_followers.resolve_user_id(s, target)
            except Exception as e:
                err_str = str(e)
                if "session expired" in err_str.lower() or "redirected to login" in err_str.lower():
                    return jsonify({"error": err_str, "auth_expired": True}), 401
                return jsonify({"error": f"Could not find Instagram user '{target}': {err_str}"}), 404

    user_dir = get_user_data_dir(user_id)
    followers_file = os.path.join(user_dir, f"followers_{user_id}.csv")
    following_file = os.path.join(user_dir, f"following_{user_id}.csv")

    # Scrape if missing/empty or if force_refresh requested
    need_followers = force_refresh or not is_valid_csv(followers_file)
    need_following = force_refresh or not is_valid_csv(following_file)

    try:
        if need_following:
            scrape_followers.scrape_relationship(s, user_id, "following", output_dir=user_dir)
        if need_followers:
            scrape_followers.scrape_relationship(s, user_id, "followers", output_dir=user_dir)

        # Run comparison with user filter
        result = compare.compare(
            user_id=user_id,
            max_followers_filter=max_followers,
            data_dir=user_dir,
            session=s,
            exclude_verified=exclude_verified,
        )

        return jsonify({
            "status": "success",
            "user_id": str(user_id),
            "target": target,
            "filter_applied": max_followers,
            "exclude_verified": exclude_verified,
            "stats": {
                "total_following": result["total_following"],
                "total_followers": result["total_followers"],
                "not_following_back": len(result["not_following_back"]),
                "all_not_following": len(result["all_not_following"]),
                "excluded_big": len(result["excluded_big"]),
                "fans": len(result["fans"]),
            },
            "not_following_back": result["not_following_back"],
            "fans": result["fans"],
            "excluded_big": result["excluded_big"],
        })

    except Exception as e:
        err_str = str(e)
        if (
            "session expired" in err_str.lower()
            or "redirected to login" in err_str.lower()
            or "unauthorized" in err_str.lower()
            or "html page instead of json" in err_str.lower()
            or "html instead of json" in err_str.lower()
            or "redirected to the homepage" in err_str.lower()
            or "did not accept this session" in err_str.lower()
        ):
            return jsonify({"error": err_str, "auth_expired": True}), 401
        return jsonify({"error": f"Analysis failed: {err_str}"}), 500


@app.route("/api/saved_results/<target>", methods=["GET"])
def get_saved_results(target):
    target = target.strip()
    if not target:
        return jsonify({"status": "none"}), 404

    user_id = target
    if not user_id.isdigit():
        creds = get_active_credentials()
        if creds and creds.get("ds_user_id") and (not target or target.lower() == str(session.get("ig_profile", {}).get("username", "")).lower()):
            user_id = str(creds.get("ds_user_id"))
        else:
            cache = scrape_followers._load_user_id_cache()
            cached = cache.get(target.lower())
            if isinstance(cached, str) and cached.isdigit():
                user_id = cached

    user_dir = get_user_data_dir(user_id)
    not_following_file = os.path.join(user_dir, f"not_following_back_{user_id}.csv")

    if not is_valid_csv(not_following_file):
        return jsonify({"status": "none"}), 404

    not_following = compare.load_csv(not_following_file) or {}
    fans_file = os.path.join(user_dir, f"fans_{user_id}.csv")
    fans = compare.load_csv(fans_file) or {}

    excluded_file = os.path.join(user_dir, f"excluded_big_accounts_{user_id}.csv")
    excluded = compare.load_csv(excluded_file) or {}

    followers_file = os.path.join(user_dir, f"followers_{user_id}.csv")
    followers = compare.load_csv(followers_file) or {}

    following_file = os.path.join(user_dir, f"following_{user_id}.csv")
    following = compare.load_csv(following_file) or {}

    return jsonify({
        "status": "success",
        "user_id": str(user_id),
        "target": target,
        "stats": {
            "total_following": len(following),
            "total_followers": len(followers),
            "not_following_back": len(not_following),
            "all_not_following": len(not_following) + len(excluded),
            "excluded_big": len(excluded),
            "fans": len(fans),
        },
        "not_following_back": list(not_following.values()),
        "fans": list(fans.values()),
        "excluded_big": list(excluded.values()),
    })


@app.route("/api/export/<user_id>/<filename>", methods=["GET"])
def export_file(user_id, filename):
    user_dir = get_user_data_dir(user_id)
    safe_filename = os.path.basename(filename)
    if not safe_filename.endswith(".csv"):
        return jsonify({"error": "Invalid file type"}), 400
    return send_from_directory(user_dir, safe_filename, as_attachment=True)


@app.route("/api/unfollow", methods=["POST"])
def api_unfollow():
    creds = get_active_credentials()
    if not creds:
        return jsonify({"error": "Not authenticated. Connect with Instagram first.", "auth_expired": True}), 401

    data = request.get_json() or {}
    target_user_id = str(data.get("target_user_id", "")).strip()
    username = data.get("username", "")

    if not target_user_id:
        return jsonify({"error": "target_user_id is required."}), 400

    s = scrape_followers.build_session(creds)
    import unfollow
    outcome, detail = unfollow.unfollow(s, target_user_id)

    if outcome == "ok":
        owner_id = creds.get("ds_user_id")
        user_dir = get_user_data_dir(owner_id)
        unfollow.log_unfollow(target_user_id, username or target_user_id, log_dir=user_dir)
        mark_unfollowed_in_csv(owner_id, target_user_id)
        return jsonify({
            "status": "success",
            "message": f"Successfully unfollowed @{username or target_user_id}",
            "target_user_id": target_user_id
        })
    elif outcome == "failed":
        return jsonify({"status": "failed", "message": str(detail)}), 400
    else:
        return jsonify({"status": "unknown", "message": str(detail)}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
