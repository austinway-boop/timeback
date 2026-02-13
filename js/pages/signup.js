    /* ---- Helpers ---------------------------------------------------------- */
    function showError(msg) {
        const el = document.getElementById('signup-error');
        document.getElementById('error-text').textContent = msg;
        el.style.display = 'block';
        document.getElementById('signup-success').style.display = 'none';
    }

    function showSuccess(msg) {
        const el = document.getElementById('signup-success');
        document.getElementById('success-text').innerHTML = msg;
        el.style.display = 'block';
        document.getElementById('signup-error').style.display = 'none';
    }

    function hideMessages() {
        document.getElementById('signup-error').style.display = 'none';
        document.getElementById('signup-success').style.display = 'none';
    }

    function setLoading(btn, loading) {
        if (loading) {
            btn.disabled = true;
            btn.dataset.originalText = btn.innerHTML;
            btn.innerHTML = '<span class="skeleton-btn-bar"></span>';
        } else {
            btn.disabled = false;
            btn.innerHTML = btn.dataset.originalText || 'Create Account';
        }
    }

    /* ---- Signup Form → direct API call to /api/auth/signup --------------- */
    document.getElementById('signup-form').addEventListener('submit', async function (e) {
        e.preventDefault();
        hideMessages();

        const givenName  = document.getElementById('firstName').value.trim();
        const familyName = document.getElementById('lastName').value.trim();
        const email      = document.getElementById('email').value.trim();
        const password   = document.getElementById('password').value;
        const confirm    = document.getElementById('confirmPassword').value;
        const signupBtn  = document.getElementById('signup-btn');

        // Client-side validation
        if (!givenName || !familyName || !email || !password) {
            showError('Please fill in all fields.');
            return;
        }
        if (password !== confirm) {
            showError('Passwords do not match.');
            return;
        }
        if (password.length < 8) {
            showError('Password must be at least 8 characters.');
            return;
        }

        setLoading(signupBtn, true);

        try {
            const resp = await fetch('/api/auth/signup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ givenName, familyName, email, password }),
            });
            const data = await resp.json();

            if (!resp.ok || !data.success) {
                showError(data.error || 'Signup failed. Please try again.');
                setLoading(signupBtn, false);
                return;
            }

            showSuccess('Account created! Redirecting to <a href="/login">Sign In</a>...');
            signupBtn.disabled = true;

            // Redirect to login after a short delay
            setTimeout(function () {
                window.location.href = '/login';
            }, 2000);
        } catch (err) {
            console.error('[AlphaLearn] Signup error:', err);
            showError('Unable to reach the server. Please try again.');
            setLoading(signupBtn, false);
        }
    });
    