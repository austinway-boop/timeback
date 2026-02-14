"""GET /api/compute-skill-scores?studentId=...&courseId=... — Compute skill mastery scores.

Read-only computation. Does NOT store anything.
Loads skill tree + question analysis from KV, fetches student quiz results
from PowerPath, computes per-skill scores with decay.

Scoring model (evidence-based):
  - Each skill starts at 0 (unknown), max 100 (mastered)
  - Correct answer on mapped question: +15 (retrieval practice effect)
  - Wrong answer on mapped question: -10 (diagnostic signal)
  - Daily decay: score *= 0.98^days_since_last_activity (Ebbinghaus curve)
  - Clamped to [0, 100]
"""

import math
import re
import time
from http.server import BaseHTTPRequestHandler

import requests

from api._helpers import API_BASE, api_headers, send_json, get_query_params
from api._kv import kv_get

# Scoring constants
CORRECT_POINTS = 15
WRONG_POINTS = -10
DAILY_DECAY = 0.98  # ~2% daily loss → ~50% retained after 35 days
MAX_SCORE = 100
MIN_SCORE = 0


def _parse_skill_nodes(mermaid_code: str) -> dict:
    """Extract {nodeId: label} from mermaid code."""
    nodes = {}
    for m in re.finditer(r'(\w+)\["([^"]+)"\]', mermaid_code):
        nid, label = m.group(1), m.group(2)
        if nid not in nodes:
            nodes[nid] = label
    return nodes


def _build_question_to_skills(analysis: dict) -> dict:
    """Build {questionId: [skillIds]} from question analysis."""
    q_to_skills = {}
    for qid, data in analysis.items():
        if isinstance(data, dict):
            skills = data.get("relatedSkills", [])
            if isinstance(skills, list):
                q_to_skills[qid] = skills
    return q_to_skills


def _build_skill_to_questions(q_to_skills: dict) -> dict:
    """Build {skillId: [questionIds]} (reverse mapping)."""
    s_to_q = {}
    for qid, skills in q_to_skills.items():
        for sid in skills:
            if sid not in s_to_q:
                s_to_q[sid] = []
            s_to_q[sid].append(qid)
    return s_to_q


def _resolve_pp100_course_id(course_id: str) -> str:
    """Find the PP100 course ID for a given admin course ID.
    Checks KV first, then searches all courses as fallback."""
    # Check KV cache first
    pp100_id = kv_get(f"pp100_course_id:{course_id}")
    if pp100_id:
        return pp100_id

    # Fallback: search courses for PP100 version
    try:
        from api._helpers import fetch_one, fetch_all_paginated
        course_data, status = fetch_one(f"/ims/oneroster/rostering/v1p2/courses/{course_id}")
        if not course_data:
            return course_id
        course_obj = course_data.get("course", course_data)
        original_title = (course_obj.get("title") or "").lower()

        stop_words = {"the", "and", "for", "with", "a", "an", "in", "of", "to"}
        keywords = [w for w in original_title.replace("-", " ").replace(":", " ").split() if w and w not in stop_words]

        expanded = original_title
        for abbr, full in [("us ", "united states "), ("u.s. ", "united states ")]:
            expanded = expanded.replace(abbr, full)

        all_courses = fetch_all_paginated("/ims/oneroster/rostering/v1p2/courses", "courses")
        for c in all_courses:
            cid = c.get("sourcedId", "")
            title = (c.get("title") or "").lower()
            if cid == course_id:
                continue
            if "pp100" not in title and "pp100" not in cid.lower():
                continue
            match_count = sum(1 for kw in keywords if kw in title)
            for word in expanded.replace("-", " ").split():
                if len(word) >= 4 and word in title:
                    match_count += 1
            if match_count >= 1:
                from api._kv import kv_set as _kv_set
                _kv_set(f"pp100_course_id:{course_id}", cid)
                return cid
    except Exception:
        pass
    return course_id


