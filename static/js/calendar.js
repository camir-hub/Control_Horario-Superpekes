document.addEventListener('DOMContentLoaded', () => {
    const dayButtons = Array.from(document.querySelectorAll('.day'));
    const dateInput = document.getElementById('work_date');
    const selectedDayTitle = document.getElementById('calendar-selected-day');
    const summaryWorkRange = document.getElementById('summary-work-range');
    const summaryMealRange = document.getElementById('summary-meal-range');
    const summaryMealHours = document.getElementById('summary-meal-hours');
    const summaryWorkedHours = document.getElementById('summary-worked-hours');
    const summaryComments = document.getElementById('summary-comments');
    const summaryOvertime = document.getElementById('summary-overtime');
    const adminUserSelect = document.getElementById('user_id');
    const editPanel = document.getElementById('edit-entry-panel');
    const emptyEditPanel = document.getElementById('edit-entry-panel-empty');
    const editForm = document.getElementById('edit-entry-form');
    const editCheckIn = document.getElementById('edit_check_in');
    const editCheckOut = document.getElementById('edit_check_out');
    const editMealStart = document.getElementById('edit_meal_start');
    const editMealEnd = document.getElementById('edit_meal_end');
    const editComments = document.getElementById('edit_comments');

    function currentUserId() {
        return adminUserSelect ? adminUserSelect.value : null;
    }

    function setActiveButton(activeButton) {
        dayButtons.forEach((button) => button.classList.remove('active'));
        activeButton.classList.add('active');
    }

    function updateDayButtonState(button, entry) {
        button.dataset.hasEntry = entry ? 'true' : 'false';
        button.classList.toggle('has-entry', Boolean(entry));
        button.classList.toggle('has-overtime', Boolean(entry) && Number(entry.overtime_hours) > 0);
        button.classList.toggle('is-validated', Boolean(entry) && Boolean(entry.overtime_validated));

        if (!entry) {
            button.dataset.checkIn = '';
            button.dataset.checkOut = '';
            button.dataset.mealStart = '';
            button.dataset.mealEnd = '';
            button.dataset.mealHours = '0.00';
            button.dataset.workedHours = '0.00';
            button.dataset.overtimeHours = '0.00';
            button.dataset.comments = 'Sin registro en este día';
            button.dataset.validated = 'false';
            return;
        }

        button.dataset.checkIn = entry.check_in || '';
        button.dataset.checkOut = entry.check_out || '';
        button.dataset.mealStart = entry.meal_start || '';
        button.dataset.mealEnd = entry.meal_end || '';
        button.dataset.mealHours = Number(entry.meal_hours || 0).toFixed(2);
        button.dataset.workedHours = Number(entry.worked_hours || 0).toFixed(2);
        button.dataset.overtimeHours = Number(entry.overtime_hours || 0).toFixed(2);
        button.dataset.comments = entry.comments || 'Sin comentarios';
        button.dataset.validated = entry.overtime_validated ? 'true' : 'false';
    }

    function renderDaySummary(button) {
        const hasEntry = button.dataset.hasEntry === 'true';
        const overtime = Number(button.dataset.overtimeHours || '0');
        const validated = button.dataset.validated === 'true';

        selectedDayTitle.textContent = `Detalle ${button.dataset.label}`;
        dateInput.value = button.dataset.day;

        if (!hasEntry) {
            summaryWorkRange.textContent = 'Sin registro';
            summaryMealRange.textContent = 'Sin tramo de comida';
            summaryMealHours.textContent = '0.00 h';
            summaryWorkedHours.textContent = '0.00 h';
            summaryComments.textContent = 'Sin registro en este día';
            summaryOvertime.textContent = 'No existe registro en este día.';
            summaryOvertime.classList.remove('warning');
            summaryOvertime.classList.add('meta');
            return;
        }

        const mealStart = button.dataset.mealStart;
        const mealEnd = button.dataset.mealEnd;
        summaryWorkRange.textContent = `${button.dataset.checkIn} - ${button.dataset.checkOut}`;
        summaryMealRange.textContent = mealStart && mealEnd ? `${mealStart} - ${mealEnd}` : 'Sin tramo de comida';
        summaryMealHours.textContent = `${button.dataset.mealHours} h`;
        summaryWorkedHours.textContent = `${button.dataset.workedHours} h`;
        summaryComments.textContent = button.dataset.comments || 'Sin comentarios';

        if (overtime > 0) {
            summaryOvertime.textContent = validated
                ? `Horas extra: ${button.dataset.overtimeHours} h | Validadas`
                : `Horas extra: ${button.dataset.overtimeHours} h`;
            summaryOvertime.classList.remove('meta');
            summaryOvertime.classList.add('warning');
        } else {
            summaryOvertime.textContent = 'No hay horas extra registradas.';
            summaryOvertime.classList.remove('warning');
            summaryOvertime.classList.add('meta');
        }
    }

    function renderEditPanel(entry) {
        if (!editPanel || !emptyEditPanel) {
            return;
        }

        if (!entry || !entry.editable) {
            if (editPanel) {
                editPanel.style.display = 'none';
            }
            emptyEditPanel.style.display = 'block';
            return;
        }

        editPanel.style.display = 'block';
        emptyEditPanel.style.display = 'none';
        editForm.action = `/entries/${entry.id}/update`;
        editCheckIn.value = entry.check_in || '';
        editCheckOut.value = entry.check_out || '';
        editMealStart.value = entry.meal_start || '';
        editMealEnd.value = entry.meal_end || '';
        editComments.value = entry.comments || '';
    }

    async function fetchDayData(button) {
        const params = new URLSearchParams({ day: button.dataset.day });
        const userId = currentUserId();
        if (userId) {
            params.set('user_id', userId);
        }

        const response = await fetch(`/calendar/day-data?${params.toString()}`, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });

        if (!response.ok) {
            throw new Error('No se pudo cargar el detalle del día');
        }

        return response.json();
    }

    function navigateWithSelection(button) {
        const params = new URLSearchParams(window.location.search);
        params.set('day', button.dataset.day);
        const userId = currentUserId();
        if (userId) {
            params.set('user_id', userId);
        }
        window.history.replaceState({}, '', `/?${params.toString()}`);
    }

    dayButtons.forEach((button) => {
        button.addEventListener('click', async () => {
            setActiveButton(button);

            try {
                const payload = await fetchDayData(button);
                updateDayButtonState(button, payload.entry);
                renderDaySummary(button);
                renderEditPanel(payload.entry);
                navigateWithSelection(button);
            } catch (error) {
                summaryComments.textContent = error.message;
            }
        });
    });

    const activeButton = document.querySelector('.day.active') || dayButtons[0];
    if (activeButton) {
        renderDaySummary(activeButton);
        if (activeButton.dataset.hasEntry !== 'true') {
            renderEditPanel(null);
        }
    }
});
