    function esc(s) { if (!s) return ''; return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

    // Reuse the renderNode from the QTI parser for rich content
    function renderNode(node) {
        if (!node) return '';
        if (typeof node === 'string') return node;
        if (Array.isArray(node)) return node.map(renderNode).join('');
        var html = '';
        for (var key in node) {
            if (key.startsWith('_')) continue;
            var val = node[key];
            if (key === 'strong' || key === 'b') { html += '<strong>' + (typeof val === 'string' ? val : renderNode(val)) + '</strong>'; continue; }
            if (key === 'em' || key === 'i') { html += '<em>' + (typeof val === 'string' ? val : renderNode(val)) + '</em>'; continue; }
            if (key === 'p') { var ps = Array.isArray(val) ? val : [val]; ps.forEach(function(p) { html += '<p>' + (typeof p === 'string' ? p : (p['_'] || renderNode(p))) + '</p>'; }); continue; }
            if (key === 'img') { var ia = val['_attributes'] || val; html += '<img src="' + esc(ia.src||'') + '" alt="' + esc(ia.alt||'') + '" style="max-width:100%;border-radius:8px;">'; continue; }
            if (key === 'figure') { var figs = Array.isArray(val)?val:[val]; figs.forEach(function(f){ var im=f.img||{}; var a=im['_attributes']||im; html+='<figure style="text-align:center;margin:12px 0;"><img src="'+esc(a.src||'')+'" style="max-width:100%;border-radius:8px;">'+(f.figcaption?'<figcaption style="font-size:0.82rem;color:var(--color-text-muted);margin-top:6px;">'+esc(f.figcaption)+'</figcaption>':'')+'</figure>'; }); continue; }
            if (key === 'span') { html += typeof val === 'string' ? val : renderNode(val); continue; }
            if (key === 'div') { var ds=Array.isArray(val)?val:[val]; ds.forEach(function(d){html+=renderNode(d);}); continue; }
            // Table support
            if (key === 'table') { var ts=Array.isArray(val)?val:[val]; ts.forEach(function(t){html+='<table style="width:100%;border-collapse:collapse;margin:12px 0;font-size:0.9rem;">'+renderNode(t)+'</table>';}); continue; }
            if (key === 'thead') { html += '<thead style="background:var(--color-bg);font-weight:600;">' + renderNode(val) + '</thead>'; continue; }
            if (key === 'tbody') { html += '<tbody>' + renderNode(val) + '</tbody>'; continue; }
            if (key === 'tr') { var trs=Array.isArray(val)?val:[val]; trs.forEach(function(r){html+='<tr>'+renderNode(r)+'</tr>';}); continue; }
            if (key === 'th') { var ths=Array.isArray(val)?val:[val]; ths.forEach(function(c){html+='<th style="padding:8px 12px;border:1px solid var(--color-border);text-align:left;">'+(typeof c==='string'?c:(c['_']||renderNode(c)))+'</th>';}); continue; }
            if (key === 'td') { var tds=Array.isArray(val)?val:[val]; tds.forEach(function(c){html+='<td style="padding:8px 12px;border:1px solid var(--color-border);">'+(typeof c==='string'?c:(c['_']||renderNode(c)))+'</td>';}); continue; }
            if (key === 'caption') { html += '<caption style="font-weight:600;margin-bottom:8px;">' + (typeof val === 'string' ? val : renderNode(val)) + '</caption>'; continue; }
            // List support
            if (key === 'ul') { html += '<ul style="margin:8px 0;padding-left:20px;">' + renderNode(val) + '</ul>'; continue; }
            if (key === 'ol') { html += '<ol style="margin:8px 0;padding-left:20px;">' + renderNode(val) + '</ol>'; continue; }
            if (key === 'li') { var lis=Array.isArray(val)?val:[val]; lis.forEach(function(l){html+='<li style="margin-bottom:4px;">'+(typeof l==='string'?l:(l['_']||renderNode(l)))+'</li>';}); continue; }
            if (key === 'br') { html += '<br>'; continue; }
            if (key === 'blockquote') { html += '<blockquote style="border-left:3px solid var(--color-primary);padding:8px 16px;margin:12px 0;background:var(--color-bg);border-radius:4px;">' + (typeof val === 'string' ? val : renderNode(val)) + '</blockquote>'; continue; }
            if (typeof val === 'object' && val !== null) html += renderNode(val);
        }
        return html;
    }

    var quizState = {
        attemptId: null,
        questionNum: 0,
        correct: 0,
        total: 0,
        xpEarned: 0,
        ppScore: 0, // PowerPath 100 score (0-100)
        streak: 0, // consecutive correct answers
        currentQuestion: null,
        selectedChoice: null,
        answered: false,
        testId: '',
        title: '',
        isReadingQuiz: false, // true when quiz has article/stimulus content
        accumulatedStimuli: [], // all article parts shown so far
        totalQuestions: 0, // fixed question count for reading quizzes
        // Crossout tool
        crossOutMode: false,
        crossedOut: {},
        // Question reporting
        reportingEnabled: true, // default ON; API can disable
        // Track answered question IDs locally (survives reload even if server state is stale)
        answeredIds: [],
    };
    var _aiExplanations = null; // AI-generated wrong-answer explanations (prefetched)

    // ── Stage-based PowerPath scoring ──
    function _getQuestionDifficulty(q) {
        if (!q) return 'medium';
        var d = q.difficulty || (q.metadata && q.metadata.difficulty) || '';
        if (d) {
            d = String(d).toLowerCase();
            if (d === 'easy' || d === 'low') return 'easy';
            if (d === 'hard' || d === 'high') return 'hard';
            return 'medium';
        }
        var bloom = q.bloomsTaxonomyLevel || (q.metadata && q.metadata.bloomsTaxonomyLevel) || 0;
        if (bloom) {
            bloom = parseInt(bloom, 10);
            if (bloom <= 2) return 'easy';
            if (bloom >= 5) return 'hard';
            return 'medium';
        }
        return 'medium';
    }

    function _ppScoreChange(ppScore, difficulty, isCorrect) {
        var table;
        if (ppScore <= 50) {
            // Stage 1: Exploration (0-50%) — testing effect, safe to fail
            table = { easy: [3, -1], medium: [6, -1], hard: [9, -1] };
        } else if (ppScore <= 80) {
            // Stage 2: Building (51-80%) — productive struggle
            table = { easy: [2, -3], medium: [5, -2], hard: [8, -1] };
        } else if (ppScore <= 95) {
            // Stage 3: Proficiency (81-95%) — desirable difficulties
            table = { easy: [1, -3], medium: [3, -2], hard: [5, -2] };
        } else {
            // Stage 4: Mastery Gate (96-100%) — statistical confidence
            table = { easy: [1, -4], medium: [1, -3], hard: [3, -2] };
        }
        var row = table[difficulty] || table.medium;
        return isCorrect ? row[0] : row[1];
    }

    // ── Progress persistence (save/restore across sessions) ──
    function _getProgressKey() {
        var userId = localStorage.getItem('alphalearn_userId') || localStorage.getItem('alphalearn_sourcedId') || '';
        var params = new URLSearchParams(window.location.search);
        var lessonId = params.get('lessonId') || params.get('id') || params.get('testId') || '';
        if (!userId || !lessonId) return '';
        return 'quiz_progress:' + userId + ':' + lessonId;
    }

    function _saveProgress() {
        var key = _getProgressKey();
        if (!key) return;
        try {
            localStorage.setItem(key, JSON.stringify({
                ppScore: quizState.ppScore,
                correct: quizState.correct,
                total: quizState.total,
                streak: quizState.streak,
                xpEarned: quizState.xpEarned,
                questionNum: quizState.questionNum,
                attemptId: quizState.attemptId,
                answeredIds: quizState.answeredIds,
                timestamp: Date.now(),
            }));
        } catch(e) {}
    }

    function _restoreProgress() {
        var key = _getProgressKey();
        if (!key) return false;
        try {
            var saved = JSON.parse(localStorage.getItem(key));
            if (!saved || !saved.timestamp) return false;
            // Expire after 7 days
            if (Date.now() - saved.timestamp > 7 * 24 * 60 * 60 * 1000) {
                localStorage.removeItem(key);
                return false;
            }
            quizState.ppScore = saved.ppScore || 0;
            quizState.correct = saved.correct || 0;
            quizState.total = saved.total || 0;
            quizState.streak = saved.streak || 0;
            quizState.xpEarned = saved.xpEarned || 0;
            quizState.questionNum = saved.questionNum || 0;
            quizState.answeredIds = saved.answeredIds || [];
            return true;
        } catch(e) { return false; }
    }

    function _clearProgress() {
        var key = _getProgressKey();
        if (key) localStorage.removeItem(key);
    }

    function _retryQuiz() {
        _clearProgress();
        var url = new URL(window.location.href);
        url.searchParams.set('retry', 'true');
        window.location.href = url.toString();
    }

    // Save progress automatically when leaving or hiding the page
    window.addEventListener('beforeunload', function() {
        if (quizState.total > 0) _saveProgress();
    });
    document.addEventListener('visibilitychange', function() {
        if (document.hidden && quizState.total > 0) _saveProgress();
    });

    var area = document.getElementById('quiz-area');

    // ── Question Reporting: init ──
    (function initReporting() {
        var userId = localStorage.getItem('alphalearn_userId') || localStorage.getItem('alphalearn_sourcedId') || '';
        if (!userId) return;
        // Check if reporting is disabled by admin (default is ON)
        fetch('/api/report-question?studentId=' + encodeURIComponent(userId))
            .then(function(r) { return r.json(); })
            .then(function(d) { if (d.enabled === false) quizState.reportingEnabled = false; })
            .catch(function() { /* keep enabled on error */ });
    })();


    // Mark quiz complete — saves ALL possible keys so course.html can detect it
    function _markQuizComplete() {
        var p = new URLSearchParams(window.location.search);
        var ids = [p.get('lessonId')||'', p.get('id')||'', p.get('testId')||'', p.get('title')||''];
        for (var i = 0; i < ids.length; i++) {
            if (ids[i]) localStorage.setItem('completed_' + ids[i], 'true');
        }
        // Signal course.html to refresh progress when we navigate back
        sessionStorage.setItem('al_progress_changed', 'true');
    }

    document.addEventListener('DOMContentLoaded', async function() {
        var params = new URLSearchParams(window.location.search);
        var testId = params.get('id') || params.get('testId') || '';
        var qtiUrl = params.get('url') || '';
        var subject = params.get('subject') || '';
        var gradeLevel = params.get('grade') || params.get('gradeLevel') || '';
        var lessonId = params.get('lessonId') || '';
        var courseCode = params.get('courseCode') || '';
        var contentType = (params.get('type') || '').toLowerCase();
        quizState.title = params.get('title') || 'Quiz';
        quizState.testId = testId;

        var userId = localStorage.getItem('alphalearn_userId') || localStorage.getItem('alphalearn_sourcedId') || '';

        // Prefetch AI explanations if enabled for this course
        try {
            var _ld = JSON.parse(sessionStorage.getItem('al_lesson_data') || '{}');
            var _cid = _ld.courseSourcedId || '';
            if (_cid) {
                fetch('/api/get-explanations?courseId=' + encodeURIComponent(_cid))
                    .then(function(r) { return r.json(); })
                    .then(function(d) { if (d.enabled) _aiExplanations = d.explanations || null; })
                    .catch(function() {});
            }
        } catch(e) {}

        // ── Detect retry flag ──
        var isRetry = params.get('retry') === 'true';
        if (isRetry) {
            var cleanUrl = new URL(window.location.href);
            cleanUrl.searchParams.delete('retry');
            history.replaceState(null, '', cleanUrl.toString());
            _clearProgress();
        }

        // ── Restore progress from previous session BEFORE any API calls ──
        if (!isRetry) {
            _restoreProgress();
        }

        // ── Detect reading/stimulus content (not a quiz) ──
        var isReading = contentType === 'stimulus' || contentType === 'stimuli'
            || contentType === 'reading' || contentType === 'article';

        // ── 0. Reading/Article path — fetch and display content, no quiz ──
        if (isReading && (qtiUrl || testId)) {
            area.innerHTML = '<div class="loading-msg"><div class="loading-spinner"></div>Loading article...</div>';
            var loaded = await loadReadingContent(qtiUrl, testId, contentType);
            if (loaded) return;
            // If reading fetch failed, fall through to try other methods
        }

        // ── 1. PowerPath adaptive flow (assessments only) ──
        if (!isReading && userId && (testId || lessonId)) {
            try {
                area.innerHTML = '<div class="loading-msg"><div class="loading-spinner"></div>Starting assessment...</div>';
                var startResp = await fetch('/api/quiz-session?action=start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ studentId: userId, testId: testId, lessonId: lessonId, subject: subject, grade: gradeLevel, retry: isRetry }),
                });
                var startData = await startResp.json();

                if (startData.attemptId || startData.id) {
                    quizState.attemptId = startData.attemptId || startData.id;
                    // Progress already restored above; use server hints as fallback
                    if (quizState.total === 0 && startData.hasExistingProgress) {
                        quizState.questionNum = startData.answeredCount || 0;
                        if (startData.score != null) quizState.ppScore = Math.max(0, Math.min(100, startData.score));
                    }
                    await loadNextQuestion();
                    return;
                }
                if (startData.useLocalAssessment) {
                    // Fall through to local FRQ below
                }
            } catch(e) {
                console.warn('Assessment start failed:', e.message);
            }
        }

        // ── 2. QTI content fetch (direct URL or search catalog by ID/subject) ──
        if (qtiUrl || testId) {
            var loaded = await loadAllQuestions(qtiUrl, testId, subject, gradeLevel, contentType);
            if (loaded) return;
        }

        // ── 4. Local FRQ fallback ──
        if (testId || subject) {
            showLocalAssessment(quizState.title, subject, gradeLevel);
            return;
        }

        area.innerHTML = '<div class="loading-msg">No quiz ID provided.</div>';
    });

    // ── PowerPath adaptive: load one question at a time ──
    async function loadNextQuestion() {
        if (!quizState.attemptId) return;
        area.innerHTML = '<div class="loading-msg"><div class="loading-spinner"></div>Loading question...</div>';

        try {
            var skipParam = quizState.answeredIds.length > 0 ? '&skipIds=' + encodeURIComponent(quizState.answeredIds.join(',')) : '';
            var resp = await fetch('/api/quiz-session?action=next&attemptId=' + encodeURIComponent(quizState.attemptId) + skipParam);
            var data = await resp.json();

            if (data.complete || data.finished || data.error === 'no_more_questions') {
                showResults();
                return;
            }

            quizState.currentQuestion = data;
            quizState.questionNum++;
            quizState.selectedChoice = null;
            quizState.answered = false;
            renderQuestion(data);
        } catch(e) {
            area.innerHTML = '<div class="loading-msg">Error loading question: ' + esc(e.message) + '</div>';
        }
    }

    // Fisher-Yates shuffle (returns a new shuffled copy)
    function _shuffleChoices(arr) {
        var a = arr.slice();
        for (var i = a.length - 1; i > 0; i--) {
            var j = Math.floor(Math.random() * (i + 1));
            var tmp = a[i]; a[i] = a[j]; a[j] = tmp;
        }
        return a;
    }

    function renderQuestion(q) {
        var prompt = q.prompt || q.question || q.text || q.body || '';
        if (typeof prompt === 'object') prompt = renderNode(prompt);
        var choices = _shuffleChoices(q.choices || q.options || q.answers || []);
        var stimulus = q.stimulus || q.passage || q.reading || '';
        if (typeof stimulus === 'object') stimulus = renderNode(stimulus);
        var isFRQ = q.isFRQ || false;
        var expectedLines = q.expectedLines || 10;

        // Accumulate stimuli for reading quizzes
        if (quizState.isReadingQuiz && stimulus && stimulus.length > 10) {
            var isDup = quizState.accumulatedStimuli.some(function(s) { return s === stimulus; });
            if (!isDup) {
                quizState.accumulatedStimuli.push(stimulus);
            }
        }

        var html = '';

        if (quizState.isReadingQuiz) {
            // Simple progress bar for reading quizzes (no PowerPath score)
            var progressPct = quizState.totalQuestions > 0 ? Math.round((quizState.questionNum / quizState.totalQuestions) * 100) : 0;
            html += '<div class="quiz-header"><div class="quiz-title">' + esc(quizState.title) + '</div>' +
                '<div class="quiz-score"><i class="fa-solid fa-book-open"></i> Question ' + quizState.questionNum + ' of ' + quizState.totalQuestions + '</div></div>';
            html += '<div class="quiz-progress-bar"><div class="quiz-progress-fill" style="width:' + progressPct + '%"></div></div>';
        } else {
            var accuracy = quizState.total > 0 ? Math.round((quizState.correct / quizState.total) * 100) : 0;
            var ppScore = Math.max(0, Math.min(100, quizState.ppScore));
            var circumference = 2 * Math.PI * 28;
            var dashOffset = circumference - (ppScore / 100) * circumference;

            html += '<div class="quiz-header"><div class="quiz-title">' + esc(quizState.title) + '</div></div>' +
            '<div class="pp-scoreboard">' +
                '<div class="pp-ring">' +
                    '<svg width="64" height="64" viewBox="0 0 64 64">' +
                        '<circle class="pp-ring-bg" cx="32" cy="32" r="28"/>' +
                        '<circle class="pp-ring-fill" cx="32" cy="32" r="28" stroke-dasharray="' + circumference.toFixed(1) + '" stroke-dashoffset="' + dashOffset.toFixed(1) + '"/>' +
                    '</svg>' +
                    '<div class="pp-ring-text">' + ppScore + '</div>' +
                '</div>' +
                '<div><div class="pp-label">PowerPath 100</div><div class="pp-score-text">' + ppScore + ' / 100</div></div>' +
                '<div class="pp-stat"><div class="pp-stat-label">Questions</div><div class="pp-stat-value">' + quizState.total + '</div></div>' +
                '<div class="pp-stat"><div class="pp-stat-label">Accuracy</div><div class="pp-stat-value">' + accuracy + '%</div></div>' +
            '</div>';
        }

        var hasStimulus = (quizState.isReadingQuiz && quizState.accumulatedStimuli.length > 0) || (stimulus && stimulus.length > 10);

        // Extract images from prompt for side-by-side layout (like articles)
        var promptImages = '';
        if (!hasStimulus && prompt && typeof prompt === 'string') {
            var imgMatches = prompt.match(/<figure[\s\S]*?<\/figure>|<img\s[^>]*>/gi);
            if (imgMatches && imgMatches.length > 0) {
                promptImages = imgMatches.join('');
                var cleanedPrompt = prompt;
                for (var mi = 0; mi < imgMatches.length; mi++) {
                    cleanedPrompt = cleanedPrompt.replace(imgMatches[mi], '');
                }
                cleanedPrompt = cleanedPrompt.replace(/<p>\s*<\/p>/gi, '').trim();
                prompt = cleanedPrompt;
            }
        }

        // Toggle wide mode based on stimulus or images
        var quizWrap = document.querySelector('.quiz-wrap');
        if (quizWrap) {
            if (hasStimulus || promptImages) quizWrap.classList.add('wide-mode');
            else quizWrap.classList.remove('wide-mode');
        }

        // Build question + choices HTML
        var questionHtml = '<div class="question-card">';
        var coToggleHtml = (!isFRQ && choices.length > 0) ? '<div class="crossout-toggle' + (quizState.crossOutMode ? ' active' : '') + '" onclick="toggleCrossOut()" title="Eliminate answers">ABC' + (quizState.crossOutMode ? '<div class="strike-line"></div>' : '') + '</div>' : '';
        var reportFlagHtml = quizState.reportingEnabled ? '<button class="report-flag" onclick="openReportModal()" title="Report this question"><i class="fa-solid fa-flag"></i></button>' : '';
        questionHtml += '<div class="q-tools-row"><div class="question-num">Question ' + quizState.questionNum + (isFRQ ? ' — Free Response' : '') + '</div>' + reportFlagHtml + coToggleHtml + '</div>';
        questionHtml += '<div class="question-text">' + (prompt || 'Loading question...') + '</div>';

        if (isFRQ) {
            questionHtml += '<textarea id="frq-response" rows="' + expectedLines + '" placeholder="Type your response here..." ' +
                'style="width:100%;padding:14px;border:2px solid var(--color-border);border-radius:10px;font-size:0.95rem;font-family:inherit;line-height:1.7;resize:vertical;outline:none;transition:border-color 0.15s;box-sizing:border-box;" ' +
                'onfocus="this.style.borderColor=\'var(--color-primary)\'" onblur="this.style.borderColor=\'var(--color-border)\'" ' +
                'oninput="document.getElementById(\'submit-btn\').disabled=!this.value.trim()"></textarea>' +
                '<div style="text-align:right;font-size:0.75rem;color:var(--color-text-muted);margin-top:4px;">Write a complete response. Be specific and use evidence.</div>';
        } else if (choices.length > 0) {
            var letters = 'ABCDEFGHIJ';
            var co = quizState.crossedOut[quizState.questionNum] || {};
            questionHtml += '<div class="choices' + (quizState.crossOutMode ? ' crossout-mode' : '') + '" id="choices">';
            for (var i = 0; i < choices.length; i++) {
                var c = choices[i];
                var cText = c.text || c.label || c.value || c.content || (typeof c === 'string' ? c : '');
                if (typeof cText === 'object') cText = renderNode(cText);
                var cId = c.id || c.identifier || letters[i] || String(i);
                var crossedCls = co[cId] ? ' crossed-out' : '';
                questionHtml += '<div class="choice' + crossedCls + '" data-id="' + esc(cId) + '" onclick="selectAnswer(this, \'' + esc(cId) + '\')">' +
                    '<div class="choice-letter">' + (letters[i] || i) + '</div>' +
                    '<div class="choice-text">' + (cText || 'Option ' + (letters[i]||i)) + '</div>' +
                    '<button class="crossout-btn" onclick="event.stopPropagation();crossOutChoice(this.parentElement,\'' + esc(cId) + '\')" title="Cross out"><i class="fa-solid fa-xmark"></i></button>' +
                '</div>';
            }
            questionHtml += '</div>';
        }

        questionHtml += '<div class="feedback" id="feedback"></div>';
        questionHtml += '</div>';
        questionHtml += '<div class="quiz-actions"><button class="quiz-btn quiz-btn-primary" id="submit-btn" onclick="submitAnswer()" disabled><i class="fa-solid fa-check"></i> Submit Answer</button></div>';

        if (hasStimulus) {
            // Build stimulus content
            var stimContent = '';
            if (quizState.isReadingQuiz && quizState.accumulatedStimuli.length > 0) {
                for (var si = 0; si < quizState.accumulatedStimuli.length; si++) {
                    if (si > 0) stimContent += '<hr style="border:none;border-top:2px dashed #E8ECF1;margin:20px 0;">';
                    stimContent += quizState.accumulatedStimuli[si];
                }
            } else {
                stimContent = stimulus;
            }
            // Split layout: passage left, question right
            html += '<div class="quiz-split-layout">';
            html += '<div class="quiz-split-left">' + stimContent + '</div>';
            html += '<div class="quiz-split-right">' + questionHtml + '</div>';
            html += '</div>';
        } else if (promptImages) {
            // Image split layout — image left, question right (like articles)
            html += '<div class="quiz-split-layout">';
            html += '<div class="quiz-split-left" style="display:flex;align-items:center;justify-content:center;">' + promptImages + '</div>';
            html += '<div class="quiz-split-right">' + questionHtml + '</div>';
            html += '</div>';
        } else {
            // Stacked layout (no stimulus)
            if (stimulus) {
                html += '<div class="stimulus-box">' + stimulus + '</div>';
            }
            html += questionHtml;
        }

        area.innerHTML = html;
    }

    function selectAnswer(el, choiceId) {
        if (quizState.answered) return;
        // In crossout mode, clicking toggles crossout instead of selecting
        if (quizState.crossOutMode) {
            crossOutChoice(el, choiceId);
            return;
        }
        // Don't select crossed-out choices
        if (el.classList.contains('crossed-out')) return;
        quizState.selectedChoice = choiceId;
        document.querySelectorAll('.choice').forEach(function(c) { c.classList.remove('selected'); });
        el.classList.add('selected');
        document.getElementById('submit-btn').disabled = false;
    }

    function toggleCrossOut() {
        quizState.crossOutMode = !quizState.crossOutMode;
        var choicesEl = document.getElementById('choices');
        if (choicesEl) choicesEl.classList.toggle('crossout-mode', quizState.crossOutMode);
        var toggle = document.querySelector('.crossout-toggle');
        if (toggle) {
            toggle.classList.toggle('active', quizState.crossOutMode);
            toggle.innerHTML = 'ABC' + (quizState.crossOutMode ? '<div class="strike-line"></div>' : '');
        }
    }

    function crossOutChoice(el, choiceId) {
        if (quizState.answered) return;
        var qNum = quizState.questionNum;
        if (!quizState.crossedOut[qNum]) quizState.crossedOut[qNum] = {};
        if (quizState.crossedOut[qNum][choiceId]) {
            delete quizState.crossedOut[qNum][choiceId];
            el.classList.remove('crossed-out');
        } else {
            quizState.crossedOut[qNum][choiceId] = true;
            el.classList.add('crossed-out');
            // If this choice was selected, deselect it
            if (quizState.selectedChoice === choiceId) {
                quizState.selectedChoice = null;
                el.classList.remove('selected');
                document.getElementById('submit-btn').disabled = true;
            }
        }
    }

    async function submitAnswer() {
        // Handle FRQ: read from textarea
        var frqEl = document.getElementById('frq-response');
        if (frqEl && !quizState.selectedChoice) {
            quizState.selectedChoice = frqEl.value.trim();
        }
        if (!quizState.selectedChoice || quizState.answered) return;
        quizState.answered = true;
        quizState.total++;

        // Track this question as answered locally (survives reload)
        var answeredQId = String((quizState.currentQuestion && (quizState.currentQuestion.id || quizState.currentQuestion.questionId)) || '');
        if (answeredQId && quizState.answeredIds.indexOf(answeredQId) === -1) {
            quizState.answeredIds.push(answeredQId);
        }

        var btn = document.getElementById('submit-btn');
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Checking...';

        // Submit to PowerPath if we have an attempt
        var isCorrect = false;
        var feedback = '';
        if (quizState.attemptId) {
            try {
                var resp = await fetch('/api/quiz-session?action=respond', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        attemptId: quizState.attemptId,
                        questionId: quizState.currentQuestion.id || quizState.currentQuestion.questionId || '',
                        response: quizState.selectedChoice,
                    }),
                });
                var data = await resp.json();
                isCorrect = (data.responseResult && data.responseResult.isCorrect) || data.correct || data.isCorrect || false;
                feedback = (data.responseResult && data.responseResult.feedback) || data.feedback || data.explanation || '';
                if (data.xpEarned || data.xp) quizState.xpEarned += (data.xpEarned || data.xp);
            } catch(e) {}
        }

        // Override with AI explanation if available for this wrong choice
        if (!isCorrect && _aiExplanations) {
            var _aiQid = quizState.currentQuestion ? (quizState.currentQuestion.id || quizState.currentQuestion.questionId || '') : '';
            if (_aiQid && _aiExplanations[_aiQid] && _aiExplanations[_aiQid][quizState.selectedChoice]) {
                feedback = _aiExplanations[_aiQid][quizState.selectedChoice];
            }
        }

        var pointsChange = 0;
        var difficulty = _getQuestionDifficulty(quizState.currentQuestion);
        if (isCorrect) {
            quizState.correct++;
            pointsChange = _ppScoreChange(quizState.ppScore, difficulty, true);
            quizState.ppScore = Math.min(100, quizState.ppScore + pointsChange);
            quizState.xpEarned += 1;
        } else {
            pointsChange = _ppScoreChange(quizState.ppScore, difficulty, false);
            quizState.ppScore = Math.max(0, quizState.ppScore + pointsChange);
        }

        // Use real PowerPath score from API if available (overrides synthetic calculation)
        if (typeof data.powerpathScore === 'number') {
            quizState.ppScore = data.powerpathScore;
        }

        // Persist progress to localStorage
        _saveProgress();

        // Show feedback with points and difficulty
        var feedbackEl = document.getElementById('feedback');
        if (feedbackEl) {
            feedbackEl.className = 'feedback ' + (isCorrect ? 'correct' : 'incorrect');
            var diffLabel = difficulty === 'easy' ? 'Easy' : difficulty === 'hard' ? 'Hard' : 'Medium';
            feedbackEl.innerHTML = (isCorrect ? '<strong><i class="fa-solid fa-check-circle"></i> Correct! +' + pointsChange + '</strong> <span style="font-size:0.82rem;">' + diffLabel + '</span>' : '<strong><i class="fa-solid fa-times-circle"></i> Incorrect ' + pointsChange + '</strong> <span style="font-size:0.82rem;">' + diffLabel + '</span>') +
                (feedback ? '<p style="margin-top:8px;">' + feedback + '</p>' : '');
        }

        // Highlight choices
        document.querySelectorAll('.choice').forEach(function(c) {
            if (c.dataset.id === quizState.selectedChoice) c.classList.add(isCorrect ? 'correct' : 'incorrect');
        });

        // Update PowerPath scoreboard
        updateScoreboard();

        // Check if score reached 100 (not for reading quizzes)
        if (!quizState.isReadingQuiz && quizState.ppScore >= 100) {
            btn.innerHTML = '<i class="fa-solid fa-trophy"></i> PowerPath 100 Complete!';
            btn.disabled = false;
            btn.onclick = function() { showResults(); };
        } else {
            btn.innerHTML = '<i class="fa-solid fa-arrow-right"></i> Next Question';
            btn.disabled = false;
            btn.onclick = function() { loadNextQuestion(); };
        }

        // (AI review now triggers immediately on report submission)
    }

    function updateScoreboard() {
        var ppScore = Math.max(0, Math.min(100, quizState.ppScore));
        var accuracy = quizState.total > 0 ? Math.round((quizState.correct / quizState.total) * 100) : 0;
        var circumference = 2 * Math.PI * 28;
        var dashOffset = circumference - (ppScore / 100) * circumference;
        var sb = document.querySelector('.pp-scoreboard');
        if (sb) {
            sb.querySelector('.pp-ring-fill').setAttribute('stroke-dashoffset', dashOffset.toFixed(1));
            sb.querySelector('.pp-ring-text').textContent = ppScore;
            sb.querySelectorAll('.pp-stat-value')[0].textContent = quizState.total;
            sb.querySelectorAll('.pp-stat-value')[1].textContent = accuracy + '%';
            sb.querySelector('.pp-score-text').textContent = ppScore + ' / 100';
        }
    }

    function showResults() {
        // Collapse wide mode for results
        var quizWrap = document.querySelector('.quiz-wrap');
        if (quizWrap) quizWrap.classList.remove('wide-mode');

        // Clear saved progress — quiz is complete
        _clearProgress();

        var pct = quizState.total > 0 ? Math.round((quizState.correct / quizState.total) * 100) : 0;
        // Completion-based: finishing the quiz = passed. Accuracy does not gate progression.
        var passed = true;
        // XP requires 80%+ accuracy
        var noXp = pct < 80;
        if (noXp) quizState.xpEarned = 0;

        area.innerHTML = '<div class="result-card">' +
            '<div style="font-size:3rem;margin-bottom:8px;">🎉</div>' +
            '<div class="result-score">' + pct + '%</div>' +
            '<div class="result-label">Quiz Complete!</div>' +
            '<div class="xp-badge"><i class="fa-solid fa-bolt"></i> ' + quizState.xpEarned + ' XP earned' + (noXp ? ' (need 80%+ for XP)' : '') + '</div>' +
            '<div class="result-details">' +
                '<div class="result-stat"><div class="result-stat-val" style="color:#2E7D32;">' + quizState.correct + '</div><div class="result-stat-label">Correct</div></div>' +
                '<div class="result-stat"><div class="result-stat-val">' + (quizState.total - quizState.correct) + '</div><div class="result-stat-label">Incorrect</div></div>' +
                '<div class="result-stat"><div class="result-stat-val">' + quizState.total + '</div><div class="result-stat-label">Questions</div></div>' +
                '<div class="result-stat"><div class="result-stat-val" style="color:#2E7D32;">' + pct + '%</div><div class="result-stat-label">Accuracy</div></div>' +
            '</div>' +
            '<div style="margin-top:16px;padding:12px 20px;background:#E8F5E9;border-radius:10px;color:#1B5E20;font-size:0.9rem;"><i class="fa-solid fa-check-circle" style="margin-right:6px;"></i>This lesson is now marked as complete. You can proceed to the next lesson.</div>' +
            '<div style="margin-top:24px;display:flex;gap:12px;justify-content:center;">' +
                '<button class="quiz-btn quiz-btn-primary" onclick="history.back()"><i class="fa-solid fa-arrow-right"></i> Continue to Next Lesson</button>' +
                '<button class="quiz-btn quiz-btn-secondary" onclick="history.back()"><i class="fa-solid fa-arrow-left"></i> Back to Course (Progress Saved)</button>' +
            '</div>' +
        '</div>';

        // Finalize the attempt
        if (quizState.attemptId) {
            fetch('/api/quiz-session?action=finalize', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({attemptId: quizState.attemptId}),
            }).catch(function(){});
        }

        if (passed) { _markQuizComplete(); }
    }

    // ── Reading/Article display — fetch content and render as readable article ──
    async function loadReadingContent(qtiUrl, testId, contentType) {
        try {
            var apiUrl = '/api/qti-item?';
            if (qtiUrl) apiUrl += 'url=' + encodeURIComponent(qtiUrl);
            else apiUrl += 'id=' + encodeURIComponent(testId) + '&type=' + encodeURIComponent(contentType || 'stimulus');
            var resp = await fetch(apiUrl);
            var result = await resp.json();

            if (!result.success || !result.data) return false;
            var data = result.data;
            var title = data.title || quizState.title || 'Reading';

            // Extract article content from various response shapes
            var articleHtml = '';

            // 1. QTI stimulus body
            var stim = data['qti-assessment-stimulus'];
            if (stim) {
                articleHtml = renderNode(stim['qti-stimulus-body'] || stim);
            }

            // 2. Direct body/html/content string
            if (!articleHtml) {
                var body = data.body || data.html || data.content;
                if (typeof body === 'string' && body.length > 20) {
                    articleHtml = body;
                }
            }

            // 3. Render the whole data object as rich content
            if (!articleHtml) {
                articleHtml = renderNode(data);
            }

            if (!articleHtml || articleHtml.length < 10) return false;

            // Build a clean reading layout
            area.innerHTML =
                '<div class="quiz-header"><div class="quiz-title">' + esc(title) + '</div></div>' +
                '<div style="padding:10px 16px;background:#EBF8FF;border:1px solid #BEE3F8;border-radius:10px;margin-bottom:20px;font-size:0.88rem;color:#2B6CB0;">' +
                    '<i class="fa-solid fa-book-open" style="margin-right:8px;"></i>' +
                    '<strong>Reading</strong> — Read the article below, then mark it complete.' +
                '</div>' +
                '<div class="stimulus-box" style="max-height:none;background:#fff;border:1px solid var(--color-border);padding:28px;line-height:1.8;font-size:1rem;">' +
                    articleHtml +
                '</div>' +
                '<div class="quiz-actions" style="margin-top:20px;">' +
                    '<button class="quiz-btn quiz-btn-primary" onclick="_markQuizComplete(); this.innerHTML=\'<i class=\\\'fa-solid fa-check\\\'></i> Marked Complete\'; this.disabled=true; this.style.background=\'#2E7D32\';">' +
                        '<i class="fa-solid fa-check"></i> Mark as Read</button>' +
                    '<button class="quiz-btn quiz-btn-secondary" onclick="history.back()"><i class="fa-solid fa-arrow-left"></i> Back to Course (Progress Saved)</button>' +
                '</div>';
            return true;
        } catch(e) {
            console.warn('Reading content fetch failed:', e);
            return false;
        }
    }

    // ── Fallback: load all questions at once from QTI (when PowerPath adaptive fails) ──
    // Returns true if content was loaded, false if not
    async function loadAllQuestions(qtiUrl, testId, subject, gradeLevel, contentType) {
        area.innerHTML = '<div class="loading-msg"><div class="loading-spinner"></div>Loading quiz...</div>';
        try {
            var apiUrl = '/api/qti-item?';
            if (qtiUrl) apiUrl += 'url=' + encodeURIComponent(qtiUrl);
            else apiUrl += 'id=' + encodeURIComponent(testId) + '&type=' + encodeURIComponent(contentType || 'assessment');
            // Pass subject/title/grade for QTI catalog search when ID isn't a direct QTI ID
            if (subject) apiUrl += '&subject=' + encodeURIComponent(subject);
            if (gradeLevel) apiUrl += '&grade=' + encodeURIComponent(gradeLevel);
            var quizTitle = quizState.title || '';
            if (quizTitle) apiUrl += '&title=' + encodeURIComponent(quizTitle);
            var resp = await fetch(apiUrl);
            var result = await resp.json();
            if (!result.success || !result.data) {
                return false; // Signal caller to try next fallback
            }
            var data = result.data;

            // Check for PowerPath item body/content (HTML rendered content)
            var ppBody = data.body || data.html || data.content;
            if (typeof ppBody === 'string' && ppBody.length > 20 && !data.questions && !data['qti-assessment-stimulus'] && !data['qti-assessment-test']) {
                area.innerHTML = '<h1 style="font-size:1.3rem;font-weight:700;margin-bottom:16px;">' + esc(data.title || quizState.title) + '</h1>' +
                    '<div class="stimulus-box" style="max-height:none;">' + ppBody + '</div>' +
                    '<div class="quiz-actions"><button class="quiz-btn quiz-btn-secondary" onclick="history.back()"><i class="fa-solid fa-arrow-left"></i> Back to Course</button></div>';
                return true;
            }

            // Check for stimulus
            var stimulus = data['qti-assessment-stimulus'];
            if (stimulus) {
                var stimBody = stimulus['qti-stimulus-body'] || {};
                area.innerHTML = '<h1 style="font-size:1.3rem;font-weight:700;margin-bottom:16px;">' + esc(data.title || quizState.title) + '</h1>' +
                    '<div class="stimulus-box" style="max-height:none;">' + renderNode(stimBody) + '</div>' +
                    '<div class="quiz-actions"><button class="quiz-btn quiz-btn-secondary" onclick="history.back()"><i class="fa-solid fa-arrow-left"></i> Back to Course</button></div>';
                return true;
            }

            // Render questions (from the already-fetched data)
            var questions = data.questions || [];
            if (questions.length > 0) {
                quizState.title = data.title || quizState.title;
                // Use the questions as a static quiz, one at a time
                var allQ = questions.map(function(q) {
                    var qi = q['qti-assessment-item'] || (q.content && q.content['qti-assessment-item']) || q;
                    var attrs = qi['_attributes'] || {};
                    var body = qi['qti-item-body'] || {};

                    // Detect FRQ: qti-extended-text-interaction present
                    var eti = body['qti-extended-text-interaction'];
                    var ci = body['qti-choice-interaction'] || {};
                    var isFRQ = !!eti && !ci['qti-simple-choice'];

                    // Extract prompt — check ALL possible locations
                    var promptText = '';

                    // Try qti-prompt inside interactions or body
                    var promptSources = [
                        ci['qti-prompt'], body['qti-prompt'], eti && eti['qti-prompt'],
                        qi['qti-prompt'], qi.prompt, qi.question, qi.text,
                    ];
                    for (var ps = 0; ps < promptSources.length; ps++) {
                        var src = promptSources[ps];
                        if (!src) continue;
                        if (typeof src === 'string' && src.length > 3) { promptText = src; break; }
                        if (src.p) {
                            var pArr = Array.isArray(src.p) ? src.p : [src.p];
                            promptText = pArr.map(function(p) {
                                return '<p>' + (typeof p === 'string' ? p : (p['_'] || renderNode(p))) + '</p>';
                            }).join('');
                            if (promptText) break;
                        }
                        if (typeof src === 'object') {
                            var rendered = renderNode(src);
                            if (rendered && rendered.length > 3) { promptText = rendered; break; }
                        }
                    }

                    // Try item body content (minus interactions)
                    if (!promptText) {
                        var bc = JSON.parse(JSON.stringify(body));
                        delete bc['qti-choice-interaction'];
                        delete bc['qti-extended-text-interaction'];
                        delete bc['qti-response-declaration'];
                        delete bc['qti-outcome-declaration'];
                        delete bc['_attributes'];
                        promptText = renderNode(bc);
                    }

                    // Try item title or content fields
                    if (!promptText) {
                        promptText = qi.title || attrs.title || q.title || '';
                    }

                    // Try rendering the entire qi content
                    if (!promptText && qi.content) {
                        var qiBody = qi.content['qti-item-body'] || qi.content;
                        promptText = renderNode(qiBody);
                    }

                    // FRQ: get expected lines
                    var expectedLines = 10;
                    if (eti) {
                        var etiAttrs = eti['_attributes'] || eti;
                        expectedLines = parseInt(etiAttrs['expected-lines'] || etiAttrs.expectedLines || '10', 10);
                    }

                    // Stimulus content — from backend _sectionStimulus attachment
                    var stimulusHtml = '';
                    var secStim = q['_sectionStimulus'] || qi['_sectionStimulus'] || null;
                    if (secStim) {
                        // The stimulus from QTI API can be nested in multiple ways
                        var stimObj = secStim;
                        // Try: content['qti-assessment-stimulus']['qti-stimulus-body']
                        if (stimObj.content && stimObj.content['qti-assessment-stimulus']) {
                            stimObj = stimObj.content['qti-assessment-stimulus'];
                        } else if (stimObj['qti-assessment-stimulus']) {
                            stimObj = stimObj['qti-assessment-stimulus'];
                        }
                        var stimContent = stimObj['qti-stimulus-body'] || stimObj.body || stimObj.content || stimObj;
                        if (typeof stimContent === 'string' && stimContent.length > 10) {
                            stimulusHtml = stimContent;
                        } else if (typeof stimContent === 'object') {
                            stimulusHtml = renderNode(stimContent);
                        }
                        // Fallback: try rawXml or rawHtml
                        if (!stimulusHtml && secStim.rawXml) {
                            stimulusHtml = secStim.rawXml;
                        }
                        if (!stimulusHtml && secStim.rawHtml) {
                            stimulusHtml = secStim.rawHtml;
                        }
                        // Last resort: render the entire stimulus object
                        if (!stimulusHtml) {
                            stimulusHtml = renderNode(secStim);
                        }
                        if (stimulusHtml) console.log('Stimulus found for question:', qi.title || attrs.title || q.title || '');
                    }
                    // Also check for inline stimulus ref
                    var stimRef = body['qti-stimulus-ref'];
                    var stimId = stimRef ? ((stimRef['_attributes'] || stimRef).identifier || '') : '';

                    // Multiple choice parsing
                    var sc = ci['qti-simple-choice'] || [];
                    if (!Array.isArray(sc)) sc = [sc];
                    var choices = isFRQ ? [] : sc.map(function(c,i) {
                        var ca = c['_attributes'] || {};
                        var t = c.p ? (typeof c.p === 'string' ? c.p : (c.p['_'] || renderNode(c.p))) : renderNode(c);
                        return { id: ca.identifier || String(i), text: t };
                    });

                    // Get correct answer (MC only)
                    // Get correct answer — try XML format then native JSON format
                    var correctId = '';
                    // 1. XML format: qti-response-declaration.qti-correct-response.qti-value
                    var rd = qi['qti-response-declaration'] || {};
                    if (Array.isArray(rd)) {
                        var found = false;
                        for (var rdi = 0; rdi < rd.length; rdi++) {
                            var rdAttrs = (rd[rdi] || {})['_attributes'] || {};
                            if (rdAttrs['base-type'] === 'identifier' || rdAttrs.identifier === 'RESPONSE') {
                                rd = rd[rdi]; found = true; break;
                            }
                        }
                        if (!found) rd = rd[0] || {};
                    }
                    var cr = rd['qti-correct-response'] || {};
                    var rawVal = cr['qti-value'];
                    if (typeof rawVal === 'string') correctId = rawVal;
                    else if (rawVal && typeof rawVal === 'object') {
                        if (rawVal['_']) correctId = rawVal['_'];
                        else if (rawVal['_text']) correctId = rawVal['_text'];
                        else if (Array.isArray(rawVal)) correctId = typeof rawVal[0] === 'string' ? rawVal[0] : ((rawVal[0] || {})['_'] || '');
                    }
                    // 2. Native JSON format: responseDeclarations[].correctResponse.value[]
                    if (!correctId) {
                        var jrd = qi.responseDeclarations || q.responseDeclarations || [];
                        if (Array.isArray(jrd)) {
                            for (var jri = 0; jri < jrd.length; jri++) {
                                if (jrd[jri].identifier === 'RESPONSE' || jrd[jri].baseType === 'identifier') {
                                    var cv = (jrd[jri].correctResponse || {}).value;
                                    if (Array.isArray(cv) && cv.length > 0) correctId = String(cv[0]);
                                    else if (typeof cv === 'string') correctId = cv;
                                    break;
                                }
                            }
                        }
                    }

                    // Get feedback
                    var feedbackMap = {};
                    if (!isFRQ) {
                        sc.forEach(function(c) {
                            var ca = c['_attributes'] || {};
                            var fb = c['qti-feedback-inline'] || {};
                            if (fb.span) feedbackMap[ca.identifier] = typeof fb.span === 'string' ? fb.span : renderNode(fb.span);
                        });
                    }

                    return {
                        prompt: promptText, choices: choices, correctId: correctId,
                        feedbackMap: feedbackMap, isFRQ: isFRQ, expectedLines: expectedLines,
                        stimulusId: stimId, stimulus: stimulusHtml,
                    };
                });

                // Detect reading quiz — only for Reading/ELA subject courses
                var _isReadingCourse = /^reading$|^ela$|^english\s*language\s*arts$/i.test((subject || '').trim());
                var hasAnyStimulus = allQ.some(function(q) { return q.stimulus && q.stimulus.length > 10; });
                if (_isReadingCourse && hasAnyStimulus) {
                    quizState.isReadingQuiz = true;
                    quizState.totalQuestions = allQ.length;
                    quizState.accumulatedStimuli = [];
                }

                // Run static quiz one at a time
                var currentIdx = 0;
                function showStaticQuestion() {
                    if (currentIdx >= allQ.length) { showResults(); return; }
                    var q = allQ[currentIdx];
                    quizState.currentQuestion = q;
                    quizState.selectedChoice = null;
                    quizState.answered = false;
                    quizState.questionNum = currentIdx + 1;

                    var qData = {
                        prompt: q.prompt,
                        choices: q.choices.map(function(c) { return { id: c.id, text: c.text }; }),
                        correctId: q.correctId || '',
                        isFRQ: q.isFRQ,
                        expectedLines: q.expectedLines,
                        stimulus: q.stimulus,
                    };
                    renderQuestion(qData);

                    // Override submit to handle locally
                    document.getElementById('submit-btn').onclick = function() {
                        // FRQ: read from textarea
                        var frqEl = document.getElementById('frq-response');
                        if (frqEl && !quizState.selectedChoice) {
                            quizState.selectedChoice = frqEl.value.trim();
                        }
                        if (!quizState.selectedChoice || quizState.answered) return;
                        quizState.answered = true;
                        quizState.total++;

                        var isCorrect;
                        if (q.isFRQ) {
                            // FRQ: mark as correct if response is substantial (30+ chars)
                            isCorrect = quizState.selectedChoice.length >= 30;
                        } else {
                            isCorrect = quizState.selectedChoice === q.correctId;
                        }
                        var pointsChange = 0;
                        var difficulty = _getQuestionDifficulty(q);
                        if (isCorrect) {
                            quizState.correct++;
                            pointsChange = _ppScoreChange(quizState.ppScore, difficulty, true);
                            quizState.ppScore = Math.min(100, quizState.ppScore + pointsChange);
                            quizState.xpEarned += q.isFRQ ? 2 : 1;
                        } else {
                            pointsChange = _ppScoreChange(quizState.ppScore, difficulty, false);
                            quizState.ppScore = Math.max(0, quizState.ppScore + pointsChange);
                        }

                        // Persist progress to localStorage
                        _saveProgress();

                        var fb = q.isFRQ ? '' : (q.feedbackMap[quizState.selectedChoice] || '');
                        var diffLabel = difficulty === 'easy' ? 'Easy' : difficulty === 'hard' ? 'Hard' : 'Medium';

                        if (q.isFRQ) {
                            // FRQ: disable textarea, show submission feedback
                            var frqBox = document.getElementById('frq-response');
                            if (frqBox) { frqBox.disabled = true; frqBox.style.opacity = '0.7'; }
                            var feedbackEl = document.getElementById('feedback');
                            feedbackEl.className = 'feedback correct';
                            feedbackEl.innerHTML = '<strong><i class="fa-solid fa-check-circle"></i> Response Submitted</strong>' +
                                (isCorrect ? '<p style="margin-top:6px;">Good response! XP awarded.</p>' : '<p style="margin-top:6px;">Try to write a more detailed response next time (at least 30 characters).</p>');
                        } else {
                            // MC: Highlight correct and incorrect choices
                            document.querySelectorAll('.choice').forEach(function(c) {
                                if (c.dataset.id === quizState.selectedChoice) c.classList.add(isCorrect ? 'correct' : 'incorrect');
                                if (c.dataset.id === q.correctId) c.classList.add('correct');
                            });
                            var feedbackEl = document.getElementById('feedback');
                            feedbackEl.className = 'feedback ' + (isCorrect ? 'correct' : 'incorrect');
                            feedbackEl.innerHTML = (isCorrect ? '<strong><i class="fa-solid fa-check-circle"></i> Correct! +' + pointsChange + '</strong> <span style="font-size:0.82rem;">' + diffLabel + '</span>' : '<strong><i class="fa-solid fa-times-circle"></i> Incorrect ' + pointsChange + '</strong> <span style="font-size:0.82rem;">' + diffLabel + '</span>') + (fb ? '<p style="margin-top:8px;">' + fb + '</p>' : '');
                        }

                        // Update PowerPath scoreboard
                        updateScoreboard();

                        var btn = document.getElementById('submit-btn');

                        // Quiz ends when PowerPath score reaches 100 (not for reading quizzes)
                        if (!quizState.isReadingQuiz && quizState.ppScore >= 100) {
                            quizState.xpEarned += 5; // bonus
                            btn.innerHTML = '<i class="fa-solid fa-trophy"></i> PowerPath 100 Complete!';
                            btn.onclick = function() { showResults(); };
                        } else if (currentIdx + 1 >= allQ.length) {
                            btn.innerHTML = '<i class="fa-solid fa-flag-checkered"></i> See Results';
                            btn.onclick = function() { showResults(); };
                        } else {
                            btn.innerHTML = '<i class="fa-solid fa-arrow-right"></i> Next Question';
                            btn.onclick = function() { currentIdx++; showStaticQuestion(); };
                        }
                    };
                }
                showStaticQuestion();
            } else {
                // Raw content display
                area.innerHTML = '<h1 style="font-size:1.3rem;font-weight:700;margin-bottom:16px;">' + esc(data.title || quizState.title) + '</h1>' +
                    '<div class="stimulus-box" style="max-height:none;">' + renderNode(data) + '</div>' +
                    '<div class="quiz-actions"><button class="quiz-btn quiz-btn-secondary" onclick="history.back()"><i class="fa-solid fa-arrow-left"></i> Back</button></div>';
            }
            return true;
        } catch(e) {
            return false;
        }
    }

    // ── Local FRQ assessment fallback (when PowerPath + QTI both fail) ──
    function showLocalAssessment(title, subject, gradeLevel) {
        var subjectDisplay = subject || 'this subject';
        var gradeDisplay = gradeLevel ? 'Grade ' + gradeLevel : '';
        var heading = title || ('End of Unit Assessment' + (gradeDisplay ? ' — ' + gradeDisplay : ''));

        quizState.title = heading;

        var prompts = [
            {
                num: 1,
                text: '<p><strong>Part A:</strong> Identify and explain a key concept from this unit. Use specific details and examples from the material you studied.</p>',
                lines: 8,
            },
            {
                num: 2,
                text: '<p><strong>Part B:</strong> Analyze how this concept connects to a broader theme in ' + esc(subjectDisplay) + '. Explain the cause-and-effect relationship.</p>',
                lines: 8,
            },
            {
                num: 3,
                text: '<p><strong>Part C:</strong> Evaluate the significance of what you learned. How does it apply to real-world scenarios? Support your answer with evidence.</p>',
                lines: 10,
            },
        ];

        var html = '<div class="quiz-header">' +
            '<div class="quiz-title">' + esc(heading) + '</div>' +
        '</div>' +
        '<div style="padding:12px 16px;background:#F3F0FF;border:1px solid #D6BCFA;border-radius:10px;margin-bottom:20px;font-size:0.88rem;color:#553C9A;">' +
            '<i class="fa-solid fa-pen-nib" style="margin-right:8px;"></i>' +
            '<strong>Free Response Assessment</strong> — Write thoughtful, detailed responses to each prompt below. Minimum 50 characters per response.' +
        '</div>';

        for (var i = 0; i < prompts.length; i++) {
            var p = prompts[i];
            html += '<div class="question-card" style="margin-bottom:16px;">' +
                '<div class="question-num">Question ' + p.num + ' — Free Response</div>' +
                '<div class="question-text">' + p.text + '</div>' +
                '<textarea id="local-frq-' + i + '" rows="' + p.lines + '" placeholder="Write your response here..." ' +
                    'style="width:100%;padding:14px;border:2px solid var(--color-border);border-radius:10px;font-size:0.95rem;font-family:inherit;line-height:1.7;resize:vertical;outline:none;box-sizing:border-box;" ' +
                    'onfocus="this.style.borderColor=\'var(--color-primary)\'" onblur="this.style.borderColor=\'var(--color-border)\'" ' +
                    'oninput="checkLocalFrqReady()"></textarea>' +
                '<div style="text-align:right;font-size:0.72rem;color:var(--color-text-muted);margin-top:4px;" id="local-frq-count-' + i + '">0 / 50 characters minimum</div>' +
            '</div>';
        }

        html += '<div class="quiz-actions">' +
            '<button class="quiz-btn quiz-btn-primary" id="local-frq-submit" onclick="submitLocalAssessment(' + prompts.length + ')" disabled>' +
                '<i class="fa-solid fa-paper-plane"></i> Submit Assessment</button>' +
        '</div>';

        area.innerHTML = html;
    }

    function checkLocalFrqReady() {
        var textareas = area.querySelectorAll('textarea[id^="local-frq-"]');
        var allReady = true;
        for (var i = 0; i < textareas.length; i++) {
            var len = textareas[i].value.trim().length;
            var countEl = document.getElementById('local-frq-count-' + i);
            if (countEl) {
                countEl.textContent = len + ' / 50 characters minimum';
                countEl.style.color = len >= 50 ? '#2E7D32' : 'var(--color-text-muted)';
            }
            if (len < 50) allReady = false;
        }
        document.getElementById('local-frq-submit').disabled = !allReady;
    }

    /* =====================================================================
       Question Reporting Functions
       ===================================================================== */
    var _selectedReportReason = '';

    function selectReportReason(el, reason) {
        _selectedReportReason = reason;
        document.querySelectorAll('.report-reason').forEach(function(r) { r.classList.remove('selected'); r.querySelector('input').checked = false; });
        el.classList.add('selected');
        el.querySelector('input').checked = true;
        document.getElementById('report-submit-btn').disabled = false;
    }

    function openReportModal() {
        if (!quizState.reportingEnabled) return;
        _selectedReportReason = '';
        document.querySelectorAll('.report-reason').forEach(function(r) { r.classList.remove('selected'); r.querySelector('input').checked = false; });
        document.getElementById('report-other-text').value = '';
        document.getElementById('report-submit-btn').disabled = true;
        document.getElementById('report-modal').classList.add('open');
    }

    function closeReportModal() {
        document.getElementById('report-modal').classList.remove('open');
    }

    async function submitReport() {
        if (!_selectedReportReason) return;
        var userId = localStorage.getItem('alphalearn_userId') || localStorage.getItem('alphalearn_sourcedId') || '';
        if (!userId || !quizState.currentQuestion) return;

        var btn = document.getElementById('report-submit-btn');
        btn.disabled = true;
        btn.textContent = 'Submitting...';

        var q = quizState.currentQuestion;
        // Gather article/stimulus content
        var articleContent = '';
        if (quizState.accumulatedStimuli.length > 0) {
            articleContent = quizState.accumulatedStimuli.join('\n---\n');
        } else if (q.stimulus || q.passage || q.reading) {
            articleContent = q.stimulus || q.passage || q.reading || '';
            if (typeof articleContent === 'object') articleContent = JSON.stringify(articleContent);
        }

        // Get video URL from sessionStorage lesson data if available
        var videoUrl = '';
        try {
            var ld = JSON.parse(sessionStorage.getItem('al_lesson_data') || '{}');
            var resources = ld.resources || [];
            for (var i = 0; i < resources.length; i++) {
                if (resources[i].label === 'Video') { videoUrl = resources[i].url || resources[i].pillUrl || ''; break; }
            }
        } catch(e) {}

        var payload = {
            studentId: userId,
            questionId: q.id || q.questionId || q.identifier || ('q_' + quizState.questionNum),
            questionText: q.prompt || q.question || q.text || q.body || '',
            choices: (q.choices || q.options || q.answers || []).map(function(c) {
                return { id: c.id || c.identifier || '', text: c.text || c.label || c.value || c.content || '' };
            }),
            correctId: q.correctId || '',
            reason: _selectedReportReason,
            customText: document.getElementById('report-other-text').value || '',
            videoUrl: videoUrl,
            articleContent: articleContent,
            lessonTitle: quizState.title || '',
            answeredCorrectly: quizState.answered && quizState.selectedChoice === (q.correctId || ''),
        };

        try {
            var resp = await fetch('/api/report-question', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
            var data = await resp.json();
            if (data.ok && data.reportId) {
                // Add notification (processing state)
                if (window._addReportNotif) window._addReportNotif({
                    reportId: data.reportId,
                    questionText: typeof payload.questionText === 'string' ? payload.questionText.substring(0, 80) : '',
                    answeredCorrectly: payload.answeredCorrectly,
                });
                closeReportModal();
                showReportToast('info', '<i class="fa-solid fa-spinner fa-spin"></i> Report submitted! AI is analyzing the question...');
                // Trigger AI review immediately
                triggerAIReview(data.reportId);
            } else {
                closeReportModal();
                showReportToast('info', '<i class="fa-solid fa-info-circle"></i> ' + (data.error || 'Report submitted.'));
            }
        } catch(e) {
            closeReportModal();
            showReportToast('info', '<i class="fa-solid fa-info-circle"></i> Report saved. It will be reviewed soon.');
        }
    }

    async function triggerAIReview(reportId) {
        try {
            var resp = await fetch('/api/review-report', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ reportId: reportId }),
            });
            var data = await resp.json();
            if (data.aiFlaggedBad) {
                // AI determined the question is bad — notify user, human will review
                if (window._updateReportNotif) window._updateReportNotif(reportId, {
                    status: 'ai_flagged_bad',
                    verdict: 'valid',
                    pointsAwarded: data.pointsAwarded || 0,
                    reasoning: 'Our AI has determined this question has an issue. A human will review it shortly. The question has been temporarily removed for other students.'
                });
                if (data.pointsAwarded > 0) {
                    quizState.ppScore = Math.min(100, quizState.ppScore + data.pointsAwarded);
                    updateScoreboard();
                    showReportToast('success', '<i class="fa-solid fa-check-circle"></i> AI found an issue with this question! +' + data.pointsAwarded + ' points. A human will review it shortly.');
                } else {
                    showReportToast('success', '<i class="fa-solid fa-check-circle"></i> AI found an issue with this question. A human will review it shortly.');
                }
            } else if (data.verdict === 'valid' && data.pointsAwarded > 0) {
                quizState.ppScore = Math.min(100, quizState.ppScore + data.pointsAwarded);
                updateScoreboard();
                if (window._updateReportNotif) window._updateReportNotif(reportId, { status: 'completed', verdict: 'valid', pointsAwarded: data.pointsAwarded });
                showReportToast('success', '<i class="fa-solid fa-star"></i> Your score has been increased by ' + data.pointsAwarded + ' points due to your valid question report!');
            } else if (data.verdict === 'valid') {
                // Valid report but no points (student got it right) — sent to internal team
                if (window._updateReportNotif) window._updateReportNotif(reportId, { status: 'completed', verdict: 'valid', pointsAwarded: 0 });
            } else {
                // Invalid report — pass AI reasoning so student sees why the question was valid
                if (window._updateReportNotif) window._updateReportNotif(reportId, { status: 'completed', verdict: 'invalid', pointsAwarded: 0, reasoning: data.reasoning || '' });
            }
        } catch(e) {}
    }

    function showReportToast(type, html) {
        var t = document.getElementById('report-toast');
        t.className = 'report-toast ' + type;
        t.innerHTML = html;
        requestAnimationFrame(function() { t.classList.add('visible'); });
        setTimeout(function() { t.classList.remove('visible'); }, 6000);
    }

    // Close report modal on Escape or overlay click
    document.getElementById('report-modal').addEventListener('click', function(e) { if (e.target === this) closeReportModal(); });
    document.addEventListener('keydown', function(e) { if (e.key === 'Escape' && document.getElementById('report-modal').classList.contains('open')) closeReportModal(); });

    function submitLocalAssessment(count) {
        var responses = [];
        for (var i = 0; i < count; i++) {
            var ta = document.getElementById('local-frq-' + i);
            if (ta) { ta.disabled = true; responses.push(ta.value.trim()); }
        }

        // Award XP: 2 per substantial response
        var xp = 0;
        for (var r = 0; r < responses.length; r++) {
            if (responses[r].length >= 50) xp += 2;
        }

        _markQuizComplete();

        area.innerHTML = '<div class="result-card">' +
            '<div style="font-size:3rem;margin-bottom:8px;">✅</div>' +
            '<div class="result-score" style="font-size:2rem;">Assessment Complete</div>' +
            '<div class="result-label" style="margin-top:8px;">Your responses have been recorded.</div>' +
            '<div class="xp-badge"><i class="fa-solid fa-bolt"></i> ' + xp + ' XP earned</div>' +
            '<div class="result-details">' +
                '<div class="result-stat"><div class="result-stat-val">' + responses.length + '</div><div class="result-stat-label">Responses</div></div>' +
                '<div class="result-stat"><div class="result-stat-val">' + xp + '</div><div class="result-stat-label">XP Earned</div></div>' +
            '</div>' +
            '<div style="margin-top:16px;padding:12px 20px;background:#E8F5E9;border-radius:10px;color:#1B5E20;font-size:0.9rem;">' +
                '<i class="fa-solid fa-check-circle" style="margin-right:6px;"></i>This assessment is now marked as complete.</div>' +
            '<div style="margin-top:24px;">' +
                '<button class="quiz-btn quiz-btn-primary" onclick="history.back()"><i class="fa-solid fa-arrow-right"></i> Continue to Next Lesson</button>' +
            '</div>' +
        '</div>';
    }
    