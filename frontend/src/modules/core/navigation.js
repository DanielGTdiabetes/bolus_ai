export function navigate(hash) {
    if (window.location.hash === hash) {
        window.dispatchEvent(new Event("hashchange"));
        return;
    }
    window.location.hash = hash;
}

export function redirectToLogin() {
    navigate('#/login');
}
