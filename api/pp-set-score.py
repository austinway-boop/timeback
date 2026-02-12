"""POST /api/pp-set-score — Set score for a lesson by answering all questions correctly.

Body:
  studentId: string (required)
  lessonId: string (required) - courseComponentResource sourcedId
  score: number (required) - target score percentage (0-100)
"""

import json
import time
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json


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
        target_score = body.get("score", 100)

        if not student_id or not lesson_id:
            send_json(self, {"error": "Missing studentId or lessonId"}, 400)
            return

        headers = api_headers()
        debug = []
        
        # Step 1: Get assessment progress to find questions
        progress_url = f"{API_BASE}/powerpath/getAssessmentProgress"
        progress_payload = {"student": student_id, "lesson": lesson_id}
        
        try:
            resp = requests.post(progress_url, headers=headers, json=progress_payload, timeout=30)
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.post(progress_url, headers=headers, json=progress_payload, timeout=30)
            
            if resp.status_code != 200:
                send_json(self, {"error": f"getAssessmentProgress failed: {resp.status_code}", "body": resp.text[:500]}, 502)
                return
            
            progress = resp.json()
            debug.append({"step": "getAssessmentProgress", "status": 200})
        except Exception as e:
            send_json(self, {"error": f"getAssessmentProgress error: {str(e)}"}, 500)
            return

        questions = progress.get("questions", [])
        total_questions = len(questions)
        
        if total_questions == 0:
            send_json(self, {"error": "No questions found in lesson", "progress": progress}, 400)
            return
        
        # Calculate how many to answer correctly for target score
        correct_count = round((target_score / 100) * total_questions)
        
        # Step 2: Submit answers for each question
        answered = 0
        correct = 0
        
        for i, q in enumerate(questions):
            q_id = q.get("id", "")
            if not q_id:
                continue
            
            # Mark as correct if we haven't reached our target yet
            is_correct = (i < correct_count)
            
            answer_url = f"{API_BASE}/powerpath/updateStudentQuestionResponse"
            answer_payload = {
                "student": student_id,
                "lesson": lesson_id,
                "question": q_id,
                "answered": True,
                "correct": is_correct
            }
            
            try:
                resp = requests.post(answer_url, headers=headers, json=answer_payload, timeout=15)
                if resp.status_code in (200, 201):
                    answered += 1
                    if is_correct:
                        correct += 1
                debug.append({"step": f"question_{i+1}", "id": q_id, "correct": is_correct, "status": resp.status_code})
            except Exception as e:
                debug.append({"step": f"question_{i+1}", "error": str(e)})

        # Step 3: Finalize the lesson
        finalize_url = f"{API_BASE}/powerpath/finalStudentAssessmentResponse"
        finalize_payload = {"student": student_id, "lesson": lesson_id}
        
        try:
            resp = requests.post(finalize_url, headers=headers, json=finalize_payload, timeout=30)
            if resp.status_code in (200, 201):
                finalize_result = resp.json() if resp.text else {}
                debug.append({"step": "finalize", "status": 200, "result": finalize_result})
            else:
                debug.append({"step": "finalize", "status": resp.status_code, "body": resp.text[:300]})
        except Exception as e:
            debug.append({"step": "finalize", "error": str(e)})

        send_json(self, {
            "status": "success",
            "totalQuestions": total_questions,
            "answered": answered,
            "correct": correct,
            "targetScore": target_score,
            "expectedScore": round((correct / total_questions) * 100) if total_questions > 0 else 0,
            "debug": debug
        })
