/* ===========================================================================
   AlphaLearn – Shared Layout (topbar + sidebar)
   Reads data-view and data-active from <body> to configure itself.
   =========================================================================== */

(function () {
    /* ---- Apply saved staging theme immediately --------------------------- */
    const _stagingTheme = localStorage.getItem('al_staging_theme');
    if (_stagingTheme && localStorage.getItem('alphalearn_staging')) {
        document.documentElement.setAttribute('data-theme', _stagingTheme);
    }

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

    /* ---- Staging Banner (shown on every page when staging flag is set) ---- */
    if (localStorage.getItem('alphalearn_staging')) {
        document.body.classList.add('has-staging-banner');
        const banner = document.createElement('div');
        banner.className = 'staging-banner';
        banner.innerHTML = '<i class="fa-solid fa-flask"></i> STAGING MODE &mdash; Test account: pehal64861@aixind.com &nbsp;|&nbsp; <a href="/staging">Back to Hub</a>';
        topbar.insertAdjacentElement('afterend', banner);
    }

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
        { id: 'thinking-tree',  icon: 'fa-brain',           label: 'Thinking Tree', href: '/admin/thinking-tree' },
        { id: 'course-editor', icon: 'fa-pen-ruler',       label: 'Course Editor', href: '/admin/course-editor' },
        { id: 'settings',      icon: 'fa-gear',            label: 'Settings',      href: '/admin/settings' },
    ];

    const stagingNav = [
        { id: 'staging', icon: 'fa-flask', label: 'Staging Hub', href: '/staging' },
    ];

    const items = view === 'staging' ? stagingNav : (view === 'student' ? studentNav : adminNav);

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

    /* ---- Theme Settings (staging only) ---------------------------------- */
    /* Adds a "Settings" nav item + a full-screen modal with theme cards.    */
    /* Exposed as a global so staging.js can call after async auto-login.    */

    const THEMES = [
        { id: 'default',  label: 'Default',   desc: 'Clean teal — the classic look',          primary: '#45B5AA', bg: '#F4F6F9',  surface: '#FFFFFF', text: '#2D3748' },
        { id: 'ocean',    label: 'Ocean',      desc: 'Deep blue, calm and focused',            primary: '#2B6CB0', bg: '#EFF6FF',  surface: '#FFFFFF', text: '#1E3A5F' },
        { id: 'lavender', label: 'Lavender',   desc: 'Soft purple, creative vibes',            primary: '#7C3AED', bg: '#F5F3FF',  surface: '#FFFFFF', text: '#3B1F6E' },
        { id: 'sunset',   label: 'Sunset',     desc: 'Warm orange, energetic and bold',        primary: '#EA580C', bg: '#FFFBF5',  surface: '#FFFFFF', text: '#5C2D0E' },
        { id: 'rose',     label: 'Rose',       desc: 'Elegant pink, refined and modern',       primary: '#E11D48', bg: '#FFF5F6',  surface: '#FFFFFF', text: '#4C0519' },
        { id: 'forest',   label: 'Forest',     desc: 'Natural green, earthy and grounded',     primary: '#16A34A', bg: '#F0FDF4',  surface: '#FFFFFF', text: '#14432A' },
        { id: 'slate',    label: 'Slate',      desc: 'Neutral gray, minimal and clean',        primary: '#64748B', bg: '#F8FAFC',  surface: '#FFFFFF', text: '#1E293B' },
        { id: 'midnight', label: 'Midnight',   desc: 'Dark mode — easy on the eyes',           primary: '#6366F1', bg: '#0F172A',  surface: '#1E293B', text: '#F1F5F9' },
        { id: 'berry',    label: 'Berry',      desc: 'Bold magenta, playful and vibrant',      primary: '#C026D3', bg: '#FDF4FF',  surface: '#FFFFFF', text: '#4A044E' },
        { id: 'amber',    label: 'Amber',      desc: 'Golden warmth, cozy and inviting',       primary: '#D97706', bg: '#FFFDF5',  surface: '#FFFFFF', text: '#5C3D0E' },
    ];

    function buildThemeCard(t, isActive) {
        return `
            <button class="theme-card${isActive ? ' active' : ''}" data-theme="${t.id}">
                <div class="theme-card-preview" style="background:${t.bg}; border-color:${t.primary}20;">
                    <div class="theme-card-mockup">
                        <div class="theme-mock-sidebar" style="background:${t.surface}; border-color:${t.primary}20;">
                            <div class="theme-mock-dot" style="background:${t.primary};"></div>
                            <div class="theme-mock-line" style="background:${t.primary}30;"></div>
                            <div class="theme-mock-line short" style="background:${t.primary}20;"></div>
                        </div>
                        <div class="theme-mock-content">
                            <div class="theme-mock-heading" style="background:${t.text}; opacity:0.7;"></div>
                            <div class="theme-mock-bar" style="background:${t.primary};"></div>
                            <div class="theme-mock-bar half" style="background:${t.primary}40;"></div>
                        </div>
                    </div>
                </div>
                <div class="theme-card-info">
                    <span class="theme-card-name">
                        <span class="theme-card-dot" style="background:${t.primary};"></span>
                        ${t.label}
                    </span>
                    <span class="theme-card-desc">${t.desc}</span>
                </div>
                ${isActive ? '<div class="theme-card-check"><i class="fa-solid fa-circle-check"></i></div>' : ''}
            </button>`;
    }

    function openThemeModal() {
        if (document.getElementById('theme-modal')) return;
        const current = localStorage.getItem('al_staging_theme') || 'default';
        const overlay = document.createElement('div');
        overlay.id = 'theme-modal';
        overlay.className = 'theme-modal-overlay';
        overlay.innerHTML = `
            <div class="theme-modal">
                <div class="theme-modal-header">
                    <div>
                        <h2 class="theme-modal-title">Settings</h2>
                        <p class="theme-modal-subtitle">Choose a theme for your AlphaLearn experience</p>
                    </div>
                    <button class="theme-modal-close" id="theme-modal-close">
                        <i class="fa-solid fa-xmark"></i>
                    </button>
                </div>
                <div class="theme-modal-grid">
                    ${THEMES.map(t => buildThemeCard(t, t.id === current)).join('')}
                </div>
            </div>`;
        document.body.appendChild(overlay);

        // Close handlers
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) closeThemeModal();
        });
        document.getElementById('theme-modal-close').addEventListener('click', closeThemeModal);

        // Theme card click handlers
        overlay.querySelectorAll('.theme-card').forEach(card => {
            card.addEventListener('click', function () {
                const themeId = this.dataset.theme;
                // Apply theme
                if (themeId === 'default') {
                    localStorage.removeItem('al_staging_theme');
                    document.documentElement.removeAttribute('data-theme');
                } else {
                    localStorage.setItem('al_staging_theme', themeId);
                    document.documentElement.setAttribute('data-theme', themeId);
                }
                // Update active states
                overlay.querySelectorAll('.theme-card').forEach(c => {
                    c.classList.remove('active');
                    const check = c.querySelector('.theme-card-check');
                    if (check) check.remove();
                });
                this.classList.add('active');
                this.insertAdjacentHTML('beforeend', '<div class="theme-card-check"><i class="fa-solid fa-circle-check"></i></div>');
            });
        });

        // Animate in
        requestAnimationFrame(() => overlay.classList.add('open'));
    }

    function closeThemeModal() {
        const overlay = document.getElementById('theme-modal');
        if (!overlay) return;
        overlay.classList.remove('open');
        setTimeout(() => overlay.remove(), 200);
    }

    window._renderStagingThemeBar = function () {
        const sb = document.getElementById('sidebar');
        if (!sb) return;
        const navList = sb.querySelector('.nav-list');
        if (!navList || navList.querySelector('.nav-item-settings')) return; // already rendered

        // Add Settings nav item at the bottom of the nav list
        const settingsItem = document.createElement('li');
        settingsItem.className = 'nav-item nav-item-settings';
        settingsItem.innerHTML = `
            <a href="#" id="staging-settings-btn">
                <i class="fa-solid fa-gear"></i>
                <span>Settings</span>
            </a>`;
        navList.appendChild(settingsItem);

        // Open modal on click
        settingsItem.querySelector('a').addEventListener('click', function (e) {
            e.preventDefault();
            openThemeModal();
        });
    };

    // Render immediately if staging flag is already set
    if (localStorage.getItem('alphalearn_staging')) {
        window._renderStagingThemeBar();
    }
})();
