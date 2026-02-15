/* =====================================================================
   Admin Notifications — Question Report Queue
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

/* ── Stats bar ── */
function renderStats(stats) {
    var el = document.getElementById('stats-bar');
    el.innerHTML =
        '<div class="stat-chip"><span class="stat-num">' + (stats.total || 0) + '</span> Total Reports</div>' +
        '<div class="stat-chip pending"><span class="stat-num">' + (stats.aiFlagged || 0) + '</span> AI Flagged</div>' +
        '<div class="stat-chip pending"><span class="stat-num">' + (stats.pending || 0) + '</span> Pending</div>' +
        '<div class="stat-chip valid"><span class="stat-num">' + (stats.valid || 0) + '</span> Valid</div>' +
        '<div class="stat-chip invalid"><span class="stat-num">' + (stats.invalid || 0) + '</span> Invalid</div>' +
        '<div class="stat-chip reviewed"><span class="stat-num">' + (stats.humanReviewed || 0) + '</span> Human Reviewed</div>';
}

/* ── Filter tabs ── */
function renderTabs() {
    var counts = { all: allReports.length, ai_flagged: 0, pending: 0, valid: 0, invalid: 0, human_reviewed: 0 };
    allReports.forEach(function(r) {
        if (r.status === 'ai_flagged_bad') counts.ai_flagged++;
        if (r.status === 'pending_review' || r.status === 'ai_error') counts.pending++;
        if (r.verdict === 'valid') counts.valid++;
        if (r.verdict === 'invalid') counts.invalid++;
        if (r.adminAction === 'mark_good' || r.adminAction === 'mark_bad') counts.human_reviewed++;
    });
    document.getElementById('count-all').textContent = counts.all;
    document.getElementById('count-flagged').textContent = counts.ai_flagged;
    document.getElementById('count-pending').textContent = counts.pending;
    document.getElementById('count-valid').textContent = counts.valid;
    document.getElementById('count-invalid').textContent = counts.invalid;
    document.getElementById('count-reviewed').textContent = counts.human_reviewed;
}

function setFilter(f) {
    currentFilter = f;
    document.querySelectorAll('.filter-tab').forEach(function(t) { t.classList.toggle('active', t.dataset.filter === f); });
    renderReports();
}

