    /* ====================================================================
       Lesson Viewer — Video → Article → Quiz (all inline)
       ==================================================================== */
    var steps = [];
    var currentStep = 0;
    var lessonData = null;

    var stepConfig = {
        'Video':   { icon: 'fa-video',              label: 'Video' },
        'Article': { icon: 'fa-file-lines',          label: 'Article' },
        'Quiz':    { icon: 'fa-clipboard-question',   label: 'Quiz' }
    };

    /* ── Inline quiz state ──────────────────────────────────── */
    var quizState = {
        attemptId: null, questionNum: 0, correct: 0, total: 0,
        xpEarned: 0, ppScore: 0, streak: 0,
        currentQuestion: null, selectedChoice: null, answered: false,
        testId: '', quizLessonId: '', title: '', active: false, finished: false,
        // For static (QTI) quiz
        staticQuestions: null, staticIdx: 0,
        // Reading quiz mode
        isReadingQuiz: false, accumulatedStimuli: [], totalQuestions: 0,
        // Crossout tool
        crossOutMode: false, crossedOut: {},
        // Question reporting
        reportingEnabled: true,
        cachedPassage: '',
        // Track answered question IDs locally (survives reload even if server state is stale)
        answeredIds: [],
    };
    var quizArea = null; // reference to the quiz container element

    // ── Progress persistence (save/restore across sessions) ──
    function _getQuizProgressKey() {
        // Use attemptId as key when available — it encodes student+lesson and is always correct
        if (quizState.attemptId) return 'quiz_progress:' + quizState.attemptId;
        // Fallback for before attemptId is set
        var userId = localStorage.getItem('alphalearn_userId') || localStorage.getItem('alphalearn_sourcedId') || '';
        var lessonId = quizState.quizLessonId || (lessonData && lessonData.lessonSourcedId) || quizState.testId || '';
        if (!userId || !lessonId) return '';
        return 'quiz_progress:' + userId + ':' + lessonId;
    }

    function _saveQuizProgress() {
        var key = _getQuizProgressKey();
        if (!key) { console.warn('[QuizProgress] Cannot save — key is empty. quizLessonId:', quizState.quizLessonId, 'lessonSourcedId:', lessonData && lessonData.lessonSourcedId, 'testId:', quizState.testId); return; }
        try {
            var payload = {
                ppScore: quizState.ppScore,
                correct: quizState.correct,
                total: quizState.total,
                streak: quizState.streak,
                xpEarned: quizState.xpEarned,
                questionNum: quizState.questionNum,
                attemptId: quizState.attemptId,
                answeredIds: quizState.answeredIds,
                timestamp: Date.now(),
            };
            localStorage.setItem(key, JSON.stringify(payload));
            console.log('[QuizProgress] Saved —', key, '— answeredIds:', quizState.answeredIds.length, 'questionNum:', quizState.questionNum);
        } catch(e) { console.warn('[QuizProgress] Save error:', e); }
    }

    function _restoreQuizProgress() {
        var key = _getQuizProgressKey();
        if (!key) { console.warn('[QuizProgress] Cannot restore — key is empty'); return false; }
        try {
            var raw = localStorage.getItem(key);
            if (!raw) { console.log('[QuizProgress] No saved data for', key); return false; }
            var saved = JSON.parse(raw);
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
            console.log('[QuizProgress] Restored —', key, '— answeredIds:', quizState.answeredIds, 'questionNum:', quizState.questionNum, 'total:', quizState.total);
            return true;
        } catch(e) { console.warn('[QuizProgress] Restore error:', e); return false; }
    }

    function _clearQuizProgress() {
        var key = _getQuizProgressKey();
        if (key) localStorage.removeItem(key);
    }

    // Save progress automatically when leaving or hiding the page
    window.addEventListener('beforeunload', function() {
        if (quizState.total > 0) _saveQuizProgress();
    });
    document.addEventListener('visibilitychange', function() {
        if (document.hidden && quizState.total > 0) _saveQuizProgress();
    });

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


    /* ══════════════════════════════════════════════════════════
       Progress Sync — OneRoster Results + Caliper Activity
       ══════════════════════════════════════════════════════════
       Two sync mechanisms (per Timeback docs):
       1. OneRoster AssessmentResult — records score in gradebook
       2. Caliper ToolUseEvent      — records activity metrics (XP, accuracy, mastery)
       ══════════════════════════════════════════════════════════ */
    var syncState = {
        userId: '',              // platform sourcedId
        userEmail: '',           // for Caliper actor
        lessonStartTime: null,   // ISO string — set when lesson opens
    };

    var APP_SENSOR = 'https://alphalearn.alpha.school';

    function _uuid() {
        if (crypto && crypto.randomUUID) return crypto.randomUUID();
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            var r = Math.random() * 16 | 0;
            return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
        });
    }

    /* ── 1. OneRoster: POST assessment result to gradebook ── */
    function submitAssessmentResult(score, passed) {
        // PRIORITY: Use the PowerPath assessmentLineItemSourcedId if available
        // This ensures results sync properly with PowerPath getCourseProgress
        var lineItemId = lessonData.assessmentLineItemSourcedId || '';
        
        // Fallback: try to get from resource data
        if (!lineItemId) {
            for (var si = 0; si < steps.length; si++) {
                if (steps[si].type === 'Quiz' && steps[si].resource) {
                    lineItemId = steps[si].resource.assessmentLineItemSourcedId || steps[si].resource.resId || '';
                    if (lineItemId) break;
                }
            }
        }
        
        // Secondary fallback: quiz testId or resource ID
        if (!lineItemId) lineItemId = quizState.testId || '';
        if (!lineItemId) {
            for (var si = 0; si < steps.length; si++) {
                if (steps[si].type === 'Quiz' && steps[si].resource) {
                    lineItemId = steps[si].resource.resId || '';
                    if (lineItemId) break;
                }
            }
        }
        
        // Final fallback: use the lesson title
        if (!lineItemId) lineItemId = lessonData.title || '';

        console.log('[Sync] Submitting AssessmentResult — userId:', syncState.userId, 'lineItemId:', lineItemId, 'ppALI:', lessonData.assessmentLineItemSourcedId || 'none', 'score:', score);

        // Determine step type from current lesson steps
        var quizStepType = 'Quiz';
        for (var si = 0; si < steps.length; si++) {
            if (steps[si].type === 'Quiz') { quizStepType = 'Quiz'; break; }
            if (si === steps.length - 1) quizStepType = steps[si].type || 'Quiz';
        }

        var payload = {
            studentSourcedId: syncState.userId,
            assessmentLineItemSourcedId: lineItemId,
            score: score,
            scoreStatus: 'fully graded',
            comment: (lessonData.title || 'Quiz') + ' — ' + score + '% accuracy' + (score >= 80 ? ' — Mastery' : ''),
            metadata: {
                'timeback.xp': quizState.xpEarned,
                'timeback.correct': quizState.correct,
                'timeback.total': quizState.total,
                'timeback.passed': passed,
                'timeback.ppScore': quizState.ppScore,
                'timeback.stepType': quizStepType,
                'timeback.lessonTitle': lessonData.title || '',
                'timeback.courseTitle': lessonData.courseName || lessonData.courseTitle || '',
                'timeback.enrollmentId': lessonData.enrollmentId || '',
            },
        };

        fetch('/api/submit-result', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            console.log('[Sync] AssessmentResult response:', JSON.stringify(d));
            if (d.attempts) { d.attempts.forEach(function(a) { console.log('[Sync] Attempt:', a.name, a.method, a.httpStatus, (a.body||'').substring(0,200)); }); }
        })
        .catch(function(e) {
            console.error('[Sync] AssessmentResult FAILED:', e.message);
        });
    }

    /* ── 2. Caliper: send ActivityCompletedEvent (TimebackProfile) ── */
    function sendCaliperActivity(passed) {
        var now = new Date().toISOString();
        var runId = _uuid();
        var xp = passed ? quizState.xpEarned : 0;

        console.log('[Sync] Sending Caliper ActivityCompletedEvent — userId:', syncState.userId, 'email:', syncState.userEmail, 'xp:', xp, 'correct:', quizState.correct, '/', quizState.total, 'passed:', passed);

        // Subject detection from lesson data
        var subject = 'Other';
        var titleLower = ((lessonData.courseName || lessonData.courseTitle || lessonData.title) || '').toLowerCase();
        if (titleLower.includes('math')) subject = 'Math';
        else if (titleLower.includes('reading') || titleLower.includes('ela') || titleLower.includes('english')) subject = 'Reading';
        else if (titleLower.includes('science') || titleLower.includes('biology') || titleLower.includes('chemistry') || titleLower.includes('physics')) subject = 'Science';
        else if (titleLower.includes('history') || titleLower.includes('social') || titleLower.includes('government') || titleLower.includes('geography')) subject = 'Social Studies';
        else if (titleLower.includes('writing') || titleLower.includes('essay')) subject = 'Writing';
        else if (titleLower.includes('vocabulary') || titleLower.includes('vocab')) subject = 'Vocabulary';
        else if (titleLower.includes('language') || titleLower.includes('spanish') || titleLower.includes('french')) subject = 'Language';

        var courseCode = lessonData.courseSourcedId || lessonData.courseName || lessonData.courseTitle || '';
        var enrollmentId = lessonData.enrollmentId || '';

        // Build ActivityCompletedEvent per Timeback docs
        var metrics = [
            { type: 'xpEarned', value: xp },
            { type: 'totalQuestions', value: quizState.total },
            { type: 'correctQuestions', value: quizState.correct },
        ];
        if (passed) {
            metrics.push({ type: 'masteredUnits', value: 1 });
        }

        var activityId = APP_SENSOR + '/activities/' + encodeURIComponent(subject) + '/' + encodeURIComponent(lessonData.title || 'lesson');
        var metricsId = 'https://api.alpha-1edtech.ai/ims/metrics/collections/activity/' + runId;

        console.log('[Sync] Caliper event enrollmentId:', enrollmentId, 'courseId:', courseCode);

        var event = {
            '@context': 'http://purl.imsglobal.org/ctx/caliper/v1p2',
            id: 'urn:uuid:' + _uuid(),
            type: 'ActivityEvent',
            action: 'Completed',
            profile: 'TimebackProfile',
            eventTime: now,
            actor: {
                id: 'https://api.alpha-1edtech.ai/ims/oneroster/rostering/v1p2/users/' + syncState.userId,
                type: 'TimebackUser',
                email: syncState.userEmail || undefined,
            },
            object: {
                id: activityId,
                type: 'TimebackActivityContext',
                subject: subject,
                app: { name: 'AlphaLearn' },
            },
            generated: {
                id: metricsId,
                type: 'TimebackActivityMetricsCollection',
                items: metrics,
                extensions: passed ? { pctCompleteApp: 100 } : undefined,
            },
            edApp: APP_SENSOR,
            extensions: {
                runId: runId,
                courseId: courseCode,
                enrollmentId: enrollmentId || undefined,
            },
        };

        fetch('/api/caliper-event', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ data: [event] }),
        })
        .then(function(r) { return r.json(); })
        .then(function(d) { console.log('[Sync] Caliper response:', JSON.stringify(d)); })
        .catch(function(e) { console.error('[Sync] Caliper FAILED:', e.message); });
    }

    /* ── 3. SDK-style activity record (updates XP on Timeback dashboards) ── */
    function sendActivityRecord(passed) {
        var xp = passed ? quizState.xpEarned : 0;
        if (xp <= 0) return;

        var email = localStorage.getItem('alphalearn_email') || '';
        var courseCode = lessonData.courseSourcedId || lessonData.courseName || '';
        var activityId = lessonData.lessonSourcedId || quizState.testId || lessonData.title || '';

        var payload = {
            userId: syncState.userId,
            email: email,
            activityId: activityId,
            activityName: lessonData.title || 'Quiz',
            courseCode: courseCode,
            xpEarned: xp,
            totalQuestions: quizState.total,
            correctQuestions: quizState.correct,
            pctComplete: quizState.total > 0 ? Math.round((quizState.correct / quizState.total) * 100) : 100,
        };

        console.log('[Sync] Sending activity-record — xp:', xp, 'course:', courseCode, 'activity:', activityId);

        fetch('/api/activity-record', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
        .then(function(r) { return r.json(); })
        .then(function(d) { console.log('[Sync] Activity-record response:', JSON.stringify(d)); })
        .catch(function(e) { console.error('[Sync] Activity-record FAILED:', e.message); });
    }

    /* ── 4. PowerPath: finalize lesson via finalStudentAssessmentResponse API ── */
    /* Returns a Promise that resolves with { xpEarned, multiplier, finalScore } from PowerPath.
       The backend now always tries getAssessmentProgress even if finalize fails,
       so we can extract XP from "partial" or "error" responses too. */
    async function markLessonComplete(score) {
        // Priority: use the quiz resource's componentResId (PowerPath needs this format,
        // e.g. "USHI23-l48-r104178-v1", not the lesson-level "USHI23-l48-v1")
        var lessonId = '';
        for (var si = 0; si < steps.length; si++) {
            if (steps[si].type === 'Quiz' && steps[si].resource) {
                lessonId = steps[si].resource.componentResId || steps[si].resource.resId || '';
                if (lessonId) break;
            }
        }
        // Fallback: lesson-level sourcedId
        if (!lessonId) lessonId = lessonData.lessonSourcedId || '';
        
        if (!lessonId || !syncState.userId) {
            console.warn('[Sync] No lessonId or userId - skipping PowerPath finalize');
            return { xpEarned: 0, multiplier: 1, finalScore: null };
        }
        
        var payload = {
            studentId: syncState.userId,
            lessonId: lessonId
        };
        if (typeof score === 'number') {
            payload.score = score;
        }
        
        console.log('[Sync] Finalizing lesson via PowerPath - lessonId:', lessonId, 'userId:', syncState.userId, 'score:', score);
        
        try {
            var resp = await fetch('/api/finalize-lesson', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            var d = await resp.json();
            console.log('[Sync] PowerPath finalize response (status ' + resp.status + '):', JSON.stringify(d));
            
            // The backend now returns xpEarned even on "partial" status
            // (when finalize failed but getAssessmentProgress succeeded)
            var ppXp = d.xpEarned || 0;
            var ppMultiplier = d.multiplier || 1;
            var ppScore = typeof d.powerpathScore === 'number' ? d.powerpathScore : null;
            var ppAccuracy = typeof d.powerpathAccuracy === 'number' ? d.powerpathAccuracy : null;
            
            if (d.status === 'error' && ppXp === 0) {
                console.error('[Sync] PowerPath finalize returned error with no XP:', d.message || 'unknown error');
            } else if (d.status === 'partial') {
                console.warn('[Sync] PowerPath finalize failed but XP retrieved from progress:', ppXp);
            } else {
                console.log('[Sync] PowerPath XP extracted — xpEarned:', ppXp, 'multiplier:', ppMultiplier, 'score:', ppScore, 'accuracy:', ppAccuracy);
            }
            
            return { xpEarned: ppXp, multiplier: ppMultiplier, finalScore: ppScore, accuracy: ppAccuracy };
        } catch(e) {
            console.error('[Sync] PowerPath finalize request FAILED:', e.message);
            return { xpEarned: 0, multiplier: 1, finalScore: null };
        }
    }

    /* ── Combined: fire all sync methods on quiz completion ── */
    /* Async: finalizes on PowerPath FIRST to get real XP, then reports through all channels */
    async function syncQuizCompletion(pct, passed) {
        if (!syncState.userId) {
            console.error('[Sync] NO userId — cannot sync! Check localStorage alphalearn_userId');
            return;
        }
        console.log('[Sync] === Syncing quiz completion === pct:', pct, 'passed:', passed, 'localXp:', quizState.xpEarned);

        // ── STEP 1: Finalize on PowerPath FIRST to get authoritative XP ──
        // PowerPath's getAssessmentProgress returns the real XP value after finalization.
        // We must await this before reporting XP to other systems.
        if (passed) {
            try {
                var ppResult = await markLessonComplete(pct);
                if (ppResult && ppResult.xpEarned > 0) {
                    console.log('[Sync] Using PowerPath XP:', ppResult.xpEarned, '(was local:', quizState.xpEarned, ')');
                    quizState.xpEarned = ppResult.xpEarned;
                } else {
                    console.log('[Sync] PowerPath returned no XP, keeping local XP:', quizState.xpEarned);
                }
            } catch(e) {
                console.error('[Sync] PowerPath finalize await failed:', e.message, '— using local XP:', quizState.xpEarned);
            }
            saveLessonToLocalStorage();
        }

        console.log('[Sync] Final XP to report:', quizState.xpEarned);

        // ── STEP 2: Report XP through all channels (now using PowerPath XP) ──
        // 2a. OneRoster: Record assessment result with real XP in metadata
        submitAssessmentResult(pct, passed);
        
        // 2b. Caliper: Send activity event for XP/metrics
        sendCaliperActivity(passed);
        
        // 2c. SDK-style activity record (updates XP on Timeback dashboards)
        if (passed) {
            sendActivityRecord(passed);
        }

        // ── STEP 3: Signal course page to refresh ──
        sessionStorage.setItem('al_progress_changed', 'true');

        // ── STEP 4: Save XP locally so the course page can show it immediately ──
        var xp = passed ? quizState.xpEarned : 0;
        if (xp > 0) {
            var enrollId = lessonData.enrollmentId || '';
            var existingXP = parseInt(localStorage.getItem('local_xp_' + enrollId) || '0', 10);
            localStorage.setItem('local_xp_' + enrollId, String(existingXP + xp));
            // Also save per-lesson XP
            var lTitle = lessonData.title || '';
            if (lTitle) localStorage.setItem('xp_' + lTitle, String(xp));
        }

        // ── STEP 5: Update the results UI with real XP (if visible) ──
        var xpBadge = document.querySelector('.xp-badge');
        if (xpBadge && xp > 0) {
            xpBadge.innerHTML = '<i class="fa-solid fa-bolt"></i> ' + xp + ' XP earned';
            xpBadge.className = 'xp-badge';
        }
    }

    /* ── Sync article/video step completion ── */
    function syncStepCompletion(step) {
        if (!syncState.userId) {
            console.warn('[Sync] No userId — skipping step sync');
            return;
        }
        
        var resourceId = (step.resource && step.resource.resId) || lessonData.lessonSourcedId || '';
        var stepLabel = step.type || 'Content';
        var contentType = stepLabel.toLowerCase(); // 'video' or 'article'
        
        console.log('[Sync] Syncing', stepLabel, 'completion — resourceId:', resourceId, 'userId:', syncState.userId);
        
        // Use the dedicated mark-content-complete endpoint for articles/videos
        // Each resource has its OWN assessmentLineItemSourcedId from PowerPath
        var stepALI = (step.resource && step.resource.assessmentLineItemSourcedId) || '';
        var componentResId = (step.resource && step.resource.componentResId) || resourceId;
        if (resourceId && stepALI) {
            fetch('/api/mark-content-complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    studentId: syncState.userId,
                    resourceId: resourceId,
                    componentResId: componentResId,
                    assessmentLineItemSourcedId: stepALI,
                    contentType: contentType,
                    title: step.resource.title || lessonData.title || stepLabel,
                    email: syncState.userEmail || '',
                    courseId: lessonData.courseSourcedId || '',
                    courseName: lessonData.courseName || lessonData.courseTitle || '',
                }),
            })
            .then(function(r) { return r.json(); })
            .then(function(d) { 
                console.log('[Sync]', stepLabel, 'mark-content-complete response:', JSON.stringify(d));
                if (d.success) {
                    console.log('[Sync]', stepLabel, 'successfully marked as complete via API');
                }
            })
            .catch(function(e) { console.error('[Sync]', stepLabel, 'mark-content-complete FAILED:', e.message); });
        }
        
        // Submit to OneRoster using the RESOURCE'S OWN assessmentLineItemSourcedId
        // (each video/article has its own ALI — NOT the shared lesson-level one)
        var lineItemId = (step.resource && step.resource.assessmentLineItemSourcedId) || '';
        if (!lineItemId) lineItemId = lessonData.assessmentLineItemSourcedId || '';
        if (!lineItemId) lineItemId = lessonData.title || '';
        
        // Use actual question counts from quizState if available
        var stepCorrect = quizState.correct || 0;
        var stepTotal = quizState.total || 0;
        var stepAccuracy = stepTotal > 0 ? Math.round((stepCorrect / stepTotal) * 100) : 100;

        fetch('/api/submit-result', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                studentSourcedId: syncState.userId,
                assessmentLineItemSourcedId: lineItemId,
                score: stepAccuracy,
                scoreStatus: 'fully graded',
                comment: (lessonData.title || stepLabel) + ' — ' + stepAccuracy + '% accuracy' + (stepAccuracy >= 80 ? ' — Mastery' : ''),
                metadata: {
                    'timeback.xp': quizState.xpEarned || 0,
                    'timeback.correct': stepCorrect,
                    'timeback.total': stepTotal,
                    'timeback.passed': true,
                    'timeback.lessonTitle': lessonData.title || '',
                    'timeback.courseTitle': lessonData.courseName || lessonData.courseTitle || '',
                    'timeback.enrollmentId': lessonData.enrollmentId || '',
                    'timeback.stepType': stepLabel,
                },
            }),
        })
        .then(function(r) { return r.json(); })
        .then(function(d) { 
            console.log('[Sync]', stepLabel, 'OneRoster result response:', JSON.stringify(d));
        })
        .catch(function(e) { console.error('[Sync]', stepLabel, 'OneRoster result FAILED:', e.message); });
        
        // 3. localStorage for immediate UI feedback
        var localKey = 'completed_' + (lessonData.title || '');
        if (localKey !== 'completed_') {
            localStorage.setItem(localKey, 'true');
        }
        sessionStorage.setItem('al_progress_changed', 'true');
    }

    function initSync() {
        syncState.userId = localStorage.getItem('alphalearn_userId')
            || localStorage.getItem('alphalearn_sourcedId') || '';
        syncState.userEmail = localStorage.getItem('alphalearn_email') || '';
        syncState.lessonStartTime = new Date().toISOString();
        if (!syncState.userId) {
            console.warn('[Sync] No userId found, progress will not be synced');
        }
    }

    function resetQuizState() {
        quizState.attemptId = null; quizState.questionNum = 0;
        quizState.correct = 0; quizState.total = 0; quizState.xpEarned = 0;
        quizState.ppScore = 0; quizState.streak = 0;
        quizState.currentQuestion = null; quizState.selectedChoice = null;
        quizState.answered = false; quizState.active = false;
        quizState.finished = false; quizState.staticQuestions = null;
        quizState.staticIdx = 0; quizState.quizLessonId = '';
        quizState.isReadingQuiz = false; quizState.accumulatedStimuli = [];
        quizState.totalQuestions = 0;
        quizState.answeredIds = [];
    }

    /* ── QTI renderNode (for rich question content) ─────────── */
    function renderNode(node) {
        if (!node) return '';
        if (typeof node === 'string') return node;
        if (Array.isArray(node)) return node.map(renderNode).join('');
        var html = '';
        for (var key in node) {
            if (key.startsWith('_')) continue;
            if (key.indexOf('feedback') !== -1) continue;
            var val = node[key];
            if (key === 'strong' || key === 'b') { html += '<strong>' + (typeof val === 'string' ? val : renderNode(val)) + '</strong>'; continue; }
            if (key === 'em' || key === 'i') { html += '<em>' + (typeof val === 'string' ? val : renderNode(val)) + '</em>'; continue; }
            if (key === 'p') { var ps = Array.isArray(val) ? val : [val]; ps.forEach(function(p) { html += '<p>' + (typeof p === 'string' ? p : (p['_'] || renderNode(p))) + '</p>'; }); continue; }
            if (key === 'img') { var ia = val['_attributes'] || val; html += '<img src="' + esc(ia.src||'') + '" alt="' + esc(ia.alt||'') + '" style="max-width:100%;border-radius:8px;">'; continue; }
            if (key === 'span') { html += typeof val === 'string' ? val : renderNode(val); continue; }
            if (key === 'div') { var ds = Array.isArray(val) ? val : [val]; ds.forEach(function(d){ html += renderNode(d); }); continue; }
            if (key === 'table') { var ts=Array.isArray(val)?val:[val]; ts.forEach(function(t){html+='<table style="width:100%;border-collapse:collapse;margin:12px 0;font-size:0.9rem;">'+renderNode(t)+'</table>';}); continue; }
            if (key === 'thead') { html += '<thead style="background:var(--color-bg);font-weight:600;">' + renderNode(val) + '</thead>'; continue; }
            if (key === 'tbody') { html += '<tbody>' + renderNode(val) + '</tbody>'; continue; }
            if (key === 'tr') { var trs=Array.isArray(val)?val:[val]; trs.forEach(function(r){html+='<tr>'+renderNode(r)+'</tr>';}); continue; }
            if (key === 'th') { var ths=Array.isArray(val)?val:[val]; ths.forEach(function(c){html+='<th style="padding:8px 12px;border:1px solid var(--color-border);text-align:left;">'+(typeof c==='string'?c:(c['_']||renderNode(c)))+'</th>';}); continue; }
            if (key === 'td') { var tds=Array.isArray(val)?val:[val]; tds.forEach(function(c){html+='<td style="padding:8px 12px;border:1px solid var(--color-border);">'+(typeof c==='string'?c:(c['_']||renderNode(c)))+'</td>';}); continue; }
            if (key === 'caption') { html += '<caption style="font-weight:600;margin-bottom:8px;">' + (typeof val === 'string' ? val : renderNode(val)) + '</caption>'; continue; }
            if (key === 'ul') { html += '<ul style="margin:8px 0;padding-left:20px;">' + renderNode(val) + '</ul>'; continue; }
            if (key === 'ol') { html += '<ol style="margin:8px 0;padding-left:20px;">' + renderNode(val) + '</ol>'; continue; }
            if (key === 'li') { var lis=Array.isArray(val)?val:[val]; lis.forEach(function(l){html+='<li style="margin-bottom:4px;">'+(typeof l==='string'?l:(l['_']||renderNode(l)))+'</li>';}); continue; }
            if (key === 'br') { html += '<br>'; continue; }
            if (key === 'blockquote') { html += '<blockquote style="border-left:3px solid var(--color-primary);padding:8px 16px;margin:12px 0;background:var(--color-bg);border-radius:4px;">' + (typeof val === 'string' ? val : renderNode(val)) + '</blockquote>'; continue; }
            if (typeof val === 'object' && val !== null) html += renderNode(val);
        }
        return html;
    }

    /* ── Init ───────────────────────────────────────────────── */
    function init() {
        var raw = sessionStorage.getItem('al_lesson_data');
        if (!raw) { showError('No lesson data found. Please go back and select a lesson.'); return; }
        try { lessonData = JSON.parse(raw); } catch(e) { showError('Invalid lesson data.'); return; }

        document.title = 'AlphaLearn - ' + (lessonData.title || 'Lesson');

        // Set title
        var titleEl = document.getElementById('lesson-title-text');
        if (titleEl) titleEl.textContent = lessonData.title || 'Lesson';

        var resources = lessonData.resources || [];
        var videos = [], articles = [], quizzes = [];
        for (var i = 0; i < resources.length; i++) {
            var r = resources[i];
            if (r.label === 'Video') videos.push(r);
            else if (r.label === 'Quiz') quizzes.push(r);
            else articles.push(r);
        }
        if (videos.length > 0) steps.push({ type: 'Video', resource: videos[0] });
        if (articles.length > 0) steps.push({ type: 'Article', resource: articles[0] });
        if (quizzes.length > 0) steps.push({ type: 'Quiz', resource: quizzes[0] });

        if (steps.length === 0) { showError('This lesson has no content yet.'); return; }

        // Initialize progress sync
        initSync();

        renderStepper();
        var savedStep = _restoreSavedStep();
        showStep(savedStep);
    }

    function renderStepper() {
        var el = document.getElementById('stepper');
        var html = '';
        for (var i = 0; i < steps.length; i++) {
            var cfg = stepConfig[steps[i].type] || { icon: 'fa-circle', label: steps[i].type };
            var cls = i < currentStep ? 'completed' : i === currentStep ? 'active' : 'upcoming';

            html += '<div class="step-group">';
            html += '<div class="step ' + cls + '" onclick="showStep(' + i + ')">';
            html += '<div class="step-icon">';
            if (i < currentStep) {
                html += '<i class="fa-solid fa-check"></i>';
            } else {
                html += '<i class="fa-solid ' + cfg.icon + '"></i>';
            }
            html += '</div>';
            html += '<span class="step-label">' + cfg.label + '</span>';
            html += '</div>';

            // Connector line between steps
            if (i < steps.length - 1) {
                var connCls = i < currentStep ? 'step-connector done' : 'step-connector';
                html += '<div class="' + connCls + '"></div>';
            }
            html += '</div>';
        }
        el.innerHTML = html;
    }

    /* ── Step persistence helpers ─────────────────────────────── */
    function _getStepKey() {
        var id = (lessonData && (lessonData.lessonSourcedId || lessonData.completionKey)) || '';
        return id ? 'lesson_step:' + id : '';
    }
    function _saveCurrentStep(idx) {
        var key = _getStepKey();
        if (key) localStorage.setItem(key, String(idx));
    }
    function _restoreSavedStep() {
        var key = _getStepKey();
        if (!key) return 0;
        var saved = localStorage.getItem(key);
        if (saved == null) return 0;
        var idx = parseInt(saved, 10);
        return (isNaN(idx) || idx < 0 || idx >= steps.length) ? 0 : idx;
    }
    function _clearSavedStep() {
        var key = _getStepKey();
        if (key) localStorage.removeItem(key);
    }

    /* ── Show Step ──────────────────────────────────────────── */
    function showStep(idx) {
        if (idx < 0 || idx >= steps.length) return;
        currentStep = idx;
        _saveCurrentStep(idx);
        renderStepper();

        var step = steps[idx];
        var contentEl = document.getElementById('lesson-content');
        var nav = document.getElementById('lesson-nav');
        var btnContinue = document.getElementById('btn-continue');

        var url = step.resource.url || step.resource.pillUrl || '';

        // Ensure lesson page is visible for non-quiz steps
        var lessonPage = document.querySelector('.lesson-page');
        if (lessonPage) {
            lessonPage.style.display = '';
            // Reset wide mode when switching away from quiz
            if (step.type !== 'Quiz') lessonPage.classList.remove('wide-mode');
        }

        // Toggle quiz-mode (strips outer card styling for quiz)
        contentEl.classList.toggle('quiz-mode', step.type === 'Quiz');

        if (step.type === 'Video') {
            nav.classList.remove('hidden');
            btnContinue.style.display = '';
            btnContinue.innerHTML = (idx === steps.length - 1) ? 'Finish <i class="fa-solid fa-check"></i>' : 'Continue <i class="fa-solid fa-arrow-right"></i>';
            var btnBack = document.getElementById('btn-back');
            btnBack.innerHTML = '<i class="fa-solid fa-arrow-left"></i> Back';
            btnBack.onclick = function() { goBack(); };
            var embedUrl = toEmbedUrl(url);
            if (embedUrl) {
                contentEl.innerHTML = '<div class="video-wrap"><iframe src="' + esc(embedUrl) + '" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe></div>';
            } else {
                contentEl.innerHTML = '<div class="lesson-placeholder"><div class="ph-icon"><i class="fa-solid fa-video"></i></div><p>Video</p><p class="sub"><a href="' + esc(url) + '" target="_blank" style="color:var(--color-primary);font-weight:600;">Open video in new tab</a></p></div>';
            }
        } else if (step.type === 'Article') {
            nav.classList.remove('hidden');
            btnContinue.style.display = '';
            btnContinue.innerHTML = (idx === steps.length - 1) ? 'Finish <i class="fa-solid fa-check"></i>' : 'Continue <i class="fa-solid fa-arrow-right"></i>';
            var btnBack = document.getElementById('btn-back');
            btnBack.innerHTML = '<i class="fa-solid fa-arrow-left"></i> Back';
            btnBack.onclick = function() { goBack(); };
            var resId = step.resource.resId || '';
            if (url || resId) {
                contentEl.innerHTML = '<div class="article-loading"><i class="fa-solid fa-spinner fa-spin"></i><span>Loading article...</span></div>';
                fetchArticle(url, resId, contentEl);
            } else {
                contentEl.innerHTML = '<div class="lesson-placeholder"><div class="ph-icon"><i class="fa-solid fa-file-lines"></i></div><p>Article content</p><p class="sub">No article URL available for this lesson.</p></div>';
            }
        } else if (step.type === 'Quiz') {
            nav.classList.add('hidden');
            resetQuizState();
            quizState.active = true;
            quizState.title = lessonData.title || 'Quiz';
            // Prepare quiz area (hidden behind overlay)
            contentEl.innerHTML = '<div class="quiz-area" id="quiz-area"></div>';
            quizArea = document.getElementById('quiz-area');
            startInlineQuiz(step.resource);
        }
    }

    /* ==================================================================
       INLINE QUIZ ENGINE
       ================================================================== */

    async function startInlineQuiz(resource) {
        var pillUrl = resource.pillUrl || '';
        var resUrl = resource.url || '';
        // Parse quiz params from pillUrl (e.g. /quiz?url=...&title=...&subject=...&grade=...)
        var qParams = {};
        if (pillUrl && pillUrl.includes('?')) {
            var sp = new URLSearchParams(pillUrl.split('?')[1]);
            qParams.url = sp.get('url') || '';
            qParams.id = sp.get('id') || sp.get('testId') || '';
            qParams.subject = sp.get('subject') || '';
            qParams.grade = sp.get('grade') || sp.get('gradeLevel') || '';
            qParams.title = sp.get('title') || '';
        }
        var testId = qParams.id || resource.resId || '';
        var qtiUrl = qParams.url || resUrl || '';
        var subject = qParams.subject || '';
        var gradeLevel = qParams.grade || '';
        if (qParams.title) quizState.title = qParams.title;
        quizState.testId = testId;
        // Compute the robust lesson ID used for PowerPath AND progress persistence
        quizState.quizLessonId = resource.componentResId || resource.resId || (lessonData && lessonData.lessonSourcedId) || testId || '';
        apState.subject = _apSubjectKey(subject) || _apSubjectKey(quizState.title);

        var userId = localStorage.getItem('alphalearn_userId') || localStorage.getItem('alphalearn_sourcedId') || '';

        // ── 1. PowerPath adaptive flow ──
        if (userId && (testId || qtiUrl)) {
            try {
                // Use the quiz resource's componentResId as the PowerPath lesson ID
                // PowerPath needs format like "USHI23-l48-r104178-v1", not "USHI23-l48-v1"
                var startResp = await fetch('/api/quiz-session?action=start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ studentId: userId, testId: testId, lessonId: quizState.quizLessonId, subject: subject, grade: gradeLevel }),
                });
                var startData = await startResp.json();
                if (startData.debug) console.log('[Quiz] start debug:', JSON.stringify(startData.debug));
                if (startData.attemptId || startData.id) {
                    quizState.attemptId = startData.attemptId || startData.id;
                    // ── Restore progress NOW that attemptId is set (reliable key) ──
                    _restoreQuizProgress();
                    // Use server hints as fallback if restore found nothing
                    if (quizState.total === 0 && startData.hasExistingProgress) {
                        quizState.questionNum = startData.answeredCount || 0;
                        quizState.total = startData.answeredCount || 0;
                        if (startData.score != null) quizState.ppScore = Math.max(0, Math.min(100, startData.score));
                    }
                    await loadNextQuestion();
                    return;
                }
            } catch(e) { console.warn('PowerPath start failed:', e.message); }
        }

        // ── 2. QTI content fetch ──
        if (qtiUrl || testId) {
            var loaded = await loadAllQTIQuestions(qtiUrl, testId, subject, gradeLevel);
            if (loaded) return;
        }

        // ── 3. Fallback: show message ──
        removeQuizLoader();
        quizArea.innerHTML = '<div class="lesson-placeholder"><div class="ph-icon"><i class="fa-solid fa-clipboard-question"></i></div><p>No quiz questions available</p><span class="sub">This quiz has no questions yet.</span></div>';
        showNavAfterQuiz(false);
    }

    /* ── PowerPath adaptive: one question at a time ────────── */
    async function loadNextQuestion() {
        if (!quizState.attemptId) return;
        // Keep the initial loading spinner for the first question; show inline loading for subsequent ones
        if (quizState.questionNum > 0) {
            quizArea.innerHTML = '<div class="loading-msg"><i class="fa-solid fa-spinner fa-spin" style="font-size:1.2rem;display:block;margin-bottom:10px;"></i>Loading question...</div>';
        }
        try {
            var skipParam = quizState.answeredIds.length > 0 ? '&skipIds=' + encodeURIComponent(quizState.answeredIds.join(',')) : '';
            var resp = await fetch('/api/quiz-session?action=next&attemptId=' + encodeURIComponent(quizState.attemptId) + skipParam);
            var data = await resp.json();

            // Handle errors separately — don't treat API failures as quiz completion
            if (data.error && !data.complete) {
                console.warn('[Quiz] Error loading next question:', data.error);
                removeQuizLoader();
                quizArea.innerHTML = '<div class="loading-msg"><i class="fa-solid fa-triangle-exclamation" style="font-size:1.5rem;display:block;margin-bottom:10px;color:#D97706;"></i>Error loading question<br><span style="font-size:0.82rem;color:#9ca3af;">' + esc(data.error) + '</span><br><button class="quiz-btn quiz-btn-primary" style="margin-top:14px;" onclick="loadNextQuestion()"><i class="fa-solid fa-rotate-right"></i> Retry</button></div>';
                return;
            }

            // Only treat as complete if the API explicitly says so
            if (data.complete || data.finished) {
                // If there are questions in the bank (answered or not), show results
                if (data.totalQuestions > 0 || quizState.total > 0) {
                    // Populate local stats from server if we don't have local progress
                    if (quizState.total === 0 && data.answeredQuestions > 0) {
                        quizState.total = data.answeredQuestions;
                        quizState.questionNum = data.answeredQuestions;
                    }
                    showQuizResults();
                    return;
                }
                // Stale/corrupt attempt — auto-retry once with reset
                if (!quizState._retried) {
                    console.warn('[Quiz] 0 questions — retrying with reset');
                    quizState._retried = true;
                    var userId = localStorage.getItem('alphalearn_userId') || localStorage.getItem('alphalearn_sourcedId') || '';
                    try {
                        var retryResp = await fetch('/api/quiz-session?action=start', {
                            method: 'POST', headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({ studentId: userId, testId: quizState.testId, lessonId: quizState.quizLessonId, retry: true }),
                        });
                        var retryData = await retryResp.json();
                        if (retryData.debug) console.log('[Quiz] retry debug:', JSON.stringify(retryData.debug));
                        if (retryData.attemptId || retryData.id) {
                            quizState.attemptId = retryData.attemptId || retryData.id;
                            quizState.ppScore = 0; quizState.correct = 0; quizState.total = 0;
                            quizState.streak = 0; quizState.questionNum = 0; quizState.answeredIds = [];
                            await loadNextQuestion();
                            return;
                        }
                    } catch(e) { console.warn('[Quiz] Retry failed:', e.message); }
                }
                // Truly no questions in the bank
                console.warn('[Quiz] No questions in bank — totalQuestions:', data.totalQuestions);
                removeQuizLoader();
                quizArea.innerHTML = '<div class="loading-msg"><i class="fa-solid fa-circle-info" style="font-size:1.5rem;display:block;margin-bottom:10px;color:var(--color-primary);"></i>No questions available<br><button class="quiz-btn quiz-btn-secondary" style="margin-top:14px;" onclick="goBackToCourse()"><i class="fa-solid fa-arrow-left"></i> Back to Course</button></div>';
                return;
            }

            quizState.currentQuestion = data;
            quizState.questionNum++;
            quizState.selectedChoice = null;
            quizState.answered = false;
            renderQuestion(data);
        } catch(e) {
            removeQuizLoader();
            quizArea.innerHTML = '<div class="loading-msg">Error loading question: ' + esc(e.message) + '</div>';
        }
    }

    /* ── Remove full-page loader once quiz UI is ready ────── */
    function removeQuizLoader() {
        var el = document.getElementById('quiz-fullpage-loader');
        if (el) el.remove();
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

    /* ── Render a question ─────────────────────────────────── */
    function renderQuestion(q) {
        removeQuizLoader();
        // Hide bottom nav — exit button goes inline with submit
        var nav = document.getElementById('lesson-nav');
        nav.classList.add('hidden');

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
            // Simple progress for reading quizzes (no PowerPath score)
            var progressPct = quizState.totalQuestions > 0 ? Math.round((quizState.questionNum / quizState.totalQuestions) * 100) : 0;
            html += '<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">' +
                '<div style="font-size:0.95rem;font-weight:700;flex:1;color:#111827;">' + esc(quizState.title) + '</div>' +
                '<div style="display:flex;align-items:center;gap:6px;font-size:0.82rem;font-weight:700;color:var(--color-primary);background:var(--color-primary-light);padding:5px 12px;border-radius:16px;">' +
                    '<i class="fa-solid fa-book-open" style="font-size:0.72rem;"></i> Question ' + quizState.questionNum + ' of ' + quizState.totalQuestions +
                '</div></div>';
            html += '<div style="height:5px;background:#E8ECF1;border-radius:3px;margin-bottom:18px;overflow:hidden;">' +
                '<div style="height:100%;background:var(--color-primary);border-radius:3px;transition:width 0.4s ease;width:' + progressPct + '%;"></div></div>';
        } else {
            var accuracy = quizState.total > 0 ? Math.round((quizState.correct / quizState.total) * 100) : 0;
            var ppScore = Math.max(0, Math.min(100, quizState.ppScore));
            var circ = 2 * Math.PI * 18;
            var dash = circ - (ppScore / 100) * circ;

            html += '<div class="pp-scoreboard">' +
                '<div class="pp-ring"><svg width="44" height="44" viewBox="0 0 44 44">' +
                    '<circle class="pp-ring-bg" cx="22" cy="22" r="18"/>' +
                    '<circle class="pp-ring-fill" cx="22" cy="22" r="18" stroke-dasharray="' + circ.toFixed(1) + '" stroke-dashoffset="' + dash.toFixed(1) + '"/>' +
                '</svg><div class="pp-ring-text">' + ppScore + '</div></div>' +
                '<div><div class="pp-label">PowerPath</div><div class="pp-score-text">' + ppScore + ' / 100</div></div>' +
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

        // Expand layout when split view is needed
        var lessonPage = document.querySelector('.lesson-page');
        if (lessonPage) {
            if (hasStimulus || promptImages) {
                lessonPage.classList.add('wide-mode');
            } else {
                lessonPage.classList.remove('wide-mode');
            }
        }

        // Build question + choices HTML (reused in both layouts)
        var questionHtml = '<div class="question-card">';
        var coToggleHtml = (!isFRQ && choices.length > 0) ? '<div class="crossout-toggle' + (quizState.crossOutMode ? ' active' : '') + '" onclick="toggleCrossOut()" title="Eliminate answers">ABC' + (quizState.crossOutMode ? '<div class="strike-line"></div>' : '') + '</div>' : '';
        var reportFlagHtml = quizState.reportingEnabled ? '<button class="report-flag" onclick="openReportModal()" title="Report this question"><i class="fa-solid fa-flag"></i></button>' : '';
        questionHtml += '<div class="q-tools-row"><div class="question-num">Question ' + quizState.questionNum + (isFRQ ? ' — Free Response' : '') + '</div>' + reportFlagHtml + coToggleHtml + '</div>';
        questionHtml += '<div class="question-text">' + (prompt || 'Loading question...') + '</div>';

        if (isFRQ) {
            questionHtml += '<textarea id="frq-response" rows="' + expectedLines + '" placeholder="Type your response here..." ' +
                'style="width:100%;padding:12px;border:2px solid var(--color-border);border-radius:10px;font-size:0.93rem;font-family:inherit;line-height:1.7;resize:vertical;outline:none;box-sizing:border-box;" ' +
                'oninput="document.getElementById(\'quiz-submit\').disabled=!this.value.trim()"></textarea>';
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
                questionHtml += '<div class="choice' + crossedCls + '" data-id="' + esc(cId) + '" onclick="selectAnswer(this,\'' + esc(cId) + '\')">' +
                    '<div class="choice-letter">' + (letters[i] || i) + '</div>' +
                    '<div class="choice-text">' + (cText || 'Option ' + (letters[i]||i)) + '</div>' +
                    '<button class="crossout-btn" onclick="event.stopPropagation();crossOutChoice(this.parentElement,\'' + esc(cId) + '\')" title="Cross out"><i class="fa-solid fa-xmark"></i></button>' +
                '</div>';
            }
            questionHtml += '</div>';
        }

        questionHtml += '<div class="feedback" id="feedback"></div>';
        questionHtml += '</div>';
        questionHtml += '<div class="quiz-actions"><button class="quiz-btn quiz-btn-secondary" onclick="goBackToCourse()"><i class="fa-solid fa-arrow-left"></i> Exit</button><button class="quiz-btn quiz-btn-primary" id="quiz-submit" onclick="submitQuizAnswer()" disabled><i class="fa-solid fa-check"></i> Submit</button></div>';

        if (hasStimulus) {
            // Build stimulus content — accumulated for reading quizzes
            var stimContent = '';
            if (quizState.isReadingQuiz && quizState.accumulatedStimuli.length > 0) {
                for (var si = 0; si < quizState.accumulatedStimuli.length; si++) {
                    if (si > 0) stimContent += '<hr style="border:none;border-top:2px dashed #E8ECF1;margin:20px 0;">';
                    stimContent += quizState.accumulatedStimuli[si];
                }
            } else {
                stimContent = stimulus;
            }
            // Split layout: article left, questions right
            html += '<div class="pp-split-layout">';
            html += '<div class="pp-split-left">' + stimContent + '</div>';
            html += '<div class="pp-split-right">' + questionHtml + '</div>';
            html += '</div>';
        } else if (promptImages) {
            // Image split layout — image left, question right (like articles)
            html += '<div class="pp-split-layout">';
            html += '<div class="pp-split-left" style="display:flex;align-items:center;justify-content:center;">' + promptImages + '</div>';
            html += '<div class="pp-split-right">' + questionHtml + '</div>';
            html += '</div>';
        } else {
            // Normal stacked layout (no stimulus)
            html += questionHtml;
        }

        quizArea.innerHTML = html;
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
        document.getElementById('quiz-submit').disabled = false;
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
                document.getElementById('quiz-submit').disabled = true;
            }
        }
    }

    /* ── Submit answer ─────────────────────────────────────── */
    async function submitQuizAnswer() {
        var frqEl = document.getElementById('frq-response');
        if (frqEl && !quizState.selectedChoice) quizState.selectedChoice = frqEl.value.trim();
        if (!quizState.selectedChoice || quizState.answered) return;
        quizState.answered = true;
        quizState.total++;

        // Track this question as answered locally (survives reload)
        var answeredQId = String((quizState.currentQuestion && (quizState.currentQuestion.id || quizState.currentQuestion.questionId)) || '');
        if (answeredQId && quizState.answeredIds.indexOf(answeredQId) === -1) {
            quizState.answeredIds.push(answeredQId);
        }

        var btn = document.getElementById('quiz-submit');
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Checking...';

        var isCorrect = false, feedback = '';
        var apiProvidedXp = false;

        // PowerPath adaptive submit
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
                if (data.xpEarned || data.xp) {
                    quizState.xpEarned += (data.xpEarned || data.xp);
                    apiProvidedXp = true;
                }
            } catch(e) {}
        }
        // Static quiz: check locally
        else if (quizState.staticQuestions) {
            var sq = quizState.staticQuestions[quizState.staticIdx];
            if (sq) {
                if (sq.isFRQ) {
                    isCorrect = quizState.selectedChoice.length >= 30;
                } else {
                    isCorrect = quizState.selectedChoice === sq.correctId;
                    feedback = (sq.feedbackMap || {})[quizState.selectedChoice] || '';
                }
            }
        }

        // Score
        var pointsChange = 0;
        if (isCorrect) {
            quizState.correct++;
            quizState.streak++;
            var mult = quizState.streak <= 3 ? 1 : Math.min(3.5, 1 + (quizState.streak - 3) * 0.75);
            pointsChange = Math.round(5 * mult);
            quizState.ppScore = Math.min(100, quizState.ppScore + pointsChange);
            // Only add local XP if the API didn't already provide it (avoid double-counting)
            if (!apiProvidedXp) quizState.xpEarned += 1;
        } else {
            quizState.streak = 0;
            pointsChange = -4;
            quizState.ppScore = Math.max(0, quizState.ppScore + pointsChange);
        }

        // Use real PowerPath score from API if available (overrides synthetic calculation)
        if (typeof data !== 'undefined' && data && typeof data.powerpathScore === 'number') {
            quizState.ppScore = data.powerpathScore;
        }

        // Persist progress to localStorage
        _saveQuizProgress();

        // Show feedback
        var fb = document.getElementById('feedback');
        if (fb) {
            fb.className = 'feedback ' + (isCorrect ? 'correct' : 'incorrect');
            var streakText = isCorrect && quizState.streak > 3 ? ' <span style="font-size:0.82rem;">🔥 ' + quizState.streak + ' streak</span>' : '';
            fb.innerHTML = (isCorrect ? '<strong><i class="fa-solid fa-check-circle"></i> Correct! +' + pointsChange + '</strong>' + streakText : '<strong><i class="fa-solid fa-times-circle"></i> Incorrect ' + pointsChange + '</strong>') +
                (feedback ? '<p style="margin-top:6px;">' + feedback + '</p>' : '');
        }

        // Highlight choices
        document.querySelectorAll('.choice').forEach(function(c) {
            if (c.dataset.id === quizState.selectedChoice) c.classList.add(isCorrect ? 'correct' : 'incorrect');
        });

        // FRQ feedback
        if (frqEl) { frqEl.disabled = true; frqEl.style.opacity = '0.7'; }

        // Update scoreboard
        updateScoreboard();

        // Next button — reading quizzes don't end on PP score
        if (!quizState.isReadingQuiz && quizState.ppScore >= 100) {
            btn.innerHTML = '<i class="fa-solid fa-trophy"></i> PowerPath 100 — Complete!';
            btn.disabled = false;
            btn.onclick = function() { showQuizResults(); };
        } else if (quizState.staticQuestions && quizState.staticIdx + 1 >= quizState.staticQuestions.length) {
            btn.innerHTML = '<i class="fa-solid fa-flag-checkered"></i> See Results';
            btn.disabled = false;
            btn.onclick = function() { showQuizResults(); };
        } else {
            btn.innerHTML = '<i class="fa-solid fa-arrow-right"></i> Next Question';
            btn.disabled = false;
            btn.onclick = function() {
                quizState.selectedChoice = null;
                quizState.answered = false;
                if (quizState.staticQuestions) {
                    quizState.staticIdx++;
                    showStaticQuestion();
                } else {
                    loadNextQuestion();
                }
            };
        }

        // (AI review now triggers immediately on report submission)
    }

    function updateScoreboard() {
        var ppScore = Math.max(0, Math.min(100, quizState.ppScore));
        var accuracy = quizState.total > 0 ? Math.round((quizState.correct / quizState.total) * 100) : 0;
        var circ = 2 * Math.PI * 18;
        var dash = circ - (ppScore / 100) * circ;
        var sb = document.querySelector('.pp-scoreboard');
        if (!sb) return;
        var fill = sb.querySelector('.pp-ring-fill');
        if (fill) fill.setAttribute('stroke-dashoffset', dash.toFixed(1));
        var ringText = sb.querySelector('.pp-ring-text');
        if (ringText) ringText.textContent = ppScore;
        var vals = sb.querySelectorAll('.pp-stat-value');
        if (vals[0]) vals[0].textContent = quizState.total;
        if (vals[1]) vals[1].textContent = accuracy + '%';
        var scoreText = sb.querySelector('.pp-score-text');
        if (scoreText) scoreText.textContent = ppScore + ' / 100';
    }

    /* ── Quiz results (inline) ─────────────────────────────── */
    async function showQuizResults() {
        // Collapse wide mode for results view
        var lessonPage = document.querySelector('.lesson-page');
        if (lessonPage) lessonPage.classList.remove('wide-mode');

        // Clear saved progress — quiz is complete
        _clearQuizProgress();

        quizState.finished = true;
        var pct = quizState.total > 0 ? Math.round((quizState.correct / quizState.total) * 100) : 0;
        // Completion-based: quiz is "passed" when the student finishes it
        // Accuracy does NOT gate progression — only completion matters
        var passed = quizState.finished;
        // XP requires 80%+ accuracy
        if (pct < 80) quizState.xpEarned = 0;

        console.log('[Quiz] Results — ppScore:', quizState.ppScore, 'accuracy:', pct + '%', 'passed:', passed, 'total:', quizState.total);

        // ═══ Show a loading state while we finalize ═══
        if (!quizArea) quizArea = document.getElementById('quiz-area');
        if (quizArea && passed) {
            quizArea.innerHTML = '<div class="result-card">' +
                '<div class="result-emoji"><i class="fa-solid fa-spinner fa-spin" style="font-size:2rem;color:var(--color-primary);"></i></div>' +
                '<div class="result-label">Saving progress...</div>' +
            '</div>';
        }

        // Disable nav buttons until sync completes
        var btnContinue = document.getElementById('btn-continue');
        var btnBack = document.getElementById('btn-back');
        if (btnContinue) { btnContinue.disabled = true; }
        if (btnBack) { btnBack.disabled = true; }

        // ═══ SYNC FIRST — before any DOM writes that could fail ═══
        // Mark lesson complete locally and signal course page — ONLY when truly passed
        if (passed) {
            var lessonId = lessonData.title || '';
            if (lessonId) localStorage.setItem('completed_' + lessonId, 'true');
        }
        // Always signal course.html to refresh (even on fail — updates frontier)
        sessionStorage.setItem('al_progress_changed', 'true');

        // Sync with TimeBack Platform — AWAIT so we get real XP from PowerPath
        // before rendering and before the user can navigate away
        await syncQuizCompletion(pct, passed);

        // ═══ Now render the results UI with authoritative XP ═══
        if (!quizArea) quizArea = document.getElementById('quiz-area');
        var resultColor = '#16A34A';
        var incorrect = quizState.total - quizState.correct;
        var resultHtml = '<div class="result-card">' +
            '<div class="result-emoji">🎉</div>' +
            '<div class="result-score" style="color:' + resultColor + ';">' + pct + '%</div>' +
            '<div class="result-label">Lesson Complete!</div>' +
            '<div class="result-summary">' + quizState.correct + ' of ' + quizState.total + ' correct' + (incorrect > 0 ? ' &middot; ' + incorrect + ' missed' : '') + '</div>' +
            (quizState.xpEarned > 0 ? '<div class="xp-badge"><i class="fa-solid fa-bolt"></i> ' + quizState.xpEarned + ' XP earned</div>' : '<div class="xp-badge xp-badge-muted"><i class="fa-solid fa-bolt"></i> Need 80%+ to earn XP</div>') +
            '<div class="result-complete"><i class="fa-solid fa-circle-check"></i> Lesson complete</div>' +
        '</div>';

        if (quizArea) {
            quizArea.innerHTML = resultHtml;
        }

        // Re-enable nav buttons now that sync is done
        if (btnContinue) { btnContinue.disabled = false; }
        if (btnBack) { btnBack.disabled = false; }

        // Show nav with finish/retry
        showNavAfterQuiz(passed);
    }

    function showNavAfterQuiz(passed) {
        var nav = document.getElementById('lesson-nav');
        nav.classList.remove('hidden');
        var btnContinue = document.getElementById('btn-continue');
        btnContinue.style.display = '';
        if (passed || quizState.finished) {
            btnContinue.innerHTML = 'Finish Lesson <i class="fa-solid fa-check"></i>';
            btnContinue.onclick = function() { goBackToCourse(); };
        } else {
            btnContinue.innerHTML = 'Continue <i class="fa-solid fa-arrow-right"></i>';
            btnContinue.onclick = function() { goBackToCourse(); };
        }
        var btnBack = document.getElementById('btn-back');
        btnBack.innerHTML = '<i class="fa-solid fa-arrow-left"></i> Back to Course';
        btnBack.onclick = function() { goBackToCourse(); };
    }

    /* ── QTI static questions (fallback) ───────────────────── */
    async function loadAllQTIQuestions(qtiUrl, testId, subject, gradeLevel) {
        try {
            var apiUrl = '/api/qti-item?';
            if (qtiUrl) apiUrl += 'url=' + encodeURIComponent(qtiUrl);
            else apiUrl += 'id=' + encodeURIComponent(testId) + '&type=assessment';
            if (subject) apiUrl += '&subject=' + encodeURIComponent(subject);
            if (gradeLevel) apiUrl += '&grade=' + encodeURIComponent(gradeLevel);
            if (quizState.title) apiUrl += '&title=' + encodeURIComponent(quizState.title);

            var resp = await fetch(apiUrl);
            var result = await resp.json();
            if (!result.success || !result.data) return false;
            var data = result.data;

            // Check for stimulus content (article displayed as quiz content)
            var stim = data['qti-assessment-stimulus'];
            if (stim) {
                var stimBody = stim['qti-stimulus-body'] || {};
                removeQuizLoader();
                quizArea.innerHTML = '<div style="padding:20px;"><h2 style="font-size:1.1rem;font-weight:700;margin-bottom:14px;">' + esc(data.title || quizState.title) + '</h2>' +
                    '<div class="stimulus-box" style="max-height:none;">' + renderNode(stimBody) + '</div></div>';
                showNavAfterQuiz(false);
                return true;
            }

            var questions = data.questions || [];
            if (questions.length === 0) return false;

            quizState.title = data.title || quizState.title;
            // Parse QTI questions into usable format
            quizState.staticQuestions = questions.map(function(q) {
                var qi = q['qti-assessment-item'] || (q.content && q.content['qti-assessment-item']) || q;
                var attrs = qi['_attributes'] || {};
                var body = qi['qti-item-body'] || {};
                var eti = body['qti-extended-text-interaction'];
                var ci = body['qti-choice-interaction'] || {};
                var isFRQ = !!eti && !ci['qti-simple-choice'];

                // Extract prompt
                var promptText = '';
                var sources = [ci['qti-prompt'], body['qti-prompt'], eti && eti['qti-prompt'], qi.prompt, qi.question];
                for (var ps = 0; ps < sources.length; ps++) {
                    var src = sources[ps];
                    if (!src) continue;
                    if (typeof src === 'string' && src.length > 3) { promptText = src; break; }
                    if (src.p) {
                        var pArr = Array.isArray(src.p) ? src.p : [src.p];
                        promptText = pArr.map(function(p) { return '<p>' + (typeof p === 'string' ? p : (p['_'] || renderNode(p))) + '</p>'; }).join('');
                        if (promptText) break;
                    }
                    if (typeof src === 'object') { var r = renderNode(src); if (r && r.length > 3) { promptText = r; break; } }
                }
                if (!promptText) promptText = qi.title || attrs.title || q.title || '';

                var sc = ci['qti-simple-choice'] || [];
                if (!Array.isArray(sc)) sc = [sc];
                var choices = isFRQ ? [] : sc.map(function(c, i) {
                    var ca = c['_attributes'] || {};
                    // Extract choice text, excluding any feedback elements
                    var t = '';
                    if (c.p) {
                        t = typeof c.p === 'string' ? c.p : (c.p['_'] || renderNode(c.p));
                    } else if (c.span && !c['qti-feedback-inline']) {
                        t = typeof c.span === 'string' ? c.span : renderNode(c.span);
                    } else {
                        // Build a clean copy without feedback keys
                        var clean = {};
                        for (var ck in c) {
                            if (ck.indexOf('feedback') === -1) clean[ck] = c[ck];
                        }
                        t = renderNode(clean);
                    }
                    return { id: ca.identifier || String(i), text: t };
                });

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

                var feedbackMap = {};
                if (!isFRQ) {
                    sc.forEach(function(c) {
                        var ca = c['_attributes'] || {};
                        var fb = c['qti-feedback-inline'] || {};
                        if (fb.span) feedbackMap[ca.identifier] = typeof fb.span === 'string' ? fb.span : renderNode(fb.span);
                    });
                }

                // Extract stimulus content (article/passage attached by backend)
                var stimulusHtml = '';
                var secStim = q['_sectionStimulus'] || qi['_sectionStimulus'] || null;
                if (secStim) {
                    var stimObj = secStim;
                    if (stimObj.content && stimObj.content['qti-assessment-stimulus']) stimObj = stimObj.content['qti-assessment-stimulus'];
                    else if (stimObj['qti-assessment-stimulus']) stimObj = stimObj['qti-assessment-stimulus'];
                    var stimContent = stimObj['qti-stimulus-body'] || stimObj.body || stimObj.content || stimObj;
                    if (typeof stimContent === 'string' && stimContent.length > 10) stimulusHtml = stimContent;
                    else if (typeof stimContent === 'object') stimulusHtml = renderNode(stimContent);
                    if (!stimulusHtml && secStim.rawXml) stimulusHtml = secStim.rawXml;
                    if (!stimulusHtml) stimulusHtml = renderNode(secStim);
                }

                return { prompt: promptText, choices: choices, correctId: correctId, feedbackMap: feedbackMap, isFRQ: isFRQ, expectedLines: 10, stimulus: stimulusHtml };
            });

            quizState.staticIdx = 0;

            // Detect reading quiz — only for Reading/ELA subject courses
            var _isReadingCourse = /^reading$|^ela$|^english\s*language\s*arts$/i.test((subject || '').trim());
            var hasAnyStimulus = quizState.staticQuestions.some(function(q) { return q.stimulus && q.stimulus.length > 10; });
            if (_isReadingCourse && hasAnyStimulus) {
                quizState.isReadingQuiz = true;
                quizState.totalQuestions = quizState.staticQuestions.length;
                quizState.accumulatedStimuli = [];
            }

            // AP exam UI for cumulative reviews, end-of-unit assessments, and MCQ tests
            // Excludes standalone "review" (e.g. Heimler's Review) which are just videos
            var titleLower = (quizState.title || '').toLowerCase();
            var isAPStyle = /cumulative\s*review|mcq|end.of.unit|unit\s*\d+\s*(mcq|frq|saq)?\s*test|final.test|exam|assessment|aps[\s:\-]/i.test(titleLower);

            if (isAPStyle) {
                quizState.answers = new Array(quizState.staticQuestions.length).fill(null);
                quizState.marked = new Array(quizState.staticQuestions.length).fill(false);
                startAPExam();
            } else {
                // Normal inline quiz (PowerPath style, one at a time)
                showStaticQuestion();
            }
            return true;
        } catch(e) {
            console.warn('QTI load failed:', e);
            return false;
        }
    }

    /* ==================================================================
       AP EXAM UI — full feature set
       ================================================================== */
    var apState = {
        crossOutMode: false,
        crossedOut: [],
        notes: [],
        notesOpen: false,
        calcOpen: false,
        refOpen: false,
        highlightMode: false,
        hlColor: 'yellow',
        subject: '',
    };

    // Subject detection helpers
    function _apSubjectKey(subj) {
        var s = (subj || '').toLowerCase();
        if (/physics/.test(s)) return 'physics';
        if (/chem/.test(s)) return 'chemistry';
        if (/bio/.test(s)) return 'biology';
        if (/stat/.test(s)) return 'statistics';
        if (/calc/.test(s)) return 'calculus';
        if (/precalc/.test(s)) return 'precalculus';
        if (/math/.test(s)) return 'math';
        if (/environ/.test(s)) return 'environmental';
        if (/computer/.test(s)) return 'cs';
        return '';
    }
    function _apHasCalc(key) {
        return ['physics','chemistry','biology','calculus','precalculus','math','environmental'].indexOf(key) >= 0;
    }
    function _apHasRef(key) {
        return ['physics','chemistry','biology','statistics','environmental','cs'].indexOf(key) >= 0;
    }
    function _apRefHTML(key) {
        if (key === 'physics') return '<h3>Constants</h3><table><tr><td>g</td><td>9.8 m/s\u00B2</td></tr><tr><td>G</td><td>6.674 \u00D7 10\u207B\u00B9\u00B9 N\u00B7m\u00B2/kg\u00B2</td></tr><tr><td>Speed of light (c)</td><td>3.0 \u00D7 10\u2078 m/s</td></tr><tr><td>Electron charge (e)</td><td>1.6 \u00D7 10\u207B\u00B9\u2079 C</td></tr><tr><td>1 atm</td><td>1.0 \u00D7 10\u2075 Pa</td></tr></table>' +
            '<h3>Kinematics</h3><table><tr><td>v = v\u2080 + at</td><td>x = x\u2080 + v\u2080t + \u00BDat\u00B2</td></tr><tr><td>v\u00B2 = v\u2080\u00B2 + 2a\u0394x</td><td>\u0394x = \u00BD(v + v\u2080)t</td></tr></table>' +
            '<h3>Forces &amp; Energy</h3><table><tr><td>F = ma</td><td>F\u2091 = mg</td></tr><tr><td>f = \u03BCN</td><td>F\u209B = -kx</td></tr><tr><td>KE = \u00BDmv\u00B2</td><td>PE = mgh</td></tr><tr><td>W = Fd cos\u03B8</td><td>P = W/t</td></tr></table>' +
            '<h3>Momentum &amp; Rotation</h3><table><tr><td>p = mv</td><td>J = F\u0394t = \u0394p</td></tr><tr><td>\u03C4 = rF sin\u03B8</td><td>L = I\u03C9</td></tr><tr><td>a\u1D04 = v\u00B2/r</td><td>F\u1D04 = mv\u00B2/r</td></tr></table>' +
            '<h3>Waves &amp; Fluids</h3><table><tr><td>v = f\u03BB</td><td>T = 1/f</td></tr><tr><td>T\u209B = 2\u03C0\u221A(m/k)</td><td>T\u209A = 2\u03C0\u221A(L/g)</td></tr><tr><td>P = F/A</td><td>\u03C1 = m/V</td></tr><tr><td>F\u2095 = \u03C1Vg</td><td>P = P\u2080 + \u03C1gh</td></tr></table>';
        if (key === 'chemistry') return '<h3>Atomic Structure</h3><table><tr><td>E = hf</td><td>c = f\u03BB</td></tr><tr><td>h = 6.626 \u00D7 10\u207B\u00B3\u2074 J\u00B7s</td><td>N\u2090 = 6.022 \u00D7 10\u00B2\u00B3</td></tr></table>' +
            '<h3>Gases</h3><table><tr><td>PV = nRT</td><td>R = 8.314 J/(mol\u00B7K)</td></tr><tr><td>P\u2081V\u2081/T\u2081 = P\u2082V\u2082/T\u2082</td><td>P\u209C = P\u2081 + P\u2082 + ...</td></tr><tr><td>KE = \u00BDmv\u00B2 = 3/2 kT</td><td>M = m/n</td></tr></table>' +
            '<h3>Equilibrium &amp; Acid-Base</h3><table><tr><td>K\u2091 = [products]/[reactants]</td><td>pH = -log[H\u207A]</td></tr><tr><td>pOH = -log[OH\u207B]</td><td>pH + pOH = 14</td></tr><tr><td>K\u2090 \u00D7 K\u2095 = K\u2092</td><td>Henderson-Hasselbalch: pH = pK\u2090 + log([A\u207B]/[HA])</td></tr></table>' +
            '<h3>Thermodynamics</h3><table><tr><td>q = mc\u0394T</td><td>\u0394G = \u0394H - T\u0394S</td></tr><tr><td>\u0394G\u00B0 = -RT ln K</td><td>E\u00B0\u1D04\u2091\u2097\u2097 = E\u00B0\u1D04\u2090\u209C\u2095 - E\u00B0\u2090\u2099\u2092\u209E\u2091</td></tr></table>';
        if (key === 'biology') return '<h3>Hardy-Weinberg</h3><table><tr><td>p + q = 1</td><td>p\u00B2 + 2pq + q\u00B2 = 1</td></tr></table>' +
            '<h3>Population Growth</h3><table><tr><td>Exponential</td><td>dN/dt = r\u2098\u2090\u2093N</td></tr><tr><td>Logistic</td><td>dN/dt = r\u2098\u2090\u2093N(K - N)/K</td></tr></table>' +
            '<h3>Energy &amp; Water</h3><table><tr><td>Gibbs Free Energy</td><td>\u0394G = \u0394H - T\u0394S</td></tr><tr><td>Water Potential</td><td>\u03A8 = \u03A8\u209A + \u03A8\u209B</td></tr><tr><td>Solute Potential</td><td>\u03A8\u209B = -iCRT</td></tr></table>' +
            '<h3>Statistics</h3><table><tr><td>Chi-Square</td><td>\u03C7\u00B2 = \u03A3(O - E)\u00B2/E</td></tr><tr><td>SA/V Ratio</td><td>Surface Area / Volume</td></tr></table>';
        if (key === 'statistics') return '<h3>Descriptive Statistics</h3><table><tr><td>Mean</td><td>x\u0304 = \u03A3x\u1D62/n</td></tr><tr><td>Std Dev</td><td>s = \u221A[\u03A3(x\u1D62 - x\u0304)\u00B2/(n-1)]</td></tr><tr><td>Regression</td><td>\u0177 = a + bx, b = r(s\u1D67/s\u2093)</td></tr></table>' +
            '<h3>Probability</h3><table><tr><td>Addition</td><td>P(A\u222AB) = P(A) + P(B) - P(A\u2229B)</td></tr><tr><td>Conditional</td><td>P(A|B) = P(A\u2229B)/P(B)</td></tr><tr><td>Binomial</td><td>P(X=x) = C(n,x)p\u02E3(1-p)\u207F\u207B\u02E3</td></tr><tr><td>\u03BC = np</td><td>\u03C3 = \u221A[np(1-p)]</td></tr></table>' +
            '<h3>Inference</h3><table><tr><td>Confidence Interval</td><td>statistic \u00B1 (critical value)(SE)</td></tr><tr><td>Test Statistic</td><td>(statistic - parameter)/SE</td></tr><tr><td>Chi-Square</td><td>\u03C7\u00B2 = \u03A3(O-E)\u00B2/E</td></tr><tr><td>SE (proportion)</td><td>\u221A[p\u0302(1-p\u0302)/n]</td></tr><tr><td>SE (mean)</td><td>s/\u221An</td></tr></table>';
        if (key === 'environmental') return '<h3>Earth Systems</h3><table><tr><td>Earth radius</td><td>6,371 km</td></tr><tr><td>Atmosphere</td><td>78% N\u2082, 21% O\u2082, 1% other</td></tr><tr><td>Water distribution</td><td>97.5% saltwater, 2.5% freshwater</td></tr></table>' +
            '<h3>Energy &amp; Ecology</h3><table><tr><td>10% rule</td><td>~10% energy transfers between trophic levels</td></tr><tr><td>LD50</td><td>Lethal dose for 50% of test population</td></tr><tr><td>Population growth</td><td>r = (birth rate - death rate)/1000</td></tr><tr><td>Rule of 70</td><td>Doubling time = 70/growth rate(%)</td></tr></table>';
        if (key === 'cs') return '<h3>Java Quick Reference</h3><table><tr><td>String methods</td><td>length(), substring(), indexOf(), equals(), compareTo()</td></tr><tr><td>Math methods</td><td>abs(), pow(), sqrt(), random()</td></tr><tr><td>ArrayList</td><td>add(), get(), set(), remove(), size()</td></tr><tr><td>Array</td><td>arr.length, Arrays.sort()</td></tr></table>';
        return '';
    }

    function startAPExam() {
        // Hide lesson page — AP exam takes over with fullscreen overlay
        var lp = document.querySelector('.lesson-page');
        if (lp) lp.style.display = 'none';
        var n = quizState.staticQuestions.length;
        apState.crossedOut = [];
        apState.notes = [];
        for (var i = 0; i < n; i++) { apState.crossedOut.push({}); apState.notes.push(''); }
        apState.crossOutMode = false;
        apState.notesOpen = false;
        apState.calcOpen = false;
        apState.refOpen = false;
        apState.highlightMode = false;
        // Subject is stored from startInlineQuiz
        renderAPQuestion();
    }

    function renderAPQuestion() {
        removeQuizLoader();
        var idx = quizState.staticIdx;
        var q = quizState.staticQuestions[idx];
        var totalQ = quizState.staticQuestions.length;
        var passage = quizState.cachedPassage || '';
        if (q.stimulus) passage = q.stimulus;
        var hasPassage = passage && passage.length > 10;
        var letters = 'ABCDEFGHIJ';
        var isMarked = quizState.marked[idx];
        var old = document.getElementById('ap-overlay');
        if (old) old.remove();
        var overlay = document.createElement('div');
        overlay.id = 'ap-overlay';
        overlay.className = 'ap-overlay';
        var html = '';

        // ── Header with all tools ──
        html += '<div class="ap-header">' +
            '<div class="ap-header-title">' + esc(quizState.title) + '</div>' +
            '<div class="ap-tools">' +
                '<div style="position:relative;display:inline-flex;">' +
                    '<button class="ap-tool-btn' + (apState.highlightMode ? ' active' : '') + '" onclick="apToggleHighlight()" title="Highlight text"><i class="fa-solid fa-highlighter"></i><span>Highlight</span></button>' +
                    '<div class="ap-hl-picker' + (apState.highlightMode ? ' open' : '') + '" id="ap-hl-picker">' +
                        '<div class="ap-hl-swatch sw-yellow' + (apState.hlColor === 'yellow' ? ' active' : '') + '" onclick="apSetHlColor(\'yellow\')"></div>' +
                        '<div class="ap-hl-swatch sw-blue' + (apState.hlColor === 'blue' ? ' active' : '') + '" onclick="apSetHlColor(\'blue\')"></div>' +
                        '<div class="ap-hl-swatch sw-pink' + (apState.hlColor === 'pink' ? ' active' : '') + '" onclick="apSetHlColor(\'pink\')"></div>' +
                    '</div>' +
                '</div>' +
                '<div class="ap-tool-sep"></div>' +
                '<div class="ap-more-wrap">' +
                    '<button class="ap-tool-btn" onclick="apToggleMore()" title="More tools"><i class="fa-solid fa-ellipsis-vertical"></i><span>More</span></button>' +
                    '<div class="ap-more-dropdown" id="ap-more-dd">' +
                        '<button class="ap-more-item" onclick="apAddNote();apCloseMore()"><i class="fa-solid fa-sticky-note"></i>Sticky Note</button>' +
                        (_apHasCalc(apState.subject) ? '<button class="ap-more-item" onclick="apToggleCalc();apCloseMore()"><i class="fa-solid fa-calculator"></i>Calculator</button>' : '') +
                        (_apHasRef(apState.subject) ? '<button class="ap-more-item" onclick="apToggleRef();apCloseMore()"><i class="fa-solid fa-book-open"></i>Reference Sheet</button>' : '') +
                        '<button class="ap-more-item" onclick="apShowReview();apCloseMore()"><i class="fa-solid fa-list-check"></i>Review Answers</button>' +
                        '<button class="ap-more-item" onclick="exitAPExam()"><i class="fa-solid fa-right-from-bracket"></i>Exit Exam</button>' +
                    '</div>' +
                '</div>' +
            '</div></div>';

        html += '<div class="ap-divider"></div>';

        // ── Body ──
        html += '<div class="ap-body' + (hasPassage ? '' : ' no-passage') + '">';
        if (hasPassage) {
            html += '<div class="ap-passage" id="ap-passage">' + passage + '</div>';
        }
        html += '<div class="ap-question-panel" id="ap-qpanel">';

        // Question tools
        var abcActive = apState.crossOutMode;
        html += '<div class="ap-q-tools">' +
            '<div class="ap-q-num">' + (idx + 1) + '</div>' +
            '<button class="ap-q-bookmark' + (isMarked ? ' marked' : '') + '" onclick="toggleAPMark()">' +
                '<i class="fa-' + (isMarked ? 'solid' : 'regular') + ' fa-bookmark"></i> Mark for Review' +
            '</button>' +
            '<div class="ap-q-abc' + (abcActive ? ' active' : '') + '" onclick="apToggleCrossOut()" title="Eliminate answers">ABC' + (abcActive ? '<div class="abc-strike"></div>' : '') + '</div>' +
        '</div>';

        html += '<div class="ap-q-prompt">' + (q.prompt || '') + '</div>';

        // Choices
        if (q.choices && q.choices.length > 0) {
            html += '<div class="ap-choices' + (apState.crossOutMode ? ' crossout-mode' : '') + '">';
            var co = apState.crossedOut[idx] || {};
            for (var ci = 0; ci < q.choices.length; ci++) {
                var c = q.choices[ci];
                var sel = quizState.answers[idx] === c.id ? ' selected' : '';
                var crossed = co[c.id] ? ' crossed-out' : '';
                html += '<div class="ap-choice' + sel + crossed + '" data-id="' + esc(c.id) + '" onclick="apClickChoice(this,\'' + esc(c.id) + '\')">' +
                    '<div class="ap-choice-letter">' + (letters[ci] || ci) + '</div>' +
                    '<div class="ap-choice-text">' + (c.text || '') + '</div>' +
                    '<button class="ap-crossout-btn" onclick="event.stopPropagation();apCrossOutOne(this.parentElement,\'' + esc(c.id) + '\')" title="Cross out"><i class="fa-solid fa-xmark"></i></button>' +
                '</div>';
            }
            html += '</div>';
        } else if (q.isFRQ) {
            var saved = quizState.answers[idx] || '';
            html += '<textarea id="ap-frq" rows="' + (q.expectedLines || 10) + '" placeholder="Type your response here..." ' +
                'style="width:100%;padding:14px;border:1.5px solid #ddd;border-radius:8px;font-size:0.95rem;font-family:inherit;line-height:1.7;resize:vertical;outline:none;box-sizing:border-box;" ' +
                'oninput="quizState.answers[quizState.staticIdx]=this.value">' + esc(saved) + '</textarea>';
        }

        // Sticky note (draggable)
        html += '<div class="ap-notes-panel' + (apState.notesOpen ? ' open' : '') + '" id="ap-notes">' +
            '<div class="ap-notes-header" onmousedown="apStartDrag(event,\'ap-notes\')"><span>Q' + (idx+1) + ' Notes</span><button onclick="apState.notesOpen=false;document.getElementById(\'ap-notes\').classList.remove(\'open\')">&times;</button></div>' +
            '<div class="ap-notes-body"><textarea placeholder="Write your notes here..." oninput="apState.notes[' + idx + ']=this.value">' + esc(apState.notes[idx] || '') + '</textarea></div></div>';

        html += '</div></div>'; // question-panel, body

        html += '<div class="ap-footer-divider"></div>';

        // ── Footer ──
        html += '<div class="ap-footer">' +
            '<button class="ap-nav-btn ap-nav-prev" onclick="apNav(-1)"' + (idx === 0 ? ' disabled' : '') + '>Back</button>' +
            '<div style="flex:1;display:flex;justify-content:center;position:relative;">' +
                '<button class="ap-q-nav" onclick="toggleAPNav()" id="ap-q-nav-btn">Question ' + (idx + 1) + ' of ' + totalQ + ' <i class="fa-solid fa-chevron-up" id="ap-nav-chevron"></i></button>' +
                '<div class="ap-nav-dropdown" id="ap-nav-dropdown">' +
                    '<div class="ap-nav-dropdown-header">Questions</div>' +
                    '<div class="ap-nav-grid">';
        for (var di = 0; di < totalQ; di++) {
            var dc = 'ap-nav-item';
            if (quizState.answers[di] !== null) dc += ' answered';
            if (di === idx) dc += ' current';
            if (quizState.marked[di]) dc += ' marked';
            html += '<div class="' + dc + '" onclick="apGoTo(' + di + ')">' + (di + 1) + '</div>';
        }
        html += '</div>' +
            '<button onclick="apShowReview()" style="display:block;width:100%;margin-top:12px;padding:9px;border:none;border-radius:8px;background:#1a237e;color:#fff;font-size:0.82rem;font-weight:600;cursor:pointer;font-family:var(--font);">Review All Answers</button>' +
            '</div></div>' +
            '<button class="ap-nav-btn ap-nav-next" onclick="apNav(1)">' + (idx === totalQ - 1 ? 'Review' : 'Next') + '</button>' +
        '</div>';

        // Calculator panel
        html += '<div class="ap-calc-panel' + (apState.calcOpen ? ' open' : '') + '" id="ap-calc">' +
            '<div class="ap-calc-header" onmousedown="apStartDrag(event,\'ap-calc\')"><span>Graphing Calculator</span><button onclick="apToggleCalc()">&times;</button></div>' +
            '<iframe src="https://www.desmos.com/calculator" loading="lazy"></iframe></div>';

        // Reference panel (subject-specific)
        var refContent = _apRefHTML(apState.subject);
        if (refContent) {
            html += '<div class="ap-ref-panel' + (apState.refOpen ? ' open' : '') + '" id="ap-ref">' +
                '<div class="ap-ref-header"><span>Reference Sheet</span><button onclick="apToggleRef()">&times;</button></div>' +
                '<div class="ap-ref-body">' + refContent + '</div></div>';
        }

        overlay.innerHTML = html;
        document.body.appendChild(overlay);
    }

    // ── Choice handling (select or cross-out) ──
    function apClickChoice(el, choiceId) {
        var idx = quizState.staticIdx;
        if (apState.crossOutMode) {
            // Toggle cross-out
            if (!apState.crossedOut[idx]) apState.crossedOut[idx] = {};
            if (apState.crossedOut[idx][choiceId]) {
                delete apState.crossedOut[idx][choiceId];
                el.classList.remove('crossed-out');
            } else {
                apState.crossedOut[idx][choiceId] = true;
                el.classList.add('crossed-out');
            }
        } else {
            // Select answer
            quizState.answers[idx] = choiceId;
            var overlay = document.getElementById('ap-overlay');
            if (!overlay) return;
            overlay.querySelectorAll('.ap-choice').forEach(function(c) { c.classList.remove('selected'); });
            el.classList.add('selected');
            // Update nav grid item to show answered
            var navItems = overlay.querySelectorAll('.ap-nav-item');
            if (navItems[idx]) navItems[idx].classList.add('answered');
        }
    }

    function apToggleCrossOut() {
        apState.crossOutMode = !apState.crossOutMode;
        renderAPQuestion();
    }

    function apCrossOutOne(el, choiceId) {
        var idx = quizState.staticIdx;
        if (!apState.crossedOut[idx]) apState.crossedOut[idx] = {};
        if (apState.crossedOut[idx][choiceId]) {
            delete apState.crossedOut[idx][choiceId];
            el.classList.remove('crossed-out');
        } else {
            apState.crossedOut[idx][choiceId] = true;
            el.classList.add('crossed-out');
        }
    }

    // ── Navigation ──
    function apNav(dir) {
        var next = quizState.staticIdx + dir;
        if (next < 0) return;
        if (next >= quizState.staticQuestions.length) { apShowReview(); return; }
        quizState.staticIdx = next;
        renderAPQuestion();
    }
    function apGoTo(idx) {
        if (idx < 0 || idx >= quizState.staticQuestions.length) return;
        quizState.staticIdx = idx;
        renderAPQuestion();
    }
    function toggleAPMark() { quizState.marked[quizState.staticIdx] = !quizState.marked[quizState.staticIdx]; renderAPQuestion(); }
    function toggleAPNav() {
        var dd = document.getElementById('ap-nav-dropdown');
        var chev = document.getElementById('ap-nav-chevron');
        if (!dd) return;
        var isOpen = dd.classList.toggle('open');
        if (chev) chev.style.transform = isOpen ? 'rotate(180deg)' : '';
    }

    // ── More dropdown ──
    function apToggleMore() {
        var dd = document.getElementById('ap-more-dd');
        if (dd) dd.classList.toggle('open');
    }
    function apCloseMore() {
        var dd = document.getElementById('ap-more-dd');
        if (dd) dd.classList.remove('open');
    }
    // Close more dropdown when clicking outside
    document.addEventListener('click', function(e) {
        var dd = document.getElementById('ap-more-dd');
        if (dd && dd.classList.contains('open') && !e.target.closest('.ap-more-wrap')) dd.classList.remove('open');
    });

    // ── Highlight tool ──
    function apToggleHighlight() {
        apState.highlightMode = !apState.highlightMode;
        // Update button state without re-rendering (preserves highlights)
        var overlay = document.getElementById('ap-overlay');
        if (overlay) {
            var btn = overlay.querySelector('.ap-tool-btn');
            if (btn) btn.classList.toggle('active', apState.highlightMode);
            var picker = document.getElementById('ap-hl-picker');
            if (picker) picker.classList.toggle('open', apState.highlightMode);
        }
        if (apState.highlightMode) {
            document.addEventListener('mouseup', apDoHighlight);
        } else {
            document.removeEventListener('mouseup', apDoHighlight);
        }
    }
    function apSetHlColor(color) {
        apState.hlColor = color;
        // Update swatch active states
        var picker = document.getElementById('ap-hl-picker');
        if (picker) {
            picker.querySelectorAll('.ap-hl-swatch').forEach(function(s) { s.classList.remove('active'); });
            var active = picker.querySelector('.sw-' + color);
            if (active) active.classList.add('active');
        }
    }
    function apDoHighlight(e) {
        if (!apState.highlightMode) return;
        // Click on existing highlight to remove it
        if (e && e.target && e.target.closest && e.target.closest('mark.ap-hl')) {
            var mark = e.target.closest('mark.ap-hl');
            var text = document.createTextNode(mark.textContent);
            mark.parentNode.replaceChild(text, mark);
            return;
        }
        var sel = window.getSelection();
        if (!sel || sel.isCollapsed || !sel.rangeCount) return;
        var range = sel.getRangeAt(0);
        var container = range.commonAncestorContainer;
        var el = container.nodeType === 3 ? container.parentElement : container;
        if (!el.closest || (!el.closest('.ap-passage') && !el.closest('.ap-q-prompt'))) return;
        var mark = document.createElement('mark');
        mark.className = 'ap-hl hl-' + (apState.hlColor || 'yellow');
        try { range.surroundContents(mark); } catch(e) {}
        sel.removeAllRanges();
    }

    // ── Notes ──
    function apAddNote() {
        apState.notesOpen = !apState.notesOpen;
        var panel = document.getElementById('ap-notes');
        if (panel) panel.classList.toggle('open', apState.notesOpen);
    }

    // ── Calculator ──
    function apToggleCalc() {
        apState.calcOpen = !apState.calcOpen;
        var panel = document.getElementById('ap-calc');
        if (panel) panel.classList.toggle('open', apState.calcOpen);
    }

    // ── Reference sheet ──
    function apToggleRef() {
        apState.refOpen = !apState.refOpen;
        var panel = document.getElementById('ap-ref');
        if (panel) panel.classList.toggle('open', apState.refOpen);
    }

    // ── Draggable panels ──
    function apStartDrag(e, panelId) {
        var panel = document.getElementById(panelId);
        if (!panel) return;
        var startX = e.clientX, startY = e.clientY;
        var rect = panel.getBoundingClientRect();
        var origLeft = rect.left, origTop = rect.top;
        panel.style.position = 'fixed';
        function onMove(ev) {
            panel.style.left = (origLeft + ev.clientX - startX) + 'px';
            panel.style.top = (origTop + ev.clientY - startY) + 'px';
            panel.style.right = 'auto';
        }
        function onUp() { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); }
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    }

    // ── Review page ──
    function apShowReview() {
        var old = document.getElementById('ap-overlay');
        if (old) old.remove();
        var overlay = document.createElement('div');
        overlay.id = 'ap-overlay';
        overlay.className = 'ap-overlay';
        var totalQ = quizState.staticQuestions.length;
        var answered = 0, markedCount = 0, unanswered = 0;
        for (var i = 0; i < totalQ; i++) {
            if (quizState.answers[i] !== null) answered++;
            else unanswered++;
            if (quizState.marked[i]) markedCount++;
        }
        var currentIdx = quizState.staticIdx;

        var html = '<div class="ap-header"><div class="ap-header-title">' + esc(quizState.title) + ' - Review</div>' +
            '<div class="ap-tools"><button class="ap-tool-btn" onclick="exitAPExam()"><i class="fa-solid fa-right-from-bracket"></i><span>Exit</span></button></div></div>' +
            '<div class="ap-divider"></div>' +
            '<div class="ap-review">' +
            '<h2>Review Your Answers</h2>' +
            '<p class="ap-review-summary">' + answered + ' of ' + totalQ + ' answered' +
                (unanswered > 0 ? ' &middot; <span style="color:#DC2626;font-weight:600;">' + unanswered + ' unanswered</span>' : '') +
                (markedCount > 0 ? ' &middot; <span style="color:#D97706;font-weight:600;">' + markedCount + ' flagged</span>' : '') +
            '</p>';

        // Legend
        html += '<div class="ap-review-legend">' +
            '<div class="ap-review-legend-item"><div class="ap-review-legend-swatch answered"></div>Answered</div>' +
            '<div class="ap-review-legend-item"><div class="ap-review-legend-swatch unanswered"></div>Unanswered</div>' +
            '<div class="ap-review-legend-item"><div class="ap-review-legend-swatch marked"></div>Flagged</div>' +
            '<div class="ap-review-legend-item"><div class="ap-review-legend-swatch current-swatch"></div>Current</div>' +
        '</div>';

        // Grid of question boxes
        html += '<div class="ap-review-grid">';
        for (var ri = 0; ri < totalQ; ri++) {
            var ans = quizState.answers[ri];
            var cls = ans !== null ? 'answered' : 'unanswered';
            if (ri === currentIdx) cls += ' current';
            html += '<div class="ap-review-item ' + cls + '" onclick="apGoTo(' + ri + ')">' +
                (ri === currentIdx ? '<div class="ap-review-pin"><i class="fa-solid fa-location-dot"></i></div>' : '') +
                (quizState.marked[ri] ? '<div class="ap-review-flag"><i class="fa-solid fa-flag"></i></div>' : '') +
                (ri + 1) +
            '</div>';
        }
        html += '</div>';

        // Submit area
        var allDone = answered === totalQ;
        html += '<div style="text-align:center;margin-top:8px;">';
        if (allDone) {
            html += '<button class="ap-nav-btn ap-nav-next" onclick="apFinalSubmit()" style="padding:12px 40px;font-size:0.95rem;">Submit Test</button>';
        } else {
            html += '<button class="ap-nav-btn ap-nav-next" onclick="apFinalSubmit()" style="padding:12px 40px;font-size:0.95rem;opacity:0.7;">Submit Anyway</button>';
        }
        html += '<br><button class="ap-nav-btn ap-nav-prev" onclick="renderAPQuestion()" style="margin-top:12px;">Return to Questions</button>';
        html += '</div></div>';

        overlay.innerHTML = html;
        document.body.appendChild(overlay);
    }

    // ── Submit (from header) — shows confirmation ──
    function submitAPExam() {
        var totalQ = quizState.staticQuestions.length;
        var answered = 0;
        for (var i = 0; i < totalQ; i++) { if (quizState.answers[i] !== null) answered++; }
        if (answered < totalQ) {
            // Show confirmation modal
            var modal = document.createElement('div');
            modal.className = 'ap-modal-overlay';
            modal.id = 'ap-confirm-modal';
            modal.innerHTML = '<div class="ap-modal"><h3>Submit Test?</h3>' +
                '<p>You have <strong>' + (totalQ - answered) + '</strong> unanswered question' + (totalQ - answered > 1 ? 's' : '') + '. Are you sure you want to submit?</p>' +
                '<div class="ap-modal-btns">' +
                    '<button onclick="document.getElementById(\'ap-confirm-modal\').remove()" style="background:#f0f0f0;color:#555;">Go Back</button>' +
                    '<button onclick="document.getElementById(\'ap-confirm-modal\').remove();apShowReview()" style="background:#1a237e;color:#fff;">Review Answers</button>' +
                '</div></div>';
            document.body.appendChild(modal);
        } else {
            apShowReview();
        }
    }

    // ── Final submit (scores and closes) ──
    function apFinalSubmit() {
        var ol = document.getElementById('ap-overlay');
        if (ol) ol.remove();
        var lp = document.querySelector('.lesson-page');
        if (lp) lp.style.display = '';
        var correct = 0, total = quizState.staticQuestions.length;
        for (var i = 0; i < total; i++) {
            var q = quizState.staticQuestions[i];
            var ans = quizState.answers[i];
            if (q.isFRQ) { if (ans && ans.length >= 30) correct++; }
            else { if (ans === q.correctId) correct++; }
        }
        quizState.correct = correct;
        quizState.total = total;
        quizState.xpEarned = correct;
        showQuizResults();
    }

    function exitAPExam() {
        var ol = document.getElementById('ap-overlay');
        if (ol) ol.remove();
        var lp = document.querySelector('.lesson-page');
        if (lp) lp.style.display = '';
        document.removeEventListener('mouseup', apDoHighlight);
        goBackToCourse();
    }

    // Keep old function for PowerPath flow compatibility
    function showStaticQuestion() {
        if (quizState.staticIdx >= quizState.staticQuestions.length) { showQuizResults(); return; }
        var q = quizState.staticQuestions[quizState.staticIdx];
        quizState.currentQuestion = q;
        quizState.selectedChoice = null;
        quizState.answered = false;
        quizState.questionNum = quizState.staticIdx + 1;
        renderQuestion({ prompt: q.prompt, choices: q.choices, isFRQ: q.isFRQ, expectedLines: q.expectedLines, stimulus: q.stimulus, correctId: q.correctId || '' });
    }

    /* ==================================================================
       NAVIGATION
       ================================================================== */
    async function goNext() {
        // Mark current step (video/article) as completed locally
        markStepComplete(currentStep);

        // Sync article/video completion to PowerPath + OneRoster APIs
        var step = steps[currentStep];
        if (step && (step.type === 'Video' || step.type === 'Article')) {
            syncStepCompletion(step);
        }
        if (currentStep < steps.length - 1) {
            showStep(currentStep + 1);
            window.scrollTo({ top: 0, behavior: 'smooth' });
        } else {
            // Last step — save to localStorage and go back
            saveLessonToLocalStorage();
            // If no quiz in this lesson, sync completion to server APIs BEFORE navigating
            var hasQuiz = steps.some(function(s) { return s.type === 'Quiz'; });
            if (!hasQuiz) {
                // Show a brief "Saving..." state and wait for sync
                var btn = document.getElementById('btn-continue');
                if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving...'; }
                await syncNonQuizCompletion();
                // Small delay to ensure localStorage is written
                await new Promise(function(r) { setTimeout(r, 300); });
            }
            goBackToCourse();
        }
    }

    function goBack() {
        if (currentStep > 0) {
            showStep(currentStep - 1);
            window.scrollTo({ top: 0, behavior: 'smooth' });
        } else {
            goBackToCourse();
        }
    }

    function goBackToCourse() {
        // Always signal course page to refresh when navigating back
        sessionStorage.setItem('al_progress_changed', 'true');
        if (window.history.length > 1) window.history.back();
        else window.location.href = '/dashboard';
    }

    function markStepComplete(idx) {
        if (idx < 0 || idx >= steps.length) return;
        var step = steps[idx];
        if (step.type === 'Quiz') return; // Quizzes handle their own completion via syncQuizCompletion

        // Mark this individual resource as viewed/completed
        var resId = step.resource.resId || step.resource.id || '';
        var resTitle = step.resource.title || '';
        if (resId) localStorage.setItem('completed_' + resId, 'true');
        if (resTitle) localStorage.setItem('completed_' + resTitle, 'true');

        // Set the _rN key that course.html uses for per-resource tracking
        if (lessonData.completionKey) {
            localStorage.setItem(lessonData.completionKey + '_r' + idx, 'true');
        }

        console.log('[Complete] Marked step', idx, step.type, ':', resTitle || resId);

        // Signal course page to refresh (but do NOT mark the whole lesson complete
        // — that only happens when ALL steps are done + quiz passed)
        sessionStorage.setItem('al_progress_changed', 'true');
    }

    function saveLessonToLocalStorage() {
        // Clear saved step — lesson is complete, don't resume mid-lesson
        _clearSavedStep();

        // Signal course.html to reload and pick up new completion data
        sessionStorage.setItem('al_progress_changed', 'true');

        // Use the exact completion key from course.html (most important)
        if (lessonData.completionKey) {
            localStorage.setItem(lessonData.completionKey, 'true');
            console.log('[Complete] Saved completionKey:', lessonData.completionKey);
        } else {
            console.warn('[Complete] No completionKey in lessonData!');
        }

        // Also save with all possible key patterns as fallback
        var title = lessonData.title || '';
        var lessonId = lessonData.lessonId || lessonData.id || '';
        var ppLessonId = lessonData.ppLessonId || lessonData.lessonSourcedId || '';
        console.log('[Complete] Saving keys — title:', title, 'lessonId:', lessonId, 'ppLessonId:', ppLessonId, 'resources:', (lessonData.resources||[]).length);
        if (title) localStorage.setItem('completed_' + title, 'true');
        if (lessonId) localStorage.setItem('completed_' + lessonId, 'true');
        if (ppLessonId) localStorage.setItem('completed_' + ppLessonId, 'true');

        // Also mark each resource
        var resources = lessonData.resources || [];
        for (var i = 0; i < resources.length; i++) {
            var r = resources[i];
            if (r.resId) localStorage.setItem('completed_' + r.resId, 'true');
            if (r.title) localStorage.setItem('completed_' + r.title, 'true');
        }
    }

    /* ── Sync non-quiz lesson completion (video/article only) to server ── */
    async function syncNonQuizCompletion() {
        if (!syncState.userId) {
            console.warn('[Sync] No userId — cannot sync non-quiz completion');
            return;
        }
        console.log('[Sync] Syncing non-quiz lesson completion (video/article)');

        // Set minimal quiz state so the existing sync functions work
        quizState.xpEarned = 0;  // Start at 0 — PowerPath will provide real XP
        quizState.total = 1;
        quizState.correct = 1;

        // 1. PowerPath: finalize lesson FIRST to get real XP
        var ppXp = 0;
        try {
            var ppResult = await markLessonComplete(100);
            if (ppResult && ppResult.xpEarned > 0) {
                ppXp = ppResult.xpEarned;
                quizState.xpEarned = ppXp;
                console.log('[Sync] Non-quiz: PowerPath XP:', ppXp);
            }
        } catch(e) {
            console.warn('[Sync] Non-quiz finalize failed:', e.message);
        }

        // 2. Report XP via activity record (only if XP > 0)
        if (quizState.xpEarned > 0) {
            var email = localStorage.getItem('alphalearn_email') || '';
            var courseCode = lessonData.courseSourcedId || '';
            var activityId = lessonData.lessonSourcedId || lessonData.title || '';
            try {
                var resp = await fetch('/api/activity-record', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        userId: syncState.userId, email: email,
                        activityId: activityId, activityName: lessonData.title || 'Lesson',
                        courseCode: courseCode, xpEarned: quizState.xpEarned,
                        totalQuestions: 1, correctQuestions: 1, pctComplete: 100,
                    }),
                });
                var d = await resp.json();
                console.log('[Sync] Activity-record response:', JSON.stringify(d));
            } catch(e) {
                console.warn('[Sync] Activity-record failed:', e.message);
            }
        }

        // 3. Save XP locally
        if (quizState.xpEarned > 0) {
            var enrollId = lessonData.enrollmentId || '';
            var existingXP = parseInt(localStorage.getItem('local_xp_' + enrollId) || '0', 10);
            localStorage.setItem('local_xp_' + enrollId, String(existingXP + quizState.xpEarned));
        }
    }

    /* ── Utilities ──────────────────────────────────────────── */
    function toEmbedUrl(url) {
        if (!url) return '';
        var yt = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/);
        if (yt) return 'https://www.youtube.com/embed/' + yt[1];
        var vm = url.match(/vimeo\.com\/(\d+)/);
        if (vm) return 'https://player.vimeo.com/video/' + vm[1];
        if (url.includes('/embed') || url.includes('player.')) return url;
        return url;
    }

    function esc(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function showError(msg) {
        document.getElementById('lesson-title-text').textContent = 'Lesson';
        document.getElementById('lesson-content').innerHTML =
            '<div class="lesson-placeholder"><div class="ph-icon"><i class="fa-solid fa-circle-exclamation" style="color:#DC2626;"></i></div><p>' + msg + '</p>' +
            '<p class="sub"><a href="/dashboard" style="color:var(--color-primary);font-weight:600;">Back to Dashboard</a></p></div>';
        document.getElementById('btn-continue').style.display = 'none';
    }

    function fetchArticle(url, resId, contentEl) {
        var proxyUrl = '/api/article-proxy?';
        var params = [];
        if (url) params.push('url=' + encodeURIComponent(url));
        if (resId) params.push('id=' + encodeURIComponent(resId));
        proxyUrl += params.join('&');

        fetch(proxyUrl)
            .then(function(resp) {
                if (!resp.ok) {
                    return resp.text().then(function(body) {
                        var detail = '';
                        try { detail = JSON.parse(body).error || ''; } catch(e) {}
                        throw new Error(detail || 'Failed to load article (status ' + resp.status + ')');
                    });
                }
                var ct = resp.headers.get('content-type') || '';
                if (ct.includes('application/json')) {
                    return resp.json().then(function(data) { return data.html || data.body || data.content || data.text || ''; });
                }
                return resp.text();
            })
            .then(function(html) {
                if (html && html.trim().length > 0) {
                    contentEl.innerHTML = '<div class="article-wrap">' + html + '</div>';
                    // Cache for AP exam passage panel
                    quizState.cachedPassage = html;
                } else {
                    contentEl.innerHTML = '<div class="lesson-placeholder"><div class="ph-icon"><i class="fa-solid fa-file-lines"></i></div><p>Article content is empty.</p></div>';
                }
            })
            .catch(function(err) {
                console.warn('[Lesson] Article fetch failed:', err);
                contentEl.innerHTML = '<div class="lesson-placeholder"><div class="ph-icon"><i class="fa-solid fa-file-lines"></i></div><p>Article</p><p class="sub">Could not load article content.</p></div>';
            });
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

    async function submitQuizReport() {
        if (!_selectedReportReason) return;
        var userId = localStorage.getItem('alphalearn_userId') || localStorage.getItem('alphalearn_sourcedId') || '';
        if (!userId || !quizState.currentQuestion) return;

        var btn = document.getElementById('report-submit-btn');
        btn.disabled = true;
        btn.textContent = 'Submitting...';

        var q = quizState.currentQuestion;
        var articleContent = '';
        if (quizState.accumulatedStimuli.length > 0) {
            articleContent = quizState.accumulatedStimuli.join('\n---\n');
        } else if (quizState.cachedPassage) {
            articleContent = quizState.cachedPassage;
        } else if (q.stimulus || q.passage || q.reading) {
            articleContent = q.stimulus || q.passage || q.reading || '';
            if (typeof articleContent === 'object') articleContent = JSON.stringify(articleContent);
        }

        // Get video URL from lesson data
        var videoUrl = '';
        if (lessonData && lessonData.resources) {
            for (var i = 0; i < lessonData.resources.length; i++) {
                if (lessonData.resources[i].label === 'Video') { videoUrl = lessonData.resources[i].url || lessonData.resources[i].pillUrl || ''; break; }
            }
        }

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
            lessonTitle: (lessonData && lessonData.title) || quizState.title || '',
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

    document.getElementById('report-modal').addEventListener('click', function(e) { if (e.target === this) closeReportModal(); });

    document.addEventListener('DOMContentLoaded', init);
    