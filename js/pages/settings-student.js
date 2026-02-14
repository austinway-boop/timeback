/* ===========================================================================
   AlphaLearn – Student Settings Page
   Theme picker rendered inline on the settings page.
   Reads window._THEME_SECTIONS and window._THEMES exposed by layout.js.
   =========================================================================== */

(function () {
    const THEME_SECTIONS = window._THEME_SECTIONS;
    const THEMES         = window._THEMES;
    if (!THEME_SECTIONS || !THEMES) return;

    const container = document.getElementById('theme-sections');
    if (!container) return;

    // Update subtitle with count
    const subtitle = document.getElementById('theme-count-subtitle');
    if (subtitle) subtitle.textContent = `Choose from ${THEMES.length} themes for your AlphaLearn experience`;

    const currentId = localStorage.getItem('al_theme') || 'default';

    /* ---- Helpers -------------------------------------------------------- */
    function getThemeById(id) {
        return THEMES.find(t => t.id === id) || THEMES[0];
    }

    function isColorDark(hex) {
        if (!hex || hex.charAt(0) !== '#') return false;
        const c = hex.substring(1);
        const r = parseInt(c.substring(0, 2), 16);
        const g = parseInt(c.substring(2, 4), 16);
        const b = parseInt(c.substring(4, 6), 16);
        return (r * 0.299 + g * 0.587 + b * 0.114) < 128;
    }

    function buildThemeCard(t, isActive) {
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

    /* ---- Render sections ------------------------------------------------ */
    container.innerHTML = THEME_SECTIONS.map(section => `
        <div class="theme-section">
            <h3 class="theme-section-title">
                <i class="fa-solid ${section.icon}"></i> ${section.title}
            </h3>
            <div class="theme-grid">
                ${section.themes.map(t => buildThemeCard(t, t.id === currentId)).join('')}
            </div>
        </div>`).join('');

    /* ---- Click + hover handlers ---------------------------------------- */
    let committedThemeId = currentId;

    container.querySelectorAll('.theme-card').forEach(card => {
        // Click to commit
        card.addEventListener('click', function () {
            const themeId = this.dataset.theme;
            committedThemeId = themeId;

            if (themeId === 'default') {
                localStorage.removeItem('al_theme');
                document.documentElement.removeAttribute('data-theme');
            } else {
                localStorage.setItem('al_theme', themeId);
                document.documentElement.setAttribute('data-theme', themeId);
            }

            // Update active states
            container.querySelectorAll('.theme-card').forEach(c => {
                c.classList.remove('active');
                const check = c.querySelector('.theme-card-check');
                if (check) check.remove();
            });
            this.classList.add('active');
            this.insertAdjacentHTML('beforeend', '<div class="theme-card-check"><i class="fa-solid fa-circle-check"></i></div>');
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

        // Mouse leave to revert
        card.addEventListener('mouseleave', function () {
            if (committedThemeId === 'default') {
                document.documentElement.removeAttribute('data-theme');
            } else {
                document.documentElement.setAttribute('data-theme', committedThemeId);
            }
        });
    });
})();
