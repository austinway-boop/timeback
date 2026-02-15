/* ====================================================================
   Diagnostic Assessment — Student Quiz UI
   ====================================================================
   Loads diagnostic items from the API, presents them one at a time
   in an AP-style UI, tracks answers, submits results, and shows
   placement/skill breakdown.
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
            showError('Not signed in. Please <a href="/login" style="color:#6C5CE7;">sign in</a> first.');
            return;
        }

        document.title = 'AlphaLearn - Diagnostic Assessment';

        await loadDiagnostic();
    });

    /* ── Load diagnostic ──────────────────────────────────────── */
    async function loadDiagnostic() {
        try {
            var url;
            if (state.isPreview) {
                // Admin preview: load full diagnostic from status endpoint
                url = '/api/diagnostic-status?courseId=' + encodeURIComponent(state.courseId);
            } else {
                // Student: load from quiz endpoint (answers stripped)
                url = '/api/diagnostic-quiz?studentId=' + encodeURIComponent(state.studentId) +
                      '&courseId=' + encodeURIComponent(state.courseId);
            }

            var resp = await fetch(url);
            var data = await resp.json();

            if (data.error) {
                showError(data.error);
                return;
            }

            // Handle already completed
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
        var el = document.getElementById('diag-content');
        var total = state.items.length;

        // Hero header
        var html = '<div class="diag-hero">' +
            '<h1><i class="fa-solid fa-stethoscope" style="margin-right:8px;opacity:0.8;"></i>Diagnostic Assessment</h1>' +
            '<p class="subtitle">' + esc(state.courseTitle) + '</p>' +
            '<div class="meta">' +
                '<span><i class="fa-solid fa-list-check" style="margin-right:4px;"></i>' + total + ' questions</span>' +
                (state.isPreview ? '<span><i class="fa-solid fa-eye" style="margin-right:4px;"></i>Admin Preview</span>' : '') +
            '</div>' +
        '</div>';

        // Progress bar
        html += '<div class="diag-progress" id="diag-progress">' +
            '<span class="count" id="progress-count">1 / ' + total + '</span>' +
            '<div class="bar"><div class="bar-fill" id="progress-fill" style="width:' + (1/total*100).toFixed(1) + '%;"></div></div>' +
            '<span class="pct" id="progress-pct">' + Math.round(1/total*100) + '%</span>' +
        '</div>';

        // Question area
        html += '<div id="question-area"></div>';

        // Navigation
        html += '<div class="q-nav" id="q-nav">' +
            '<button class="q-nav-btn" id="btn-prev" onclick="diagPrev()" disabled><i class="fa-solid fa-arrow-left"></i> Previous</button>' +
            '<button class="q-nav-btn primary" id="btn-next" onclick="diagNext()">Next <i class="fa-solid fa-arrow-right"></i></button>' +
        '</div>';

        el.innerHTML = html;
        renderQuestion();
    }

    function renderQuestion() {
        var item = state.items[state.currentIdx];
        if (!item) return;

        var total = state.items.length;
        var idx = state.currentIdx;

        // Update progress
        var countEl = document.getElementById('progress-count');
        var fillEl = document.getElementById('progress-fill');
        var pctEl = document.getElementById('progress-pct');
        if (countEl) countEl.textContent = (idx + 1) + ' / ' + total;
        if (fillEl) fillEl.style.width = ((idx + 1) / total * 100).toFixed(1) + '%';
        if (pctEl) pctEl.textContent = Math.round((idx + 1) / total * 100) + '%';

        // Build question card
        var html = '<div class="q-card">';

        // Stimulus/passage
        if (item.stimulus) {
            html += '<div class="q-stimulus">' +
                '<div class="q-stimulus-label">Read the following passage:</div>' +
                '<div>' + esc(item.stimulus) + '</div>' +
            '</div>';
        }

        // Question body
        html += '<div class="q-body">' +
            '<div class="q-number">Question ' + (idx + 1) + ' of ' + total + '</div>' +
            '<div class="q-stem">' + esc(item.stem) + '</div>';

        // Options
        var selectedOpt = state.answers[item.id] || '';
        html += '<div class="q-options">';
        var options = item.options || [];
        for (var i = 0; i < options.length; i++) {
            var o = options[i];
            var isSelected = selectedOpt === o.id;
            var optClass = 'q-option' + (isSelected ? ' selected' : '');
            html += '<div class="' + optClass + '" onclick="diagSelectOption(\'' + esc(item.id) + '\',\'' + esc(o.id) + '\')">' +
                '<div class="q-opt-letter">' + esc(o.id) + '</div>' +
                '<div class="q-opt-text">' + esc(o.text) + '</div>' +
            '</div>';
        }
        html += '</div>';
        html += '</div></div>';

        document.getElementById('question-area').innerHTML = html;

        // Update nav buttons
        var prevBtn = document.getElementById('btn-prev');
        var nextBtn = document.getElementById('btn-next');
        if (prevBtn) prevBtn.disabled = idx === 0;
        if (nextBtn) {
            if (idx === total - 1) {
                var answeredCount = Object.keys(state.answers).length;
                nextBtn.innerHTML = '<i class="fa-solid fa-flag-checkered" style="margin-right:4px;"></i>Submit (' + answeredCount + '/' + total + ')';
                nextBtn.className = 'q-nav-btn primary';
            } else {
                nextBtn.innerHTML = 'Next <i class="fa-solid fa-arrow-right"></i>';
                nextBtn.className = 'q-nav-btn primary';
            }
        }
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
            // Last question — submit
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
            // Admin preview: score locally
            scoreLocally();
            return;
        }

        // Show loading
        var area = document.getElementById('question-area');
        area.innerHTML = '<div class="diag-loading"><div class="loading-spinner"></div><p style="color:var(--color-text-muted);">Submitting and scoring your assessment...</p></div>';
        document.getElementById('q-nav').style.display = 'none';

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
                area.innerHTML = '<div style="text-align:center;padding:32px;color:#E53E3E;">' +
                    '<i class="fa-solid fa-circle-exclamation" style="font-size:2rem;display:block;margin-bottom:12px;"></i>' +
                    '<p>' + esc(data.error || 'Submission failed.') + '</p>' +
                '</div>';
            }
        } catch(e) {
            area.innerHTML = '<div style="text-align:center;padding:32px;color:#E53E3E;"><p>Network error: ' + esc(e.message) + '</p></div>';
        }
    }

    /* ── Local scoring (preview mode) ─────────────────────────── */
    function scoreLocally() {
        var total = state.items.length;
        var correct = 0;
        var skillResults = {};
        var itemResults = [];

        for (var i = 0; i < state.items.length; i++) {
            var item = state.items[i];
            var selected = state.answers[item.id] || '';
            var correctAnswer = item.correctAnswer || '';
            var isCorrect = selected === correctAnswer;
            if (isCorrect) correct++;

            var gid = item.gatewayNodeId || '';
            if (gid) {
                if (!skillResults[gid]) {
                    skillResults[gid] = { label: item.gatewayNodeLabel || gid, tested: 0, correct: 0 };
                }
                skillResults[gid].tested++;
                if (isCorrect) skillResults[gid].correct++;
            }

            itemResults.push({
                itemId: item.id,
                selected: selected,
                correctAnswer: correctAnswer,
                isCorrect: isCorrect,
            });
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
            itemResults: itemResults,
        };
        renderResults(state.results);
    }

    /* ── Render results ───────────────────────────────────────── */
    function renderResults(results) {
        var el = document.getElementById('diag-content');
        var pl = results.placementLevel || {};

        var html = '<div class="diag-hero">' +
            '<h1><i class="fa-solid fa-chart-column" style="margin-right:8px;opacity:0.8;"></i>Assessment Complete</h1>' +
            '<p class="subtitle">' + esc(state.courseTitle) + '</p>' +
        '</div>';

        html += '<div class="results-card">';
        html += '<div style="font-size:1.1rem;font-weight:700;color:#111827;">Your Results</div>';
        html += '<div class="results-score">' + results.scorePercent + '%</div>';
        html += '<div class="results-label">' + results.correctCount + ' of ' + results.totalItems + ' correct</div>';

        if (pl.name) {
            html += '<div class="results-level"><i class="fa-solid fa-award" style="margin-right:6px;"></i>Placement: ' + esc(pl.name) + '</div>';
            if (pl.description) {
                html += '<div style="font-size:0.85rem;color:var(--color-text-muted);margin-bottom:20px;">' + esc(pl.description) + '</div>';
            }
        }

        html += '<div class="results-stats">' +
            '<div class="results-stat"><div class="results-stat-value">' + results.totalItems + '</div><div class="results-stat-label">Questions</div></div>' +
            '<div class="results-stat"><div class="results-stat-value">' + results.correctCount + '</div><div class="results-stat-label">Correct</div></div>' +
            '<div class="results-stat"><div class="results-stat-value">' + (results.totalItems - results.correctCount) + '</div><div class="results-stat-label">Incorrect</div></div>' +
        '</div>';

        // Skill breakdown
        var skills = results.skillResults || {};
        var skillKeys = Object.keys(skills);
        if (skillKeys.length > 0) {
            // Sort by mastery ascending (weakest first)
            skillKeys.sort(function(a, b) { return (skills[a].mastery || 0) - (skills[b].mastery || 0); });

            html += '<div class="results-skills">' +
                '<h3><i class="fa-solid fa-chart-bar" style="margin-right:6px;color:#6C5CE7;"></i>Skill Breakdown</h3>';

            for (var i = 0; i < skillKeys.length; i++) {
                var sk = skills[skillKeys[i]];
                var mastery = sk.mastery || 0;
                var color = mastery >= 80 ? '#22C55E' : mastery >= 50 ? '#F59E0B' : '#EF4444';

                html += '<div class="skill-row">' +
                    '<div class="skill-label">' + esc(sk.label) + '</div>' +
                    '<div class="skill-bar"><div class="skill-bar-fill" style="width:' + mastery + '%;background:' + color + ';"></div></div>' +
                    '<div class="skill-pct" style="color:' + color + ';">' + mastery + '%</div>' +
                '</div>';
            }
            html += '</div>';
        }

        html += '</div>'; // close results-card

        // Action button
        html += '<div style="text-align:center;margin-top:20px;">' +
            '<a href="/dashboard" class="q-nav-btn primary" style="text-decoration:none;display:inline-flex;"><i class="fa-solid fa-home" style="margin-right:6px;"></i>Back to Dashboard</a>' +
        '</div>';

        el.innerHTML = html;

        // Scroll to top
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    /* ── Already completed view ────────────────────────────────── */
    function showAlreadyCompleted(data) {
        var el = document.getElementById('diag-content');
        el.innerHTML = '<div class="diag-hero">' +
            '<h1><i class="fa-solid fa-check-circle" style="margin-right:8px;"></i>Diagnostic Complete</h1>' +
            '<p class="subtitle">You have already completed this assessment.</p>' +
        '</div>' +
        '<div class="results-card">' +
            '<div class="results-score">' + (data.score || 0) + '%</div>' +
            '<div class="results-label">Completed ' + (data.completedAt ? new Date(data.completedAt * 1000).toLocaleDateString() : '') + '</div>' +
            (data.placementLevel ? '<div class="results-level"><i class="fa-solid fa-award" style="margin-right:6px;"></i>' + esc(data.placementLevel.name || '') + '</div>' : '') +
        '</div>' +
        '<div style="text-align:center;margin-top:20px;">' +
            '<a href="/dashboard" class="q-nav-btn primary" style="text-decoration:none;display:inline-flex;"><i class="fa-solid fa-home" style="margin-right:6px;"></i>Back to Dashboard</a>' +
        '</div>';
    }

    /* ── Error view ────────────────────────────────────────────── */
    function showError(msg) {
        var el = document.getElementById('diag-content');
        el.innerHTML = '<div style="text-align:center;padding:60px 20px;">' +
            '<i class="fa-solid fa-circle-exclamation" style="font-size:2.5rem;color:#E53E3E;display:block;margin-bottom:16px;opacity:0.6;"></i>' +
            '<p style="font-size:0.95rem;color:var(--color-text-muted);">' + msg + '</p>' +
            '<a href="/dashboard" style="margin-top:16px;display:inline-block;color:#6C5CE7;font-weight:600;font-size:0.88rem;">Back to Dashboard</a>' +
        '</div>';
    }

})();
