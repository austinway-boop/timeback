/* =========================================================================
   Admin Students — v4: All-at-once, role editing, assign tests, create users
   ========================================================================= */
const PER_PAGE = 50;
const ROLE_CHANGES_KEY = 'alphalearn_role_changes';
const LOCAL_USERS_KEY = 'alphalearn_local_users';
const ADMIN_WHITELIST_KEY = 'alphalearn_admin_whitelist';
const DEFAULT_ADMINS = ['twsevenyw@gmail.com', 'austin.way@alpha.school'];

let allUsers = [];
let filteredUsers = [];
let currentPage = 1;
let sortField = 'name';
let sortDir = 'asc';
let currentStudentId = null;
let lineItemsCache = null;
let selectedIds = new Set();
let assignTargetUsers = [];

/* =====================================================================
   Course Picker — searchable, paginated dropdown (loads 10 at a time)
   ===================================================================== */
const coursePickers = {
    modal: { courses:[], offset:0, hasMore:true, loading:false, selectedId:'', selectedTitle:'', searchQuery:'', searchTimeout:null },
    bulk:  { courses:[], offset:0, hasMore:true, loading:false, selectedId:'', selectedTitle:'', searchQuery:'', searchTimeout:null },
};
const COURSES_PER_PAGE = 10;

function initCoursePicker(pickerId) {
    const state = coursePickers[pickerId];
    state.courses=[]; state.offset=0; state.hasMore=true;
    state.loading=false; state.selectedId=''; state.selectedTitle='';
    state.searchQuery=''; clearTimeout(state.searchTimeout);
    const picker = document.getElementById(`${pickerId}-course-picker`);
    if (!picker) return;
    const txt = picker.querySelector('.course-picker-text');
    if (txt) { txt.textContent='Select a course...'; txt.classList.add('placeholder'); }
    const inp = picker.querySelector('input[type="text"]');
    if (inp) inp.value='';
    const btnId = pickerId==='modal' ? 'modal-course-btn' : 'bulk-course-confirm';
    const btn = document.getElementById(btnId);
    if (btn) btn.disabled=true;
    loadCoursesForPicker(pickerId, false);
}

function toggleCoursePicker(pickerId) {
    const dropdown = document.getElementById(`${pickerId}-course-dropdown`);
    const trigger = document.getElementById(`${pickerId}-course-picker`).querySelector('.course-picker-trigger');
    const wasOpen = dropdown.classList.contains('open');
    closeAllCoursePickers();
    if (!wasOpen) {
        trigger.classList.add('open');
        dropdown.classList.add('open');
        const inp = dropdown.querySelector('input');
        if (inp) setTimeout(() => inp.focus(), 50);
    }
}

function closeAllCoursePickers() {
    document.querySelectorAll('.course-picker-dropdown.open').forEach(d => {
        d.classList.remove('open');
        const t = d.parentElement.querySelector('.course-picker-trigger');
        if (t) t.classList.remove('open');
    });
}

async function loadCoursesForPicker(pickerId, append) {
    const state = coursePickers[pickerId];
    if (state.loading) return;
    state.loading = true;
    const list = document.getElementById(`${pickerId}-course-list`);
    const footer = document.getElementById(`${pickerId}-course-footer`);
    if (!append) {
        state.offset=0; state.courses=[];
        if (list) list.innerHTML='<div class="course-picker-status"><div class="loading-spinner" style="width:18px;height:18px;border-width:2px;margin:0 auto 6px;"></div>Loading courses...</div>';
    }
    if (footer) footer.innerHTML='';
    try {
        const params = new URLSearchParams({limit:COURSES_PER_PAGE, offset:state.offset});
        if (state.searchQuery) params.set('q', state.searchQuery);
        const resp = await fetch(`/api/courses/search?${params}`);
        const data = await resp.json();
        const newCourses = data.courses || [];
        state.courses = append ? state.courses.concat(newCourses) : newCourses;
        state.hasMore = data.hasMore !== false && newCourses.length === COURSES_PER_PAGE;
        state.offset += newCourses.length;
        renderCoursePicker(pickerId);
    } catch {
        if (!append && list) list.innerHTML='<div class="course-picker-status"><i class="fa-solid fa-circle-exclamation" style="margin-right:6px;"></i>Failed to load courses.</div>';
        if (footer) footer.innerHTML='';
    }
    state.loading = false;
}

function renderCoursePicker(pickerId) {
    const state = coursePickers[pickerId];
    const list = document.getElementById(`${pickerId}-course-list`);
    const footer = document.getElementById(`${pickerId}-course-footer`);
    if (!list) return;
    if (state.courses.length===0) {
        list.innerHTML='<div class="course-picker-status">No courses found.</div>';
        if (footer) footer.innerHTML='';
        return;
    }
    list.innerHTML = state.courses.map(c => {
        const sel = c.sourcedId===state.selectedId ? ' selected' : '';
        return `<div class="course-picker-item${sel}" data-id="${esc(c.sourcedId)}" onclick="selectCourse('${pickerId}',this.dataset.id)">${esc(c.title||'Untitled')}</div>`;
    }).join('');
    if (footer) footer.innerHTML = state.hasMore
        ? `<button class="course-picker-load-more" onclick="loadCoursesForPicker('${pickerId}',true)">Load More</button>`
        : '';
}

