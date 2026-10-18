# ADR-0016: Countries as ISO codes, eligibility signals from posting text, budget in any currency

- **Status:** accepted (M15, 2026-10-19)
- **Context:** Countries were free text. Preferences stored "Germany", the autopilot asked
  for "DE", and its filter rejected everything. Users need include and exclude lists covering
  every country, plus groups such as the EU and the Nordics. Applicants without a visa need to
  know whether a posting sponsors one, requires existing work rights, or requires a local
  language. Applicants on a budget need fees compared in their own currency.

## Decision
1. **ISO 3166-1 alpha-2 everywhere** (`domain/geo.py`, `geo_data/countries.json`).
   - The data covers all 249 assigned codes, with aliases, local names and major cities. It
     also defines 15 groups: EU, EEA, Schengen, Nordics, Baltics, DACH, Benelux, UK & Ireland,
     Iberia, Europe and the five other continents.
   - `normalize_list` turns what users type into codes or group keys ("Finland" → `FI`,
     "Nordic countries" → `NORDICS`). The autopilot API rejects unknown entries.
   - `resolve_location(text)` reads countries and remote scope from posting locations.
     Ambiguous city words ("Nice", "Reading", "Bath") count only when written with a capital
     letter.
   - A posting stores `country_codes`, `location_text` and `remote_scope`.
2. **Include and exclude lists.**
   - In preferences and the autopilot policy, a posting in an excluded country is a blocker.
     So is one outside the included area.
   - A posting with no resolvable country is an **info** note, not a guess.
   - The web uses one `CountryPicker` component: search, chips and group buttons.
3. **Signals are read, never guessed** (`domain/signals.py`, pure). Matching looks for these
   phrases in the posting's own text:
   - visa sponsorship offered or refused (career-ops vocabulary, extended for the EU);
   - work authorization required;
   - relocation support;
   - local-language fluency (fi, sv, de, nl, fr, da, no, it, es, pl, pt);
   - funded or unfunded;
   - fees, with amount and currency.

   Each signal keeps the words that triggered it. A posting that says nothing gives "not
   stated", which is a gap or a note, never assumed in the user's favour.
4. **Matching consequences.**
   - Sponsorship refused while the user needs it: blocker. Not mentioned: info.
   - Authorization required outside the user's authorized countries: gap (blocker in strict
     mode).
   - A required language the user doesn't list: gap (blocker in strict mode).
   - Academic positions when the user chose "funded preferred": unfunded is a gap. With
     "funded only" it is a blocker. Funding not described: info.
5. **Budget** (`max_upfront_cost` + `budget_currency`).
   - Fees found in the text are converted with the **ECB daily reference rates**
     (`fx_rates`, refreshed once a day by the worker; they include INR) and summed.
   - Over budget is a blocker. If a rate is missing, the fee is reported unconverted
     (`cost_unconverted`, info). An academic position that states no cost and isn't funded gets
     `cost_not_stated` (info): check before applying.

## Consequences
- Country filters work across preferences, matching, sync filtering and the autopilot, and
  show readable names in messages.
- Signals are lexical. A posting that phrases sponsorship in an unusual way is reported as
  "not stated", and the user can read the source text. False "offered" readings are limited
  by checking negative phrases first.
- ECB rates are for information. Real amounts differ by bank and date, so messages say
  "about".
