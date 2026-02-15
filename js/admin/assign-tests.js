var selectedStudent = null;
var existingAssignments = [];
var availableTests = [];  // built dynamically from enrollment data

function esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── Init ──────────────────────────────────────────────────── */
var searchInput, searchTimer;

document.addEventListener('DOMContentLoaded', function() {
    searchInput = document.getElementById('student-search');
    searchInput.addEventListener('input', function() {
        clearTimeout(searchTimer);
        var q = this.value.trim();
        if (q.length < 2) { closeDD(); return; }
        searchTimer = setTimeout(function() { doSearch(q); }, 250);
    });
    document.addEventListener('click', function(e) { if (!e.target.closest('.search-wrap')) closeDD(); });
});

/* ── Search via API (no huge pre-fetch) ────────────────────── */
var searchController = null;

function doSearch(q) {
    // Cancel previous in-flight request
    if (searchController) searchController.abort();
    searchController = new AbortController();

    // Show loading state
    var dd = document.getElementById('search-dropdown');
    dd.innerHTML = '<div class="search-empty"><i class="fa-solid fa-spinner fa-spin" style="margin-right:6px;"></i>Searching...</div>';
    dd.classList.add('open');

    fetch('/api/users-page?search=' + encodeURIComponent(q) + '&limit=20', { signal: searchController.signal })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var users = d.users || [];
            renderDD(users);
        })
        .catch(function(e) {
            if (e.name !== 'AbortError') {
                dd.innerHTML = '<div class="search-empty">Search failed. Try again.</div>';
            }
        });
}

function renderDD(list) {
    var dd = document.getElementById('search-dropdown');
    if (!list.length) { dd.innerHTML = '<div class="search-empty">No students found.</div>'; dd.classList.add('open'); return; }
    dd.innerHTML = list.map(function(u) {
        var nm = ((u.givenName || '') + ' ' + (u.familyName || '')).trim() || 'Unknown';
        return '<div class="search-item" data-id="' + esc(u.sourcedId) + '" onclick="pickStudent(this)">' +
            '<div class="user-cell-avatar">' + esc((u.givenName || '?')[0].toUpperCase()) + '</div>' +
            '<div style="flex:1;min-width:0;"><div class="search-item-name">' + esc(nm) +
            '</div><div class="search-item-email">' + esc(u.email || '') + '</div></div></div>';
    }).join('');
    dd.classList.add('open');
}

function closeDD() { document.getElementById('search-dropdown').classList.remove('open'); }

/* ── Pick Student ──────────────────────────────────────────── */
function pickStudent(el) {
    var id = el.getAttribute('data-id');
    var n = el.querySelector('.search-item-name');
    var e = el.querySelector('.search-item-email');
    var fullName = n ? n.textContent.trim() : '';
    var parts = fullName.split(' ');
    var user = {
        sourcedId: id,
        givenName: parts[0] || '',
        familyName: parts.slice(1).join(' ') || '',
        email: e ? e.textContent.trim() : '',
    };

    selectedStudent = user;
    existingAssignments = [];
    closeDD();

    var nm = ((user.givenName || '') + ' ' + (user.familyName || '')).trim();
    searchInput.value = nm;

    document.getElementById('panels').style.display = '';
    document.getElementById('tests-list').innerHTML = '<div class="empty-state"><i class="fa-solid fa-spinner fa-spin" style="opacity:0.5;"></i><p>Loading tests...</p></div>';
    document.getElementById('pending-tests').innerHTML = '<div class="empty-state"><i class="fa-solid fa-spinner fa-spin" style="opacity:0.5;"></i><p>Loading...</p></div>';
    document.getElementById('subject-filter').value = 'all';
    clearFeedback();

    loadAssignments(user.sourcedId);
}

/* ── PowerPath test catalog ──────────────────────────────────── */
var PP_SUBJECTS = ['Reading','Math','Language','Vocabulary','Writing','Science','Social Studies','FastMath'];
var PP_GRADES = ['3','4','5','6','7','8','9','10','11','12'];
var FULL_CATALOG = [];
PP_SUBJECTS.forEach(function(subj) {
    PP_GRADES.forEach(function(gr) {
        FULL_CATALOG.push({ subject: subj, grade: gr, name: subj + ' Grade ' + gr });
    });
});

var placementLevels = {};   // subject → { level, ... }
var subjectProgress = {};   // subject → progress data
var enrolledKeys = new Set();

