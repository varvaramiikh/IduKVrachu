class ApiClient {
    constructor() {
        this.tg = window.Telegram.WebApp;
        this.baseUrl = '/api';
        this.initData = this.tg.initData;
    }

    async request(path, options = {}) {
        const url = `${this.baseUrl}${path}`;
        const headers = {
            'Content-Type': 'application/json',
            'X-Tg-Init-Data': this.initData,
            ...options.headers
        };

        const response = await fetch(url, { ...options, headers });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'API Error');
        }
        return response.json();
    }

    getCities() { return this.request('/cities'); }
    getClinics(cityId) { return this.request(`/clinics?city_id=${cityId}`); }
    getServices() { return this.request('/services'); }
    getSlots(clinicId, serviceId, date) { 
        return this.request(`/slots?clinic_id=${clinicId}&service_id=${serviceId}&date=${date}`); 
    }
    createAppointment(data) {
        return this.request('/appointments', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }
    getMyAppointments() { return this.request('/appointments'); }
    acceptConsent(version) {
        return this.request(`/consent?version=${version}`, { method: 'POST' });
    }
    createTicket(message) {
        return this.request('/support', {
            method: 'POST',
            body: JSON.stringify({ message })
        });
    }
    cancelAppointment(id) {
        return this.request(`/appointments/${id}`, { method: 'DELETE' });
    }
}

window.api = new ApiClient();
