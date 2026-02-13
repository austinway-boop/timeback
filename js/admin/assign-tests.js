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
