"""
Authentication / Login routes.

Owner: [login-team-member]
Blueprint prefix: /
"""

from flask import Blueprint, render_template, request, redirect, url_for, session

auth_bp = Blueprint("auth", __name__, template_folder="../templates")


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Show the login form (GET) or process credentials (POST)."""
    error = None

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        # TODO: Replace with real authentication (Cognito, database, etc.)
        if email == "admin@alpha.school" and password == "admin":
            session["user"] = {
                "email": email,
                "role": "admin",
                "givenName": "Admin",
                "familyName": "User",
            }
            return redirect(url_for("admin.admin_dashboard"))

        elif email and password:
            # Default: treat as a student login
            session["user"] = {
                "email": email,
                "role": "student",
                "givenName": email.split("@")[0].title(),
                "familyName": "",
            }
            return redirect(url_for("dashboard.student_home"))

        else:
            error = "Please enter your email and password."

    return render_template("login.html", error=error)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
