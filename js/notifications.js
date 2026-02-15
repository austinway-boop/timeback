/* ===========================================================================
   AlphaLearn – Notification Bell (student report statuses)
   Extracted from layout.js — load after layout.js so topbar DOM exists.
   =========================================================================== */

(function initNotifBell() {
    const style = document.createElement('style');
    style.textContent = `
        .notif-badge { position:absolute; top:2px; right:2px; min-width:16px; height:16px; line-height:16px; text-align:center; border-radius:8px; background:#E53E3E; color:#fff; font-size:0.62rem; font-weight:700; padding:0 4px; pointer-events:none; }
        .notif-panel { display:none; position:absolute; top:calc(100% + 8px); right:0; width:340px; max-height:420px; overflow-y:auto; background:#fff; border:1px solid var(--color-border); border-radius:12px; box-shadow:0 12px 40px rgba(0,0,0,0.15); z-index:9999; }
        .notif-panel.open { display:block; }
        .notif-panel-header { padding:14px 16px; border-bottom:1px solid var(--color-border); font-weight:700; font-size:0.88rem; color:var(--color-text); display:flex; align-items:center; justify-content:space-between; }
        .notif-panel-header .notif-clear { font-size:0.75rem; font-weight:500; color:var(--color-text-muted); cursor:pointer; border:none; background:none; padding:2px 6px; }
        .notif-panel-header .notif-clear:hover { color:#E53E3E; }
        .notif-item { padding:12px 16px; border-bottom:1px solid var(--color-border); transition:background 0.1s; }
        .notif-item:last-child { border-bottom:none; }
        .notif-item.unread { background:#F0F7FF; }
        .notif-item-q { font-size:0.82rem; font-weight:500; color:var(--color-text); line-height:1.4; margin-bottom:6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .notif-item-status { display:inline-flex; align-items:center; gap:5px; font-size:0.75rem; font-weight:600; padding:3px 8px; border-radius:6px; }
        .notif-status-processing { background:#FFF3E0; color:#E65100; }
        .notif-status-awarded { background:#E8F5E9; color:#1B5E20; }
        .notif-status-no-issue { background:#F3F4F6; color:#6B7280; }
        .notif-status-team { background:#EDE7F6; color:#4527A0; }
        .notif-status-replaced { background:#E3F2FD; color:#1565C0; }
        .notif-status-flagged { background:#FFF3E0; color:#D84315; }
        .notif-item-time { font-size:0.7rem; color:var(--color-text-muted); margin-top:4px; }
        .notif-empty { padding:30px 16px; text-align:center; color:var(--color-text-muted); font-size:0.85rem; }
        .notif-empty i { display:block; font-size:1.5rem; margin-bottom:8px; opacity:0.3; }
        .notif-item-reasoning { font-size:0.75rem; color:var(--color-text-muted); line-height:1.45; margin-top:6px; padding:8px 10px; background:#F9FAFB; border-radius:6px; border-left:3px solid #D1D5DB; }
    `;
    document.head.appendChild(style);

    function getNotifs() {
        try { return JSON.parse(localStorage.getItem('al_report_notifs') || '[]'); } catch(e) { return []; }
    }
    function saveNotifs(n) { localStorage.setItem('al_report_notifs', JSON.stringify(n)); }

    function renderBadge() {
        const notifs = getNotifs();
        const unread = notifs.filter(n => !n.read).length;
        const badge = document.getElementById('notif-badge');
        if (badge) {
            if (unread > 0) { badge.textContent = unread; badge.style.display = ''; }
            else { badge.style.display = 'none'; }
        }
    }

    function statusHtml(n) {
        if (n.status === 'processing') return '<span class="notif-item-status notif-status-processing"><i class="fa-solid fa-spinner fa-spin"></i> AI Reviewing...</span>';
        if (n.status === 'ai_flagged_bad') return '<span class="notif-item-status notif-status-flagged"><i class="fa-solid fa-triangle-exclamation"></i> AI Flagged — Human Review Pending</span>';
        if (n.status === 'completed' && n.verdict === 'valid' && n.pointsAwarded > 0) return '<span class="notif-item-status notif-status-awarded"><i class="fa-solid fa-star"></i> +' + n.pointsAwarded + ' Points Awarded</span>';
        if (n.status === 'completed' && n.verdict === 'valid' && n.pointsAwarded === 0) return '<span class="notif-item-status notif-status-team"><i class="fa-solid fa-users"></i> Sent to Internal Team</span>';
        if (n.status === 'completed' && n.verdict === 'invalid') return '<span class="notif-item-status notif-status-no-issue"><i class="fa-solid fa-check"></i> Reviewed — No Issues Found</span>';
        if (n.status === 'internal_review') return '<span class="notif-item-status notif-status-team"><i class="fa-solid fa-users"></i> Under Internal Review</span>';
        if (n.status === 'replaced') return '<span class="notif-item-status notif-status-replaced"><i class="fa-solid fa-rotate"></i> Question Replaced</span>';
        return '<span class="notif-item-status notif-status-processing"><i class="fa-solid fa-clock"></i> Pending</span>';
    }

    function timeAgo(ts) {
        if (!ts) return '';
        const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
        if (diff < 60) return 'just now';
        if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
        if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
        return Math.floor(diff / 86400) + 'd ago';
    }

    function renderPanel() {
        const notifs = getNotifs();
        const panel = document.getElementById('notif-panel');
        if (!panel) return;
        if (notifs.length === 0) {
            panel.innerHTML = '<div class="notif-panel-header">Reports<span></span></div><div class="notif-empty"><i class="fa-solid fa-bell"></i>No question reports yet</div>';
            return;
        }
        let html = '<div class="notif-panel-header">Reports <button class="notif-clear" onclick="window._clearNotifs()">Clear all</button></div>';
        notifs.slice().reverse().forEach(function(n) {
            const q = (n.questionText || '').substring(0, 60) + ((n.questionText || '').length > 60 ? '...' : '');
            html += '<div class="notif-item' + (n.read ? '' : ' unread') + '">';
            html += '<div class="notif-item-q">' + (q || 'Reported question') + '</div>';
            html += statusHtml(n);
            if (n.reasoning) {
                var reason = n.reasoning.length > 200 ? n.reasoning.substring(0, 200) + '...' : n.reasoning;
                html += '<div class="notif-item-reasoning">' + reason + '</div>';
            }
            html += '<div class="notif-item-time">' + timeAgo(n.timestamp) + '</div>';
            html += '</div>';
        });
        panel.innerHTML = html;
    }

    window._toggleNotifPanel = function() {
        const panel = document.getElementById('notif-panel');
        const isOpen = panel.classList.toggle('open');
        if (isOpen) {
            renderPanel();
            // Mark all as read
            const notifs = getNotifs();
            notifs.forEach(function(n) { n.read = true; });
            saveNotifs(notifs);
            renderBadge();
        }
    };

    window._clearNotifs = function() {
        saveNotifs([]);
        renderPanel();
        renderBadge();
    };

    // Close panel on outside click
    document.addEventListener('click', function(e) {
        const wrap = document.getElementById('notif-bell-wrap');
        const panel = document.getElementById('notif-panel');
        if (wrap && panel && !wrap.contains(e.target)) {
            panel.classList.remove('open');
        }
    });

    // Global helpers for quiz/lesson pages to call
    window._addReportNotif = function(data) {
        const notifs = getNotifs();
        notifs.push({
            reportId: data.reportId,
            questionText: data.questionText || '',
            status: 'processing',
            verdict: null,
            pointsAwarded: 0,
            answeredCorrectly: data.answeredCorrectly || false,
            timestamp: new Date().toISOString(),
            read: false,
        });
        saveNotifs(notifs);
        renderBadge();
    };

    window._updateReportNotif = function(reportId, updates) {
        const notifs = getNotifs();
        for (let i = 0; i < notifs.length; i++) {
            if (notifs[i].reportId === reportId) {
                Object.assign(notifs[i], updates, { read: false });
                break;
            }
        }
        saveNotifs(notifs);
        renderBadge();
    };

    renderBadge();
})();