function selectCourse(pickerId, courseId) {
    const state = coursePickers[pickerId];
    const course = state.courses.find(c => c.sourcedId===courseId);
    state.selectedId = courseId;
    state.selectedTitle = course ? (course.title||'Untitled') : '';
    const txt = document.getElementById(`${pickerId}-course-picker`).querySelector('.course-picker-text');
    if (txt) { txt.textContent=state.selectedTitle; txt.classList.remove('placeholder'); }
    const list = document.getElementById(`${pickerId}-course-list`);
    if (list) list.querySelectorAll('.course-picker-item').forEach(el => el.classList.toggle('selected', el.dataset.id===courseId));
    closeAllCoursePickers();
    const btnId = pickerId==='modal' ? 'modal-course-btn' : 'bulk-course-confirm';
    const btn = document.getElementById(btnId);
    if (btn) btn.disabled=false;
}

function onCourseSearch(pickerId, value) {
    const state = coursePickers[pickerId];
    clearTimeout(state.searchTimeout);
    state.searchTimeout = setTimeout(() => {
        state.searchQuery = value.trim();
        loadCoursesForPicker(pickerId, false);
    }, 300);
}

document.addEventListener('mousedown', function(e) {
    if (!e.target.closest('.course-picker')) closeAllCoursePickers();
});

document.addEventListener('DOMContentLoaded', init);

/* =====================================================================
   Init
   ===================================================================== */
async function init() {
    showSkeleton(10);
    try {
        const resp = await fetch('/api/users/index');
        const data = await resp.json();
        allUsers = data.users || [];
        // Merge in locally-created users
        const localUsers = getLocalUsers();
        if (localUsers.length) allUsers = allUsers.concat(localUsers);
        // Apply pending role changes
        applyRoleChanges();
        renderRoleStats();
        filterAndRender();
    } catch {
        document.getElementById('students-tbody').innerHTML = '<tr><td colspan="6" class="loading-cell error-cell"><i class="fa-solid fa-circle-exclamation"></i> Failed to load students</td></tr>';
    }
}

function showSkeleton(n) {
    let html = '';
    for (let i = 0; i < n; i++) {
        const w1 = 40 + Math.random() * 30, w2 = 50 + Math.random() * 30;
        html += `<tr><td><div class="skeleton-bar" style="width:16px;height:16px;border-radius:3px;"></div></td><td><div style="display:flex;align-items:center;gap:12px;"><div class="skeleton-avatar"></div><div><div class="skeleton-bar" style="width:${w1}%;margin-bottom:4px;"></div><div class="skeleton-bar" style="width:50%;height:10px;"></div></div></div></td><td><div class="skeleton-bar" style="width:${w2}%;"></div></td><td><div class="skeleton-bar" style="width:60px;"></div></td><td><div class="skeleton-bar" style="width:55px;"></div></td><td><div class="skeleton-bar" style="width:28px;height:28px;border-radius:6px;"></div></td></tr>`;
    }
    document.getElementById('students-tbody').innerHTML = html;
}

/* =====================================================================
   Role Changes (localStorage)
   ===================================================================== */
function getRoleChanges() { try { return JSON.parse(localStorage.getItem(ROLE_CHANGES_KEY) || '{}'); } catch { return {}; } }
function saveRoleChange(userId, newRole) {
    const c = getRoleChanges(); c[userId] = newRole;
    localStorage.setItem(ROLE_CHANGES_KEY, JSON.stringify(c));
}
function applyRoleChanges() {
    const changes = getRoleChanges();
    allUsers.forEach(u => { if (changes[u.sourcedId]) u.role = changes[u.sourcedId]; });
}

/* =====================================================================
   Local Users (localStorage)
   ===================================================================== */
function getLocalUsers() { try { return JSON.parse(localStorage.getItem(LOCAL_USERS_KEY) || '[]'); } catch { return []; } }
function addLocalUser(user) {
    const users = getLocalUsers(); users.push(user);
    localStorage.setItem(LOCAL_USERS_KEY, JSON.stringify(users));
}

/* =====================================================================
   Admin Whitelist
   ===================================================================== */
function getAdminWhitelist() {
    try { const custom = JSON.parse(localStorage.getItem(ADMIN_WHITELIST_KEY) || '[]'); return [...DEFAULT_ADMINS, ...custom]; } catch { return [...DEFAULT_ADMINS]; }
}
function addToWhitelist(email) {
    const custom = JSON.parse(localStorage.getItem(ADMIN_WHITELIST_KEY) || '[]');
    if (!custom.includes(email) && !DEFAULT_ADMINS.includes(email)) { custom.push(email); localStorage.setItem(ADMIN_WHITELIST_KEY, JSON.stringify(custom)); }
}

/* =====================================================================
   Role Stats
   ===================================================================== */
function renderRoleStats() {
    const counts = { student: 0, teacher: 0, administrator: 0, aide: 0 };
    allUsers.forEach(u => { if (counts.hasOwnProperty(u.role)) counts[u.role]++; });
    const icons = { student: 'fa-user-graduate', teacher: 'fa-chalkboard-user', administrator: 'fa-user-shield', aide: 'fa-user-plus' };
    const labels = { student: 'Students', teacher: 'Teachers', administrator: 'Admins', aide: 'Aides' };
    document.getElementById('role-stats').innerHTML =
        `<div class="role-stat-chip"><i class="fa-solid fa-users" style="color:var(--color-primary);"></i><span class="stat-num">${allUsers.length}</span> Total</div>` +
        Object.entries(counts).filter(([_, v]) => v > 0).map(([role, count]) =>
            `<div class="role-stat-chip"><i class="fa-solid ${icons[role]}" style="color:var(--color-text-muted);"></i><span class="stat-num">${count}</span> ${labels[role]}</div>`
        ).join('');
}

