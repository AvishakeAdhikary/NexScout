# ADR-0013: Notification channels (official APIs, outbox, paired identity)

- **Status:** accepted (M11, 2026-10-17)
- **Context:** The user wants NexScout to keep working while they are away, and to reach them on
  Telegram, Discord, WhatsApp, Slack, email or their own automation. They want to approve
  submissions and answer questions from there ("human-in-the-loop autopilot"). OpenClaw was
  reviewed as a reference (MIT). Its pairing and allowlist ideas fit, but its WhatsApp channel
  uses an unofficial WhatsApp Web client (Baileys). That client breaks WhatsApp's terms and gets
  numbers banned, and the user explicitly asked to stay out of trouble.

## Decision
1. **Official provider APIs only.**

   | Channel | Outbound | Inbound | Pairing |
   |---|---|---|---|
   | Telegram Bot API | `sendMessage` with inline buttons | long polling with `getUpdates`, so no public URL is needed | the user sends `/start CODE` to their own bot |
   | Discord | bot REST: a DM with button components | the official Gateway (only the non-privileged DIRECT_MESSAGES intent): INTERACTION_CREATE and DM MESSAGE_CREATE | the bot DMs a code, and the user types it into NexScout |
   | WhatsApp Cloud API (Meta Graph) | interactive reply buttons, or an approved template outside the 24-hour window | a webhook verified with `X-Hub-Signature-256` | the user sends `PAIR CODE` |
   | Slack | incoming webhook | none (links only) | none |
   | Email | SMTP | none (links only) | none |
   | Generic webhook | a POST signed with HMAC-SHA256 over `"<timestamp>.<body>"` | none (links only) | none |

   Each user brings their own bot or app, so NexScout never holds a shared credential.
2. **Transactional outbox.**
   - `notifications._notify` inserts the notification and, in the same transaction, one
     `notification_deliveries` row per matching active channel.
   - The worker claims due rows with `SKIP LOCKED` and a lease. It sends channels in parallel
     but messages within a channel in order.
   - Transient errors (429/5xx) retry with exponential backoff and jitter, up to 8 attempts.
     Permanent errors (other 4xx) are dead-lettered.
   - Five consecutive dead letters open the circuit: the channel goes to `error` and the user
     sees it.
   - Quiet hours (in the user's time zone) defer delivery to the end of the quiet period.
3. **Paired identity and single-use actions.**
   - A one-time code (hashed, valid for 30 minutes) binds a channel to one chat, user or phone.
     Messages from anyone else are ignored, and unpaired senders get no reply, so there is
     nothing to probe.
   - Buttons carry a random `channel_actions` id. It is valid only from the paired identity of
     the same channel, expires after 7 days, and is single-use: pressing one button also uses
     up its sibling.
   - A decision goes through the same `runs.decide` use case as the web UI. It runs as the
     owner in a tenant (RLS) session and is audited as `approval.decided_via_channel`.
4. **Answers, not guesses.**
   - When a form asks something NexScout has no answer for, it sends a `question`
     notification, once per question per application.
   - A reply to that message (Telegram `reply_to_message`, WhatsApp `context.id`, Discord
     message reference) is stored as the user's own answer (`record_answer`) and reused.
5. **Inbox and idempotency.**
   - Every provider event is recorded in `channel_inbound_events` under a provider event id:
     Telegram `update_id`, Discord interaction or message id, WhatsApp message id, and for raw
     webhook bodies their sha256. A replayed event does nothing.
   - The WhatsApp webhook route is unauthenticated by design. It can only INSERT the raw body.
     The worker verifies the signature with the channel's app secret before acting, then drops
     the raw body.
6. **Secrets.**
   - Credentials are stored as one AES-GCM sealed JSON blob, bound to the owner and purpose
     `channel:<kind>`. They are write-only in the API.
   - The webhook signing secret is shown once.
   - The WhatsApp verify token is derived from the master key (HMAC), so the API can answer
     Meta's handshake without reading user data.
   - Webhook URLs are SSRF-checked on save and again at every send.

## Consequences
- Telegram and Discord work behind NAT with no public URL. WhatsApp replies need a public
  HTTPS URL (a tunnel or a server); sending works without one.
- Chat apps refuse buttons that link to localhost, so local links appear as text. Setting
  `NEXSCOUT_PUBLIC_WEB_URL` to an HTTPS address enables an "Open in NexScout" button.
- Tests fake every provider at the HTTP layer (`httpx.MockTransport`) and run a real WebSocket
  Gateway. Live verification with real credentials needs the user's own bots and is listed in
  KNOWN_LIMITATIONS.
