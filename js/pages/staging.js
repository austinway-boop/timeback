/* ===========================================================================
   AlphaLearn – Staging Hub
   Auto-logs in with the staging test account and renders feature cards.
   =========================================================================== */

(function () {
    /* ---- Staging credentials ---------------------------------------------- */
    const STAGING_EMAIL    = 'pehal64861@aixind.com';
    const STAGING_PASSWORD = 'Backdoor1!';

    /* ---- Feature definitions ---------------------------------------------- */
    const studentFeatures = [
        {
            title: 'Dashboard',
            desc: 'Course cards, assigned tests, XP tracking, today/week toggle.',
            icon: 'fa-house',
            color: 'var(--color-primary)',
            href: '/dashboard'
        },
        {
            title: 'Course View',
            desc: 'Unit & lesson structure, progress tracking, lesson locking.',
            icon: 'fa-book-open',
            color: 'var(--color-blue)',
            href: '/dashboard',
            note: 'Open a course from the dashboard'
        },
        {
            title: 'Lesson Viewer',
            desc: 'Step-by-step lesson content, embedded quizzes, video/article resources.',
            icon: 'fa-chalkboard',
            color: 'var(--color-purple)',
            href: '/dashboard',
            note: 'Navigate: Dashboard > Course > Lesson'
        },
        {
            title: 'Quiz / Assessment',
            desc: 'PowerPath adaptive flow, QTI questions, crossout tool, FRQ support.',
            icon: 'fa-pen-to-square',
            color: 'var(--color-pink)',
            href: '/dashboard',
            note: 'Navigate: Dashboard > Course > Lesson > Quiz'
        },
        {
            title: 'Goals',
            desc: 'Set end dates, daily XP goals, pace calculation, holiday calendar.',
            icon: 'fa-bullseye',
            color: 'var(--color-orange)',
            href: '/goals'
        }
    ];

    const adminFeatures = [
        {
            title: 'Students',
            desc: 'User creation/editing, role management, enrollment management.',
            icon: 'fa-users',
            color: 'var(--color-blue)',
            href: '/admin/students'
        },
        {
            title: 'Courses',
            desc: 'Browse and manage the course catalog.',
            icon: 'fa-book',
            color: 'var(--color-primary)',
            href: '/admin/courses'
        },
        {
            title: 'Assign Tests',
            desc: 'Assign mastery tests by subject and grade.',
            icon: 'fa-clipboard-check',
            color: 'var(--color-purple)',
            href: '/admin/assign-tests'
        },
        {
            title: 'Notifications',
            desc: 'Manage and review notification queue.',
            icon: 'fa-bell',
            color: 'var(--color-orange)',
            href: '/admin/notifications'
        },
        {
            title: 'Thinking Tree',
            desc: 'Visualize student thinking patterns.',
            icon: 'fa-brain',
            color: 'var(--color-pink)',
            href: '/admin/thinking-tree'
        },
        {
            title: 'Settings',
            desc: 'Organization settings, admin users, permissions, integrations.',
            icon: 'fa-gear',
            color: 'var(--color-text-secondary)',
            href: '/admin/settings'
        }
    ];

    const utilityFeatures = [
        {
            title: 'Download Tool',
            desc: 'Extract AP course content — videos, articles, questions — into a ZIP.',
            icon: 'fa-download',
            color: 'var(--color-blue)',
            href: '/download'
        }
    ];

    /* ---- Render a single feature card ------------------------------------- */
    function renderCard(feature) {
        const noteHtml = feature.note
            ? `<span class="staging-card-note"><i class="fa-solid fa-circle-info"></i> ${feature.note}</span>`
            : '';

        return `
            <a href="${feature.href}" class="staging-card">
                <div class="staging-card-icon" style="background: ${feature.color}15; color: ${feature.color};">
                    <i class="fa-solid ${feature.icon}"></i>
                </div>
                <div class="staging-card-body">
                    <h3 class="staging-card-title">${feature.title}</h3>
                    <p class="staging-card-desc">${feature.desc}</p>
                    ${noteHtml}
                </div>
                <div class="staging-card-arrow">
                    <i class="fa-solid fa-arrow-right"></i>
                </div>
            </a>`;
    }

    /* ---- Render all sections ---------------------------------------------- */
    function renderFeatures() {
        document.getElementById('student-features').innerHTML  = studentFeatures.map(renderCard).join('');
        document.getElementById('admin-features').innerHTML    = adminFeatures.map(renderCard).join('');
        document.getElementById('utility-features').innerHTML  = utilityFeatures.map(renderCard).join('');
    }

    /* ---- Status indicator helpers ----------------------------------------- */
    function setStatus(icon, label, state) {
        const el = document.getElementById('staging-status');
        el.className = 'staging-status staging-status--' + state;
        el.querySelector('.staging-status-icon').innerHTML  = `<i class="fa-solid ${icon}"></i>`;
        el.querySelector('.staging-status-label').textContent = label;
    }

    /* ---- Auto-login ------------------------------------------------------- */
    async function autoLogin() {
        try {
            const resp = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: STAGING_EMAIL, password: STAGING_PASSWORD })
            });
            const data = await resp.json();

            if (!resp.ok || !data.success) {
                setStatus('fa-triangle-exclamation', 'Login failed — ' + (data.error || 'unknown error'), 'error');
                return;
            }

            // Store auth data (same keys as normal login)
            const user = data.user;
            const displayName = ((user.givenName || '') + ' ' + (user.familyName || '')).trim() || user.email;
            localStorage.setItem('alphalearn_name',      displayName);
            localStorage.setItem('alphalearn_email',     user.email || '');
            localStorage.setItem('alphalearn_role',      user.role  || 'student');
            localStorage.setItem('alphalearn_sourcedId', user.sourcedId || '');

            // Set staging flag
            localStorage.setItem('alphalearn_staging', 'true');

            setStatus('fa-circle-check', 'Logged in as ' + displayName, 'success');
        } catch (err) {
            console.error('[Staging] Auto-login error:', err);
            setStatus('fa-triangle-exclamation', 'Could not reach the server', 'error');
        }
    }

    /* ---- Exit staging ----------------------------------------------------- */
    window._exitStaging = function () {
        localStorage.removeItem('alphalearn_name');
        localStorage.removeItem('alphalearn_email');
        localStorage.removeItem('alphalearn_role');
        localStorage.removeItem('alphalearn_sourcedId');
        localStorage.removeItem('alphalearn_userId');
        localStorage.removeItem('alphalearn_staging');
        window.location.href = '/login';
    };

    /* ---- Init ------------------------------------------------------------- */
    renderFeatures();
    autoLogin();
})();
