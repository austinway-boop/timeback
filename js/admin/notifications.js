/* =====================================================================
   Admin Notifications — Question Report Queue (Redesigned)
   ===================================================================== */
var allReports = [];
var currentFilter = 'all';
var pendingConfirmAction = null;

function esc(s) { if (s == null) return ''; if (typeof s !== 'string') s = String(s); return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

/* ── Load reports ── */
async function loadReports() {
    try {
        var resp = await fetch('/api/report-queue');
        var data = await resp.json();
        allReports = data.reports || [];
        renderStats(data.stats || {});
        renderTabs();
        renderReports();
    } catch(e) {
        document.getElementById('report-list').innerHTML = '<div class="empty-state"><i class="fa-solid fa-circle-exclamation"></i><h2>Failed to load reports</h2><p>' + esc(e.message) + '</p></div>';
    }
}

/* ── Stats bar (simplified: 3 chips) ── */
function renderStats(stats) {
    var total = stats.total || 0;
    var needsAttention = (stats.aiFlagged || 0) + (stats.pending || 0);
    var reviewed = (stats.humanReviewed || 0) + (stats.valid || 0) + (stats.invalid || 0);
    var el = document.getElementById('stats-bar');
    el.innerHTML =
        '<div class="stat-chip"><span class="stat-num">' + total + '</span> Total</div>' +
        '<div class="stat-chip attention"><span class="stat-num">' + needsAttention + '</span> Needs Attention</div>' +
        '<div class="stat-chip reviewed"><span class="stat-num">' + reviewed + '</span> Reviewed</div>';
}

/* ── Filter tabs (simplified: 3 tabs) ── */
function renderTabs() {
    var counts = { all: allReports.length, needs_review: 0, resolved: 0 };
    allReports.forEach(function(r) {
        if (_isNeedsReview(r)) counts.needs_review++;
        else counts.resolved++;
    });
    document.getElementById('count-all').textContent = counts.all;
    document.getElementById('count-needs-review').textContent = counts.needs_review;
    document.getElementById('count-resolved').textContent = counts.resolved;
}

function _isNeedsReview(r) {
    return r.status === 'ai_flagged_bad' || r.status === 'pending_review' || r.status === 'ai_error' || (!r.adminAction && r.verdict !== 'invalid');
}

function setFilter(f) {
    currentFilter = f;
    document.querySelectorAll('.filter-tab').forEach(function(t) { t.classList.toggle('active', t.dataset.filter === f); });
    renderReports();
}

function filteredReports() {
    if (currentFilter === 'all') return allReports;
    return allReports.filter(function(r) {
        if (currentFilter === 'needs_review') return _isNeedsReview(r);
        if (currentFilter === 'resolved') return !_isNeedsReview(r);
        return true;
    });
}

/* ── Render reports ── */
function renderReports() {
    var list = filteredReports();
    var el = document.getElementById('report-list');

    if (list.length === 0) {
        el.innerHTML = '<div class="empty-state"><i class="fa-solid fa-bell"></i><h2>No reports</h2><p>' +
            (currentFilter === 'all' ? 'No student question reports yet.' : 'No reports match this filter.') + '</p></div>';
        return;
    }

    var html = '';
    list.forEach(function(r) {
        html += buildReportCard(r);
    });
    el.innerHTML = html;
}

/* ── Reason label map ── */
var reasonLabels = {
    'not_in_source': 'Not in source',
    'factual_error': 'Factual error',
    'poorly_written': 'Poorly written',
    'other': 'Other',
};

/* ── Toggle details expand/collapse ── */
function toggleDetails(id) {
    var card = document.getElementById('card-' + id.replace(/[^a-zA-Z0-9_-]/g, ''));
    if (!card) return;
    card.classList.toggle('expanded');
}

/* ── Build compact report card ── */
function buildReportCard(r) {
    var verdictClass = 'pending';
    var verdictLabel = 'Pending';
    var verdictIcon = 'fa-clock';
    if (r.adminAction === 'mark_good') {
        verdictClass = 'marked-good';
        verdictLabel = 'Good';
        verdictIcon = 'fa-check-circle';
    } else if (r.adminAction === 'mark_bad') {
        verdictClass = 'marked-bad';
        verdictLabel = 'Bad';
        verdictIcon = 'fa-ban';
    } else if (r.status === 'ai_flagged_bad') {
        verdictClass = 'ai-flagged';
        verdictLabel = 'AI Flagged';
        verdictIcon = 'fa-triangle-exclamation';
    } else if (r.status === 'ai_error') {
        verdictClass = 'error';
        verdictLabel = 'AI Error';
        verdictIcon = 'fa-exclamation-triangle';
    } else if (r.verdict === 'valid') {
        verdictClass = 'valid';
        verdictLabel = 'Valid';
        verdictIcon = 'fa-check-circle';
    } else if (r.verdict === 'invalid') {
        verdictClass = 'invalid';
        verdictLabel = 'Invalid';
        verdictIcon = 'fa-times-circle';
    }

    var date = r.date ? new Date(r.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '';
    var uid = (r.id || '').replace(/[^a-zA-Z0-9_-]/g, '');
    var reasonText = reasonLabels[r.reason] || r.reason || 'Unknown';

    // Truncate question text for summary row
    var qText = r.questionText || '';
    if (typeof qText === 'object') qText = JSON.stringify(qText);
    var qShort = qText.length > 120 ? qText.substring(0, 120) + '...' : qText;

    var html = '<div class="report-card ' + verdictClass + '-card" id="card-' + esc(r.id) + '">';

    // ── Summary row (always visible) ──
    html += '<div class="report-summary" onclick="toggleDetails(\'' + esc(r.id) + '\')">';
    html += '<span class="verdict-badge ' + verdictClass + '"><i class="fa-solid ' + verdictIcon + '"></i> ' + verdictLabel + '</span>';
    html += '<span class="summary-question">' + esc(qShort) + '</span>';
    html += '<div class="summary-right">';
    html += '<span class="summary-reason">' + esc(reasonText) + '</span>';
    if (r.pointsAwarded > 0) html += '<span class="summary-points">+' + r.pointsAwarded + '</span>';
    html += '<span class="summary-date">' + esc(date) + '</span>';
    html += '<i class="fa-solid fa-chevron-down expand-icon"></i>';
    html += '</div>';
    html += '</div>';

    // ── Details (collapsed by default) ──
    html += '<div class="report-details">';

    // Meta row
    html += '<div class="detail-meta">';
    html += '<span><i class="fa-solid fa-user"></i> ' + esc(r.studentId || 'Unknown') + '</span>';
    if (r.lessonTitle) html += '<span><i class="fa-solid fa-book"></i> ' + esc(r.lessonTitle) + '</span>';
    if (typeof r.answeredCorrectly !== 'undefined') {
        html += '<span class="answer-indicator ' + (r.answeredCorrectly ? 'correct' : 'incorrect') + '">' +
            (r.answeredCorrectly ? 'Answered correctly' : 'Answered incorrectly') + '</span>';
    }
    html += '</div>';

    // Full question + choices
    html += '<div class="detail-section">';
    html += '<div class="detail-label">Question</div>';
    html += '<div class="detail-question">' + esc(qText) + '</div>';
    var choices = r.choices || [];
    if (choices.length > 0) {
        var letters = 'ABCDEFGHIJ';
        html += '<div class="detail-choices">';
        for (var i = 0; i < choices.length; i++) {
            var c = choices[i];
            var isCorrect = (c.id || '') === (r.correctId || '');
            html += '<div class="detail-choice' + (isCorrect ? ' correct' : '') + '">';
            html += '<span class="choice-letter">' + (letters[i] || i) + '.</span> ';
            html += esc(c.text || c.label || '');
            if (isCorrect) html += ' <span class="correct-badge"><i class="fa-solid fa-check"></i></span>';
            html += '</div>';
        }
        html += '</div>';
    }
    html += '</div>';

    // Student's elaboration
    if (r.customText) {
        html += '<div class="detail-section">';
        html += '<div class="detail-label">Student Note</div>';
        html += '<div class="detail-note">' + esc(r.customText) + '</div>';
        html += '</div>';
    }

    // AI Analysis
    if (r.aiReasoning && r.aiReasoning !== 'AI review failed. Queued for manual admin review.') {
        html += '<div class="detail-section">';
        html += '<div class="detail-label">AI Analysis</div>';
        html += '<div class="detail-ai">';
        // Lesson relevance summary (highlighted at top)
        if (r.aiLessonRelevance) {
            html += '<div class="lesson-relevance"><i class="fa-solid fa-book-open"></i> ' + esc(r.aiLessonRelevance) + '</div>';
        }
        if (typeof r.aiConfidence === 'number') {
            var confLevel = r.aiConfidence >= 80 ? 'high' : r.aiConfidence >= 50 ? 'medium' : 'low';
            html += '<div class="ai-conf"><span class="conf-label">Confidence</span><div class="conf-track"><div class="conf-fill ' + confLevel + '" style="width:' + Math.min(100, r.aiConfidence) + '%"></div></div><span class="conf-val">' + r.aiConfidence + '%</span></div>';
        }
        if (r.aiRecommendation) {
            var recClass = r.aiRecommendation === 'remove' ? 'rec-remove' : r.aiRecommendation === 'regenerate' ? 'rec-regenerate' : 'rec-keep';
            html += '<span class="rec-tag ' + recClass + '">' + esc(r.aiRecommendation) + '</span>';
        }
        html += '<p class="ai-text">' + esc(r.aiReasoning) + '</p>';
        html += '</div>';
        html += '</div>';
    } else if (r.status === 'ai_error') {
        html += '<div class="detail-section">';
        html += '<div class="detail-label">AI Analysis</div>';
        html += '<div class="detail-ai empty"><i class="fa-solid fa-exclamation-triangle"></i> AI review failed. Queued for manual review.</div>';
        html += '</div>';
    }

    // Admin note
    if (r.adminNote) {
        html += '<div class="admin-note"><i class="fa-solid fa-shield-halved"></i> ' + esc(r.adminNote) + '</div>';
    }

    // Action buttons (only show if not already reviewed by admin)
    if (!r.adminAction) {
        html += '<div class="detail-actions">';
        html += '<button class="action-btn success" onclick="event.stopPropagation();confirmAction(\'' + esc(r.id) + '\',\'mark_good\')"><i class="fa-solid fa-check"></i> Good</button>';
        html += '<button class="action-btn danger" onclick="event.stopPropagation();confirmAction(\'' + esc(r.id) + '\',\'mark_bad\')"><i class="fa-solid fa-ban"></i> Bad</button>';
        html += '</div>';
    }

    html += '</div>'; // .report-details
    html += '</div>'; // .report-card
    return html;
}

/* ── Admin actions ── */
async function doAction(reportId, action) {
    try {
        var resp = await fetch('/api/report-queue', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reportId: reportId, action: action }),
        });
        var data = await resp.json();
        if (data.ok) {
            showToast('Action completed successfully.', 'success');
            loadReports();
        } else {
            showToast(data.error || 'Action failed.', 'warning');
        }
    } catch(e) {
        showToast('Network error: ' + e.message, 'warning');
    }
}

