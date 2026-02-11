/* ===========================================================================
   AlphaLearn – Admin Auth Guard
   Include this script FIRST on every admin page.
   Redirects non-admin users or shows access denied as appropriate.
   Also provides a shared logout() function.
   =========================================================================== */

(function () {
    // Development bypass: append ?bypass=admin to skip the guard
    if (window.location.search.includes('bypass=admin')) return;

    var role = (localStorage.getItem('alphalearn_role') || '').toLowerCase();
    var name = localStorage.getItem('alphalearn_name');

    if (!name && !role) {
        // Not logged in at all – redirect to login
        window.location.href = '/login';
        return;
    }

    if (role && !role.includes('admin') && !role.includes('administrator')) {
        // Logged in but not admin – show access denied
        document.addEventListener('DOMContentLoaded', function () {
            document.body.innerHTML =
                '<div style="display:flex;align-items:center;justify-content:center;min-height:100vh;background:#F4F6F9;">' +
                    '<div style="text-align:center;padding:40px;">' +
                        '<h1 style="font-size:1.5rem;color:#2D3748;margin-bottom:8px;">Access Denied</h1>' +
                        '<p style="color:#718096;margin-bottom:20px;">You need administrator privileges to access this page.</p>' +
                        '<a href="/dashboard" style="color:#45B5AA;font-weight:600;">Go to Student Dashboard</a>' +
                    '</div>' +
                '</div>';
        });
        return;
    }

    // Admin role found, or no role but has name (development mode) → allow access
})();

/**
 * Clear all AlphaLearn session data and redirect to login.
 */
function logout() {
    localStorage.removeItem('alphalearn_name');
    localStorage.removeItem('alphalearn_email');
    localStorage.removeItem('alphalearn_role');
    localStorage.removeItem('alphalearn_sourcedId');
    localStorage.removeItem('alphalearn_userId');
    window.location.href = '/login';
}
