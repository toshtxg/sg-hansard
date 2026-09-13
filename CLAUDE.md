# Working agreements for this repo

## Do not poll, watch, or schedule anything unless asked

Default to doing the work, reporting the result, and ending the turn.

Specifically, unless I ask for it in that conversation:

- **Do not subscribe to PR activity.** Opening a PR is not a request to watch it.
- **Do not schedule check-ins, wake-ups, reminders, cron jobs, or routines** of
  any kind — no `send_later`, no `create_trigger`, no self-scheduled follow-ups.
- **Do not poll** for external state (CI, deploys, queues) on a timer.

Each wake-up costs me a turn's worth of usage, and this repo has no CI that
runs on pull requests — the only workflow is the ingest cron, which triggers on
`schedule` and `workflow_dispatch`. So there is nothing on a PR here for a
check-in to discover: it will find the same state every time and bill me for it.

If you have already scheduled something and find there is nothing to act on,
cancel it — do not re-arm it. One no-op check is enough to conclude there is
nothing to watch.

Tell me what you'd watch and why, and let me ask for it.
