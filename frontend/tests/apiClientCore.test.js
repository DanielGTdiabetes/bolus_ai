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
assert.equal(mock401.getCalls(), 1);
assert.equal(cleared, 1);
assert.equal(logoutCalls, 1);

console.log("api client core tests passed");
