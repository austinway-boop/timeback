/* ===========================================================================
   AlphaLearn – Shared Layout (topbar + sidebar)
   Reads data-view and data-active from <body> to configure itself.
   =========================================================================== */

(function () {
    const view   = document.body.dataset.view   || 'student';
    const active = document.body.dataset.active  || 'home';

    /* ---- Logout helper (works on both admin and student pages) ----------- */
    window.handleLogout = function () {
        if (typeof logout === 'function') {
            logout();
        } else {
            localStorage.removeItem('alphalearn_name');
            localStorage.removeItem('alphalearn_email');
            localStorage.removeItem('alphalearn_role');
            localStorage.removeItem('alphalearn_sourcedId');
            window.location.href = '/login';
        }
    };

    /* ---- Topbar ---------------------------------------------------------- */
    const switchBtn = view === 'student'
        ? '<a href="/admin" class="view-switch-btn" title="Switch to Admin View"><i class="fa-solid fa-shield-halved"></i></a>'
        : '<a href="/dashboard" class="view-switch-btn" title="Switch to Student View"><i class="fa-solid fa-graduation-cap"></i></a>';

    const topbar = document.createElement('header');
    topbar.className = 'topbar';
    topbar.innerHTML = `
        <div class="topbar-left">
            <div class="logo">
                <svg class="logo-bird" width="32" height="32" viewBox="0 0 40 40" fill="none">
                    <path d="M8 28C8 28 12 20 20 16C28 12 36 8 36 8C36 8 34 16 28 22C22 28 16 30 16 30L8 28Z" fill="#45B5AA"/>
                    <path d="M4 32C4 32 8 28 16 30C16 30 12 34 4 32Z" fill="#45B5AA" opacity="0.7"/>
                    <path d="M20 16C20 16 18 24 16 30" stroke="#45B5AA" stroke-width="1.5" fill="none" opacity="0.5"/>
                </svg>
                <span class="logo-text"><span class="logo-alpha">Alpha</span><span class="logo-learn">Learn</span></span>
            </div>
        </div>
        <div class="topbar-right">
            <div class="notif-bell-wrap" id="notif-bell-wrap" style="position:relative;">
                <button class="topbar-icon-btn" id="notif-bell-btn" onclick="window._toggleNotifPanel()" title="Report notifications">
                    <i class="fa-solid fa-bell"></i>
                    <span class="notif-badge" id="notif-badge" style="display:none;"></span>
                </button>
                <div class="notif-panel" id="notif-panel"></div>
            </div>
            ${switchBtn}
            <button class="topbar-icon-btn" onclick="handleLogout()" title="Sign out"><i class="fa-solid fa-right-from-bracket"></i></button>
        </div>`;
    document.body.prepend(topbar);

    /* ---- Notification bell (student report statuses) --------------------- */
    (function initNotifBell() {
        const style = document.createElement('style');
        style.textContent = `
            .notif-badge { position:absolute; top:2px; right:2px; min-width:16px; height:16px; line-height:16px; text-align:center; border-radius:8px; background:#E53E3E; color:#fff; font-size:0.62rem; font-weight:700; padding:0 4px; pointer-events:none; }
            .notif-panel { display:none; position:absolute; top:calc(100% + 8px); right:0; width:340px; max-height:420px; overflow-y:auto; background:#fff; border:1px solid var(--color-border); border-radius:12px; box-shadow:0 12px 40px rgba(0,0,0,0.15); z-index:9999; }
            .notif-panel.open { display:block; }
            .notif-panel-header { padding:14px 16px; border-bottom:1px solid var(--color-border); font-weight:700; font-size:0.88rem; color:var(--color-text); display:flex; align-items:center; justify-content:space-between; }
            .notif-panel-header .notif-clear { font-size:0.75rem; font-weight:500; color:var(--color-text-muted); cursor:pointer; border:none; background:none; padding:2px 6px; }
            .notif-panel-header .notif-clear:hover { color:#E53E3E; }
            .notif-item { padding:12px 16px; border-bottom:1px solid var(--color-border); transition:background 0.1s; }
            .notif-item:last-child { border-bottom:none; }
            .notif-item.unread { background:#F0F7FF; }
            .notif-item-q { font-size:0.82rem; font-weight:500; color:var(--color-text); line-height:1.4; margin-bottom:6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
            .notif-item-status { display:inline-flex; align-items:center; gap:5px; font-size:0.75rem; font-weight:600; padding:3px 8px; border-radius:6px; }
            .notif-status-processing { background:#FFF3E0; color:#E65100; }
            .notif-status-awarded { background:#E8F5E9; color:#1B5E20; }
            .notif-status-no-issue { background:#F3F4F6; color:#6B7280; }
            .notif-status-team { background:#EDE7F6; color:#4527A0; }
            .notif-status-replaced { background:#E3F2FD; color:#1565C0; }
            .notif-item-time { font-size:0.7rem; color:var(--color-text-muted); margin-top:4px; }
            .notif-empty { padding:30px 16px; text-align:center; color:var(--color-text-muted); font-size:0.85rem; }
            .notif-empty i { display:block; font-size:1.5rem; margin-bottom:8px; opacity:0.3; }
        `;
        document.head.appendChild(style);

        function getNotifs() {
            try { return JSON.parse(localStorage.getItem('al_report_notifs') || '[]'); } catch(e) { return []; }
        }
        function saveNotifs(n) { localStorage.setItem('al_report_notifs', JSON.stringify(n)); }

        function renderBadge() {
            const notifs = getNotifs();
            const unread = notifs.filter(n => !n.read).length;
            const badge = document.getElementById('notif-badge');
            if (badge) {
                if (unread > 0) { badge.textContent = unread; badge.style.display = ''; }
                else { badge.style.display = 'none'; }
            }
        }

        function statusHtml(n) {
            if (n.status === 'processing') return '<span class="notif-item-status notif-status-processing"><i class="fa-solid fa-spinner fa-spin"></i> AI Reviewing...</span>';
            if (n.status === 'completed' && n.verdict === 'valid' && n.pointsAwarded > 0) return '<span class="notif-item-status notif-status-awarded"><i class="fa-solid fa-star"></i> +' + n.pointsAwarded + ' Points Awarded</span>';
            if (n.status === 'completed' && n.verdict === 'valid' && n.pointsAwarded === 0) return '<span class="notif-item-status notif-status-team"><i class="fa-solid fa-users"></i> Sent to Internal Team</span>';
            if (n.status === 'completed' && n.verdict === 'invalid') return '<span class="notif-item-status notif-status-no-issue"><i class="fa-solid fa-check"></i> Reviewed — No Issues Found</span>';
            if (n.status === 'internal_review') return '<span class="notif-item-status notif-status-team"><i class="fa-solid fa-users"></i> Under Internal Review</span>';
            if (n.status === 'replaced') return '<span class="notif-item-status notif-status-replaced"><i class="fa-solid fa-rotate"></i> Question Replaced</span>';
            return '<span class="notif-item-status notif-status-processing"><i class="fa-solid fa-clock"></i> Pending</span>';
        }

        function timeAgo(ts) {
            if (!ts) return '';
            const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
            if (diff < 60) return 'just now';
            if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
            if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
            return Math.floor(diff / 86400) + 'd ago';
        }

        function renderPanel() {
            const notifs = getNotifs();
            const panel = document.getElementById('notif-panel');
            if (!panel) return;
            if (notifs.length === 0) {
                panel.innerHTML = '<div class="notif-panel-header">Reports<span></span></div><div class="notif-empty"><i class="fa-solid fa-bell"></i>No question reports yet</div>';
                return;
            }
            let html = '<div class="notif-panel-header">Reports <button class="notif-clear" onclick="window._clearNotifs()">Clear all</button></div>';
            notifs.slice().reverse().forEach(function(n) {
                const q = (n.questionText || '').substring(0, 60) + ((n.questionText || '').length > 60 ? '...' : '');
                html += '<div class="notif-item' + (n.read ? '' : ' unread') + '">';
                html += '<div class="notif-item-q">' + (q || 'Reported question') + '</div>';
                html += statusHtml(n);
                html += '<div class="notif-item-time">' + timeAgo(n.timestamp) + '</div>';
                html += '</div>';
            });
            panel.innerHTML = html;
        }

        window._toggleNotifPanel = function() {
            const panel = document.getElementById('notif-panel');
            const isOpen = panel.classList.toggle('open');
            if (isOpen) {
                renderPanel();
                // Mark all as read
                const notifs = getNotifs();
                notifs.forEach(function(n) { n.read = true; });
                saveNotifs(notifs);
                renderBadge();
            }
        };

        window._clearNotifs = function() {
            saveNotifs([]);
            renderPanel();
            renderBadge();
        };

        // Close panel on outside click
        document.addEventListener('click', function(e) {
            const wrap = document.getElementById('notif-bell-wrap');
            const panel = document.getElementById('notif-panel');
            if (wrap && panel && !wrap.contains(e.target)) {
                panel.classList.remove('open');
            }
        });

        // Global helpers for quiz/lesson pages to call
        window._addReportNotif = function(data) {
            const notifs = getNotifs();
            notifs.push({
                reportId: data.reportId,
                questionText: data.questionText || '',
                status: 'processing',
                verdict: null,
                pointsAwarded: 0,
                answeredCorrectly: data.answeredCorrectly || false,
                timestamp: new Date().toISOString(),
                read: false,
            });
            saveNotifs(notifs);
            renderBadge();
        };

        window._updateReportNotif = function(reportId, updates) {
            const notifs = getNotifs();
            for (let i = 0; i < notifs.length; i++) {
                if (notifs[i].reportId === reportId) {
                    Object.assign(notifs[i], updates, { read: false });
                    break;
                }
            }
            saveNotifs(notifs);
            renderBadge();
        };

        renderBadge();
    })();

    /* ---- Sidebar --------------------------------------------------------- */
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;

    const studentNav = [
        { id: 'home',     icon: 'fa-house',    label: 'Home',   href: '/dashboard' },
        { id: 'goals',    icon: 'fa-bullseye',  label: 'Goals',  href: '/goals' },
    ];

    const adminNav = [
        { id: 'notifications', icon: 'fa-bell',            label: 'Notifications', href: '/admin/notifications' },
        { id: 'students',      icon: 'fa-users',           label: 'Students',      href: '/admin/students' },
        { id: 'courses',       icon: 'fa-book',            label: 'Courses',       href: '/admin/courses' },
        { id: 'assign-tests',  icon: 'fa-clipboard-check', label: 'Assign Tests',  href: '/admin/assign-tests' },
        { id: 'thinking-tree', icon: 'fa-brain',           label: 'Thinking Tree', href: '/admin/thinking-tree' },
        { id: 'settings',      icon: 'fa-gear',            label: 'Settings',      href: '/admin/settings' },
    ];

    const items = view === 'student' ? studentNav : adminNav;

    function renderNavItem(item) {
        // Collapsible parent with children
        if (item.children) {
            const isParentActive = active === item.id || item.children.some(c => c.id === active);
            const isOpen = isParentActive; // auto-open if a child is active
            return `
                <li class="nav-item nav-item-parent ${isParentActive ? 'active' : ''} ${isOpen ? 'open' : ''}">
                    <a href="#" class="nav-parent-toggle">
                        <i class="fa-solid ${item.icon}"></i>
                        <span>${item.label}</span>
                        <i class="fa-solid fa-chevron-right nav-chevron"></i>
                    </a>
                    <ul class="nav-children">
                        ${item.children.map(child => `
                            <li class="nav-child ${child.id === active ? 'active' : ''}">
                                <a href="${child.href}">
                                    <i class="fa-solid ${child.icon}"></i>
                                    <span>${child.label}</span>
                                </a>
                            </li>`).join('')}
                    </ul>
                </li>`;
        }
        // Regular flat item
        return `
            <li class="nav-item ${item.id === active ? 'active' : ''}">
                <a href="${item.href}">
                    <i class="fa-solid ${item.icon}"></i>
                    <span>${item.label}</span>
                </a>
            </li>`;
    }

    sidebar.innerHTML = '<ul class="nav-list">' + items.map(renderNavItem).join('') + '</ul>';

    // Attach click handlers for collapsible parents
    sidebar.querySelectorAll('.nav-parent-toggle').forEach(toggle => {
        toggle.addEventListener('click', function (e) {
            e.preventDefault();
            const parentLi = this.closest('.nav-item-parent');
            parentLi.classList.toggle('open');
        });
    });
})();