/* ── Load everything for a student ────────────────────────── */
async function loadAssignments(studentId) {
    existingAssignments = [];
    availableTests = FULL_CATALOG;
    placementLevels = {};
    subjectProgress = {};
    enrolledKeys = new Set();

    try {
        // Fetch assignments, enrollments, and placement subjects in parallel
        var [assignResp, enrollResp] = await Promise.all([
            fetch('/api/assign-test?student=' + encodeURIComponent(studentId)).then(function(r) { return r.json(); }).catch(function() { return { testAssignments: [] }; }),
            fetch('/api/enrollments?userId=' + encodeURIComponent(studentId)).then(function(r) { return r.json(); }).catch(function() { return {}; }),
        ]);

        // ── Parse existing assignments ──
        var rawAssignments = assignResp.testAssignments || [];
        if (!Array.isArray(rawAssignments)) rawAssignments = [];
        existingAssignments = rawAssignments.map(function(a) {
            return {
                sourcedId: a.sourcedId || a.assignmentId || a.id || '',
                subject: a.subject || '',
                grade: a.grade || a.gradeLevel || '',
                assignmentStatus: a.assignmentStatus || a.status || 'assigned',
                assignedAt: a.assignedAt || '',
                testName: a.testName || ((a.subject || '') + ' Grade ' + (a.grade || '')),
            };
        });

        // ── Build enrolled keys ──
        var raw = enrollResp.data || enrollResp.enrollments || enrollResp.courses || (Array.isArray(enrollResp) ? enrollResp : []);
        for (var i = 0; i < raw.length; i++) {
            var e = raw[i];
            var c = e.course || {};
            var title = (c.title || '').trim();
            var subjects = c.subjects || [];
            var grades = c.grades || [];
            if (!title || !subjects.length || !grades.length) continue;
            if (title.startsWith('Manual XP') || title.includes('Hole-Filling')) continue;
            for (var g = 0; g < grades.length; g++) {
                enrolledKeys.add(subjects[0] + '|' + grades[g]);
            }
        }

        // ── Fetch placement levels for ALL subjects (non-blocking) ──
        PP_SUBJECTS.forEach(function(subj) {
            // Current level
            fetch('/api/assign-test?action=placement&student=' + encodeURIComponent(studentId) + '&subject=' + encodeURIComponent(subj))
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    if (d && !d.error) {
                        placementLevels[subj] = d;
                        renderTests();
                    }
                })
                .catch(function() {});
            // Subject progress
            fetch('/api/assign-test?action=progress&student=' + encodeURIComponent(studentId) + '&subject=' + encodeURIComponent(subj))
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    if (d && !d.error) {
                        subjectProgress[subj] = d;
                        renderTests();
                    }
                })
                .catch(function() {});
        });
    } catch(e) {
        console.error('loadAssignments error:', e);
    }

    // Rebuild filter dropdown
    var sel = document.getElementById('subject-filter');
    var current = sel.value;
    sel.innerHTML = '<option value="all">All Subjects</option>';
    PP_SUBJECTS.forEach(function(s) {
        var opt = document.createElement('option');
        opt.value = s;
        opt.textContent = s;
        sel.appendChild(opt);
    });
    if (current !== 'all') sel.value = current;

    renderTests();
    renderPending();
}

/* ── Helper: extract grade level from placement response ──── */
function getPlacementGrade(subj) {
    var d = placementLevels[subj];
    if (!d) return null;
    var g = d.gradeLevel || d.grade || d.level;
    if (typeof g === 'object') g = g.level || g.grade;
    return g != null ? String(g) : null;
}

/* ── Render Available Tests ─────────────────────────────────── */
function renderTests() {
    var el = document.getElementById('tests-list');
    var filter = document.getElementById('subject-filter').value;

    // Build status lookup from existing assignments (case-insensitive)
    var statusMap = {};
    existingAssignments.forEach(function(a) {
        var key = (a.subject || '').toLowerCase() + '|' + (a.grade || '');
        statusMap[key] = a.assignmentStatus || 'assigned';
    });

    // Filter by subject if selected
    var tests = availableTests;
    if (filter !== 'all') {
        tests = tests.filter(function(t) { return t.subject === filter; });
    }

    if (!tests.length) {
        el.innerHTML = '<div class="empty-state"><i class="fa-solid fa-clipboard-list"></i><p>No tests available.</p></div>';
        return;
    }

    // Sort: placement-level first, then enrolled, then rest
    var sorted = tests.slice().sort(function(a, b) {
        var aPlacement = getPlacementGrade(a.subject) === a.grade ? 0 : 1;
        var bPlacement = getPlacementGrade(b.subject) === b.grade ? 0 : 1;
        if (aPlacement !== bPlacement) return aPlacement - bPlacement;
        var aEnrolled = enrolledKeys.has(a.subject + '|' + a.grade) ? 0 : 1;
        var bEnrolled = enrolledKeys.has(b.subject + '|' + b.grade) ? 0 : 1;
        if (aEnrolled !== bEnrolled) return aEnrolled - bEnrolled;
        if (a.subject !== b.subject) return a.subject.localeCompare(b.subject);
        return parseInt(a.grade) - parseInt(b.grade);
    });

    el.innerHTML = sorted.map(function(t, idx) {
        var key = t.subject.toLowerCase() + '|' + t.grade;
        var status = statusMap[key] || '';
        var plGrade = getPlacementGrade(t.subject);
        var isPlacement = plGrade != null && plGrade === t.grade;
        var hasPlacement = plGrade != null;
        // Assignable = at placement level, OR no placement data yet (let them try)
        var canAssign = isPlacement || !hasPlacement;
        var btnHtml;

        if (status === 'completed') {
            btnHtml = '<span class="test-btn completed"><i class="fa-solid fa-check" style="margin-right:3px;"></i>Done</span>';
        } else if (status === 'assigned' || status === 'in_progress') {
            btnHtml = '<span class="test-btn assigned"><i class="fa-solid fa-clock" style="margin-right:3px;"></i>Pending</span>';
        } else if (status === 'failed') {
            btnHtml = '<span class="test-btn failed"><i class="fa-solid fa-rotate" style="margin-right:3px;"></i>Failed</span>';
        } else if (canAssign) {
            btnHtml = '<button class="test-btn assign" id="tbtn-' + idx + '" onclick="assignTest(\'' + esc(t.subject) + '\',\'' + esc(t.grade) + '\',' + idx + ')"><i class="fa-solid fa-plus" style="margin-right:3px;"></i>Assign</button>';
        } else {
            // Not at placement level — disabled
            btnHtml = '<span class="test-btn" style="background:#F4F6F9;color:#A0AEC0;font-size:0.7rem;cursor:default;">Grade ' + esc(plGrade) + ' only</span>';
        }

        // Badges
        var meta = '';
        if (isPlacement) meta += '<span style="background:#E8F5E9;color:#2E7D32;font-size:0.68rem;font-weight:600;padding:1px 6px;border-radius:4px;margin-left:6px;">Current Level</span>';

        var rowStyle = canAssign || status ? '' : 'opacity:0.35;';

        return '<div class="test-row" style="' + rowStyle + '">' +
            '<div class="test-row-info">' +
                '<div class="test-row-title">' + esc(t.name) + meta + '</div>' +
            '</div>' + btnHtml + '</div>';
    }).join('');
}

