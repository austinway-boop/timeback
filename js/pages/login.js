    /* ---- Helpers ---------------------------------------------------------- */
    function showError(msg) {
        const el = document.getElementById('login-error');
        document.getElementById('error-text').textContent = msg;
        el.style.display = 'flex';
    }

    function hideError() {
        document.getElementById('login-error').style.display = 'none';
    }

    function setLoading(btn, loading, originalText) {
        if (loading) {
            btn.disabled = true;
            btn.dataset.originalText = btn.innerHTML;
            btn.innerHTML = '<span class="skeleton-btn-bar"></span>';
        } else {
            btn.disabled = false;
            btn.innerHTML = btn.dataset.originalText || originalText || 'Submit';
        }
    }

    /** Store user data in localStorage and redirect based on role */
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

    /* ---- Email / Password Login ------------------------------------------ */
    document.getElementById('login-form').addEventListener('submit', async function (e) {
        e.preventDefault();
        hideError();

        const email    = document.getElementById('email').value.trim();
        const password = document.getElementById('password').value;
        const loginBtn = document.getElementById('login-btn');

        if (!email || !password) {
            showError('Please enter your email and password.');
            return;
        }

        setLoading(loginBtn, true);

        try {
            const resp = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password }),
            });
            const data = await resp.json();

            if (!resp.ok || !data.success) {
                showError(data.error || 'Invalid email or password.');
                setLoading(loginBtn, false, 'Sign In');
                return;
            }

            handleAuthSuccess(data.user);
        } catch (err) {
            console.error('[AlphaLearn] Login error:', err);
            showError('Unable to reach the server. Please try again.');
            setLoading(loginBtn, false, 'Sign In');
        }
    });
    