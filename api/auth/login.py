"""POST /api/auth/login — Email/password login via Timeback API.

Looks up the user by email in OneRoster, then uses the Timeback
credentials system to verify the password:

  1. Find the user's "AlphaLearn" credential in their userProfiles
  2. Decrypt it via POST /users/{id}/credentials/{credId}/decrypt
  3. Compare the decrypted password with what the user provided

If the user exists but has no credential yet (e.g. they were created
outside of this app), the first login registers their password.
"""

import json
from http.server import BaseHTTPRequestHandler

from api._helpers import (
    fetch_with_params,
    post_resource,
    parse_user,
    send_json,
)

APP_NAME = "AlphaLearn"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _lookup_user_by_email(email: str) -> tuple[dict | None, dict | None]:
    """Find a user in OneRoster by email.

    Returns (raw_user_dict, parsed_user_dict) or (None, None).
    """
    data, status = fetch_with_params(
        "/ims/oneroster/rostering/v1p2/users",
        {"filter": f"email='{email}'"},
    )
    if data and status == 200:
        users = data.get("users", [])
        if not users:
            for val in data.values():
                if isinstance(val, list) and val:
                    users = val
                    break
        if users:
            return users[0], parse_user(users[0])
    return None, None


def _find_app_credential(user_profiles: list) -> tuple[str | None, str | None]:
    """Search userProfiles for our app's credential.

    Returns (profileId, credentialId) or (None, None).
    The exact shape of userProfiles varies, so we search flexibly.
    """
    for profile in user_profiles:
        if not isinstance(profile, dict):
            continue

        # Check if this profile belongs to our app
        profile_type = (
            profile.get("profileType", "")
            or profile.get("applicationName", "")
            or profile.get("vendorId", "")
            or profile.get("description", "")
        )
        if APP_NAME.lower() not in str(profile_type).lower():
            # Also check nested fields
            if APP_NAME.lower() not in json.dumps(profile).lower():
                continue

        # Try to extract the credential ID
        cred_id = (
            profile.get("credentialId")
            or profile.get("credential_id")
            or profile.get("sourcedId")
        )
        profile_id = (
            profile.get("profileId")
            or profile.get("userProfileId")
            or profile.get("sourcedId")
        )

        if cred_id:
            return profile_id, cred_id

    return None, None


def _decrypt_credential(user_id: str, credential_id: str) -> str | None:
    """Decrypt a stored credential and return the plaintext password."""
    path = f"/ims/oneroster/rostering/v1p2/users/{user_id}/credentials/{credential_id}/decrypt"
    resp_data, status = post_resource(path, {})
    if resp_data and status == 200:
        return resp_data.get("password")
    return None


def _register_credential(user_id: str, email: str, password: str) -> tuple[str | None, str | None]:
    """Register a new credential for our app. Returns (credentialId, error)."""
    path = f"/ims/oneroster/rostering/v1p2/users/{user_id}/credentials"
    payload = {
        "applicationName": APP_NAME,
        "credentials": {
            "username": email,
            "password": password,
        },
    }
    resp_data, status = post_resource(path, payload)
    if resp_data and status in (200, 201):
        return resp_data.get("credentialId"), None
    error_msg = "Failed to register credential"
    if resp_data and isinstance(resp_data, dict):
        error_msg = resp_data.get("message") or resp_data.get("error") or error_msg
    return None, error_msg


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        """CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, Authorization"
        )
        self.end_headers()

    def do_GET(self):
        send_json(self, {"error": "Method not allowed. Use POST.", "success": False}, 405)

    def do_POST(self):
        try:
            # --- Parse body ---------------------------------------------------
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)
            data = json.loads(raw_body)

            email = data.get("email", "").strip()
            password = data.get("password", "")
            debug_requested = data.get("debug", False)

            if not email or not password:
                send_json(
                    self,
                    {"error": "Email and password are required", "success": False},
                    400,
                )
                return

            # --- Look up user in Timeback OneRoster ---------------------------
            raw_user, user = _lookup_user_by_email(email)

            if not raw_user:
                send_json(
                    self,
                    {"error": "No account found with that email", "success": False},
                    401,
                )
                return

            user_id = raw_user.get("sourcedId", "")
            user_profiles = raw_user.get("userProfiles", [])

            # --- Find existing credential for our app ------------------------
            _profile_id, credential_id = _find_app_credential(user_profiles)

            debug_info = {
                "userFound": True,
                "userSourcedId": user_id,
                "userProfilesCount": len(user_profiles),
                "userProfiles": user_profiles,
                "credentialFound": credential_id is not None,
                "credentialId": credential_id,
            }

            if credential_id:
                # --- Decrypt and compare --------------------------------------
                stored_password = _decrypt_credential(user_id, credential_id)
                debug_info["decryptSuccess"] = stored_password is not None
                debug_info["passwordMatch"] = (stored_password == password) if stored_password else False

                if not stored_password:
                    resp = {"error": "Unable to verify password", "success": False}
                    if debug_requested:
                        resp["debug"] = debug_info
                    send_json(self, resp, 500)
                    return

                if stored_password != password:
                    resp = {"error": "Invalid password", "success": False}
                    if debug_requested:
                        resp["debug"] = debug_info
                    send_json(self, resp, 401)
                    return

                send_json(self, {"user": user, "success": True})

            else:
                # --- No credential yet: first-time setup ----------------------
                # Register the provided password as the user's credential
                # for this app (one-time for existing Timeback users).
                new_cred_id, reg_error = _register_credential(user_id, email, password)

                debug_info["firstTimeSetup"] = True
                debug_info["registrationSuccess"] = new_cred_id is not None
                debug_info["registrationError"] = reg_error

                if not new_cred_id:
                    resp = {
                        "error": reg_error or "Unable to set up login credentials",
                        "success": False,
                    }
                    if debug_requested:
                        resp["debug"] = debug_info
                    send_json(self, resp, 500)
                    return

                # Password was just registered — user is authenticated
                send_json(self, {"user": user, "success": True})

        except json.JSONDecodeError:
            send_json(self, {"error": "Invalid JSON body", "success": False}, 400)
        except Exception as exc:
            send_json(self, {"error": str(exc), "success": False}, 500)