/* ── Render Student's Existing Tests ───────────────────────── */
function renderPending() {
    var el = document.getElementById('pending-tests');
    if (!existingAssignments.length) {
        el.innerHTML = '<div class="empty-state"><i class="fa-solid fa-check-circle"></i><p>No test assignments yet.</p></div>';
        return;
    }

    el.innerHTML = existingAssignments.map(function(a, idx) {
        var title = a.testName || ((a.subject || '') + ' Grade ' + (a.grade || ''));
        var status = a.assignmentStatus || 'assigned';
        var statusLabel = status.charAt(0).toUpperCase() + status.slice(1).replace('_', ' ');
        var date = a.assignedAt ? new Date(a.assignedAt).toLocaleDateString() : '';
        var statusClass = status === 'completed' ? 'status-active' : status === 'failed' ? 'status-tobedeleted' : 'status-testing';

        return '<div class="pending-row">' +
            '<div class="pending-row-info">' +
                '<div class="pending-row-title">' + esc(title) + '</div>' +
                '<div class="pending-row-meta"><span class="status-badge ' + statusClass + '">' + esc(statusLabel) + '</span>' +
                    (date ? ' &middot; ' + esc(date) : '') + '</div>' +
            '</div>' +
            (status !== 'completed' ? '<button class="remove-btn" onclick="removeAssignment(' + idx + ')"><i class="fa-solid fa-xmark"></i></button>' : '') +
        '</div>';
    }).join('');
}

/* ── Assign ────────────────────────────────────────────────── */
async function assignTest(subject, grade, idx) {
    if (!selectedStudent) return;
    var btn = document.getElementById('tbtn-' + idx);
    if (btn) { btn.className = 'test-btn loading'; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>'; }
    clearFeedback();

    try {
        var resp = await fetch('/api/assign-test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ student: selectedStudent.sourcedId, subject: subject, grade: grade, email: selectedStudent.email || '' }),
        });
        var data = await resp.json().catch(function() { return {}; });

        if (resp.ok && data.success) {
            // Step 2: Provision on MasteryTrack via Timeback's makeExternalTestAssignment
            var lessonId = data.lessonId || (data.response || {}).lessonId || '';
            var mtResult = null;

            if (lessonId && selectedStudent.sourcedId) {
                try {
                    showFeedback('Provisioning on MasteryTrack...', 'success');
                    var mtResp = await fetch('https://alpha.timeback.com/_serverFn/src_features_powerpath-quiz_services_lesson-mastery_ts--makeExternalTestAssignment_createServerFn_handler?createServerFn', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'include',
                        body: JSON.stringify({ data: { student: selectedStudent.sourcedId, lesson: lessonId }, context: {} }),
                    });
                    mtResult = await mtResp.json().catch(function() { return null; });
                    console.log('MasteryTrack provision result:', mtResult);
                } catch(e) {
                    console.warn('MasteryTrack provision failed (may need to be logged into alpha.timeback.com):', e.message);
                }
            }

            var testUrl = '';
            if (mtResult && mtResult.result && mtResult.result.testUrl) {
                testUrl = mtResult.result.testUrl;
            } else if (data.testLink) {
                testUrl = data.testLink;
            }

            var msg = data.message || 'Test assigned!';
            if (mtResult && mtResult.result && mtResult.result.success) {
                msg += ' (MasteryTrack: ready)';
            } else if (lessonId) {
                msg += ' (MasteryTrack: pending — open alpha.timeback.com to activate)';
            }

            showFeedback(msg + (testUrl ? ' <a href="' + testUrl + '" target="_blank" style="color:inherit;text-decoration:underline;">Open Test</a>' : ''), 'success');
            existingAssignments.push({
                sourcedId: data.assignmentId || (ppResponse.assignmentId) || '',
                subject: subject, grade: grade,
                assignmentStatus: 'assigned',
                assignedAt: new Date().toISOString(),
                testName: subject + ' Grade ' + grade,
            });
            renderTests();
            renderPending();
        } else {
            console.log('Assign error response:', JSON.stringify(data));

            // Build helpful error using placement data we already fetched
            var plGrade = getPlacementGrade(subject);
            var errMsg = '';

            if (data.httpStatus === 500 && plGrade != null) {
                if (plGrade === grade) {
                    errMsg = subject + ' Grade ' + grade + ' failed. Student is placed at this level but the test may already be assigned or not available.';
                } else {
                    errMsg = 'Cannot assign ' + subject + ' Grade ' + grade + '. Student is placed at Grade ' + plGrade + '. Try assigning Grade ' + plGrade + ' instead.';
                }
            } else if (data.httpStatus === 500) {
                errMsg = subject + ' Grade ' + grade + ' is not available for this student. Check their placement level.';
            } else {
                errMsg = data.error || 'Assignment failed (HTTP ' + (data.httpStatus || '?') + ')';
            }

            showFeedback(errMsg, 'error');
            if (btn) { btn.className = 'test-btn assign'; btn.innerHTML = '<i class="fa-solid fa-plus" style="margin-right:3px;"></i>Assign'; }
        }
    } catch(e) {
        showFeedback('Network error. Try again.', 'error');
        if (btn) { btn.className = 'test-btn assign'; btn.innerHTML = '<i class="fa-solid fa-plus" style="margin-right:3px;"></i>Assign'; }
    }
}