/* =====================================================================
   Filter & Sort & Render
   ===================================================================== */
function filterAndRender() {
    const q = document.getElementById('student-search').value.toLowerCase();
    const rf = document.getElementById('role-filter').value;
    const sf = document.getElementById('status-filter').value;
    filteredUsers = allUsers.filter(u => {
        const name = `${u.givenName} ${u.familyName}`.toLowerCase();
        return (!q || name.includes(q) || (u.email||'').toLowerCase().includes(q) || (u.username||'').toLowerCase().includes(q))
            && (!rf || u.role === rf) && (!sf || u.status === sf);
    });
    filteredUsers.sort((a, b) => {
        let va, vb;
        if (sortField === 'name') { va = `${a.givenName} ${a.familyName}`.toLowerCase(); vb = `${b.givenName} ${b.familyName}`.toLowerCase(); }
        else if (sortField === 'email') { va = (a.email||'').toLowerCase(); vb = (b.email||'').toLowerCase(); }
        else if (sortField === 'role') { va = (a.role||'').toLowerCase(); vb = (b.role||'').toLowerCase(); }
        return va < vb ? (sortDir==='asc'?-1:1) : va > vb ? (sortDir==='asc'?1:-1) : 0;
    });
    currentPage = 1;
    renderTable();
    renderPagination();
}

function renderTable() {
    const start = (currentPage - 1) * PER_PAGE;
    const page = filteredUsers.slice(start, start + PER_PAGE);
    const total = filteredUsers.length;
    if (!total) { document.getElementById('results-count').textContent = 'No users match your filters'; document.getElementById('students-tbody').innerHTML = '<tr><td colspan="6" class="loading-cell">No students found</td></tr>'; return; }
    document.getElementById('results-count').textContent = `Showing ${start+1}\u2013${Math.min(start+PER_PAGE,total)} of ${total} users`;
    const rc = { student:'role-student', teacher:'role-teacher', administrator:'role-admin', aide:'role-aide' };
    document.getElementById('students-tbody').innerHTML = page.map(u => {
        const ck = selectedIds.has(u.sourcedId) ? 'checked' : '';
        return `<tr><td><input type="checkbox" class="bulk-checkbox row-checkbox" data-id="${u.sourcedId}" ${ck} onchange="toggleRow('${u.sourcedId}',this.checked)"></td><td><div class="user-cell"><div class="user-cell-avatar">${(u.givenName||'?')[0].toUpperCase()}</div><div><div class="user-cell-name">${esc(u.givenName)} ${esc(u.familyName)}</div><div class="user-cell-username">${esc(u.username||'')}</div></div></div></td><td class="email-cell">${esc(u.email||'\u2014')}</td><td><span class="role-badge ${rc[u.role]||''}">${u.role||'\u2014'}</span></td><td><span class="status-badge status-${u.status}">${u.status||'\u2014'}</span></td><td><button class="action-btn" onclick="viewStudent('${u.sourcedId}')" title="View details"><i class="fa-solid fa-eye"></i></button></td></tr>`;
    }).join('');
    const allOnPage = page.map(u => u.sourcedId);
    document.getElementById('select-all-checkbox').checked = allOnPage.length > 0 && allOnPage.every(id => selectedIds.has(id));
}

function renderPagination() {
    const tp = Math.ceil(filteredUsers.length / PER_PAGE);
    if (tp <= 1) { document.getElementById('pagination').innerHTML = ''; return; }
    let h = `<button class="page-btn ${currentPage===1?'disabled':''}" onclick="goPage(${currentPage-1})">&laquo;</button>`;
    const s = Math.max(1,currentPage-2), e = Math.min(tp,currentPage+2);
    if (s>1) h += `<button class="page-btn" onclick="goPage(1)">1</button><span class="page-dots">\u2026</span>`;
    for (let i=s;i<=e;i++) h += `<button class="page-btn ${i===currentPage?'active':''}" onclick="goPage(${i})">${i}</button>`;
    if (e<tp) h += `<span class="page-dots">\u2026</span><button class="page-btn" onclick="goPage(${tp})">${tp}</button>`;
    h += `<button class="page-btn ${currentPage===tp?'disabled':''}" onclick="goPage(${currentPage+1})">&raquo;</button>`;
    document.getElementById('pagination').innerHTML = h;
}
function goPage(p) { const tp = Math.ceil(filteredUsers.length/PER_PAGE); if(p<1||p>tp)return; currentPage=p; renderTable(); renderPagination(); document.querySelector('.table-container').scrollTop=0; }

/* Sorting */
document.querySelectorAll('.sortable').forEach(th => { th.addEventListener('click', () => { const f=th.dataset.sort; if(sortField===f) sortDir=sortDir==='asc'?'desc':'asc'; else{sortField=f;sortDir='asc';} filterAndRender(); }); });

/* Filters */
document.getElementById('student-search').addEventListener('input', debounce(filterAndRender, 300));
document.getElementById('role-filter').addEventListener('change', filterAndRender);
document.getElementById('status-filter').addEventListener('change', filterAndRender);
function debounce(fn,ms){let t;return function(...a){clearTimeout(t);t=setTimeout(()=>fn.apply(this,a),ms);};}

/* =====================================================================
   Bulk Selection
   ===================================================================== */
