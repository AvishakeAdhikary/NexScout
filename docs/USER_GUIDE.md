# NexScout user guide

This guide is for anyone who wants to *use* NexScout. You don't need to be technical. If you
want to change NexScout's code, see [DEVELOPMENT.md](DEVELOPMENT.md) instead.

NexScout helps you apply for PhD positions and jobs **truthfully**:
- It reads your CV.
- It finds positions that fit you, and explains why.
- It researches each position, with sources.
- It writes your documents only from facts you confirmed.
- It can fill in and submit application forms for you, with your permission.

It never invents anything about you. When it doesn't know something, it asks you.

---

## 1. Install (about 10 minutes, once)

NexScout runs on your own computer, inside **Docker Desktop**, a free program that runs apps
in their own safe box. NexScout's data stays on your computer.

1. **Install Docker Desktop** from <https://www.docker.com/products/docker-desktop/> (free for
   personal use). Open it once and wait until it says *Engine running*. On Windows it may ask
   you to restart the computer; that's normal.
2. **Get NexScout.** Choose one:
   - **Windows app (easiest):** go to
     [Releases](https://github.com/AvishakeAdhikary/NexScout/releases/latest), download
     `NexScout-Setup-<version>.exe` and install it. Windows may say *"Windows protected your
     PC"* because the app isn't code-signed yet. Click **More info → Run anyway**. Open
     NexScout and choose **Easy**.
   - **Any computer (Windows, Mac or Linux):** download `nexscout-easy-<version>.zip` from
     [Releases](https://github.com/AvishakeAdhikary/NexScout/releases/latest) and unzip it.
     Open the `easy` folder and double-click the start file for your computer:
     - Windows: **Start NexScout.cmd**
     - Mac: **Start NexScout.command**. The first time, right-click it and choose **Open**.
     - Linux: run `./start-nexscout.sh`
3. The first start downloads NexScout, which takes a few minutes. Then your browser opens
   NexScout (the Windows app shows it in its own window).

> **Keep the file `easy/.env`** (zip version), or keep using the same Windows account (app
> version). It holds the secret key that protects your saved passwords and tokens. Back it up
> together with your data.

To **stop** NexScout:
- Windows app: menu **NexScout → Stop NexScout**.
- Zip version: **Stop NexScout.cmd** on Windows, or `./start-nexscout.sh stop` on Mac and
  Linux.

Closing the window doesn't stop NexScout. It keeps working in the background, so the autopilot
and reminders keep running. Your data is kept between runs.

## 2. First steps

1. **Create your account.** Your email and a password, only on your computer.
2. **Create a case**, for example "PhD in machine learning" or "Data jobs in Germany". Choose
   what you're looking for: PhD, employment or both.
3. **Add your CV** (Documents). Drop it on the page, or several files at once. NexScout
   suggests profile entries and shows exactly where in your CV each one came from. Add your
   **letters of recommendation** too: each recommender becomes a private reference entry.
   Nothing a letter says about you is turned into a claim.
4. **Check your profile.** Accept, edit or reject each suggestion. Tick several entries, or
   **Select all** in a section, to accept, reject, delete or make them private in one go. *Only
   confirmed entries are ever used*, and private entries never leave your profile.
   - A project or certificate can be **part of** a job or study (Edit → Part of). NexScout
     links them for you when your CV says so, and letters and statements mention them together.
   - Got a better CV, or a newer NexScout? **Documents → Read again** replaces only the
     suggestions you haven't reviewed. What you accepted, rejected or edited stays as it is.
   - Deleted a file but kept its suggestions? The Profile page tells you, and **Remove them**
     clears those suggestions in one go.
5. Optional: **choose an AI model** (Settings → AI models). You need one for letters and
   statements. Use your own key (OpenAI, Anthropic, Gemini, or any OpenAI-compatible service
   such as NVIDIA NIM), or a free model on your computer (Ollama, LM Studio). NexScout asks
   before your data goes to an online AI. Resumes and CVs are built **without** AI.
   Made a typo? **Edit** fixes the name, model, address or key in place. If a model "ran out of
   room for its answer", tick **Skip the model's thinking** (NVIDIA NIM) or raise **Longest
   answer**.

The case dashboard shows a **Getting started** checklist until you're done.

## 3. Find and prepare

- **Choose where to look** (Settings → Where to look). Nothing is searched until you pick
  sources.
  - Turn on job boards, company career pages and university portals from the list. Filter it
    by country or type, or use "Turn on all shown".
  - **Add any careers page by its address.** NexScout works out what kind of page it is and
    shows how many positions it found. Examples: a company's Greenhouse or Lever page, a
    university's vacancy feed, or Work in Finland.
  - Already use career-ops? **Import your `portals.yml`.**
  - Some well-known sites (for example Duunitori, EURAXESS and LinkedIn) don't allow automated
    searching. They're listed with a link so you can search there yourself.
  - Each source shows when it last worked and how many positions it had. Use **Check** to test
    one.
- **Tell NexScout what fits** (Profile → Preferences).
  - **Countries to look in** and **Countries to leave out**: type a country, or choose a group
    such as EU, Nordic countries or Europe.
  - **Search words** (for example *machine learning, computer vision*) and words to leave out
    (for example *intern*).
  - If you need a visa, say so. NexScout looks for "visa sponsorship" or "work permit support"
    in each posting and tells you what it found.
  - **Funding** for PhDs: any, funded preferred, or funded only.
  - **The most you can spend up front** (application fees, deposits), in your own currency,
    for example 150000 INR. Fees in other currencies are converted with the European Central
    Bank's daily rates.
- **PhD Opportunities / Job Opportunities.** Press **Find opportunities**. Each position shows
  how well it fits you and what's missing. Duplicates from different sites are merged.
- **Research and prepare.** NexScout reads the posting and its linked pages: requirements,
  deadlines, supervisors. Every finding quotes its source.
- **Documents.** Statement of purpose, research proposal, CV, resume, cover letter, inquiry
  email. Everything NexScout writes comes from your confirmed profile.
  - Anything it doesn't know is shown as **[[PLACEHOLDER: …]]**. Fill those in yourself.
  - The format follows the country of the position (for example a German *Lebenslauf* on A4),
    or uses an international format when the country isn't known.

## 4. Apply

On a position, start an **application** and choose your documents. NexScout opens the
application page in a browser, fills it in, and shows you every field and a screenshot.
**Nothing is sent until you approve.** After you approve, it submits once and records the
site's confirmation.

If the site shows a **CAPTCHA** ("I'm not a robot") or asks you to **sign in**, NexScout stops.
It never solves CAPTCHAs or signs in for you. You have two options:
- Open the page, apply yourself, then mark the application as submitted.
- Windows app (developer mode), or a local install: press **Open a browser window for me**.
  NexScout fills the form in a window on your screen. You solve the CAPTCHA and press submit,
  and NexScout records the confirmation.

## 5. Get notified on your phone

**Account → Notifications on your phone.** Each option shows step-by-step instructions:
- **Telegram:** create a bot with @BotFather (2 minutes), paste its token, and send the pairing
  code to your bot. You get **Approve / Reject** buttons, and you answer questions by replying.
- **Discord:** your own bot sends you direct messages with buttons.
- **WhatsApp:** through Meta's official WhatsApp Business Cloud API. This needs a Meta
  developer account and a public web address for replies. NexScout never uses unofficial
  WhatsApp apps, because those get numbers banned.
- **Slack, email or a webhook:** notifications with a link to NexScout.

Only the account you paired can approve anything. You can set quiet hours, choose which
notifications you get, pause a channel and send a test message.

## 6. Autopilot: let NexScout work for you

**Autopilot** (in each case) lets NexScout work on its own within rules you set. It searches
for positions, picks the ones that fit, researches them, writes your documents, and fills in
the forms. When it needs you, it asks on your phone:
- "Your resume needs: contact details" → reply with them once, and they're reused next time.
- "Northwind asks: Why are you interested in this role?" → reply with your answer.
- "Submit your application to Northwind?" → **Approve** or **Reject**.

You decide:
- Which **steps** it may do on its own, how good a fit must be, and how many positions and
  submissions per day.
- Which countries, and which organizations never to apply to.
- **Whether it may submit without asking you each time.** This is off by default. Turning it
  on shows the exact statement you agree to, and NexScout stores it with the date. Even then
  it only submits when:
  - your documents are complete;
  - every answer came from you;
  - the site doesn't forbid automation;
  - the daily limit isn't reached.

**Stop everything:** press **Stop everything** on the Autopilot page, or send **STOP** from
your paired chat.

## 7. Staying out of trouble online

NexScout is built so that using it doesn't break any site's rules for you:
- It **never** automates sites whose terms forbid bots, such as LinkedIn, Indeed, Glassdoor,
  ZipRecruiter and Handshake. Pages whose robots.txt asks automated tools to stay away are
  treated the same way. For those, it prepares your documents and tells you to apply there
  yourself.
- It never solves CAPTCHAs, never signs in for you, and never gets around a site's
  protections.
- It goes slowly: at most one autopilot visit per site every 10 minutes, a daily limit you
  set, and at most one application per position.
- Messaging uses each provider's official API only.
- Everything it writes about you comes from your confirmed facts. Missing details become
  questions or placeholders, never guesses.

You are still responsible for what you submit, so read what NexScout prepared. That's why
approvals show you everything first.

## 8. Keeping NexScout up to date

- **Windows app (2.3.0 or newer):** updates itself. When a new version is downloaded, you're
  asked to restart. Choose *Later* and it updates the next time you close NexScout. Menu →
  NexScout → *Check for updates…* checks right away.
- **Easy install (2.3.0 or newer):** NexScout shows a notice when there's a new version.
  Double-click **Update NexScout** in your NexScout folder. It downloads the new version,
  checks it isn't damaged, keeps your data and your `.env` file, starts the new version and
  removes the old one.
- **2.2.0 or older:** download the newest version from the GitHub releases page once and
  install it over the old one. Your data is kept.

## 9. Your data

- Everything stays on your computer (or your own server). Your saved keys and tokens are
  encrypted.
- **My Profile → Export profile** saves one case as a `.nexscout` file: every entry, the mind
  map, snapshots, relationships and your documents. **Your cases → Import a profile** turns that
  file into a new case, on this computer or another one. Nothing existing is changed, and no
  keys or passwords are ever in the file.
- On the mind map, **Auto-arrange** places everything neatly again (your renames and hidden
  items stay). Snapshots you no longer need can be deleted under **Saved snapshots**.
- **Account → Download my data** gives you everything as a .zip file.
- **Account → Delete my account** removes everything permanently.

## 10. Something isn't working?

| Problem | Try this |
|---|---|
| "Docker Desktop is needed" | Install Docker Desktop, open it once, wait for *Engine running*, then start NexScout again. |
| The first start takes long | The first start downloads about 2 GB. Later starts take seconds. |
| The browser says "can't reach this page" | Wait a minute and reload: NexScout is still starting. |
| "Another NexScout is already set up on this computer" | You have both the Windows app and the zip version. Keep using the one named in the message, or stop and remove it first (`docker compose down` in its `easy` folder keeps your data). |
| A port is already in use | Edit `NEXSCOUT_PORT` in `easy/.env` (for example 3100), then start again and open that port. |
| Letters say "Mock text, not written by AI" | You haven't chosen an AI model yet (Settings → AI models). |
| A Telegram or Discord test fails | Check the token. On Discord, share a server with your bot. |
| Something else | Settings → Diagnostics shows what's running. Logs: run `docker compose logs` in the `easy` folder, or see the app's logs folder. |

Known limits are listed honestly in [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).
