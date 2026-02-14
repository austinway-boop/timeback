/* ====================================================================
   Thinking Tree – Student Skill Mastery Visualization
   ==================================================================== */
var selectedStudent = null;
var isStaging = false;

function esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── Init ──────────────────────────────────────────────────── */
var searchInput, searchTimer;

document.addEventListener('DOMContentLoaded', function() {
    isStaging = !!localStorage.getItem('alphalearn_staging');
    searchInput = document.getElementById('student-search');
    searchInput.addEventListener('input', function() {
        clearTimeout(searchTimer);
        var q = this.value.trim();
        if (q.length < 2) { closeDD(); return; }
        searchTimer = setTimeout(function() { doSearch(q); }, 250);
    });
    document.addEventListener('click', function(e) {
        if (!e.target.closest('.search-wrap')) closeDD();
    });
});

/* ── Search via API ────────────────────────────────────────── */
var searchController = null;

function doSearch(q) {
    if (searchController) searchController.abort();
    searchController = new AbortController();

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
    if (!list.length) {
        dd.innerHTML = '<div class="search-empty">No students found.</div>';
        dd.classList.add('open');
        return;
    }
    dd.innerHTML = list.map(function(u) {
        var nm = ((u.givenName || '') + ' ' + (u.familyName || '')).trim() || 'Unknown';
        return '<div class="search-item" data-id="' + esc(u.sourcedId) + '"' +
            ' data-given="' + esc(u.givenName) + '"' +
            ' data-family="' + esc(u.familyName) + '"' +
            ' data-email="' + esc(u.email) + '"' +
            ' onclick="pickStudent(this)">' +
            '<div class="user-cell-avatar">' + esc((u.givenName || '?')[0].toUpperCase()) + '</div>' +
            '<div style="flex:1;min-width:0;">' +
                '<div class="search-item-name">' + esc(nm) + '</div>' +
                '<div class="search-item-email">' + esc(u.email || '') + '</div>' +
            '</div></div>';
    }).join('');
    dd.classList.add('open');
}

function closeDD() {
    document.getElementById('search-dropdown').classList.remove('open');
}

/* ── Pick Student ──────────────────────────────────────────── */
function pickStudent(el) {
    var user = {
        sourcedId:  el.getAttribute('data-id'),
        givenName:  el.getAttribute('data-given') || '',
        familyName: el.getAttribute('data-family') || '',
        email:      el.getAttribute('data-email') || '',
    };

    selectedStudent = user;
    closeDD();

    var nm = ((user.givenName || '') + ' ' + (user.familyName || '')).trim() || 'Unknown';
    var initial = (user.givenName || '?')[0].toUpperCase();

    document.getElementById('search-section').style.display = 'none';
    document.getElementById('placeholder').style.display = 'none';

    document.getElementById('selected-student-card').style.display = '';
    document.getElementById('selected-student-card').innerHTML =
        '<div class="selected-student">' +
            '<div class="student-avatar">' + esc(initial) + '</div>' +
            '<div class="student-info">' +
                '<div class="student-name">' + esc(nm) + '</div>' +
                '<div class="student-email">' + esc(user.email) + '</div>' +
            '</div>' +
            '<button class="deselect-btn" onclick="clearStudent()"><i class="fa-solid fa-xmark" style="margin-right:4px;"></i>Change</button>' +
        '</div>';

    document.getElementById('tree-content').style.display = '';
    loadTreeContent();
}

/* ── Clear Student ─────────────────────────────────────────── */
function clearStudent() {
    selectedStudent = null;

    document.getElementById('selected-student-card').style.display = 'none';
    document.getElementById('tree-content').style.display = 'none';

    document.getElementById('search-section').style.display = '';
    document.getElementById('placeholder').style.display = '';

    searchInput.value = '';
    searchInput.focus();
}

/* ── Load Tree Content ─────────────────────────────────────── */
async function loadTreeContent() {
    var el = document.getElementById('tree-content');

    // Staging gate
    if (!isStaging) {
        el.innerHTML =
            '<div class="tt-notice">' +
                '<i class="fa-solid fa-flask"></i>' +
                '<div>' +
                    '<strong>Staging Mode Required</strong>' +
                    '<p>Skill mastery tracking is currently only available in staging mode. Go to the <a href="/staging">Staging Hub</a> to enable it.</p>' +
                '</div>' +
            '</div>';
        return;
    }

    el.innerHTML = '<div class="tt-loading"><div class="tt-spinner"></div> Loading skill-mapped courses...</div>';

    // Fetch courses with skill mapping enabled
    try {
        var resp = await fetch('/api/skill-mapping-toggle?list=true');
        var data = await resp.json();
        var enabledCourses = data.courses || [];

        if (!enabledCourses.length) {
            el.innerHTML =
                '<div class="tt-notice">' +
                    '<i class="fa-solid fa-info-circle"></i>' +
                    '<div>' +
                        '<strong>No courses with skill mapping</strong>' +
                        '<p>No courses have skill mapping enabled yet. Go to <a href="/admin/course-editor">Course Editor</a> to set up a course with hole filling / mastery detection, then enable the skill mapping toggle.</p>' +
                    '</div>' +
                '</div>';
            return;
        }

        // Fetch course details for each enabled course
        var coursesResp = await fetch('/api/courses');
        var coursesData = await coursesResp.json();
        var allCourses = coursesData.courses || [];
        var courseMap = {};
        allCourses.forEach(function(c) { courseMap[c.sourcedId] = c; });

        var html = '<div class="tt-course-list">';
        enabledCourses.forEach(function(cid) {
            var c = courseMap[cid];
            var title = c ? c.title : cid;
            var code = c ? (c.courseCode || '') : '';
            html += '<div class="tt-course-card" data-course-id="' + esc(cid) + '">' +
                '<div class="tt-course-card-icon"><i class="fa-solid fa-graduation-cap"></i></div>' +
                '<div class="tt-course-card-info">' +
                    '<strong>' + esc(title) + '</strong>' +
                    (code ? '<span>' + esc(code) + '</span>' : '') +
                '</div>' +
                '<button class="tt-view-btn" onclick="loadSkillScores(\'' + esc(cid) + '\')"><i class="fa-solid fa-eye" style="margin-right:4px;"></i>View Skills</button>' +
            '</div>';
        });
        html += '</div>';
        html += '<div id="skill-scores-container"></div>';
        el.innerHTML = html;

    } catch (e) {
        el.innerHTML = '<div class="tt-notice"><i class="fa-solid fa-circle-exclamation"></i><div><strong>Error</strong><p>Failed to load courses. Please try again.</p></div></div>';
    }
}

