(function () {
    function formatRegistrationNumber(value) {
        const cleaned = (value || '').trim().replace(/[-\s]/g, '');
        if (cleaned.length === 10 && /^\d+$/.test(cleaned)) {
            return `${cleaned.slice(0, 4)}-${cleaned.slice(4, 7)}-${cleaned.slice(7)}`;
        }
        return (value || '').trim();
    }

    function ensureToastContainer() {
        let container = document.getElementById('toastContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toastContainer';
            document.body.appendChild(container);
        }
        return container;
    }

    function getToastIcon(type) {
        if (type === 'success') {
            return '<i class="fas fa-check-circle" style="color: #8BDFDD;"></i>';
        }
        if (type === 'error' || type === 'danger') {
            return '<i class="fas fa-exclamation-circle text-danger"></i>';
        }
        if (type === 'warning') {
            return '<i class="fas fa-exclamation-triangle text-warning"></i>';
        }
        return '<i class="fas fa-info-circle text-info"></i>';
    }

    window.showToast = function (message, type = 'info') {
        const container = ensureToastContainer();
        const toast = document.createElement('div');
        toast.className = 'premium-toast';
        toast.innerHTML = `${getToastIcon(type)} <span>${message}</span>`;
        container.appendChild(toast);

        setTimeout(() => {
            toast.classList.add('show');
        }, 50);

        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => {
                toast.remove();
                if (container.children.length === 0) {
                    container.remove();
                }
            }, 300);
        }, 3000);
    };

    window.DUCrackCommon = {
        formatRegistrationNumber,
    };
})();