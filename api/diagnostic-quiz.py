"""GET/POST /api/diagnostic-quiz — Serve and score diagnostic quiz.

GET ?studentId=X&courseId=Y
    Returns diagnostic items (without correct answers) for student to take.
    Also returns assignment status.

POST { studentId, courseId, answers: { itemId: selectedOptionId, ... } }
    Scores the submission, computes per-skill results, determines placement,
    and marks the assignment as completed.
"""

import json
import time
from http.server import BaseHTTPRequestHandler

from api._helpers import send_json, get_query_params
from api._kv import kv_get, kv_set


def _strip_answers(items: list) -> list:
    """Remove correct answer indicators from items for student view."""
    safe_items = []
    for item in items:
        safe_item = {
            "id": item.get("id", ""),
            "stem": item.get("stem", ""),
            "stimulus": item.get("stimulus"),
            "stimulusGroup": item.get("stimulusGroup"),
            "bloomsLevel": item.get("bloomsLevel", ""),
            "options": [],
        }
        for opt in item.get("options", []):
            safe_item["options"].append({
                "id": opt.get("id", ""),
                "text": opt.get("text", ""),
            })
        safe_items.append(safe_item)
    return safe_items


def _score_diagnostic(items: list, answers: dict, cut_scores: list) -> dict:
    """Score the diagnostic submission and determine placement."""
    total = len(items)
    correct = 0
    skill_results = {}
    item_results = []

    for item in items:
        item_id = item.get("id", "")
        selected = answers.get(item_id, "")
        correct_answer = item.get("correctAnswer", "")
        is_correct = selected == correct_answer

        if is_correct:
            correct += 1

        # Track per-gateway-node results
        gateway_id = item.get("gatewayNodeId", "")
        if gateway_id:
            if gateway_id not in skill_results:
                skill_results[gateway_id] = {
                    "label": item.get("gatewayNodeLabel", ""),
                    "tested": 0,
                    "correct": 0,
                }
            skill_results[gateway_id]["tested"] += 1
            if is_correct:
                skill_results[gateway_id]["correct"] += 1

        # Build item result (for detailed feedback)
        item_result = {
            "itemId": item_id,
            "selected": selected,
            "correctAnswer": correct_answer,
            "isCorrect": is_correct,
            "gatewayNodeId": gateway_id,
        }

        # Find the misconception for wrong answers
        if not is_correct and selected:
            for opt in item.get("options", []):
                if opt.get("id") == selected and opt.get("misconception"):
                    item_result["misconception"] = opt["misconception"]
                    break

        item_results.append(item_result)

    # Compute overall percentage
    score_pct = round((correct / total) * 100, 1) if total > 0 else 0

    # Determine placement level from cut scores
    placement_level = None
    if isinstance(cut_scores, list) and cut_scores:
        # Sort by minCorrectPercent descending to find highest qualifying level
        sorted_cuts = sorted(cut_scores, key=lambda c: c.get("minCorrectPercent", 0), reverse=True)
        for level in sorted_cuts:
            if score_pct >= level.get("minCorrectPercent", 0):
                placement_level = level
                break
        if not placement_level:
            placement_level = sorted_cuts[-1]  # Lowest level
    else:
        # Default placement levels if none defined
        if score_pct >= 80:
            placement_level = {"level": 4, "name": "Advanced", "description": "Strong mastery of most skills"}
        elif score_pct >= 60:
            placement_level = {"level": 3, "name": "Proficient", "description": "Good foundation with some gaps"}
        elif score_pct >= 40:
            placement_level = {"level": 2, "name": "Developing", "description": "Significant gaps in foundational skills"}
        else:
            placement_level = {"level": 1, "name": "Foundational", "description": "Needs comprehensive review"}

    # Compute per-skill mastery
    for sid, sr in skill_results.items():
        sr["mastery"] = round((sr["correct"] / sr["tested"]) * 100, 1) if sr["tested"] > 0 else 0

    return {
        "totalItems": total,
        "correctCount": correct,
        "scorePercent": score_pct,
        "placementLevel": placement_level,
        "skillResults": skill_results,
        "itemResults": item_results,
    }


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        student_id = params.get("studentId", "").strip()
        course_id = params.get("courseId", "").strip()

        if not student_id or not course_id:
            send_json(self, {"error": "Missing studentId or courseId"}, 400)
            return

        # Check assignment exists
        assignment = kv_get(f"diagnostic_assignment:{student_id}:{course_id}")
        if not isinstance(assignment, dict):
            send_json(self, {"error": "No diagnostic assignment found"}, 404)
            return

        if assignment.get("status") == "completed":
            send_json(self, {
                "status": "completed",
                "score": assignment.get("score"),
                "placementLevel": assignment.get("placementLevel"),
                "completedAt": assignment.get("completedAt"),
            })
            return

        # Load diagnostic
        diagnostic = kv_get(f"diagnostic:{course_id}")
        if not isinstance(diagnostic, dict) or not diagnostic.get("items"):
            send_json(self, {"error": "Diagnostic not found for this course"}, 404)
            return

        # Mark as in_progress if just starting
        if assignment.get("status") == "assigned":
            assignment["status"] = "in_progress"
            assignment["startedAt"] = time.time()
            kv_set(f"diagnostic_assignment:{student_id}:{course_id}", assignment)

        # Return items without answers
        safe_items = _strip_answers(diagnostic["items"])

        send_json(self, {
            "status": "in_progress",
            "courseTitle": diagnostic.get("courseTitle", ""),
            "items": safe_items,
            "totalItems": len(safe_items),
        })

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
        answers = body.get("answers", {})

        if not student_id or not course_id:
            send_json(self, {"error": "Missing studentId or courseId"}, 400)
            return
        if not isinstance(answers, dict) or len(answers) == 0:
            send_json(self, {"error": "No answers provided"}, 400)
            return

        # Check assignment
        assignment = kv_get(f"diagnostic_assignment:{student_id}:{course_id}")
        if not isinstance(assignment, dict):
            send_json(self, {"error": "No diagnostic assignment found"}, 404)
            return

        if assignment.get("status") == "completed":
            send_json(self, {
                "error": "Diagnostic already completed",
                "score": assignment.get("score"),
                "placementLevel": assignment.get("placementLevel"),
            })
            return

        # Load diagnostic (with answers for scoring)
        diagnostic = kv_get(f"diagnostic:{course_id}")
        if not isinstance(diagnostic, dict) or not diagnostic.get("items"):
            send_json(self, {"error": "Diagnostic not found"}, 404)
            return

        # Score the submission
        cut_scores = diagnostic.get("cutScores", [])
        results = _score_diagnostic(diagnostic["items"], answers, cut_scores)

        # Update assignment
        assignment["status"] = "completed"
        assignment["completedAt"] = time.time()
        assignment["answers"] = answers
        assignment["score"] = results["scorePercent"]
        assignment["placementLevel"] = results["placementLevel"]
        assignment["skillResults"] = results["skillResults"]
        assignment["correctCount"] = results["correctCount"]
        assignment["totalItems"] = results["totalItems"]

        kv_set(f"diagnostic_assignment:{student_id}:{course_id}", assignment)

        send_json(self, {
            "success": True,
            "results": results,
        })
