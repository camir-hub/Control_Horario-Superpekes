// ─────────────────────────────────────────────────────────────────
// Calendar — month view + dynamic right panel
// ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const {
        monthIso, selectedDay, today, isAdmin,
        selectedUserId, monthEntries,
        updateUrl,
    } = APP;

    // ── DOM references ───────────────────────────────────────────
    const calGrid       = document.getElementById('cal-grid');
    const monthTitle    = document.getElementById('month-title');
    const prevBtn       = document.getElementById('prev-month-btn');
    const nextBtn       = document.getElementById('next-month-btn');

    const panelHeading  = document.getElementById('panel-heading');
    const panelDayLabel = document.getElementById('panel-day-label');
    const addWrap       = document.getElementById('add-form-wrap');
    const editWrap      = document.getElementById('edit-form-wrap');
    const viewWrap      = document.getElementById('view-wrap');
    const noRegWrap     = document.getElementById('no-register-wrap');
    const emptyState    = document.getElementById('empty-state');
    const addForm       = document.getElementById('add-form');

    // add-form fields
    const fWorkDate  = document.getElementById('form-work-date');
    const fCheckIn   = document.getElementById('form-check-in');
    const fCheckOut  = document.getElementById('form-check-out');
    const fMealStart = document.getElementById('form-meal-start');
    const fMealEnd   = document.getElementById('form-meal-end');
    const fEnableMeal = document.getElementById('form-enable-meal');
    const fEnablePause = document.getElementById('form-enable-pause');
    const fEnableOvertime = document.getElementById('form-enable-overtime');
    const fUserId    = document.getElementById('form-user-id');
    const fUserRoleFilter = document.getElementById('form-user-role-filter');
    const fPauseStart = document.getElementById('form-pause-start');
    const fPauseEnd = document.getElementById('form-pause-end');
    const fOvertimeStart = document.getElementById('form-overtime-start');
    const fOvertimeEnd = document.getElementById('form-overtime-end');
    const fLocationLatitude = document.getElementById('form-location-latitude');
    const fLocationLongitude = document.getElementById('form-location-longitude');
    const fGeoStatus = document.getElementById('form-geo-status');

    // edit-form fields
    const editForm      = document.getElementById('edit-form');
    const eCheckIn      = document.getElementById('edit-check-in');
    const eCheckOut     = document.getElementById('edit-check-out');
    const eMealStart    = document.getElementById('edit-meal-start');
    const eMealEnd      = document.getElementById('edit-meal-end');
    const eEnableMeal   = document.getElementById('edit-enable-meal');
    const eEnablePause  = document.getElementById('edit-enable-pause');
    const eEnableOvertime = document.getElementById('edit-enable-overtime');
    const eReason       = document.getElementById('edit-reason');
    const ePauseStart = document.getElementById('edit-pause-start');
    const ePauseEnd = document.getElementById('edit-pause-end');
    const eOvertimeStart = document.getElementById('edit-overtime-start');
    const eOvertimeEnd = document.getElementById('edit-overtime-end');
    const eLocationLatitude = document.getElementById('edit-location-latitude');
    const eLocationLongitude = document.getElementById('edit-location-longitude');
    const eGeoStatus = document.getElementById('edit-geo-status');

    // view fields
    const vWorkRange    = document.getElementById('view-work-range');
    const vMealRange    = document.getElementById('view-meal-range');
    const vMealHours    = document.getElementById('view-meal-hours');
    const vWorkedHours  = document.getElementById('view-worked-hours');
    const vPauseHours = document.getElementById('view-pause-hours');
    const vOvertimeHours = document.getElementById('view-overtime-hours');
    const vLocation = document.getElementById('view-location');

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

    function updateGeoStatus(element, message, tone = '') {
        if (!element) {
            return;
        }
        element.textContent = message;
        element.classList.remove('is-error', 'is-success');
        if (tone) {
            element.classList.add(tone);
        }
    }

    function clearGeoFields(latInput, lonInput) {
        if (latInput) latInput.value = '';
        if (lonInput) lonInput.value = '';
    }

    function fillGeoFields(latInput, lonInput, coords) {
        if (latInput) latInput.value = coords.latitude.toFixed(7);
        if (lonInput) lonInput.value = coords.longitude.toFixed(7);
    }

    function captureGeolocation(latInput, lonInput, statusElement) {
        const hadStoredLocation = Boolean(latInput?.value && lonInput?.value);

        if (!window.isSecureContext || !navigator.geolocation) {
            updateGeoStatus(statusElement, hadStoredLocation
                ? 'No se puede actualizar la geolocalización desde este navegador o conexión. Se conserva la ubicación ya guardada.'
                : 'La geolocalización no está disponible en este navegador o en una conexión no segura. El registro se guardará sin ubicación.');
            return Promise.resolve();
        }

        updateGeoStatus(statusElement, 'Solicitando permiso para obtener la ubicación actual...');

        return new Promise((resolve) => {
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    fillGeoFields(latInput, lonInput, position.coords);
                    const accuracy = Math.round(position.coords.accuracy || 0);
                    updateGeoStatus(statusElement, `Ubicación capturada${accuracy ? ` (±${accuracy} m)` : ''}.`, 'is-success');
                    resolve();
                },
                () => {
                    updateGeoStatus(statusElement, hadStoredLocation
                        ? 'No se pudo actualizar la ubicación actual. Se conserva la ubicación ya guardada.'
                        : 'No se pudo obtener la ubicación. El registro se guardará sin geolocalización.');
                    resolve();
                },
                {
                    enableHighAccuracy: true,
                    timeout: 8000,
                    maximumAge: 60000,
                },
            );
        });
    }

    function bindGeolocatedSubmit(form, latInput, lonInput, statusElement) {
        if (!form) {
            return;
        }

        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            await captureGeolocation(latInput, lonInput, statusElement);
            form.submit();
        });
    }

    function setLocationView(entry) {
        if (!vLocation) {
            return;
        }

        if (entry.location_latitude == null || entry.location_longitude == null) {
            vLocation.textContent = 'Sin ubicación registrada';
            return;
        }

        const latitude = Number(entry.location_latitude);
        const longitude = Number(entry.location_longitude);
        const link = document.createElement('a');
        link.className = 'map-link';
        link.href = `https://www.google.com/maps?q=${latitude},${longitude}`;
        link.target = '_blank';
        link.rel = 'noreferrer noopener';
        link.textContent = `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`;
        vLocation.replaceChildren(link);
    }

    function syncBreakInputs(mealStart, mealEnd, pauseStart, pauseEnd, overtimeStart, overtimeEnd, mealToggle, pauseToggle, overtimeToggle) {
        if (!mealStart || !mealEnd || !pauseStart || !pauseEnd || !overtimeStart || !overtimeEnd || !mealToggle || !pauseToggle || !overtimeToggle) {
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
        const overtimeEnabled = overtimeToggle.checked;
        overtimeStart.disabled = !overtimeEnabled;
        overtimeEnd.disabled = !overtimeEnabled;
        if (!overtimeEnabled) {
            overtimeStart.value = '';
            overtimeEnd.value = '';
        }
    }

    function bindBreakToggleHandlers(mealStart, mealEnd, pauseStart, pauseEnd, overtimeStart, overtimeEnd, mealToggle, pauseToggle, overtimeToggle) {
        if (!mealToggle || !pauseToggle || !overtimeToggle) {
            return;
        }

        const sync = () => syncBreakInputs(
            mealStart,
            mealEnd,
            pauseStart,
            pauseEnd,
            overtimeStart,
            overtimeEnd,
            mealToggle,
            pauseToggle,
            overtimeToggle,
        );

        mealToggle.addEventListener('change', sync);
        pauseToggle.addEventListener('change', sync);
        overtimeToggle.addEventListener('change', sync);
        sync();
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
        let label = monthDate.toLocaleDateString('es-ES', { month: 'long', year: 'numeric' });
        label = label.replace(/^de\s+/i, '').replace(/\s+de\s+/i, ' ');
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
                    if (entry.overtime_hours > 0) cls += ' has-overtime';
                    else cls += ' has-entry';
                    if (entry.overtime_validated) {
                        cls += ' is-validated';
                    } else {
                        cls += ' is-unvalidated';
                    }
                }
                if (isSelected) cls += ' is-selected';
                cell.className = cls;

                let hoursHtml = '';
                if (entry) {
                    let parts = [];
                    if (entry.worked_hours > 0) parts.push(`<span style='color:#22c55e'>${entry.worked_hours}h</span>`); // Verde J.ordinaria
                    if (entry.meal_hours > 0)   parts.push(`<span style='color:#fb923c'>${entry.meal_hours}h</span>`);   // Naranja comida
                    if (entry.pause_hours > 0)  parts.push(`<span style='color:#ef4444'>${entry.pause_hours}h</span>`);  // Rojo pausa
                    if (entry.overtime_hours > 0) parts.push(`<span style='color:#8b5cf6'>${entry.overtime_hours}h</span>`); // Violeta extra
                    hoursHtml = parts.length ? `<span class="cell-hours">${parts.join('-')}</span>` : '<span class="cell-hours"></span>';
                } else {
                    hoursHtml = '<span class="cell-hours"></span>';
                }
                const dotHtml = entry ? '<span class="cell-dot"></span>' : '';
                const checkHtml = (entry && entry.overtime_validated)
                    ? '<span class="cell-check">&#10003;</span>'
                    : '';

                cell.innerHTML = `<span class="cell-num">${cursor.getDate()}</span>${hoursHtml}${dotHtml}${checkHtml}`;
                cell.addEventListener('click', () => selectDay(iso, cell));
            }

            calGrid.appendChild(cell);
            cursor.setDate(cursor.getDate() + 1);
        }

        // Navigation links
        const prevMonth = new Date(year, month - 1, 1);
        const nextMonth = new Date(year, month + 1, 1);
        const userPart  = isAdmin ? `&user_id=${selectedUserId}` : '';
        prevBtn.href = '#';
        nextBtn.href = '#';
        prevBtn.onclick = (e) => {
            e.preventDefault();
            renderCalendar(prevMonth);
        };
        nextBtn.onclick = (e) => {
            e.preventDefault();
            renderCalendar(nextMonth);
        };
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
    }

    function updatePanel(iso) {
        hideAll();
        const entry = monthEntries[iso] || null;
        panelDayLabel.textContent = cap(localeDateLabel(iso));

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
                ePauseStart.value = entry.pause_start;
                ePauseEnd.value = entry.pause_end;
                eOvertimeStart.value = entry.overtime_start;
                eOvertimeEnd.value = entry.overtime_end;
                if (eEnableMeal && eEnablePause && eEnableOvertime) {
                    const hasMeal = Boolean(entry.meal_start && entry.meal_end);
                    const hasPause = Boolean(entry.pause_start && entry.pause_end);
                    const hasOvertime = Boolean(entry.overtime_start && entry.overtime_end);
                    eEnableMeal.checked = hasMeal;
                    eEnablePause.checked = hasPause;
                    eEnableOvertime.checked = hasOvertime;
                    syncBreakInputs(eMealStart, eMealEnd, ePauseStart, ePauseEnd, eOvertimeStart, eOvertimeEnd, eEnableMeal, eEnablePause, eEnableOvertime);
                }
                if (eLocationLatitude && eLocationLongitude) {
                    eLocationLatitude.value = entry.location_latitude || '';
                    eLocationLongitude.value = entry.location_longitude || '';
                }
                updateGeoStatus(eGeoStatus, entry.location_latitude && entry.location_longitude
                    ? 'Al guardar se intentará actualizar la ubicación actual del dispositivo.'
                    : 'Al guardar, el navegador intentará adjuntar tu ubicación actual si das permiso.');
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
                vPauseHours.textContent = `${entry.pause_hours} h`;
                vOvertimeHours.textContent = `${entry.overtime_hours} h`;
                setLocationView(entry);
            }
        } else {
            const canCreate = !isAdmin && iso === today;
            if (canCreate) {
                panelHeading.textContent = 'Nuevo registro';
                addWrap.style.display    = '';
                fWorkDate.value  = iso;
                fCheckIn.value   = '';
                fCheckOut.value  = '';
                fMealStart.value = '';
                fMealEnd.value   = '';
                fPauseStart.value = '';
                fPauseEnd.value = '';
                fOvertimeStart.value = '';
                fOvertimeEnd.value = '';
                clearGeoFields(fLocationLatitude, fLocationLongitude);
                if (fEnableMeal && fEnablePause && fEnableOvertime) {
                    fEnableMeal.checked = false;
                    fEnablePause.checked = false;
                    fEnableOvertime.checked = false;
                    syncBreakInputs(fMealStart, fMealEnd, fPauseStart, fPauseEnd, fOvertimeStart, fOvertimeEnd, fEnableMeal, fEnablePause, fEnableOvertime);
                }
                updateGeoStatus(fGeoStatus, 'Al guardar, el navegador intentará adjuntar tu ubicación actual si das permiso.');
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

    bindBreakToggleHandlers(
        fMealStart,
        fMealEnd,
        fPauseStart,
        fPauseEnd,
        fOvertimeStart,
        fOvertimeEnd,
        fEnableMeal,
        fEnablePause,
        fEnableOvertime,
    );

    bindBreakToggleHandlers(
        eMealStart,
        eMealEnd,
        ePauseStart,
        ePauseEnd,
        eOvertimeStart,
        eOvertimeEnd,
        eEnableMeal,
        eEnablePause,
        eEnableOvertime,
    );

    bindGeolocatedSubmit(addForm, fLocationLatitude, fLocationLongitude, fGeoStatus);
    bindGeolocatedSubmit(editForm, eLocationLatitude, eLocationLongitude, eGeoStatus);

    if (selectedDay) {
        updatePanel(selectedDay);
    } else {
        emptyState.style.display = '';
    }
});