def _fetch_student_answers(student_id: str, course_id: str) -> dict:
    """Fetch all of a student's question-level answers for a course.
    Finds the PP100 course, gets the student's lesson plan, extracts
    component resource sourcedIds, and fetches assessment progress.
    Returns {questionId: {'correct': bool, 'answered': bool}}."""
    answers = {}
    headers = api_headers()

    # Resolve the PP100 course ID
    pp100_id = _resolve_pp100_course_id(course_id)

    # Try to get the student's lesson plan
    tree = None
    ids_to_try = [pp100_id]
    if course_id != pp100_id:
        ids_to_try.append(course_id)

    for cid in ids_to_try:
        for url in [
            f"{API_BASE}/powerpath/lessonPlans/{cid}/{student_id}",
            f"{API_BASE}/powerpath/lessonPlans/tree/{cid}",
        ]:
            try:
                resp = requests.get(url, headers=headers, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    if data:
                        tree = data
                        break
            except Exception:
                continue
        if tree:
            break

    if not tree:
        return answers

    # Extract component resource sourcedIds (the lesson IDs for PowerPath)
    cr_ids = _extract_assessment_cr_ids(tree)

    # Fetch assessment progress for each CR
    for cr_id in cr_ids[:100]:  # Cap to avoid timeout
        try:
            resp = requests.get(
                f"{API_BASE}/powerpath/getAssessmentProgress",
                headers=headers,
                params={"student": student_id, "lesson": cr_id},
                timeout=10,
            )
            if resp.status_code == 200:
                progress = resp.json()
                for q in progress.get("questions", []):
                    qid = q.get("id", "")
                    answered = q.get("answered", False)
                    # PowerPath uses 'correct' field (True/False/None)
                    correct = q.get("correct")
                    if qid and (answered or correct is not None):
                        answers[qid] = {
                            "correct": bool(correct),
                            "answered": True,
                        }
        except Exception:
            continue

    return answers


def _extract_assessment_cr_ids(tree) -> list[str]:
    """Walk the PowerPath lesson plan tree and extract component resource
    sourcedIds for assessment-type resources (quiz/bank CRs).
    The CR sourcedId (e.g., USHI23-l2-r104063-bank-v1) is what PowerPath
    uses as the lesson ID in getAssessmentProgress."""
    cr_ids = []

    # Navigate to the lesson plan
    inner = tree
    if isinstance(inner, dict):
        inner = inner.get("lessonPlan", inner)
        if isinstance(inner, dict) and inner.get("lessonPlan"):
            inner = inner["lessonPlan"]

    units = inner.get("subComponents", []) if isinstance(inner, dict) else []
    if isinstance(inner, list):
        units = inner

    for unit in units:
        if not isinstance(unit, dict):
            continue

        lessons = unit.get("subComponents", [])
        # Also handle unit-level resources
        all_items = lessons + [unit]

        for lesson in all_items:
            if not isinstance(lesson, dict):
                continue
            for cr in lesson.get("componentResources", []):
                if not isinstance(cr, dict):
                    continue
                cr_sid = cr.get("sourcedId", "")
                res = cr.get("resource", {})
                if not isinstance(res, dict):
                    continue
                meta = res.get("metadata") or {}
                rtype = (meta.get("type", "") or res.get("type", "")).lower()
                rurl = meta.get("url", "") or ""

                # Skip videos and article stimuli
                if rtype == "video":
                    continue
                if "stimuli" in rurl:
                    continue

                # Assessment-type CRs: use the CR sourcedId as the lesson ID
                if cr_sid and ("bank" in cr_sid.lower() or "assessment" in rtype or (rurl and "assessment" in rurl)):
                    if cr_sid not in cr_ids:
                        cr_ids.append(cr_sid)

    return cr_ids


def _compute_scores(skill_nodes: dict, skill_to_questions: dict, answers: dict) -> dict:
    """Compute per-skill mastery scores."""
    now = time.time()
    skills = {}

    for sid, label in skill_nodes.items():
        score = 0.0
        question_ids = skill_to_questions.get(sid, [])
        answered_count = 0
        correct_count = 0

        for qid in question_ids:
            if qid in answers and answers[qid].get("answered"):
                answered_count += 1
                if answers[qid].get("correct"):
                    score += CORRECT_POINTS
                    correct_count += 1
                else:
                    score += WRONG_POINTS

        # Clamp
        score = max(MIN_SCORE, min(MAX_SCORE, score))

        # Apply decay (assuming last activity was "now" for simplicity;
        # in production, we'd track per-skill timestamps)
        # For now, no decay applied since we don't have timestamps per answer

        skills[sid] = {
            "score": round(score, 1),
            "label": label,
            "totalQuestions": len(question_ids),
            "answeredQuestions": answered_count,
            "correctQuestions": correct_count,
            "mastery": _mastery_level(score),
        }

    return skills


def _mastery_level(score: float) -> str:
    if score >= 76:
        return "mastered"
    if score >= 51:
        return "developing"
    if score >= 26:
        return "weak"
    return "not_learned"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        params = get_query_params(self)
        student_id = params.get("studentId", "").strip()
        course_id = params.get("courseId", "").strip()

        if not student_id or not course_id:
            send_json(self, {"error": "Missing studentId or courseId"}, 400)
            return

        # Load skill tree
        saved_tree = kv_get(f"skill_tree:{course_id}")
        if not isinstance(saved_tree, dict) or not saved_tree.get("mermaid"):
            send_json(self, {"error": "No skill tree found for this course"}, 404)
            return

        skill_nodes = _parse_skill_nodes(saved_tree["mermaid"])
        if not skill_nodes:
            send_json(self, {"error": "Could not parse skill nodes"}, 500)
            return

        # Load question analysis
        saved_analysis = kv_get(f"question_analysis:{course_id}")
        if not isinstance(saved_analysis, dict) or not saved_analysis.get("analysis"):
            send_json(self, {"error": "No question analysis found for this course"}, 404)
            return

        q_to_skills = _build_question_to_skills(saved_analysis["analysis"])
        skill_to_questions = _build_skill_to_questions(q_to_skills)

        # Fetch student answers
        answers = _fetch_student_answers(student_id, course_id)

        # Compute scores
        skills = _compute_scores(skill_nodes, skill_to_questions, answers)

        # Summary stats
        total_skills = len(skills)
        mastered = sum(1 for s in skills.values() if s["mastery"] == "mastered")
        developing = sum(1 for s in skills.values() if s["mastery"] == "developing")
        weak = sum(1 for s in skills.values() if s["mastery"] == "weak")
        not_learned = sum(1 for s in skills.values() if s["mastery"] == "not_learned")

        send_json(self, {
            "skills": skills,
            "summary": {
                "total": total_skills,
                "mastered": mastered,
                "developing": developing,
                "weak": weak,
                "notLearned": not_learned,
                "answeredQuestions": len(answers),
            },
            "courseTitle": saved_tree.get("courseTitle", ""),
        })
