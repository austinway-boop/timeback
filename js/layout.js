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

    const userName = localStorage.getItem('alphalearn_name') || 'A';
    const initial  = userName.charAt(0).toUpperCase();

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
            ${switchBtn}
            <button class="topbar-icon-btn" title="Notifications"><i class="fa-solid fa-bell"></i></button>
            <button class="topbar-icon-btn" onclick="handleLogout()" title="Logout"><i class="fa-solid fa-right-from-bracket"></i></button>
            <div class="avatar"><span>${initial}</span></div>
        </div>`;
    document.body.prepend(topbar);

    /* ---- Sidebar --------------------------------------------------------- */
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;

    const studentNav = [
        { id: 'home',     icon: 'fa-house',   label: 'Home',             href: '/dashboard' },
        { id: 'mastery',  icon: 'fa-trophy',  label: 'Mastery Progress', href: '#' },
        { id: 'badges',   icon: 'fa-award',   label: 'Badges',           href: '#' },
    ];

    const adminNav = [
        { id: 'dashboard', icon: 'fa-grid-2',  label: 'Dashboard', href: '/admin' },
        { id: 'students',  icon: 'fa-users',   label: 'Students',  href: '/admin/students' },
        { id: 'courses',   icon: 'fa-book',    label: 'Courses',   href: '/admin/courses' },
        { id: 'settings',  icon: 'fa-gear',    label: 'Settings',  href: '/admin/settings' },
    ];

    const items = view === 'student' ? studentNav : adminNav;

    sidebar.innerHTML = '<ul class="nav-list">' + items.map(item => `
        <li class="nav-item ${item.id === active ? 'active' : ''}">
            <a href="${item.href}">
                <i class="fa-solid ${item.icon}"></i>
                <span>${item.label}</span>
            </a>
        </li>`).join('') + '</ul>';
})();
