import assert from "node:assert/strict";

import {
  LOGIN_ROUTE,
  loginRedirectFor,
  sessionUserFromResponse,
} from "../src/modules/core/authRouting.js";

assert.equal(loginRedirectFor("#/", false), LOGIN_ROUTE);
assert.equal(loginRedirectFor(LOGIN_ROUTE, false), null);
assert.equal(loginRedirectFor("#/", true), null);

const directUser = { username: "dani", role: "admin" };
assert.equal(sessionUserFromResponse(directUser), directUser);
assert.equal(sessionUserFromResponse({ user: directUser }), directUser);
assert.equal(sessionUserFromResponse({}), null);

console.log("auth routing tests passed");
