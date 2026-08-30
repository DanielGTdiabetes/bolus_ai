import assert from "node:assert/strict";
import { createApiFetch } from "../src/lib/apiClientCore.js";

const buildMockFetch = (status = 200) => {
  let calls = 0;
  let lastOptions = null;
  const fetchImpl = async (_url, options) => {
    calls += 1;
    lastOptions = options;
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => ({}),
      text: async () => ""
    };
  };
  return { fetchImpl, getCalls: () => calls, getLastOptions: () => lastOptions };
};

const { fetchImpl: fetchWithToken, getLastOptions: getTokenOptions } = buildMockFetch(200);
const apiFetchWithToken = createApiFetch({
  fetchImpl: fetchWithToken,
  getToken: () => "token-123",
  clearToken: () => {},
  onLogout: () => {},
  onMissingToken: () => {},
  resolveUrl: (path) => path,
  isPublicEndpoint: () => false
});

await apiFetchWithToken("/api/test");
assert.equal(getTokenOptions().headers.Authorization, "Bearer token-123");

let missingTokenNotified = 0;
const { fetchImpl: fetchNoToken, getLastOptions: getNoTokenOptions } = buildMockFetch(200);
const apiFetchNoToken = createApiFetch({
  fetchImpl: fetchNoToken,
  getToken: () => null,
  clearToken: () => {},
  onLogout: () => {},
  onMissingToken: () => {
    missingTokenNotified += 1;
  },
  resolveUrl: (path) => path,
  isPublicEndpoint: () => false
});

await apiFetchNoToken("/api/test");
assert.ok(!("Authorization" in getNoTokenOptions().headers));
assert.equal(missingTokenNotified, 1);

let logoutCalls = 0;
let cleared = 0;
const mock401 = buildMockFetch(401);
const apiFetch401 = createApiFetch({
  fetchImpl: mock401.fetchImpl,
  getToken: () => "token-456",
  clearToken: () => {
    cleared += 1;
  },
  onLogout: () => {
    logoutCalls += 1;
  },
  onMissingToken: () => {},
  resolveUrl: (path) => path,
  isPublicEndpoint: () => false
});

await assert.rejects(() => apiFetch401("/api/test"), /Sesión caducada/);

const publicUnauthorizedResponse = { status: 401 };
const apiFetchPublic401 = createApiFetch({
  fetchImpl: async () => publicUnauthorizedResponse,
  getToken: () => null,
  clearToken: () => {},
  onLogout: () => {},
  onMissingToken: () => {},
  resolveUrl: (path) => path,
  isPublicEndpoint: path => path === "/api/auth/login"
});
assert.equal(
  await apiFetchPublic401("/api/auth/login", { method: "POST" }),
  publicUnauthorizedResponse
);
assert.equal(mock401.getCalls(), 1);
assert.equal(cleared, 1);
assert.equal(logoutCalls, 1);

let activeToken = "expired-token";
let refreshCalls = 0;
const retryAuthorizations = [];
const apiFetchWithRefresh = createApiFetch({
  fetchImpl: async (_url, options) => {
    retryAuthorizations.push(options.headers.Authorization);
    const status = options.headers.Authorization === "Bearer refreshed-token" ? 200 : 401;
    return { ok: status === 200, status };
  },
  getToken: () => activeToken,
  clearToken: () => {},
  onLogout: () => {},
  onMissingToken: () => {},
  refreshToken: async () => {
    refreshCalls += 1;
    activeToken = "refreshed-token";
    return true;
  },
  resolveUrl: (path) => path,
  isPublicEndpoint: () => false
});

const refreshedResponse = await apiFetchWithRefresh("/api/test");
assert.equal(refreshedResponse.status, 200);
assert.equal(refreshCalls, 1);
assert.deepEqual(retryAuthorizations, ["Bearer expired-token", "Bearer refreshed-token"]);

let refreshFailureLogoutCalls = 0;
const apiFetchWithFailedRefresh = createApiFetch({
  fetchImpl: async () => ({ ok: false, status: 401 }),
  getToken: () => "expired-token",
  clearToken: () => {},
  onLogout: () => {
    refreshFailureLogoutCalls += 1;
  },
  onMissingToken: () => {},
  refreshToken: async () => false,
  resolveUrl: (path) => path,
  isPublicEndpoint: () => false
});

await assert.rejects(() => apiFetchWithFailedRefresh("/api/test"), /Sesión caducada/);
assert.equal(refreshFailureLogoutCalls, 1);

console.log("api client core tests passed");