document.getElementById('select-all-checkbox').addEventListener('change', function() {
    const start=(currentPage-1)*PER_PAGE; const page=filteredUsers.slice(start,start+PER_PAGE);
    page.forEach(u=>{if(this.checked)selectedIds.add(u.sourcedId);else selectedIds.delete(u.sourcedId);});
    document.querySelectorAll('.row-checkbox').forEach(cb=>{cb.checked=this.checked;});
    updateBulk();
});
function toggleRow(id,ck){if(ck)selectedIds.add(id);else selectedIds.delete(id);updateBulk();const s=(currentPage-1)*PER_PAGE;const p=filteredUsers.slice(s,s+PER_PAGE);document.getElementById('select-all-checkbox').checked=p.length>0&&p.every(u=>selectedIds.has(u.sourcedId));}
function updateBulk(){const c=selectedIds.size;document.getElementById('bulk-count').textContent=c;document.getElementById('bulk-actions-bar').classList.toggle('visible',c>0);}
function clearBulkSelection(){selectedIds.clear();document.querySelectorAll('.row-checkbox').forEach(cb=>{cb.checked=false;});document.getElementById('select-all-checkbox').checked=false;updateBulk();}

/* =====================================================================
   Student Detail Modal
   ===================================================================== */
async function viewStudent(id) {
    currentStudentId = id;
    document.getElementById('student-modal').classList.add('open');
    document.getElementById('modal-body').innerHTML = '<div style="display:flex;align-items:center;justify-content:center;padding:40px;"><div class="loading-spinner"></div></div>';
    try {
        const [uResp, eResp, tsResp] = await Promise.all([fetch(`/api/users/${id}`), fetch(`/api/enrollments/index?userId=${id}`), fetch(`/api/activity/time-saved?userId=${id}`)]);
        const u = (await uResp.json()).user;
        let enrollments = []; try { const ed = await eResp.json(); enrollments = ed.data || ed.enrollments || []; } catch {}
        let timeSaved = {}; try { timeSaved = await tsResp.json(); } catch {}

        document.getElementById('modal-student-name').textContent = `${u.givenName} ${u.familyName}`;
        document.getElementById('modal-body').innerHTML = buildModal(u, enrollments, timeSaved);
        switchTab('profile');
        setStudentReportingToggle(u.sourcedId);
        if (u.email) loadAnalytics(u.email);
        loadAssignDropdowns();
    } catch { document.getElementById('modal-body').innerHTML = '<p class="error-text">Failed to load student details.</p>'; }
}

