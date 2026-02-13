/* =========================================================================
   AlphaLearn – Goals Page
   ========================================================================= */

const THEMES = ['teal', 'purple', 'pink', 'orange'];
const NATIVE = ['timeback dash', 'alpha timeback', 'alphalearn', 'timeback'];
const TBG    = { teal: 'card-theme-teal', purple: 'card-theme-purple', pink: 'card-theme-pink', orange: 'card-theme-orange' };

/* ---- Helpers ---------------------------------------------------------- */

/* Per-app images and icon overrides */
const APP_IMAGES = {
    gumpp:'/img/apps/egumpp.png?v=2', runestone:'/img/apps/runestone.png?v=2',
    newsela:'/img/apps/newsela.png?v=2', khan:'/img/apps/khan.png?v=2',
    readtheory:'/img/apps/readtheory.png?v=2', commonlit:'/img/apps/commonlit.png?v=2',
    knewton:'/img/apps/knewton.png?v=2', alta:'/img/apps/knewton.png?v=2',
    lalilo:'/img/apps/lalilo.png?v=2', rocketmath:'/img/apps/rocketmath.png?v=2',
    zearn:'/img/apps/zearn.png?v=2', renaissance:'/img/apps/renaissance.png?v=2',
    starreading:'/img/apps/renaissance.png?v=2', starmath:'/img/apps/renaissance.png?v=2',
    powerpath:'/img/apps/powerpath.png?v=2',
};
const APP_ICON_MAP = {
    gumpp:'fa-book-open', runestone:'fa-laptop-code', newsela:'fa-book-open-reader',
    khan:'fa-calculator', readtheory:'fa-book-open-reader', commonlit:'fa-book-open-reader',
    knewton:'fa-calculator', alta:'fa-calculator', lalilo:'fa-book-open-reader',
    rocketmath:'fa-calculator', zearn:'fa-calculator', renaissance:'fa-graduation-cap',
    starreading:'fa-book-open-reader', starmath:'fa-calculator', powerpath:'fa-calculator',
};
const SUBJ_IMAGES = {
    math:'/img/subjects/math.png', science:'/img/subjects/science.png',
    language:'/img/subjects/language.png', reading:'/img/subjects/reading.png',
    geography:'/img/subjects/geography.png', biology:'/img/subjects/biology.png',
    tech:'/img/subjects/tech.png', default:'/img/subjects/default.png',
};

function matchApp(s) {
    const a = (s || '').toLowerCase().replace(/[\s_-]/g, '');
    if (!a) return null;
    const keys = Object.keys(APP_IMAGES).sort((a, b) => b.length - a.length);
    for (const k of keys) { if (a.includes(k)) return k; }
    return null;
}

function ic(t, appName) {
    const app = matchApp(appName) || matchApp(t);
    if (app && APP_ICON_MAP[app]) return APP_ICON_MAP[app];
    t = (t || '').toLowerCase();
    if (t.includes('math') || t.includes('algebra'))                        return 'fa-calculator';
    if (t.includes('chem') || t.includes('physics'))                        return 'fa-atom';
    if (t.includes('bio'))                                                  return 'fa-dna';
    if (t.includes('history') || t.includes('social') || t.includes('geo')) return 'fa-globe-americas';
    if (t.includes('read') || t.includes('ela') || t.includes('english'))   return 'fa-book-open-reader';
    if (t.includes('lang') || t.includes('composition') || t.includes('writing')) return 'fa-book-open';
    if (t.includes('code') || t.includes('tech'))                           return 'fa-laptop-code';
    return 'fa-graduation-cap';
}

function getCardImage(t, appName) {
    const app = matchApp(appName) || matchApp(t);
    if (app && APP_IMAGES[app]) return APP_IMAGES[app];
    t = (t || '').toLowerCase();
    if (t.includes('math') || t.includes('algebra') || t.includes('calculus')) return SUBJ_IMAGES.math;
    if (t.includes('chem') || t.includes('physics'))       return SUBJ_IMAGES.science;
    if (t.includes('bio'))                                  return SUBJ_IMAGES.biology;
    if (t.includes('read') || t.includes('ela') || t.includes('english')) return SUBJ_IMAGES.reading;
    if (t.includes('lang') || t.includes('composition') || t.includes('writing')) return SUBJ_IMAGES.language;
    if (t.includes('geo') || t.includes('history') || t.includes('social')) return SUBJ_IMAGES.geography;
    if (t.includes('code') || t.includes('tech'))          return SUBJ_IMAGES.tech;
    return SUBJ_IMAGES.default;
}

