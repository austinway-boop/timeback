    /** Store user data and redirect based on role */
    function handleAuthSuccess(user) {
        const displayName = ((user.givenName || '') + ' ' + (user.familyName || '')).trim() || user.email;
        localStorage.setItem('alphalearn_name', displayName);
        localStorage.setItem('alphalearn_email', user.email || '');
        localStorage.setItem('alphalearn_role', user.role || 'student');
        localStorage.setItem('alphalearn_sourcedId', user.sourcedId || '');

        const role = (user.role || '').toLowerCase();
        if (role.includes('admin') || role.includes('administrator')) {
            window.location.href = '/admin';
        } else {
            window.location.href = '/dashboard';
        }
    }

    function showError(msg) {
        document.getElementById('loading-state').style.display = 'none';
        const errorState = document.getElementById('error-state');
        errorState.style.display = 'block';
        document.getElementById('error-message').textContent = msg;
    }

    /* ---- Process OAuth Callback ------------------------------------------ */
    (async function processCallback() {
        const params = new URLSearchParams(window.location.search);
        const code = params.get('code');
        const error = params.get('error');
        const errorDescription = params.get('error_description');

        // Handle Cognito-level errors (e.g. user denied consent)
        if (error) {
            showError(errorDescription || error || 'Authentication was cancelled.');
            return;
        }

        // No code means the user landed here directly
        if (!code) {
            showError('No authorization code found. Please try signing in again.');
            return;
        }

        try {
            const redirectUri = encodeURIComponent(window.location.origin + '/callback');
            const resp = await fetch('/api/auth/callback?code=' + encodeURIComponent(code) + '&redirect_uri=' + redirectUri);
            const data = await resp.json();

            if (!resp.ok || !data.success) {
                showError(data.error || 'Authentication failed. Please try again.');
                return;
            }

            handleAuthSuccess(data.user);
        } catch (err) {
            console.error('[AlphaLearn] Callback error:', err);
            showError('Unable to complete sign-in. Please try again.');
        }
    })();
    