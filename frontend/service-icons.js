// Общий набор SVG-иконок услуг в стилистике сайта (line-style, currentColor).
// Используется и в админке (выбор иконки при создании/редактировании услуги),
// и на booking.html (отображение карточек услуг).
(function () {
  const STROKE = 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';

  const ICONS = [
    { key: "tooth", label: "Стоматология",
      body: '<path d="M14 3c-3 0-5 1.5-5 4 0 1.6.4 2.7.9 3.7.6 1.4 1 3 1.2 4.6.3 2 .8 4 1.4 5.5.5 1.2 1.6 1.2 2.1 0 .6-1.3.9-2.6 1.1-3.5.2-1 .4-1.2 1.3-1.2s1.1.2 1.3 1.2c.2.9.5 2.2 1.1 3.5.5 1.2 1.6 1.2 2.1 0 .6-1.5 1.1-3.5 1.4-5.5.2-1.6.6-3.2 1.2-4.6.5-1 .9-2.1.9-3.7 0-2.5-2-4-5-4-1.6 0-2.4.5-3.1.9-.5.3-1.1.3-1.6 0C16.4 3.5 15.6 3 14 3z"/>'
    },
    { key: "syringe", label: "Анализы",
      body: '<path d="M4 24l4-4M3 23l5 5M9 19l4 4M11 17l4 4M14 14l7-7M21 3l4 4M17 7l4 4M19 5l4 4"/>'
    },
    { key: "child", label: "Педиатрия",
      body: '<circle cx="14" cy="9" r="4"/><path d="M6 24c0-4.4 3.6-8 8-8s8 3.6 8 8"/>'
    },
    { key: "brain", label: "Неврология",
      body: '<path d="M14 4c-3.9 0-7 3-7 7 0 2.5 1.2 4.7 3 6.1V22h8v-4.9c1.8-1.4 3-3.6 3-6.1 0-4-3.1-7-7-7z"/><path d="M11 22h6"/>'
    },
    { key: "heart", label: "Кардиология",
      body: '<path d="M14 24c-7-6-10-10-10-14a5 5 0 0 1 10-2 5 5 0 0 1 10 2c0 4-3 8-10 14z"/>'
    },
    { key: "eye", label: "Офтальмология",
      body: '<path d="M2 14c4-7 8-9 12-9s8 2 12 9c-4 7-8 9-12 9S6 21 2 14z"/><circle cx="14" cy="14" r="3"/>'
    },
    { key: "ear", label: "Лор",
      body: '<path d="M10 25c-3-3-5-7-5-12a8 8 0 0 1 16 0c0 4-2 6-5 6-1 0-1 1-1 2 0 2-2 3-5 4z"/>'
    },
    { key: "pill", label: "Терапия",
      body: '<g transform="rotate(-30 14 14)"><rect x="3" y="11" width="22" height="6" rx="3"/><path d="M14 11v6"/></g>'
    },
    { key: "cross", label: "Скорая помощь",
      body: '<rect x="11" y="4" width="6" height="20" rx="2"/><rect x="4" y="11" width="20" height="6" rx="2"/>'
    },
    { key: "doctor", label: "Консультация",
      body: '<circle cx="14" cy="8" r="4"/><path d="M6 24c0-4.4 3.6-8 8-8s8 3.6 8 8"/><path d="M11 16v3a3 3 0 0 0 6 0v-3"/>'
    },
    { key: "clipboard", label: "Карта/документ",
      body: '<rect x="6" y="6" width="16" height="20" rx="2"/><path d="M10 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M10 14h8M10 18h8M10 22h5"/>'
    },
    { key: "microscope", label: "Лабораторные",
      body: '<path d="M14 4v8M11 12h6"/><path d="M8 22h12M11 22v-2a3 3 0 0 1 6 0v2"/><circle cx="14" cy="16" r="3"/>'
    },
  ];

  const KEYS = new Set(ICONS.map(i => i.key));
  const BY_KEY = Object.fromEntries(ICONS.map(i => [i.key, i]));

  function svgMarkup(key, size) {
    const item = BY_KEY[key];
    if (!item) return "";
    const s = size || 24;
    return `<svg width="${s}" height="${s}" viewBox="0 0 28 28" fill="none" ${STROKE}>${item.body}</svg>`;
  }

  // Универсальный рендер: если value — известный ключ, отрисовываем SVG;
  // иначе считаем, что это эмодзи/строка и выводим как текст.
  function renderServiceIconHTML(value, size) {
    const s = size || 24;
    if (value && KEYS.has(value)) return svgMarkup(value, s);
    const text = value || "⚕️";
    return `<span style="font-size:${Math.round(s * 0.85)}px;line-height:1;display:inline-flex;align-items:center;justify-content:center;width:${s}px;height:${s}px">${text}</span>`;
  }

  window.SERVICE_ICONS = ICONS;
  window.SERVICE_ICON_KEYS = KEYS;
  window.renderServiceIconHTML = renderServiceIconHTML;
  window.serviceIconSvgMarkup = svgMarkup;
  window.isKnownServiceIcon = (v) => !!v && KEYS.has(v);
})();
