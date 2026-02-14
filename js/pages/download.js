/* =========================================================================
   AlphaLearn — TEMP Download Questions Page
   ========================================================================= */

var apCourses = [];
var selectedCourseId = null;
var selectedCatalogId = null;
var extractedData = null;

/* ---- Helpers --------------------------------------------------------- */
function isAPCourse(title) { return /\bAP\b/.test((title || '').trim()); }

function setStatus(html) {
    document.getElementById('status-text').innerHTML = html;
}

/* ---- 1. Load courses (enrollments for correct IDs + catalog for full list) */
(function loadCourses() {
    var userId = localStorage.getItem('alphalearn_userId') || localStorage.getItem('alphalearn_sourcedId') || '';

    // Fetch both sources in parallel: enrollments (correct PowerPath IDs)
    // and course catalog (full list of all AP courses in the org).
    var enrollPromise = userId
        ? fetch('/api/enrollments?userId=' + encodeURIComponent(userId)).then(function (r) { return r.json(); }).catch(function () { return {}; })
        : Promise.resolve({});
    var catalogPromise = fetch('/api/courses').then(function (r) { return r.json(); }).catch(function () { return {}; });

    Promise.all([enrollPromise, catalogPromise])
        .then(function (results) {
            var enrollData = results[0];
            var catalogData = results[1];

            // 1. Build map from enrollment data (these have the correct PowerPath IDs)
            var enrollRaw = enrollData.data || enrollData.enrollments || enrollData.courses || (Array.isArray(enrollData) ? enrollData : []);
            var enrollMap = {}; // title (lowercase) → { sourcedId, title, courseCode }
            for (var i = 0; i < enrollRaw.length; i++) {
                var e = enrollRaw[i];
                var ec = e.course || {};
                var eTitle = (ec.title || '').trim();
                if (!isAPCourse(eTitle)) continue;
                var eKey = eTitle.toLowerCase();
                if (!enrollMap[eKey]) {
                    enrollMap[eKey] = {
                        sourcedId: ec.sourcedId || ec.id || '',
                        title: eTitle,
                        courseCode: ec.courseCode || ec.sourcedId || '',
                    };
                }
            }

            // 2. Build full list from catalog, preferring enrollment IDs when available
            var catalogCourses = catalogData.courses || [];
            var seen = {};
            for (var j = 0; j < catalogCourses.length; j++) {
                var cc = catalogCourses[j];
                var cTitle = (cc.title || '').trim();
                if (!isAPCourse(cTitle)) continue;
                var cKey = cTitle.toLowerCase();
                if (seen[cKey]) continue;
                seen[cKey] = true;
                // Store BOTH IDs: enrollment ID (for student-specific endpoint)
                // and catalog ID (for tree endpoint) — backend tries both
                var enrolled = enrollMap[cKey];
                apCourses.push({
                    sourcedId: (enrolled && enrolled.sourcedId) || cc.sourcedId || '',
                    catalogId: cc.sourcedId || '',
                    title: cTitle,
                    courseCode: cc.courseCode || cc.sourcedId || '',
                });
            }

            // 3. Add any enrollment courses not in catalog (edge case)
            for (var ek in enrollMap) {
                if (!seen[ek]) {
                    seen[ek] = true;
                    apCourses.push(enrollMap[ek]);
                }
            }

            document.getElementById('courses-loading').style.display = 'none';

            if (apCourses.length === 0) {
                document.getElementById('empty-state').style.display = '';
                return;
            }

            var grid = document.getElementById('courses-grid');
            grid.style.display = '';
            document.getElementById('actions-bar').style.display = '';

            var icons = ['fa-book-open', 'fa-flask', 'fa-calculator', 'fa-globe-americas', 'fa-atom', 'fa-landmark', 'fa-dna', 'fa-laptop-code'];

            apCourses.forEach(function (c, i) {
                var card = document.createElement('div');
                card.className = 'dl-course-card';
                card.dataset.id = c.sourcedId;
                card.innerHTML =
                    '<div class="cc-icon"><i class="fa-solid ' + icons[i % icons.length] + '"></i></div>' +
                    '<div class="cc-title">' + escapeHtml(c.title) + '</div>' +
                    '<div class="cc-meta">' + escapeHtml(c.courseCode) + '</div>';
                card.onclick = function () { selectCourse(c.sourcedId, c.catalogId, card); };
                grid.appendChild(card);
            });
        })
        .catch(function (err) {
            document.getElementById('courses-loading').innerHTML =
                '<i class="fa-solid fa-exclamation-triangle" style="color:#E53E3E"></i> Failed to load courses: ' + escapeHtml(err.message);
        });
})();

