// Общий набор иконок услуг в стилистике сайта (line-style).
// Используется и в админке (выбор иконки при создании/редактировании услуги),
// и на booking.html (отображение карточек услуг). Каждая иконка живёт в
// отдельном SVG-файле в frontend/materials/svg/ и подключается через <img>.
(function () {
  const ICONS = [
    { key: "tooth",      label: "Стоматология",      file: "materials/svg/icon-svc-tooth.svg" },
    { key: "syringe",    label: "Анализы",           file: "materials/svg/icon-svc-syringe.svg" },
    { key: "child",      label: "Педиатрия",         file: "materials/svg/icon-svc-child.svg" },
    { key: "brain",      label: "Неврология",        file: "materials/svg/icon-svc-brain.svg" },
    { key: "heart",      label: "Кардиология",       file: "materials/svg/icon-svc-heart.svg" },
    { key: "eye",        label: "Офтальмология",     file: "materials/svg/icon-svc-eye.svg" },
    { key: "ear",        label: "Лор",               file: "materials/svg/icon-svc-ear.svg" },
    { key: "pill",       label: "Терапия",           file: "materials/svg/icon-svc-pill.svg" },
    { key: "cross",      label: "Скорая помощь",     file: "materials/svg/icon-svc-cross.svg" },
    { key: "doctor",     label: "Консультация",      file: "materials/svg/icon-svc-doctor.svg" },
    { key: "clipboard",  label: "Карта/документ",    file: "materials/svg/icon-svc-clipboard.svg" },
    { key: "microscope", label: "Лабораторные",      file: "materials/svg/icon-svc-microscope.svg" },
  ];

  const KEYS = new Set(ICONS.map(i => i.key));
  const BY_KEY = Object.fromEntries(ICONS.map(i => [i.key, i]));

  function imgMarkup(key, size) {
    const item = BY_KEY[key];
    if (!item) return "";
    const s = size || 24;
    return `<img src="${item.file}" alt="" width="${s}" height="${s}" style="display:inline-block">`;
  }

  // Универсальный рендер: если value — известный ключ, отрисовываем <img>;
  // иначе считаем, что это эмодзи/строка и выводим как текст.
  function renderServiceIconHTML(value, size) {
    const s = size || 24;
    if (value && KEYS.has(value)) return imgMarkup(value, s);
    const text = value || "⚕️";
    return `<span style="font-size:${Math.round(s * 0.85)}px;line-height:1;display:inline-flex;align-items:center;justify-content:center;width:${s}px;height:${s}px">${text}</span>`;
  }

  window.SERVICE_ICONS = ICONS;
  window.SERVICE_ICON_KEYS = KEYS;
  window.renderServiceIconHTML = renderServiceIconHTML;
  window.serviceIconSvgMarkup = imgMarkup;
  window.isKnownServiceIcon = (v) => !!v && KEYS.has(v);
})();
