#!/usr/bin/env python3
"""
Instagram Session Authentication Engine
Validates Instagram session cookies and fetches user profile details.
"""

import requests

APP_ID = "936619743392459"
ASBD_ID = "129477"
BASE = "https://www.instagram.com/api/v1"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)


def get_base_headers(csrftoken=None):
    headers = {
        "User-Agent": USER_AGENT,
        "X-IG-App-ID": APP_ID,
        "X-ASBD-ID": ASBD_ID,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.instagram.com/",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    if csrftoken:
        headers["X-CSRFToken"] = csrftoken
    return headers


def normalize_sessionid(sid):
    """Ensure colons in sessionid are URL-encoded as %3A per Instagram standard."""
    if not sid:
        return ""
    sid = str(sid).strip()
    if "%253A" in sid.upper():
        sid = sid.replace("%253A", "%3A").replace("%253a", "%3A")
    if ":" in sid and "%3A" not in sid:
        sid = sid.replace(":", "%3A")
    return sid


def build_session_from_cookies(cookies_dict):
    """Construct an authenticated requests.Session from cookie dictionary."""
    s = requests.Session()
    csrftoken = cookies_dict.get("csrftoken", "")
    s.headers.update(get_base_headers(csrftoken=csrftoken))

    # Set each cookie cleanly ONCE on .instagram.com
    for k, v in cookies_dict.items():
        if v:
            val = normalize_sessionid(v) if k == "sessionid" else str(v)
            s.cookies.set(k, val, domain=".instagram.com")

    return s


def verify_session(session_dict):
    """
    Validate that the provided session credentials can make authenticated requests.
    Returns (is_valid, user_info_or_error).
    Handles region routing (rur) redirects while strictly catching login redirects.
    """
    if not session_dict or not isinstance(session_dict, dict):
        return False, "No session credentials provided."

    sessionid = session_dict.get("sessionid", "").strip()
    ds_user_id = str(session_dict.get("ds_user_id", "")).strip()

    if not sessionid or not ds_user_id:
        return False, "Both User ID (ds_user_id) and Session ID (sessionid) are required."

    session = build_session_from_cookies(session_dict)

    try:
        # Primary check: /api/v1/users/{ds_user_id}/info/
        r = session.get(
            f"{BASE}/users/{ds_user_id}/info/",
            timeout=15,
        )

        is_login = ("login" in r.url.lower()) or any(
            "login" in resp.headers.get("Location", "").lower() for resp in r.history
        )
        content_type = r.headers.get("Content-Type", "").lower()

        if not is_login and r.status_code == 200 and "application/json" in content_type:
            try:
                data = r.json()
                if data.get("status") == "ok" and "user" in data:
                    u = data["user"]
                    profile = {
                        "user_id": str(ds_user_id),
                        "username": u.get("username", str(ds_user_id)),
                        "full_name": u.get("full_name", ""),
                        "profile_pic_url": u.get("profile_pic_url", ""),
                        "is_verified": u.get("is_verified", False),
                        "follower_count": u.get("follower_count", 0),
                        "following_count": u.get("following_count", 0),
                    }
                    return True, profile
            except Exception:
                pass

        # Secondary check: /api/v1/friendships/{ds_user_id}/followers/?count=1
        r2 = session.get(
            f"{BASE}/friendships/{ds_user_id}/followers/",
            params={"count": 1, "search_surface": "follow_list_page"},
            timeout=15,
        )

        is_login_2 = ("login" in r2.url.lower()) or any(
            "login" in resp.headers.get("Location", "").lower() for resp in r2.history
        )
        content_type_2 = r2.headers.get("Content-Type", "").lower()

        if not is_login_2 and r2.status_code == 200 and "application/json" in content_type_2:
            try:
                data2 = r2.json()
                if data2.get("status") == "ok" or "users" in data2:
                    profile = get_user_profile(session, ds_user_id)
                    return True, profile
            except Exception:
                pass

        if is_login or is_login_2:
            return False, "Instagram rejected your session credentials (sessionid is invalid or expired). Please check that you copied the complete sessionid."

        if r.status_code in (401, 403) or r2.status_code in (401, 403):
            return False, "Instagram session unauthorized (HTTP 401/403). Session ID is invalid or expired."

        return False, "Instagram session verification failed. Your sessionid cookie may be expired or incomplete."

    except requests.RequestException as e:
        return False, f"Connection to Instagram failed: {str(e)}"
    except Exception as e:
        return False, f"Verification failed: {str(e)}"


def get_user_profile(session, user_id):
    """Fetch rich profile data for the account."""
    try:
        r = session.get(
            f"{BASE}/users/{user_id}/info/",
            timeout=15,
        )
        if r.status_code == 200 and "application/json" in r.headers.get("Content-Type", "").lower():
            u = r.json().get("user", {})
            return {
                "user_id": str(user_id),
                "username": u.get("username", str(user_id)),
                "full_name": u.get("full_name", ""),
                "profile_pic_url": u.get("profile_pic_url", ""),
                "is_verified": u.get("is_verified", False),
                "is_private": u.get("is_private", False),
                "biography": u.get("biography", ""),
                "external_url": u.get("external_url", ""),
                "follower_count": u.get("follower_count", 0),
                "following_count": u.get("following_count", 0),
                "media_count": u.get("media_count", 0),
            }
    except Exception:
        pass

    return {
        "user_id": str(user_id),
        "username": str(user_id),
        "full_name": "",
        "profile_pic_url": "",
        "is_verified": False,
        "is_private": False,
        "biography": "",
        "external_url": "",
        "follower_count": None,
        "following_count": None,
        "media_count": None,
    }