function isAP(t) { return /\bAP\b/.test((t || '').trim()); }
function isTimeback(c) {
    const a = (c.appName || '').toLowerCase().trim();
    if (!a) return true;
    if (NATIVE.some(n => a.includes(n) || n.includes(a))) return true;
    if (/^pp/i.test(a) || a.includes('powerpath')) return true;
    return false;
}
function isLesson(c) { return isAP(c.title) && isTimeback(c); }

/* ---- State ------------------------------------------------------------ */

let ALL = [], XP = {}, MASTERED = {}, GOALS = {};
let currentUserId = '';

/* ---- API-backed goal storage ------------------------------------------ */

async function apiSaveGoal(enrollmentId, goalData) {
    try {
        const resp = await fetch('/api/goals', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ userId: currentUserId, enrollmentId, ...goalData }),
        });
        const data = await resp.json();
        if (data.goals) GOALS = data.goals;
        return !!data.ok;
    } catch (e) {
        console.error('[AlphaLearn] Goal save failed:', e);
        return false;
    }
}

/* ---- UI helpers ------------------------------------------------------- */

function toast(m) {
    const e = document.getElementById('toast');
    e.textContent = m;
    e.classList.add('show');
    setTimeout(() => e.classList.remove('show'), 2500);
}

function fmtD(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function fmtNice(s) {
    return new Date(s + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/* ---- Holidays (US school calendar) ------------------------------------ */

function holidays(y) {
    const h = [];

    // Labor Day — 1st Monday of September
    const s1 = new Date(y, 8, 1);
    h.push(fmtD(new Date(y, 8, 1 + ((8 - s1.getDay()) % 7))));

    // Veterans Day — Nov 11
    h.push(`${y}-11-11`);

    // Thanksgiving — 4th Thursday of November + Friday
    const n1 = new Date(y, 10, 1);
    const th = new Date(y, 10, 1 + ((11 - n1.getDay()) % 7) + 21);
    h.push(fmtD(th));
    const tf = new Date(th); tf.setDate(tf.getDate() + 1);
    h.push(fmtD(tf));

    // Winter Break — Dec 23-31 + Jan 1-3
    for (let d = 23; d <= 31; d++) h.push(`${y}-12-${String(d).padStart(2, '0')}`);
    for (let d = 1; d <= 3; d++)   h.push(`${y + 1}-01-${String(d).padStart(2, '0')}`);

    // MLK Day — 3rd Monday of January
    const j1 = new Date(y + 1, 0, 1);
    h.push(fmtD(new Date(y + 1, 0, 1 + ((8 - j1.getDay()) % 7) + 14)));

    // Presidents Day — 3rd Monday of February
    const f1 = new Date(y + 1, 1, 1);
    h.push(fmtD(new Date(y + 1, 1, 1 + ((8 - f1.getDay()) % 7) + 14)));

    // Spring Break — 5 days starting 3rd Monday of March
    const m1 = new Date(y + 1, 2, 1);
    const sb = new Date(y + 1, 2, 1 + ((8 - m1.getDay()) % 7) + 14);
    for (let i = 0; i < 5; i++) {
        const dd = new Date(sb); dd.setDate(dd.getDate() + i);
        h.push(fmtD(dd));
    }

    // Memorial Day — last Monday of May
    const may31 = new Date(y + 1, 4, 31);
    h.push(fmtD(new Date(y + 1, 4, 31 - ((may31.getDay() + 6) % 7))));

    return new Set(h);
}

/* ---- Day counting ----------------------------------------------------- */

function cntDays(end, excl) {
    const t = new Date(); t.setHours(0, 0, 0, 0);
    const e = new Date(end + 'T00:00:00');
    if (e <= t) return { total: 0, school: 0 };

    // Build holiday set spanning from last year through end year
    const hs = new Set();
    if (excl) {
        for (let y = t.getFullYear() - 1; y <= e.getFullYear(); y++) {
            for (const h of holidays(y)) hs.add(h);
        }
    }

    let tot = 0, sch = 0;
    const c = new Date(t); c.setDate(c.getDate() + 1);
    while (c <= e) {
        tot++;
        const dow = c.getDay();
        if (excl) {
            if (dow !== 0 && dow !== 6 && !hs.has(fmtD(c))) sch++;
        } else {
            sch++;
        }
        c.setDate(c.getDate() + 1);
    }
    return { total: tot, school: sch };
}

/* ===================================================================
   AP LESSON CARD — clean layout: progress up top, compact form below
   =================================================================== */

function lessonCard(c, i) {
    const g   = GOALS[c._enrollmentId] || {};
    const has = !!g.endDate;

    const done      = MASTERED[i] || 0;
    const total     = c.totalLessons || g.target || 0;
    const remaining = Math.max(total - done, 0);
    const pct       = total > 0 ? Math.min((done / total) * 100, 100) : 0;

    // Pace line
    let paceHtml = '';
    if (has && total > 0) {
        const excl = g.excludeNonSchoolDays !== false;
        const d    = cntDays(g.endDate, excl);
        const daily = remaining > 0 && d.school > 0 ? Math.ceil(remaining / d.school) : 0;
        const dayT = excl ? 'school day' : 'day';

        if (remaining <= 0) {
            paceHtml = '<div class="gc-pace gc-pace-done"><i class="fa-solid fa-circle-check"></i> Complete!</div>';
        } else if (d.school <= 0) {
            paceHtml = '<div class="gc-pace gc-pace-overdue"><i class="fa-solid fa-triangle-exclamation"></i> Past due</div>';
        } else {
            paceHtml = `<div class="gc-pace"><i class="fa-solid fa-bolt"></i>${daily} lessons/${dayT} &middot; ${d.school} days left</div>`;
        }
    }

    return `<div class="gc" data-i="${i}" data-eid="${c._enrollmentId}">
        <div class="gc-img"><img src="${getCardImage(c.title, c.appName)}" alt="${c.title}" loading="lazy"></div>
        <div class="gc-b">
            <div class="gc-name">${c.title}</div>
            <div class="gc-detail">
                <div class="gc-detail-big">${done} <span>/ ${total || '?'} lessons</span></div>
            </div>
            <div class="gc-bar"><div class="gc-bar-fill" style="width:${pct.toFixed(1)}%"></div></div>
            ${paceHtml}
            <div class="gc-form">
                <div class="gc-fld"><label class="gc-lbl">Finish by</label><input type="date" class="gc-inp gl-date" value="${g.endDate || ''}" min="${fmtD(new Date())}" onchange="previewL(${i})"></div>
                <div class="gc-fld gc-fld-chk"><label class="gc-chk"><input type="checkbox" class="gl-sch" ${(g.excludeNonSchoolDays !== false) ? 'checked' : ''} onchange="previewL(${i})"> School days</label></div>
            </div>
            <div class="gc-preview" id="pv-${i}"><i class="fa-solid fa-calculator"></i><span id="pvt-${i}"></span></div>
            <div class="gc-actions">
                <button class="btn-c" onclick="saveL(${i})">${has ? 'Update' : 'Set Goal'}</button>
                ${has ? `<button class="btn-x" onclick="clearG(${i})">Clear</button>` : ''}
            </div>
        </div></div>`;
}

/* ===================================================================
   XP CARD — same clean layout
   =================================================================== */

function xpCard(c, i) {
    const g      = GOALS[c._enrollmentId] || {};
    const dailyG = g.dailyXp || c.dailyXpGoal || 0;
    const has    = dailyG > 0;
    const xpE    = Math.round(XP[i] || 0);

    return `<div class="gc" data-i="${i}" data-eid="${c._enrollmentId}">
        <div class="gc-img"><img src="${getCardImage(c.title, c.appName)}" alt="${c.title}" loading="lazy"></div>
        <div class="gc-b">
            <div class="gc-name">${c.title}</div>
            <div class="gc-detail" style="margin-bottom:14px">
                <div class="gc-detail-big">${xpE.toLocaleString()} <span>XP earned this year</span></div>
            </div>
            <div class="gc-form">
                <div class="gc-fld"><label class="gc-lbl">Daily XP Goal</label><input type="number" class="gc-inp gx-tgt" min="1" value="${dailyG || ''}" placeholder="e.g. 30"></div>
            </div>
            <div class="gc-actions">
                <button class="btn-c" onclick="saveXP(${i})">${has ? 'Update' : 'Set Goal'}</button>
                ${has ? `<button class="btn-x" onclick="clearG(${i})">Clear</button>` : ''}
            </div>
        </div></div>`;
}

/* ===================================================================
   PREVIEW (live pace calculation as user types — inline in form area)
   =================================================================== */

function previewL(i) {
    const card = document.querySelector(`.gc[data-i="${i}"]`);
    const tgt  = ALL[i].totalLessons || (GOALS[ALL[i]._enrollmentId] || {}).target || 0;
    const dt   = card.querySelector('.gl-date').value;
    const excl = card.querySelector('.gl-sch').checked;
    const pv   = document.getElementById('pv-' + i);
    const pvt  = document.getElementById('pvt-' + i);
    const done = MASTERED[i] || 0;

    if (!tgt || !dt) { pv.classList.remove('show'); return; }

    const rem  = Math.max(tgt - done, 0);
    const d    = cntDays(dt, excl);
    const dayT = excl ? 'school day' : 'day';

    if (d.school <= 0)    pvt.textContent = 'That date has already passed.';
    else if (rem <= 0)    pvt.textContent = 'Already completed!';
    else                  pvt.innerHTML = `${Math.ceil(rem / d.school)} lessons/${dayT} &middot; ${d.school} ${dayT}s left`;
    pv.classList.add('show');
}

/* previewXP removed — XP courses only have a target, no date/pace */

/* ===================================================================
   SAVE / CLEAR
   =================================================================== */

async function saveL(i) {
    const card = document.querySelector(`.gc[data-i="${i}"]`);
    const tgt  = ALL[i].totalLessons || (GOALS[ALL[i]._enrollmentId] || {}).target || 0;
    const dt   = card.querySelector('.gl-date').value;
    if (!dt)  { toast('Pick an end date.'); return; }
    const excl = card.querySelector('.gl-sch').checked;
    const eid  = card.dataset.eid;

    const btn = card.querySelector('.btn-c');
    btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving…';

    const ok = await apiSaveGoal(eid, { target: tgt, endDate: dt, excludeNonSchoolDays: excl });
    btn.disabled = false;
    toast(ok ? 'Goal saved!' : 'Failed to save goal.');
    render();
}

async function saveXP(i) {
    const card = document.querySelector(`.gc[data-i="${i}"]`);
    const daily = parseInt(card.querySelector('.gx-tgt').value) || 0;
    if (!daily) { toast('Enter a daily XP goal.'); return; }
    const eid  = card.dataset.eid;

    const btn = card.querySelector('.btn-c');
    btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving…';

    const ok = await apiSaveGoal(eid, { dailyXp: daily });
    btn.disabled = false;
    toast(ok ? 'Goal saved!' : 'Failed to save goal.');
    render();
}

async function clearG(i) {
    const card = document.querySelector(`.gc[data-i="${i}"]`);
    const eid  = card.dataset.eid;

    const ok = await apiSaveGoal(eid, { clear: true });
    toast(ok ? 'Goal cleared.' : 'Failed to clear goal.');
    render();
}

/* ===================================================================
   RENDER
   =================================================================== */

function render() {
    const lc = [], xc = [];
    ALL.forEach((c, i) => {
        if (isLesson(c)) lc.push({ c, i });
        else xc.push({ c, i });
    });
    document.getElementById('lg').innerHTML = lc.length
        ? lc.map(({ c, i }) => lessonCard(c, i)).join('')
        : '<div class="empty-s">No courses with lesson data found.</div>';
    document.getElementById('xg').innerHTML = xc.length
        ? xc.map(({ c, i }) => xpCard(c, i)).join('')
        : '<div class="empty-s">No XP courses found.</div>';
}

/* ===================================================================
   DATA LOADING
   =================================================================== */

document.addEventListener('DOMContentLoaded', async function () {
    const email = localStorage.getItem('alphalearn_email') || '';
    if (!email) {
        document.getElementById('lg').innerHTML = '<div class="empty-s">Please <a href="/login" style="color:var(--color-primary)">sign in</a>.</div>';
        document.getElementById('xg').innerHTML = '';
        return;
    }

    try {
        /* 1. Fire user-lookup AND enrollments in parallel if we have a cached userId */
        const cachedUid = localStorage.getItem('alphalearn_userId') || '';
        const luPromise = fetch(`/api/user-lookup?email=${encodeURIComponent(email)}`).then(r => r.json());
        const earlyEnroll = cachedUid
            ? fetch(`/api/enrollments?userId=${cachedUid}`).then(r => r.json())
            : null;

        const lu = await luPromise;
        if (!lu.user || !lu.user.sourcedId) {
            document.getElementById('lg').innerHTML = '<div class="empty-s">Account not found.</div>';
            document.getElementById('xg').innerHTML = '';
            return;
        }
        const uid = lu.user.sourcedId;
        currentUserId = uid;
        localStorage.setItem('alphalearn_userId', uid);

        /* 2. Use pre-fetched enrollments or fetch now */
        let ed;
        if (earlyEnroll && uid === cachedUid) {
            ed = await earlyEnroll;
        } else {
            ed = await (await fetch(`/api/enrollments?userId=${uid}`)).json();
        }
        const raw = ed.data || ed.enrollments || ed.courses || (Array.isArray(ed) ? ed : []);
        const now = new Date();
        const courses = [];

        for (const e of raw) {
            const co  = e.course || {};
            const cm  = co.metadata || {};
            const gl  = (e.metadata && e.metadata.goals) || {};
            const mt  = (e.metadata && e.metadata.metrics) || {};
            const cmt = cm.metrics || {};
            const ti  = (co.title || '').trim();
            const su  = co.subjects || [];
            const eD  = e.endDate ? new Date(e.endDate) : null;

            // Skip expired
            if (eD && eD < now) continue;
            // Skip junk rows
            if (!ti || ti.startsWith('Manual XP') || ti.includes('Hole-Filling') || !su.length) continue;
            // Skip mastery tests
            if (mt.courseType === 'mastery_test' || mt.courseType === 'mastery-test' || mt.courseType === 'masteryTest'
                || (ti.toLowerCase().includes('mastery') && ti.toLowerCase().includes('test'))) continue;

            const pA = co.primaryApp || {};
            const an = (typeof pA === 'object' ? pA.name : '') || cm.primaryApp || cm.app || '';
            const totalLessons = mt.totalLessons || cmt.totalLessons || cm.totalLessons
                || co.totalLessons || mt.totalUnits || cmt.totalUnits || cm.totalUnits || co.totalUnits || 0;
            const totalXp      = mt.totalXp || cmt.totalXp || cm.totalXp || co.totalXp || 0;

            const vendorKey = cm.primaryApp || cm.app || cm.vendor
                || (typeof pA === 'object' && pA.id ? pA.id : '') || '';

            courses.push({
                title: ti,
                subject: su[0] || '',
                appName: [an, vendorKey].filter(Boolean).join(' '),
                totalXp,
                totalLessons,
                dailyXpGoal: gl.dailyXp || 0,
                _goalKey: e.id || e.sourcedId || co.id || co.sourcedId || ti,
                _enrollmentId: e.id || e.sourcedId || '',
                _raw: e,
                _course: co,
            });
        }

        ALL = courses;

        /* 3. Fetch per-enrollment analytics for accurate per-course data */
        const soy = new Date(now.getFullYear(), 7, 1);
        if (soy > now) soy.setFullYear(soy.getFullYear() - 1);
        soy.setHours(0, 0, 0, 0);
        const endDay = new Date(now); endDay.setHours(23, 59, 59, 999);
        const startParam = soy.toISOString();
        const endParam   = endDay.toISOString();
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || '';

        // Fetch goals from KV API in parallel with analytics
        const goalsPromise = fetch(`/api/goals?userId=${encodeURIComponent(uid)}`)
            .then(r => r.json())
            .then(d => { GOALS = d.goals || {}; })
            .catch(e => console.warn('[AlphaLearn] Goals unavailable:', e.message));

        // Fire per-enrollment analytics calls in parallel for every course with an enrollment ID
        const analyticsPromises = ALL.map((c, i) => {
            if (!c._enrollmentId) return Promise.resolve(null);
            return fetch(`/api/enrollment-analytics?enrollmentId=${encodeURIComponent(c._enrollmentId)}&startDate=${startParam}&endDate=${endParam}&timezone=${encodeURIComponent(tz)}`)
                .then(r => r.json())
                .then(data => ({ i, data }))
                .catch(() => null);
        });

        try {
            const [results] = await Promise.all([Promise.all(analyticsPromises), goalsPromise]);
            const cache = {};

            for (const r of results) {
                if (!r || !r.data) continue;
                const { i, data } = r;
                const facts      = data.facts || {};
                const factsByApp = data.factsByApp || {};

                let totalXp = 0, totalMastered = 0;

                // Sum from facts (subject-level per day)
                for (const dayFacts of Object.values(facts)) {
                    for (const info of Object.values(dayFacts)) {
                        const am = info.activityMetrics || {};
                        totalXp      += am.xpEarned || 0;
                        totalMastered += am.masteredUnits || am.lessonsCompleted || am.completedLessons
                            || am.unitsCompleted || am.completedUnits || 0;
                    }
                }

                // Also sum from factsByApp for completeness
                let appXp = 0, appMastered = 0;
                for (const dayData of Object.values(factsByApp)) {
                    for (const apps of Object.values(dayData)) {
                        for (const info of Object.values(apps)) {
                            const am = info.activityMetrics || {};
                            appXp      += am.xpEarned || 0;
                            appMastered += am.masteredUnits || am.lessonsCompleted || am.completedLessons
                                || am.unitsCompleted || am.completedUnits || 0;
                        }
                    }
                }

                // Use whichever source has more data
                XP[i]       = Math.max(totalXp, appXp);
                MASTERED[i] = Math.max(totalMastered, appMastered);

                // Backfill totalLessons from analytics if enrollment didn't have it
                if (!ALL[i].totalLessons) {
                    const enr = data.enrollment || data.course || {};
                    const eMeta = enr.metadata || {};
                    const eMetrics = eMeta.metrics || {};
                    ALL[i].totalLessons = enr.totalLessons || enr.totalUnits
                        || eMetrics.totalLessons || eMetrics.totalUnits
                        || eMeta.totalLessons || eMeta.totalUnits || 0;
                }

                // Build cache for dashboard
                if (ALL[i]._enrollmentId) {
                    cache[ALL[i]._enrollmentId] = {
                        mastered: MASTERED[i],
                        xp: XP[i],
                        totalLessons: ALL[i].totalLessons || 0,
                        goalKey: ALL[i]._goalKey,
                    };
                }
            }

            // Cache mastered data for dashboard to use
            localStorage.setItem('alphalearn_mastered_cache', JSON.stringify({
                data: cache,
                updatedAt: new Date().toISOString(),
            }));
        } catch (e) {
            console.warn('[AlphaLearn] Per-enrollment analytics:', e.message);
        }

        /* 4. For AP lesson courses still missing totalLessons, fetch from course API */
        const missingTotal = ALL.map((c, i) => {
            if (!isLesson(c) || c.totalLessons > 0) return null;
            const courseId = (c._course && (c._course.sourcedId || c._course.id)) || '';
            if (!courseId) return null;
            return fetch(`/api/course-info?courseId=${encodeURIComponent(courseId)}`)
                .then(r => r.json())
                .then(d => { if (d.totalLessons) ALL[i].totalLessons = d.totalLessons; })
                .catch(() => null);
        }).filter(Boolean);
        if (missingTotal.length) await Promise.all(missingTotal);

        render();

    } catch (e) {
        document.getElementById('lg').innerHTML = '<div class="empty-s">Unable to load data.</div>';
        document.getElementById('xg').innerHTML = '';
        console.error(e);
    }
});
