export const LOGIN_ROUTE = "#/login";

export function loginRedirectFor(route, hasUser) {
    return !hasUser && route !== LOGIN_ROUTE ? LOGIN_ROUTE : null;
}

export function sessionUserFromResponse(data) {
    const candidate = data?.user ?? data;
    return candidate && typeof candidate.username === "string" ? candidate : null;
}
