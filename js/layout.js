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

    const THEME_SECTIONS = [
        {
            title: 'Standard',
            icon: 'fa-palette',
            themes: [
                { id: 'default',  label: 'Default',   desc: 'Clean teal — the classic look',      primary: '#45B5AA', bg: '#F4F6F9',  surface: '#FFFFFF', text: '#2D3748', radius: '12px', sidebarBg: '#FFFFFF' },
                { id: 'ocean',    label: 'Ocean',      desc: 'Deep blue gradient sidebar, watery depth', primary: '#1D63A6', bg: '#EBF2FA', surface: '#F5F9FF', text: '#0F2942', radius: '16px', sidebarBg: '#1A4F8A' },
                { id: 'lavender', label: 'Lavender',   desc: 'Pill shapes, dreamy purple haze',    primary: '#7C3AED', bg: '#F3F0FF',  surface: '#FAF8FF', text: '#2E1065', radius: '20px', sidebarBg: '#F3F0FF' },
                { id: 'sunset',   label: 'Sunset',     desc: 'Fiery sidebar, warm glow everywhere', primary: '#DC4E11', bg: '#FFF5EB', surface: '#FFFAF5', text: '#431407', radius: '14px', sidebarBg: '#B93E0A' },
                { id: 'rose',     label: 'Rose',       desc: 'Elegant blush-tinted everything',    primary: '#DB2777', bg: '#FDF2F8',  surface: '#FFF5FA', text: '#500724', radius: '16px', sidebarBg: '#FFF5FA' },
                { id: 'forest',   label: 'Forest',     desc: 'Dark green sidebar, earthy and warm', primary: '#0D7C3E', bg: '#ECFDF2', surface: '#F5FFF8', text: '#052E16', radius: '10px', sidebarBg: '#064E24' },
                { id: 'slate',    label: 'Slate',      desc: 'Sharp corners, flat & ultra-minimal', primary: '#64748B', bg: '#F1F5F9', surface: '#FFFFFF', text: '#0F172A', radius: '4px',  sidebarBg: '#FFFFFF' },
                { id: 'midnight', label: 'Midnight',   desc: 'Full dark mode with glow borders',   primary: '#818CF8', bg: '#0B1120',  surface: '#151D2E', text: '#E8ECF4', radius: '8px',  sidebarBg: '#080D18' },
                { id: 'berry',    label: 'Berry',      desc: 'Purple gradient sidebar, playful shapes', primary: '#C026D3', bg: '#FBF0FF', surface: '#FEF9FF', text: '#3B0544', radius: '18px', sidebarBg: '#7E22CE' },
                { id: 'amber',    label: 'Amber',      desc: 'Golden sidebar, honey-glow shadows', primary: '#C47E0B', bg: '#FFFBEB',  surface: '#FFFDF5', text: '#451A03', radius: '12px', sidebarBg: '#92400E' },
            ]
        },
        {
            title: 'Seasonal',
            icon: 'fa-sun',
            themes: [
                { id: 'spring',   label: 'Spring',    desc: 'Soft pills, cherry blossom pink wash', primary: '#E4729B', bg: '#FFF7FA', surface: '#FFFBFD', text: '#4A1A2E', radius: '20px', sidebarBg: '#FFF0F5' },
                { id: 'summer',   label: 'Summer',    desc: 'Cyan gradient sidebar, bold & sunny', primary: '#0891B2', bg: '#EFFCFF',  surface: '#F8FEFF', text: '#134E5A', radius: '14px', sidebarBg: '#0E7490' },
                { id: 'autumn',   label: 'Autumn',    desc: 'Brown sidebar, warm maple everywhere', primary: '#B45309', bg: '#FBF5EC', surface: '#FDF9F3', text: '#3D1E03', radius: '8px',  sidebarBg: '#6B3410' },
                { id: 'winter',   label: 'Winter',    desc: 'Frosty icy surfaces, glass-like feel', primary: '#6B8FC7', bg: '#F0F4FA', surface: '#F8FAFF', text: '#1C2D44', radius: '12px', sidebarBg: '#E8F0FE' },
            ]
        },
        {
            title: 'Holidays',
            icon: 'fa-gift',
            themes: [
                { id: 'valentines',  label: "Valentine's",   desc: 'Romantic red sidebar, hearts overlay', primary: '#E63462', bg: '#FFF0F3', surface: '#FFF8F9', text: '#4A0E20', radius: '22px', sidebarBg: '#C41E4A' },
                { id: 'stpatricks',  label: "St. Patrick's", desc: 'Shamrock green sidebar, gold accents', primary: '#228B22', bg: '#F0F9F0', surface: '#F7FCF7', text: '#0B3B0B', radius: '12px', sidebarBg: '#145A14' },
                { id: 'july4th',     label: 'July 4th',      desc: 'Navy sidebar, red top stripe',        primary: '#2553A0', bg: '#F2F5FB', surface: '#FAFBFF', text: '#111D33', radius: '6px',  sidebarBg: '#0D1F45' },
                { id: 'halloween',   label: 'Halloween',     desc: 'Sharp & spooky, orange glow on dark', primary: '#E86C1A', bg: '#1A1025', surface: '#231530', text: '#F0E6F6', radius: '4px',  sidebarBg: '#120A1A' },
                { id: 'christmas',   label: 'Christmas',     desc: 'Green sidebar, red accents, snowfall', primary: '#C41E3A', bg: '#FDF5F5', surface: '#FFFAFA', text: '#3D0A14', radius: '16px', sidebarBg: '#1B5E20' },
                { id: 'newyears',    label: "New Year's",    desc: 'Luxe dark with gold sparkle accents', primary: '#D4A843', bg: '#0E0B1A', surface: '#18142A', text: '#F2ECD8', radius: '6px',  sidebarBg: '#0A0818' },
            ]
        },
        {
            title: 'Special',
            icon: 'fa-star',
            themes: [
                { id: 'neon',      label: 'Neon',       desc: 'Cyberpunk green glow on jet black',   primary: '#39FF14', bg: '#050A05',  surface: '#0C140C', text: '#D0F0C8', radius: '2px',  sidebarBg: '#030803' },
                { id: 'bubblegum', label: 'Bubblegum',  desc: 'Candy pink, pillowy & playful',       primary: '#FF6BB5', bg: '#FFF5FA',  surface: '#FFFFFF', text: '#5C1040', radius: '24px', sidebarBg: '#E8408F' },
                { id: 'coffee',    label: 'Coffee',     desc: 'Espresso sidebar, warm cream surfaces', primary: '#8B5E3C', bg: '#FAF5EF', surface: '#FDF8F3', text: '#3B2614', radius: '10px', sidebarBg: '#3B2614' },
                { id: 'arctic',    label: 'Arctic',     desc: 'Pure ice, barely-there shadows',      primary: '#88C0D0', bg: '#F8FCFD',  surface: '#FFFFFF', text: '#2E3440', radius: '6px',  sidebarBg: '#FFFFFF' },
                { id: 'sakura',    label: 'Sakura',     desc: 'Cherry blossom + warm stone elegance', primary: '#C97B8B', bg: '#FBF6F4', surface: '#FEF9F8', text: '#3E2830', radius: '14px', sidebarBg: '#5C464C' },
                { id: 'retro',     label: 'Retro',      desc: 'Teal sidebar + warm orange, 80s vibes', primary: '#E87040', bg: '#FFF8F2', surface: '#FFFCF8', text: '#2A2018', radius: '8px', sidebarBg: '#1A6B60' },
                { id: 'mocha',     label: 'Mocha',      desc: 'Dark chocolate + caramel gold, rich',  primary: '#D4A05A', bg: '#161010',  surface: '#1E1614', text: '#F0E4D4', radius: '12px', sidebarBg: '#120C08' },
                { id: 'reef',      label: 'Coral Reef', desc: 'Turquoise sidebar, coral accents',    primary: '#FF6B6B', bg: '#F0FFFE',  surface: '#F8FFFF', text: '#1A3838', radius: '16px', sidebarBg: '#0E7B72' },
                { id: 'storm',     label: 'Storm',      desc: 'Charcoal + electric blue, dramatic',  primary: '#4A9EF5', bg: '#10141A',  surface: '#181E28', text: '#E0E8F0', radius: '6px',  sidebarBg: '#0C1018' },
                { id: 'matcha',    label: 'Matcha',     desc: 'Sage green, zen calm, ultra-muted',   primary: '#8BA88A', bg: '#F6F8F4',  surface: '#FBFCF9', text: '#2A3228', radius: '16px', sidebarBg: '#F0F4EF' },
            ]
        }
    ];

    // Flat list for lookups
    const THEMES = THEME_SECTIONS.flatMap(s => s.themes);

    function buildThemeCard(t, isActive) {
        // Determine if sidebar is dark (text should be light in preview)
        const isDarkSidebar = isColorDark(t.sidebarBg);
        const sidebarLineColor = isDarkSidebar ? 'rgba(255,255,255,0.25)' : (t.primary + '30');
        const sidebarLineColorLight = isDarkSidebar ? 'rgba(255,255,255,0.15)' : (t.primary + '20');
        const mockRadius = t.radius || '12px';

        return `
            <button class="theme-card${isActive ? ' active' : ''}" data-theme="${t.id}">
                <div class="theme-card-preview" style="background:${t.bg}; border-color:${t.primary}20;">
                    <div class="theme-card-mockup" style="border-radius:${mockRadius};">
                        <div class="theme-mock-sidebar" style="background:${t.sidebarBg}; border-color:${isDarkSidebar ? 'rgba(255,255,255,0.08)' : t.primary + '20'}; border-radius:${mockRadius} 0 0 ${mockRadius};">
                            <div class="theme-mock-dot" style="background:${isDarkSidebar ? '#FFFFFF' : t.primary}; opacity:${isDarkSidebar ? '0.7' : '1'};"></div>
                            <div class="theme-mock-line" style="background:${sidebarLineColor};"></div>
                            <div class="theme-mock-line short" style="background:${sidebarLineColorLight};"></div>
                        </div>
                        <div class="theme-mock-content" style="border-radius:0 ${mockRadius} ${mockRadius} 0;">
                            <div class="theme-mock-heading" style="background:${t.text}; opacity:0.7;"></div>
                            <div class="theme-mock-bar" style="background:${t.primary}; border-radius:calc(${mockRadius} / 4);"></div>
                            <div class="theme-mock-bar half" style="background:${t.primary}40; border-radius:calc(${mockRadius} / 4);"></div>
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

    // Rough check if a hex color is dark
    function isColorDark(hex) {
        if (!hex || hex.charAt(0) !== '#') return false;
        const c = hex.substring(1);
        const r = parseInt(c.substring(0, 2), 16);
        const g = parseInt(c.substring(2, 4), 16);
        const b = parseInt(c.substring(4, 6), 16);
        return (r * 0.299 + g * 0.587 + b * 0.114) < 128;
    }

    function getThemeById(id) {
        return THEMES.find(t => t.id === id) || THEMES[0];
    }

    function openThemeModal() {
        if (document.getElementById('theme-modal')) return;
        const currentId = localStorage.getItem('al_staging_theme') || 'default';
        const currentTheme = getThemeById(currentId);
        const totalCount = THEMES.length;

        const overlay = document.createElement('div');
        overlay.id = 'theme-modal';
        overlay.className = 'theme-modal-overlay';

        const sectionsHTML = THEME_SECTIONS.map(section => `
            <div class="theme-modal-section">
                <h3 class="theme-modal-section-title">
                    <i class="fa-solid ${section.icon}"></i> ${section.title}
                </h3>
                <div class="theme-modal-grid">
                    ${section.themes.map(t => buildThemeCard(t, t.id === currentId)).join('')}
                </div>
            </div>`).join('');

        overlay.innerHTML = `
            <div class="theme-modal">
                <div class="theme-modal-header">
                    <div>
                        <h2 class="theme-modal-title">Settings</h2>
                        <p class="theme-modal-subtitle">Choose from ${totalCount} themes for your AlphaLearn experience</p>
                    </div>
                    <button class="theme-modal-close" id="theme-modal-close">
                        <i class="fa-solid fa-xmark"></i>
                    </button>
                </div>
                <div class="theme-modal-active" id="theme-modal-active-banner">
                    <span class="theme-modal-active-dot" style="background:${currentTheme.primary};"></span>
                    Currently using: <span class="theme-modal-active-name">${currentTheme.label}</span>
                </div>
                <div class="theme-modal-body">
                    ${sectionsHTML}
                </div>
            </div>`;
        document.body.appendChild(overlay);

        // Track the committed theme for hover-preview revert
        let committedThemeId = currentId;

        // Close handlers
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) closeThemeModal(committedThemeId);
        });
        document.getElementById('theme-modal-close').addEventListener('click', function () {
            closeThemeModal(committedThemeId);
        });

        // Theme card click handlers
        overlay.querySelectorAll('.theme-card').forEach(card => {
            // Click to commit
            card.addEventListener('click', function () {
                const themeId = this.dataset.theme;
                committedThemeId = themeId;
                // Apply and save
                if (themeId === 'default') {
                    localStorage.removeItem('al_staging_theme');
                    document.documentElement.removeAttribute('data-theme');
                } else {
                    localStorage.setItem('al_staging_theme', themeId);
                    document.documentElement.setAttribute('data-theme', themeId);
                }
                // Update active states on cards
                overlay.querySelectorAll('.theme-card').forEach(c => {
                    c.classList.remove('active');
                    const check = c.querySelector('.theme-card-check');
                    if (check) check.remove();
                });
                this.classList.add('active');
                this.insertAdjacentHTML('beforeend', '<div class="theme-card-check"><i class="fa-solid fa-circle-check"></i></div>');
                // Update the active banner
                const t = getThemeById(themeId);
                const banner = document.getElementById('theme-modal-active-banner');
                if (banner) {
                    banner.querySelector('.theme-modal-active-dot').style.background = t.primary;
                    banner.querySelector('.theme-modal-active-name').textContent = t.label;
                }
            });

            // Hover to live-preview
            card.addEventListener('mouseenter', function () {
                const themeId = this.dataset.theme;
                if (themeId === 'default') {
                    document.documentElement.removeAttribute('data-theme');
                } else {
                    document.documentElement.setAttribute('data-theme', themeId);
                }
            });

            // Mouse leave to revert to committed theme
            card.addEventListener('mouseleave', function () {
                if (committedThemeId === 'default') {
                    document.documentElement.removeAttribute('data-theme');
                } else {
                    document.documentElement.setAttribute('data-theme', committedThemeId);
                }
            });
        });

        // Animate in
        requestAnimationFrame(() => overlay.classList.add('open'));
    }

    function closeThemeModal(committedId) {
        const overlay = document.getElementById('theme-modal');
        if (!overlay) return;
        // Ensure the committed theme is applied on close (in case hover left it different)
        if (committedId && committedId !== 'default') {
            document.documentElement.setAttribute('data-theme', committedId);
        } else if (committedId === 'default') {
            document.documentElement.removeAttribute('data-theme');
        }
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