function escapeHtml(str) {
    var d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
}

/* ---- 2. Select course ------------------------------------------------ */
function selectCourse(courseId, catalogId, card) {
    selectedCourseId = courseId;
    selectedCatalogId = catalogId || '';
    extractedData = null;
    document.getElementById('btn-extract').disabled = false;
    document.getElementById('btn-download').disabled = true;
    document.getElementById('results').style.display = 'none';
    setStatus('');

    // Toggle selected styling
    var cards = document.querySelectorAll('.dl-course-card');
    for (var i = 0; i < cards.length; i++) cards[i].classList.remove('selected');
    card.classList.add('selected');
}

/* ---- 3. Extract content ---------------------------------------------- */
var _progressTimer = null;

var PROGRESS_STAGES = [
    { at: 0,  label: 'Connecting to PowerPath...' },
    { at: 5,  label: 'Fetching lesson plan tree...' },
    { at: 12, label: 'Parsing units and lessons...' },
    { at: 20, label: 'Extracting video links...' },
    { at: 30, label: 'Fetching article content...' },
    { at: 45, label: 'Loading QTI questions...' },
    { at: 60, label: 'Resolving question details...' },
    { at: 75, label: 'Assembling results...' },
    { at: 88, label: 'Almost done...' },
];

function startProgress() {
    var bar = document.getElementById('progress-bar');
    var fill = document.getElementById('progress-fill');
    var stage = document.getElementById('progress-stage');
    var pct = document.getElementById('progress-pct');
    bar.classList.add('active');
    fill.style.width = '0%';
    pct.textContent = '0%';
    stage.innerHTML = '<span class="spinner"></span> Starting...';

    var current = 0;
    var startTime = Date.now();

    _progressTimer = setInterval(function () {
        var elapsed = (Date.now() - startTime) / 1000;
        // Asymptotic curve: approaches 95% over ~60s, never reaches 100
        current = Math.min(95, 95 * (1 - Math.exp(-elapsed / 20)));
        var rounded = Math.round(current);
        fill.style.width = rounded + '%';
        pct.textContent = rounded + '%';

        // Update stage label
        var label = PROGRESS_STAGES[0].label;
        for (var i = 0; i < PROGRESS_STAGES.length; i++) {
            if (rounded >= PROGRESS_STAGES[i].at) label = PROGRESS_STAGES[i].label;
        }
        stage.innerHTML = '<span class="spinner"></span> ' + label;
    }, 300);
}

function stopProgress(success) {
    if (_progressTimer) { clearInterval(_progressTimer); _progressTimer = null; }
    var fill = document.getElementById('progress-fill');
    var stage = document.getElementById('progress-stage');
    var pct = document.getElementById('progress-pct');
    if (success) {
        fill.style.width = '100%';
        pct.textContent = '100%';
        stage.innerHTML = '<i class="fa-solid fa-check" style="color:#2E7D32"></i> Complete';
        // Fade out after a moment
        setTimeout(function () {
            document.getElementById('progress-bar').classList.remove('active');
        }, 1500);
    } else {
        document.getElementById('progress-bar').classList.remove('active');
    }
}