function buildModal(u, enrollments, ts) {
    const fe = enrollments.filter(e => { const t=(e.course?.title||'').trim(); return !t.startsWith('Manual XP') && !t.includes('Hole-Filling'); });
    const totalXP = fe.reduce((s,e) => s + (e.xpEarned||0), 0);
    const whitelist = getAdminWhitelist();

    return `
    <div class="modal-tabs">
        <button class="modal-tab active" onclick="switchTab('profile')">Profile</button>
        <button class="modal-tab" onclick="switchTab('enrollments')">Enrollments (${fe.length})</button>
        <button class="modal-tab" onclick="switchTab('assign')">Assign</button>
    </div>
    <div class="modal-tab-content active" id="tab-profile">
        <div class="modal-detail-grid">
            <div class="detail-item"><span class="detail-label">Email</span><span class="detail-value">${esc(u.email||'\u2014')}</span></div>
            <div class="detail-item"><span class="detail-label">Username</span><span class="detail-value">${esc(u.username||'\u2014')}</span></div>
            <div class="detail-item"><span class="detail-label">Primary Role</span><span class="detail-value"><span class="role-badge role-${u.role}">${u.role||'\u2014'}</span></span></div>
            <div class="detail-item"><span class="detail-label">Status</span><span class="detail-value"><span class="status-badge status-${u.status}">${u.status||'\u2014'}</span></span></div>
            <div class="detail-item full-width"><span class="detail-label">Source ID</span><span class="detail-value monospace">${u.sourcedId}</span></div>
        </div>
        <div class="modal-section"><h3>All Roles</h3><div class="roles-list">
            ${(u.roles||[]).map(r=>{const rn=typeof r==='object'?r.role:r;const rt=typeof r==='object'?(r.roleType||''):'';return`<div class="role-item"><span class="role-badge role-${rn}">${rn}</span>${rt?`<span class="role-type">${rt}</span>`:''}  </div>`;}).join('')||'<span style="color:var(--color-text-muted);">No roles</span>'}
        </div></div>
        <div class="role-edit-section">
            <h4><i class="fa-solid fa-pen" style="margin-right:6px; color:var(--color-primary);"></i>Change Role</h4>
            <div class="assign-row">
                <select id="role-change-select">
                    <option value="student" ${u.role==='student'?'selected':''}>Student</option>
                    <option value="teacher" ${u.role==='teacher'?'selected':''}>Teacher</option>
                    <option value="administrator" ${u.role==='administrator'?'selected':''}>Administrator</option>
                    <option value="aide" ${u.role==='aide'?'selected':''}>Aide</option>
                    <option value="superadmin" ${u.role==='superadmin'?'selected':''}>Super Admin</option>
                </select>
                <button class="btn-sm btn-primary" onclick="changeRole('${u.sourcedId}')">Update Role</button>
            </div>
            <div class="alert" id="role-change-alert"></div>
        </div>
        <div class="stats-row" style="margin-top:16px;">
            <div class="stat-mini"><div class="stat-mini-value hl">${totalXP}</div><div class="stat-mini-label">Total XP</div></div>
            <div class="stat-mini"><div class="stat-mini-value">${ts.timeSaved||ts.totalMinutes||0}</div><div class="stat-mini-label">Time Saved</div></div>
            <div class="stat-mini"><div class="stat-mini-value">${fe.length}</div><div class="stat-mini-label">Courses</div></div>
        </div>
        <div id="analytics-details"><div class="empty-state" style="padding:12px;"><div class="loading-spinner" style="margin:0 auto 8px;"></div><p style="font-size:0.85rem;">Loading analytics...</p></div></div>
        <div class="whitelist-section">
            <h4><i class="fa-solid fa-shield-halved" style="margin-right:6px; color:#6C5CE7;"></i>Admin Whitelist</h4>
            <div id="whitelist-list">${whitelist.map(e=>`<div class="whitelist-item"><i class="fa-solid fa-check-circle"></i>${esc(e)}</div>`).join('')}</div>
            <div class="assign-row" style="margin-top:8px;">
                <input class="form-input" id="whitelist-email" placeholder="Add admin email..." style="flex:1;">
                <button class="btn-sm btn-primary" onclick="addWhitelistEmail()">Add</button>
            </div>
        </div>
        <div class="reporting-toggle-section">
            <h4><i class="fa-solid fa-flag"></i> Question Reporting</h4>
            <div class="toggle-row">
                <span class="toggle-label-text">Enable question reporting for this student</span>
                <label class="toggle-switch">
                    <input type="checkbox" id="student-reporting-toggle" onchange="toggleStudentReporting('${u.sourcedId}', this.checked)">
                    <span class="toggle-track"></span>
                </label>
            </div>
            <div class="alert" id="reporting-toggle-alert" style="margin-top:8px;"></div>
        </div>
    </div>
    <div class="modal-tab-content" id="tab-enrollments">
        ${fe.length?`<div style="margin-bottom:12px;font-size:0.85rem;color:var(--color-text-secondary);">Total XP: <strong style="color:var(--color-primary);">${totalXP}</strong></div><div class="enroll-list">${fe.map((e,ei)=>{const c=e.course||{};const t=c.title||'Unknown';const s=(c.subjects||[]).join(', ');const xp=e.xpEarned||0;const eid=e.sourcedId||e.id||'';return`<div class="enroll-item"><div class="enroll-icon"><i class="fa-solid fa-graduation-cap"></i></div><div class="enroll-info"><div class="enroll-name">${esc(t)}</div><div class="enroll-meta">${s?esc(s):''}</div></div><span class="enroll-xp">${xp} XP</span><button onclick="removeEnrollment('${esc(eid)}','${esc(t)}',this)" style="padding:3px 8px;border:1px solid var(--color-border);border-radius:4px;background:transparent;color:var(--color-text-muted);font-size:0.7rem;cursor:pointer;margin-left:8px;" onmouseover="this.style.borderColor='#E53E3E';this.style.color='#E53E3E';this.style.background='#FFF5F5'" onmouseout="this.style.borderColor='var(--color-border)';this.style.color='var(--color-text-muted)';this.style.background='transparent'" title="Remove course assignment"><i class="fa-solid fa-xmark"></i></button></div>`;}).join('')}</div>`:`<div class="empty-state"><i class="fa-solid fa-graduation-cap"></i><p>No enrollments found.</p></div>`}
    </div>
    <div class="modal-tab-content" id="tab-assign">
        <div style="margin-bottom:16px;">
            <h4 style="font-size:0.9rem;font-weight:600;margin-bottom:10px;"><i class="fa-solid fa-book" style="color:var(--color-primary);margin-right:6px;"></i>Assign Course</h4>
            <div class="assign-row">
                <div class="course-picker" id="modal-course-picker">
                    <div class="course-picker-trigger" onclick="toggleCoursePicker('modal')">
                        <span class="course-picker-text placeholder">Select a course...</span>
                        <i class="fa-solid fa-chevron-down"></i>
                    </div>
                    <div class="course-picker-dropdown" id="modal-course-dropdown">
                        <div class="course-picker-search-wrap">
                            <i class="fa-solid fa-magnifying-glass"></i>
                            <input type="text" placeholder="Search courses..." oninput="onCourseSearch('modal',this.value)">
                        </div>
                        <div class="course-picker-list" id="modal-course-list"></div>
                        <div class="course-picker-footer" id="modal-course-footer"></div>
                    </div>
                </div>
                <button class="btn-sm btn-primary" id="modal-course-btn" disabled onclick="assignCourseModal()">Assign</button>
            </div>
            <div class="alert" id="modal-course-alert"></div>
        </div>
        <div>
            <h4 style="font-size:0.9rem;font-weight:600;margin-bottom:10px;"><i class="fa-solid fa-clipboard-list" style="color:#6C5CE7;margin-right:6px;"></i>Assign Test</h4>
            <div class="assign-row"><select id="modal-test-select"><option value="">Loading...</option></select><button class="btn-sm btn-secondary" id="modal-test-btn" disabled onclick="assignTestModal()">Assign</button></div>
            <div class="alert" id="modal-test-alert"></div>
        </div>
    </div>`;
}

function switchTab(name) {
    const tabs = ['profile','enrollments','assign'];
    document.querySelectorAll('.modal-tab').forEach((t,i)=>{t.classList.toggle('active',tabs[i]===name);});
    document.querySelectorAll('.modal-tab-content').forEach(c=>c.classList.remove('active'));
    const el = document.getElementById(`tab-${name}`); if(el) el.classList.add('active');
}

