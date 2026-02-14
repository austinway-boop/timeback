/* ====================================================================
   Course Editor – AP Course Skill Tree Generator
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
        history: 'fa-landmark',
        lang:    'fa-pen-fancy',
        lit:     'fa-book-open',
        bio:     'fa-dna',
        chem:    'fa-flask',
        physics: 'fa-atom',
        math:    'fa-calculator',
        calc:    'fa-square-root-variable',
        stat:    'fa-chart-line',
        cs:      'fa-laptop-code',
        psych:   'fa-brain',
        econ:    'fa-chart-pie',
        gov:     'fa-building-columns',
        geo:     'fa-globe-americas',
        env:     'fa-leaf',
        art:     'fa-palette',
        music:   'fa-music',
        default: 'fa-graduation-cap',
    };

    const POLL_INTERVAL = 15000; // 15 seconds

    /* ---- State ------------------------------------------------------ */
    let allCourses = [];
    let filteredCourses = [];
    let selectedCourse = null;
    let pollTimer = null;
    let chartZoom = 1;

    /* ---- Helpers ----------------------------------------------------- */
    function esc(str) {
        if (str == null) return '';
        var div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    function guessIcon(title) {
        var t = (title || '').toLowerCase();
        if (t.includes('hist') || t.includes('world'))             return ICONS.history;
        if (t.includes('lang') && !t.includes('language & comp'))  return ICONS.lang;
        if (t.includes('language & comp') || t.includes('lang'))   return ICONS.lang;
        if (t.includes('lit'))                                     return ICONS.lit;
        if (t.includes('bio'))                                     return ICONS.bio;
        if (t.includes('chem'))                                    return ICONS.chem;
        if (t.includes('physics'))                                 return ICONS.physics;
        if (t.includes('calc'))                                    return ICONS.calc;
        if (t.includes('stat'))                                    return ICONS.stat;
        if (t.includes('math'))                                    return ICONS.math;
        if (t.includes('computer') || t.includes('cs'))            return ICONS.cs;
        if (t.includes('psych'))                                   return ICONS.psych;
        if (t.includes('econ'))                                    return ICONS.econ;
        if (t.includes('gov'))                                     return ICONS.gov;
        if (t.includes('geo') || t.includes('human'))              return ICONS.geo;
        if (t.includes('environ'))                                 return ICONS.env;
        if (t.includes('art'))                                     return ICONS.art;
        if (t.includes('music'))                                   return ICONS.music;
        return ICONS.default;
    }

    function isAPCourse(course) {
        var title = (course.title || '').trim();
        return /\bAP\b/i.test(title);
    }

    function isExternal(course) {
        var meta = course.metadata || {};
        var app = (meta.app || meta.primaryApp || '').toLowerCase().replace(/[\s_-]/g, '');
        if (!app) return false;
        for (var key of EXTERNAL_APP_KEYS) {
            if (app.includes(key)) return true;
        }
        return false;
    }

    /* ---- Skeleton Cards --------------------------------------------- */
    function showSkeletonCards(count) {
        var grid = document.getElementById('courses-grid');
        grid.innerHTML = Array.from({ length: count }, function (_, i) {
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
            });

            // Check which courses already have skill trees
            await checkExistingTrees();

            updateCount();
            filterAndRender();
        } catch (e) {
            document.getElementById('courses-grid').innerHTML =
                '<div class="ce-empty-state"><i class="fa-solid fa-circle-exclamation"></i><p>Failed to load courses. Please try again.</p></div>';
        }
    }

    async function checkExistingTrees() {
        // Check each course for existing skill trees (in parallel, batched)
        var checks = allCourses.map(function (c) {
            return fetch('/api/skill-tree-status?courseId=' + encodeURIComponent(c.sourcedId))
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    c._hasTree = d.status === 'done';
                    c._generating = d.status === 'processing';
                })
                .catch(function () {
                    c._hasTree = false;
                    c._generating = false;
                });
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
            return (c.title || '').toLowerCase().includes(q) ||
                   (c.courseCode || '').toLowerCase().includes(q);
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
            var theme = THEMES[i % THEMES.length];
            var icon = guessIcon(c.title);
            var badge = '';
            if (c._hasTree) {
                badge = '<span class="ce-card-badge has-tree"><i class="fa-solid fa-check" style="margin-right:3px;"></i>Skill Tree</span>';
            } else if (c._generating) {
                badge = '<span class="ce-card-badge generating"><i class="fa-solid fa-spinner fa-spin" style="margin-right:3px;"></i>Generating</span>';
            }

            var meta = c.metadata || {};
            var metrics = meta.metrics || {};
            var lessons = metrics.totalLessons || metrics.totalUnits || '';

            return '<div class="ce-course-card" data-idx="' + i + '">' +
                badge +
                '<div class="ce-card-icon ' + theme + '"><i class="fa-solid ' + icon + '"></i></div>' +
                '<div class="ce-card-title">' + esc(c.title) + '</div>' +
                '<div class="ce-card-code">' + esc(c.courseCode || 'No code') + '</div>' +
                '<div class="ce-card-meta">' +
                    (lessons ? '<span><i class="fa-solid fa-layer-group"></i>' + lessons + ' lessons</span>' : '') +
                    '<span><i class="fa-solid fa-circle ' + (c.status === 'active' ? '" style="color:#45B5AA;font-size:0.5rem;"' : '" style="color:#CBD5E0;font-size:0.5rem;"') + '></i> ' + esc(c.status || 'unknown') + '</span>' +
                '</div>' +
            '</div>';
        }).join('');

        // Attach click handlers
        grid.querySelectorAll('.ce-course-card').forEach(function (card) {
            card.addEventListener('click', function () {
                var idx = parseInt(this.getAttribute('data-idx'), 10);
                openCourseDetail(filteredCourses[idx]);
            });
        });
    }

    /* ---- Course Detail View ----------------------------------------- */
    function openCourseDetail(course) {
        selectedCourse = course;
        document.getElementById('course-list-view').style.display = 'none';
        document.getElementById('course-detail-view').style.display = '';

        var icon = guessIcon(course.title);
        var meta = course.metadata || {};
        var metrics = meta.metrics || {};
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

        // Load skill tree state
        loadSkillTreeState(course.sourcedId);
    }

    function closeCourseDetail() {
        selectedCourse = null;
        stopPolling();
        document.getElementById('course-detail-view').style.display = 'none';
        document.getElementById('course-list-view').style.display = '';
        // Refresh the list to update badges
        checkExistingTrees().then(function () { filterAndRender(); });
    }

    async function loadSkillTreeState(courseId) {
        var actionsEl = document.getElementById('skill-tree-actions');
        var progressEl = document.getElementById('generation-progress');
        var chartEl = document.getElementById('chart-container');

        actionsEl.innerHTML = '<div class="ce-progress-spinner" style="display:inline-block;"></div> Checking...';
        progressEl.style.display = 'none';
        chartEl.style.display = 'none';

        try {
            var resp = await fetch('/api/skill-tree-status?courseId=' + encodeURIComponent(courseId));
            var data = await resp.json();

            if (data.status === 'done' && data.mermaid) {
                showTreeActions(true);
                renderMermaidChart(data.mermaid);
            } else if (data.status === 'processing') {
                showTreeActions(false, true);
                showProgress('Claude is generating the skill tree...', 'This may take 5-10 minutes. You can leave this page and come back later.');
                startPolling(courseId);
            } else {
                showTreeActions(false);
            }
        } catch (e) {
            showTreeActions(false);
        }
    }

    function showTreeActions(hasTree, isGenerating) {
        var actionsEl = document.getElementById('skill-tree-actions');

        if (isGenerating) {
            actionsEl.innerHTML =
                '<button class="ce-btn-generate" disabled>' +
                    '<i class="fa-solid fa-spinner fa-spin"></i> Generating...' +
                '</button>';
            return;
        }

        if (hasTree) {
            actionsEl.innerHTML =
                '<button class="ce-btn-secondary" id="btn-regenerate">' +
                    '<i class="fa-solid fa-arrows-rotate"></i> Regenerate Skill Tree' +
                '</button>';
            document.getElementById('btn-regenerate').addEventListener('click', function () {
                if (confirm('This will replace the existing skill tree. Continue?')) {
                    startGeneration();
                }
            });
        } else {
            actionsEl.innerHTML =
                '<button class="ce-btn-generate" id="btn-generate">' +
                    '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate Skill Tree' +
                '</button>' +
                '<span style="font-size:0.82rem; color:var(--color-text-muted);">Uses Claude Opus 4.6 with extended thinking</span>';
            document.getElementById('btn-generate').addEventListener('click', function () {
                startGeneration();
            });
        }
    }

    /* ---- Generation Flow -------------------------------------------- */
    async function startGeneration() {
        if (!selectedCourse) return;

        showTreeActions(false, true);
        showProgress('Submitting to Claude...', 'Preparing the prompt with course and lesson data.');
        document.getElementById('chart-container').style.display = 'none';

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

            if (data.error) {
                showError(data.error);
                showTreeActions(false);
                return;
            }

            showProgress('Claude is generating the skill tree...', 'This may take 5-10 minutes. You can leave this page and come back later.');
            startPolling(selectedCourse.sourcedId);
        } catch (e) {
            showError('Failed to start generation: ' + e.message);
            showTreeActions(false);
        }
    }

    /* ---- Polling ----------------------------------------------------- */
    function startPolling(courseId) {
        stopPolling();
        var startTime = Date.now();

        function poll() {
            fetch('/api/skill-tree-status?courseId=' + encodeURIComponent(courseId))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.status === 'done' && data.mermaid) {
                        stopPolling();
                        showProgress(null); // hide
                        showTreeActions(true);
                        renderMermaidChart(data.mermaid);
                        // Update the course state
                        if (selectedCourse) {
                            selectedCourse._hasTree = true;
                            selectedCourse._generating = false;
                        }
                    } else if (data.status === 'error') {
                        stopPolling();
                        showProgress(null);
                        showError(data.error || 'Generation failed. Please try again.');
                        showTreeActions(false);
                    } else {
                        // Still processing
                        var elapsed = Math.floor((Date.now() - startTime) / 1000);
                        var mins = Math.floor(elapsed / 60);
                        var secs = elapsed % 60;
                        var timeStr = mins > 0 ? mins + 'm ' + secs + 's' : secs + 's';
                        showProgress(
                            'Claude is generating the skill tree...',
                            'Elapsed: ' + timeStr + '. This may take 5-10 minutes.'
                        );
                        pollTimer = setTimeout(poll, POLL_INTERVAL);
                    }
                })
                .catch(function () {
                    // Network error, keep polling
                    pollTimer = setTimeout(poll, POLL_INTERVAL);
                });
        }

        pollTimer = setTimeout(poll, POLL_INTERVAL);
    }

    function stopPolling() {
        if (pollTimer) {
            clearTimeout(pollTimer);
            pollTimer = null;
        }
    }

    /* ---- Progress UI ------------------------------------------------ */
    function showProgress(title, detail) {
        var el = document.getElementById('generation-progress');
        if (!title) {
            el.style.display = 'none';
            return;
        }
        el.style.display = '';
        el.innerHTML =
            '<div class="ce-progress-header">' +
                '<div class="ce-progress-spinner"></div>' +
                '<div class="ce-progress-title">' + esc(title) + '</div>' +
            '</div>' +
            '<div class="ce-progress-detail">' + esc(detail || '') + '</div>' +
            '<div class="ce-progress-bar-track"><div class="ce-progress-bar-fill" style="width:60%;"></div></div>';
    }

    function showError(msg) {
        var el = document.getElementById('generation-progress');
        el.style.display = '';
        el.innerHTML = '<div class="ce-error"><i class="fa-solid fa-circle-exclamation" style="margin-right:6px;"></i>' + esc(msg) + '</div>';
    }

    /* ---- Mermaid Rendering ------------------------------------------ */
    async function renderMermaidChart(mermaidCode) {
        var container = document.getElementById('chart-container');
        var inner = document.getElementById('chart-inner');
        container.style.display = '';
        chartZoom = 1;

        // Clean up the mermaid code (remove markdown fences if present)
        var code = mermaidCode
            .replace(/^```mermaid\s*/i, '')
            .replace(/^```\s*/m, '')
            .replace(/\s*```$/m, '')
            .trim();

        inner.innerHTML = '<div style="text-align:center; padding:40px; color:var(--color-text-muted);"><i class="fa-solid fa-spinner fa-spin" style="margin-right:8px;"></i>Rendering chart...</div>';

        try {
            // Initialize mermaid
            mermaid.initialize({
                startOnLoad: false,
                theme: 'default',
                flowchart: {
                    useMaxWidth: false,
                    htmlLabels: true,
                    curve: 'basis',
                },
                securityLevel: 'loose',
            });

            var id = 'skill-tree-' + Date.now();
            var result = await mermaid.render(id, code);
            inner.innerHTML = result.svg;

            // Apply initial zoom reset
            applyZoom(1);
        } catch (e) {
            inner.innerHTML =
                '<div class="ce-error" style="margin:20px;">' +
                    '<i class="fa-solid fa-circle-exclamation" style="margin-right:6px;"></i>' +
                    'Failed to render the mermaid chart. The generated code may have syntax issues.<br><br>' +
                    '<details style="margin-top:8px;"><summary style="cursor:pointer;">Show raw mermaid code</summary>' +
                    '<pre style="margin-top:8px; font-size:0.75rem; max-height:300px; overflow:auto; white-space:pre-wrap; background:var(--color-bg); padding:12px; border-radius:6px;">' +
                    esc(code) + '</pre></details>' +
                '</div>';
        }
    }

    /* ---- Pan & Zoom ------------------------------------------------- */
    function applyZoom(level) {
        chartZoom = Math.max(0.1, Math.min(3, level));
        var inner = document.getElementById('chart-inner');
        inner.style.transform = 'scale(' + chartZoom + ')';
    }

    function setupPanZoom() {
        var viewport = document.getElementById('chart-viewport');
        var isDragging = false;
        var startX, startY, scrollLeftStart, scrollTopStart;

        viewport.addEventListener('mousedown', function (e) {
            if (e.target.closest('.ce-toolbar-btn')) return;
            isDragging = true;
            startX = e.pageX - viewport.offsetLeft;
            startY = e.pageY - viewport.offsetTop;
            scrollLeftStart = viewport.scrollLeft;
            scrollTopStart = viewport.scrollTop;
        });

        viewport.addEventListener('mousemove', function (e) {
            if (!isDragging) return;
            e.preventDefault();
            var x = e.pageX - viewport.offsetLeft;
            var y = e.pageY - viewport.offsetTop;
            viewport.scrollLeft = scrollLeftStart - (x - startX);
            viewport.scrollTop = scrollTopStart - (y - startY);
        });

        viewport.addEventListener('mouseup', function () { isDragging = false; });
        viewport.addEventListener('mouseleave', function () { isDragging = false; });

        // Scroll wheel zoom
        viewport.addEventListener('wheel', function (e) {
            if (e.ctrlKey || e.metaKey) {
                e.preventDefault();
                var delta = e.deltaY > 0 ? -0.1 : 0.1;
                applyZoom(chartZoom + delta);
            }
        }, { passive: false });

        // Toolbar buttons
        document.getElementById('zoom-in-btn').addEventListener('click', function () {
            applyZoom(chartZoom + 0.2);
        });
        document.getElementById('zoom-out-btn').addEventListener('click', function () {
            applyZoom(chartZoom - 0.2);
        });
        document.getElementById('zoom-reset-btn').addEventListener('click', function () {
            applyZoom(1);
            document.getElementById('chart-viewport').scrollTop = 0;
            document.getElementById('chart-viewport').scrollLeft = 0;
        });
    }

    /* ---- Init ------------------------------------------------------- */
    document.addEventListener('DOMContentLoaded', function () {
        // Back button
        document.getElementById('back-btn').addEventListener('click', closeCourseDetail);

        // Search
        var searchTimer;
        document.getElementById('course-search').addEventListener('input', function () {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(function () {
                updateCount();
                filterAndRender();
            }, 200);
        });

        // Pan/zoom setup
        setupPanZoom();

        // Load courses
        loadCourses();
    });

})();
