"""POST/GET/DELETE /api/diagnostic-assign — Manage diagnostic assignments.

POST: Assign a diagnostic to a student
  Body: { studentId, courseId }
  Creates KV entry: diagnostic_assignment:{studentId}:{courseId}

GET: Check diagnostic assignments
  ?studentId=X&courseId=Y → single assignment
  ?studentId=X → all pending assignments for student
  ?courseId=Y → all assignments for a course

DELETE: Remove an assignment
  Body: { studentId, courseId }
"""

import json
import time
from http.server import BaseHTTPRequestHandler

from api._helpers import send_json, get_query_params
from api._kv import kv_get, kv_set, kv_delete, kv_list_get, kv_list_push, kv_list_remove


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        student_id = params.get("studentId", "").strip()
        course_id = params.get("courseId", "").strip()

        if student_id and course_id:
            # Check specific assignment
            assignment = kv_get(f"diagnostic_assignment:{student_id}:{course_id}")
            if isinstance(assignment, dict):
                send_json(self, {"assignment": assignment, "exists": True})
            else:
                send_json(self, {"assignment": None, "exists": False})
            return

        if student_id:
            # List all assignments for a student
            assignment_keys = kv_get(f"diagnostic_assignments_list:{student_id}")
            if not isinstance(assignment_keys, list):
                assignment_keys = []

            assignments = []
            for cid in assignment_keys:
                a = kv_get(f"diagnostic_assignment:{student_id}:{cid}")
                if isinstance(a, dict) and a.get("status") != "removed":
                    assignments.append(a)

            send_json(self, {"assignments": assignments, "count": len(assignments)})
            return

        if course_id:
            # List all assignments for a course
            assignment_ids = kv_get(f"diagnostic_course_assignments:{course_id}")
            if not isinstance(assignment_ids, list):
                assignment_ids = []

            assignments = []
            for sid in assignment_ids:
                a = kv_get(f"diagnostic_assignment:{sid}:{course_id}")
                if isinstance(a, dict) and a.get("status") != "removed":
                    assignments.append(a)

            send_json(self, {"assignments": assignments, "count": len(assignments)})
            return

        send_json(self, {"error": "Missing studentId or courseId parameter"}, 400)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            send_json(self, {"error": "Invalid JSON"}, 400)
            return

        student_id = body.get("studentId", "").strip()
        course_id = body.get("courseId", "").strip()

        if not student_id or not course_id:
            send_json(self, {"error": "Missing studentId or courseId"}, 400)
            return

        # Check diagnostic exists for this course
        diagnostic = kv_get(f"diagnostic:{course_id}")
        if not isinstance(diagnostic, dict) or not diagnostic.get("items"):
            send_json(self, {
                "error": "No diagnostic found for this course. Generate one first."
            }, 400)
            return

        # Check if already assigned
        existing = kv_get(f"diagnostic_assignment:{student_id}:{course_id}")
        if isinstance(existing, dict) and existing.get("status") in ("assigned", "in_progress"):
            send_json(self, {
                "assignment": existing,
                "message": "Diagnostic already assigned to this student",
                "success": True,
            })
            return

        # Create assignment
        assignment = {
            "studentId": student_id,
            "courseId": course_id,
            "courseTitle": diagnostic.get("courseTitle", ""),
            "status": "assigned",
            "assignedAt": time.time(),
            "startedAt": None,
            "completedAt": None,
            "totalItems": len(diagnostic.get("items", [])),
            "answers": {},
            "score": None,
            "placementLevel": None,
            "skillResults": {},
        }

        # Save assignment
        kv_set(f"diagnostic_assignment:{student_id}:{course_id}", assignment)

        # Add to index lists for lookups
        # Student's assignment list
        student_courses = kv_get(f"diagnostic_assignments_list:{student_id}")
        if not isinstance(student_courses, list):
            student_courses = []
        if course_id not in student_courses:
            student_courses.append(course_id)
            kv_set(f"diagnostic_assignments_list:{student_id}", student_courses)

        # Course's assignment list
        course_students = kv_get(f"diagnostic_course_assignments:{course_id}")
        if not isinstance(course_students, list):
            course_students = []
        if student_id not in course_students:
            course_students.append(student_id)
            kv_set(f"diagnostic_course_assignments:{course_id}", course_students)

        send_json(self, {
            "assignment": assignment,
            "message": "Diagnostic assigned successfully",
            "success": True,
        })

    def do_DELETE(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            send_json(self, {"error": "Invalid JSON"}, 400)
            return

        student_id = body.get("studentId", "").strip()
        course_id = body.get("courseId", "").strip()

        if not student_id or not course_id:
            send_json(self, {"error": "Missing studentId or courseId"}, 400)
            return

        # Delete the assignment
        kv_delete(f"diagnostic_assignment:{student_id}:{course_id}")

        # Remove from index lists
        student_courses = kv_get(f"diagnostic_assignments_list:{student_id}")
        if isinstance(student_courses, list) and course_id in student_courses:
            student_courses.remove(course_id)
            kv_set(f"diagnostic_assignments_list:{student_id}", student_courses)

        course_students = kv_get(f"diagnostic_course_assignments:{course_id}")
        if isinstance(course_students, list) and student_id in course_students:
            course_students.remove(student_id)
            kv_set(f"diagnostic_course_assignments:{course_id}", course_students)

        send_json(self, {"success": True, "message": "Assignment removed"})
