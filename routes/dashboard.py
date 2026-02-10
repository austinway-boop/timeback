"""
Student Dashboard routes.

Owner: [dashboard-team-member]
Blueprint prefix: /student
"""

from flask import Blueprint, render_template

dashboard_bp = Blueprint("dashboard", __name__, template_folder="../templates")


# ---------------------------------------------------------------------------
# Demo data for student view
# ---------------------------------------------------------------------------
DEMO_USER = {
    "givenName": "Austin",
    "familyName": "Way",
    "email": "austin@alpha.school",
    "role": "student",
}

DEMO_COURSES = [
    {
        "id": 1,
        "name": "Math Academy - SAT Math Fundamentals",
        "color": "teal",
        "icon": "fa-calculator",
        "xp_earned": 0,
        "xp_total": 60,
        "lessons_left": 0,
        "image_style": "math",
    },
    {
        "id": 2,
        "name": "AP Language and Composition",
        "color": "purple",
        "icon": "fa-book-open",
        "xp_earned": 0,
        "xp_total": 30,
        "lessons_left": 1,
        "image_style": "language",
    },
    {
        "id": 3,
        "name": "eGumpp",
        "color": "purple",
        "icon": "fa-laptop-code",
        "xp_earned": 0,
        "xp_total": 15,
        "lessons_left": 0,
        "image_style": "tech",
    },
    {
        "id": 4,
        "name": "Chemistry Honors",
        "color": "pink",
        "icon": "fa-atom",
        "xp_earned": 0,
        "xp_total": 45,
        "lessons_left": 2,
        "image_style": "science",
    },
    {
        "id": 5,
        "name": "Biology Fundamentals",
        "color": "pink",
        "icon": "fa-dna",
        "xp_earned": 0,
        "xp_total": 30,
        "lessons_left": 0,
        "image_style": "biology",
    },
    {
        "id": 6,
        "name": "World Geography",
        "color": "orange",
        "icon": "fa-globe-americas",
        "xp_earned": 0,
        "xp_total": 25,
        "lessons_left": 1,
        "image_style": "geography",
    },
]

DEMO_TESTS = [
    {
        "id": 1,
        "name": "Reading Mastery Test",
        "grade": "Grade 11",
        "xp": 120,
        "image_style": "reading",
    },
]


# ---------------------------------------------------------------------------
# Student routes
# ---------------------------------------------------------------------------
@dashboard_bp.route("/dashboard")
@dashboard_bp.route("/student")
def student_home():
    return render_template(
        "student/home.html",
        user=DEMO_USER,
        courses=DEMO_COURSES,
        tests=DEMO_TESTS,
        view="student",
    )
