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
        loadSkillTreeState(course.sourcedId);
    }

    function closeCourseDetail() {
        selectedCourse = null;
        currentMermaidCode = '';
        stopPolling();
        stopLessonPolling();
        stopQuestionPolling();
        history.pushState(null, '', '/admin/course-editor');
        document.getElementById('course-detail-view').style.display = 'none';
        document.getElementById('course-list-view').style.display = '';
        document.getElementById('lesson-mapping-section').style.display = 'none';
        document.getElementById('question-analysis-section').style.display = 'none';
        checkExistingTrees().then(function () { filterAndRender(); });
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

        showQuestionAnalysisProgress('Finding assessment tests for this course...', 0);

        try {
            // Phase 1: Find tests
            var findResp = await fetch('/api/find-course-tests', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    courseId: selectedCourse.sourcedId,
                    courseCode: selectedCourse.courseCode || '',
                }),
            });
            var findData = await findResp.json();
            var tests = findData.tests || [];

            if (!tests.length) {
                showQuestionAnalysisError('No assessment tests found for this course (code: ' + esc(selectedCourse.courseCode || 'none') + '). The QTI catalog may not have content for this course.');
                showQuestionAnalysisActions(false);
                activeGenerating = false;
                return;
            }

            showQuestionAnalysisProgress('Found ' + tests.length + ' tests. Fetching questions...', 0);

            // Phase 2: Fetch questions from each test (parallel, batched)
            var allQuestions = [];
            var fetched = 0;
            var BATCH = 3; // fetch 3 tests at a time

            for (var i = 0; i < tests.length; i += BATCH) {
                var batch = tests.slice(i, i + BATCH);
                var promises = batch.map(function (t) {
                    return fetch('/api/qti-item?id=' + encodeURIComponent(t.id) + '&type=assessment')
                        .then(function (r) { return r.json(); })
                        .then(function (d) {
                            if (d.success && d.data && d.data.questions) {
                                return d.data.questions;
                            }
                            return [];
                        })
                        .catch(function () { return []; });
                });
                var results = await Promise.all(promises);
                results.forEach(function (qs) {
                    allQuestions = allQuestions.concat(qs);
                });
                fetched += batch.length;
                showQuestionAnalysisProgress('Fetching questions: ' + fetched + '/' + tests.length + ' tests (' + allQuestions.length + ' questions found)...', 0);
            }

            if (!allQuestions.length) {
                showQuestionAnalysisError('Tests were found but no questions could be fetched. The QTI content may be unavailable.');
                showQuestionAnalysisActions(false);
                activeGenerating = false;
                return;
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
