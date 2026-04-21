function initSupport() {
    document.getElementById('btn-open-support')?.addEventListener('click', () => {
        openScreen('screen-support');
    });

    document.getElementById('support-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(e.target);
        const message = formData.get('message');

        try {
            tg.MainButton.showProgress();
            await window.api.createTicket(message);
            tg.showAlert('Ваше сообщение отправлено! Мы ответим вам в ближайшее время.');
            e.target.reset();
            openScreen('screen-welcome');
        } catch (err) {
            tg.showAlert('Ошибка: ' + err.message);
        } finally {
            tg.MainButton.hideProgress();
        }
    });
}

initSupport();
