export function navigate(hash) {
    window.location.hash = hash;
}

export function redirectToLogin() {
    navigate('#/login');
}
