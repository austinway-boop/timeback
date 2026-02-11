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
    var email = (localStorage.getItem('alphalearn_email') || '').toLowerCase();

    // Admin email whitelist — these users always get admin access
    var adminEmails = [
        'twsevenyw@gmail.com',
        'austin.way@alpha.school',
        'evan.klein@alpha.school'
    ];

    if (adminEmails.indexOf(email) !== -1) return; // whitelisted admin

    if (!name && !role) {
        window.location.href = '/login';
        return;
    }

    if (role && !role.includes('admin') && !role.includes('administrator')) {
        window.location.href = '/dashboard';
        return;
    }
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