/* ── Confirmation modal ── */
function confirmAction(reportId, action) {
    pendingConfirmAction = { reportId: reportId, action: action };
    if (action === 'mark_good') {
        document.getElementById('confirm-title').textContent = 'Mark Question as Good?';
        document.getElementById('confirm-text').innerHTML =
            'This confirms the question is <strong>valid</strong>. ' +
            'It will be shown to students again if it was temporarily hidden.';
        document.getElementById('confirm-btn').className = 'confirm-primary';
        document.getElementById('confirm-btn').textContent = 'Mark as Good';
    } else if (action === 'mark_bad') {
        document.getElementById('confirm-title').textContent = 'Mark Question as Bad?';
        document.getElementById('confirm-text').innerHTML =
            'This <strong>permanently removes</strong> the question from the platform. ' +
            'It will no longer be shown to any students.';
        document.getElementById('confirm-btn').className = 'confirm-danger';
        document.getElementById('confirm-btn').textContent = 'Mark as Bad';
    }
    document.getElementById('confirm-modal').classList.add('open');
}

function closeConfirm() {
    document.getElementById('confirm-modal').classList.remove('open');
    pendingConfirmAction = null;
}

function executeConfirm() {
    if (pendingConfirmAction) {
        doAction(pendingConfirmAction.reportId, pendingConfirmAction.action);
    }
    closeConfirm();
}

document.getElementById('confirm-modal').addEventListener('click', function(e) { if (e.target === this) closeConfirm(); });

/* ── Toast ── */
function showToast(msg, type) {
    type = type || 'success';
    var t = document.getElementById('toast');
    var ic = type === 'success' ? 'fa-check-circle' : type === 'info' ? 'fa-info-circle' : 'fa-exclamation-triangle';
    t.className = 'toast ' + type;
    t.innerHTML = '<i class="fa-solid ' + ic + '"></i> ' + esc(msg);
    requestAnimationFrame(function() { t.classList.add('visible'); });
    setTimeout(function() { t.classList.remove('visible'); }, 4000);
}

/* ── Init ── */
document.addEventListener('DOMContentLoaded', loadReports);
document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeConfirm(); });
