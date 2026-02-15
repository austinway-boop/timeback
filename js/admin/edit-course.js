/* ====================================================================
   Edit Course – Tree Editor + Activity Generator
   ====================================================================
   Exposes window.initEditCourse(courseId, courseObj) and
   window.cleanupEditCourse() for integration with course-editor.js.
   ==================================================================== */
(function () {
    'use strict';

    /* ---- State -------------------------------------------------------- */
    var courseId = null;
    var courseObj = null;
    var units = [];
    var saveTimer = null;
    var sortableInstances = [];
    var currentModalLessonId = null;
    var currentModalUnitId = null;
    var modalImages = [];
    var generatedHtml = '';
    var generatedActivityId = '';

    /* ---- Helpers ------------------------------------------------------- */
    function esc(str) {
        if (str == null) return '';
        var d = document.createElement('div');
        d.textContent = String(str);
        return d.innerHTML;
    }

    function uid() {
        return 'ec_' + Math.random().toString(36).substr(2, 9) + Date.now().toString(36);
    }

    function activityIcon(type) {
        switch (type) {
            case 'video': return 'fa-play';
            case 'article': return 'fa-file-lines';
            case 'quiz': return 'fa-question-circle';
            case 'custom': return 'fa-wand-magic-sparkles';
            default: return 'fa-circle';
        }
    }

    function activityIconsForLesson(activities) {
        var seen = {};
        var html = '';
        (activities || []).forEach(function (a) {
            if (!seen[a.type]) {
                seen[a.type] = true;
                html += '<i class="fa-solid ' + activityIcon(a.type) + '" title="' + esc(a.type) + '"></i>';
            }
        });
        return html;
    }

    /* ---- Save / Load -------------------------------------------------- */
    function scheduleSave() {
        clearTimeout(saveTimer);
        setSaveStatus('saving', 'Saving...');
        saveTimer = setTimeout(doSave, 800);
    }

    function doSave() {
        fetch('/api/edit-course-save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ courseId: courseId, units: units }),
        }).then(function (r) { return r.json(); }).then(function (d) {
            if (d.success) setSaveStatus('saved', 'All changes saved');
            else setSaveStatus('error', 'Save failed');
        }).catch(function () {
            setSaveStatus('error', 'Save failed');
        });
    }

    function setSaveStatus(cls, text) {
        var el = document.getElementById('ec-save-status');
        if (el) {
            el.className = 'ec-save-status ' + cls;
            el.textContent = text;
        }
    }

    async function loadCourseData() {
        var container = document.getElementById('edit-course-view');
        container.innerHTML =
            '<div class="ec-loading"><div class="ce-progress-spinner"></div><br>Loading course structure...</div>';

        try {
            var resp = await fetch('/api/edit-course-load?courseId=' + encodeURIComponent(courseId));
            var data = await resp.json();
            if (data.error && !data.units) {
                container.innerHTML =
                    '<div class="ec-empty"><i class="fa-solid fa-triangle-exclamation"></i><p>' + esc(data.error) + '</p></div>';
                return;
            }
            units = data.units || [];
            renderTree();
        } catch (e) {
            container.innerHTML =
                '<div class="ec-empty"><i class="fa-solid fa-triangle-exclamation"></i><p>Failed to load: ' + esc(e.message) + '</p></div>';
        }
    }

    /* ---- Render Tree -------------------------------------------------- */
    function renderTree() {
        destroySortables();
        var container = document.getElementById('edit-course-view');
        var html = '<div class="ec-container">';

        // Toolbar
        html += '<div class="ec-toolbar">' +
            '<div class="ec-toolbar-left">' +
                '<button class="ec-back-btn" id="ec-back-btn"><i class="fa-solid fa-arrow-left"></i> Back to actions</button>' +
                '<span style="font-size:1rem; font-weight:700; color:var(--color-text);">' +
                    esc((courseObj && courseObj.title) || 'Edit Course') +
                '</span>' +
            '</div>' +
            '<div class="ec-toolbar-right">' +
                '<span class="ec-save-status saved" id="ec-save-status">All changes saved</span>' +
            '</div>' +
        '</div>';

        // Units list
        html += '<div id="ec-units-list">';
        if (units.length === 0) {
            html += '<div class="ec-empty"><i class="fa-solid fa-folder-open"></i><p>No units found. Add one below.</p></div>';
        } else {
            units.forEach(function (unit, uIdx) {
                html += renderUnit(unit, uIdx);
            });
        }
        html += '</div>';

        // Add unit button
        html += '<button class="ec-add-unit-btn" id="ec-add-unit-btn"><i class="fa-solid fa-plus"></i> Add Unit</button>';

        html += '</div>';
        container.innerHTML = html;

        // Event listeners
        document.getElementById('ec-back-btn').addEventListener('click', backToActions);
        document.getElementById('ec-add-unit-btn').addEventListener('click', addUnit);

        bindUnitEvents();
        initSortables();
    }

    function renderUnit(unit, uIdx) {
        var lessonCount = (unit.lessons || []).length;
        var html = '<div class="ec-unit" data-unit-idx="' + uIdx + '">';

        // Header
        html += '<div class="ec-unit-header">' +
            '<span class="ec-drag-handle ec-unit-drag" title="Drag to reorder"><i class="fa-solid fa-grip-vertical"></i></span>' +
            '<i class="fa-solid fa-chevron-right ec-unit-chevron"></i>' +
            '<span class="ec-unit-title">' + esc(unit.title) + '</span>' +
            '<span class="ec-unit-badge">' + lessonCount + ' lesson' + (lessonCount !== 1 ? 's' : '') + '</span>' +
            '<span class="ec-unit-actions">' +
                '<button class="ec-icon-btn ec-edit-unit-btn" title="Rename"><i class="fa-solid fa-pen"></i></button>' +
                '<button class="ec-icon-btn danger ec-delete-unit-btn" title="Remove unit"><i class="fa-solid fa-trash"></i></button>' +
            '</span>' +
        '</div>';

        // Body (lessons)
        html += '<div class="ec-unit-body">';
        html += '<div class="ec-lessons-list" data-unit-idx="' + uIdx + '">';
        (unit.lessons || []).forEach(function (lesson, lIdx) {
            html += renderLesson(lesson, uIdx, lIdx);
        });
        html += '</div>';
        html += '<button class="ec-add-btn ec-add-lesson-btn" data-unit-idx="' + uIdx + '"><i class="fa-solid fa-plus"></i> Add Lesson</button>';
        html += '</div>';

        html += '</div>';
        return html;
    }

    function renderLesson(lesson, uIdx, lIdx) {
        var acts = lesson.activities || [];
        var html = '<div class="ec-lesson" data-unit-idx="' + uIdx + '" data-lesson-idx="' + lIdx + '">';

        // Header
        html += '<div class="ec-lesson-header">' +
            '<span class="ec-drag-handle ec-lesson-drag" title="Drag to reorder"><i class="fa-solid fa-grip-vertical"></i></span>' +
            '<i class="fa-solid fa-chevron-right ec-lesson-chevron"></i>' +
            '<span class="ec-lesson-title">' + esc(lesson.title) + '</span>' +
            '<span class="ec-lesson-icons">' + activityIconsForLesson(acts) + '</span>' +
            '<span class="ec-lesson-actions">' +
                '<button class="ec-icon-btn ec-edit-lesson-btn" title="Rename"><i class="fa-solid fa-pen"></i></button>' +
                '<button class="ec-icon-btn danger ec-delete-lesson-btn" title="Remove lesson"><i class="fa-solid fa-trash"></i></button>' +
            '</span>' +
        '</div>';

        // Body (activities)
        html += '<div class="ec-lesson-body">';
        html += '<div class="ec-activities-list" data-unit-idx="' + uIdx + '" data-lesson-idx="' + lIdx + '">';
        acts.forEach(function (act, aIdx) {
            html += renderActivity(act, uIdx, lIdx, aIdx);
        });
        html += '</div>';
        html += '<button class="ec-add-btn ec-add-activity-btn" data-unit-idx="' + uIdx + '" data-lesson-idx="' + lIdx + '"><i class="fa-solid fa-wand-magic-sparkles"></i> Generate Activity</button>';
        html += '</div>';

        html += '</div>';
        return html;
    }

    function renderActivity(act, uIdx, lIdx, aIdx) {
        var typeClass = act.type || 'other';
        return '<div class="ec-activity" data-unit-idx="' + uIdx + '" data-lesson-idx="' + lIdx + '" data-activity-idx="' + aIdx + '">' +
            '<span class="ec-drag-handle ec-activity-drag" title="Drag to reorder"><i class="fa-solid fa-grip-vertical"></i></span>' +
            '<span class="ec-activity-icon ' + typeClass + '"><i class="fa-solid ' + activityIcon(act.type) + '"></i></span>' +
            '<span class="ec-activity-title">' + esc(act.title || 'Untitled') + '</span>' +
            '<span class="ec-activity-type">' + esc(act.type) + '</span>' +
            '<span class="ec-activity-actions">' +
                (act.sourceType === 'custom' ? '<button class="ec-icon-btn ec-preview-activity-btn" title="Preview"><i class="fa-solid fa-eye"></i></button>' : '') +
                '<button class="ec-icon-btn danger ec-delete-activity-btn" title="Remove"><i class="fa-solid fa-trash"></i></button>' +
            '</span>' +
        '</div>';
    }

    /* ---- Event Binding ------------------------------------------------ */
    function bindUnitEvents() {
        // Unit header click (expand/collapse)
        document.querySelectorAll('.ec-unit-header').forEach(function (h) {
            h.addEventListener('click', function (e) {
                if (e.target.closest('.ec-icon-btn') || e.target.closest('.ec-drag-handle')) return;
                this.closest('.ec-unit').classList.toggle('expanded');
            });
        });

        // Lesson header click (expand/collapse)
        document.querySelectorAll('.ec-lesson-header').forEach(function (h) {
            h.addEventListener('click', function (e) {
                if (e.target.closest('.ec-icon-btn') || e.target.closest('.ec-drag-handle')) return;
                this.closest('.ec-lesson').classList.toggle('expanded');
            });
        });

        // Edit unit name
        document.querySelectorAll('.ec-edit-unit-btn').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var unitEl = this.closest('.ec-unit');
                var uIdx = parseInt(unitEl.getAttribute('data-unit-idx'));
                startInlineEdit(unitEl.querySelector('.ec-unit-title'), units[uIdx].title, function (newVal) {
                    units[uIdx].title = newVal;
                    scheduleSave();
                    renderTree();
                });
            });
        });

        // Delete unit
        document.querySelectorAll('.ec-delete-unit-btn').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var unitEl = this.closest('.ec-unit');
                var uIdx = parseInt(unitEl.getAttribute('data-unit-idx'));
                if (confirm('Delete "' + units[uIdx].title + '" and all its lessons?')) {
                    units.splice(uIdx, 1);
                    scheduleSave();
                    renderTree();
                }
            });
        });

        // Edit lesson name
        document.querySelectorAll('.ec-edit-lesson-btn').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var lessonEl = this.closest('.ec-lesson');
                var uIdx = parseInt(lessonEl.getAttribute('data-unit-idx'));
                var lIdx = parseInt(lessonEl.getAttribute('data-lesson-idx'));
                startInlineEdit(lessonEl.querySelector('.ec-lesson-title'), units[uIdx].lessons[lIdx].title, function (newVal) {
                    units[uIdx].lessons[lIdx].title = newVal;
                    scheduleSave();
                    renderTree();
                });
            });
        });

        // Delete lesson
        document.querySelectorAll('.ec-delete-lesson-btn').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var lessonEl = this.closest('.ec-lesson');
                var uIdx = parseInt(lessonEl.getAttribute('data-unit-idx'));
                var lIdx = parseInt(lessonEl.getAttribute('data-lesson-idx'));
                if (confirm('Delete "' + units[uIdx].lessons[lIdx].title + '"?')) {
                    units[uIdx].lessons.splice(lIdx, 1);
                    scheduleSave();
                    renderTree();
                }
            });
        });

        // Delete activity
        document.querySelectorAll('.ec-delete-activity-btn').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var actEl = this.closest('.ec-activity');
                var uIdx = parseInt(actEl.getAttribute('data-unit-idx'));
                var lIdx = parseInt(actEl.getAttribute('data-lesson-idx'));
                var aIdx = parseInt(actEl.getAttribute('data-activity-idx'));
                units[uIdx].lessons[lIdx].activities.splice(aIdx, 1);
                scheduleSave();
                renderTree();
            });
        });

        // Preview custom activity
        document.querySelectorAll('.ec-preview-activity-btn').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var actEl = this.closest('.ec-activity');
                var uIdx = parseInt(actEl.getAttribute('data-unit-idx'));
                var lIdx = parseInt(actEl.getAttribute('data-lesson-idx'));
                var aIdx = parseInt(actEl.getAttribute('data-activity-idx'));
                var act = units[uIdx].lessons[lIdx].activities[aIdx];
                if (act.activityId) {
                    previewExistingActivity(act.activityId);
                }
            });
        });

        // Add lesson buttons
        document.querySelectorAll('.ec-add-lesson-btn').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var uIdx = parseInt(this.getAttribute('data-unit-idx'));
                var newLesson = {
                    id: uid(),
                    title: 'New Lesson',
                    sortOrder: units[uIdx].lessons.length,
                    activities: [],
                };
                units[uIdx].lessons.push(newLesson);
                scheduleSave();
                renderTree();
                // Auto-expand the unit and start editing the new lesson name
                var unitEl = document.querySelector('.ec-unit[data-unit-idx="' + uIdx + '"]');
                if (unitEl && !unitEl.classList.contains('expanded')) unitEl.classList.add('expanded');
            });
        });

        // Add activity buttons (opens modal)
        document.querySelectorAll('.ec-add-activity-btn').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var uIdx = parseInt(this.getAttribute('data-unit-idx'));
                var lIdx = parseInt(this.getAttribute('data-lesson-idx'));
                openActivityModal(uIdx, lIdx);
            });
        });
    }

    /* ---- Inline Editing ----------------------------------------------- */
    function startInlineEdit(spanEl, currentValue, onSave) {
        var input = document.createElement('input');
        input.type = 'text';
        input.value = currentValue;
        spanEl.innerHTML = '';
        spanEl.appendChild(input);
        input.focus();
        input.select();

        function finish() {
            var val = input.value.trim();
            if (val && val !== currentValue) {
                onSave(val);
            } else {
                spanEl.textContent = currentValue;
            }
        }

        input.addEventListener('blur', finish);
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
            if (e.key === 'Escape') { input.value = currentValue; input.blur(); }
        });
    }

    /* ---- SortableJS Initialization ------------------------------------ */
    function destroySortables() {
        sortableInstances.forEach(function (s) {
            try { s.destroy(); } catch (e) {}
        });
        sortableInstances = [];
    }

    function initSortables() {
        if (typeof Sortable === 'undefined') return;

        // Units sortable
        var unitsList = document.getElementById('ec-units-list');
        if (unitsList) {
            sortableInstances.push(Sortable.create(unitsList, {
                animation: 200,
                handle: '.ec-unit-drag',
                draggable: '.ec-unit',
                ghostClass: 'sortable-ghost',
                dragClass: 'sortable-drag',
                onEnd: function (evt) {
                    var moved = units.splice(evt.oldIndex, 1)[0];
                    units.splice(evt.newIndex, 0, moved);
                    scheduleSave();
                    renderTree();
                },
            }));
        }

        // Lessons sortable (per unit)
        document.querySelectorAll('.ec-lessons-list').forEach(function (list) {
            var uIdx = parseInt(list.getAttribute('data-unit-idx'));
            sortableInstances.push(Sortable.create(list, {
                animation: 200,
                handle: '.ec-lesson-drag',
                draggable: '.ec-lesson',
                group: 'lessons',
                ghostClass: 'sortable-ghost',
                onEnd: function (evt) {
                    var fromUIdx = parseInt(evt.from.getAttribute('data-unit-idx'));
                    var toUIdx = parseInt(evt.to.getAttribute('data-unit-idx'));
                    var lesson = units[fromUIdx].lessons.splice(evt.oldIndex, 1)[0];
                    units[toUIdx].lessons.splice(evt.newIndex, 0, lesson);
                    scheduleSave();
                    renderTree();
                },
            }));
        });

        // Activities sortable (per lesson)
        document.querySelectorAll('.ec-activities-list').forEach(function (list) {
            sortableInstances.push(Sortable.create(list, {
                animation: 200,
                handle: '.ec-activity-drag',
                draggable: '.ec-activity',
                group: 'activities',
                ghostClass: 'sortable-ghost',
                onEnd: function (evt) {
                    var fromUIdx = parseInt(evt.from.getAttribute('data-unit-idx'));
                    var fromLIdx = parseInt(evt.from.getAttribute('data-lesson-idx'));
                    var toUIdx = parseInt(evt.to.getAttribute('data-unit-idx'));
                    var toLIdx = parseInt(evt.to.getAttribute('data-lesson-idx'));
                    var act = units[fromUIdx].lessons[fromLIdx].activities.splice(evt.oldIndex, 1)[0];
                    units[toUIdx].lessons[toLIdx].activities.splice(evt.newIndex, 0, act);
                    scheduleSave();
                    renderTree();
                },
            }));
        });
    }

    /* ---- Add Unit ----------------------------------------------------- */
    function addUnit() {
        units.push({
            id: uid(),
            title: 'New Unit',
            sortOrder: units.length,
            lessons: [],
        });
        scheduleSave();
        renderTree();
    }

    /* ---- Back to Actions ---------------------------------------------- */
    function backToActions() {
        document.getElementById('edit-course-view').style.display = 'none';
        document.getElementById('course-actions').style.display = '';
    }

    /* ================================================================
       Activity Generator Modal
       ================================================================ */
    function openActivityModal(uIdx, lIdx) {
        currentModalUnitId = uIdx;
        currentModalLessonId = lIdx;
        modalImages = [];
        generatedHtml = '';
        generatedActivityId = '';

        var overlay = document.createElement('div');
        overlay.className = 'ec-modal-overlay';
        overlay.id = 'ec-activity-modal';

        overlay.innerHTML =
            '<div class="ec-modal">' +
                '<div class="ec-modal-header">' +
                    '<span class="ec-modal-title"><i class="fa-solid fa-wand-magic-sparkles" style="margin-right:8px; opacity:0.6;"></i>Generate Activity</span>' +
                    '<button class="ec-modal-close" id="ec-modal-close"><i class="fa-solid fa-xmark"></i></button>' +
                '</div>' +
                '<div class="ec-modal-body">' +
                    '<div class="ec-modal-input">' +
                        '<div class="ec-modal-label">Upload Images (optional)</div>' +
                        '<div class="ec-modal-sublabel">Upload maps, diagrams, charts, or any visual content for the activity</div>' +
                        '<div class="ec-upload-previews" id="ec-upload-previews"></div>' +
                        '<div class="ec-upload-zone" id="ec-upload-zone">' +
                            '<i class="fa-solid fa-cloud-arrow-up"></i>' +
                            '<span>Drop images here or click to browse</span>' +
                            '<input type="file" id="ec-file-input" accept="image/*" multiple>' +
                        '</div>' +
                        '<div class="ec-modal-label" style="margin-top:4px;">Describe the Activity</div>' +
                        '<div class="ec-modal-sublabel">Tell Claude what kind of activity to create and what it should test</div>' +
                        '<textarea class="ec-description-input" id="ec-description" placeholder="Example: Create a drag-and-drop activity where students must drag the correct country name over each region on the uploaded map. Include 8 regions."></textarea>' +
                        '<button class="ec-generate-btn" id="ec-generate-btn"><i class="fa-solid fa-wand-magic-sparkles"></i> Generate Activity</button>' +
                        '<div class="ec-generate-status" id="ec-generate-status" style="display:none;"></div>' +
                    '</div>' +
                    '<div class="ec-modal-preview">' +
                        '<div class="ec-preview-toolbar">' +
                            '<span class="ec-preview-toolbar-left">Preview</span>' +
                            '<div class="ec-preview-toolbar-right">' +
                                '<button class="ec-preview-btn" id="ec-reset-btn" disabled><i class="fa-solid fa-arrows-rotate"></i> Reset</button>' +
                                '<button class="ec-preview-btn" id="ec-regenerate-btn" disabled><i class="fa-solid fa-rotate"></i> Regenerate</button>' +
                            '</div>' +
                        '</div>' +
                        '<div class="ec-preview-frame-wrap" id="ec-preview-wrap">' +
                            '<div class="ec-preview-placeholder" id="ec-preview-placeholder">' +
                                '<i class="fa-solid fa-sparkles"></i>' +
                                '<span>Your generated activity will appear here</span>' +
                            '</div>' +
                        '</div>' +
                        '<div class="ec-name-row" id="ec-name-row" style="display:none;">' +
                            '<input type="text" class="ec-name-input" id="ec-activity-name" placeholder="Activity name (e.g., European Map Regions)">' +
                            '<button class="ec-preview-btn primary" id="ec-add-to-course-btn"><i class="fa-solid fa-plus"></i> Add to Course</button>' +
                        '</div>' +
                    '</div>' +
                '</div>' +
            '</div>';

        document.body.appendChild(overlay);
        bindModalEvents(overlay);
    }

    function bindModalEvents(overlay) {
        // Close
        document.getElementById('ec-modal-close').addEventListener('click', closeModal);
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) closeModal();
        });

        // File upload
        var fileInput = document.getElementById('ec-file-input');
        var uploadZone = document.getElementById('ec-upload-zone');

        fileInput.addEventListener('change', function () {
            handleFiles(this.files);
            this.value = '';
        });

        uploadZone.addEventListener('dragover', function (e) {
            e.preventDefault();
            this.classList.add('dragover');
        });
        uploadZone.addEventListener('dragleave', function () {
            this.classList.remove('dragover');
        });
        uploadZone.addEventListener('drop', function (e) {
            e.preventDefault();
            this.classList.remove('dragover');
            handleFiles(e.dataTransfer.files);
        });

        // Generate
        document.getElementById('ec-generate-btn').addEventListener('click', generateActivity);

        // Reset preview
        document.getElementById('ec-reset-btn').addEventListener('click', function () {
            if (generatedHtml) loadPreview(generatedHtml);
        });

        // Regenerate
        document.getElementById('ec-regenerate-btn').addEventListener('click', generateActivity);

        // Add to course
        document.getElementById('ec-add-to-course-btn').addEventListener('click', addActivityToCourse);

        // Escape key
        document.addEventListener('keydown', modalEscHandler);
    }

    function modalEscHandler(e) {
        if (e.key === 'Escape') closeModal();
    }

    function closeModal() {
        var overlay = document.getElementById('ec-activity-modal');
        if (overlay) overlay.remove();
        document.removeEventListener('keydown', modalEscHandler);
        modalImages = [];
        generatedHtml = '';
        generatedActivityId = '';
    }

    /* ---- File Handling ------------------------------------------------ */
    function handleFiles(fileList) {
        Array.from(fileList).forEach(function (file) {
            if (!file.type.startsWith('image/')) return;
            var reader = new FileReader();
            reader.onload = function (e) {
                var dataUrl = e.target.result;
                var base64 = dataUrl.split(',')[1];
                var mediaType = file.type;
                modalImages.push({ data: base64, mediaType: mediaType, preview: dataUrl });
                renderUploadPreviews();
            };
            reader.readAsDataURL(file);
        });
    }

    function renderUploadPreviews() {
        var container = document.getElementById('ec-upload-previews');
        if (!container) return;
        container.innerHTML = modalImages.map(function (img, i) {
            return '<div class="ec-upload-thumb">' +
                '<img src="' + img.preview + '">' +
                '<button class="ec-upload-thumb-remove" data-idx="' + i + '"><i class="fa-solid fa-xmark"></i></button>' +
            '</div>';
        }).join('');

        container.querySelectorAll('.ec-upload-thumb-remove').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var idx = parseInt(this.getAttribute('data-idx'));
                modalImages.splice(idx, 1);
                renderUploadPreviews();
            });
        });
    }

    /* ---- Generate Activity -------------------------------------------- */
    async function generateActivity() {
        var desc = document.getElementById('ec-description').value.trim();
        if (!desc) {
            showGenerateStatus('Please describe the activity you want to create.', true);
            return;
        }

        var btn = document.getElementById('ec-generate-btn');
        var regenBtn = document.getElementById('ec-regenerate-btn');
        btn.disabled = true;
        regenBtn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generating...';
        showGenerateStatus('Claude is creating your activity... This may take up to 60 seconds.', false);

        // Clear old preview
        var wrap = document.getElementById('ec-preview-wrap');
        var placeholder = document.getElementById('ec-preview-placeholder');
        if (placeholder) placeholder.style.display = '';
        var oldFrame = wrap.querySelector('iframe');
        if (oldFrame) oldFrame.remove();

        try {
            var body = {
                courseId: courseId,
                description: desc,
                images: modalImages.map(function (img) { return { data: img.data, mediaType: img.mediaType }; }),
            };

            var resp = await fetch('/api/generate-activity', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            var data = await resp.json();

            if (data.error) {
                showGenerateStatus(data.error, true);
                btn.disabled = false;
                regenBtn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate Activity';
                return;
            }

            generatedHtml = data.html;
            generatedActivityId = data.activityId;
            loadPreview(generatedHtml);
            hideGenerateStatus();

            btn.disabled = false;
            regenBtn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate Activity';

            // Show name row and enable reset
            document.getElementById('ec-name-row').style.display = '';
            document.getElementById('ec-reset-btn').disabled = false;

        } catch (e) {
            showGenerateStatus('Generation failed: ' + e.message, true);
            btn.disabled = false;
            regenBtn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate Activity';
        }
    }

    function showGenerateStatus(msg, isError) {
        var el = document.getElementById('ec-generate-status');
        el.style.display = '';
        el.className = 'ec-generate-status' + (isError ? ' error' : '');
        el.textContent = msg;
    }

    function hideGenerateStatus() {
        var el = document.getElementById('ec-generate-status');
        if (el) el.style.display = 'none';
    }

    /* ---- Preview ------------------------------------------------------ */
    function loadPreview(html) {
        var wrap = document.getElementById('ec-preview-wrap');
        var placeholder = document.getElementById('ec-preview-placeholder');
        if (placeholder) placeholder.style.display = 'none';

        // Remove old iframe
        var old = wrap.querySelector('iframe');
        if (old) old.remove();

        var iframe = document.createElement('iframe');
        iframe.sandbox = 'allow-scripts allow-same-origin';
        wrap.appendChild(iframe);

        // Write HTML to iframe
        var doc = iframe.contentDocument || iframe.contentWindow.document;
        doc.open();
        doc.write(html);
        doc.close();

        // Listen for completion messages
        window.addEventListener('message', function handler(e) {
            if (e.data && e.data.type === 'activity-complete') {
                var score = e.data.score || 0;
                showGenerateStatus('Activity completed! Score: ' + score + '/100', false);
                window.removeEventListener('message', handler);
            }
        });
    }

    function previewExistingActivity(activityId) {
        fetch('/api/edit-course-load?courseId=' + encodeURIComponent(courseId))
            .catch(function () {});

        // For existing activities we need to fetch from KV
        // We'll build a simple preview modal
        var overlay = document.createElement('div');
        overlay.className = 'ec-modal-overlay';
        overlay.innerHTML =
            '<div class="ec-modal" style="max-width:800px;">' +
                '<div class="ec-modal-header">' +
                    '<span class="ec-modal-title">Activity Preview</span>' +
                    '<button class="ec-modal-close" onclick="this.closest(\'.ec-modal-overlay\').remove()"><i class="fa-solid fa-xmark"></i></button>' +
                '</div>' +
                '<div style="flex:1; overflow:hidden; padding:0;">' +
                    '<div style="text-align:center; padding:40px; color:var(--color-text-muted);">Loading activity...</div>' +
                '</div>' +
            '</div>';
        document.body.appendChild(overlay);
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) overlay.remove();
        });

        // Fetch activity HTML from KV via a simple approach:
        // We already have the data in our local units array, but the HTML is in KV.
        // For now, we'll note this requires a load endpoint. Let's use a direct approach.
        // The activity HTML was stored when generated. We need a fetch endpoint.
        // For simplicity, we store the activityId and re-fetch if needed.
        // TODO: Could cache the HTML locally too.
    }

    /* ---- Add Activity to Course --------------------------------------- */
    function addActivityToCourse() {
        var name = document.getElementById('ec-activity-name').value.trim();
        if (!name) {
            document.getElementById('ec-activity-name').style.borderColor = '#E53E3E';
            document.getElementById('ec-activity-name').focus();
            return;
        }

        if (currentModalUnitId == null || currentModalLessonId == null) return;

        var lesson = units[currentModalUnitId].lessons[currentModalLessonId];
        lesson.activities.push({
            id: uid(),
            type: 'custom',
            title: name,
            sourceType: 'custom',
            activityId: generatedActivityId,
        });

        scheduleSave();
        closeModal();
        renderTree();

        // Expand to the lesson that got the new activity
        var unitEl = document.querySelector('.ec-unit[data-unit-idx="' + currentModalUnitId + '"]');
        if (unitEl) unitEl.classList.add('expanded');
        var lessonEl = document.querySelector('.ec-lesson[data-unit-idx="' + currentModalUnitId + '"][data-lesson-idx="' + currentModalLessonId + '"]');
        if (lessonEl) lessonEl.classList.add('expanded');
    }

    /* ---- Public API --------------------------------------------------- */
    window.initEditCourse = function (id, obj) {
        courseId = id;
        courseObj = obj;
        loadCourseData();
    };

    window.cleanupEditCourse = function () {
        destroySortables();
        clearTimeout(saveTimer);
        courseId = null;
        courseObj = null;
        units = [];
        closeModal();
    };

})();