async function changeRole(userId) {
    const sel = document.getElementById('role-change-select');
    const alert = document.getElementById('role-change-alert');
    if (!sel || !sel.value) return;
    const newRole = sel.value;

    alert.className = 'alert alert-info'; alert.textContent = 'Updating...';

    try {
        const resp = await fetch('/api/users/role', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({userId, newRole}) });
        if (resp.ok) {
            alert.className = 'alert alert-success'; alert.textContent = `Role updated to ${newRole}.`;
        } else { throw new Error(); }
    } catch {
        // Save locally
        saveRoleChange(userId, newRole);
        alert.className = 'alert alert-warning'; alert.textContent = `Role changed to ${newRole} (saved locally \u2014 API not available).`;
    }
    // Update in-memory
    const u = allUsers.find(u=>u.sourcedId===userId); if(u) u.role = newRole;
    renderRoleStats(); renderTable();
}

function addWhitelistEmail() {
    const input = document.getElementById('whitelist-email');
    if (!input || !input.value.trim()) return;
    const email = input.value.trim().toLowerCase();
    addToWhitelist(email);
    input.value = '';
    const list = document.getElementById('whitelist-list');
    if (list) list.innerHTML = getAdminWhitelist().map(e=>`<div class="whitelist-item"><i class="fa-solid fa-check-circle"></i>${esc(e)}</div>`).join('');
    showToast(`${email} added to admin whitelist.`, 'success');
}

async function loadAnalytics(email) {
    const c = document.getElementById('analytics-details'); if(!c) return;
    try {
        const resp = await fetch(`/api/analytics/index?email=${encodeURIComponent(email)}`);
        const data = await resp.json();
        const facts = data.facts || {};
        const subjectXP = {};
        for (const df of Object.values(facts)) { for (const [s, info] of Object.entries(df)) { subjectXP[s] = (subjectXP[s]||0) + ((info.activityMetrics||{}).xpEarned||0); } }
        if (!Object.keys(subjectXP).length) { c.innerHTML = '<div class="empty-state" style="padding:12px;"><i class="fa-solid fa-chart-bar"></i><p>No recent activity.</p></div>'; return; }
        c.innerHTML = `<div style="margin-top:8px;"><h4 style="font-size:0.85rem;font-weight:600;margin-bottom:8px;"><i class="fa-solid fa-chart-bar" style="color:var(--color-primary);margin-right:6px;"></i>Activity by Subject</h4><div class="fact-list">${Object.entries(subjectXP).sort((a,b)=>b[1]-a[1]).map(([s,x])=>`<div class="fact-item"><span class="fact-label">${esc(s)}</span><span class="fact-value">${Math.round(x)} XP</span></div>`).join('')}</div></div>`;
    } catch { c.innerHTML = '<div class="empty-state" style="padding:12px;"><i class="fa-solid fa-chart-bar"></i><p>Unable to load analytics.</p></div>'; }
}

async function loadAssignDropdowns() {
    initCoursePicker('modal');

    if (!lineItemsCache) { try { const r=await fetch('/api/lineitems/index');const d=await r.json();lineItemsCache=d.lineItems||[]; } catch { lineItemsCache=[]; } }
    const ts = document.getElementById('modal-test-select');
    if(ts){ts.innerHTML='<option value="">Select a test...</option>'+lineItemsCache.map(t=>`<option value="${t.sourcedId}">${esc(t.title||t.name||'Untitled')}</option>`).join('');ts.onchange=function(){const b=document.getElementById('modal-test-btn');if(b)b.disabled=!this.value;};}
}

async function removeEnrollment(enrollmentId, courseTitle, btn) {
    if (!confirm('Remove "' + courseTitle + '" from this student?')) return;
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    try {
        const resp = await fetch('/api/enrollments/index', {
            method: 'DELETE',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ sourcedId: enrollmentId }),
        });
        const data = await resp.json().catch(()=>({}));
        if (resp.ok && data.success) {
            btn.closest('.enroll-item').style.display = 'none';
            showToast('Course "' + courseTitle + '" removed.', 'success');
        } else {
            btn.closest('.enroll-item').style.display = 'none';
            showToast(data.error || 'Could not remove — may need manual action.', 'warning');
        }
    } catch(e) {
        btn.closest('.enroll-item').style.display = 'none';
        showToast('Network error removing enrollment.', 'warning');
    }
}

async function assignCourseModal() {
    const state=coursePickers.modal; const a=document.getElementById('modal-course-alert');
    if(!state.selectedId||!currentStudentId) return;
    const course=state.courses.find(c=>c.sourcedId===state.selectedId);
    const student=allUsers.find(u=>u.sourcedId===currentStudentId);
    const courseName=course?.title||'Unknown';
    const studentName=student?`${student.givenName} ${student.familyName}`:currentStudentId;
    a.className='alert alert-info'; a.textContent=`Enrolling ${studentName} in "${courseName}"...`;
    try {
        const resp=await fetch('/api/enrollments/index',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:currentStudentId,courseId:state.selectedId,role:'student'})});
        const data=await resp.json().catch(()=>({}));
        if(resp.ok&&data.success){
            a.className='alert alert-success'; a.textContent=`${studentName} enrolled in "${courseName}".`;
        } else {
            a.className='alert alert-error'; a.textContent=data.error||`Failed to enroll in "${courseName}".`;
        }
    } catch(e) { a.className='alert alert-error'; a.textContent='Network error. Try again.'; }
}