/* ── Remove ────────────────────────────────────────────────── */
async function removeAssignment(idx) {
    var a = existingAssignments[idx];
    if (!a) return;
    existingAssignments.splice(idx, 1);
    renderPending();
    renderTests();
    try {
        await fetch('/api/assign-test', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ assignmentId: a.sourcedId || '', student: selectedStudent ? selectedStudent.sourcedId : '', subject: a.subject || '', grade: a.grade || '' }),
        });
    } catch(e) {}
}

function showFeedback(msg, type) { document.getElementById('assign-feedback').innerHTML = '<div class="feedback ' + type + '">' + esc(msg) + '</div>'; }
function clearFeedback() { document.getElementById('assign-feedback').innerHTML = ''; }

/* ══════════════════════════════════════════════════════════════════
   COURSE DIAGNOSTICS — Generate & Assign AI-built mastery tests
   ══════════════════════════════════════════════════════════════════ */

var diagCourses = [];          // courses that have skill trees
var diagFilteredCourses = [];
var diagSelectedCourse = null; // { sourcedId, title, ... }
var diagSelectedStudent = null;
var diagPollTimer = null;
var diagCurrentDiagnostic = null;
var DIAG_POLL_INTERVAL = 15000;

/* ── External app detection (mirrors course-editor.js) ────────── */
var DIAG_EXTERNAL_APP_KEYS = new Set([
    'gumpp', 'runestone', 'newsela', 'khan', 'readtheory', 'commonlit',
    'knewton', 'alta', 'lalilo', 'rocketmath', 'zearn',
    'renaissance', 'starreading', 'starmath',
    'edmentum', 'mathacademy', 'membean',
]);

function diagIsExternal(c) {
    var meta = c.metadata || {};
    var app = (meta.app || meta.primaryApp || '').toLowerCase().replace(/[\s_-]/g, '');
    if (!app) return false;
    for (var key of DIAG_EXTERNAL_APP_KEYS) { if (app.includes(key)) return true; }
    return false;
}

/* ── Load courses with skill trees ────────────────────────────── */
async function diagLoadCourses() {
    var el = document.getElementById('diag-courses-list');
    el.innerHTML = '<div class="empty-state"><i class="fa-solid fa-spinner fa-spin" style="opacity:0.5;"></i><p>Loading courses with learning trees...</p></div>';

    try {
        var resp = await fetch('/api/courses');
        var data = await resp.json();
        var all = data.courses || [];

        // Filter to AP courses (exclude external app courses)
        var apCourses = all.filter(function(c) { return /\bAP\b/i.test(c.title || '') && !diagIsExternal(c); });

        // Check which courses have skill trees (batch check via diagnostic-status or skill-tree-status)
        var coursesWithTrees = [];
        var checks = apCourses.map(function(c) {
            return fetch('/api/skill-tree-status?courseId=' + encodeURIComponent(c.sourcedId))
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    if (d.status === 'done' && d.mermaid) {
                        c._hasTree = true;
                        c._nodeCount = (d.mermaid.match(/\w+\["[^"]*"\]/g) || []).length;
                        coursesWithTrees.push(c);
                    }
                })
                .catch(function() {});
        });

        await Promise.all(checks);

        // Also check for existing diagnostics
        var diagChecks = coursesWithTrees.map(function(c) {
            return fetch('/api/diagnostic-status?courseId=' + encodeURIComponent(c.sourcedId))
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    if (d.status === 'done') {
                        c._hasDiagnostic = true;
                        c._diagItemCount = d.itemCount || 0;
                    } else if (d.status === 'processing') {
                        c._diagGenerating = true;
                    }
                })
                .catch(function() {});
        });

        await Promise.all(diagChecks);

        diagCourses = coursesWithTrees.sort(function(a, b) {
            return (a.title || '').localeCompare(b.title || '');
        });
        diagFilteredCourses = diagCourses.slice();
        diagRenderCourses();
    } catch(e) {
        el.innerHTML = '<div class="empty-state"><i class="fa-solid fa-circle-exclamation"></i><p>Failed to load courses.</p></div>';
    }
}

function diagFilterCourses() {
    var q = (document.getElementById('diag-course-search').value || '').toLowerCase().trim();
    if (!q) {
        diagFilteredCourses = diagCourses.slice();
    } else {
        diagFilteredCourses = diagCourses.filter(function(c) {
            return (c.title || '').toLowerCase().includes(q) || (c.courseCode || '').toLowerCase().includes(q);
        });
    }
    diagRenderCourses();
}

function diagRenderCourses() {
    var el = document.getElementById('diag-courses-list');
    if (!diagFilteredCourses.length) {
        el.innerHTML = '<div class="empty-state"><i class="fa-solid fa-tree"></i><p>No courses with learning trees found.<br><span style="font-size:0.78rem;color:var(--color-text-muted);">Generate skill trees in the Edit Course tab first.</span></p></div>';
        return;
    }

    el.innerHTML = diagFilteredCourses.map(function(c) {
        var isSelected = diagSelectedCourse && diagSelectedCourse.sourcedId === c.sourcedId;
        var statusBadge = '';
        if (c._hasDiagnostic) {
            statusBadge = '<span class="diag-badge done"><i class="fa-solid fa-check"></i> ' + c._diagItemCount + ' items</span>';
        } else if (c._diagGenerating) {
            statusBadge = '<span class="diag-badge generating"><i class="fa-solid fa-spinner fa-spin"></i> Generating</span>';
        }

        return '<div class="diag-course-row' + (isSelected ? ' selected' : '') + '" onclick="diagSelectCourse(\'' + esc(c.sourcedId) + '\')">' +
            '<div class="diag-course-info">' +
                '<div class="diag-course-title">' + esc(c.title) + '</div>' +
                '<div class="diag-course-meta">' + esc(c.courseCode || '') + ' &middot; ' + (c._nodeCount || '?') + ' skills</div>' +
            '</div>' +
            statusBadge +
        '</div>';
    }).join('');
}

