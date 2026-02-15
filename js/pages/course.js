    /* ====================================================================
       Course Detail Page — Units → Lessons → Resources (Video/Article/Quiz)
       ==================================================================== */

    /* ── Refresh on back/forward navigation ────────────────────
       When the user completes a lesson or quiz and hits "Back to Course",
       the browser may serve this page from the bfcache (back-forward cache).
       In that case DOMContentLoaded does NOT re-fire, so progress is stale.
       We listen for `pageshow` with `event.persisted` and also check a
       sessionStorage flag set by quiz/lesson pages on completion. Either
       condition triggers a full reload so the progress UI is rebuilt. */
    window.addEventListener('pageshow', function(event) {
        if (event.persisted || sessionStorage.getItem('al_progress_changed') === 'true') {
            sessionStorage.removeItem('al_progress_changed');
            window.location.reload();
        }
    });

    // Also handle visibility change (e.g. tab switching or mobile backgrounding)
    document.addEventListener('visibilitychange', function() {
        if (document.visibilityState === 'visible' && sessionStorage.getItem('al_progress_changed') === 'true') {
            sessionStorage.removeItem('al_progress_changed');
            window.location.reload();
        }
    });

    function esc(str) {
        if (str === null || str === undefined) return '';
        if (typeof str !== 'string') str = String(str);
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /* ── Expand / Collapse helpers ─────────────────────────────── */
    function toggleUnit(id) {
        var timeline = document.getElementById(id);
        var chev = document.getElementById(id + '-chev');
        var card = document.getElementById(id + '-card');
        if (!timeline) return;
        timeline.classList.toggle('open');
        if (chev) chev.classList.toggle('open');
        if (card) card.classList.toggle('expanded');
    }

    // Store lesson data for navigation to lesson viewer
    window._lessonData = {};

    function openLesson(key) {
        var data = window._lessonData[key];
        if (!data) return;
        sessionStorage.setItem('al_lesson_data', JSON.stringify(data));
        window.location.href = '/lesson?title=' + encodeURIComponent(data.title);
    }

    /* ── Resource-type helpers ──────────────────────────────────── */
    function resIcon(type) {
        var t = (type || '').toLowerCase();
        if (t === 'video') return 'fa-play';
        if (t.includes('assess') || t === 'quiz' || t === 'test' || t === 'exam' || t === 'frq') return 'fa-clipboard-question';
        return 'fa-file-lines';
    }

    function resLabel(type, url) {
        var t = (type || '').toLowerCase();
        if (t === 'video') return 'Video';
        if (t === 'assessment' || t === 'quiz' || t === 'test' || t === 'exam' || t === 'frq') return 'Quiz';
        if (t.includes('assessment') && !t.includes('stimulus') && !t.includes('reading')) return 'Quiz';
        if (url && url.includes('stimuli')) return 'Article';
        if (url && (url.includes('/assessment') || url.includes('/quiz'))) return 'Quiz';
        return 'Article';
    }

    function resClass(label) {
        if (label === 'Video') return 'video';
        if (label === 'Quiz') return 'quiz';
        return 'reading';
    }

    function pctBadgeClass(pct) {
        if (pct >= 80) return 'green';
        if (pct >= 50) return 'amber';
        if (pct > 0) return 'red';
        return 'gray';
    }

    /* ── SVG progress ring helper ──────────────────────────────── */
    function progressRing(pct) {
        var r = 16, circ = 2 * Math.PI * r;
        var offset = circ * (1 - pct / 100);
        var color = pct >= 80 ? '#16A34A' : pct >= 50 ? '#D97706' : pct > 0 ? '#DC2626' : '#E8ECF1';
        return '<div class="unit-ring">' +
            '<svg width="40" height="40"><circle cx="20" cy="20" r="' + r + '" fill="none" stroke="#E8ECF1" stroke-width="3"></circle>' +
            '<circle cx="20" cy="20" r="' + r + '" fill="none" stroke="' + color + '" stroke-width="3" stroke-dasharray="' + circ.toFixed(1) + '" stroke-dashoffset="' + offset.toFixed(1) + '" stroke-linecap="round"></circle></svg>' +
            '<span class="ring-pct">' + pct + '%</span></div>';
    }

    /* ── Main ──────────────────────────────────────────────────── */
    document.addEventListener('DOMContentLoaded', async function() {
        var params = new URLSearchParams(window.location.search);
        var courseTitle = params.get('title') || 'Course';
        var courseId = params.get('id') || '';
        var userId = localStorage.getItem('alphalearn_userId') || localStorage.getItem('alphalearn_sourcedId') || '';

        // Admin detection (real role, before debug override)
        var userRole = (localStorage.getItem('alphalearn_role') || '').toLowerCase();
        var userEmail = (localStorage.getItem('alphalearn_email') || '').toLowerCase();
        var realIsAdmin = userRole.includes('admin') || userRole.includes('administrator')
            || userEmail === 'twsevenyw@gmail.com' || userEmail === 'austin.way@alpha.school';
        var isAdmin = realIsAdmin;

        // Staging bypass: unlock all lessons in staging mode
        if (localStorage.getItem('alphalearn_staging')) isAdmin = true;

        // Debug override: force student view to test locks
        var debugMode = localStorage.getItem('al_debug_mode');
        if (debugMode === 'student' && realIsAdmin) isAdmin = false;

        // Show debug toggle for real admins
        if (realIsAdmin) {
            var isStudentMode = (debugMode === 'student');
            var dbgBtn = document.createElement('button');
            dbgBtn.className = 'debug-toggle ' + (isStudentMode ? 'is-student' : 'is-admin');
            dbgBtn.innerHTML = isStudentMode
                ? '<i class="fa-solid fa-lock"></i> Student View (Locked)'
                : '<i class="fa-solid fa-shield-halved"></i> Admin View (Unlocked)';
            dbgBtn.onclick = function() {
                localStorage.setItem('al_debug_mode', isStudentMode ? '' : 'student');
                location.reload();
            };
            document.body.appendChild(dbgBtn);
        }

        document.title = 'AlphaLearn - ' + courseTitle;

        // Show header with title
        document.getElementById('course-header').innerHTML =
            '<h1>' + esc(courseTitle) + '</h1>' +
            '<div class="meta"><span class="meta-item"><i class="fa-solid fa-spinner fa-spin"></i> Loading course data...</span></div>';

        if (!userId) {
            document.getElementById('course-content').innerHTML =
                '<div style="text-align:center;padding:40px;color:var(--color-text-muted);"><i class="fa-solid fa-circle-exclamation" style="font-size:2.5rem;display:block;margin-bottom:12px;opacity:0.4;"></i><p>No user ID found. Please <a href="/login" style="color:var(--color-primary);">sign in</a> first.</p></div>';
            return;
        }

        // ── Fetch enrollment ───────────────────────────────────────
        var enrollment = null;
        try {
            var resp = await fetch('/api/enrollments?userId=' + encodeURIComponent(userId));
            var data = await resp.json();
            var enrollments = data.data || data.enrollments || data.courses || (Array.isArray(data) ? data : []);
            for (var i = 0; i < enrollments.length; i++) {
                var e = enrollments[i];
                var eId = e.id || e.sourcedId || '';
                var eTitle = (e.course || {}).title || e.title || '';
                if ((courseId && eId === courseId) || eTitle === courseTitle) { enrollment = e; break; }
            }
        } catch(err) { console.warn('[Course] Failed to fetch enrollments:', err.message); }

        if (!enrollment) {
            document.getElementById('course-header').innerHTML =
                '<h1>' + esc(courseTitle) + '</h1>' +
                '<div class="meta"><span class="meta-item"><i class="fa-solid fa-info-circle"></i> Enrollment data not available</span></div>';
            document.getElementById('course-content').innerHTML =
                '<div style="text-align:center;padding:40px;color:var(--color-text-muted);"><i class="fa-solid fa-book" style="font-size:2.5rem;display:block;margin-bottom:12px;opacity:0.4;"></i><p>This course is part of your AlphaLearn curriculum. Course content will appear here as it becomes available.</p></div>';
            return;
        }

        // ── Parse enrollment ───────────────────────────────────────
        var course = enrollment.course || {};
        var meta = Object.assign({}, course.metadata || {}, enrollment.metadata || {});
        var goals = meta.goals || {};
        var metrics = meta.metrics || {};
        var subjects = (course.subjects || []).join(', ') || '';
        var xpEarned = enrollment.xpEarned || 0;
        // Add locally tracked XP (earned in this browser, may not be synced to API yet)
        var enrollId = enrollment.id || enrollment.sourcedId || '';
        var localXP = parseInt(localStorage.getItem('local_xp_' + enrollId) || '0', 10);
        xpEarned = Math.max(xpEarned, xpEarned + localXP);
        var totalXp = metrics.totalXp || goals.dailyXp || 0;
        var dailyGoal = goals.dailyXp || 0;
        var totalLessons = metrics.totalLessons || 0;
        var isAlphaRead = meta.isAlphaRead || false;
        var isAlphaWrite = meta.isAlphaWrite || meta.isAlphawrite || false;
        var endDate = enrollment.endDate || '';

        // ── Render Header ──────────────────────────────────────────
        var metaItems = [];
        if (subjects) metaItems.push('<span class="meta-item"><i class="fa-solid fa-book"></i> ' + esc(subjects) + '</span>');
        if (endDate) metaItems.push('<span class="meta-item"><i class="fa-solid fa-calendar"></i> Ends ' + esc(endDate.split('T')[0]) + '</span>');
        if (totalLessons) metaItems.push('<span class="meta-item"><i class="fa-solid fa-list-check"></i> ' + totalLessons + ' lessons</span>');

        document.getElementById('course-header').innerHTML =
            '<h1>' + esc(course.title || courseTitle) + '</h1>' +
            '<div class="meta">' + (metaItems.length ? metaItems.join('') : '<span class="meta-item"><i class="fa-solid fa-graduation-cap"></i> AlphaLearn Course</span>') + '</div>';

        // ── Build content sections ─────────────────────────────────
        var contentHTML = '';

        // Loading placeholder for course content
        contentHTML += '<div id="content-section">' +
            '<div style="text-align:center;padding:24px;color:var(--color-text-muted);">' +
                '<div class="loading-spinner" style="margin:0 auto 8px;width:28px;height:28px;"></div>' +
                'Loading course content...</div></div>';

        document.getElementById('course-content').innerHTML = contentHTML;

        // ── Fetch course content ───────────────────────────────────
        try {
            var enrollmentId = enrollment.id || enrollment.sourcedId || '';
            var courseSourcedId = course.sourcedId || course.id || '';

            var contentUrl = '/api/course-content?';
            if (courseSourcedId) contentUrl += 'courseId=' + encodeURIComponent(courseSourcedId);
            if (enrollmentId) contentUrl += '&enrollmentId=' + encodeURIComponent(enrollmentId);
            if (userId) contentUrl += '&userId=' + encodeURIComponent(userId);

            var contentResp = await fetch(contentUrl);
            var contentData = contentResp.ok ? await contentResp.json() : {};
            var contentEl = document.getElementById('content-section');
            if (!contentEl) return;

            var html = '';

            // Helper: check if a progress entry represents actual completion (for display)
            // For articles/videos: 'fully graded' means the resource was consumed
            // Used for resource-level display (checkmarks) only — NOT for locking
            function _isComplete(p) {
                if (!p) return false;
                if (p.scoreStatus === 'fully graded') return true;
                if (p.textScore === 'Completed') return true;
                return false;
            }
            // PowerPath 100: quiz is complete when score reaches 100,
            // or fallback: any fully graded quiz with a positive score (PowerPath finalized it)
            function _isQuizComplete(p) {
                if (!p) return false;
                if (p.scoreStatus === 'fully graded' && typeof p.score === 'number' && p.score >= 100) return true;
                if (p.scoreStatus === 'fully graded' && typeof p.score === 'number' && p.score > 0) return true;
                return false;
            }
            // PowerPath 100: mastered when score reaches 100,
            // or fallback: any fully graded quiz with a positive score
            function _isMastered(p) {
                if (!p) return false;
                if (p.scoreStatus === 'fully graded' && typeof p.score === 'number' && p.score >= 100) return true;
                if (p.scoreStatus === 'fully graded' && typeof p.score === 'number' && p.score > 0) return true;
                return false;
            }

            // ── Build progress lookup ──────────────────────────────
            var progressByTitle = {};
            var progressById = {};  // Also index progress by resource sourcedId
            var assessmentLineItemByResId = {};  // Map resource IDs to PowerPath assessmentLineItemSourcedId
            var cp = contentData.courseProgress;
            if (cp && cp.lineItems) {
                for (var pi = 0; pi < cp.lineItems.length; pi++) {
                    var pItem = cp.lineItems[pi];
                    var pTitle = (pItem.title || '').trim();
                    
                    // Store the PowerPath assessmentLineItemSourcedId for this resource
                    var resSourcedId = pItem.courseComponentResourceSourcedId || '';
                    var aliSourcedId = pItem.assessmentLineItemSourcedId || '';
                    if (resSourcedId && aliSourcedId) {
                        assessmentLineItemByResId[resSourcedId] = aliSourcedId;
                    }
                    // Also map by title for fallback
                    if (pTitle && aliSourcedId) {
                        assessmentLineItemByResId[pTitle] = aliSourcedId;
                    }
                    
                    if (pItem.results && pItem.results.length > 0) {
                        var r = pItem.results[0];
                        var progEntry = {
                            scoreStatus: r.scoreStatus || '',
                            textScore: r.textScore || '',
                            score: r.score,
                            scorePercentile: r.scorePercentile,
                            scoreDate: r.scoreDate || '',
                        };
                        if (pTitle) {
                            progressByTitle[pTitle] = progEntry;
                        }
                        // Also index by resource sourcedId for more reliable matching
                        if (resSourcedId) {
                            progressById[resSourcedId] = progEntry;
                            // Progress IDs have format "USHI23-l44-r155857-bank-v1" but lesson plan
                            // resource IDs omit the lesson number: "USHI23-r155857-bank-v1"
                            // Index by the short form too so componentResource lookups work
                            var shortResId = resSourcedId.replace(/-l\d+-/, '-');
                            if (shortResId !== resSourcedId) {
                                progressById[shortResId] = progEntry;
                            }
                        }
                        // And by the lineItem sourcedId/id
                        var pItemId = pItem.sourcedId || pItem.id || '';
                        if (pItemId) {
                            progressById[pItemId] = progEntry;
                        }
                        // Also index by assessmentLineItemSourcedId so all resources sharing the same
                        // lineItem can be found (videos/articles often share one lineItem per lesson)
                        if (aliSourcedId) {
                            progressById[aliSourcedId] = progEntry;
                        }
                    }
                    // Even if no results yet, map the assessmentLineItemSourcedId to resSourcedId
                    // so we can look up other resources that share this lineItem
                    if (aliSourcedId && resSourcedId) {
                        // Store a mapping from ALI to all resources that use it
                        if (!progressById['_ali_' + aliSourcedId]) {
                            progressById['_ali_' + aliSourcedId] = [];
                        }
                        progressById['_ali_' + aliSourcedId].push(resSourcedId);
                    }
                }
            }

            // Count total completed (API data only — no localStorage)
            var totalCompleted = Object.keys(progressByTitle).length;

            // ── Parse lesson plan ──────────────────────────────────
            var plan = contentData.lessonPlan;
            var innerPlan = (plan && plan.lessonPlan) ? plan.lessonPlan : plan;
            var lessonPlanId = (innerPlan && innerPlan.id) ? innerPlan.id : '';  // PowerPath lessonPlan ID
            var units = (innerPlan && innerPlan.subComponents) ? innerPlan.subComponents : [];
            units.sort(function(a, b) { return (a.sortOrder || '').localeCompare(b.sortOrder || ''); });

            var courseSubject = (course.subjects || [])[0] || '';
            var courseGrade = ((course.grades || [])[0] || '').replace(/[^0-9]/g, '');
            var quizExtra = '';
            if (courseSubject) quizExtra += '&subject=' + encodeURIComponent(courseSubject);
            if (courseGrade) quizExtra += '&grade=' + encodeURIComponent(courseGrade);

            if (units.length > 0) {
                // ── Pre-process: normalize lessons, build flat list, count activities ──
                var processedUnits = [];
                var globalLessonList = [];
                var grandTotalAct = 0, grandDoneAct = 0;

                for (var pu = 0; pu < units.length; pu++) {
                    var pMod = units[pu];
                    var pLessons = (pMod.subComponents || []).slice();
                    pLessons.sort(function(a, b) { return (a.sortOrder || '').localeCompare(b.sortOrder || ''); });
                    // Filter out Advanced Organizer Submission items from AP courses
                    pLessons = pLessons.filter(function(les) {
                        var t = (les.title || '').toLowerCase();
                        return !t.includes('advanced organizer') && !t.includes('organizer submission');
                    });
                    var pUnitRes = pMod.componentResources || [];
                    if (pLessons.length === 0 && pUnitRes.length > 0) {
                        for (var puri = 0; puri < pUnitRes.length; puri++) {
                            var pR = pUnitRes[puri].resource || pUnitRes[puri] || {};
                            pLessons.push({ title: pR.title || ('Assessment ' + (puri + 1)), id: pR.id || pR.sourcedId || '', sourcedId: pR.sourcedId || pR.id || '', sortOrder: pR.sortOrder || String(puri), componentResources: [pUnitRes[puri]] });
                        }
                    }
                    // Extract unit number from title (e.g. "Unit 0: Intro" → 0, "Unit 3" → 3)
                    var _unitNumMatch = (pMod.title || '').match(/Unit\s+(\d+)/i);
                    var _parsedUnitNum = _unitNumMatch ? parseInt(_unitNumMatch[1], 10) : null;
                    processedUnits.push({ mod: pMod, lessons: pLessons, title: pMod.title || '', unitNum: _parsedUnitNum });

                    for (var pl = 0; pl < pLessons.length; pl++) {
                        var pLesson = pLessons[pl];
                        var pLTitle = (pLesson.title || '').trim();
                        var pLessonId = pLesson.id || pLesson.sourcedId || '';
                        var pLProg = progressByTitle[pLTitle] || (pLessonId ? progressById[pLessonId] : null);
                        var pLDone = _isComplete(pLProg);
                        // Also check componentResources by unique ID only (not title — titles repeat across units)
                        var pRes = pLesson.componentResources || [];
                        var pHasQuizComplete = false;  // Track if any resource has PowerPath score > 0 (quiz completion)
                        var pCompletedCount = 0;       // Track how many resources are fully complete
                        var pTotalCount = pRes.length;  // Total resources in this lesson
                        if (pRes.length > 0) {
                            for (var _pri = 0; _pri < pRes.length; _pri++) {
                                var _prr = pRes[_pri].resource || pRes[_pri] || {};
                                var _prId = _prr.id || _prr.sourcedId || pRes[_pri].id || pRes[_pri].sourcedId || '';
                                var _prProg = _prId ? progressById[_prId] : null;
                                // Also check via assessmentLineItemSourcedId (consistent with rendering logic)
                                if (!_isComplete(_prProg)) {
                                    var _prAli = (_prId && assessmentLineItemByResId[_prId]) || '';
                                    if (_prAli && _isComplete(progressById[_prAli])) {
                                        _prProg = progressById[_prAli];
                                    }
                                }
                                if (_prProg && (_isComplete(_prProg) || (typeof _prProg.score === 'number'))) {
                                    if (!pLDone) pLDone = true;
                                    pCompletedCount++;
                                }
                                // Track quiz completions (score > 0) separately for other uses.
                                if (_isQuizComplete(_prProg)) {
                                    pHasQuizComplete = true;
                                }
                            }
                        }
                        // Frontier: advance when lesson-level progress shows completion,
                        // OR when all individual activities are complete.
                        // Accuracy does NOT gate progression — only completion matters.
                        var pHasAny = pLDone || (pTotalCount > 0 && pCompletedCount === pTotalCount);
                        var pCount = Math.max(pRes.length, 1);
                        grandTotalAct += pCount;
                        if (pLDone) { grandDoneAct += pCount; }
                        globalLessonList.push({ unitIdx: pu, hasProgress: pHasAny });
                    }
                }

                // ── Assign unit numbers for units without one parsed from the title ──
                // Detect if course starts at Unit 0 (common in AP courses)
                var _hasUnit0 = processedUnits.some(function(u) { return u.unitNum === 0; });
                var _unitNumOffset = _hasUnit0 ? 0 : 1;
                for (var _ui = 0; _ui < processedUnits.length; _ui++) {
                    if (processedUnits[_ui].unitNum === null) {
                        processedUnits[_ui].unitNum = _ui + _unitNumOffset;
                    }
                    // Assign fallback title using correct unit number
                    if (!processedUnits[_ui].title) {
                        processedUnits[_ui].title = 'Unit ' + processedUnits[_ui].unitNum;
                    }
                }

                // ── Global frontier: furthest lesson with ANY progress ──
                var globalFrontier = -1;
                for (var gi = globalLessonList.length - 1; gi >= 0; gi--) {
                    if (globalLessonList[gi].hasProgress) { globalFrontier = gi; break; }
                }
                var currentUnitIdx = globalFrontier >= 0 ? globalLessonList[globalFrontier].unitIdx : 0;

                // Target lesson for auto-scroll: next lesson after last fully-complete one
                var scrollToGlobalIdx = globalFrontier + 1;
                if (scrollToGlobalIdx >= globalLessonList.length) {
                    scrollToGlobalIdx = Math.max(0, globalLessonList.length - 1);
                }

                var overallPct = grandTotalAct > 0 ? Math.round((grandDoneAct / grandTotalAct) * 100) : 0;

                // ── Render Units ───────────────────────────────────
                var globalIdx = 0;
                var currentLessonElId = null; // Track current lesson for auto-scroll

                for (var mi = 0; mi < processedUnits.length; mi++) {
                    var puData = processedUnits[mi];
                    var modLessons = puData.lessons;
                    var modTitle = puData.title;
                    var unitId = 'unit-' + mi;

                    // Unit state from global frontier
                    var unitFirstIdx = globalIdx;
                    var forceComplete = !isAdmin && mi < currentUnitIdx;
                    var unitLocked = isAdmin ? false : (unitFirstIdx > globalFrontier + 1);

                    var unitDone = 0;
                    var unitQuizzesMastered = true; // Track if ALL quizzes in unit are mastered
                    var unitHasQuizzes = false;
                    
                    for (var lc = 0; lc < modLessons.length; lc++) {
                        var lcTitle = (modLessons[lc].title || '').trim();
                        var lcId = modLessons[lc].id || modLessons[lc].sourcedId || '';
                        var lcProg = progressByTitle[lcTitle] || (lcId ? progressById[lcId] : null);
                        var lcFound = _isComplete(lcProg);
                        
                        // Check if this lesson is a quiz/assessment
                        var lcIsAssessment = /assess|quiz|test|exam|mcq|frq|saq|dbq|leq|cumulative\s*review/i.test(lcTitle);
                        
                        // Also check componentResources (API data only)
                        var lcRes = modLessons[lc].componentResources || [];
                        var lcHasQuizResource = false;
                        var lcQuizMastered = false;
                        
                        for (var _lri = 0; _lri < lcRes.length; _lri++) {
                            var _lr = lcRes[_lri].resource || lcRes[_lri] || {};
                            var _lrId = _lr.id || _lr.sourcedId || lcRes[_lri].id || lcRes[_lri].sourcedId || '';
                            var _lrProg = _lrId ? progressById[_lrId] : null;
                            
                            // Check mastery: any resource with score > 0 and fully graded
                            // (videos/articles have score=0 so only quizzes pass this check)
                            if (_isMastered(_lrProg)) {
                                lcHasQuizResource = true;
                                lcQuizMastered = true;
                                unitHasQuizzes = true;
                            }
                            
                            if (!lcFound && _lrId && _isComplete(progressById[_lrId])) { 
                                lcFound = true; 
                            }
                        }
                        
                        // If this lesson has a quiz, check if it's mastered (PowerPath score 100)
                        if (lcIsAssessment || lcHasQuizResource) {
                            if (!lcQuizMastered && !_isMastered(lcProg)) {
                                unitQuizzesMastered = false;
                            }
                        }
                        
                        if (lcFound) unitDone++;
                    }
                    var unitPct = modLessons.length > 0 ? Math.round((unitDone / modLessons.length) * 100) : 0;
                    // Unit is only complete if:
                    // 1. All lessons are done (unitDone === modLessons.length) AND
                    // 2. If unit has quizzes, ALL quizzes must have PowerPath score 100
                    var unitComplete = forceComplete || (
                        unitDone === modLessons.length && 
                        modLessons.length > 0 && 
                        (!unitHasQuizzes || unitQuizzesMastered)
                    );
                    var isCurrentUnit = (mi === currentUnitIdx);
                    var autoExpand = !unitLocked && isCurrentUnit;

                    // ── Unit card (header only) ──
                    var cardClass = 'unit-card';
                    if (unitComplete) cardClass += ' complete';
                    if (unitLocked) cardClass += ' locked';
                    if (autoExpand) cardClass += ' expanded';

                    html += '<div class="' + cardClass + '" id="' + unitId + '-card">';
                    html += '<div class="unit-header" onclick="' + (unitLocked ? '' : "toggleUnit('" + unitId + "')") + '">' +
                        '<div class="unit-info">' +
                            '<div class="u-label">Unit ' + puData.unitNum + '</div>' +
                            '<h3>' + esc(modTitle) + '</h3>' +
                        '</div>' +
                        '<div class="unit-status">';

                    if (unitComplete) {
                        html += '<span class="complete-badge"><i class="fa-solid fa-check"></i> COMPLETE</span>';
                    } else if (!unitLocked) {
                        html += progressRing(unitPct);
                    }

                    html += '</div>' +
                        '<i class="fa-solid fa-chevron-down unit-chevron' + (autoExpand ? ' open' : '') + '" id="' + unitId + '-chev"></i>' +
                    '</div>';
                    html += '</div>'; // close unit-card

                    // ── Unit timeline (sibling, outside card border) ──
                    html += '<div class="unit-timeline' + (autoExpand ? ' open' : '') + '" id="' + unitId + '">';

                    if (!unitLocked) {
                        html += '<div class="timeline">';

                        for (var li = 0; li < modLessons.length; li++) {
                            var lessonGlobalIdx = globalIdx + li;
                            var lesson = modLessons[li];
                            var lTitle = lesson.title || 'Lesson ' + (li + 1);
                            var lId = lesson.id || lesson.sourcedId || '';
                            // Look up progress by title first, then by sourcedId
                            var prog = progressByTitle[lTitle.trim()] || (lId ? progressById[lId] : null) || null;
                            
                            // Also check componentResources by unique ID only (not title — titles repeat across units)
                            var _lesRes = lesson.componentResources || [];
                            if (!_isComplete(prog) && _lesRes.length > 0) {
                                for (var _cri = 0; _cri < _lesRes.length; _cri++) {
                                    var _cr = _lesRes[_cri].resource || _lesRes[_cri] || {};
                                    var _crId = _cr.id || _cr.sourcedId || _lesRes[_cri].id || _lesRes[_cri].sourcedId || '';
                                    if (_crId && _isComplete(progressById[_crId])) { prog = progressById[_crId]; break; }
                                    // Also check via assessmentLineItemSourcedId (video/article share one lineItem per lesson)
                                    var _crAli = assessmentLineItemByResId[_crId] || '';
                                    if (_crAli && _isComplete(progressById[_crAli])) { prog = progressById[_crAli]; break; }
                                }
                            }
                            
                            var isDone = _isComplete(prog);
                            var localKey = 'completed_' + (lId || lTitle);
                            // Locking uses API data only — no localStorage
                            var lessonLocked = isAdmin ? false : (lessonGlobalIdx > globalFrontier + 1);
                            var resources = lesson.componentResources || [];

                            var isAssessmentTitle = /assess|aps[\s:\-]|quiz|final\s*test|unit\s*test|exam|cumulative\s*review/i.test(lTitle);
                            var isReview = /cumulative\s*review|review/i.test(lTitle);
                            var lessonType = isAssessmentTitle ? 'quiz' : 'reading';
                            var openUrl = '';
                            var resDetails = [];

                            for (var ri = 0; ri < resources.length; ri++) {
                                var resObj = resources[ri];
                                var res = resObj.resource || resObj || {};
                                var rmeta = (typeof res === 'object' ? res.metadata : null) || {};
                                var rtype = (rmeta.type || res.type || '').toLowerCase();
                                var rurl = rmeta.url || res.url || rmeta.href || res.href || '';
                                var rTitle2 = (typeof res === 'object' ? (res.title || '') : '').substring(0, 60);
                                var resId = res.id || res.sourcedId || resObj.id || resObj.sourcedId || '';
                                if (rtype === 'video') lessonType = 'video';
                                else if (rtype.includes('assess') || rtype.includes('quiz') || rtype.includes('test')) lessonType = 'quiz';
                                var pillUrl = '';
                                if (rtype === 'video' && rurl) { pillUrl = rurl; }
                                else if (rurl && !rurl.includes('flashcard.com')) { pillUrl = '/quiz?url=' + encodeURIComponent(rurl) + '&title=' + encodeURIComponent(lTitle) + quizExtra; }
                                else if (resId) { pillUrl = '/quiz?id=' + encodeURIComponent(resId) + '&type=' + encodeURIComponent(rtype || 'assessment') + '&title=' + encodeURIComponent(lTitle) + quizExtra; }
                                var lbl = resLabel(rtype, rurl);
                                var componentResId = resObj.sourcedId || resObj.id || resId;
                                resDetails.push({ type: rtype, url: rurl, pillUrl: pillUrl, title: rTitle2, label: lbl, resId: resId, componentResId: componentResId });
                                if (!openUrl && pillUrl) openUrl = pillUrl;
                            }

                            if (!openUrl) {
                                var lessonMetaUrl = (lesson.metadata || {}).url || lesson.url || '';
                                var lessonResId = lesson.id || lesson.sourcedId || '';
                                if (lessonMetaUrl) { openUrl = '/quiz?url=' + encodeURIComponent(lessonMetaUrl) + '&title=' + encodeURIComponent(lTitle) + quizExtra; }
                                else if (lessonResId && (lessonType === 'quiz' || isAssessmentTitle)) { openUrl = '/quiz?id=' + encodeURIComponent(lessonResId) + '&type=assessment&title=' + encodeURIComponent(lTitle) + quizExtra; }
                            }
                            if (resDetails.length === 0 && openUrl) { resDetails.push({ type: 'assessment', url: '', pillUrl: openUrl, title: lTitle, label: 'Quiz' }); }

                            var nonQuizCount = 0, nonQuizDoneCount = 0;
                            for (var rci = 0; rci < resDetails.length; rci++) {
                                var isQuizRes = (resDetails[rci].label === 'Quiz');
                                resDetails[rci]._isQuiz = isQuizRes;
                                if (!isQuizRes) {
                                    nonQuizCount++;
                                    resDetails[rci]._localKey = localKey + '_r' + rci;
                                    // Check API only via progressById (resource id or assessmentLineItemSourcedId)
                                    var resApiDone = false;
                                    var thisResId = resDetails[rci].resId || '';
                                    if (thisResId && _isComplete(progressById[thisResId])) { resApiDone = true; }
                                    // Check via assessmentLineItemSourcedId (shared by video/article in same lesson)
                                    var thisResAli = assessmentLineItemByResId[thisResId] || '';
                                    if (!resApiDone && thisResAli && _isComplete(progressById[thisResAli])) { resApiDone = true; }
                                    resDetails[rci]._resDone = resApiDone;
                                    if (resDetails[rci]._resDone) nonQuizDoneCount++;
                                } else {
                                    // Quiz/assessment resources — check API completion only
                                    resDetails[rci]._localKey = localKey + '_r' + rci;
                                    var qResApiDone = false;
                                    var qResId = resDetails[rci].resId || '';
                                    if (qResId && _isComplete(progressById[qResId])) { qResApiDone = true; }
                                    var qResAli = assessmentLineItemByResId[qResId] || '';
                                    if (!qResApiDone && qResAli && _isComplete(progressById[qResAli])) { qResApiDone = true; }
                                    resDetails[rci]._resDone = qResApiDone;
                                }
                            }

                            var totalRes = resDetails.length;
                            var doneRes = 0;
                            for (var dc = 0; dc < resDetails.length; dc++) { if (resDetails[dc]._resDone) doneRes++; }
                            var lessonPctVal = totalRes > 0 ? Math.round((doneRes / totalRes) * 100) : (isDone ? 100 : 0);

                            var typeIcon = lessonType === 'video' ? 'fa-play' : lessonType === 'quiz' ? 'fa-clipboard-question' : 'fa-file-lines';
                            var lessonId = 'lesson-' + mi + '-' + li;
                            var sortedRes = resDetails.slice().sort(function(a, b) { var order = { 'Video': 0, 'Article': 1, 'Quiz': 2 }; return (order[a.label] || 1) - (order[b.label] || 1); });

                            var tlClass = 'tl-item';
                            if (lessonLocked) tlClass += ' locked';
                            if (isReview) tlClass += ' review';
                            html += '<div class="' + tlClass + '" id="' + lessonId + '">';

                            // Track the lesson at the scroll target index
                            if (!currentLessonElId && lessonGlobalIdx === scrollToGlobalIdx) {
                                currentLessonElId = lessonId;
                            }

                            // Timeline dot
                            var dotClass = 'tl-dot';
                            if (isDone) dotClass += ' done';
                            else if (lessonLocked) dotClass += ' locked';
                            else dotClass += ' active';
                            html += '<div class="' + dotClass + '">';
                            if (isDone) html += '<i class="fa-solid fa-check" style="font-size:0.7rem;"></i>';
                            else if (lessonLocked) html += '<i class="fa-solid fa-lock" style="font-size:0.6rem;"></i>';
                            html += '</div>';

                            // Store lesson data for navigation
                            var lessonDataKey = 'lesson_' + mi + '_' + li;
                            
                            // Find the PowerPath assessmentLineItemSourcedId for this lesson's resources
                            var ppAssessmentLineItemId = '';
                            for (var ri = 0; ri < sortedRes.length; ri++) {
                                var rid = sortedRes[ri].resId || '';
                                if (rid && assessmentLineItemByResId[rid]) {
                                    ppAssessmentLineItemId = assessmentLineItemByResId[rid];
                                    break;
                                }
                            }
                            // Fallback: try by lesson title
                            if (!ppAssessmentLineItemId && assessmentLineItemByResId[lTitle]) {
                                ppAssessmentLineItemId = assessmentLineItemByResId[lTitle];
                            }
                            
                            window._lessonData[lessonDataKey] = {
                                title: lTitle,
                                completionKey: localKey,
                                resources: sortedRes.map(function(r) { 
                                    return { 
                                        type: r.type, 
                                        url: r.url, 
                                        pillUrl: r.pillUrl, 
                                        title: r.title, 
                                        label: r.label, 
                                        resId: r.resId || '',
                                        componentResId: r.componentResId || r.resId || '',
                                        assessmentLineItemSourcedId: assessmentLineItemByResId[r.componentResId] || assessmentLineItemByResId[r.resId] || ''
                                    }; 
                                }),
                                courseTitle: courseTitle,
                                quizExtra: quizExtra,
                                enrollmentId: enrollment ? (enrollment.id || enrollment.sourcedId || '') : '',
                                courseSourcedId: course ? (course.sourcedId || course.id || '') : '',
                                courseName: course ? (course.title || courseTitle) : courseTitle,
                                assessmentLineItemSourcedId: ppAssessmentLineItemId,
                                lessonPlanId: lessonPlanId,
                                lessonSourcedId: lesson.sourcedId || lesson.id || ''
                            };

                            var actAllDone = (doneRes === totalRes && totalRes > 0);
                            var statsHtml = '';
                            if (actAllDone) {
                                statsHtml = '<div class="lesson-stats">' +
                                    '<span class="act-text complete"><i class="fa-solid fa-circle-check"></i></span>' +
                                '</div>';
                            } else if (doneRes > 0) {
                                statsHtml = '<div class="lesson-stats">' +
                                    '<span class="act-text"><i class="fa-solid fa-circle"></i> ' + doneRes + '/' + totalRes + ' Activities</span>' +
                                '</div>';
                            }

                            var rowClick = lessonLocked ? '' : ' onclick="openLesson(\'' + lessonDataKey + '\')"';
                            html += '<div class="lesson-row"' + rowClick + '>' +
                                '<div class="lesson-info"><div class="lesson-title">' + esc(lTitle) + '</div></div>' +
                                statsHtml +
                            '</div>';

                            html += '</div>'; // tl-item
                        }

                        html += '</div>'; // timeline
                    } else {
                        html += '<div style="padding:16px 24px;color:var(--color-text-muted);font-size:0.85rem;">' +
                            '<i class="fa-solid fa-lock" style="margin-right:6px;"></i> Complete the previous lessons to unlock this unit.</div>';
                    }

                    html += '</div>'; // unit-timeline
                    globalIdx += modLessons.length;
                }
            }

            // Fallback
            if (!html) {
                html = '<div style="text-align:center;padding:30px;color:var(--color-text-muted);"><p>No lesson data available yet.</p></div>';
            }

            // (Launch CTA removed)

            contentEl.innerHTML = html;

            // ── Auto-scroll to current lesson ──
            if (units.length > 0) {
                setTimeout(function() {
                    var target = currentLessonElId
                        ? document.getElementById(currentLessonElId)
                        : document.getElementById('unit-' + currentUnitIdx + '-card');
                    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }, 500);
            }

        } catch(e) {
            console.error('[Course] Content fetch error:', e);
            var contentEl = document.getElementById('content-section');
            if (contentEl) {
                contentEl.innerHTML = '<div style="text-align:center;padding:24px;color:var(--color-text-muted);"><p>Error loading content: ' + esc(e.message) + '</p></div>';
            }
        }
    });
    