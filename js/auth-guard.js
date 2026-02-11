/* ===========================================================================
   AlphaLearn – Admin Auth Guard
   Include this script FIRST on every admin page.
   Redirects non-admin users appropriately.
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
        // Logged in but not admin – redirect to student dashboard
        window.location.href = '/dashboard';
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
