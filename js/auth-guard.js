/* ===========================================================================
   AlphaLearn – Admin Auth Guard
   Include this script FIRST on every admin page.
   It immediately redirects non-admin users to /login.
   Also provides a shared logout() function.
   =========================================================================== */

(function () {
    var role = (localStorage.getItem('alphalearn_role') || '').toLowerCase();
    if (!role || (!role.includes('admin') && !role.includes('administrator'))) {
        window.location.href = '/login';
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
