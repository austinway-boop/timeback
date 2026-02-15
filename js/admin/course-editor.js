/* ====================================================================
   Course Editor – AP Course Skill Tree Generator + Lesson Mapping
   ==================================================================== */
(function () {
    'use strict';

    /* ---- Constants -------------------------------------------------- */
    const EXTERNAL_APP_KEYS = new Set([
        'gumpp', 'runestone', 'newsela', 'khan', 'readtheory', 'commonlit',
        'knewton', 'alta', 'lalilo', 'rocketmath', 'zearn',
        'renaissance', 'starreading', 'starmath',
        'edmentum', 'mathacademy', 'membean',
    ]);

    const THEMES = ['teal', 'purple', 'pink', 'orange', 'blue'];
    const ICONS = {
        history: 'fa-landmark', lang: 'fa-pen-fancy', lit: 'fa-book-open',
        bio: 'fa-dna', chem: 'fa-flask', physics: 'fa-atom',
        math: 'fa-calculator', calc: 'fa-square-root-variable', stat: 'fa-chart-line',
        cs: 'fa-laptop-code', psych: 'fa-brain', econ: 'fa-chart-pie',
        gov: 'fa-building-columns', geo: 'fa-globe-americas', env: 'fa-leaf',
        art: 'fa-palette', music: 'fa-music', default: 'fa-graduation-cap',
    };

    const POLL_INTERVAL = 15000;

    /* ---- State ------------------------------------------------------ */
    var allCourses = [];
    var filteredCourses = [];
    var selectedCourse = null;
    var pollTimer = null;
    var lessonPollTimer = null;
    var currentMermaidCode = ''; // stored for export
    var explanationPollTimer = null;
    var relevancePollTimer = null;

    /* ---- Helpers ----------------------------------------------------- */
    function esc(str) {
        if (str == null) return '';
        var div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    function guessIcon(title) {
        var t = (title || '').toLowerCase();
        if (t.includes('hist') || t.includes('world')) return ICONS.history;
        if (t.includes('lang')) return ICONS.lang;
        if (t.includes('lit')) return ICONS.lit;
        if (t.includes('bio')) return ICONS.bio;
        if (t.includes('chem')) return ICONS.chem;
        if (t.includes('physics')) return ICONS.physics;
        if (t.includes('calc')) return ICONS.calc;
        if (t.includes('stat')) return ICONS.stat;
        if (t.includes('math')) return ICONS.math;
        if (t.includes('computer') || t.includes('cs')) return ICONS.cs;
        if (t.includes('psych')) return ICONS.psych;
        if (t.includes('econ')) return ICONS.econ;
        if (t.includes('gov')) return ICONS.gov;
        if (t.includes('geo') || t.includes('human')) return ICONS.geo;
        if (t.includes('environ')) return ICONS.env;
        if (t.includes('art')) return ICONS.art;
        if (t.includes('music')) return ICONS.music;
        return ICONS.default;
    }

    function isAPCourse(c) { return /\bAP\b/i.test((c.title || '').trim()); }

    function isExternal(c) {
        var meta = c.metadata || {};
        var app = (meta.app || meta.primaryApp || '').toLowerCase().replace(/[\s_-]/g, '');
        if (!app) return false;
        for (var key of EXTERNAL_APP_KEYS) { if (app.includes(key)) return true; }
        return false;
    }

    function countMermaidNodes(code) {
        var matches = code.match(/\w+\["[^"]*"\]/g);
        return matches ? matches.length : 0;
    }

    function formatTime(secs) {
        var m = Math.floor(secs / 60), s = secs % 60;
        return m > 0 ? m + 'm ' + s + 's' : s + 's';
    }

    /* ---- Skeleton Cards --------------------------------------------- */
    function showSkeletonCards(count) {
        var grid = document.getElementById('courses-grid');
        grid.innerHTML = Array.from({ length: count }, function () {
            return '<div class="ce-skeleton-card">' +
                '<div class="skeleton skeleton-text lg" style="width:40px;height:40px;border-radius:10px;margin-bottom:12px;"></div>' +
                '<div class="skeleton skeleton-text" style="width:75%;margin-bottom:8px;"></div>' +
                '<div class="skeleton skeleton-text sm" style="width:50%;margin-bottom:8px;"></div>' +
                '<div class="skeleton skeleton-text xs" style="width:35%;"></div>' +
            '</div>';
        }).join('');
    }

    /* ---- Load Courses ----------------------------------------------- */
    async function loadCourses() {
        showSkeletonCards(6);
        try {
            var resp = await fetch('/api/courses');
            var data = await resp.json();
            allCourses = (data.courses || []).filter(function (c) {
                return isAPCourse(c) && !isExternal(c);
            }).sort(function (a, b) {
                var aA = (a.status || '').toLowerCase() === 'active' ? 0 : 1;
                var bA = (b.status || '').toLowerCase() === 'active' ? 0 : 1;
                if (aA !== bA) return aA - bA;
                return (a.title || '').localeCompare(b.title || '');
            });
            await checkExistingTrees();
            updateCount();
            filterAndRender();
            // Auto-open course from URL
            autoOpenFromURL();
        } catch (e) {
            document.getElementById('courses-grid').innerHTML =
                '<div class="ce-empty-state"><i class="fa-solid fa-circle-exclamation"></i><p>Failed to load courses. Please try again.</p></div>';
        }
    }

    function autoOpenFromURL() {
        var id = new URLSearchParams(window.location.search).get('id');
        if (!id) return;
        var course = allCourses.find(function (c) { return c.sourcedId === id; });
        if (course) openCourseDetail(course);
    }

    async function checkExistingTrees() {
        var checks = allCourses.map(function (c) {
            return fetch('/api/skill-tree-status?courseId=' + encodeURIComponent(c.sourcedId))
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    c._hasTree = d.status === 'done';
                    c._generating = d.status === 'processing';
                })
                .catch(function () { c._hasTree = false; c._generating = false; });
        });
        await Promise.all(checks);
    }

    /* ---- Filter & Render -------------------------------------------- */
    function updateCount() {
        filteredCourses = filterCourses();
        document.getElementById('courses-count').textContent =
            filteredCourses.length + ' AP course' + (filteredCourses.length !== 1 ? 's' : '') + ' found';
    }

    function filterCourses() {
        var q = (document.getElementById('course-search').value || '').toLowerCase().trim();
        if (!q) return allCourses.slice();
        return allCourses.filter(function (c) {
            return (c.title || '').toLowerCase().includes(q) || (c.courseCode || '').toLowerCase().includes(q);
        });
    }

    function filterAndRender() {
        filteredCourses = filterCourses();
        var grid = document.getElementById('courses-grid');
        if (!filteredCourses.length) {
            grid.innerHTML = '<div class="ce-empty-state"><i class="fa-solid fa-book"></i><p>No AP courses found matching your search.</p></div>';
            return;
        }
        grid.innerHTML = filteredCourses.map(function (c, i) {
            var theme = THEMES[i % THEMES.length], icon = guessIcon(c.title), badge = '';
            if (c._hasTree) badge = '<span class="ce-card-badge has-tree"><i class="fa-solid fa-check" style="margin-right:3px;"></i>Skill Tree</span>';
            else if (c._generating) badge = '<span class="ce-card-badge generating"><i class="fa-solid fa-spinner fa-spin" style="margin-right:3px;"></i>Generating</span>';
            var meta = c.metadata || {}, metrics = meta.metrics || {};
            var lessons = metrics.totalLessons || metrics.totalUnits || '';
            return '<div class="ce-course-card" data-idx="' + i + '">' + badge +
                '<div class="ce-card-icon ' + theme + '"><i class="fa-solid ' + icon + '"></i></div>' +
                '<div class="ce-card-title">' + esc(c.title) + '</div>' +
                '<div class="ce-card-code">' + esc(c.courseCode || 'No code') + '</div>' +
                '<div class="ce-card-meta">' +
                    (lessons ? '<span><i class="fa-solid fa-layer-group"></i>' + lessons + ' lessons</span>' : '') +
                    '<span><i class="fa-solid fa-circle ' + (c.status === 'active' ? '" style="color:#45B5AA;font-size:0.5rem;"' : '" style="color:#CBD5E0;font-size:0.5rem;"') + '></i> ' + esc(c.status || 'unknown') + '</span>' +
                '</div></div>';
        }).join('');
        grid.querySelectorAll('.ce-course-card').forEach(function (card) {
            card.addEventListener('click', function () {
                openCourseDetail(filteredCourses[parseInt(this.getAttribute('data-idx'), 10)]);
            });
        });
    }

    /* ---- Course Detail View ----------------------------------------- */
    function openCourseDetail(course) {
        selectedCourse = course;
        history.pushState(null, '', '?id=' + encodeURIComponent(course.sourcedId));
        document.getElementById('course-list-view').style.display = 'none';
        document.getElementById('course-detail-view').style.display = '';
        var icon = guessIcon(course.title);
        var meta = course.metadata || {}, metrics = meta.metrics || {};
        var lessons = metrics.totalLessons || metrics.totalUnits || '?';
        var subjects = (course.subjects || []).join(', ') || 'N/A';
        var grades = (course.grades || []).join(', ') || 'N/A';
        document.getElementById('detail-header').innerHTML =
            '<div class="ce-detail-title"><i class="fa-solid ' + icon + '" style="margin-right:10px; opacity:0.5;"></i>' + esc(course.title) + '</div>' +
            '<div class="ce-detail-code">' + esc(course.courseCode || 'No course code') + ' &bull; ' + esc(course.sourcedId) + '</div>' +
            '<div class="ce-detail-meta">' +
                '<span><i class="fa-solid fa-layer-group"></i>' + esc(lessons) + ' lessons</span>' +
                '<span><i class="fa-solid fa-tag"></i>' + esc(subjects) + '</span>' +
                '<span><i class="fa-solid fa-users"></i>Grades: ' + esc(grades) + '</span>' +
                '<span><i class="fa-solid fa-circle ' + (course.status === 'active' ? '" style="color:#45B5AA;font-size:0.5rem;"' : '" style="color:#CBD5E0;font-size:0.5rem;"') + '></i> ' + esc(course.status) + '</span>' +
            '</div>';
        // Show landing page (not wizard)
        document.getElementById('setup-wizard').style.display = 'none';
        showCourseActions(course.sourcedId);
    }

    function closeCourseDetail() {
        selectedCourse = null;
        currentMermaidCode = '';
        stopPolling();
        stopLessonPolling();
        stopQuestionPolling();
        stopRelevancePolling();
        history.pushState(null, '', '/admin/course-editor');
        document.getElementById('course-detail-view').style.display = 'none';
        document.getElementById('course-list-view').style.display = '';
        document.getElementById('setup-wizard').style.display = 'none';
        document.getElementById('lesson-mapping-section').style.display = 'none';
        document.getElementById('question-analysis-section').style.display = 'none';
        checkExistingTrees().then(function () { filterAndRender(); });
    }

    /* ---- Course Actions (Landing Page) ------------------------------ */
    async function showCourseActions(courseId) {
        var el = document.getElementById('course-actions');
        el.style.display = '';
        el.innerHTML = '<div style="text-align:center; padding:40px; color:var(--color-text-muted);"><div class="ce-progress-spinner" style="display:inline-block; margin-bottom:12px;"></div><br>Checking setup status...</div>';

        // Check status of all 3 steps in parallel
        var statuses = { tree: 'pending', lessons: 'pending', questions: 'pending' };
        try {
            var results = await Promise.all([
                fetch('/api/skill-tree-status?courseId=' + encodeURIComponent(courseId)).then(function (r) { return r.json(); }).catch(function () { return {}; }),
                fetch('/api/lesson-mapping-status?courseId=' + encodeURIComponent(courseId)).then(function (r) { return r.json(); }).catch(function () { return {}; }),
                fetch('/api/question-analysis-status?courseId=' + encodeURIComponent(courseId)).then(function (r) { return r.json(); }).catch(function () { return {}; }),
            ]);
            if (results[0].status === 'done') statuses.tree = 'done';
            else if (results[0].status === 'processing') statuses.tree = 'processing';
            if (results[1].status === 'done') statuses.lessons = 'done';
            else if (results[1].status === 'processing') statuses.lessons = 'processing';
            if (results[2].status === 'done') statuses.questions = 'done';
            else if (results[2].status === 'processing') statuses.questions = 'processing';
        } catch (e) { /* ignore */ }

        var allDone = statuses.tree === 'done' && statuses.lessons === 'done' && statuses.questions === 'done';
        var anyDone = statuses.tree === 'done' || statuses.lessons === 'done' || statuses.questions === 'done';
        var anyProcessing = statuses.tree === 'processing' || statuses.lessons === 'processing' || statuses.questions === 'processing';

        // Check skill mapping toggle status + explanation status + relevance status in parallel
        var skillMappingEnabled = false;
        var explStatus = 'none';
        var explQuestionCount = 0;
        var explEnabled = false;
        var relStatus = 'none';
        var relQuestionCount = 0;
        var relBadCount = 0;
        var relEnabled = false;
        try {
            var extraResults = await Promise.all([
                fetch('/api/skill-mapping-toggle?courseId=' + encodeURIComponent(courseId)).then(function (r) { return r.json(); }).catch(function () { return {}; }),
                fetch('/api/explanation-status?courseId=' + encodeURIComponent(courseId)).then(function (r) { return r.json(); }).catch(function () { return {}; }),
                fetch('/api/explanation-toggle?courseId=' + encodeURIComponent(courseId)).then(function (r) { return r.json(); }).catch(function () { return {}; }),
                fetch('/api/relevance-status?courseId=' + encodeURIComponent(courseId)).then(function (r) { return r.json(); }).catch(function () { return {}; }),
                fetch('/api/relevance-toggle?courseId=' + encodeURIComponent(courseId)).then(function (r) { return r.json(); }).catch(function () { return {}; }),
            ]);
            skillMappingEnabled = extraResults[0].enabled === true;
            if (extraResults[1].status === 'done') { explStatus = 'done'; explQuestionCount = extraResults[1].questionCount || 0; }
            else if (extraResults[1].status === 'processing') explStatus = 'processing';
            explEnabled = extraResults[2].enabled === true;
            if (extraResults[3].status === 'done') { relStatus = 'done'; relQuestionCount = extraResults[3].questionCount || 0; relBadCount = extraResults[3].badCount || 0; }
            else if (extraResults[3].status === 'processing') relStatus = 'processing';
            relEnabled = extraResults[4].enabled === true;
        } catch (e) { /* ignore */ }

        function badge(status) {
            if (status === 'done') return '<span class="ce-status-badge done"><i class="fa-solid fa-check-circle"></i> Complete</span>';
            if (status === 'processing') return '<span class="ce-status-badge processing"><i class="fa-solid fa-spinner fa-spin"></i> In progress</span>';
            return '<span class="ce-status-badge pending"><i class="fa-regular fa-circle"></i> Not started</span>';
        }

        var btnLabel, btnIcon;
        if (allDone) {
            btnLabel = 'View / Edit Setup';
            btnIcon = 'fa-solid fa-gear';
        } else if (anyDone || anyProcessing) {
            btnLabel = 'Continue Setup';
            btnIcon = 'fa-solid fa-arrow-right';
        } else {
            btnLabel = 'Setup Hole Filling / Mastery Detection';
            btnIcon = 'fa-solid fa-wand-magic-sparkles';
        }

        // Summary badge for header
        var doneCount = (statuses.tree === 'done' ? 1 : 0) + (statuses.lessons === 'done' ? 1 : 0) + (statuses.questions === 'done' ? 1 : 0);
        var summaryClass, summaryText;
        if (allDone) {
            summaryClass = 'all-done';
            summaryText = '<i class="fa-solid fa-check-circle"></i> 3/3 complete';
        } else if (anyDone || anyProcessing) {
            summaryClass = 'in-progress';
            summaryText = doneCount + '/3 complete';
        } else {
            summaryClass = 'not-started';
            summaryText = 'Not started';
        }

        // Skill mapping toggle HTML (inline, only when all done)
        var toggleHtml = '';
        if (allDone) {
            toggleHtml =
                '<div class="ce-inline-toggle">' +
                    '<div class="ce-inline-toggle-left">' +
                        '<i class="fa-solid fa-toggle-' + (skillMappingEnabled ? 'on' : 'off') + '"></i>' +
                        '<strong>Skill Mapping</strong>' +
                        '<span>Per-student mastery scores</span>' +
                    '</div>' +
                    '<label class="ce-switch">' +
                        '<input type="checkbox" id="skill-mapping-toggle" ' + (skillMappingEnabled ? 'checked' : '') + '>' +
                        '<span class="ce-switch-slider"></span>' +
                    '</label>' +
                '</div>';
        }

        // Explanation card status
        var explSummaryClass, explSummaryText, explBtnLabel, explBtnIcon;
        if (explStatus === 'done') {
            explSummaryClass = 'all-done';
            explSummaryText = '<i class="fa-solid fa-check-circle"></i> ' + explQuestionCount + ' questions';
            explBtnLabel = 'Regenerate Explanations';
            explBtnIcon = 'fa-solid fa-arrows-rotate';
        } else if (explStatus === 'processing') {
            explSummaryClass = 'in-progress';
            explSummaryText = '<i class="fa-solid fa-spinner fa-spin"></i> Generating...';
            explBtnLabel = 'Generating...';
            explBtnIcon = 'fa-solid fa-spinner fa-spin';
        } else {
            explSummaryClass = 'not-started';
            explSummaryText = 'Not started';
            explBtnLabel = 'Generate Explanations';
            explBtnIcon = 'fa-solid fa-wand-magic-sparkles';
        }

        // Explanation toggle HTML (only when done)
        var explToggleHtml = '';
        if (explStatus === 'done') {
            explToggleHtml =
                '<div class="ce-inline-toggle">' +
                    '<div class="ce-inline-toggle-left">' +
                        '<i class="fa-solid fa-toggle-' + (explEnabled ? 'on' : 'off') + '"></i>' +
                        '<strong>Answer Explanations</strong>' +
                        '<span>Show AI explanations for wrong answers</span>' +
                    '</div>' +
                    '<label class="ce-switch">' +
                        '<input type="checkbox" id="explanation-toggle" ' + (explEnabled ? 'checked' : '') + '>' +
                        '<span class="ce-switch-slider"></span>' +
                    '</label>' +
                '</div>';
        }

        // Relevance card status
        var relSummaryClass, relSummaryText, relBtnLabel, relBtnIcon;
        if (relStatus === 'done') {
            relSummaryClass = 'all-done';
            relSummaryText = '<i class="fa-solid fa-check-circle"></i> ' + relBadCount + ' flagged / ' + relQuestionCount + ' analyzed';
            relBtnLabel = 'Re-Analyze Relevance';
            relBtnIcon = 'fa-solid fa-arrows-rotate';
        } else if (relStatus === 'processing') {
            relSummaryClass = 'in-progress';
            relSummaryText = '<i class="fa-solid fa-spinner fa-spin"></i> Analyzing...';
            relBtnLabel = 'Analyzing...';
            relBtnIcon = 'fa-solid fa-spinner fa-spin';
        } else {
            relSummaryClass = 'not-started';
            relSummaryText = 'Not started';
            relBtnLabel = 'Analyze Relevance';
            relBtnIcon = 'fa-solid fa-magnifying-glass-chart';
        }

        // Relevance toggle HTML (only when done)
        var relToggleHtml = '';
        if (relStatus === 'done') {
            relToggleHtml =
                '<div class="ce-inline-toggle">' +
                    '<div class="ce-inline-toggle-left">' +
                        '<i class="fa-solid fa-toggle-' + (relEnabled ? 'on' : 'off') + '"></i>' +
                        '<strong>Hide Irrelevant Questions</strong>' +
                        '<span>Remove flagged questions from student quizzes</span>' +
                    '</div>' +
                    '<label class="ce-switch">' +
                        '<input type="checkbox" id="relevance-toggle" ' + (relEnabled ? 'checked' : '') + '>' +
                        '<span class="ce-switch-slider"></span>' +
                    '</label>' +
                '</div>';
        }

        el.innerHTML =
            '<div class="ce-action-card' + (allDone ? ' collapsed' : '') + '">' +
                '<div class="ce-action-card-header" id="action-card-header">' +
                    '<div class="ce-action-card-icon"><i class="fa-solid fa-crosshairs"></i></div>' +
                    '<div class="ce-action-card-header-text">' +
                        '<div class="ce-action-card-title">Hole Filling / Mastery Detection</div>' +
                        '<div class="ce-action-card-subtitle">AI-powered skill analysis for this course</div>' +
                    '</div>' +
                    '<span class="ce-action-card-summary ' + summaryClass + '">' + summaryText + '</span>' +
                    '<i class="fa-solid fa-chevron-down ce-action-card-chevron"></i>' +
                '</div>' +
                '<div class="ce-action-card-body">' +
                    '<div class="ce-setup-steps">' +
                        '<div class="ce-setup-step">' +
                            '<span class="ce-setup-step-num">1</span>' +
                            '<div class="ce-setup-step-info">' +
                                '<strong>Generate Skill Tree</strong>' +
                                '<span>Map every micro-skill and prerequisite</span>' +
                            '</div>' +
                            badge(statuses.tree) +
                        '</div>' +
                        '<div class="ce-setup-step">' +
                            '<span class="ce-setup-step-num">2</span>' +
                            '<div class="ce-setup-step-info">' +
                                '<strong>Map Lessons to Skills</strong>' +
                                '<span>Link each lesson to its skills</span>' +
                            '</div>' +
                            badge(statuses.lessons) +
                        '</div>' +
                        '<div class="ce-setup-step">' +
                            '<span class="ce-setup-step-num">3</span>' +
                            '<div class="ce-setup-step-info">' +
                                '<strong>Analyze Questions</strong>' +
                                '<span>Map every question and answer to skills</span>' +
                            '</div>' +
                            badge(statuses.questions) +
                        '</div>' +
                    '</div>' +
                    toggleHtml +
                    '<button class="ce-btn-generate ce-action-card-btn" id="btn-start-setup">' +
                        '<i class="' + btnIcon + '"></i> ' + btnLabel +
                    '</button>' +
                '</div>' +
            '</div>' +

            /* ---- Answer Explanations Action Card ---- */
            '<div class="ce-action-card' + (explStatus === 'done' ? ' collapsed' : '') + '">' +
                '<div class="ce-action-card-header" id="expl-card-header">' +
                    '<div class="ce-action-card-icon"><i class="fa-solid fa-comment-dots"></i></div>' +
                    '<div class="ce-action-card-header-text">' +
                        '<div class="ce-action-card-title">Answer Explanations</div>' +
                        '<div class="ce-action-card-subtitle">AI-generated feedback for wrong answers</div>' +
                    '</div>' +
                    '<span class="ce-action-card-summary ' + explSummaryClass + '">' + explSummaryText + '</span>' +
                    '<i class="fa-solid fa-chevron-down ce-action-card-chevron"></i>' +
                '</div>' +
                '<div class="ce-action-card-body">' +
                    '<p style="font-size:0.88rem; color:var(--color-text-muted); margin:0 0 16px 0;">Pull every question for this course and use AI to generate research-backed explanations for each wrong answer. When enabled, students see a short, specific explanation whenever they answer incorrectly.</p>' +
                    explToggleHtml +
                    '<div id="expl-progress" style="display:none;"></div>' +
                    '<div id="expl-results" style="display:none;"></div>' +
                    '<button class="ce-btn-generate ce-action-card-btn" id="btn-generate-explanations"' + (explStatus === 'processing' ? ' disabled' : '') + '>' +
                        '<i class="' + explBtnIcon + '"></i> ' + explBtnLabel +
                    '</button>' +
                '</div>' +
            '</div>' +

            /* ---- Question Relevance Action Card ---- */
            '<div class="ce-action-card' + (relStatus === 'done' ? ' collapsed' : '') + '">' +
                '<div class="ce-action-card-header" id="rel-card-header">' +
                    '<div class="ce-action-card-icon"><i class="fa-solid fa-magnifying-glass-chart"></i></div>' +
                    '<div class="ce-action-card-header-text">' +
                        '<div class="ce-action-card-title">Question Relevance</div>' +
                        '<div class="ce-action-card-subtitle">AI analysis of question-to-content alignment</div>' +
                    '</div>' +
                    '<span class="ce-action-card-summary ' + relSummaryClass + '">' + relSummaryText + '</span>' +
                    '<i class="fa-solid fa-chevron-down ce-action-card-chevron"></i>' +
                '</div>' +
                '<div class="ce-action-card-body">' +
                    '<p style="font-size:0.88rem; color:var(--color-text-muted); margin:0 0 16px 0;">Analyze every question against its lesson\'s video transcript and article to detect questions that are unrelated to the learning content. Flagged questions can be hidden so students never see them.</p>' +
                    relToggleHtml +
                    '<div id="rel-progress" style="display:none;"></div>' +
                    '<div id="rel-results" style="display:none;"></div>' +
                    '<button class="ce-btn-generate ce-action-card-btn" id="btn-analyze-relevance"' + (relStatus === 'processing' ? ' disabled' : '') + '>' +
                        '<i class="' + relBtnIcon + '"></i> ' + relBtnLabel +
                    '</button>' +
                '</div>' +
            '</div>';

        // Collapse / expand handler
        document.getElementById('action-card-header').addEventListener('click', function () {
            this.closest('.ce-action-card').classList.toggle('collapsed');
        });

        document.getElementById('expl-card-header').addEventListener('click', function () {
            this.closest('.ce-action-card').classList.toggle('collapsed');
        });

        document.getElementById('rel-card-header').addEventListener('click', function () {
            this.closest('.ce-action-card').classList.toggle('collapsed');
        });

        document.getElementById('btn-start-setup').addEventListener('click', function () {
            enterSetupWizard();
        });

        // Skill mapping toggle handler
        var toggleEl = document.getElementById('skill-mapping-toggle');
        if (toggleEl) {
            toggleEl.addEventListener('change', function () {
                var enabled = this.checked;
                var icon = this.closest('.ce-inline-toggle').querySelector('.ce-inline-toggle-left i');
                icon.className = 'fa-solid fa-toggle-' + (enabled ? 'on' : 'off');
                fetch('/api/skill-mapping-toggle', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ courseId: courseId, enabled: enabled }),
                }).catch(function () {});
            });
        }

        // Explanation toggle handler
        var explToggleEl = document.getElementById('explanation-toggle');
        if (explToggleEl) {
            explToggleEl.addEventListener('change', function () {
                var enabled = this.checked;
                var icon = this.closest('.ce-inline-toggle').querySelector('.ce-inline-toggle-left i');
                icon.className = 'fa-solid fa-toggle-' + (enabled ? 'on' : 'off');
                // Send aliases so student pages with different courseIds can find the data
                var aliases = [];
                if (selectedCourse) {
                    if (selectedCourse.courseCode) aliases.push(selectedCourse.courseCode);
                    if (selectedCourse.id && selectedCourse.id !== courseId) aliases.push(selectedCourse.id);
                    if (selectedCourse.title) aliases.push(selectedCourse.title);
                }
                fetch('/api/explanation-toggle', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ courseId: courseId, enabled: enabled, aliases: aliases }),
                }).catch(function () {});
            });
        }

        // Generate explanations button
        document.getElementById('btn-generate-explanations').addEventListener('click', function () {
            if (explStatus === 'done') {
                if (!confirm('This will regenerate all answer explanations. Continue?')) return;
            }
            startExplanationGeneration(courseId);
        });

        // If already processing, start polling
        if (explStatus === 'processing') {
            startExplanationPolling(courseId);
        }

        // If done, show preview
        if (explStatus === 'done') {
            fetch('/api/explanation-status?courseId=' + encodeURIComponent(courseId))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.status === 'done' && data.explanations) showExplanationResults(data);
                }).catch(function () {});
        }

        // Relevance toggle handler
        var relToggleEl = document.getElementById('relevance-toggle');
        if (relToggleEl) {
            relToggleEl.addEventListener('change', function () {
                var enabled = this.checked;
                var icon = this.closest('.ce-inline-toggle').querySelector('.ce-inline-toggle-left i');
                icon.className = 'fa-solid fa-toggle-' + (enabled ? 'on' : 'off');
                fetch('/api/relevance-toggle', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ courseId: courseId, enabled: enabled }),
                }).catch(function () {});
            });
        }

        // Analyze relevance button
        document.getElementById('btn-analyze-relevance').addEventListener('click', function () {
            if (relStatus === 'done') {
                if (!confirm('This will re-analyze all questions for relevance. Continue?')) return;
            }
            startRelevanceAnalysis(courseId);
        });

        // If relevance already processing, start polling
        if (relStatus === 'processing') {
            startRelevancePolling(courseId);
        }

        // If relevance done, show results
        if (relStatus === 'done') {
            fetch('/api/relevance-status?courseId=' + encodeURIComponent(courseId))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.status === 'done' && data.results) showRelevanceResults(data);
                }).catch(function () {});
        }
    }

    function enterSetupWizard() {
        document.getElementById('course-actions').style.display = 'none';
        document.getElementById('setup-wizard').style.display = '';
        if (selectedCourse) loadSkillTreeState(selectedCourse.sourcedId);
    }

    async function loadSkillTreeState(courseId) {
        var actionsEl = document.getElementById('skill-tree-actions');
        var progressEl = document.getElementById('generation-progress');
        var exportEl = document.getElementById('skill-tree-export');
        actionsEl.innerHTML = '<div class="ce-progress-spinner" style="display:inline-block;"></div> Checking...';
        progressEl.style.display = 'none';
        exportEl.style.display = 'none';
        document.getElementById('lesson-mapping-section').style.display = 'none';
        document.getElementById('question-analysis-section').style.display = 'none';

        try {
            var resp = await fetch('/api/skill-tree-status?courseId=' + encodeURIComponent(courseId));
            var data = await resp.json();
            if (data.status === 'done' && data.mermaid) {
                currentMermaidCode = data.mermaid;
                showTreeActions(true);
                showSkillTreeComplete(data);
                showLessonMappingSection(courseId);
            } else if (data.status === 'processing') {
                showTreeActions(false, true);
                showProgress('Claude is generating the skill tree...', '');
                startPolling(courseId);
            } else {
                showTreeActions(false);
            }
        } catch (e) {
            showTreeActions(false);
        }
    }

    function showTreeActions(hasTree, isGenerating) {
        var el = document.getElementById('skill-tree-actions');
        if (isGenerating) {
            el.innerHTML = '<button class="ce-btn-generate" disabled><i class="fa-solid fa-spinner fa-spin"></i> Generating...</button>';
            return;
        }
        if (hasTree) {
            el.innerHTML = '<button class="ce-btn-secondary" id="btn-regenerate"><i class="fa-solid fa-arrows-rotate"></i> Regenerate Skill Tree</button>';
            document.getElementById('btn-regenerate').addEventListener('click', function () {
                if (confirm('This will replace the existing skill tree and lesson mappings. Continue?')) startGeneration();
            });
        } else {
            el.innerHTML =
                '<button class="ce-btn-generate" id="btn-generate"><i class="fa-solid fa-wand-magic-sparkles"></i> Generate Skill Tree</button>' +
                '<span style="font-size:0.82rem; color:var(--color-text-muted);">Uses Claude Opus 4.6 with extended thinking</span>';
            document.getElementById('btn-generate').addEventListener('click', function () { startGeneration(); });
        }
    }

    /* ---- Skill Tree Complete (Export UI) ----------------------------- */
    function showSkillTreeComplete(data) {
        var el = document.getElementById('skill-tree-export');
        el.style.display = '';
        var nodeCount = countMermaidNodes(data.mermaid);
        var genDate = data.generatedAt ? new Date(data.generatedAt * 1000).toLocaleString() : '';
        var preview = data.mermaid.split('\n').slice(0, 20).join('\n');

        el.innerHTML =
            '<div class="ce-export-header">' +
                '<div class="ce-export-status"><i class="fa-solid fa-circle-check"></i> Skill tree generated</div>' +
                '<div class="ce-export-meta">' +
                    '<span><i class="fa-solid fa-diagram-project"></i> ' + nodeCount + ' skill nodes</span>' +
                    (genDate ? '<span><i class="fa-regular fa-clock"></i> ' + esc(genDate) + '</span>' : '') +
                    (data.model ? '<span><i class="fa-solid fa-robot"></i> ' + esc(data.model) + '</span>' : '') +
                '</div>' +
            '</div>' +
            '<div class="ce-export-actions">' +
                '<button class="ce-btn-export" id="btn-copy-mermaid"><i class="fa-solid fa-copy"></i> Copy Code</button>' +
                '<button class="ce-btn-export" id="btn-download-mermaid"><i class="fa-solid fa-download"></i> Download .mmd</button>' +
                '<a href="https://mermaid.live" target="_blank" class="ce-btn-export" style="text-decoration:none;"><i class="fa-solid fa-external-link-alt"></i> Open Mermaid Live</a>' +
            '</div>' +
            '<details class="ce-export-preview"><summary>Preview raw mermaid code (first 20 lines)</summary>' +
                '<pre>' + esc(preview) + (data.mermaid.split('\n').length > 20 ? '\n... (' + data.mermaid.split('\n').length + ' total lines)' : '') + '</pre>' +
            '</details>';

        document.getElementById('btn-copy-mermaid').addEventListener('click', function () {
            navigator.clipboard.writeText(currentMermaidCode).then(function () {
                var btn = document.getElementById('btn-copy-mermaid');
                btn.innerHTML = '<i class="fa-solid fa-check"></i> Copied!';
                setTimeout(function () { btn.innerHTML = '<i class="fa-solid fa-copy"></i> Copy Code'; }, 2000);
            });
        });

        document.getElementById('btn-download-mermaid').addEventListener('click', function () {
            var blob = new Blob([currentMermaidCode], { type: 'text/plain' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = (selectedCourse ? selectedCourse.courseCode || selectedCourse.sourcedId : 'skill-tree') + '.mmd';
            a.click();
            URL.revokeObjectURL(url);
        });
    }

    /* ---- Page Leave Guard ------------------------------------------- */
    var activeGenerating = false;

    function onBeforeUnload(e) {
        if (activeGenerating) { e.preventDefault(); e.returnValue = ''; }
    }
    window.addEventListener('beforeunload', onBeforeUnload);

    /* ---- Generation Flow -------------------------------------------- */
    async function startGeneration() {
        if (!selectedCourse) return;
        activeGenerating = true;
        showTreeActions(false, true);
        showProgress('Submitting to Claude...', '');
        document.getElementById('skill-tree-export').style.display = 'none';
        document.getElementById('lesson-mapping-section').style.display = 'none';

        try {
            var resp = await fetch('/api/generate-skill-tree', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    courseId: selectedCourse.sourcedId,
                    courseTitle: selectedCourse.title,
                    courseCode: selectedCourse.courseCode || '',
                }),
            });
            var data = await resp.json();
            if (data.error) { showError(data.error); showTreeActions(false); activeGenerating = false; return; }
            showProgress('Claude is generating the skill tree...', '');
            startPolling(selectedCourse.sourcedId);
        } catch (e) {
            showError('Failed to start generation: ' + e.message);
            showTreeActions(false);
            activeGenerating = false;
        }
    }

    /* ---- Polling (Skill Tree) --------------------------------------- */
    function startPolling(courseId) {
        stopPolling();
        function poll() {
            fetch('/api/skill-tree-status?courseId=' + encodeURIComponent(courseId))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.status === 'done' && data.mermaid) {
                        activeGenerating = false;
                        stopPolling();
                        showProgress(null);
                        currentMermaidCode = data.mermaid;
                        showTreeActions(true);
                        showSkillTreeComplete(data);
                        showLessonMappingSection(courseId);
                        if (selectedCourse) { selectedCourse._hasTree = true; selectedCourse._generating = false; }
                    } else if (data.status === 'error') {
                        activeGenerating = false;
                        stopPolling();
                        showProgress(null);
                        showError(data.error || 'Generation failed. Please try again.');
                        showTreeActions(false);
                    } else {
                        showProgress('Claude is generating the skill tree...', '');
                        pollTimer = setTimeout(poll, POLL_INTERVAL);
                    }
                })
                .catch(function () { pollTimer = setTimeout(poll, POLL_INTERVAL); });
        }
        pollTimer = setTimeout(poll, POLL_INTERVAL);
    }

    function stopPolling() { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; } }

    /* ---- Progress UI ------------------------------------------------ */
    var progressStartTime = null;
    var progressTickTimer = null;

    function showProgress(title) {
        var el = document.getElementById('generation-progress');
        if (!title) { el.style.display = 'none'; stopProgressTick(); return; }
        el.style.display = '';
        if (!progressStartTime) progressStartTime = Date.now();
        var elapsed = Math.floor((Date.now() - progressStartTime) / 1000);

        el.innerHTML =
            '<div class="ce-progress-header"><div class="ce-progress-spinner"></div><div class="ce-progress-title">' + esc(title) + '</div></div>' +
            '<div class="ce-progress-elapsed"><i class="fa-regular fa-clock" style="margin-right:6px;"></i>Elapsed: <strong>' + formatTime(elapsed) + '</strong></div>' +
            '<div class="ce-warning"><i class="fa-solid fa-triangle-exclamation"></i> Please do not leave or close this page until generation is complete. The process cannot resume if interrupted.</div>' +
            '<div class="ce-progress-steps">' +
                '<div class="ce-step done"><i class="fa-solid fa-check-circle"></i><div><strong>Prompt submitted</strong><span>Course data and lesson names sent to Claude</span></div></div>' +
                '<div class="ce-step ' + (elapsed >= 5 ? 'active' : '') + '"><i class="fa-solid ' + (elapsed >= 5 ? 'fa-spinner fa-spin' : 'fa-circle') + '"></i><div><strong>Deep analysis in progress</strong><span>Claude is reviewing pedagogical research and mapping prerequisite relationships between micro-skills</span></div></div>' +
                '<div class="ce-step"><i class="fa-solid fa-circle"></i><div><strong>Building skill chart</strong><span>Structuring hundreds of skills into a dependency graph</span></div></div>' +
            '</div>' +
            '<div class="ce-progress-info">' +
                '<div class="ce-info-card"><div class="ce-info-icon"><i class="fa-solid fa-lightbulb"></i></div><div><strong>What is a skill tree?</strong><p>A skill tree maps every micro-skill in a course and shows how they depend on each other. For example, a student needs to "Identify the three branches of government" before they can "Compare the powers of Congress vs. the Executive branch."</p></div></div>' +
                '<div class="ce-info-card"><div class="ce-info-icon"><i class="fa-solid fa-graduation-cap"></i></div><div><strong>Why is this useful?</strong><p>Skill trees enable personalized learning paths. Instead of making every student go through the same linear sequence, the system can identify exactly which prerequisite skills a student is missing and target those gaps directly.</p></div></div>' +
                '<div class="ce-info-card"><div class="ce-info-icon"><i class="fa-solid fa-brain"></i></div><div><strong>How does it work?</strong><p>Claude Opus 4.6 with extended thinking analyzes your course structure against peer-reviewed AP curriculum standards, identifying hundreds of fact-based skills and mapping which are prerequisites for others. This typically takes 5-10 minutes.</p></div></div>' +
            '</div>';
        startProgressTick();
    }

    function startProgressTick() {
        if (progressTickTimer) return;
        progressTickTimer = setInterval(function () {
            var el = document.getElementById('generation-progress');
            if (!el || el.style.display === 'none') { stopProgressTick(); return; }
            var elapsedEl = el.querySelector('.ce-progress-elapsed strong');
            if (elapsedEl && progressStartTime) {
                var elapsed = Math.floor((Date.now() - progressStartTime) / 1000);
                elapsedEl.textContent = formatTime(elapsed);
                var steps = el.querySelectorAll('.ce-step');
                if (steps[1] && elapsed >= 5) {
                    steps[1].classList.add('active');
                    var ic = steps[1].querySelector('i');
                    if (ic && !ic.classList.contains('fa-spinner')) ic.className = 'fa-solid fa-spinner fa-spin';
                }
            }
        }, 1000);
    }

    function stopProgressTick() {
        if (progressTickTimer) { clearInterval(progressTickTimer); progressTickTimer = null; }
        progressStartTime = null;
    }

    function showError(msg) {
        var el = document.getElementById('generation-progress');
        el.style.display = '';
        el.innerHTML = '<div class="ce-error"><i class="fa-solid fa-circle-exclamation" style="margin-right:6px;"></i>' + esc(msg) + '</div>';
    }

    /* ==================================================================
       STEP 2: LESSON MAPPING
       ================================================================== */

    function showLessonMappingSection(courseId) {
        var section = document.getElementById('lesson-mapping-section');
        section.style.display = '';
        var actionsEl = document.getElementById('lesson-mapping-actions');
        var progressEl = document.getElementById('lesson-mapping-progress');
        var resultsEl = document.getElementById('lesson-mapping-results');
        progressEl.style.display = 'none';
        resultsEl.style.display = 'none';
        actionsEl.innerHTML = '<div class="ce-progress-spinner" style="display:inline-block;"></div> Checking lesson mappings...';
        loadLessonMappingState(courseId);
    }

    async function loadLessonMappingState(courseId) {
        var actionsEl = document.getElementById('lesson-mapping-actions');
        try {
            var resp = await fetch('/api/lesson-mapping-status?courseId=' + encodeURIComponent(courseId));
            var data = await resp.json();
            if (data.status === 'done' && data.mapping) {
                showLessonMappingActions(true);
                showLessonMappingResults(data.mapping);
                showQuestionAnalysisSection(courseId);
            } else if (data.status === 'processing') {
                showLessonMappingActions(false, true);
                showLessonMappingProgress('Claude is mapping lessons to skills...');
                startLessonPolling(courseId);
            } else {
                showLessonMappingActions(false);
            }
        } catch (e) {
            showLessonMappingActions(false);
        }
    }

    function showLessonMappingActions(hasMappings, isProcessing) {
        var el = document.getElementById('lesson-mapping-actions');
        if (isProcessing) {
            el.innerHTML = '<button class="ce-btn-generate" disabled><i class="fa-solid fa-spinner fa-spin"></i> Mapping in progress...</button>';
            return;
        }
        if (hasMappings) {
            el.innerHTML = '<button class="ce-btn-secondary" id="btn-remap-lessons"><i class="fa-solid fa-arrows-rotate"></i> Re-map Lessons</button>';
            document.getElementById('btn-remap-lessons').addEventListener('click', function () {
                if (confirm('This will regenerate all lesson-to-skill mappings. Continue?')) startLessonMapping();
            });
        } else {
            el.innerHTML =
                '<button class="ce-btn-generate" id="btn-map-lessons"><i class="fa-solid fa-wand-magic-sparkles"></i> Map Lessons to Skills</button>' +
                '<span style="font-size:0.82rem; color:var(--color-text-muted);">Uses Claude to map each lesson to specific skills from the tree</span>';
            document.getElementById('btn-map-lessons').addEventListener('click', function () { startLessonMapping(); });
        }
    }

    async function startLessonMapping() {
        if (!selectedCourse) return;
        activeGenerating = true;
        showLessonMappingActions(false, true);
        showLessonMappingProgress('Submitting lesson mapping request...');
        document.getElementById('lesson-mapping-results').style.display = 'none';

        try {
            var resp = await fetch('/api/map-lessons-to-skills', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ courseId: selectedCourse.sourcedId }),
            });
            var data = await resp.json();
            if (data.error) {
                showLessonMappingError(data.error);
                showLessonMappingActions(false);
                activeGenerating = false;
                return;
            }
            showLessonMappingProgress('Claude is mapping lessons to skills...');
            startLessonPolling(selectedCourse.sourcedId);
        } catch (e) {
            showLessonMappingError('Failed to start mapping: ' + e.message);
            showLessonMappingActions(false);
            activeGenerating = false;
        }
    }

    /* ---- Lesson Mapping Polling -------------------------------------- */
    function startLessonPolling(courseId) {
        stopLessonPolling();
        var startTime = Date.now();
        function poll() {
            fetch('/api/lesson-mapping-status?courseId=' + encodeURIComponent(courseId))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.status === 'done' && data.mapping) {
                        activeGenerating = false;
                        stopLessonPolling();
                        document.getElementById('lesson-mapping-progress').style.display = 'none';
                        showLessonMappingActions(true);
                        showLessonMappingResults(data.mapping);
                        if (selectedCourse) showQuestionAnalysisSection(selectedCourse.sourcedId);
                    } else if (data.status === 'error') {
                        activeGenerating = false;
                        stopLessonPolling();
                        document.getElementById('lesson-mapping-progress').style.display = 'none';
                        showLessonMappingError(data.error || 'Mapping failed.');
                        showLessonMappingActions(false);
                    } else {
                        var elapsed = Math.floor((Date.now() - startTime) / 1000);
                        showLessonMappingProgress('Claude is mapping lessons to skills... (' + formatTime(elapsed) + ')');
                        lessonPollTimer = setTimeout(poll, POLL_INTERVAL);
                    }
                })
                .catch(function () { lessonPollTimer = setTimeout(poll, POLL_INTERVAL); });
        }
        lessonPollTimer = setTimeout(poll, POLL_INTERVAL);
    }

    function stopLessonPolling() { if (lessonPollTimer) { clearTimeout(lessonPollTimer); lessonPollTimer = null; } }

    function showLessonMappingProgress(msg) {
        var el = document.getElementById('lesson-mapping-progress');
        el.style.display = '';
        el.innerHTML =
            '<div class="ce-progress-header"><div class="ce-progress-spinner"></div><div class="ce-progress-title">' + esc(msg) + '</div></div>' +
            '<div class="ce-warning"><i class="fa-solid fa-triangle-exclamation"></i> Please do not leave this page until mapping is complete.</div>';
    }

    function showLessonMappingError(msg) {
        var el = document.getElementById('lesson-mapping-progress');
        el.style.display = '';
        el.innerHTML = '<div class="ce-error"><i class="fa-solid fa-circle-exclamation" style="margin-right:6px;"></i>' + esc(msg) + '</div>';
    }

    /* ---- Lesson Mapping Results ------------------------------------- */
    function showLessonMappingResults(mapping) {
        var el = document.getElementById('lesson-mapping-results');
        el.style.display = '';

        // Build a node ID -> label lookup from the mermaid code
        var nodeLabels = {};
        if (currentMermaidCode) {
            var re = /(\w+)\["([^"]+)"\]/g, m;
            while ((m = re.exec(currentMermaidCode)) !== null) {
                nodeLabels[m[1]] = m[2];
            }
        }

        var lessonNames = Object.keys(mapping);
        if (!lessonNames.length) {
            el.innerHTML = '<div class="ce-empty-state"><p>No lesson mappings were generated.</p></div>';
            return;
        }

        var html = '<div class="ce-mapping-count">' + lessonNames.length + ' lesson' + (lessonNames.length !== 1 ? 's' : '') + ' mapped to skills</div>';
        html += '<div class="ce-accordion">';
        lessonNames.forEach(function (name, idx) {
            var skillIds = mapping[name] || [];
            html += '<div class="ce-accordion-item">' +
                '<button class="ce-accordion-header" data-idx="' + idx + '">' +
                    '<span class="ce-accordion-title"><i class="fa-solid fa-book-open" style="margin-right:8px; opacity:0.5;"></i>' + esc(name) + '</span>' +
                    '<span class="ce-accordion-badge">' + skillIds.length + ' skill' + (skillIds.length !== 1 ? 's' : '') + '</span>' +
                    '<i class="fa-solid fa-chevron-right ce-accordion-chevron"></i>' +
                '</button>' +
                '<div class="ce-accordion-body" id="acc-body-' + idx + '">';
            if (skillIds.length) {
                html += '<ul class="ce-skill-list">';
                skillIds.forEach(function (sid) {
                    var label = nodeLabels[sid] || sid;
                    html += '<li><span class="ce-skill-id">' + esc(sid) + '</span> ' + esc(label) + '</li>';
                });
                html += '</ul>';
            } else {
                html += '<p class="ce-no-skills">No skills mapped to this lesson.</p>';
            }
            html += '</div></div>';
        });
        html += '</div>';
        el.innerHTML = html;

        // Accordion toggle
        el.querySelectorAll('.ce-accordion-header').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var item = this.closest('.ce-accordion-item');
                item.classList.toggle('open');
            });
        });
    }

    /* ==================================================================
       STEP 3: QUESTION ANALYSIS
       ================================================================== */
    var questionPollTimer = null;

    function showQuestionAnalysisSection(courseId) {
        var section = document.getElementById('question-analysis-section');
        section.style.display = '';
        var actionsEl = document.getElementById('question-analysis-actions');
        var progressEl = document.getElementById('question-analysis-progress');
        var resultsEl = document.getElementById('question-analysis-results');
        progressEl.style.display = 'none';
        resultsEl.style.display = 'none';
        actionsEl.innerHTML = '<div class="ce-progress-spinner" style="display:inline-block;"></div> Checking question analysis...';
        loadQuestionAnalysisState(courseId);
    }

    async function loadQuestionAnalysisState(courseId) {
        try {
            var resp = await fetch('/api/question-analysis-status?courseId=' + encodeURIComponent(courseId));
            var data = await resp.json();
            if (data.status === 'done' && data.analysis) {
                showQuestionAnalysisActions(true);
                showQuestionAnalysisResults(data);
            } else if (data.status === 'processing') {
                showQuestionAnalysisActions(false, true);
                showQuestionAnalysisProgress('Claude is analyzing questions...', data.elapsed || 0);
                startQuestionPolling(courseId);
            } else {
                showQuestionAnalysisActions(false);
            }
        } catch (e) {
            showQuestionAnalysisActions(false);
        }
    }

    function showQuestionAnalysisActions(hasAnalysis, isProcessing) {
        var el = document.getElementById('question-analysis-actions');
        if (isProcessing) {
            el.innerHTML = '<button class="ce-btn-generate" disabled><i class="fa-solid fa-spinner fa-spin"></i> Analyzing questions...</button>';
            return;
        }
        if (hasAnalysis) {
            el.innerHTML = '<button class="ce-btn-secondary" id="btn-reanalyze"><i class="fa-solid fa-arrows-rotate"></i> Re-analyze Questions</button>';
            document.getElementById('btn-reanalyze').addEventListener('click', function () {
                if (confirm('This will re-fetch all questions and re-run the analysis. Continue?')) startQuestionAnalysis();
            });
        } else {
            el.innerHTML =
                '<button class="ce-btn-generate" id="btn-analyze-questions"><i class="fa-solid fa-wand-magic-sparkles"></i> Analyze Questions</button>' +
                '<span style="font-size:0.82rem; color:var(--color-text-muted);">Fetches all questions from QTI, then uses Claude to map each to skills</span>';
            document.getElementById('btn-analyze-questions').addEventListener('click', function () { startQuestionAnalysis(); });
        }
    }

    /* ---- Phase 1 & 2: Find tests, fetch questions ------------------- */
    async function startQuestionAnalysis() {
        if (!selectedCourse) return;
        activeGenerating = true;
        showQuestionAnalysisActions(false, true);
        document.getElementById('question-analysis-results').style.display = 'none';

        showQuestionAnalysisProgress('Setting up course access and finding tests (this may take a minute on first run)...', 0);

        try {
            // Phase 1: Find tests (may enroll+sync on first call — can take 30-60s)
            var findResp = await fetch('/api/find-course-tests', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    courseId: selectedCourse.sourcedId,
                    courseCode: selectedCourse.courseCode || '',
                }),
                signal: AbortSignal.timeout ? AbortSignal.timeout(120000) : undefined, // 2 min timeout
            });
            var findData = await findResp.json();
            var tests = findData.tests || [];

            if (!tests.length) {
                showQuestionAnalysisError('No assessment tests found for this course (code: ' + esc(selectedCourse.courseCode || 'none') + '). The QTI catalog may not have content for this course.');
                showQuestionAnalysisActions(false);
                activeGenerating = false;
                return;
            }

            showQuestionAnalysisProgress('Found ' + tests.length + ' tests. Fetching questions (auto-enrolling staging account if needed)...', 0);

            // Phase 2: Fetch questions from each test
            // Use correct endpoint based on lessonType, pass courseId for auto-enrollment
            var courseId = selectedCourse.sourcedId;
            var allQuestions = [];
            var fetched = 0;
            var testSucceeded = 0;
            var testFailed = 0;
            var testErrors = [];
            var BATCH = 3;

            function fetchTestQuestions(t) {
                // Build URL for pp-get-questions-admin which handles all approaches:
                // - QTI URL (if available from tree)
                // - PowerPath getAssessmentProgress (using resource ID as lessonId)
                // - Bank ID → QTI test ID transformation
                var params = [];
                if (t.id) params.push('lessonId=' + encodeURIComponent(t.id));
                if (t.url) params.push('url=' + encodeURIComponent(t.url));
                if (courseId) params.push('courseId=' + encodeURIComponent(courseId));
                var url = '/api/pp-get-questions-admin?' + params.join('&');
                return fetch(url)
                    .then(function (r) { return r.json(); })
                    .then(function (d) {
                        if (d.success && d.data && d.data.questions && d.data.questions.length > 0) {
                            return { questions: d.data.questions, error: null };
                        }
                        return { questions: [], error: d.error || 'No questions returned' };
                    })
                    .catch(function (e) { return { questions: [], error: e.message || 'Network error' }; });
            }

            for (var i = 0; i < tests.length; i += BATCH) {
                var batch = tests.slice(i, i + BATCH);
                var promises = batch.map(function (t, batchIdx) {
                    return fetchTestQuestions(t).then(function (result) {
                        return { test: t, result: result };
                    });
                });
                var results = await Promise.all(promises);
                results.forEach(function (r) {
                    if (r.result.questions.length > 0) {
                        allQuestions = allQuestions.concat(r.result.questions);
                        testSucceeded++;
                    } else {
                        testFailed++;
                        testErrors.push({ title: r.test.title, error: r.result.error, id: r.test.id });
                    }
                });
                fetched += batch.length;
                showQuestionAnalysisProgress(
                    'Fetching questions: ' + fetched + '/' + tests.length + ' tests (' + allQuestions.length + ' questions from ' + testSucceeded + ' tests)...',
                    0
                );
            }

            // Show results summary even if partial
            if (!allQuestions.length) {
                var errMsg = 'No questions could be fetched from any of the ' + tests.length + ' tests found.';
                if (testErrors.length) {
                    errMsg += '\n\nPer-test errors:';
                    testErrors.forEach(function (e) {
                        errMsg += '\n  - ' + e.title + ': ' + e.error;
                    });
                }
                showQuestionAnalysisError(errMsg);
                showQuestionAnalysisActions(false);
                activeGenerating = false;
                return;
            }

            // Show warning if some tests failed but we still have questions
            if (testFailed > 0) {
                showQuestionAnalysisProgress(
                    'Fetched ' + allQuestions.length + ' questions from ' + testSucceeded + '/' + tests.length + ' tests. ' + testFailed + ' test(s) had errors. Proceeding with available questions...',
                    0
                );
            }

            showQuestionAnalysisProgress('Submitting ' + allQuestions.length + ' questions for AI analysis...', 0);

            // Phase 3: Submit for analysis
            var analyzeResp = await fetch('/api/analyze-questions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    courseId: selectedCourse.sourcedId,
                    questions: allQuestions,
                }),
            });
            var analyzeData = await analyzeResp.json();

            if (analyzeData.error) {
                showQuestionAnalysisError(analyzeData.error);
                showQuestionAnalysisActions(false);
                activeGenerating = false;
                return;
            }

            showQuestionAnalysisProgress('Claude is analyzing ' + (analyzeData.questionCount || allQuestions.length) + ' questions across ' + (analyzeData.chunkCount || 1) + ' batches...', 0);
            startQuestionPolling(selectedCourse.sourcedId);

        } catch (e) {
            showQuestionAnalysisError('Failed: ' + e.message);
            showQuestionAnalysisActions(false);
            activeGenerating = false;
        }
    }

    /* ---- Phase 4: Poll for results ---------------------------------- */
    function startQuestionPolling(courseId) {
        stopQuestionPolling();
        var startTime = Date.now();
        function poll() {
            fetch('/api/question-analysis-status?courseId=' + encodeURIComponent(courseId))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.status === 'done' && data.analysis) {
                        activeGenerating = false;
                        stopQuestionPolling();
                        document.getElementById('question-analysis-progress').style.display = 'none';
                        showQuestionAnalysisActions(true);
                        showQuestionAnalysisResults(data);
                    } else if (data.status === 'error') {
                        activeGenerating = false;
                        stopQuestionPolling();
                        document.getElementById('question-analysis-progress').style.display = 'none';
                        showQuestionAnalysisError(data.error || 'Analysis failed.');
                        showQuestionAnalysisActions(false);
                    } else {
                        var elapsed = Math.floor((Date.now() - startTime) / 1000);
                        var chunkInfo = data.chunkCount ? ' (' + (data.succeeded || 0) + '/' + data.chunkCount + ' chunks done)' : '';
                        showQuestionAnalysisProgress('Claude is analyzing questions...' + chunkInfo, elapsed);
                        questionPollTimer = setTimeout(poll, POLL_INTERVAL);
                    }
                })
                .catch(function () { questionPollTimer = setTimeout(poll, POLL_INTERVAL); });
        }
        questionPollTimer = setTimeout(poll, POLL_INTERVAL);
    }

    function stopQuestionPolling() { if (questionPollTimer) { clearTimeout(questionPollTimer); questionPollTimer = null; } }

    function showQuestionAnalysisProgress(msg, elapsed) {
        var el = document.getElementById('question-analysis-progress');
        el.style.display = '';
        var timeStr = elapsed > 0 ? ' <span style="opacity:0.6;">(' + formatTime(elapsed) + ')</span>' : '';
        el.innerHTML =
            '<div class="ce-progress-header"><div class="ce-progress-spinner"></div><div class="ce-progress-title">' + msg + timeStr + '</div></div>' +
            '<div class="ce-warning"><i class="fa-solid fa-triangle-exclamation"></i> Please do not leave this page until analysis is complete.</div>';
    }

    function showQuestionAnalysisError(msg) {
        var el = document.getElementById('question-analysis-progress');
        el.style.display = '';
        el.innerHTML = '<div class="ce-error"><i class="fa-solid fa-circle-exclamation" style="margin-right:6px;"></i>' + esc(msg) + '</div>';
    }

    /* ---- Question Analysis Results ---------------------------------- */
    function showQuestionAnalysisResults(data) {
        var el = document.getElementById('question-analysis-results');
        el.style.display = '';
        var analysis = data.analysis || {};
        var qIds = Object.keys(analysis);

        // Build node label lookup from mermaid code
        var nodeLabels = {};
        if (currentMermaidCode) {
            var re = /(\w+)\["([^"]+)"\]/g, m;
            while ((m = re.exec(currentMermaidCode)) !== null) {
                nodeLabels[m[1]] = m[2];
            }
        }

        // Load raw questions for display text
        var rawQuestions = {};
        var savedQs = data._rawQuestions || {};
        // We'll try to get question text from the analysis keys or stored data

        var html = '<div class="ce-mapping-count"><i class="fa-solid fa-circle-check" style="color:#45B5AA; margin-right:6px;"></i>' +
            qIds.length + ' question' + (qIds.length !== 1 ? 's' : '') + ' analyzed' +
            (data.model ? ' <span style="opacity:0.5;">(' + esc(data.model) + ')</span>' : '') + '</div>';

        html += '<div class="ce-accordion">';
        qIds.forEach(function (qid, idx) {
            var q = analysis[qid];
            var skills = q.relatedSkills || [];
            var correct = q.correctAnswer || {};
            var wrong = q.wrongAnswers || {};
            var wrongKeys = Object.keys(wrong);

            // Skill badges
            var skillBadges = skills.slice(0, 5).map(function (sid) {
                return '<span class="ce-skill-id">' + esc(sid) + '</span>';
            }).join(' ');
            if (skills.length > 5) skillBadges += ' <span class="ce-skill-id">+' + (skills.length - 5) + '</span>';

            html += '<div class="ce-accordion-item">' +
                '<button class="ce-accordion-header" data-idx="q' + idx + '">' +
                    '<span class="ce-accordion-title"><i class="fa-solid fa-circle-question" style="margin-right:8px; opacity:0.4;"></i>Q: ' + esc(qid) + '</span>' +
                    '<span class="ce-accordion-badge">' + skills.length + ' skill' + (skills.length !== 1 ? 's' : '') + '</span>' +
                    '<i class="fa-solid fa-chevron-right ce-accordion-chevron"></i>' +
                '</button>' +
                '<div class="ce-accordion-body" id="qa-body-' + idx + '">';

            // Related skills
            html += '<div class="ce-qa-section"><strong>Related Skills:</strong><div class="ce-qa-skills">';
            skills.forEach(function (sid) {
                var label = nodeLabels[sid] || sid;
                html += '<div class="ce-qa-skill-item"><span class="ce-skill-id">' + esc(sid) + '</span> ' + esc(label) + '</div>';
            });
            html += '</div></div>';

            // Correct answer
            if (correct.id) {
                html += '<div class="ce-qa-section ce-qa-correct"><strong><i class="fa-solid fa-check-circle" style="color:#45B5AA; margin-right:4px;"></i>Correct Answer (' + esc(correct.id) + '):</strong>';
                html += '<div class="ce-qa-detail">Demonstrates knowledge of: ';
                (correct.indicatesKnowledge || []).forEach(function (sid) {
                    html += '<span class="ce-skill-id">' + esc(sid) + '</span> ';
                });
                html += '</div></div>';
            }

            // Wrong answers
            if (wrongKeys.length) {
                html += '<div class="ce-qa-section"><strong><i class="fa-solid fa-times-circle" style="color:#E53E3E; margin-right:4px;"></i>Wrong Answer Analysis:</strong>';
                wrongKeys.forEach(function (wid) {
                    var w = wrong[wid];
                    html += '<div class="ce-qa-wrong-item">';
                    html += '<div class="ce-qa-wrong-id">Choice ' + esc(wid) + ':</div>';
                    html += '<div class="ce-qa-wrong-detail">';
                    if (w.indicatesMisunderstanding && w.indicatesMisunderstanding.length) {
                        html += '<span class="ce-qa-label">Missing skills:</span> ';
                        w.indicatesMisunderstanding.forEach(function (sid) {
                            html += '<span class="ce-skill-id">' + esc(sid) + '</span> ';
                        });
                    }
                    if (w.reasoning) {
                        html += '<div class="ce-qa-reasoning">' + esc(w.reasoning) + '</div>';
                    }
                    html += '</div></div>';
                });
                html += '</div>';
            }

            html += '</div></div>';
        });
        html += '</div>';
        el.innerHTML = html;

        // Accordion toggle
        el.querySelectorAll('.ce-accordion-header').forEach(function (btn) {
            btn.addEventListener('click', function () {
                this.closest('.ce-accordion-item').classList.toggle('open');
            });
        });
    }

    /* ---- Answer Explanation Generation -------------------------------- */
    async function startExplanationGeneration(courseId) {
        if (!selectedCourse) return;
        activeGenerating = true;
        var btn = document.getElementById('btn-generate-explanations');
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Setting up...'; }

        showExplProgress('Setting up course access and finding tests...', 0);

        try {
            // Phase 1: Find tests
            var findResp = await fetch('/api/find-course-tests', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    courseId: selectedCourse.sourcedId,
                    courseCode: selectedCourse.courseCode || '',
                }),
                signal: AbortSignal.timeout ? AbortSignal.timeout(120000) : undefined,
            });
            var findData = await findResp.json();
            var tests = findData.tests || [];

            if (!tests.length) {
                showExplError('No assessment tests found for this course.');
                if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate Explanations'; }
                activeGenerating = false;
                return;
            }

            showExplProgress('Found ' + tests.length + ' tests. Fetching questions...', 0);

            // Phase 2: Fetch questions from each test
            var allQuestions = [];
            var fetched = 0;
            var testSucceeded = 0;
            var BATCH = 3;

            function fetchTestQuestions(t) {
                var params = [];
                if (t.id) params.push('lessonId=' + encodeURIComponent(t.id));
                if (t.url) params.push('url=' + encodeURIComponent(t.url));
                if (courseId) params.push('courseId=' + encodeURIComponent(courseId));
                var url = '/api/pp-get-questions-admin?' + params.join('&');
                return fetch(url)
                    .then(function (r) { return r.json(); })
                    .then(function (d) {
                        if (d.success && d.data && d.data.questions && d.data.questions.length > 0) {
                            return { questions: d.data.questions, error: null };
                        }
                        return { questions: [], error: d.error || 'No questions returned' };
                    })
                    .catch(function (e) { return { questions: [], error: e.message || 'Network error' }; });
            }

            for (var i = 0; i < tests.length; i += BATCH) {
                var batch = tests.slice(i, i + BATCH);
                var promises = batch.map(function (t) {
                    return fetchTestQuestions(t).then(function (result) {
                        return { test: t, result: result };
                    });
                });
                var results = await Promise.all(promises);
                results.forEach(function (r) {
                    if (r.result.questions.length > 0) {
                        allQuestions = allQuestions.concat(r.result.questions);
                        testSucceeded++;
                    }
                });
                fetched += batch.length;
                showExplProgress('Fetching questions: ' + fetched + '/' + tests.length + ' tests (' + allQuestions.length + ' questions)...', 0);
            }

            if (!allQuestions.length) {
                showExplError('No questions could be fetched from any of the ' + tests.length + ' tests.');
                if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate Explanations'; }
                activeGenerating = false;
                return;
            }

            showExplProgress('Submitting ' + allQuestions.length + ' questions for AI explanation generation...', 0);

            // Phase 3: Submit for explanation generation
            var genResp = await fetch('/api/generate-explanations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    courseId: selectedCourse.sourcedId,
                    questions: allQuestions,
                }),
            });
            var genData = await genResp.json();

            if (genData.error) {
                showExplError(genData.error);
                if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate Explanations'; }
                activeGenerating = false;
                return;
            }

            showExplProgress('Claude is generating explanations for ' + (genData.questionCount || allQuestions.length) + ' questions across ' + (genData.chunkCount || 1) + ' batches...', 0);
            startExplanationPolling(selectedCourse.sourcedId);

        } catch (e) {
            showExplError('Failed: ' + e.message);
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate Explanations'; }
            activeGenerating = false;
        }
    }

    function startExplanationPolling(courseId) {
        stopExplanationPolling();
        var startTime = Date.now();
        function poll() {
            fetch('/api/explanation-status?courseId=' + encodeURIComponent(courseId))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.status === 'done' && data.explanations) {
                        activeGenerating = false;
                        stopExplanationPolling();
                        document.getElementById('expl-progress').style.display = 'none';
                        var btn = document.getElementById('btn-generate-explanations');
                        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Regenerate Explanations'; }

                        // Update badge to "complete"
                        var header = document.getElementById('expl-card-header');
                        if (header) {
                            var badge = header.querySelector('.ce-action-card-summary');
                            if (badge) {
                                badge.className = 'ce-action-card-summary all-done';
                                badge.innerHTML = '<i class="fa-solid fa-check-circle"></i> ' + (data.questionCount || Object.keys(data.explanations).length) + ' questions';
                            }
                            // Expand the card if collapsed
                            var card = header.closest('.ce-action-card');
                            if (card && card.classList.contains('collapsed')) card.classList.remove('collapsed');
                        }

                        // Insert toggle if not already present
                        if (!document.getElementById('explanation-toggle')) {
                            var toggleContainer = document.createElement('div');
                            toggleContainer.className = 'ce-inline-toggle';
                            toggleContainer.innerHTML =
                                '<div class="ce-inline-toggle-left">' +
                                    '<i class="fa-solid fa-toggle-off"></i>' +
                                    '<strong>Answer Explanations</strong>' +
                                    '<span>Show AI explanations for wrong answers</span>' +
                                '</div>' +
                                '<label class="ce-switch">' +
                                    '<input type="checkbox" id="explanation-toggle">' +
                                    '<span class="ce-switch-slider"></span>' +
                                '</label>';
                            var progressEl = document.getElementById('expl-progress');
                            if (progressEl && progressEl.parentNode) {
                                progressEl.parentNode.insertBefore(toggleContainer, progressEl);
                            }
                            // Wire up toggle handler
                            var newToggle = document.getElementById('explanation-toggle');
                            if (newToggle) {
                                newToggle.addEventListener('change', function () {
                                    var enabled = this.checked;
                                    var icon = this.closest('.ce-inline-toggle').querySelector('.ce-inline-toggle-left i');
                                    icon.className = 'fa-solid fa-toggle-' + (enabled ? 'on' : 'off');
                                    var aliases = [];
                                    if (selectedCourse) {
                                        if (selectedCourse.courseCode) aliases.push(selectedCourse.courseCode);
                                        if (selectedCourse.id && selectedCourse.id !== courseId) aliases.push(selectedCourse.id);
                                        if (selectedCourse.title) aliases.push(selectedCourse.title);
                                    }
                                    fetch('/api/explanation-toggle', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify({ courseId: courseId, enabled: enabled, aliases: aliases }),
                                    }).catch(function () {});
                                });
                            }
                        }

                        showExplanationResults(data);
                    } else if (data.status === 'error') {
                        activeGenerating = false;
                        stopExplanationPolling();
                        document.getElementById('expl-progress').style.display = 'none';
                        showExplError(data.error || 'Generation failed.');
                        var btn = document.getElementById('btn-generate-explanations');
                        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate Explanations'; }
                    } else {
                        var elapsed = Math.floor((Date.now() - startTime) / 1000);
                        var chunkInfo = data.chunkCount ? ' (' + (data.succeeded || 0) + '/' + data.chunkCount + ' chunks done)' : '';
                        showExplProgress('Claude is generating explanations...' + chunkInfo, elapsed);
                        explanationPollTimer = setTimeout(poll, POLL_INTERVAL);
                    }
                })
                .catch(function () { explanationPollTimer = setTimeout(poll, POLL_INTERVAL); });
        }
        explanationPollTimer = setTimeout(poll, POLL_INTERVAL);
    }

    function stopExplanationPolling() { if (explanationPollTimer) { clearTimeout(explanationPollTimer); explanationPollTimer = null; } }

    function showExplProgress(msg, elapsed) {
        var el = document.getElementById('expl-progress');
        if (!el) return;
        el.style.display = '';
        var timeStr = elapsed > 0 ? ' <span style="opacity:0.6;">(' + formatTime(elapsed) + ')</span>' : '';
        el.innerHTML =
            '<div class="ce-progress-header"><div class="ce-progress-spinner"></div><div class="ce-progress-title">' + msg + timeStr + '</div></div>' +
            '<div class="ce-warning"><i class="fa-solid fa-triangle-exclamation"></i> Please do not leave this page until generation is complete.</div>';
    }

    function showExplError(msg) {
        var el = document.getElementById('expl-progress');
        if (!el) return;
        el.style.display = '';
        el.innerHTML = '<div class="ce-error"><i class="fa-solid fa-circle-exclamation" style="margin-right:6px;"></i>' + esc(msg) + '</div>';
    }

    function showExplanationResults(data) {
        var el = document.getElementById('expl-results');
        if (!el) return;
        el.style.display = '';
        var explanations = data.explanations || {};
        var qIds = Object.keys(explanations);

        var genDate = data.generatedAt ? new Date(data.generatedAt * 1000).toLocaleString() : '';

        var html = '<div class="ce-mapping-count" style="margin-top:12px;"><i class="fa-solid fa-circle-check" style="color:#45B5AA; margin-right:6px;"></i>' +
            qIds.length + ' question' + (qIds.length !== 1 ? 's' : '') + ' with explanations' +
            (data.model ? ' <span style="opacity:0.5;">(' + esc(data.model) + ')</span>' : '') +
            (genDate ? ' <span style="opacity:0.5;">&middot; ' + esc(genDate) + '</span>' : '') +
            '</div>';

        // Show first 10 questions as a preview
        var previewIds = qIds.slice(0, 10);
        if (previewIds.length) {
            html += '<div class="ce-accordion" style="margin-top:8px;">';
            previewIds.forEach(function (qid, idx) {
                var choices = explanations[qid] || {};
                var choiceIds = Object.keys(choices);

                html += '<div class="ce-accordion-item">' +
                    '<button class="ce-accordion-header" data-idx="expl' + idx + '">' +
                        '<span class="ce-accordion-title"><i class="fa-solid fa-circle-question" style="margin-right:8px; opacity:0.4;"></i>' + esc(qid) + '</span>' +
                        '<span class="ce-accordion-badge">' + choiceIds.length + ' explanation' + (choiceIds.length !== 1 ? 's' : '') + '</span>' +
                        '<i class="fa-solid fa-chevron-right ce-accordion-chevron"></i>' +
                    '</button>' +
                    '<div class="ce-accordion-body" id="expl-body-' + idx + '">';

                choiceIds.forEach(function (cid) {
                    html += '<div style="margin-bottom:10px;">' +
                        '<div style="font-weight:600; font-size:0.82rem; color:var(--color-text-muted); margin-bottom:2px;">Choice ' + esc(cid) + ':</div>' +
                        '<div style="font-size:0.88rem; line-height:1.5; color:var(--color-text);">' + esc(choices[cid]) + '</div>' +
                    '</div>';
                });

                html += '</div></div>';
            });
            html += '</div>';
            if (qIds.length > 10) {
                html += '<div style="font-size:0.82rem; color:var(--color-text-muted); margin-top:8px;">Showing 10 of ' + qIds.length + ' questions. All explanations are saved and will be shown to students when enabled.</div>';
            }
        }

        el.innerHTML = html;

        // Accordion toggle
        el.querySelectorAll('.ce-accordion-header').forEach(function (btn) {
            btn.addEventListener('click', function () {
                this.closest('.ce-accordion-item').classList.toggle('open');
            });
        });
    }

    /* ---- Question Relevance Analysis -------------------------------- */
    async function startRelevanceAnalysis(courseId) {
        if (!selectedCourse) return;
        activeGenerating = true;
        var btn = document.getElementById('btn-analyze-relevance');
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Setting up...'; }

        showRelProgress('Setting up course access and finding tests...', 0);

        try {
            // Phase 1: Find tests (includes videoUrl and articleUrl per lesson)
            var findResp = await fetch('/api/find-course-tests', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    courseId: selectedCourse.sourcedId,
                    courseCode: selectedCourse.courseCode || '',
                }),
                signal: AbortSignal.timeout ? AbortSignal.timeout(120000) : undefined,
            });
            var findData = await findResp.json();
            var tests = findData.tests || [];

            if (!tests.length) {
                showRelError('No assessment tests found for this course.');
                if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-magnifying-glass-chart"></i> Analyze Relevance'; }
                activeGenerating = false;
                return;
            }

            showRelProgress('Found ' + tests.length + ' tests. Fetching questions...', 0);

            // Phase 2: Fetch questions from each test (batched)
            var testQuestionMap = {};
            var fetched = 0;
            var totalQuestions = 0;
            var BATCH = 3;

            function fetchTestQuestions(t) {
                var params = [];
                if (t.id) params.push('lessonId=' + encodeURIComponent(t.id));
                if (t.url) params.push('url=' + encodeURIComponent(t.url));
                if (courseId) params.push('courseId=' + encodeURIComponent(courseId));
                var url = '/api/pp-get-questions-admin?' + params.join('&');
                return fetch(url)
                    .then(function (r) { return r.json(); })
                    .then(function (d) {
                        if (d.success && d.data && d.data.questions && d.data.questions.length > 0) {
                            return { questions: d.data.questions, error: null };
                        }
                        return { questions: [], error: d.error || 'No questions returned' };
                    })
                    .catch(function (e) { return { questions: [], error: e.message || 'Network error' }; });
            }

            for (var i = 0; i < tests.length; i += BATCH) {
                var batch = tests.slice(i, i + BATCH);
                var promises = batch.map(function (t) {
                    return fetchTestQuestions(t).then(function (result) {
                        return { test: t, result: result };
                    });
                });
                var results = await Promise.all(promises);
                results.forEach(function (r) {
                    if (r.result.questions.length > 0) {
                        var lt = r.test.lessonTitle || r.test.title || 'Unknown';
                        if (!testQuestionMap[lt]) {
                            testQuestionMap[lt] = {
                                lessonTitle: lt,
                                videoUrl: r.test.videoUrl || '',
                                articleUrl: r.test.articleUrl || '',
                                questions: [],
                            };
                        }
                        testQuestionMap[lt].questions = testQuestionMap[lt].questions.concat(r.result.questions);
                        totalQuestions += r.result.questions.length;
                    }
                });
                fetched += batch.length;
                showRelProgress('Fetching questions: ' + fetched + '/' + tests.length + ' tests (' + totalQuestions + ' questions)...', 0);
            }

            var lessonGroups = Object.values(testQuestionMap);
            if (!totalQuestions) {
                showRelError('No questions could be fetched from any of the ' + tests.length + ' tests.');
                if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-magnifying-glass-chart"></i> Analyze Relevance'; }
                activeGenerating = false;
                return;
            }

            showRelProgress('Submitting ' + totalQuestions + ' questions across ' + lessonGroups.length + ' lessons for relevance analysis...', 0);

            // Phase 3: Submit for relevance analysis
            var genResp = await fetch('/api/analyze-relevance', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    courseId: selectedCourse.sourcedId,
                    lessons: lessonGroups,
                }),
            });
            var genData = await genResp.json();

            if (genData.error) {
                showRelError(genData.error);
                if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-magnifying-glass-chart"></i> Analyze Relevance'; }
                activeGenerating = false;
                return;
            }

            showRelProgress('Claude is analyzing ' + (genData.questionCount || totalQuestions) + ' questions across ' + (genData.chunkCount || 1) + ' batches...', 0);
            startRelevancePolling(selectedCourse.sourcedId);

        } catch (e) {
            showRelError('Failed: ' + e.message);
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-magnifying-glass-chart"></i> Analyze Relevance'; }
            activeGenerating = false;
        }
    }

    function startRelevancePolling(courseId) {
        stopRelevancePolling();
        var startTime = Date.now();
        function poll() {
            fetch('/api/relevance-status?courseId=' + encodeURIComponent(courseId))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.status === 'done' && data.results) {
                        activeGenerating = false;
                        stopRelevancePolling();
                        document.getElementById('rel-progress').style.display = 'none';
                        var btn = document.getElementById('btn-analyze-relevance');
                        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Re-Analyze Relevance'; }

                        // Update badge
                        var header = document.getElementById('rel-card-header');
                        if (header) {
                            var badge = header.querySelector('.ce-action-card-summary');
                            if (badge) {
                                badge.className = 'ce-action-card-summary all-done';
                                badge.innerHTML = '<i class="fa-solid fa-check-circle"></i> ' + (data.badCount || 0) + ' flagged / ' + (data.questionCount || Object.keys(data.results).length) + ' analyzed';
                            }
                            var card = header.closest('.ce-action-card');
                            if (card && card.classList.contains('collapsed')) card.classList.remove('collapsed');
                        }

                        // Insert toggle if not already present
                        if (!document.getElementById('relevance-toggle')) {
                            var toggleContainer = document.createElement('div');
                            toggleContainer.className = 'ce-inline-toggle';
                            toggleContainer.innerHTML =
                                '<div class="ce-inline-toggle-left">' +
                                    '<i class="fa-solid fa-toggle-off"></i>' +
                                    '<strong>Hide Irrelevant Questions</strong>' +
                                    '<span>Remove flagged questions from student quizzes</span>' +
                                '</div>' +
                                '<label class="ce-switch">' +
                                    '<input type="checkbox" id="relevance-toggle">' +
                                    '<span class="ce-switch-slider"></span>' +
                                '</label>';
                            var progressEl = document.getElementById('rel-progress');
                            if (progressEl && progressEl.parentNode) {
                                progressEl.parentNode.insertBefore(toggleContainer, progressEl);
                            }
                            var newToggle = document.getElementById('relevance-toggle');
                            if (newToggle) {
                                newToggle.addEventListener('change', function () {
                                    var enabled = this.checked;
                                    var icon = this.closest('.ce-inline-toggle').querySelector('.ce-inline-toggle-left i');
                                    icon.className = 'fa-solid fa-toggle-' + (enabled ? 'on' : 'off');
                                    fetch('/api/relevance-toggle', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify({ courseId: courseId, enabled: enabled }),
                                    }).catch(function () {});
                                });
                            }
                        }

                        showRelevanceResults(data, courseId);
                    } else if (data.status === 'error') {
                        activeGenerating = false;
                        stopRelevancePolling();
                        document.getElementById('rel-progress').style.display = 'none';
                        showRelError(data.error || 'Analysis failed.');
                        var btn = document.getElementById('btn-analyze-relevance');
                        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-magnifying-glass-chart"></i> Analyze Relevance'; }
                    } else {
                        var elapsed = Math.floor((Date.now() - startTime) / 1000);
                        var chunkInfo = data.chunkCount ? ' (' + (data.succeeded || 0) + '/' + data.chunkCount + ' chunks done)' : '';
                        showRelProgress('Claude is analyzing question relevance...' + chunkInfo, elapsed);
                        relevancePollTimer = setTimeout(poll, POLL_INTERVAL);
                    }
                })
                .catch(function () { relevancePollTimer = setTimeout(poll, POLL_INTERVAL); });
        }
        relevancePollTimer = setTimeout(poll, POLL_INTERVAL);
    }

    function stopRelevancePolling() { if (relevancePollTimer) { clearTimeout(relevancePollTimer); relevancePollTimer = null; } }

    function showRelProgress(msg, elapsed) {
        var el = document.getElementById('rel-progress');
        if (!el) return;
        el.style.display = '';
        var timeStr = elapsed > 0 ? ' <span style="opacity:0.6;">(' + formatTime(elapsed) + ')</span>' : '';
        el.innerHTML =
            '<div class="ce-progress-header"><div class="ce-progress-spinner"></div><div class="ce-progress-title">' + msg + timeStr + '</div></div>' +
            '<div class="ce-warning"><i class="fa-solid fa-triangle-exclamation"></i> Please do not leave this page until analysis is complete.</div>';
    }

    function showRelError(msg) {
        var el = document.getElementById('rel-progress');
        if (!el) return;
        el.style.display = '';
        el.innerHTML = '<div class="ce-error"><i class="fa-solid fa-circle-exclamation" style="margin-right:6px;"></i>' + esc(msg) + '</div>';
    }

    function showRelevanceResults(data, courseId) {
        var el = document.getElementById('rel-results');
        if (!el) return;
        el.style.display = '';
        var results = data.results || {};
        var qIds = Object.keys(results);
        var badCount = data.badCount || 0;

        var genDate = data.generatedAt ? new Date(data.generatedAt * 1000).toLocaleString() : '';

        var html = '<div class="ce-mapping-count" style="margin-top:12px;">' +
            '<i class="fa-solid fa-circle-check" style="color:#45B5AA; margin-right:6px;"></i>' +
            qIds.length + ' question' + (qIds.length !== 1 ? 's' : '') + ' analyzed' +
            (badCount > 0 ? ' &mdash; <strong style="color:#E53E3E;">' + badCount + ' flagged as irrelevant</strong>' : ' &mdash; <strong style="color:#45B5AA;">all questions look good</strong>') +
            (data.model ? ' <span style="opacity:0.5;">(' + esc(data.model) + ')</span>' : '') +
            (genDate ? ' <span style="opacity:0.5;">&middot; ' + esc(genDate) + '</span>' : '') +
            '</div>';

        // Show flagged questions first, then good ones (up to 10 total)
        var flagged = [];
        var good = [];
        qIds.forEach(function (qid) {
            var info = results[qid];
            if (info && !info.relevant) {
                flagged.push({ id: qid, info: info });
            } else {
                good.push({ id: qid, info: info });
            }
        });

        var preview = flagged.concat(good).slice(0, 20);
        if (preview.length) {
            html += '<div class="ce-accordion" style="margin-top:8px;">';
            preview.forEach(function (item, idx) {
                var info = item.info || {};
                var isBad = !info.relevant;
                var catLabel = '';
                if (isBad) {
                    var catMap = { off_topic: 'Off Topic', too_specific: 'Too Specific', no_source_material: 'No Source Material' };
                    catLabel = catMap[info.category] || info.category || 'Irrelevant';
                }

                var headerBadge = isBad
                    ? '<span class="ce-accordion-badge" style="background:#FED7D7; color:#C53030;">' + esc(catLabel) + '</span>'
                    : '<span class="ce-accordion-badge" style="background:#C6F6D5; color:#276749;">Relevant</span>';

                var headerIcon = isBad
                    ? '<i class="fa-solid fa-triangle-exclamation" style="margin-right:8px; color:#E53E3E; opacity:0.7;"></i>'
                    : '<i class="fa-solid fa-circle-check" style="margin-right:8px; color:#45B5AA; opacity:0.5;"></i>';

                html += '<div class="ce-accordion-item">' +
                    '<button class="ce-accordion-header" data-idx="rel' + idx + '">' +
                        '<span class="ce-accordion-title">' + headerIcon + esc(item.id) + '</span>' +
                        headerBadge +
                        '<i class="fa-solid fa-chevron-right ce-accordion-chevron"></i>' +
                    '</button>' +
                    '<div class="ce-accordion-body" id="rel-body-' + idx + '">';

                html += '<div style="margin-bottom:8px; font-size:0.88rem; line-height:1.5; color:var(--color-text);">' +
                    esc(info.reasoning || 'No reasoning provided.') +
                    '</div>';

                if (info.confidence != null) {
                    html += '<div style="font-size:0.8rem; color:var(--color-text-muted); margin-bottom:8px;">Confidence: ' + info.confidence + '%</div>';
                }

                if (isBad) {
                    html += '<div style="margin-top:6px;">' +
                        '<button class="ce-btn-small ce-btn-toggle-question" data-qid="' + esc(item.id) + '" data-hidden="true" style="font-size:0.8rem; padding:4px 10px; border:1px solid #E53E3E; color:#E53E3E; background:transparent; border-radius:6px; cursor:pointer;">' +
                            '<i class="fa-solid fa-eye-slash" style="margin-right:4px;"></i> Hidden from students' +
                        '</button>' +
                    '</div>';
                }

                html += '</div></div>';
            });
            html += '</div>';
            if (qIds.length > 20) {
                html += '<div style="font-size:0.82rem; color:var(--color-text-muted); margin-top:8px;">Showing 20 of ' + qIds.length + ' questions. All results are saved.</div>';
            }
        }

        el.innerHTML = html;

        // Accordion toggle
        el.querySelectorAll('.ce-accordion-header').forEach(function (btn) {
            btn.addEventListener('click', function () {
                this.closest('.ce-accordion-item').classList.toggle('open');
            });
        });

        // Per-question toggle buttons
        el.querySelectorAll('.ce-btn-toggle-question').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var qid = this.getAttribute('data-qid');
                var isHidden = this.getAttribute('data-hidden') === 'true';
                var newHidden = !isHidden;
                var self = this;
                fetch('/api/relevance-toggle', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ courseId: courseId, questionId: qid, hidden: newHidden }),
                }).then(function () {
                    self.setAttribute('data-hidden', String(newHidden));
                    if (newHidden) {
                        self.innerHTML = '<i class="fa-solid fa-eye-slash" style="margin-right:4px;"></i> Hidden from students';
                        self.style.borderColor = '#E53E3E';
                        self.style.color = '#E53E3E';
                    } else {
                        self.innerHTML = '<i class="fa-solid fa-eye" style="margin-right:4px;"></i> Visible to students';
                        self.style.borderColor = '#45B5AA';
                        self.style.color = '#45B5AA';
                    }
                }).catch(function () {});
            });
        });
    }

    /* ---- Init ------------------------------------------------------- */
    document.addEventListener('DOMContentLoaded', function () {
        document.getElementById('back-btn').addEventListener('click', closeCourseDetail);
        var searchTimer;
        document.getElementById('course-search').addEventListener('input', function () {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(function () { updateCount(); filterAndRender(); }, 200);
        });
        loadCourses();
    });

})();