async function assignTestModal() {
    const s=document.getElementById('modal-test-select'); const a=document.getElementById('modal-test-alert');
    if(!s||!s.value||!currentStudentId) return;
    const test=lineItemsCache.find(t=>t.sourcedId===s.value);
    const student=allUsers.find(u=>u.sourcedId===currentStudentId);
    const testName=test?.title||test?.name||'Unknown';
    const studentName=student?`${student.givenName} ${student.familyName}`:currentStudentId;
    a.className='alert alert-info'; a.textContent='Submitting...';
    try {
        const resp=await fetch('/api/tests/assign',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({studentId:currentStudentId,lineItemId:s.value})});
        const data=await resp.json().catch(()=>({}));
        if(resp.ok&&data.success&&data.applied){
            a.className='alert alert-success';a.textContent=`Test "${testName}" assigned to ${studentName}.`;
        } else {
            a.className='alert alert-warning';a.textContent=data.error||data.message||`Assignment failed for "${testName}". Check API connection.`;
        }
    } catch(e) { a.className='alert alert-error'; a.textContent=`Network error: could not reach server.`; }
}

function closeModal(){closeAllCoursePickers();document.getElementById('student-modal').classList.remove('open');currentStudentId=null;}
document.getElementById('student-modal').addEventListener('click',function(e){if(e.target===this)closeModal();});

/* =====================================================================
   Create User
   ===================================================================== */
function openCreateUserModal(){document.getElementById('create-user-modal').classList.add('open');document.getElementById('create-user-alert').className='alert';document.getElementById('create-user-alert').textContent='';}
function closeCreateUser(){document.getElementById('create-user-modal').classList.remove('open');}
document.getElementById('create-user-modal').addEventListener('click',function(e){if(e.target===this)closeCreateUser();});

async function createUser() {
    const fn=document.getElementById('new-first-name').value.trim();
    const ln=document.getElementById('new-last-name').value.trim();
    const em=document.getElementById('new-email').value.trim();
    const rl=document.getElementById('new-role').value;
    const al=document.getElementById('create-user-alert');
    if(!fn||!ln||!em){al.className='alert alert-error';al.textContent='Please fill in all fields.';return;}

    al.className='alert alert-info'; al.textContent='Creating user...';

    const newUser = { sourcedId:'local-'+Date.now(), givenName:fn, familyName:ln, email:em, role:rl, status:'active', username:em.split('@')[0], roles:[{role:rl,roleType:'primary'}], _local:true };

    try {
        const resp = await fetch('/api/auth/signup', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({firstName:fn,lastName:ln,email:em,role:rl}) });
        if (resp.ok) {
            const data = await resp.json();
            if (data.user?.sourcedId) newUser.sourcedId = data.user.sourcedId;
            al.className='alert alert-success'; al.textContent=`User ${fn} ${ln} created successfully.`;
        } else throw new Error();
    } catch {
        addLocalUser(newUser);
        al.className='alert alert-warning'; al.textContent=`User ${fn} ${ln} saved locally (API unavailable).`;
    }

    allUsers.push(newUser);
    renderRoleStats(); filterAndRender();
    document.getElementById('new-first-name').value='';
    document.getElementById('new-last-name').value='';
    document.getElementById('new-email').value='';
    setTimeout(()=>closeCreateUser(), 1500);
}

/* =====================================================================
   Bulk Assign Course
   ===================================================================== */
function bulkAssignCourse() {
    assignTargetUsers = allUsers.filter(u=>selectedIds.has(u.sourcedId));
    if(!assignTargetUsers.length)return;
    document.getElementById('bulk-course-target').textContent=`Assigning to ${assignTargetUsers.length} student${assignTargetUsers.length>1?'s':''}`;
    document.getElementById('bulk-course-modal').classList.add('open');
    document.getElementById('bulk-course-alert').className='alert';document.getElementById('bulk-course-alert').textContent='';
    initCoursePicker('bulk');
}
async function confirmBulkCourse(){
    const state=coursePickers.bulk;if(!state.selectedId)return;
    const course=state.courses.find(c=>c.sourcedId===state.selectedId);
    const courseName=course?.title||'Unknown';
    let okCount=0,failCount=0;
    for(const u of assignTargetUsers){
        try{
            const r=await fetch('/api/enrollments/index',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({userId:u.sourcedId,courseId:state.selectedId,role:'student'})});
            const d=await r.json().catch(()=>({}));
            if(r.ok&&d.success) okCount++; else failCount++;
        }catch{failCount++;}
    }
    const names=assignTargetUsers.map(u=>`${u.givenName} ${u.familyName}`).join(', ');
    closeBulkCourse();
    if(okCount>0&&failCount===0) showToast(`${names} enrolled in "${courseName}".`,'success');
    else if(okCount>0) showToast(`"${courseName}": ${okCount} enrolled, ${failCount} failed.`,'warning');
    else showToast(`Failed to enroll in "${courseName}".`,'error');
}
function closeBulkCourse(){closeAllCoursePickers();document.getElementById('bulk-course-modal').classList.remove('open');}
document.getElementById('bulk-course-modal').addEventListener('click',function(e){if(e.target===this)closeBulkCourse();});

/* =====================================================================
   Bulk Assign Test
   ===================================================================== */
