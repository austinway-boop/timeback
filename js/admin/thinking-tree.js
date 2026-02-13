var selectedStudent = null;

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

    // Show selected card, hide search & placeholder
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
