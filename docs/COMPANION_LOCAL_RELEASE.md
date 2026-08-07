# Companion local release

This change set is intentionally complete in the repository but not deployed. It must be validated with the user's real Nightscout and food-photo data before NAS, Render/Neon, or APK rollout.

## Delivered behavior

- Persistent `CompanionEpisode` lifecycle: `open`, `notified`, `monitoring`, `snoozed`, `dismissed`, `resolved`, `expired`.
- Persistent preferences for enabled state, notification intensity, quiet hours, and repeat intervals.
- One glucose-monitor job owns proactive glucose episodes. The duplicate trend schedule and trend-message micro-bolus calculation are disabled.
- Current companion situations: hypo risk, hypo recovery, sustained high, rapid rise, rapid drop, post-meal high, stale/unavailable data.
- Imported MyFitnessPal meals become persistent pending-meal episodes and include the configured pre-bolus wait; low/falling or stale glucose suppresses a numeric wait.
- Telegram actions persist in the database: acknowledge, snooze, and dismiss.
- Web home and notification center share the same episode state and expose the same actions.
- The same dismissed condition cannot reappear until it has first resolved.
- Restaurant mode is hidden by default, removed from Android navigation, and removed from LLM-callable tools. Its database/code remains for one compatibility release.
- Vision returns per-item carbohydrate intervals and records whether portion evidence came from an optional scale, the 16.5 cm red insulin pen, a plate, or visual estimation only.
- The scale is never required. Pen evidence is only considered reliable when the full pen is visible and approximately in the food plane.
- Telegram and web vision share the same core food-analysis instructions.
- ISF verification uses correction-only events over the configured insulin duration, local-time buckets, CGM-quality exclusions, at least five clean events, an observed central range, and discarded-event reasons.
- ISF verification cannot change settings. Automatic/daily ISF suggestion scheduling is removed.

## Safety invariants

1. The companion never calculates or publishes an insulin dose.
2. A correction remains a deliberate action in the deterministic bolus calculator, which must re-check current BG, IOB, limits, and settings.
3. The LLM estimates food and explains context; it is not the dose authority.
4. Missing or stale CGM data suppresses glucose conclusions.
5. Acknowledgement, snooze, and dismissal survive process restart and NAS/Render failover because they are database state.
6. ISF results are evidence for review, never an automatic profile mutation.

## Local verification performed

- Python compile check for `backend/app`.
- Targeted backend tests for notifications, companion lifecycle/evaluation, vision reference evidence, vision API, and ISF analysis.
- PostgreSQL Alembic SQL generation for revision `7c9d1e2f3a4b`.
- Frontend API-client test and production Vite build.

The complete legacy backend suite still contains unrelated pre-existing failures: restaurant endpoint tests use the old form payload, snapshot tests expect a removed global alias, several Python 3.14 tests assume an implicit event loop, and a forecast-onset assertion fails independently of this release. These are not deployment blockers for the companion paths, but should be handled in a separate cleanup change set.

Android compilation was not run because this checkout has no Gradle wrapper and Gradle is not installed in the local environment. The Android edits in this release are deliberately small: remove the restaurant destination and stop marking the foreground-service notification as additionally ongoing.

## Deployment checklist — not executed

1. Back up NAS PostgreSQL and confirm NAS→Neon sync is healthy.
2. Generate and inspect the migration SQL against a schema clone.
3. Apply the additive migration to Neon.
4. Deploy Render in standby mode and verify `/api/companion/episodes`, preferences, and schema health without enabling its bot.
5. Apply the migration to NAS PostgreSQL and deploy the NAS container.
6. Keep companion Telegram delivery in `quiet` mode for an observation period; verify acknowledgements and failover persistence.
7. Build the web static bundle through the normal production script; do not manually mix hashed assets.
8. Build and test the Android APK on a device, including MyFitnessPal exit detection and notification dismissal.
9. Only then move companion intensity from `quiet` to `balanced`.

## Vision model evaluation before switching defaults

Use a labelled personal set of at least 100–200 representative meals: weighed when possible, pen-visible examples, no-reference examples, mixed dishes, sauces, and low-light photos. Compare providers/models on:

- median absolute carbohydrate error;
- percentage of labels inside the returned range;
- calibration by reported confidence;
- item identification and hidden-fat error;
- latency, failure rate, and cost.

Do not choose a model from generic rankings alone. Promote a new default only if it improves the user's own dataset and structured-output reliability.