function filteredReports() {
    if (currentFilter === 'all') return allReports;
    return allReports.filter(function(r) {
        if (currentFilter === 'ai_flagged') return r.status === 'ai_flagged_bad';
        if (currentFilter === 'pending') return r.status === 'pending_review' || r.status === 'ai_error';
        if (currentFilter === 'valid') return r.verdict === 'valid';
        if (currentFilter === 'invalid') return r.verdict === 'invalid';
        if (currentFilter === 'human_reviewed') return r.adminAction === 'mark_good' || r.adminAction === 'mark_bad';
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
    'not_in_source': 'Not in source materials',
    'factual_error': 'Factual error',
    'poorly_written': 'Poorly written/unclear',
    'other': 'Other',
};

function formatAiReasoning(text) {
    if (!text) return '';
    // Split on double-newlines or single newlines to create paragraphs
    var paragraphs = esc(text).split(/\n\s*\n|\n/).filter(function(p) { return p.trim(); });
    if (paragraphs.length <= 1) return '<p class="ai-reasoning-text">' + esc(text) + '</p>';
    return paragraphs.map(function(p) { return '<p class="ai-reasoning-text">' + p.trim() + '</p>'; }).join('');
}

function toggleExpandText(id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle('expanded');
    var btn = el.nextElementSibling;
    if (btn) btn.textContent = el.classList.contains('expanded') ? 'Show less' : 'Show more';
}

function buildReportCard(r) {
    var verdictClass = 'pending';
    var verdictLabel = 'Pending Review';
    var verdictIcon = 'fa-clock';
    if (r.adminAction === 'mark_good') {
        verdictClass = 'marked-good';
        verdictLabel = 'Marked Good';
        verdictIcon = 'fa-check-circle';
    } else if (r.adminAction === 'mark_bad') {
        verdictClass = 'marked-bad';
        verdictLabel = 'Marked Bad';
        verdictIcon = 'fa-ban';
    } else if (r.status === 'ai_flagged_bad') {
        verdictClass = 'ai-flagged';
        verdictLabel = 'AI Flagged — Needs Review';
        verdictIcon = 'fa-triangle-exclamation';
    } else if (r.status === 'ai_error') {
        verdictClass = 'error';
        verdictLabel = 'AI Error';
        verdictIcon = 'fa-exclamation-triangle';
    } else if (r.verdict === 'valid') {
        verdictClass = 'valid';
        verdictLabel = 'Valid Report';
        verdictIcon = 'fa-check-circle';
    } else if (r.verdict === 'invalid') {
        verdictClass = 'invalid';
        verdictLabel = 'Invalid Report';
        verdictIcon = 'fa-times-circle';
    }

    var date = r.date ? new Date(r.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' }) : '';

    // Choices HTML
    var choicesHtml = '';
    var choices = r.choices || [];
    var letters = 'ABCDEFGHIJ';
    for (var i = 0; i < choices.length; i++) {
        var c = choices[i];
        var isCorrect = (c.id || '') === (r.correctId || '');
        choicesHtml += '<div class="report-choice' + (isCorrect ? ' correct-choice' : '') + '">' +
            '<span class="choice-letter">' + (letters[i] || i) + '.</span> ' +
            '<span class="choice-text">' + esc(c.text || c.label || '') + '</span>' +
            (isCorrect ? ' <span class="correct-badge"><i class="fa-solid fa-check"></i> Correct</span>' : '') +
            '</div>';
    }

    var reasonText = reasonLabels[r.reason] || r.reason || 'Unknown';
    var uid = (r.id || '').replace(/[^a-zA-Z0-9_-]/g, '');

    var html = '<div class="report-card ' + verdictClass + '-card" id="card-' + esc(r.id) + '">';

    // ── Header row ──
    html += '<div class="report-card-header">';
    html += '<div class="report-meta">';
    html += '<span class="report-student"><i class="fa-solid fa-user"></i> ' + esc(r.studentId || 'Unknown') + '</span>';
    if (r.lessonTitle) html += '<span class="report-lesson"><i class="fa-solid fa-book"></i> ' + esc(r.lessonTitle) + '</span>';
    html += '<span class="report-date"><i class="fa-regular fa-clock"></i> ' + esc(date) + '</span>';
    html += '</div>';
    html += '<div class="report-header-right">';
    // Answered correctly indicator
    if (typeof r.answeredCorrectly !== 'undefined') {
        html += '<span class="answer-indicator ' + (r.answeredCorrectly ? 'correct' : 'incorrect') + '">' +
            '<i class="fa-solid ' + (r.answeredCorrectly ? 'fa-check-circle' : 'fa-times-circle') + '"></i> ' +
            (r.answeredCorrectly ? 'Student answered correctly' : 'Student answered incorrectly') + '</span>';
    }
    html += '<span class="verdict-badge ' + verdictClass + '"><i class="fa-solid ' + verdictIcon + '"></i> ' + verdictLabel + '</span>';
    html += '</div>';
    html += '</div>';

    // ── Question section ──
    var qText = r.questionText || '';
    if (typeof qText === 'object') qText = JSON.stringify(qText);
    var qEscaped = esc(qText);
    var needsTruncation = qEscaped.length > 300;

    html += '<div class="report-section">';
    html += '<div class="section-label"><i class="fa-solid fa-circle-question"></i> Question</div>';
    html += '<div class="report-question-box">';
    if (needsTruncation) {
        html += '<div class="report-question-text expandable" id="qt-' + uid + '">' + qEscaped + '</div>';
        html += '<button class="expand-btn" onclick="toggleExpandText(\'qt-' + uid + '\')">Show more</button>';
    } else {
        html += '<div class="report-question-text">' + qEscaped + '</div>';
    }
    if (choicesHtml) html += '<div class="report-choices">' + choicesHtml + '</div>';
    html += '</div>';
    html += '</div>';

    // ── Report reason section ──
    html += '<div class="report-section">';
    html += '<div class="section-label"><i class="fa-solid fa-flag"></i> Report Reason</div>';
    html += '<div class="report-reason-row">';
    html += '<span class="report-reason-tag"><i class="fa-solid fa-flag"></i> ' + esc(reasonText) + '</span>';
    if (r.pointsAwarded > 0) html += '<span class="report-reason-tag points-tag"><i class="fa-solid fa-star"></i> +' + r.pointsAwarded + ' points awarded</span>';
    html += '</div>';
    if (r.customText) html += '<div class="report-custom-text"><i class="fa-solid fa-quote-left"></i> ' + esc(r.customText) + '</div>';
    html += '</div>';

    // ── Source material section ──
    if (r.videoUrl || r.articleContent) {
        html += '<div class="report-section">';
        html += '<div class="section-label"><i class="fa-solid fa-book-open"></i> Source Material</div>';
        html += '<div class="source-material-box">';
        if (r.videoUrl) {
            html += '<div class="source-item"><i class="fa-solid fa-video"></i> <a href="' + esc(r.videoUrl) + '" target="_blank" rel="noopener">' + esc(r.videoUrl) + '</a></div>';
        }
        if (r.articleContent) {
            var articlePreview = esc(typeof r.articleContent === 'string' ? r.articleContent : JSON.stringify(r.articleContent));
            // Strip HTML tags from preview
            articlePreview = articlePreview.replace(/&lt;[^&]*&gt;/g, ' ').replace(/\s+/g, ' ').trim();
            if (articlePreview.length > 250) articlePreview = articlePreview.substring(0, 250) + '...';
            html += '<div class="source-item article-preview"><i class="fa-solid fa-file-lines"></i> ' + articlePreview + '</div>';
        }
        html += '</div>';
        html += '</div>';
    }

    // ── AI Analysis section ──
    html += '<div class="report-section">';
    html += '<div class="section-label"><i class="fa-solid fa-brain"></i> AI Analysis</div>';
    if (r.aiReasoning && r.aiReasoning !== 'AI review failed. Queued for manual admin review.') {
        html += '<div class="ai-analysis">';
        // Confidence bar
        if (typeof r.aiConfidence === 'number') {
            var confLevel = r.aiConfidence >= 80 ? 'high' : r.aiConfidence >= 50 ? 'medium' : 'low';
            html += '<div class="confidence-row">';
            html += '<span class="confidence-label">Confidence</span>';
            html += '<div class="confidence-bar-track"><div class="confidence-bar-fill ' + confLevel + '" style="width:' + Math.min(100, r.aiConfidence) + '%"></div></div>';
            html += '<span class="confidence-value">' + r.aiConfidence + '%</span>';
            html += '</div>';
        }
        // Recommendation tag
        if (r.aiRecommendation) {
            var recClass = r.aiRecommendation === 'remove' ? 'rec-remove' : r.aiRecommendation === 'regenerate' ? 'rec-regenerate' : 'rec-keep';
            html += '<span class="recommendation-tag ' + recClass + '"><i class="fa-solid fa-lightbulb"></i> Recommendation: ' + esc(r.aiRecommendation) + '</span>';
        }
        // Reasoning text
        html += '<div class="ai-reasoning-body">' + formatAiReasoning(r.aiReasoning) + '</div>';
        html += '</div>';
    } else {
        html += '<div class="ai-analysis empty">';
        html += '<i class="fa-solid fa-hourglass-half"></i> ';
        html += (r.status === 'ai_error') ? 'AI review failed. Queued for manual admin review.' : 'AI analysis pending or not yet available.';
        html += '</div>';
    }
    html += '</div>';

    // Admin note
    if (r.adminNote) {
        html += '<div class="admin-note"><i class="fa-solid fa-shield-halved"></i> ' + esc(r.adminNote) + '</div>';
    }

    // Action buttons (only show if not already reviewed by admin)
    if (!r.adminAction) {
        html += '<div class="report-actions">';
        html += '<button class="action-btn success" onclick="confirmAction(\'' + esc(r.id) + '\',\'mark_good\')" title="Question is valid — keep it"><i class="fa-solid fa-check-circle"></i> Mark as Good</button>';
        html += '<button class="action-btn danger" onclick="confirmAction(\'' + esc(r.id) + '\',\'mark_bad\')" title="Question is bad — permanently remove"><i class="fa-solid fa-ban"></i> Mark as Bad</button>';
        html += '</div>';
    }

    html += '</div>';
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
            loadReports(); // refresh
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