async function bulkAssignTest() {
    assignTargetUsers = allUsers.filter(u=>selectedIds.has(u.sourcedId));
    if(!assignTargetUsers.length)return;
    document.getElementById('bulk-test-target').textContent=`Assigning to ${assignTargetUsers.length} student${assignTargetUsers.length>1?'s':''}`;
    document.getElementById('bulk-test-modal').classList.add('open');
    document.getElementById('bulk-test-alert').className='alert';document.getElementById('bulk-test-alert').textContent='';
    if(!lineItemsCache){try{const r=await fetch('/api/lineitems/index');const d=await r.json();lineItemsCache=d.lineItems||[];}catch{lineItemsCache=[];}}
    const s=document.getElementById('bulk-test-select');
    s.innerHTML='<option value="">Select a test...</option>'+lineItemsCache.map(t=>`<option value="${t.sourcedId}">${esc(t.title||t.name||'Untitled')}</option>`).join('');
    s.onchange=function(){document.getElementById('bulk-test-confirm').disabled=!this.value;};
}
async function confirmBulkTest(){
    const s=document.getElementById('bulk-test-select');if(!s||!s.value)return;
    const test=lineItemsCache.find(t=>t.sourcedId===s.value);
    const testName=test?.title||test?.name||'Untitled';
    let okCount=0,failCount=0;
    for(const u of assignTargetUsers){
        try{
            const r=await fetch('/api/tests/assign',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({studentId:u.sourcedId,lineItemId:s.value})});
            const d=await r.json().catch(()=>({}));
            if(r.ok&&d.success&&d.applied) okCount++; else failCount++;
        }catch{failCount++;}
    }
    const names=assignTargetUsers.map(u=>`${u.givenName} ${u.familyName}`).join(', ');
    closeBulkTest();
    if(okCount>0&&failCount===0) showToast(`Test "${testName}" assigned to ${names}.`,'success');
    else if(okCount>0) showToast(`Test "${testName}": ${okCount} assigned, ${failCount} failed.`,'warning');
    else showToast(`Test "${testName}" assignment failed for all students.`,'warning');
}
function closeBulkTest(){document.getElementById('bulk-test-modal').classList.remove('open');}
document.getElementById('bulk-test-modal').addEventListener('click',function(e){if(e.target===this)closeBulkTest();});

/* =====================================================================
   Question Reporting Toggles
   ===================================================================== */
var _reportingConfig = null;

async function loadReportingConfig() {
    try {
        const resp = await fetch('/api/reports/config');
        const data = await resp.json();
        _reportingConfig = data.config || { globalEnabled: true, students: {} };
        updateGlobalReportingBtn();
    } catch(e) {
        _reportingConfig = { globalEnabled: true, students: {} };
        updateGlobalReportingBtn();
    }
}

function updateGlobalReportingBtn() {
    const btn = document.getElementById('global-reporting-btn');
    const label = document.getElementById('global-reporting-label');
    if (!_reportingConfig) return;
    const enabled = _reportingConfig.globalEnabled;
    label.textContent = enabled ? 'Reporting: ON' : 'Reporting: OFF';
    btn.classList.toggle('active', enabled);
}

async function toggleGlobalReporting() {
    if (!_reportingConfig) return;
    const newState = !_reportingConfig.globalEnabled;
    try {
        const resp = await fetch('/api/reports/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ global: true, enabled: newState }),
        });
        const data = await resp.json();
        if (data.ok) {
            _reportingConfig = data.config;
            updateGlobalReportingBtn();
            showToast(`Question reporting ${newState ? 'enabled' : 'disabled'} globally.`, 'success');
        }
    } catch(e) {
        showToast('Failed to update reporting config.', 'warning');
    }
}

async function toggleStudentReporting(studentId, enabled) {
    try {
        const resp = await fetch('/api/reports/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ studentId: studentId, enabled: enabled }),
        });
        const data = await resp.json();
        if (data.ok) {
            _reportingConfig = data.config;
            const alert = document.getElementById('reporting-toggle-alert');
            if (alert) {
                alert.className = 'alert success';
                alert.textContent = `Reporting ${enabled ? 'enabled' : 'disabled'} for this student.`;
                setTimeout(() => { alert.className = 'alert'; alert.textContent = ''; }, 3000);
            }
        }
    } catch(e) {
        showToast('Failed to update student reporting.', 'warning');
    }
}

function setStudentReportingToggle(studentId) {
    const toggle = document.getElementById('student-reporting-toggle');
    if (!toggle || !_reportingConfig) return;
    const override = (_reportingConfig.students || {})[studentId];
    if (override !== undefined && override !== null) {
        toggle.checked = override;
    } else {
        toggle.checked = _reportingConfig.globalEnabled;
    }
}

// Load config on init
loadReportingConfig();

/* =====================================================================
   Utilities
   ===================================================================== */
function esc(s){if(s==null)return'';if(typeof s!=='string')s=String(s);return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function showToast(msg,type='success'){const t=document.getElementById('toast');const ic=type==='success'?'fa-check-circle':type==='info'?'fa-info-circle':'fa-exclamation-triangle';t.className=`toast ${type}`;t.innerHTML=`<i class="fa-solid ${ic}"></i> ${esc(msg)}`;requestAnimationFrame(()=>{t.classList.add('visible');});setTimeout(()=>{t.classList.remove('visible');},4000);}
document.addEventListener('keydown',function(e){if(e.key==='Escape'){if(document.getElementById('bulk-test-modal').classList.contains('open'))closeBulkTest();else if(document.getElementById('bulk-course-modal').classList.contains('open'))closeBulkCourse();else if(document.getElementById('create-user-modal').classList.contains('open'))closeCreateUser();else if(document.getElementById('student-modal').classList.contains('open'))closeModal();}});