function extractContent() {
    if (!selectedCourseId) return;

    var btn = document.getElementById('btn-extract');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Extracting...';
    document.getElementById('btn-download').disabled = true;
    document.getElementById('results').style.display = 'none';
    setStatus('');
    startProgress();

    // No student ID sent — download uses admin catalog endpoints only
    var extractUrl = '/api/temp-extract?courseId=' + encodeURIComponent(selectedCourseId);
    if (selectedCatalogId && selectedCatalogId !== selectedCourseId) {
        extractUrl += '&catalogId=' + encodeURIComponent(selectedCatalogId);
    }
    fetch(extractUrl)
        .then(function (r) { return r.json(); })
        .then(function (data) {
            btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Extract Content';
            btn.disabled = false;

            if (!data.success) {
                stopProgress(false);
                setStatus('<i class="fa-solid fa-exclamation-triangle" style="color:#E53E3E"></i> ' + escapeHtml(data.error || 'Unknown error'));
                return;
            }

            stopProgress(true);
            extractedData = data;
            document.getElementById('btn-download').disabled = false;
            var parts = [];
            if (data.totalVideos) parts.push(data.totalVideos + ' video' + (data.totalVideos !== 1 ? 's' : ''));
            if (data.totalArticles) parts.push(data.totalArticles + ' article' + (data.totalArticles !== 1 ? 's' : ''));
            parts.push(data.totalQuestions + ' question' + (data.totalQuestions !== 1 ? 's' : ''));
            setStatus('<i class="fa-solid fa-check-circle" style="color:#2E7D32"></i> Extracted ' + parts.join(', ') + ' from ' + data.unitCount + ' units');
            renderResults(data);
        })
        .catch(function (err) {
            stopProgress(false);
            btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Extract Content';
            btn.disabled = false;
            setStatus('<i class="fa-solid fa-exclamation-triangle" style="color:#E53E3E"></i> ' + escapeHtml(err.message));
        });
}

