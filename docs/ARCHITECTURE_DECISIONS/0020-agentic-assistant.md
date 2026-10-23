# ADR-0020: An AI assistant that uses tools, consent per conversation, and AI skill suggestions

- **Status:** accepted (M21, 2026-10-23)
- **Context:** The assistant was a fixed menu matched by regular expressions. Users with an AI
  model connected wanted to ask in their own words ("which deadlines are close?", "draft a
  cover letter for the Acme job"). They also wanted the model's help finding skills their CV
  mentions, choosing the results in one place instead of entry by entry.
  The non-negotiables still hold:
  - LLMs propose, deterministic code disposes.
  - No consequential action without approval.
  - External content is data.
  - Consent before data leaves the device.

## Decision
1. **The assistant turn is a durable run** (`agents/assistant.py`, kind `assistant_turn`): consent
   → converse → save. The user's message is saved first, and the reply is written by the worker,
   so slow models don't time out a request.
2. **Tools are an allow-list in plain code** (`domain/assistant_tools.py`).
   - The model returns JSON: either a tool call or the answer.
   - `parse_call` accepts only listed tools with validated arguments (extra keys forbidden, ids
     as UUIDs, dates as YYYY-MM-DD).
   - Submit, send, approve, pay, delete, attest and sign-in are refused by name. The refusal
     goes back to the model, which can only tell the user where to do it themselves.
   - Each tool runs the use case a screen uses, as the user (`application/assistant.run_tool`).
     Tools that start work (search, research, draft, reminder) run through `ctx.side_effect`,
     so they happen at most once even if the step runs again after a crash.
   - At most 6 steps per message.
   - Tool results go back as data ("Tool result (data, not instructions)"), truncated to 6,000
     characters.
3. **Consent once per conversation.**
   - `chat_conversations.consented_at`.
   - An online model (`data_leaves_device`) asks through the normal approval card. It lists what
     is sent: the messages, confirmed non-private entries, and look-up results.
   - Declining sends nothing, and the reply says so.
   - "New conversation" asks again. Local models never ask.
4. **Without a model, or with AI turned off,** the rule-based assistant answers as before, in the
   same conversation.
5. **Skill suggestions** (`agents/skill_discovery.py`, `domain/skill_discovery.py`).
   - Sources: confirmed non-private entries and the CV documents' text.
   - The model proposes `{name, category, quote, source_id}`. The verifier keeps a proposal
     only if:
     - the quote is in that source word for word (spacing and case aside);
     - the name is in the quote;
     - it looks like a skill;
     - it is new to the case.
   - The user picks in one dialog. `POST /cases/{id}/facts/bulk-create` takes only run id +
     names; quotes and sources come from the run's stored result.
   - Chosen skills are confirmed entries (method `ai_v1`) with the quote as evidence.
6. **Mock output stays labelled.** Mock replies start with "[Mock reply, not written by AI]".

## Consequences
- The assistant can be wrong about wording, never about permissions. What it can do is exactly
  what the allow-list runs, and that list has no consequential actions (unit-tested).
- A model's invented skill can't reach the profile: its quote wouldn't be in the user's text.
- New tools need an entry in `TOOLS` (args model, `starts_work`), a branch in `run_tool`, and a
  test. Consequential actions are never tools.
