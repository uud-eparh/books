/**
 * UI корзины:
 *   - обновляет все кнопки .add-to-cart-btn (по data-lib-id)
 *   - обновляет бейдж в шапке
 *   - показывает плавающую панель
 *   - открывает модалку со списком
 *   - кнопка "Скачать ZIP" → POST /api/batch
 */
(function () {
    const cartBadge = document.getElementById('cart-badge');
    const cartPanel = document.getElementById('cart-panel');
    const cartPanelCount = document.getElementById('cart-panel-count');
    const cartClearBtn = document.getElementById('cart-clear');
    const cartDownloadBtn = document.getElementById('cart-download');
    const cartLink = document.getElementById('cart-link');

    // Модалка
    const modal = document.getElementById('cart-modal');
    const modalList = document.getElementById('cart-modal-list');
    const modalClose = document.getElementById('cart-modal-close');
    const modalClear = document.getElementById('cart-modal-clear');
    const modalDownload = document.getElementById('cart-modal-download');

    // ==== Обновление кнопок .add-to-cart-btn ====
    function updateButtons() {
        document.querySelectorAll('.add-to-cart-btn').forEach((btn) => {
            const libId = parseInt(btn.dataset.libId, 10);
            if (!libId) return;
            const inCart = Cart.has(libId);
            btn.classList.toggle('in-cart', inCart);
            btn.textContent = inCart ? '✓' : '+';
            btn.title = inCart ? 'Убрать из корзины' : 'В корзину';
        });
    }

    // ==== Обновление бейджа и панели ====
    function updateBadge() {
        const count = Cart.count();
        if (cartBadge) {
            cartBadge.textContent = count;
            cartBadge.style.display = count > 0 ? 'inline-block' : 'none';
        }
        if (cartPanel) {
            cartPanel.style.display = count > 0 ? 'flex' : 'none';
        }
        if (cartPanelCount) {
            cartPanelCount.textContent = count;
        }
    }

    // ==== Модалка со списком ====
    async function renderModalList() {
        const cart = Cart.get();
        modalList.innerHTML = '';

        if (cart.length === 0) {
            modalList.innerHTML = '<li class="cart-empty">Корзина пуста</li>';
            return;
        }

        // Загружаем детали через /api/batch/preview?lib_ids=...
        try {
            const res = await fetch(`/api/cart/preview?lib_ids=${cart.join(',')}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            data.items.forEach((item) => {
                const li = document.createElement('li');
                li.className = 'cart-item';
                li.innerHTML = `
                    <div class="cart-item-info">
                        <div class="cart-item-title">${escapeHtml(item.title)}</div>
                        <div class="cart-item-authors">${escapeHtml(item.authors_text || '')}</div>
                    </div>
                    <button class="cart-item-remove" data-lib-id="${item.lib_id}" title="Убрать">×</button>
                `;
                modalList.appendChild(li);
            });

            // Обработчики удаления
            modalList.querySelectorAll('.cart-item-remove').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const libId = parseInt(btn.dataset.libId, 10);
                    Cart.remove(libId);
                    renderModalList();
                });
            });
        } catch (e) {
            console.error('Failed to load cart preview', e);
            modalList.innerHTML = '<li class="cart-empty">Ошибка загрузки списка</li>';
        }
    }

    function escapeHtml(s) {
        if (!s) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function openModal() {
        modal.style.display = 'flex';
        renderModalList();
    }

    function closeModal() {
        modal.style.display = 'none';
    }

    // ==== Скачивание (POST /api/batch) ====
    async function startDownload() {
        const cart = Cart.get();
        if (cart.length === 0) {
            alert('Корзина пуста');
            return;
        }

        try {
            const res = await fetch('/api/batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ lib_ids: cart }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                alert(err.detail || `Ошибка: HTTP ${res.status}`);
                return;
            }
            const data = await res.json();
            closeModal();
            window.location = `/batch/${data.job_id}`;
        } catch (e) {
            console.error('Batch create failed', e);
            alert('Не удалось создать задачу: ' + e.message);
        }
    }

    // ==== Инициализация ====
    function init() {
        // Клик по любой кнопке .add-to-cart-btn (делегирование)
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('.add-to-cart-btn');
            if (!btn) return;
            e.preventDefault();
            const libId = parseInt(btn.dataset.libId, 10);
            if (!libId) return;
            Cart.toggle(libId);
        });

        // Панель
        if (cartDownloadBtn) {
            cartDownloadBtn.addEventListener('click', startDownload);
        }
        if (cartClearBtn) {
            cartClearBtn.addEventListener('click', () => {
                if (confirm('Очистить корзину?')) Cart.clear();
            });
        }

        // Ссылка в шапке → модалка
        if (cartLink) {
            cartLink.addEventListener('click', (e) => {
                e.preventDefault();
                openModal();
            });
        }

        // Модалка
        if (modalClose) modalClose.addEventListener('click', closeModal);
        if (modalClear) {
            modalClear.addEventListener('click', () => {
                if (confirm('Очистить корзину?')) {
                    Cart.clear();
                    closeModal();
                }
            });
        }
        if (modalDownload) modalDownload.addEventListener('click', startDownload);

        // Клик по фону модалки — закрыть
        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) closeModal();
            });
        }

        // Подписка на изменения корзины
        Cart.onchange(() => {
            updateButtons();
            updateBadge();
            if (modal.style.display === 'flex') {
                renderModalList();
            }
        });

        // Первичная отрисовка
        updateButtons();
        updateBadge();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();