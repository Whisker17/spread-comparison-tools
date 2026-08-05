# ADR 0003: Alert on real-time engine health via generic HTTPS webhook

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-08-05 |
| Issue | [WHI-819](https://linear.app/whisker-personal/issue/WHI-819) |

## Context

After WHI-846/847/848 the process can stay healthy (HTTP 200, systemd active)
while serving entirely stale rows: a disconnected venue WebSocket, a stopped
sweep group, a desynced book, or a lagged mid. WHI-819 requires an alert channel
the owner will actually see. An alert nobody reads is worse than none — it
creates false confidence.

The deploy target is a single VPS with one operator. There is no existing
PagerDuty / Prometheus / Alertmanager stack.

## Decision

1. **Alert channel = generic HTTPS webhook** whose URL is a secret
   (`ALERT_WEBHOOK_URL` in `/etc/spread-comparison/env`). The payload is a small
   JSON object with both:
   - `content` / `text` — human-readable one-liner (Discord-compatible `content`,
     Slack-ish `text`)
   - structured fields (`status`, `code`, `severity`, `target`, `message`, …)
2. **When the URL is unset**, the evaluator still runs and surfaces open alerts
   on `GET /health` → `engine.alerts`, and logs a WARNING per fire/resolve so
   `journalctl` remains a fallback channel. No silent drop of evaluation.
3. **Thresholds and cadence** live in typed `config/monitor.yaml` (unvalidated
   defaults pending DESIGN.md §2). The webhook URL is never in YAML.
4. **Liveness vs data**: `GET /health` stays HTTP 200 when degraded or data-stale
   (load balancers must not kill a process serving most venues).
   `GET /health/data` returns **503** when the data probe fails — that is the
   uptime check that catches "up but stale."

## Alternatives considered

| Option | Why rejected (this time) |
| --- | --- |
| **Prometheus + Alertmanager** | Correct multi-service path, but no existing scrape stack on the VPS; would be the only series. Revisit if multi-host lands. |
| **Email only** | Slow, often filtered; no structured payload for future automation. |
| **Telegram bot as hard dependency** | Forces another secret + bot setup; a generic webhook can target Telegram gateways, Discord, Slack, Feishu, or webhook.site for verification. |
| **journald-only** | Free, but does not page; kept as the no-URL fallback log path. |

## Verification

End-to-end delivery is covered offline by a MockTransport test that asserts the
webhook receives a `firing` payload. On the host, a one-shot check:

```bash
# Point at a temporary capture (webhook.site, Discord channel, etc.)
export ALERT_WEBHOOK_URL='https://…'
# Restart so the env is loaded, then force a probe failure or wait for a real
# condition; journal should show "alert webhook delivered".
sudo systemctl restart spread-comparison
journalctl -u spread-comparison -n 50 --no-pager | grep -i alert
```

## Consequences

- **Positive:** One secret, works with any receiver the operator already watches.
- **Positive:** Health body remains the source of truth for "what is wrong" even
  when the webhook is down.
- **Negative:** No multi-channel routing, no ack/silence UI — operator must
  configure the sink.
- **Revisit when:** multi-host deploy or a shared metrics stack appears.

## References

- Runbook: `docs/DEPLOYMENT.md` § Monitoring
- Config: `config/monitor.yaml`
- Implementation: `spread_compare/monitor.py`
