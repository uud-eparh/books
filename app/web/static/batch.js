(function () {
    const jobId = window.BATCH_JOB_ID;
    const libIds = window.BATCH_LIB_IDS || [];
    const total = window.BATCH_TOTAL || 0;

    const fill = document.getElementById('progress-fill');
    const status = document.getElementById('progress-status');
    const details = document.getElementById('progress-details');
    const doneCount = document.getElementById('done-count');
    const list = document.getElementById('batch-list');
    const cancelBtn = document.getElementById('cancel-btn');
    const successBlock = document.getElementById('success-block');
    const downloadLink = document.getElementById('download-link');
    const failedInfo = document.getElementById('failed-info');

    // Инициализируем список книг
    const bookItems = new Map(); // lib_id → DOM-элемент
    libIds.forEach((libId) => {
        const li = document.createElement('li');
        li.className = 'batch-item pending';
        li.dataset.libId = libId;
        li.innerHTML = `
            <span class="item-status">⏳</span>
            <span class="item-title">Книга #${libId}</span>
            <span class="item-size"></span>
        `;
        list.appendChild(li);
        bookItems.set(libId, li);
    });

    // Обработка отмены
    cancelBtn.addEventListener('click', async () => {
        if (!confirm('Отменить скачивание?')) return;
        cancelBtn.disabled = true;
        try {
            await fetch(`/api/batch/${jobId}/cancel`, { method: 'POST' });
        } catch (e) {
            console.error('Cancel failed', e);
        }
    });

    // Подключение к SSE
    const es = new EventSource(`/events/batch/${jobId}`);

    es.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('Batch progress:', data);

        if (data.error === 'not_found') {
            status.textContent = '❌ Batch не найден';
            es.close();
            return;
        }

        // Прогресс-бар
        const pct = data.progress_percent || 0;
        fill.style.width = `${pct}%`;
        doneCount.textContent = data.done_books;

        // Статус
        const statusMap = {
            pending: 'Подготовка…',
            downloading: `Скачивание: ${data.done_books} из ${data.total_books}`,
            packing: 'Упаковка в ZIP…',
            ready: '✅ Готово!',
            error: `❌ Ошибка: ${data.error || 'неизвестно'}`,
            cancelled: '⚠️ Отменено',
        };
        status.textContent = statusMap[data.status] || data.status;

        // Детали
        if (data.status === 'downloading') {
            const parts = [];
            if (data.current_lib_id) parts.push(`Сейчас: #${data.current_lib_id}`);
            if (data.failed_lib_ids?.length) parts.push(`Ошибок: ${data.failed_lib_ids.length}`);
            details.textContent = parts.join(' · ');
        } else {
            details.textContent = '';
        }

        // Обновляем состояния книг
        const completed = new Set(data.completed_lib_ids || []);
        const failed = new Set(data.failed_lib_ids || []);

        bookItems.forEach((el, libId) => {
            el.classList.remove('pending', 'done', 'failed', 'current');
            const statusSpan = el.querySelector('.item-status');

            if (completed.has(libId)) {
                el.classList.add('done');
                statusSpan.textContent = '✅';
            } else if (failed.has(libId)) {
                el.classList.add('failed');
                statusSpan.textContent = '❌';
            } else if (data.current_lib_id === libId) {
                el.classList.add('current');
                statusSpan.textContent = '⏳';
            } else {
                el.classList.add('pending');
                statusSpan.textContent = '⌛';
            }
        });

        // Финальные статусы
        if (data.status === 'ready') {
            es.close();
            cancelBtn.style.display = 'none';

            // Информация об ошибках
            if (data.failed_lib_ids?.length) {
                failedInfo.textContent = `Не удалось скачать: ${data.failed_lib_ids.length} книг. Оставшиеся в корзине.`;
            }

            // Скачивание
            downloadLink.href = `/batch/${jobId}/file`;
            successBlock.style.display = 'block';

            // Автоочистка корзины — убираем успешно скачанные
            clearDownloadedFromCart(data.completed_lib_ids || []);

            // Автоскачивание через 1 сек
            setTimeout(() => {
                window.location = `/batch/${jobId}/file`;
            }, 1000);
        }

        if (data.status === 'error' || data.status === 'cancelled') {
            es.close();
            cancelBtn.style.display = 'none';
        }
    };

    es.onerror = (e) => {
        console.error('SSE error', e);
        status.textContent = '⚠️ Потеряно соединение с сервером…';
    };

    // Очистка корзины от уже скачанных книг
    function clearDownloadedFromCart(completedIds) {
        try {
            const raw = localStorage.getItem('flibusta_cart');
            if (!raw) return;
            const cart = JSON.parse(raw);
            if (!Array.isArray(cart)) return;
            const completedSet = new Set(completedIds);
            const remaining = cart.filter((id) => !completedSet.has(id));
            localStorage.setItem('flibusta_cart', JSON.stringify(remaining));
        } catch (e) {
            console.error('Failed to clear cart', e);
        }
    }
})();