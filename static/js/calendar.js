// ─────────────────────────────────────────────────────────────────
// Calendar — month view + dynamic right panel
// ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const {
        monthIso, selectedDay, today, isAdmin,
        selectedUserId, monthEntries,
        validateUrl, updateUrl,
    } = APP;

    // ── DOM references ───────────────────────────────────────────
    const calGrid       = document.getElementById('cal-grid');
    const monthTitle    = document.getElementById('month-title');
    const prevBtn       = document.getElementById('prev-month-btn');
    const nextBtn       = document.getElementById('next-month-btn');

    const panelHeading  = document.getElementById('panel-heading');
    const panelDayLabel = document.getElementById('panel-day-label');
    const panelValidationStatus = document.getElementById('panel-validation-status');
    const addWrap       = document.getElementById('add-form-wrap');
    const editWrap      = document.getElementById('edit-form-wrap');
    const viewWrap      = document.getElementById('view-wrap');
    const noRegWrap     = document.getElementById('no-register-wrap');
    const emptyState    = document.getElementById('empty-state');
    const validateForm  = document.getElementById('validate-form');

    // add-form fields
    const fWorkDate  = document.getElementById('form-work-date');
    const fCheckIn   = document.getElementById('form-check-in');
    const fCheckOut  = document.getElementById('form-check-out');
    const fMealStart = document.getElementById('form-meal-start');
    const fMealEnd   = document.getElementById('form-meal-end');
    const fEnableMeal = document.getElementById('form-enable-meal');
    const fEnablePause = document.getElementById('form-enable-pause');
    const fUserId    = document.getElementById('form-user-id');
    const fUserRoleFilter = document.getElementById('form-user-role-filter');
    const fPauseStart = document.getElementById('form-pause-start');
    const fPauseEnd = document.getElementById('form-pause-end');

    // edit-form fields
    const editForm      = document.getElementById('edit-form');
    const eCheckIn      = document.getElementById('edit-check-in');
    const eCheckOut     = document.getElementById('edit-check-out');
    const eMealStart    = document.getElementById('edit-meal-start');
    const eMealEnd      = document.getElementById('edit-meal-end');
    const eEnableMeal   = document.getElementById('edit-enable-meal');
    const eEnablePause  = document.getElementById('edit-enable-pause');
    const eReason       = document.getElementById('edit-reason');
    const ePauseStart = document.getElementById('edit-pause-start');
    const ePauseEnd = document.getElementById('edit-pause-end');

    // view fields
    const vWorkRange    = document.getElementById('view-work-range');
    const vMealRange    = document.getElementById('view-meal-range');
    const vMealHours    = document.getElementById('view-meal-hours');
    const vWorkedHours  = document.getElementById('view-worked-hours');
    const vOvertimeHours = document.getElementById('view-overtime-hours');
    const vOvertimeBadge = document.getElementById('view-overtime-badge');

    // ── Utilities ────────────────────────────────────────────────
    function parseIso(s) {
        const [y, m, d] = s.split('-').map(Number);
        return new Date(y, m - 1, d);
    }
    function toIso(date) {
        const y = date.getFullYear();
        const m = String(date.getMonth() + 1).padStart(2, '0');
        const d = String(date.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
    }
    function localeDateLabel(iso) {
        return parseIso(iso).toLocaleDateString('es-ES', {
            weekday: 'long', day: '2-digit', month: 'long', year: 'numeric'
        });
    }
    function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
    function withId(urlTemplate, id) {
        return urlTemplate.replace(/\/0(\/|$)/, `/${id}$1`);
    }

    function syncBreakInputs(mealStart, mealEnd, pauseStart, pauseEnd, mealToggle, pauseToggle) {
        if (!mealStart || !mealEnd || !pauseStart || !pauseEnd || !mealToggle || !pauseToggle) {
            return;
        }
        const mealEnabled = mealToggle.checked;
        mealStart.disabled = !mealEnabled;
        mealEnd.disabled = !mealEnabled;
        if (!mealEnabled) {
            mealStart.value = '';
            mealEnd.value = '';
        }
        const pauseEnabled = pauseToggle.checked;
        pauseStart.disabled = !pauseEnabled;
        pauseEnd.disabled = !pauseEnabled;
        if (!pauseEnabled) {
            pauseStart.value = '';
            pauseEnd.value = '';
        }
    }

    function applyUserRoleFilter() {
        if (!fUserId || !fUserRoleFilter) {
            return;
        }

        const selectedRole = fUserRoleFilter.value;
        const options = Array.from(fUserId.options);
        let firstVisibleValue = '';

        options.forEach((option) => {
            const role = option.dataset.role || 'user';
            const shouldShow = selectedRole === 'all' || role === selectedRole;
            option.hidden = !shouldShow;
            if (shouldShow && !firstVisibleValue) {
                firstVisibleValue = option.value;
            }
        });

        const currentOption = fUserId.selectedOptions[0];
        if (!currentOption || currentOption.hidden) {
            fUserId.value = firstVisibleValue;
        }
    }

    // ── Calendar rendering ───────────────────────────────────────
    let currentMonth = parseIso(monthIso);
    let currentSelected = selectedDay;

    function renderCalendar(monthDate) {
        const year  = monthDate.getFullYear();
        const month = monthDate.getMonth();   // 0-indexed

        // Month title
        const label = monthDate.toLocaleDateString('es-ES', { month: 'long', year: 'numeric' });
        monthTitle.textContent = cap(label);

        const firstDay = new Date(year, month, 1);
        const lastDay  = new Date(year, month + 1, 0);

        // Monday-based offset (getDay: 0=Sun → offset 6, 1=Mon → 0, …)
        const startOffset = (firstDay.getDay() + 6) % 7;
        const startCell   = new Date(firstDay);
        startCell.setDate(startCell.getDate() - startOffset);

        const endOffset = (lastDay.getDay() + 6) % 7;
        const endCell = new Date(lastDay);
        endCell.setDate(endCell.getDate() + (6 - endOffset));

        calGrid.innerHTML = '';

        const cursor = new Date(startCell);
        while (cursor <= endCell) {
            const iso          = toIso(cursor);
            const inMonth      = cursor.getMonth() === month;
            const isToday      = iso === today;
            const isSelected   = iso === currentSelected;
            const isWeekend    = cursor.getDay() === 0 || cursor.getDay() === 6;
            const entry        = monthEntries[iso];

            const cell = document.createElement('button');
            cell.type  = 'button';

            if (!inMonth) {
                cell.className = 'cal-cell empty';
            } else {
                let cls = 'cal-cell';
                if (isWeekend)                                         cls += ' is-weekend';
                if (isToday)                                           cls += ' is-today';
                if (entry) {
                    if (entry.overtime_validated)                               cls += ' is-validated';
                    else if (entry.overtime_hours > 0)                        cls += ' has-overtime';
                    else                                                       cls += ' has-entry';
                }
                if (isSelected) cls += ' is-selected';
                cell.className = cls;

                const hoursHtml = entry
                    ? `<span class="cell-hours">${entry.worked_hours}h</span>`
                    : '<span class="cell-hours"></span>';
                const dotHtml = (entry && !entry.overtime_validated) ? '<span class="cell-dot"></span>' : '';
                const validatedCheckHtml = (entry && entry.overtime_validated)
                    ? '<span class="cell-check" title="Horas validadas por administrador">[OK]</span>'
                    : '';

                cell.innerHTML = `<span class="cell-num">${cursor.getDate()}</span>${hoursHtml}${dotHtml}${validatedCheckHtml}`;
                cell.addEventListener('click', () => selectDay(iso, cell));
            }

            calGrid.appendChild(cell);
            cursor.setDate(cursor.getDate() + 1);
        }

        // Navigation links
        const prevMonth = new Date(year, month - 1, 1);
        const nextMonth = new Date(year, month + 1, 1);
        const userPart  = isAdmin ? `&user_id=${selectedUserId}` : '';
        prevBtn.href = `/?day=${toIso(prevMonth)}${userPart}`;
        nextBtn.href = `/?day=${toIso(nextMonth)}${userPart}`;
    }

    // ── Day selection ────────────────────────────────────────────
    function selectDay(iso, clickedCell) {
        document.querySelectorAll('.cal-cell.is-selected')
            .forEach(c => c.classList.remove('is-selected'));
        if (clickedCell) clickedCell.classList.add('is-selected');
        currentSelected = iso;

        updatePanel(iso);

        const params = new URLSearchParams(window.location.search);
        params.set('day', iso);
        if (isAdmin && selectedUserId) params.set('user_id', selectedUserId);
        window.history.replaceState({}, '', `/?${params.toString()}`);
    }

    // ── Right-panel update ───────────────────────────────────────
    function hideAll() {
        addWrap.style.display      = 'none';
        editWrap.style.display     = 'none';
        viewWrap.style.display     = 'none';
        noRegWrap.style.display    = 'none';
        emptyState.style.display   = 'none';
        validateForm.style.display = 'none';
    }

    function updateValidationStatus(entry) {
        if (!panelValidationStatus) {
            return;
        }

        if (entry && entry.overtime_validated) {
            panelValidationStatus.style.display = '';
            panelValidationStatus.textContent = 'Horas validadas por administrador';
        } else {
            panelValidationStatus.style.display = 'none';
        }
    }

    function updatePanel(iso) {
        hideAll();
        const entry = monthEntries[iso] || null;
        panelDayLabel.textContent = cap(localeDateLabel(iso));
        updateValidationStatus(entry);

        if (entry) {
            if (entry.editable) {
                // ── Edit form ──
                panelHeading.textContent = 'Modificar registro';
                editWrap.style.display   = '';
                editForm.action          = withId(updateUrl, entry.id);
                eCheckIn.value   = entry.check_in;
                eCheckOut.value  = entry.check_out;
                eMealStart.value = entry.meal_start;
                eMealEnd.value   = entry.meal_end;
                if (eEnableMeal && eEnablePause) {
                    const hasMeal = Boolean(entry.meal_start && entry.meal_end);
                    const hasPause = Boolean(entry.pause_start && entry.pause_end);
                    eEnableMeal.checked = hasMeal;
                    eEnablePause.checked = hasPause;
                    syncBreakInputs(eMealStart, eMealEnd, ePauseStart, ePauseEnd, eEnableMeal, eEnablePause);
                }
                eReason.value    = '';
            } else {
                // ── Read-only view ──
                panelHeading.textContent = 'Registro del dia';
                viewWrap.style.display   = '';
                vWorkRange.textContent   = `${entry.check_in} - ${entry.check_out}`;
                vMealRange.textContent   = (entry.meal_start && entry.meal_end)
                    ? `${entry.meal_start} - ${entry.meal_end}` : 'Sin comida';
                vMealHours.textContent   = `${entry.meal_hours} h`;
                vWorkedHours.textContent = `${entry.worked_hours} h`;
                vOvertimeHours.textContent = `${entry.overtime_hours} h`;

                if (entry.overtime_validated) {
                    vOvertimeBadge.style.display = '';
                    vOvertimeBadge.className = 'validated-badge';
                    vOvertimeBadge.textContent = entry.overtime_hours > 0
                        ? `Registro validado. Horas extra: ${entry.overtime_hours} h`
                        : 'Registro validado';
                } else if (entry.overtime_hours > 0) {
                    vOvertimeBadge.style.display = '';
                    vOvertimeBadge.className = 'overtime-badge';
                    vOvertimeBadge.textContent = `Horas extra: ${entry.overtime_hours} h`;
                } else {
                    vOvertimeBadge.style.display = 'none';
                }
            }

            // Admin validate button
            if (isAdmin && !entry.overtime_validated) {
                validateForm.style.display = '';
                validateForm.action        = withId(validateUrl, entry.id);
            }
        } else {
            const canCreate = isAdmin || iso === today;
            if (canCreate) {
                panelHeading.textContent = 'Nuevo registro';
                addWrap.style.display    = '';
                fWorkDate.value  = iso;
                fCheckIn.value   = '';
                fCheckOut.value  = '';
                fMealStart.value = '';
                fMealEnd.value   = '';
                if (fEnableMeal && fEnablePause) {
                    fEnableMeal.checked = false;
                    fEnablePause.checked = false;
                    syncBreakInputs(fMealStart, fMealEnd, fPauseStart, fPauseEnd, fEnableMeal, fEnablePause);
                }
            } else {
                panelHeading.textContent  = 'Sin registro';
                noRegWrap.style.display   = '';
            }
        }
    }

    // ── Init ─────────────────────────────────────────────────────
    currentMonth = parseIso(monthIso);
    renderCalendar(currentMonth);

    if (fUserRoleFilter) {
        applyUserRoleFilter();
        fUserRoleFilter.addEventListener('change', applyUserRoleFilter);
    }

    if (fEnableMeal && fEnablePause) {
        fEnableMeal.addEventListener('change', () => syncBreakInputs(fMealStart, fMealEnd, fPauseStart, fPauseEnd, fEnableMeal, fEnablePause));
        fEnablePause.addEventListener('change', () => syncBreakInputs(fMealStart, fMealEnd, fPauseStart, fPauseEnd, fEnableMeal, fEnablePause));
        syncBreakInputs(fMealStart, fMealEnd, fPauseStart, fPauseEnd, fEnableMeal, fEnablePause);
    }

    if (eEnableMeal && eEnablePause) {
        eEnableMeal.addEventListener('change', () => syncBreakInputs(eMealStart, eMealEnd, ePauseStart, ePauseEnd, eEnableMeal, eEnablePause));
        eEnablePause.addEventListener('change', () => syncBreakInputs(eMealStart, eMealEnd, ePauseStart, ePauseEnd, eEnableMeal, eEnablePause));
        syncBreakInputs(eMealStart, eMealEnd, ePauseStart, ePauseEnd, eEnableMeal, eEnablePause);
    }

    if (selectedDay) {
        updatePanel(selectedDay);
    } else {
        emptyState.style.display = '';
    }
});