/* ---- 4. Render results tree ------------------------------------------ */
function renderResults(data) {
    var container = document.getElementById('results');
    container.style.display = '';
    container.innerHTML = '';

    // Summary bar
    var summary = document.createElement('div');
    summary.className = 'dl-summary';
    summary.innerHTML =
        '<div class="dl-stat"><div class="dl-stat-val">' + data.unitCount + '</div><div class="dl-stat-label">Units</div></div>' +
        '<div class="dl-stat"><div class="dl-stat-val">' + countLessons(data) + '</div><div class="dl-stat-label">Lessons</div></div>' +
        '<div class="dl-stat"><div class="dl-stat-val">' + (data.totalVideos || 0) + '</div><div class="dl-stat-label">Videos</div></div>' +
        '<div class="dl-stat"><div class="dl-stat-val">' + (data.totalArticles || 0) + '</div><div class="dl-stat-label">Articles</div></div>' +
        '<div class="dl-stat"><div class="dl-stat-val">' + data.totalQuestions + '</div><div class="dl-stat-label">Questions</div></div>';
    container.appendChild(summary);

    if (!data.units || data.units.length === 0) {
        container.innerHTML += '<div class="dl-empty"><i class="fa-solid fa-folder-open"></i><p>No units found for this course.</p></div>';
        return;
    }

    // Units
    data.units.forEach(function (unit, ui) {
        var unitEl = document.createElement('div');
        unitEl.className = 'dl-unit';
        var unitQCount = 0, unitVCount = 0, unitACount = 0;
        (unit.lessons || []).forEach(function (l) {
            unitQCount += (l.questions || []).length;
            unitVCount += (l.videos || []).length;
            unitACount += (l.articles || []).length;
        });
        var badgeParts = [];
        if (unitVCount) badgeParts.push(unitVCount + ' vid');
        if (unitACount) badgeParts.push(unitACount + ' art');
        badgeParts.push(unitQCount + ' Q');

        var unitHeader = document.createElement('div');
        unitHeader.className = 'dl-unit-header';
        unitHeader.innerHTML =
            '<i class="fa-solid fa-chevron-right chevron"></i>' +
            '<span class="unit-title">' + escapeHtml(unit.title || ('Unit ' + (ui + 1))) + '</span>' +
            '<span class="unit-badge">' + badgeParts.join(' / ') + '</span>';
        unitHeader.onclick = function () { unitEl.classList.toggle('open'); };
        unitEl.appendChild(unitHeader);

        var unitBody = document.createElement('div');
        unitBody.className = 'dl-unit-body';

        (unit.lessons || []).forEach(function (lesson, li) {
            var lessonEl = document.createElement('div');
            lessonEl.className = 'dl-lesson';
            var qs = lesson.questions || [];
            var vids = lesson.videos || [];
            var arts = lesson.articles || [];
            var totalItems = vids.length + arts.length + qs.length;

            var lBadgeParts = [];
            if (vids.length) lBadgeParts.push(vids.length + ' vid');
            if (arts.length) lBadgeParts.push(arts.length + ' art');
            lBadgeParts.push(qs.length + ' Q');

            var lessonHeader = document.createElement('div');
            lessonHeader.className = 'dl-lesson-header';
            lessonHeader.innerHTML =
                '<i class="fa-solid fa-chevron-right chevron"></i>' +
                '<span class="lesson-title">' + escapeHtml(lesson.title || ('Lesson ' + (li + 1))) + '</span>' +
                '<span class="lesson-badge">' + lBadgeParts.join(' / ') + '</span>';
            lessonHeader.onclick = function (e) { e.stopPropagation(); lessonEl.classList.toggle('open'); };
            lessonEl.appendChild(lessonHeader);

            var lessonBody = document.createElement('div');
            lessonBody.className = 'dl-lesson-body';

            if (totalItems === 0) {
                lessonBody.innerHTML = '<div style="font-size:0.82rem;color:var(--color-text-muted);padding:8px 0;"><i class="fa-solid fa-info-circle"></i> No content extracted for this lesson.</div>';
            } else {
                // Videos
                if (vids.length > 0) {
                    lessonBody.innerHTML += '<div class="dl-section-label"><i class="fa-solid fa-play"></i> Videos</div>';
                    vids.forEach(function (v) {
                        lessonBody.innerHTML += renderVideo(v);
                    });
                }

                // Articles
                if (arts.length > 0) {
                    lessonBody.innerHTML += '<div class="dl-section-label"><i class="fa-solid fa-file-lines"></i> Articles</div>';
                    arts.forEach(function (a, ai) {
                        lessonBody.innerHTML += renderArticle(a, ai);
                    });
                }

                // Questions
                if (qs.length > 0) {
                    lessonBody.innerHTML += '<div class="dl-section-label"><i class="fa-solid fa-clipboard-question"></i> Questions</div>';
                    qs.forEach(function (q, qi) {
                        lessonBody.innerHTML += renderQuestion(q, qi);
                    });
                }
            }

            lessonEl.appendChild(lessonBody);
            unitBody.appendChild(lessonEl);
        });

        unitEl.appendChild(unitBody);
        container.appendChild(unitEl);
    });
}

function renderVideo(v) {
    var html = '<div class="dl-video">';
    html += '<div class="dl-video-icon"><i class="fa-solid fa-play"></i></div>';
    html += '<div class="dl-video-info">';
    html += '<div class="dl-video-title">' + escapeHtml(v.title || 'Video') + '</div>';
    if (v.url) {
        html += '<div class="dl-video-link"><a href="' + escapeHtml(v.url) + '" target="_blank" rel="noopener">' + escapeHtml(v.url) + '</a></div>';
    }
    html += '</div></div>';
    return html;
}

