document.addEventListener('DOMContentLoaded', () => {
    const toggleBtn = document.getElementById('themeToggle');
    if (!toggleBtn) return;
    
    // Set initial icon based on applied theme
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    updateToggleIcon(currentTheme);
    
    toggleBtn.addEventListener('click', () => {
        const activeTheme = document.documentElement.getAttribute('data-theme') || 'light';
        const newTheme = activeTheme === 'light' ? 'dark' : 'light';
        
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
        updateToggleIcon(newTheme);
    });
    
    function updateToggleIcon(theme) {
        const icon = toggleBtn.querySelector('i');
        if (icon) {
            if (theme === 'dark') {
                icon.className = 'fas fa-sun';
            } else {
                icon.className = 'fas fa-moon';
            }
        }
    }
});