var diagAvailableUnits = [];   // [{ id: 'U1', label: 'Unit 1: Topic' }, ...]
var diagSelectedUnits = [];    // ['U1', 'U2', ...] — empty means all
var diagCourseMermaid = '';     // raw mermaid for the selected course

/* ── Select a course ──────────────────────────────────────────── */
function diagSelectCourse(courseId) {
    var c = diagCourses.find(function(x) { return x.sourcedId === courseId; });
    if (!c) return;

    diagSelectedCourse = c;
    diagAvailableUnits = [];
    diagSelectedUnits = [];
    diagCourseMermaid = '';
    diagRenderCourses(); // re-render to show selection

    document.getElementById('diag-gen-panel').style.display = '';
    document.getElementById('diag-course-name').textContent = c.title;
    document.getElementById('diag-unit-select').innerHTML = '';

    // Fetch mermaid to parse units, then check status
    diagLoadUnits(courseId);
    diagCheckStatus(courseId);
}

/* ── Load and render unit checkboxes ──────────────────────────── */
async function diagLoadUnits(courseId) {
    try {
        var resp = await fetch('/api/skill-tree-status?courseId=' + encodeURIComponent(courseId));
        var data = await resp.json();
        if (data.status !== 'done' || !data.mermaid) return;

        diagCourseMermaid = data.mermaid;

        // Parse subgraphs: subgraph U1["Unit 1: Topic Name"]
        var units = [];
        var re = /subgraph\s+(\w+)\["([^"]+)"\]/g;
        var m;
        while ((m = re.exec(data.mermaid)) !== null) {
            units.push({ id: m[1], label: m[2] });
        }

        diagAvailableUnits = units;
        diagSelectedUnits = units.map(function(u) { return u.id; }); // all selected by default
        diagRenderUnitSelect();
    } catch(e) {}
}

function diagRenderUnitSelect() {
    var el = document.getElementById('diag-unit-select');
    if (!diagAvailableUnits.length) { el.innerHTML = ''; return; }

    var html = '<div class="diag-unit-picker">' +
        '<div class="diag-unit-picker-header">' +
            '<span class="diag-unit-picker-label"><i class="fa-solid fa-layer-group" style="margin-right:5px;"></i>Select Units to Include</span>' +
            '<button class="diag-btn" onclick="diagToggleAllUnits()" style="font-size:0.72rem;padding:3px 8px;">Toggle All</button>' +
        '</div>' +
        '<div class="diag-unit-checkboxes">';

    for (var i = 0; i < diagAvailableUnits.length; i++) {
        var u = diagAvailableUnits[i];
        var checked = diagSelectedUnits.indexOf(u.id) >= 0 ? ' checked' : '';
        html += '<label class="diag-unit-checkbox">' +
            '<input type="checkbox" value="' + esc(u.id) + '"' + checked + ' onchange="diagToggleUnit(\'' + esc(u.id) + '\', this.checked)">' +
            '<span>' + esc(u.label) + '</span>' +
        '</label>';
    }

    html += '</div></div>';
    el.innerHTML = html;
}

function diagToggleUnit(unitId, checked) {
    if (checked) {
        if (diagSelectedUnits.indexOf(unitId) < 0) diagSelectedUnits.push(unitId);
    } else {
        diagSelectedUnits = diagSelectedUnits.filter(function(id) { return id !== unitId; });
    }
}

function diagToggleAllUnits() {
    if (diagSelectedUnits.length === diagAvailableUnits.length) {
        // Deselect all
        diagSelectedUnits = [];
    } else {
        // Select all
        diagSelectedUnits = diagAvailableUnits.map(function(u) { return u.id; });
    }
    diagRenderUnitSelect();
}

/* ── Check diagnostic status for selected course ──────────────── */
async function diagCheckStatus(courseId) {
    var area = document.getElementById('diag-status-area');
    area.innerHTML = '<div style="text-align:center;padding:16px;"><i class="fa-solid fa-spinner fa-spin" style="opacity:0.5;margin-right:6px;"></i>Checking status...</div>';

    try {
        var resp = await fetch('/api/diagnostic-status?courseId=' + encodeURIComponent(courseId));
        var data = await resp.json();

        if (data.status === 'done') {
            diagCurrentDiagnostic = data.diagnostic;
            diagRenderDone(data);
        } else if (data.status === 'processing') {
            diagRenderProcessing(data);
            diagStartPolling(courseId);
        } else if (data.status === 'error') {
            diagRenderError(data.error);
        } else {
            diagRenderReady();
        }
    } catch(e) {
        diagRenderError('Failed to check status: ' + e.message);
    }
}

/* ── Render states ────────────────────────────────────────────── */
function diagRenderReady() {
    var area = document.getElementById('diag-status-area');
    area.innerHTML = '<div class="diag-ready">' +
        '<div class="diag-ready-icon"><i class="fa-solid fa-wand-magic-sparkles"></i></div>' +
        '<h3>Ready to Generate</h3>' +
        '<p>AI will analyze the skill tree and create a comprehensive placement assessment with ~50 multiple-choice questions, distractor analysis, and placement cut scores.</p>' +
        '<button class="diag-btn primary large" onclick="diagGenerate()"><i class="fa-solid fa-bolt" style="margin-right:6px;"></i>Generate Diagnostic Assessment</button>' +
    '</div>';
    document.getElementById('diag-assign-panel').style.display = 'none';
}

