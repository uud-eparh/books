(function () {
    const libId = window.LIB_ID;
    const fill = document.getElementById('progress-fill');
    const status = document.getElementById('progress-status');
    const details = document.getElementById('progress-details');

    // Запускаем скачивание
    fetch(`/download/${libId}/start`, { method: 'POST' });

    // Слушаем SSE
    const es = new EventSource(`/events/download/${libId}`);

    es.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('Progress:', data);

        const pct = data.progress_percent || 0;
        fill.style.width = `${pct}%`;

        const statusMap = {
            pending: `В очереди${data.queue_position ? ` (позиция ${data.queue_position + 1})` : ''}…`,
            downloading: `Скачивание: ${pct.toFixed(1)}%`,
            done: '✅ Готово! Начинается загрузка файла…',
            error: `❌ Ошибка: ${data.error || 'неизвестно'}`,
        };
        status.textContent = statusMap[data.status] || data.status;

        if (data.status === 'downloading') {
            const parts = [];
            if (data.pieces_total) {
                parts.push(`${data.pieces_done}/${data.pieces_total} piece-ов`);
            }
            if (data.eta_seconds) {
                parts.push(`~${Math.round(data.eta_seconds)} сек`);
            }
            if (data.elapsed_seconds) {
                parts.push(`прошло ${data.elapsed_seconds.toFixed(1)} сек`);
            }
            details.textContent = parts.join(' · ');
        } else {
            details.textContent = '';
        }

        if (data.status === 'done') {
            es.close();
            // Автоскачивание
            window.location = `/download/${libId}/file`;
        }
        if (data.status === 'error') {
            es.close();
        }
    };

    es.onerror = (e) => {
        console.error('SSE error', e);
        status.textContent = '⚠️ Потеряно соединение с сервером…';
    };
})();