function renderArticle(a, idx) {
    var artId = 'art-' + Math.random().toString(36).substr(2, 6);
    var html = '<div class="dl-article">';
    html += '<div class="dl-article-header">';
    html += '<div class="dl-article-icon"><i class="fa-solid fa-file-lines"></i></div>';
    html += '<div><div class="dl-article-title">' + escapeHtml(a.title || 'Article') + '</div>';
    if (a.url) {
        html += '<div class="dl-article-url"><a href="' + escapeHtml(a.url) + '" target="_blank" rel="noopener">' + escapeHtml(a.url) + '</a></div>';
    }
    html += '</div></div>';
    if (a.content) {
        html += '<div class="dl-article-content" id="' + artId + '">' + escapeHtml(a.content) + '</div>';
        html += '<button class="dl-article-toggle" onclick="toggleArticle(\'' + artId + '\', this)">Show more</button>';
    }
    html += '</div>';
    return html;
}

function toggleArticle(id, btn) {
    var el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle('expanded');
    btn.textContent = el.classList.contains('expanded') ? 'Show less' : 'Show more';
}

function renderQuestion(q, idx) {
    var html = '<div class="dl-question">';
    html += '<span class="dl-q-num">Q' + (idx + 1) + '</span>';
    if (q.title) html += '<strong>' + escapeHtml(q.title) + '</strong>';
    html += '<span class="dl-q-type ' + (q.type || 'mcq') + '">' + (q.type === 'frq' ? 'FRQ' : 'MCQ') + '</span>';

    if (q.stimulus) {
        html += '<div class="dl-q-stimulus">' + escapeHtml(q.stimulus) + '</div>';
    }

    if (q.prompt) {
        html += '<div class="dl-q-prompt">' + escapeHtml(q.prompt) + '</div>';
    }

    if (q.choices && q.choices.length > 0) {
        html += '<div class="dl-q-choices">';
        q.choices.forEach(function (c) {
            var isCorrect = q.correctAnswer && c.id === q.correctAnswer;
            html += '<div class="dl-q-choice' + (isCorrect ? ' correct' : '') + '">' +
                '<span class="choice-id">' + escapeHtml(c.id) + '</span>' +
                '<span>' + escapeHtml(c.label) + (isCorrect ? ' <i class="fa-solid fa-check"></i>' : '') + '</span>' +
                '</div>';
        });
        html += '</div>';
    }

    html += '</div>';
    return html;
}

function countLessons(data) {
    var n = 0;
    (data.units || []).forEach(function (u) { n += (u.lessons || []).length; });
    return n;
}

/* ---- 5. Download as organized ZIP folder ----------------------------- */
function safeName(str) {
    return (str || 'untitled').replace(/[^a-zA-Z0-9 _-]/g, '').replace(/\s+/g, '_').substring(0, 80);
}

function padNum(n) { return n < 10 ? '0' + n : '' + n; }

function formatQuestionsTxt(questions) {
    if (!questions || !questions.length) return '';
    var lines = [];
    questions.forEach(function (q, i) {
        lines.push('Q' + (i + 1) + (q.title ? '. ' + q.title : '.'));
        lines.push('Type: ' + (q.type === 'frq' ? 'Free Response' : 'Multiple Choice'));
        if (q.stimulus) { lines.push(''); lines.push('Stimulus:'); lines.push(q.stimulus); }
        if (q.prompt) { lines.push(''); lines.push(q.prompt); }
        if (q.rawContent && !q.prompt) { lines.push(''); lines.push(q.rawContent); }
        if (q.choices && q.choices.length) {
            lines.push('');
            q.choices.forEach(function (c) {
                var mark = (q.correctAnswer && c.id === q.correctAnswer) ? ' [CORRECT]' : '';
                lines.push('  ' + c.id + ') ' + c.label + mark);
            });
        }
        if (q.correctAnswer && (!q.choices || !q.choices.length)) {
            lines.push('');
            lines.push('Answer: ' + q.correctAnswer);
        }
        lines.push('');
        lines.push('---');
        lines.push('');
    });
    return lines.join('\n');
}