function diagRenderProcessing(data) {
    var elapsed = data.elapsed || 0;
    var min = Math.floor(elapsed / 60);
    var sec = elapsed % 60;
    var timeStr = min > 0 ? min + 'm ' + sec + 's' : sec + 's';

    // Step descriptions based on elapsed time
    var steps = [
        { time: 0,   label: 'Analyzing skill tree and identifying key gateway nodes', step: 1 },
        { time: 30,  label: 'Generating questions and stimulus passages', step: 2 },
        { time: 90,  label: 'Creating answer options and distractor analysis', step: 3 },
        { time: 180, label: 'Building test blueprint and cut scores', step: 4 },
        { time: 300, label: 'Still working — large skill trees take longer', step: 4 },
    ];
    var currentStep = steps[0];
    for (var si = steps.length - 1; si >= 0; si--) {
        if (elapsed >= steps[si].time) { currentStep = steps[si]; break; }
    }

    var area = document.getElementById('diag-status-area');
    area.innerHTML = '<div class="diag-processing">' +
        '<div class="diag-processing-spinner"><i class="fa-solid fa-spinner fa-spin"></i></div>' +
        '<h3>Generating Diagnostic Assessment</h3>' +
        '<div class="diag-step-indicator">Step ' + currentStep.step + ' of 4</div>' +
        '<p>' + esc(currentStep.label) + '...</p>' +
        '<div class="diag-elapsed">Elapsed: ' + timeStr + '</div>' +
        '<div class="diag-progress-bar"><div class="diag-progress-fill" style="width:' + Math.min(95, (elapsed / 300) * 100) + '%;"></div></div>' +
    '</div>';
    document.getElementById('diag-assign-panel').style.display = 'none';
}

function diagRenderDone(data) {
    var diag = data.diagnostic || {};
    var items = diag.items || [];
    var blueprint = diag.blueprint || {};
    var cutScores = diag.cutScores || [];
    var genDate = diag.generatedAt ? new Date(diag.generatedAt * 1000).toLocaleString() : '';

    var area = document.getElementById('diag-status-area');
    var html = '<div class="diag-done">';

    // Summary stats
    html += '<div class="diag-stats-grid">' +
        '<div class="diag-stat"><div class="diag-stat-value">' + items.length + '</div><div class="diag-stat-label">Questions</div></div>' +
        '<div class="diag-stat"><div class="diag-stat-value">' + (blueprint.avgDifficulty ? (blueprint.avgDifficulty).toFixed(2) : '~0.50') + '</div><div class="diag-stat-label">Avg Difficulty</div></div>' +
        '<div class="diag-stat"><div class="diag-stat-value">' + cutScores.length + '</div><div class="diag-stat-label">Placement Levels</div></div>' +
        '<div class="diag-stat"><div class="diag-stat-value">' + (blueprint.domains ? blueprint.domains.length : '?') + '</div><div class="diag-stat-label">Domains</div></div>' +
    '</div>';

    if (genDate) {
        html += '<div class="diag-gen-date"><i class="fa-solid fa-clock" style="margin-right:4px;"></i>Generated: ' + esc(genDate) + '</div>';
    }
    if (data.warning) {
        html += '<div class="diag-warning"><i class="fa-solid fa-triangle-exclamation" style="margin-right:4px;"></i>' + esc(data.warning) + '</div>';
    }

    // Actions
    html += '<div class="diag-actions">' +
        '<button class="diag-btn primary" onclick="diagPreview()"><i class="fa-solid fa-eye" style="margin-right:4px;"></i>Preview Test</button>' +
        '<button class="diag-btn secondary" onclick="diagRegenerate()"><i class="fa-solid fa-arrows-rotate" style="margin-right:4px;"></i>Regenerate</button>' +
    '</div>';

    // Collapsible item preview
    html += '<div class="diag-preview-section">' +
        '<button class="diag-toggle-btn" onclick="diagTogglePreview()"><i class="fa-solid fa-chevron-down" id="diag-preview-chev"></i> View Items (' + items.length + ')</button>' +
        '<div id="diag-items-preview" style="display:none;">';

    for (var i = 0; i < items.length; i++) {
        var item = items[i];
        var diffLabel = (item.targetDifficulty || 0) >= 0.7 ? 'Easy' : (item.targetDifficulty || 0) >= 0.4 ? 'Medium' : 'Hard';
        html += '<div class="diag-item-card">' +
            '<div class="diag-item-header">' +
                '<span class="diag-item-num">Q' + (i + 1) + '</span>' +
                '<span class="diag-item-skill">' + esc(item.gatewayNodeLabel || item.gatewayNodeId || '') + '</span>' +
                '<span class="diag-item-diff ' + diffLabel.toLowerCase() + '">' + diffLabel + '</span>' +
                '<span class="diag-item-bloom">' + esc(item.bloomsLevel || '') + '</span>' +
            '</div>';

        if (item.stimulus) {
            html += '<div class="diag-item-stimulus">' + esc(item.stimulus).substring(0, 200) + (item.stimulus.length > 200 ? '...' : '') + '</div>';
        }

        html += '<div class="diag-item-stem">' + esc(item.stem) + '</div>';
        html += '<div class="diag-item-options">';
        var opts = item.options || [];
        for (var j = 0; j < opts.length; j++) {
            var o = opts[j];
            html += '<div class="diag-item-option' + (o.isCorrect ? ' correct' : '') + '">' +
                '<span class="opt-letter">' + esc(o.id) + '</span>' +
                '<span class="opt-text">' + esc(o.text) + '</span>' +
                (o.isCorrect ? '<i class="fa-solid fa-check" style="color:#2E7D32;margin-left:auto;"></i>' : '') +
                (o.misconception ? '<span class="opt-misconception" title="' + esc(o.misconception) + '"><i class="fa-solid fa-circle-info"></i></span>' : '') +
            '</div>';
        }
        html += '</div></div>';
    }

    html += '</div></div>'; // close preview
    html += '</div>'; // close diag-done

    area.innerHTML = html;

    // Show assignment panel
    document.getElementById('diag-assign-panel').style.display = '';
    diagLoadAssignments();
}

