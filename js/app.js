/* ===========================================================================
   AlphaLearn – Client-side JavaScript
   =========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
    initTimeToggle();
    initNavSubmenus();
});

/* --- Today / This Week Toggle -------------------------------------------- */
function initTimeToggle() {
    const buttons = document.querySelectorAll('.toggle-btn[data-period]');
    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const period = btn.dataset.period;
            updateXpPeriodLabels(period === 'week' ? 'THIS WEEK' : 'TODAY');
        });
    });
}

function updateXpPeriodLabels(text) {
    document.querySelectorAll('.xp-period').forEach(el => {
        el.textContent = text;
    });
}

/* --- Sidebar Submenus ---------------------------------------------------- */
function initNavSubmenus() {
    document.querySelectorAll('.has-submenu .nav-link-toggle').forEach(toggle => {
        toggle.addEventListener('click', (e) => {
            e.preventDefault();
            const item = toggle.closest('.nav-item');
            item.classList.toggle('submenu-open');
            const chevron = toggle.querySelector('.nav-chevron');
            if (chevron) {
                chevron.style.transform = item.classList.contains('submenu-open')
                    ? 'rotate(90deg)' : 'rotate(0)';
            }
        });
    });
}
