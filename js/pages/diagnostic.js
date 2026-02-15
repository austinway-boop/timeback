/* ====================================================================
   Diagnostic Assessment — Student Quiz UI
   ====================================================================
   Loads diagnostic items from the API, presents them one at a time
   using the standard quiz UI (quiz.css), tracks answers, submits
   results, and shows placement/skill breakdown.
   ==================================================================== */

(function() {
    'use strict';

    function esc(s) {
        if (s == null) return '';
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    var state = {
        courseId: '',
        studentId: '',
        isPreview: false,
        courseTitle: '',
        items: [],
        currentIdx: 0,
        answers: {},      // itemId -> selectedOptionId
        submitted: false,
        results: null,
    };

    /* ── Init ──────────────────────────────────────────────────── */
    document.addEventListener('DOMContentLoaded', async function() {
        var params = new URLSearchParams(window.location.search);
        state.courseId = params.get('courseId') || '';
        state.isPreview = params.get('preview') === '1';
        state.studentId = localStorage.getItem('alphalearn_userId') || localStorage.getItem('alphalearn_sourcedId') || '';

        if (!state.courseId) {
            showError('No course specified. Please navigate here from your dashboard.');
            return;
        }

        if (!state.studentId && !state.isPreview) {
            showError('Not signed in. Please <a href="/login" style="color:var(--color-primary);">sign in</a> first.');
            return;
        }

        document.title = 'AlphaLearn - Diagnostic Assessment';

        // If admin preview, update back link to go to admin page
        if (state.isPreview) {
            var backLink = document.getElementById('diag-back-link');
            if (backLink) {
                backLink.href = '/admin/assign-tests';
                backLink.innerHTML = '<i class="fa-solid fa-arrow-left"></i> Back to Assign Tests';
            }
        }

        await loadDiagnostic();
    });

    /* ── Load diagnostic ──────────────────────────────────────── */
    async function loadDiagnostic() {
        try {
            var url;
            if (state.isPreview) {
                url = '/api/diagnostic-status?courseId=' + encodeURIComponent(state.courseId);
            } else {
                url = '/api/diagnostic-quiz?studentId=' + encodeURIComponent(state.studentId) +
                      '&courseId=' + encodeURIComponent(state.courseId);
            }

            var resp = await fetch(url);
            var data = await resp.json();

            if (data.error) {
                showError(data.error);
                return;
            }

            if (data.status === 'completed') {
                showAlreadyCompleted(data);
                return;
            }

            if (state.isPreview) {
                if (data.status !== 'done' || !data.diagnostic) {
                    showError('No diagnostic found for this course.');
                    return;
                }
                state.items = data.diagnostic.items || [];
                state.courseTitle = data.diagnostic.courseTitle || 'Course';
            } else {
                state.items = data.items || [];
                state.courseTitle = data.courseTitle || 'Course';
            }

            if (!state.items.length) {
                showError('No questions found in this diagnostic.');
                return;
            }

            renderQuiz();
        } catch(e) {
            showError('Failed to load diagnostic: ' + e.message);
        }
    }

    /* ── Render quiz ──────────────────────────────────────────── */
    function renderQuiz() {
        var el = document.getElementById('quiz-area');
        var total = state.items.length;

        // Header
        var html = '<div class="quiz-header">' +
            '<div class="quiz-title">' + esc(state.courseTitle) + ' — Diagnostic</div>' +
            '<div class="quiz-score"><i class="fa-solid fa-stethoscope"></i> ' + total + ' Questions' +
                (state.isPreview ? ' <span style="opacity:0.6;font-size:0.78rem;margin-left:4px;">(Preview)</span>' : '') +
            '</div>' +
        '</div>';

        // Progress bar
        html += '<div class="quiz-status" id="quiz-status">Question 1 of ' + total + '</div>';
        html += '<div class="quiz-progress-bar"><div class="quiz-progress-fill" id="progress-fill" style="width:' + (1/total*100).toFixed(1) + '%;"></div></div>';

        // Question area
        html += '<div id="question-area"></div>';

        el.innerHTML = html;
        renderQuestion();
    }

    function renderQuestion() {
        var item = state.items[state.currentIdx];
        if (!item) return;

        var total = state.items.length;
        var idx = state.currentIdx;

        // Update progress
        var statusEl = document.getElementById('quiz-status');
        var fillEl = document.getElementById('progress-fill');
        if (statusEl) statusEl.textContent = 'Question ' + (idx + 1) + ' of ' + total;
        if (fillEl) fillEl.style.width = ((idx + 1) / total * 100).toFixed(1) + '%';

        var selectedOpt = state.answers[item.id] || '';
        var html = '';

        if (item.stimulus) {
            // Split layout: stimulus on left, question on right
            html += '<div class="quiz-split-layout">';
            html += '<div class="quiz-split-left">' + esc(item.stimulus) + '</div>';
            html += '<div class="quiz-split-right">';
            html += _buildQuestionCard(item, idx, total, selectedOpt);
            html += _buildActions(idx, total);
            html += '</div>';
            html += '</div>';
        } else {
            // Standard layout: just the question card
            html += _buildQuestionCard(item, idx, total, selectedOpt);
            html += _buildActions(idx, total);
        }

        document.getElementById('question-area').innerHTML = html;
    }

    function _buildQuestionCard(item, idx, total, selectedOpt) {
        var html = '<div class="question-card">';
        html += '<div class="question-num">Question ' + (idx + 1) + ' of ' + total + '</div>';
        html += '<div class="question-text">' + esc(item.stem) + '</div>';

        html += '<div class="choices">';
        var options = item.options || [];
        for (var i = 0; i < options.length; i++) {
            var o = options[i];
            var isSelected = selectedOpt === o.id;
            var cls = 'choice' + (isSelected ? ' selected' : '');
            html += '<div class="' + cls + '" onclick="diagSelectOption(\'' + esc(item.id) + '\',\'' + esc(o.id) + '\')">' +
                '<div class="choice-letter">' + esc(o.id) + '</div>' +
                '<div class="choice-text">' + esc(o.text) + '</div>' +
            '</div>';
        }
        html += '</div>';
        html += '</div>';
        return html;
    }

    function _buildActions(idx, total) {
        var prevDisabled = idx === 0 ? ' disabled' : '';
        var nextLabel, nextIcon;
        if (idx === total - 1) {
            var answeredCount = Object.keys(state.answers).length;
            nextLabel = 'Submit (' + answeredCount + '/' + total + ')';
            nextIcon = '<i class="fa-solid fa-flag-checkered" style="margin-right:6px;"></i>';
        } else {
            nextLabel = 'Next';
            nextIcon = '';
        }
        return '<div class="quiz-actions">' +
            '<button class="quiz-btn quiz-btn-secondary" onclick="diagPrev()"' + prevDisabled + '><i class="fa-solid fa-arrow-left" style="margin-right:4px;"></i> Previous</button>' +
            '<button class="quiz-btn quiz-btn-primary" onclick="diagNext()">' + nextIcon + nextLabel + ' <i class="fa-solid fa-arrow-right" style="margin-left:4px;"></i></button>' +
        '</div>';
    }

    /* ── User interactions (global scope for onclick) ──────────── */
    window.diagSelectOption = function(itemId, optionId) {
        if (state.submitted) return;
        state.answers[itemId] = optionId;
        renderQuestion();
    };

    window.diagPrev = function() {
        if (state.currentIdx > 0) {
            state.currentIdx--;
            renderQuestion();
        }
    };

    window.diagNext = function() {
        if (state.currentIdx < state.items.length - 1) {
            state.currentIdx++;
            renderQuestion();
        } else {
            submitDiagnostic();
        }
    };

    /* ── Submit ────────────────────────────────────────────────── */
    async function submitDiagnostic() {
        var total = state.items.length;
        var answered = Object.keys(state.answers).length;

        if (answered < total) {
            if (!confirm('You have answered ' + answered + ' of ' + total + ' questions. Submit anyway?\n\nUnanswered questions will be marked incorrect.')) {
                return;
            }
        }

        if (state.isPreview) {
            scoreLocally();
            return;
        }

        document.getElementById('question-area').innerHTML =
            '<div class="loading-msg"><div class="loading-spinner"></div>Submitting and scoring your assessment...</div>';

        try {
            var resp = await fetch('/api/diagnostic-quiz', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    studentId: state.studentId,
                    courseId: state.courseId,
                    answers: state.answers,
                }),
            });
            var data = await resp.json();

            if (data.success && data.results) {
                state.submitted = true;
                state.results = data.results;
                renderResults(data.results);
            } else {
                document.getElementById('question-area').innerHTML =
                    '<div style="text-align:center;padding:32px;color:#E53E3E;">' +
                    '<i class="fa-solid fa-circle-exclamation" style="font-size:2rem;display:block;margin-bottom:12px;"></i>' +
                    '<p>' + esc(data.error || 'Submission failed.') + '</p></div>';
            }
        } catch(e) {
            document.getElementById('question-area').innerHTML =
                '<div style="text-align:center;padding:32px;color:#E53E3E;"><p>Network error: ' + esc(e.message) + '</p></div>';
        }
    }

    /* ── Local scoring (preview mode) ─────────────────────────── */
    function scoreLocally() {
        var total = state.items.length;
        var correct = 0;
        var skillResults = {};

        for (var i = 0; i < state.items.length; i++) {
            var item = state.items[i];
            var selected = state.answers[item.id] || '';
            var correctAnswer = item.correctAnswer || '';
            var isCorrect = selected === correctAnswer;
            if (isCorrect) correct++;

            var gid = item.gatewayNodeId || item.skillNodeId || '';
            if (gid) {
                if (!skillResults[gid]) {
                    skillResults[gid] = { label: item.gatewayNodeLabel || item.skill || gid, tested: 0, correct: 0 };
                }
                skillResults[gid].tested++;
                if (isCorrect) skillResults[gid].correct++;
            }
        }

        var scorePct = total > 0 ? Math.round((correct / total) * 100 * 10) / 10 : 0;
        for (var sid in skillResults) {
            var sr = skillResults[sid];
            sr.mastery = sr.tested > 0 ? Math.round((sr.correct / sr.tested) * 100 * 10) / 10 : 0;
        }

        var placementLevel;
        if (scorePct >= 80) placementLevel = { level: 4, name: 'Advanced', description: 'Strong mastery' };
        else if (scorePct >= 60) placementLevel = { level: 3, name: 'Proficient', description: 'Good foundation' };
        else if (scorePct >= 40) placementLevel = { level: 2, name: 'Developing', description: 'Significant gaps' };
        else placementLevel = { level: 1, name: 'Foundational', description: 'Needs review' };

        state.submitted = true;
        state.results = {
            totalItems: total,
            correctCount: correct,
            scorePercent: scorePct,
            placementLevel: placementLevel,
            skillResults: skillResults,
        };
        renderResults(state.results);
    }

    /* ── Render results ───────────────────────────────────────── */
    function renderResults(results) {
        var el = document.getElementById('quiz-area');
        var pl = results.placementLevel || {};
        var backHref = state.isPreview ? '/admin/assign-tests' : '/dashboard';
        var backLabel = state.isPreview ? 'Back to Assign Tests' : 'Back to Dashboard';

        var html = '<div class="result-card">';
        html += '<div style="font-size:1.1rem;font-weight:700;color:#111827;margin-bottom:4px;">Assessment Complete</div>';
        html += '<div style="font-size:0.85rem;color:var(--color-text-muted);margin-bottom:8px;">' + esc(state.courseTitle) + '</div>';
        html += '<div class="result-score">' + results.scorePercent + '%</div>';
        html += '<div class="result-label">' + results.correctCount + ' of ' + results.totalItems + ' correct</div>';

        if (pl.name) {
            html += '<div class="xp-badge" style="margin-top:16px;margin-bottom:8px;"><i class="fa-solid fa-award" style="margin-right:6px;"></i>Placement: ' + esc(pl.name) + '</div>';
            if (pl.description) {
                html += '<div style="font-size:0.85rem;color:var(--color-text-muted);margin-bottom:16px;">' + esc(pl.description) + '</div>';
            }
        }

        html += '<div class="result-details">' +
            '<div class="result-stat"><div class="result-stat-val">' + results.totalItems + '</div><div class="result-stat-label">Questions</div></div>' +
            '<div class="result-stat"><div class="result-stat-val" style="color:#2E7D32;">' + results.correctCount + '</div><div class="result-stat-label">Correct</div></div>' +
            '<div class="result-stat"><div class="result-stat-val" style="color:#E53E3E;">' + (results.totalItems - results.correctCount) + '</div><div class="result-stat-label">Incorrect</div></div>' +
        '</div>';

        // Skill breakdown
        var skills = results.skillResults || {};
        var skillKeys = Object.keys(skills);
        if (skillKeys.length > 0) {
            skillKeys.sort(function(a, b) { return (skills[a].mastery || 0) - (skills[b].mastery || 0); });

            html += '<div style="text-align:left;margin-top:24px;border-top:1px solid var(--color-border);padding-top:20px;">' +
                '<div style="font-size:0.92rem;font-weight:700;margin-bottom:12px;"><i class="fa-solid fa-chart-bar" style="margin-right:6px;color:var(--color-primary);"></i>Skill Breakdown</div>';

            for (var i = 0; i < skillKeys.length; i++) {
                var sk = skills[skillKeys[i]];
                var mastery = sk.mastery || 0;
                var color = mastery >= 80 ? '#2E7D32' : mastery >= 50 ? '#F57F17' : '#E53E3E';

                html += '<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #f3f4f6;">' +
                    '<div style="flex:1;font-size:0.82rem;color:var(--color-text);">' + esc(sk.label) + '</div>' +
                    '<div style="width:80px;height:5px;background:#f3f4f6;border-radius:3px;overflow:hidden;"><div style="height:100%;width:' + mastery + '%;background:' + color + ';border-radius:3px;"></div></div>' +
                    '<div style="font-size:0.78rem;font-weight:700;min-width:36px;text-align:right;color:' + color + ';">' + mastery + '%</div>' +
                '</div>';
            }
            html += '</div>';
        }

        html += '</div>'; // close result-card

        html += '<div style="text-align:center;margin-top:20px;">' +
            '<a href="' + backHref + '" class="quiz-btn quiz-btn-primary" style="text-decoration:none;display:inline-flex;"><i class="fa-solid fa-arrow-left" style="margin-right:6px;"></i>' + backLabel + '</a>' +
        '</div>';

        el.innerHTML = html;
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    /* ── Already completed view ────────────────────────────────── */
    function showAlreadyCompleted(data) {
        var el = document.getElementById('quiz-area');
        var backHref = state.isPreview ? '/admin/assign-tests' : '/dashboard';
        el.innerHTML = '<div class="result-card">' +
            '<div style="font-size:1.1rem;font-weight:700;margin-bottom:8px;"><i class="fa-solid fa-check-circle" style="color:#2E7D32;margin-right:6px;"></i>Diagnostic Complete</div>' +
            '<div class="result-score">' + (data.score || 0) + '%</div>' +
            '<div class="result-label">Completed ' + (data.completedAt ? new Date(data.completedAt * 1000).toLocaleDateString() : '') + '</div>' +
            (data.placementLevel ? '<div class="xp-badge" style="margin-top:12px;"><i class="fa-solid fa-award" style="margin-right:6px;"></i>' + esc(data.placementLevel.name || '') + '</div>' : '') +
        '</div>' +
        '<div style="text-align:center;margin-top:20px;">' +
            '<a href="' + backHref + '" class="quiz-btn quiz-btn-primary" style="text-decoration:none;display:inline-flex;"><i class="fa-solid fa-arrow-left" style="margin-right:6px;"></i>Back</a>' +
        '</div>';
    }

    /* ── Error view ────────────────────────────────────────────── */
    function showError(msg) {
        var el = document.getElementById('quiz-area');
        el.innerHTML = '<div style="text-align:center;padding:60px 20px;">' +
            '<i class="fa-solid fa-circle-exclamation" style="font-size:2.5rem;color:#E53E3E;display:block;margin-bottom:16px;opacity:0.6;"></i>' +
            '<p style="font-size:0.95rem;color:var(--color-text-muted);">' + msg + '</p>' +
            '<a href="/dashboard" style="margin-top:16px;display:inline-block;color:var(--color-primary);font-weight:600;font-size:0.88rem;">Back to Dashboard</a>' +
        '</div>';
    }

})();