function diagRenderError(msg) {
    var area = document.getElementById('diag-status-area');
    area.innerHTML = '<div class="diag-error">' +
        '<i class="fa-solid fa-circle-exclamation" style="font-size:1.4rem;color:#E53E3E;"></i>' +
        '<p>' + esc(msg) + '</p>' +
        '<button class="diag-btn primary" onclick="diagRenderReady()"><i class="fa-solid fa-arrows-rotate" style="margin-right:4px;"></i>Try Again</button>' +
    '</div>';
}

function diagTogglePreview() {
    var el = document.getElementById('diag-items-preview');
    var chev = document.getElementById('diag-preview-chev');
    if (el.style.display === 'none') {
        el.style.display = '';
        chev.className = 'fa-solid fa-chevron-up';
    } else {
        el.style.display = 'none';
        chev.className = 'fa-solid fa-chevron-down';
    }
}

/* ── Generate diagnostic ──────────────────────────────────────── */
async function diagGenerate() {
    if (!diagSelectedCourse) return;
    var courseId = diagSelectedCourse.sourcedId;

    // Validate at least one unit is selected
    if (diagAvailableUnits.length > 0 && diagSelectedUnits.length === 0) {
        diagRenderError('Please select at least one unit to include in the diagnostic.');
        return;
    }

    diagRenderProcessing({ elapsed: 0, message: 'Submitting generation job...' });

    // Build request body — include selected units if not all selected
    var body = { courseId: courseId };
    if (diagAvailableUnits.length > 0 && diagSelectedUnits.length < diagAvailableUnits.length) {
        body.selectedUnits = diagSelectedUnits;
    }

    try {
        var resp = await fetch('/api/generate-diagnostic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        var data = await resp.json();

        if (data.error) {
            diagRenderError(data.error);
            return;
        }

        diagRenderProcessing({ elapsed: 0, message: 'AI is analyzing the skill tree and creating questions...' });
        diagStartPolling(courseId);
    } catch(e) {
        diagRenderError('Failed to start generation: ' + e.message);
    }
}

function diagRegenerate() {
    if (!confirm('Regenerate the diagnostic? This will replace the existing one.')) return;
    diagCurrentDiagnostic = null;
    diagGenerate();
}

/* ── Polling ──────────────────────────────────────────────────── */
function diagStartPolling(courseId) {
    diagStopPolling();
    diagPollTimer = setInterval(function() {
        diagPollStatus(courseId);
    }, DIAG_POLL_INTERVAL);
}

function diagStopPolling() {
    if (diagPollTimer) {
        clearInterval(diagPollTimer);
        diagPollTimer = null;
    }
}

async function diagPollStatus(courseId) {
    try {
        var resp = await fetch('/api/diagnostic-status?courseId=' + encodeURIComponent(courseId));
        var data = await resp.json();

        if (data.status === 'done') {
            diagStopPolling();
            diagCurrentDiagnostic = data.diagnostic;
            diagRenderDone(data);
            // Update course list
            var c = diagCourses.find(function(x) { return x.sourcedId === courseId; });
            if (c) {
                c._hasDiagnostic = true;
                c._diagItemCount = data.itemCount || 0;
                c._diagGenerating = false;
                diagRenderCourses();
            }
        } else if (data.status === 'processing') {
            diagRenderProcessing(data);
        } else if (data.status === 'error') {
            diagStopPolling();
            diagRenderError(data.error);
        }
    } catch(e) {
        // Keep polling on network errors
    }
}

/* ── Preview ──────────────────────────────────────────────────── */
function diagPreview() {
    if (!diagSelectedCourse) return;
    window.open('/lesson?diagnosticPreview=1&courseId=' + encodeURIComponent(diagSelectedCourse.sourcedId) + '&title=' + encodeURIComponent(diagSelectedCourse.title + ' — Diagnostic'), '_blank');
}

/* ── Student assignment ───────────────────────────────────────── */
var diagSearchTimer = null;
var diagSearchController = null;

document.addEventListener('DOMContentLoaded', function() {
    diagLoadCourses();

    // Set up diagnostic student search
    var dsi = document.getElementById('diag-student-search');
    if (dsi) {
        dsi.addEventListener('input', function() {
            clearTimeout(diagSearchTimer);
            var q = this.value.trim();
            if (q.length < 2) { diagCloseStudentDD(); return; }
            diagSearchTimer = setTimeout(function() { diagSearchStudents(q); }, 250);
        });
    }
    document.addEventListener('click', function(e) {
        if (!e.target.closest('#diag-assign-panel .diag-course-search-wrap')) diagCloseStudentDD();
    });
});

function diagSearchStudents(q) {
    if (diagSearchController) diagSearchController.abort();
    diagSearchController = new AbortController();

    var dd = document.getElementById('diag-student-dropdown');
    dd.innerHTML = '<div class="search-empty"><i class="fa-solid fa-spinner fa-spin" style="margin-right:6px;"></i>Searching...</div>';
    dd.classList.add('open');

    fetch('/api/users-page?search=' + encodeURIComponent(q) + '&limit=20', { signal: diagSearchController.signal })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var users = d.users || [];
            if (!users.length) {
                dd.innerHTML = '<div class="search-empty">No students found.</div>';
                return;
            }
            dd.innerHTML = users.map(function(u) {
                var nm = ((u.givenName || '') + ' ' + (u.familyName || '')).trim() || 'Unknown';
                return '<div class="search-item" data-id="' + esc(u.sourcedId) + '" onclick="diagPickStudent(this)">' +
                    '<div class="user-cell-avatar">' + esc((u.givenName || '?')[0].toUpperCase()) + '</div>' +
                    '<div style="flex:1;min-width:0;"><div class="search-item-name">' + esc(nm) +
                    '</div><div class="search-item-email">' + esc(u.email || '') + '</div></div></div>';
            }).join('');
        })
        .catch(function(e) {
            if (e.name !== 'AbortError') {
                dd.innerHTML = '<div class="search-empty">Search failed.</div>';
            }
        });
}

