    /* ====================================================================
       Settings Page — All Cards Functional
       ==================================================================== */
    let adminUsers = null; // lazy-loaded

    function esc(str) {
        if (str == null) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    function openSettingsModal(title, html) {
        document.getElementById('settings-modal-title').textContent = title;
        document.getElementById('settings-modal-body').innerHTML = html;
        document.getElementById('settings-modal').classList.add('open');
    }

    function closeSettingsModal() {
        document.getElementById('settings-modal').classList.remove('open');
    }
    document.getElementById('settings-modal').addEventListener('click', function (e) {
        if (e.target === this) closeSettingsModal();
    });

    function showSaveToast(id) {
        const el = document.getElementById(id);
        if (el) { el.classList.add('show'); setTimeout(() => el.classList.remove('show'), 2000); }
    }

    /* ---- Router --------------------------------------------------------- */
    async function openSettings(section) {
        switch (section) {
            case 'organization':    openOrganization(); break;
            case 'admin-users':     await openAdminUsers(); break;
            case 'permissions':     openPermissions(); break;
            case 'notifications':   openNotifications(); break;
            case 'integrations':    await openIntegrations(); break;
            case 'appearance':      openAppearance(); break;
        }
    }

    /* ==== Organization =================================================== */
    function openOrganization() {
        const schoolName = localStorage.getItem('al_school_name') || 'Alpha School';
        const timezone   = localStorage.getItem('al_timezone') || 'America/Chicago';

        openSettingsModal('Organization', `
            <div class="form-group">
                <label class="form-label">School Name</label>
                <input type="text" class="form-input" id="org-name" value="${esc(schoolName)}">
            </div>
            <div class="form-group">
                <label class="form-label">Timezone</label>
                <select class="form-select" id="org-timezone">
                    ${['America/New_York','America/Chicago','America/Denver','America/Los_Angeles','America/Anchorage','Pacific/Honolulu']
                        .map(tz => `<option value="${tz}" ${tz === timezone ? 'selected' : ''}>${tz.replace('_',' ')}</option>`).join('')}
                </select>
            </div>
            <div style="display:flex;align-items:center;margin-top:20px;">
                <button class="btn-save" onclick="saveOrganization()">Save Changes</button>
                <span class="save-toast" id="org-toast"><i class="fa-solid fa-circle-check"></i> Saved</span>
            </div>
        `);
    }

    window.saveOrganization = function () {
        localStorage.setItem('al_school_name', document.getElementById('org-name').value);
        localStorage.setItem('al_timezone', document.getElementById('org-timezone').value);
        showSaveToast('org-toast');
    };

    /* ==== Admin Users ==================================================== */
    let allUsersForPromotion = null;

    async function openAdminUsers() {
        openSettingsModal('Admin Users', '<div style="text-align:center;padding:24px;"><div class="loading-spinner" style="margin:0 auto 12px;"></div>Loading admins...</div>');

        if (!adminUsers || !allUsersForPromotion) {
            try {
                const resp = await fetch('/api/users');
                const data = await resp.json();
                const users = data.users || [];
                adminUsers = users.filter(u => u.role === 'administrator');
                allUsersForPromotion = users;
            } catch (e) {
                document.getElementById('settings-modal-body').innerHTML = '<p class="error-text">Failed to load users.</p>';
                return;
            }
        }

        renderAdminUsersModal();
    }

    function renderAdminUsersModal() {
        const list = adminUsers.length
            ? adminUsers.map(u => `
                <div class="admin-user-row">
                    <div class="user-cell-avatar">${esc((u.givenName||'?')[0].toUpperCase())}</div>
                    <div style="flex:1;">
                        <div class="user-cell-name">${esc(u.givenName)} ${esc(u.familyName)}</div>
                        <div class="user-cell-username">${esc(u.email || u.username || '')}</div>
                    </div>
                    <span class="role-badge role-admin">administrator</span>
                </div>`).join('')
            : '<div style="text-align:center;padding:20px;color:var(--color-text-muted);">No administrator accounts found.</div>';

        document.getElementById('settings-modal-body').innerHTML = `
            <p style="font-size:0.88rem;color:var(--color-text-secondary);margin-bottom:16px;">
                ${adminUsers.length} administrator${adminUsers.length !== 1 ? 's' : ''} found in Timeback.
            </p>
            ${list}
            <div style="margin-top:16px;border-top:1px solid var(--color-border);padding-top:16px;">
                <button class="btn-save" onclick="showPromoteUserUI()">
                    <i class="fa-solid fa-user-plus"></i> Promote User to Admin
                </button>
                <span class="save-toast" id="promote-toast"><i class="fa-solid fa-circle-check"></i> Promoted!</span>
            </div>
            <div id="promote-section" style="display:none;margin-top:16px;"></div>
        `;
    }

    window.showPromoteUserUI = function () {
        const nonAdmins = (allUsersForPromotion || []).filter(u => u.role !== 'administrator');
        const section = document.getElementById('promote-section');
        section.style.display = '';
        section.innerHTML = `
            <div class="form-group">
                <label class="form-label">Search for a user to promote</label>
                <input type="text" class="form-input" id="promote-search" placeholder="Search by name or email..." oninput="filterPromoteList()">
            </div>
            <div id="promote-list" style="max-height:200px;overflow-y:auto;"></div>
        `;
        window._promoteUsers = nonAdmins;
        filterPromoteList();
    };

    window.filterPromoteList = function () {
        const query = (document.getElementById('promote-search')?.value || '').toLowerCase();
        const list = document.getElementById('promote-list');
        const filtered = (window._promoteUsers || []).filter(u => {
            const name = `${u.givenName || ''} ${u.familyName || ''}`.toLowerCase();
            return !query || name.includes(query) || (u.email || '').toLowerCase().includes(query);
        });
        if (!filtered.length) { list.innerHTML = '<div style="text-align:center;padding:16px;color:var(--color-text-muted);font-size:0.88rem;">No users found.</div>'; return; }
        list.innerHTML = filtered.slice(0, 20).map(u => {
            const name = `${u.givenName || ''} ${u.familyName || ''}`.trim();
            return `
                <div class="admin-user-row" style="cursor:pointer;" onclick="promoteUser('${esc(u.sourcedId)}','${esc(u.email)}')">
                    <div class="user-cell-avatar">${esc((u.givenName||'?')[0].toUpperCase())}</div>
                    <div style="flex:1;">
                        <div class="user-cell-name">${esc(name)}</div>
                        <div class="user-cell-username">${esc(u.email || u.username || '')} &middot; <span class="role-badge role-${esc(u.role)}">${esc(u.role)}</span></div>
                    </div>
                    <button class="btn-save" style="padding:6px 14px;font-size:0.78rem;" onclick="event.stopPropagation();promoteUser('${esc(u.sourcedId)}','${esc(u.email)}')">Promote</button>
                </div>`;
        }).join('');
    };

    window.promoteUser = async function (userId, email) {
        if (!confirm(`Promote this user to administrator?`)) return;
        const section = document.getElementById('promote-section');
        section.innerHTML = '<div style="text-align:center;padding:16px;"><div class="loading-spinner" style="margin:0 auto 12px;"></div>Promoting...</div>';
        try {
            const resp = await fetch('/api/update-role', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ userId, newRole: 'administrator', email }),
            });
            const data = await resp.json();
            if (data.success) {
                // Refresh admin list
                adminUsers = null;
                allUsersForPromotion = null;
                showSaveToast('promote-toast');
                await openAdminUsers();
            } else {
                section.innerHTML = `<p class="error-text">${esc(data.message)}</p>`;
            }
        } catch (e) {
            section.innerHTML = '<p class="error-text">Failed to promote user.</p>';
        }
    };

    /* ==== Permissions ==================================================== */
    function openPermissions() {
        const roles = [
            { name: 'Superadmin', icon: 'fa-crown', color: 'stat-icon-purple', desc: 'Full access to all features. Can manage other admins, configure integrations, and access all data.' },
            { name: 'Administrator', icon: 'fa-user-shield', color: 'stat-icon-teal', desc: 'Manage students, courses, and view analytics. Cannot configure integrations or manage other admins.' },
            { name: 'Teacher', icon: 'fa-chalkboard-user', color: 'stat-icon-blue', desc: 'View assigned classes and students. Can assign tests and view results for their classes.' },
            { name: 'Student', icon: 'fa-graduation-cap', color: 'stat-icon-orange', desc: 'Access assigned courses, take tests, and view personal progress.' },
        ];

        openSettingsModal('Permissions & Roles', `
            <p style="font-size:0.88rem;color:var(--color-text-secondary);margin-bottom:16px;">
                Role hierarchy determines what each user type can access. Roles are assigned through the Timeback/OneRoster system.
            </p>
            <div class="role-hierarchy">
                ${roles.map((r, i) => `
                    <div class="role-tier">
                        <div class="role-tier-icon ${r.color}"><i class="fa-solid ${r.icon}"></i></div>
                        <div>
                            <div class="role-tier-name">${r.name}</div>
                            <div class="role-tier-desc">${r.desc}</div>
                        </div>
                    </div>`).join('')}
            </div>
            <p style="font-size:0.78rem;color:var(--color-text-muted);margin-top:16px;text-align:center;">
                <i class="fa-solid fa-info-circle"></i> Role editing will be available in a future update.
            </p>
        `);
    }

    /* ==== Notifications ================================================== */
    function openNotifications() {
        const prefs = JSON.parse(localStorage.getItem('al_notifications') || '{}');
        const emailOn = prefs.email !== false;
        const inappOn = prefs.inapp !== false;
        const weeklyOn = prefs.weekly || false;

        openSettingsModal('Notifications', `
            <div>
                <div class="toggle-row">
                    <div>
                        <div class="toggle-label">Email Notifications</div>
                        <div class="toggle-desc">Receive email alerts for important events</div>
                    </div>
                    <label class="toggle-switch">
                        <input type="checkbox" id="notif-email" ${emailOn ? 'checked' : ''}>
                        <span class="toggle-track"></span>
                    </label>
                </div>
                <div class="toggle-row">
                    <div>
                        <div class="toggle-label">In-App Notifications</div>
                        <div class="toggle-desc">Show notification badges and alerts in the UI</div>
                    </div>
                    <label class="toggle-switch">
                        <input type="checkbox" id="notif-inapp" ${inappOn ? 'checked' : ''}>
                        <span class="toggle-track"></span>
                    </label>
                </div>
                <div class="toggle-row">
                    <div>
                        <div class="toggle-label">Weekly Reports</div>
                        <div class="toggle-desc">Receive a weekly summary of student progress</div>
                    </div>
                    <label class="toggle-switch">
                        <input type="checkbox" id="notif-weekly" ${weeklyOn ? 'checked' : ''}>
                        <span class="toggle-track"></span>
                    </label>
                </div>
            </div>
            <div style="display:flex;align-items:center;margin-top:20px;">
                <button class="btn-save" onclick="saveNotifications()">Save Preferences</button>
                <span class="save-toast" id="notif-toast"><i class="fa-solid fa-circle-check"></i> Saved</span>
            </div>
        `);
    }

    window.saveNotifications = function () {
        localStorage.setItem('al_notifications', JSON.stringify({
            email: document.getElementById('notif-email').checked,
            inapp: document.getElementById('notif-inapp').checked,
            weekly: document.getElementById('notif-weekly').checked,
        }));
        showSaveToast('notif-toast');
    };

    /* ==== Integrations =================================================== */
    async function openIntegrations() {
        const endpoints = [
            { name: 'Users',       url: '/api/users',      key: 'users' },
            { name: 'Courses',     url: '/api/courses',    key: 'courses' },
            { name: 'Classes',     url: '/api/classes',    key: 'classes' },
            { name: 'Enrollments', url: '/api/enrollments', key: 'enrollments' },
            { name: 'Line Items',  url: '/api/line-items', key: 'lineItems' },
        ];

        openSettingsModal('Integrations & API Status', `
            <div class="form-group">
                <label class="form-label">API Base URL</label>
                <div class="form-input" style="background:var(--color-bg);cursor:default;">${window.location.origin}/api</div>
            </div>
            <div class="form-group">
                <label class="form-label">Cognito Domain</label>
                <div class="form-input" style="background:var(--color-bg);cursor:default;">alphaschool.auth.us-east-1.amazoncognito.com</div>
            </div>
            <div style="margin-top:20px;">
                <label class="form-label">Endpoint Status</label>
                <div id="endpoint-list">
                    ${endpoints.map(ep => `
                        <div class="endpoint-row">
                            <div>
                                <div class="endpoint-name">${ep.name}</div>
                                <div class="endpoint-url">${ep.url}</div>
                            </div>
                            <span class="api-status checking" id="ep-${ep.key}"><i class="fa-solid fa-spinner fa-spin"></i></span>
                        </div>`).join('')}
                </div>
            </div>
        `);

        // Test each endpoint
        for (const ep of endpoints) {
            try {
                const resp = await fetch(ep.url);
                const el = document.getElementById(`ep-${ep.key}`);
                if (el) {
                    if (resp.ok) {
                        el.className = 'api-status connected';
                        el.innerHTML = '<i class="fa-solid fa-circle-check"></i> OK';
                    } else {
                        el.className = 'api-status error';
                        el.innerHTML = `<i class="fa-solid fa-xmark"></i> ${resp.status}`;
                    }
                }
            } catch (e) {
                const el = document.getElementById(`ep-${ep.key}`);
                if (el) {
                    el.className = 'api-status error';
                    el.innerHTML = '<i class="fa-solid fa-xmark"></i> Failed';
                }
            }
        }
    }

    /* ==== Appearance ===================================================== */
    function openAppearance() {
        const theme = localStorage.getItem('al_theme') || 'light';
        const accent = localStorage.getItem('al_accent') || '#45B5AA';
        const accents = ['#45B5AA', '#4A90D9', '#6C5CE7', '#E65100', '#AD1457', '#2E7D32'];

        openSettingsModal('Appearance', `
            <div class="form-group">
                <label class="form-label">Theme</label>
                <div class="theme-options">
                    <div class="theme-option ${theme === 'light' ? 'selected' : ''}" onclick="selectTheme('light')">
                        <div class="theme-preview" style="background:linear-gradient(135deg,#F4F6F9,#FFFFFF);border:1px solid var(--color-border);"></div>
                        <div class="theme-option-label">Light</div>
                    </div>
                    <div class="theme-option ${theme === 'dark' ? 'selected' : ''}" onclick="selectTheme('dark')">
                        <div class="theme-preview" style="background:linear-gradient(135deg,#1A202C,#2D3748);border:1px solid #4A5568;"></div>
                        <div class="theme-option-label">Dark (Preview)</div>
                    </div>
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Accent Color</label>
                <div class="color-swatches">
                    ${accents.map(c => `<div class="color-swatch ${c === accent ? 'selected' : ''}" style="background:${c};" onclick="selectAccent('${c}')"></div>`).join('')}
                </div>
            </div>
            <div style="display:flex;align-items:center;margin-top:20px;">
                <button class="btn-save" onclick="saveAppearance()">Save Preferences</button>
                <span class="save-toast" id="appearance-toast"><i class="fa-solid fa-circle-check"></i> Saved</span>
            </div>
        `);
    }

    let selectedTheme  = localStorage.getItem('al_theme') || 'light';
    let selectedAccent = localStorage.getItem('al_accent') || '#45B5AA';

    window.selectTheme = function (t) {
        selectedTheme = t;
        document.querySelectorAll('.theme-option').forEach(el => el.classList.remove('selected'));
        event.currentTarget.classList.add('selected');
    };

    window.selectAccent = function (c) {
        selectedAccent = c;
        document.querySelectorAll('.color-swatch').forEach(el => el.classList.remove('selected'));
        event.currentTarget.classList.add('selected');
    };

    window.saveAppearance = function () {
        localStorage.setItem('al_theme', selectedTheme);
        localStorage.setItem('al_accent', selectedAccent);
        showSaveToast('appearance-toast');
    };

    /* ==== Initial API status check (for the card badge) ================== */
    document.addEventListener('DOMContentLoaded', async function () {
        const indicator = document.getElementById('api-status-indicator');
        try {
            const resp = await fetch('/api/users');
            if (resp.ok) {
                const data = await resp.json();
                const count = data.count || (data.users || []).length;
                indicator.innerHTML = `<span class="api-status connected"><i class="fa-solid fa-circle-check"></i> API Connected (${count} users)</span>`;
            } else {
                indicator.innerHTML = `<span class="api-status error"><i class="fa-solid fa-triangle-exclamation"></i> API Error (${resp.status})</span>`;
            }
        } catch (e) {
            indicator.innerHTML = `<span class="api-status error"><i class="fa-solid fa-triangle-exclamation"></i> API Unreachable</span>`;
        }
    });
    