/* ── Load Skill Scores ─────────────────────────────────────── */
async function loadSkillScores(courseId) {
    var container = document.getElementById('skill-scores-container');
    if (!container) return;
    if (!selectedStudent) return;

    container.innerHTML = '<div class="tt-loading"><div class="tt-spinner"></div> Computing skill scores for ' + esc(selectedStudent.givenName || 'student') + '...</div>';

    try {
        var resp = await fetch('/api/compute-skill-scores?studentId=' + encodeURIComponent(selectedStudent.sourcedId) + '&courseId=' + encodeURIComponent(courseId));
        var data = await resp.json();

        if (data.error) {
            container.innerHTML = '<div class="tt-notice"><i class="fa-solid fa-circle-exclamation"></i><div><strong>Error</strong><p>' + esc(data.error) + '</p></div></div>';
            return;
        }

        renderSkillTree(data, container);
    } catch (e) {
        container.innerHTML = '<div class="tt-notice"><i class="fa-solid fa-circle-exclamation"></i><div><strong>Error</strong><p>Failed to compute skill scores.</p></div></div>';
    }
}

/* ── Render Skill Tree ─────────────────────────────────────── */
function renderSkillTree(data, container) {
    var skills = data.skills || {};
    var summary = data.summary || {};
    var skillIds = Object.keys(skills);

    if (!skillIds.length) {
        container.innerHTML = '<div class="tt-notice"><i class="fa-solid fa-info-circle"></i><div><strong>No skill data</strong><p>No skill scores could be computed. The student may not have answered any questions yet.</p></div></div>';
        return;
    }

    // Summary bar
    var html = '<div class="tt-summary">' +
        '<h3 class="tt-summary-title"><i class="fa-solid fa-chart-bar" style="margin-right:8px; opacity:0.5;"></i>Skill Mastery Overview</h3>' +
        '<div class="tt-summary-stats">' +
            '<div class="tt-stat mastered"><span class="tt-stat-num">' + (summary.mastered || 0) + '</span><span class="tt-stat-label">Mastered</span></div>' +
            '<div class="tt-stat developing"><span class="tt-stat-num">' + (summary.developing || 0) + '</span><span class="tt-stat-label">Developing</span></div>' +
            '<div class="tt-stat weak"><span class="tt-stat-num">' + (summary.weak || 0) + '</span><span class="tt-stat-label">Weak</span></div>' +
            '<div class="tt-stat not-learned"><span class="tt-stat-num">' + (summary.notLearned || 0) + '</span><span class="tt-stat-label">Not Learned</span></div>' +
        '</div>' +
        '<div class="tt-summary-bar">' +
            '<div class="tt-bar-segment mastered" style="width:' + pct(summary.mastered, summary.total) + '%"></div>' +
            '<div class="tt-bar-segment developing" style="width:' + pct(summary.developing, summary.total) + '%"></div>' +
            '<div class="tt-bar-segment weak" style="width:' + pct(summary.weak, summary.total) + '%"></div>' +
            '<div class="tt-bar-segment not-learned" style="width:' + pct(summary.notLearned, summary.total) + '%"></div>' +
        '</div>' +
        '<div class="tt-summary-detail">' + (summary.answeredQuestions || 0) + ' questions answered across ' + (summary.total || 0) + ' skills</div>' +
    '</div>';

    // Skill grid
    html += '<div class="tt-skill-grid">';
    skillIds.forEach(function(sid) {
        var s = skills[sid];
        var level = s.mastery || 'not_learned';
        var scoreWidth = Math.max(0, Math.min(100, s.score || 0));
        html += '<div class="tt-skill-node ' + level.replace('_', '-') + '">' +
            '<div class="tt-skill-header">' +
                '<span class="tt-skill-id">' + esc(sid) + '</span>' +
                '<span class="tt-skill-score">' + Math.round(s.score || 0) + '</span>' +
            '</div>' +
            '<div class="tt-skill-label">' + esc(s.label || sid) + '</div>' +
            '<div class="tt-skill-bar"><div class="tt-skill-bar-fill" style="width:' + scoreWidth + '%"></div></div>' +
            '<div class="tt-skill-meta">' +
                (s.answeredQuestions > 0 ? s.correctQuestions + '/' + s.answeredQuestions + ' correct' : 'No data') +
                ' &bull; ' + s.totalQuestions + ' questions' +
            '</div>' +
        '</div>';
    });
    html += '</div>';

    container.innerHTML = html;
}

function pct(val, total) {
    if (!total) return 0;
    return Math.round((val / total) * 100);
}
