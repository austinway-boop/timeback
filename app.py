import os
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

# ---------------------------------------------------------------------------
# Register Blueprints  (each file = one team member's domain)
# ---------------------------------------------------------------------------
from routes.auth import auth_bp          # login / logout
from routes.dashboard import dashboard_bp  # student dashboard
from routes.admin import admin_bp          # admin dashboard

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(admin_bp)


# ---------------------------------------------------------------------------
# Timeback / Cognito credentials  (loaded from .env — see .env.example)
# ---------------------------------------------------------------------------
COGNITO_URL = "https://prod-beyond-timeback-api-2-idp.auth.us-east-1.amazoncognito.com/oauth2/token"
CLIENT_ID = os.getenv("TIMEBACK_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("TIMEBACK_CLIENT_SECRET", "")

ONEROSTER_BASE = "https://api.alpha-1edtech.ai"
PAGE_SIZE = 3000

_access_token = None


def get_token() -> str:
    global _access_token
    if _access_token:
        return _access_token
    resp = requests.post(
        COGNITO_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=30,
    )
    resp.raise_for_status()
    _access_token = resp.json()["access_token"]
    return _access_token


def api_headers() -> dict:
    return {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_user(raw: dict) -> dict:
    role = raw.get("role", "")
    if not role:
        roles = raw.get("roles", [])
        if isinstance(roles, list) and roles:
            first = roles[0]
            role = first.get("role", "") if isinstance(first, dict) else str(first)
    return {
        "sourcedId": raw.get("sourcedId", ""),
        "givenName": raw.get("givenName", ""),
        "familyName": raw.get("familyName", ""),
        "email": raw.get("email", ""),
        "role": role,
        "status": raw.get("status", ""),
        "username": raw.get("username", ""),
        "roles": raw.get("roles", []),
    }


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------
from flask import redirect, url_for

@app.route("/")
def index():
    return redirect(url_for("auth.login"))


# ---------------------------------------------------------------------------
# API routes  (shared across views — keep here or move to routes/api.py)
# ---------------------------------------------------------------------------
@app.route("/api/users")
def api_users():
    """Fetch ALL users using 3000-per-page batches (API max)."""
    global _access_token

    url = f"{ONEROSTER_BASE}/ims/oneroster/rostering/v1p2/users"
    all_users = []
    offset = 0
    batch = 0

    while True:
        batch += 1
        params = {"limit": PAGE_SIZE, "offset": offset}
        print(f"  Batch {batch}: offset={offset}", flush=True)

        try:
            resp = requests.get(url, headers=api_headers(), params=params, timeout=120)
            if resp.status_code == 401:
                _access_token = None
                resp = requests.get(url, headers=api_headers(), params=params, timeout=120)

            if resp.status_code != 200:
                print(f"  Batch {batch}: HTTP {resp.status_code}, stopping", flush=True)
                break

            data = resp.json()
            page_items = []
            for key in data:
                if isinstance(data[key], list):
                    page_items = data[key]
                    break

            print(f"  Batch {batch}: got {len(page_items)} users", flush=True)

            if not page_items:
                break

            all_users.extend(page_items)

            if len(page_items) < PAGE_SIZE:
                break

            offset += PAGE_SIZE

        except Exception as e:
            print(f"  Batch {batch}: ERROR {e}", flush=True)
            break

    users = [parse_user(u) for u in all_users]
    print(f"  Done: {len(users)} total users", flush=True)
    return jsonify({"users": users, "count": len(users)})


@app.route("/api/users/<sourced_id>")
def api_user_detail(sourced_id):
    """Get a single user by sourcedId."""
    global _access_token
    url = f"{ONEROSTER_BASE}/ims/oneroster/rostering/v1p2/users/{sourced_id}"
    try:
        resp = requests.get(url, headers=api_headers(), timeout=30)
        if resp.status_code == 401:
            _access_token = None
            resp = requests.get(url, headers=api_headers(), timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            user = data.get("user", data)
            return jsonify({"user": parse_user(user)})
        return jsonify({"error": f"HTTP {resp.status_code}"}), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/users/<sourced_id>/role", methods=["PUT"])
def api_update_role(sourced_id):
    """Update a user's role."""
    global _access_token
    body = request.get_json()
    new_role = body.get("role")
    if not new_role:
        return jsonify({"error": "Missing 'role' field"}), 400

    url = f"{ONEROSTER_BASE}/ims/oneroster/rostering/v1p2/users/{sourced_id}"
    try:
        resp = requests.get(url, headers=api_headers(), timeout=30)
        if resp.status_code == 401:
            _access_token = None
            resp = requests.get(url, headers=api_headers(), timeout=30)
        if resp.status_code != 200:
            return jsonify({"error": f"User fetch failed: HTTP {resp.status_code}"}), resp.status_code

        user_data = resp.json().get("user", resp.json())

        # Update the primary role
        for r in user_data.get("roles", []):
            if r.get("roleType") == "primary":
                r["role"] = new_role
                break

        put_resp = requests.put(url, headers=api_headers(), json={"user": user_data}, timeout=30)
        if put_resp.status_code in (200, 201):
            return jsonify({"success": True, "message": f"Role updated to {new_role}"})
        return jsonify({"error": f"Update failed: HTTP {put_resp.status_code}"}), put_resp.status_code

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="localhost", port=5050, debug=True)
