"""POST /api/pp-complete-lesson — Complete a PowerPath lesson (MCQ/quiz).

Answers all questions correctly (or to target score) and finalizes the assessment.
Returns the actual XP earned from PowerPath.

Body:
  studentId: string (required)
  lessonId: string (required)
  targetScore: number (optional, 0-100) - if set, will answer some incorrectly to hit target
"""

import json
import re
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json


def extract_correct_answer(question):
    """Extract the correct answer from the question's QTI XML."""
    raw_xml = question.get("content", {}).get("rawXml", "")
    match = re.search(r'<qti-correct-response>\s*<qti-value>([^<]+)</qti-value>', raw_xml)
    return match.group(1) if match else "A"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl)) if cl else {}
        except Exception:
            send_json(self, {"error": "Invalid JSON body"}, 400)
            return

        student_id = body.get("studentId", "")
        lesson_id = body.get("lessonId", "")
        target_score = body.get("targetScore", 100)

        if not student_id or not lesson_id:
            send_json(self, {"error": "Missing studentId or lessonId"}, 400)
            return

        headers = api_headers()
        results = {"answered": 0, "correct": 0, "errors": []}

        # Step 1: Get questions
        try:
            resp = requests.get(
                f"{API_BASE}/powerpath/getAssessmentProgress",
                headers=headers,
                params={"student": student_id, "lesson": lesson_id},
                timeout=15
            )
            if resp.status_code != 200:
                send_json(self, {"error": f"getAssessmentProgress failed: {resp.status_code}"}, 502)
                return
            progress = resp.json()
        except Exception as e:
            send_json(self, {"error": str(e)}, 500)
            return

        questions = progress.get("questions", [])
        total = len(questions)
        
        if total == 0:
            send_json(self, {"error": "No questions found"}, 400)
            return

        # Calculate how many to get correct for target score
        num_correct = round(total * target_score / 100)
        num_correct = max(0, min(total, num_correct))

        # Step 2: Answer questions using PUT (the correct method!)
        for i, q in enumerate(questions):
            q_id = q.get("id", "")
            if not q_id:
                continue

            correct_answer = extract_correct_answer(q)
            
            # Determine if this should be correct
            if i < num_correct:
                answer = correct_answer
                is_correct = True
            else:
                # Pick wrong answer
                answer = "B" if correct_answer == "A" else "A"
                is_correct = False

            try:
                # Use PUT, not POST!
                resp = requests.put(
                    f"{API_BASE}/powerpath/updateStudentQuestionResponse",
                    headers=headers,
                    json={
                        "student": student_id,
                        "lesson": lesson_id,
                        "question": q_id,
                        "response": answer  # Send the actual answer, not correct flag
                    },
                    timeout=10
                )
                
                if resp.status_code == 200:
                    results["answered"] += 1
                    if is_correct:
                        results["correct"] += 1
                else:
                    results["errors"].append(f"Q{i+1}: {resp.status_code}")
            except Exception as e:
                results["errors"].append(f"Q{i+1}: {str(e)}")

        # Step 3: Finalize using POST
        try:
            resp = requests.post(
                f"{API_BASE}/powerpath/finalStudentAssessmentResponse",
                headers=headers,
                json={"student": student_id, "lesson": lesson_id},
                timeout=15
            )
            finalize_ok = resp.status_code == 200
            finalize_data = resp.json() if finalize_ok else {}
        except Exception as e:
            finalize_ok = False
            finalize_data = {"error": str(e)}

        # Step 4: Get final progress WITH XP
        try:
            resp = requests.get(
                f"{API_BASE}/powerpath/getAssessmentProgress",
                headers=headers,
                params={"student": student_id, "lesson": lesson_id},
                timeout=10
            )
            final_progress = resp.json() if resp.status_code == 200 else {}
        except:
            final_progress = {}

        # Extract XP from PowerPath response
        xp_earned = final_progress.get("xp", 0)
        multiplier = final_progress.get("multiplier", 1)

        send_json(self, {
            "success": finalize_ok and len(results["errors"]) == 0,
            "totalQuestions": total,
            "answered": results["answered"],
            "correct": results["correct"],
            "targetScore": target_score,
            "finalScore": final_progress.get("score"),
            "finalized": final_progress.get("finalized"),
            "attempt": final_progress.get("attempt"),
            "xpEarned": xp_earned,
            "multiplier": multiplier,
            "accuracy": final_progress.get("accuracy"),
            "errors": results["errors"] if results["errors"] else None
        })
