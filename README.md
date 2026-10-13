# GhostScrapy

A lightweight web dashboard and CLI tool to track Instagram non-followers, fans, and mutual connections with built-in 1-click unfollow.

Runs entirely locally without requiring permanent environment configs or database setup. Session cookies are stored per user in local JSON/CSV files.

---

## Features

- **Non-Followers Detection**: Lists accounts you follow who don't follow you back.
- **Fans & Mutuals**: Separate views for users following you whom you don't follow back, and mutual connections.
- **Smart Filtering**: Exclude verified accounts and high-follower accounts (e.g. celebrities, brand pages) so your list stays relevant.
- **1-Click Unfollow**: Unfollow non-reciprocal accounts directly from the dashboard.
- **Profile Stats**: Live overview of followers, following, post count, and bio.
- **Ngrok Support**: Built-in `--ngrok` flag to generate a secure tunnel link if you want to access the dashboard remotely or share it.

---

## Installation

Requires Python 3.9+.

```bash
git clone https://github.com/<your-username>/GhostScrapy.git
cd GhostScrapy

pip install -r requirements.txt
```

---

## Running the Web App

Start the server:

```bash
python run.py
```

The app will start on `http://localhost:5050` and automatically open in your default browser.

To expose the dashboard via a temporary public ngrok URL:

```bash
python run.py --ngrok
```

---

## Getting Session Cookies

GhostScrapy interacts with Instagram's web endpoints using your existing browser session.

1. Open [instagram.com](https://www.instagram.com) in your browser and sign in.
2. Open Developer Tools (`F12` or `Ctrl+Shift+I` / `Cmd+Option+I`).
3. Go to **Application** (Chrome/Brave/Edge) or **Storage** (Firefox) -> **Cookies** -> `https://www.instagram.com`.
4. Copy the values for:
   - `ds_user_id` (your numeric account ID)
   - `sessionid` (your session cookie)
5. Paste them into the login prompt in the web dashboard.

---

## CLI Usage

If you prefer running from the command line without the web interface:

```bash
# Scrape relationships
python scrape_followers.py <user_id> following
python scrape_followers.py <user_id> followers
python scrape_followers.py <user_id> both

# Run comparison and output CSVs
python compare.py <user_id>

# Unfollow a specific account
python unfollow.py <username_or_id>           # dry-run preview
python unfollow.py <username_or_id> --confirm # live unfollow
```

---

## Output Files

Data is saved locally under `data/<user_id>/`:

- `following_<user_id>.csv`
- `followers_<user_id>.csv`
- `not_following_back_<user_id>.csv`
- `fans_<user_id>.csv`
- `excluded_big_accounts_<user_id>.csv`

All user data is listed in `.gitignore` and won't be committed to version control.

---

## Disclaimer

This project is intended for personal and educational use. It is not affiliated with or endorsed by Instagram/Meta. Use reasonable request limits to avoid temporary action blocks from Instagram.

---

## License

MIT
