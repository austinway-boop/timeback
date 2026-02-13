"""POST /api/finalize-lesson — Call PowerPath finalStudentAssessmentResponse.

Returns the XP earned from PowerPath after finalization.

Body:
  studentId: string (required) - student sourcedId
  lessonId: string (required) - lesson sourcedId (e.g. "USHI23-l10-r104084-bank-v1")
  score: number (optional) - score percentage (0-100), included in finalize if provided
"""

import json
from http.server import BaseHTTPRequestHandler

import requests
from api._helpers import API_BASE, api_headers, send_json


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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
        score = body.get("score")

        if not student_id or not lesson_id:
            send_json(self, {"error": "Missing studentId or lessonId"}, 400)
            return

        headers = api_headers()
        debug = []

        # Call finalStudentAssessmentResponse
        url = f"{API_BASE}/powerpath/finalStudentAssessmentResponse"
        payload = {
            "student": student_id,
            "lesson": lesson_id
        }
        if score is not None:
            payload["score"] = score

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 401:
                headers = api_headers()
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
            
            debug.append({
                "step": "finalStudentAssessmentResponse",
                "url": url,
                "payload": payload,
                "status": resp.status_code,
                "body": resp.text[:500]
            })

            finalize_ok = resp.status_code in (200, 201)
            finalize_data = {}
            if finalize_ok:
                try:
                    finalize_data = resp.json()
                except Exception:
                    finalize_data = {}

            # Always try to get XP from progress endpoint, even if finalize
            # returned an error — the lesson may have been previously finalized
            # and the XP data is still available.
            xp_earned = 0
            multiplier = 1
            pp_score = None
            pp_accuracy = None
            try:
                progress_resp = requests.get(
                    f"{API_BASE}/powerpath/getAssessmentProgress",
                    headers=headers,
                    params={"student": student_id, "lesson": lesson_id},
                    timeout=10
                )
                if progress_resp.status_code == 200:
                    progress = progress_resp.json()
                    xp_earned = progress.get("xp", 0)
                    multiplier = progress.get("multiplier", 1)
                    pp_score = progress.get("score")
                    pp_accuracy = progress.get("accuracy")
                    debug.append({
                        "step": "getAssessmentProgress",
                        "xp": xp_earned,
                        "score": pp_score,
                        "accuracy": pp_accuracy,
                        "multiplier": multiplier
                    })
                else:
                    debug.append({
                        "step": "getAssessmentProgress",
                        "status": progress_resp.status_code,
                        "body": progress_resp.text[:300]
                    })
            except Exception as e:
                debug.append({"step": "getAssessmentProgress", "error": str(e)})

            if finalize_ok:
                send_json(self, {
                    "status": "success",
                    "finalized": finalize_data.get("finalized", True),
                    "lessonType": finalize_data.get("lessonType"),
                    "attempt": finalize_data.get("attempt"),
                    "xpEarned": xp_earned,
                    "multiplier": multiplier,
                    "powerpathScore": pp_score,
                    "powerpathAccuracy": pp_accuracy,
                    "response": finalize_data,
                    "debug": debug
                })
            else:
                # Finalize failed, but we may still have XP from progress
                send_json(self, {
                    "status": "partial" if xp_earned > 0 else "error",
                    "message": f"Finalize failed ({resp.status_code}), but XP retrieved from progress" if xp_earned > 0 else f"Finalize failed ({resp.status_code})",
                    "xpEarned": xp_earned,
                    "multiplier": multiplier,
                    "powerpathScore": pp_score,
                    "powerpathAccuracy": pp_accuracy,
                    "debug": debug
                }, 200 if xp_earned > 0 else (resp.status_code if resp.status_code < 500 else 502))

        except Exception as e:
            debug.append({"step": "finalStudentAssessmentResponse", "error": str(e)})
            send_json(self, {
                "status": "error",
                "message": str(e),
                "debug": debug
            }, 500)
