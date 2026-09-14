/**
 * Корзина книг на localStorage.
 *
 * API:
 *   Cart.get()        → number[]
 *   Cart.add(libId)   → void
 *   Cart.remove(libId)→ void
 *   Cart.toggle(libId)→ boolean (true, если теперь в корзине)
 *   Cart.has(libId)   → boolean
 *   Cart.clear()      → void
 *   Cart.count()      → number
 *   Cart.onChange(cb) → void (подписка на изменения)
 *
 * Ключ в localStorage: 'flibusta_cart'
 * Формат: JSON-массив чисел
 */
(function (global) {
    const STORAGE_KEY = 'flibusta_cart';
    const MAX_BOOKS = 20;

    const listeners = [];

    function _read() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return [];
            const arr = JSON.parse(raw);
            if (!Array.isArray(arr)) return [];
            // Фильтруем только числа
            return arr.filter((x) => typeof x === 'number');
        } catch (e) {
            console.error('Cart: failed to read', e);
            return [];
        }
    }

    function _write(arr) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(arr));
            _notify();
        } catch (e) {
            console.error('Cart: failed to write', e);
        }
    }

    function _notify() {
        const cart = _read();
        listeners.forEach((cb) => {
            try {
                cb(cart);
            } catch (e) {
                console.error('Cart listener error', e);
            }
        });
    }

    const Cart = {
        get: _read,

        count: function () {
            return _read().length;
        },

        has: function (libId) {
            return _read().includes(libId);
        },

        add: function (libId) {
            const cart = _read();
            if (cart.includes(libId)) return cart;
            if (cart.length >= MAX_BOOKS) {
                alert(`Максимум ${MAX_BOOKS} книг в корзине`);
                return cart;
            }
            cart.push(libId);
            _write(cart);
            return cart;
        },

        remove: function (libId) {
            const cart = _read().filter((x) => x !== libId);
            _write(cart);
            return cart;
        },

        toggle: function (libId) {
            if (this.has(libId)) {
                this.remove(libId);
                return false;
            } else {
                this.add(libId);
                return this.has(libId);
            }
        },

        clear: function () {
            _write([]);
        },

        onchange: function (cb) {
            listeners.push(cb);
        },

        MAX_BOOKS: MAX_BOOKS,
    };

    // Синхронизация между вкладками
    global.addEventListener('storage', (e) => {
        if (e.key === STORAGE_KEY) {
            _notify();
        }
    });

    global.Cart = Cart;
})(window);