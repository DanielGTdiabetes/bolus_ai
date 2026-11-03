# Gemini migration - 3 November 2026

Google's account notice and deprecation page announce that `gemini-2.5-flash`
will redirect to `gemini-3.5-flash-lite` on 1 December 2026. The same page maps
`gemini-2.5-pro` to `gemini-3.8-flash` on that date.

- Default chat, food vision and voice transcription: `gemini-3.5-flash-lite`.
- Complex queries previously routed to Pro: `gemini-3.8-flash`.
- Environment values and saved user settings using the listed retired IDs are
  resolved centrally in `app/core/gemini_models.py`; other explicit IDs remain
  configurable. Old database records do not require a destructive migration.
- The raw settings API also normalizes these two vision model fields, preserving
  unknown fields, profile ratios and concurrency versions. The browser cache is
  migrated on read/save so the mobile IA / Visión panel shows the replacement
  even when it initially loads saved settings offline.
- Android Companion contains no Gemini endpoint or credential. Its portal uses
  the backend; NAS/Render and the web bundle deliver this change without an APK.
- The Render Dockerfile now builds the current portal, as the NAS already does,
  instead of serving the stale checked-in bundle. The standalone Render static
  service continues using its usual Vite build.

## API compatibility

The pinned legacy `google-generativeai==0.5.4` client cannot retain Gemini 3
function IDs and thought signatures. The four Gemini consumers now use a small
async REST transport over the existing httpx dependency. It retains the complete
model content in chat history, returns matching function names and IDs, removes
retired sampling controls, and uses `thinkingLevel` instead of `thinkingBudget`.
Tool requests use medium thinking; Flash-Lite one-shot requests use minimal.
No provider credentials are put in URLs or provider error bodies in logs.

The router still executes at most one tool per round. Additional calls in the
same response receive explicit non-execution results with their original IDs.
The model can then request the next action sequentially. The deterministic bolus
engine, IOB protections, confirmation buttons and database writes are unchanged.

## Validation and deployment

Local: 68 focused tests pass across the migration, router, vision, bolus, IOB
and settings suites; the Vite production build passes. Regression tests cover complete
signature preservation, call IDs, multiple calls, image/audio encoding,
configuration migration, and failed requests without history mutation.

Pre-deployment NAS tests use the existing Google key and isolated subprocesses:
both models complete a harmless echo tool round trip with real signatures/IDs;
Flash-Lite identifies a synthetic image with valid JSON and transcribes a known
synthetic English sentence through the production voice service. These are protocol
checks, not a clinical or food-estimation accuracy evaluation. No user treatment
is registered by the tests. A representative personal meal dataset is still
needed to measure nutritional accuracy.

Deploy backend compatibility before changing an instance's model environment.
Keep NAS primary and Render backup roles intact. Verify `/healthz`,
`/api/vision/status`, the effective Flash/Pro/voice model values, and bot mode.
Retain the preceding container image and deployment reference for rollback.
Rolling back code also requires restoring prior model environment values;
the old endpoint is only a temporary rollback before Google's redirect date.

Sources:
- https://ai.google.dev/gemini-api/docs/deprecations
- https://aistudio.google.com/docs/whats-new-gemini-3.6
- https://aistudio.google.com/docs/models/gemini-3.5-flash-lite
