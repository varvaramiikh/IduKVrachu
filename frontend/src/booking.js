const bookingState = {
    serviceId: null,
    cityId: null,
    clinicId: null,
    slot: null
};

async function initBooking() {
    document.getElementById('btn-open-booking')?.addEventListener('click', async () => {
        await loadServices();
        openScreen('screen-booking-services');
    });

    document.getElementById('booking-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(e.target);
        const data = {
            clinic_id: bookingState.clinicId,
            service_id: bookingState.serviceId,
            child_id: 1, // В MVP упростим, в реальности нужно создать профиль ребенка
            slot_datetime: bookingState.slot.datetime,
            comment: formData.get('comment')
        };

        try {
            tg.MainButton.showProgress();
            await window.api.createAppointment(data);
            tg.showAlert('Вы успешно записаны!');
            openScreen('screen-welcome');
        } catch (err) {
            tg.showAlert('Ошибка при записи: ' + err.message);
        } finally {
            tg.MainButton.hideProgress();
        }
    });
}

async function loadServices() {
    const list = document.getElementById('services-list');
    list.innerHTML = 'Загрузка...';
    try {
        const services = await window.api.getServices();
        list.innerHTML = services.map(s => `
            <article class="module-card" onclick="selectService(${s.id})">
                <h3>${s.name}</h3>
                <p>${s.service_type}</p>
            </article>
        `).join('');
    } catch (e) {
        list.innerHTML = 'Ошибка загрузки услуг';
    }
}

window.selectService = async (id) => {
    bookingState.serviceId = id;
    await loadCities();
    openScreen('screen-booking-cities');
};

async function loadCities() {
    const list = document.getElementById('cities-list');
    list.innerHTML = 'Загрузка...';
    try {
        const cities = await window.api.getCities();
        list.innerHTML = cities.map(c => `
            <article class="module-card" onclick="selectCity(${c.id})">
                <h3>${c.name}</h3>
            </article>
        `).join('');
    } catch (e) {
        list.innerHTML = 'Ошибка загрузки городов';
    }
}

window.selectCity = async (id) => {
    bookingState.cityId = id;
    await loadClinics(id);
    openScreen('screen-booking-clinics');
};

async function loadClinics(cityId) {
    const list = document.getElementById('clinics-list');
    list.innerHTML = 'Загрузка...';
    try {
        const clinics = await window.api.getClinics(cityId);
        list.innerHTML = clinics.map(c => `
            <article class="module-card" onclick="selectClinic(${c.id})">
                <h3>${c.name}</h3>
                <p>${c.address || ''}</p>
            </article>
        `).join('');
    } catch (e) {
        list.innerHTML = 'Ошибка загрузки клиник';
    }
}

window.selectClinic = async (id) => {
    bookingState.clinicId = id;
    await loadSlots(id);
    openScreen('screen-booking-slots');
};

async function loadSlots(clinicId) {
    const list = document.getElementById('slots-list');
    list.innerHTML = 'Загрузка...';
    try {
        const today = new Date().toISOString().split('T')[0];
        const slots = await window.api.getSlots(clinicId, bookingState.serviceId, today);
        list.innerHTML = slots.map((s, idx) => `
            <article class="module-card ${s.is_available ? '' : 'disabled'}" 
                     onclick="${s.is_available ? `selectSlot(${idx}, '${s.datetime}')` : ''}"
                     style="${s.is_available ? '' : 'opacity: 0.5; pointer-events: none;'}">
                <h3>${new Date(s.datetime).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</h3>
                <p>${s.is_available ? 'Свободно' : 'Занято'}</p>
            </article>
        `).join('');
        if (slots.length === 0) list.innerHTML = '<p>Нет свободных слотов на сегодня</p>';
    } catch (e) {
        list.innerHTML = 'Ошибка загрузки слотов';
    }
}

window.selectSlot = (idx, dt) => {
    bookingState.slot = { datetime: dt };
    openScreen('screen-booking-form');
};

initBooking();
