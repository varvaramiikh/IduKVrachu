async function loadMyAppointments() {
    const list = document.getElementById('my-appointments-list');
    list.innerHTML = 'Загрузка...';
    try {
        const appointments = await window.api.getMyAppointments();
        if (appointments.length === 0) {
            list.innerHTML = '<p style="text-align: center; margin-top: 20px;">У вас пока нет записей</p>';
            return;
        }
        
        list.innerHTML = appointments.map(a => `
            <article class="module-card">
                <div class="module-head">
                    <h3>Запись #${a.id}</h3>
                    <span class="badge ${a.status === 'scheduled' ? 'badge-soft' : ''}">${a.status}</span>
                </div>
                <p><strong>Дата:</strong> ${new Date(a.slot_datetime).toLocaleString()}</p>
                <p><strong>Комментарий:</strong> ${a.comment || '-'}</p>
                ${a.status === 'scheduled' ? `
                    <button class="button button-secondary button-full" onclick="cancelAppointment(${a.id})" style="margin-top: 10px; color: #e74c3c;">
                        Отменить запись
                    </button>
                ` : ''}
            </article>
        `).join('');
    } catch (e) {
        list.innerHTML = 'Ошибка загрузки записей';
    }
}

window.cancelAppointment = async (id) => {
    if (!confirm('Вы уверены, что хотите отменить запись?')) return;
    
    try {
        await window.api.cancelAppointment(id);
        tg.showAlert('Запись отменена');
        loadMyAppointments();
    } catch (e) {
        tg.showAlert('Ошибка: ' + e.message);
    }
};

document.getElementById('btn-open-my-appointments')?.addEventListener('click', () => {
    loadMyAppointments();
    openScreen('screen-my-appointments');
});