function diagCloseStudentDD() {
    var dd = document.getElementById('diag-student-dropdown');
    if (dd) dd.classList.remove('open');
}

function diagPickStudent(el) {
    var id = el.getAttribute('data-id');
    var name = el.querySelector('.search-item-name').textContent.trim();
    var email = el.querySelector('.search-item-email').textContent.trim();

    diagSelectedStudent = { sourcedId: id, name: name, email: email };
    diagCloseStudentDD();
    document.getElementById('diag-student-search').value = name;

    var sel = document.getElementById('diag-selected-student');
    sel.style.display = '';
    sel.innerHTML = '<div class="diag-student-card">' +
        '<div class="user-cell-avatar">' + esc(name[0] || '?') + '</div>' +
        '<div style="flex:1;"><div style="font-weight:600;">' + esc(name) + '</div><div style="font-size:0.8rem;color:var(--color-text-muted);">' + esc(email) + '</div></div>' +
        '<button class="diag-btn primary" onclick="diagAssignToStudent()"><i class="fa-solid fa-plus" style="margin-right:4px;"></i>Assign</button>' +
    '</div>';
}

async function diagAssignToStudent() {
    if (!diagSelectedStudent || !diagSelectedCourse) return;

    var fb = document.getElementById('diag-assign-feedback');
    fb.innerHTML = '<div class="feedback success" style="display:block;"><i class="fa-solid fa-spinner fa-spin" style="margin-right:6px;"></i>Assigning...</div>';

    try {
        var resp = await fetch('/api/diagnostic-assign', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                studentId: diagSelectedStudent.sourcedId,
                courseId: diagSelectedCourse.sourcedId,
            }),
        });
        var data = await resp.json();

        if (data.success) {
            fb.innerHTML = '<div class="feedback success" style="display:block;"><i class="fa-solid fa-check" style="margin-right:4px;"></i>' + esc(data.message || 'Assigned!') + '</div>';
            diagLoadAssignments();
            // Clear selection
            document.getElementById('diag-selected-student').style.display = 'none';
            document.getElementById('diag-student-search').value = '';
            diagSelectedStudent = null;
        } else {
            fb.innerHTML = '<div class="feedback error" style="display:block;">' + esc(data.error || 'Assignment failed') + '</div>';
        }
    } catch(e) {
        fb.innerHTML = '<div class="feedback error" style="display:block;">Network error. Try again.</div>';
    }
}

async function diagLoadAssignments() {
    if (!diagSelectedCourse) return;
    var el = document.getElementById('diag-assigned-list');

    try {
        var resp = await fetch('/api/diagnostic-assign?courseId=' + encodeURIComponent(diagSelectedCourse.sourcedId));
        var data = await resp.json();
        var assignments = data.assignments || [];

        if (!assignments.length) {
            el.innerHTML = '<div class="empty-state"><i class="fa-solid fa-clipboard-list"></i><p>No students assigned yet.</p></div>';
            return;
        }

        el.innerHTML = assignments.map(function(a) {
            var status = a.status || 'assigned';
            var statusClass = status === 'completed' ? 'status-active' : status === 'in_progress' ? 'status-testing' : 'status-testing';
            var statusLabel = status.charAt(0).toUpperCase() + status.slice(1).replace('_', ' ');
            var date = a.assignedAt ? new Date(a.assignedAt * 1000).toLocaleDateString() : '';
            var scoreHtml = '';
            if (status === 'completed' && a.score != null) {
                scoreHtml = '<span style="font-weight:700;color:' + (a.score >= 60 ? '#2E7D32' : '#E65100') + ';">' + a.score + '%</span>';
            }

            return '<div class="pending-row">' +
                '<div class="pending-row-info">' +
                    '<div class="pending-row-title">' + esc(a.studentId) + '</div>' +
                    '<div class="pending-row-meta"><span class="status-badge ' + statusClass + '">' + esc(statusLabel) + '</span>' +
                        (date ? ' &middot; ' + esc(date) : '') +
                        (scoreHtml ? ' &middot; ' + scoreHtml : '') +
                    '</div>' +
                '</div>' +
                (status !== 'completed' ? '<button class="remove-btn" onclick="diagRemoveAssignment(\'' + esc(a.studentId) + '\',\'' + esc(a.courseId) + '\')"><i class="fa-solid fa-xmark"></i></button>' : '') +
            '</div>';
        }).join('');
    } catch(e) {
        el.innerHTML = '<div class="empty-state"><i class="fa-solid fa-circle-exclamation"></i><p>Failed to load assignments.</p></div>';
    }
}

async function diagRemoveAssignment(studentId, courseId) {
    if (!confirm('Remove this diagnostic assignment?')) return;
    try {
        await fetch('/api/diagnostic-assign', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ studentId: studentId, courseId: courseId }),
        });
        diagLoadAssignments();
    } catch(e) {}
}