function formatVideosTxt(videos) {
    if (!videos || !videos.length) return '';
    var lines = [];
    videos.forEach(function (v, i) {
        lines.push('Video ' + (i + 1) + ': ' + (v.title || 'Untitled'));
        if (v.url) lines.push('URL: ' + v.url);
        lines.push('');
    });
    return lines.join('\n');
}

function formatArticlesTxt(articles) {
    if (!articles || !articles.length) return '';
    var lines = [];
    articles.forEach(function (a, i) {
        lines.push('Article ' + (i + 1) + ': ' + (a.title || 'Untitled'));
        if (a.url) lines.push('URL: ' + a.url);
        if (a.content) { lines.push(''); lines.push(a.content); }
        lines.push('');
        lines.push('---');
        lines.push('');
    });
    return lines.join('\n');
}

function downloadZIP() {
    if (!extractedData) return;

    var btn = document.getElementById('btn-download');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Building ZIP...';

    var courseName = safeName((extractedData.course && extractedData.course.title) || 'AP Course');
    var zip = new JSZip();
    var root = zip.folder(courseName);

    // Course summary at root
    var summaryLines = [
        courseName,
        '='.repeat(courseName.length),
        '',
        'Units: ' + (extractedData.unitCount || 0),
        'Lessons: ' + countLessons(extractedData),
        'Videos: ' + (extractedData.totalVideos || 0),
        'Articles: ' + (extractedData.totalArticles || 0),
        'Questions: ' + (extractedData.totalQuestions || 0),
        '',
    ];
    (extractedData.units || []).forEach(function (unit, ui) {
        summaryLines.push(padNum(ui + 1) + '. ' + (unit.title || 'Unit ' + (ui + 1)));
        (unit.lessons || []).forEach(function (lesson, li) {
            var counts = [];
            if (lesson.videos && lesson.videos.length) counts.push(lesson.videos.length + ' vid');
            if (lesson.articles && lesson.articles.length) counts.push(lesson.articles.length + ' art');
            counts.push((lesson.questions || []).length + ' Q');
            summaryLines.push('    ' + padNum(li + 1) + '. ' + (lesson.title || 'Lesson') + '  [' + counts.join(', ') + ']');
        });
        summaryLines.push('');
    });
    root.file('_SUMMARY.txt', summaryLines.join('\n'));

    // Full raw data for programmatic use
    root.file('_raw_data.json', JSON.stringify(extractedData, null, 2));

    // Create unit and lesson folders
    (extractedData.units || []).forEach(function (unit, ui) {
        var unitName = padNum(ui + 1) + '_' + safeName(unit.title || 'Unit_' + (ui + 1));
        var unitFolder = root.folder(unitName);

        (unit.lessons || []).forEach(function (lesson, li) {
            var lessonName = padNum(li + 1) + '_' + safeName(lesson.title || 'Lesson_' + (li + 1));
            var lessonFolder = unitFolder.folder(lessonName);

            // Videos
            var vids = lesson.videos || [];
            if (vids.length) {
                lessonFolder.file('videos.txt', formatVideosTxt(vids));
            }

            // Articles
            var arts = lesson.articles || [];
            if (arts.length) {
                lessonFolder.file('articles.txt', formatArticlesTxt(arts));
            }

            // Questions
            var qs = lesson.questions || [];
            if (qs.length) {
                lessonFolder.file('questions.txt', formatQuestionsTxt(qs));
                lessonFolder.file('questions.json', JSON.stringify(qs, null, 2));
            }
        });
    });

    zip.generateAsync({ type: 'blob' }).then(function (blob) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = courseName + '.zip';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-file-arrow-down"></i> Download ZIP';
    });
}
