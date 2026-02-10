"""
Admin Dashboard routes.

Owner: [admin-team-member]
Blueprint prefix: /admin
"""

from flask import Blueprint, render_template

admin_bp = Blueprint("admin", __name__, template_folder="../templates")


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------
@admin_bp.route("/admin")
def admin_dashboard():
    return render_template("admin/dashboard.html", view="admin")


@admin_bp.route("/admin/students")
def admin_students():
    return render_template("admin/students.html", view="admin")


@admin_bp.route("/admin/courses")
def admin_courses():
    return render_template("admin/courses.html", view="admin")


@admin_bp.route("/admin/settings")
def admin_settings():
    return render_template("admin/settings.html", view="admin")
