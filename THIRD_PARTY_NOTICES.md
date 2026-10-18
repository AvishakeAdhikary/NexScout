# Third-party notices

NexScout's own code is covered by its license. This file lists third-party work that NexScout
ports or embeds as data (code dependencies installed by `uv` and `npm` carry their own licenses
in their packages).

## career-ops

- **Project:** https://github.com/career-ops-hq/career-ops
- **Pinned commit:** `340a53b1bd4e9728237c6b964f3828589b1fc14e`
- **What NexScout uses:**
  - The job-source provider logic in `providers/*.mjs`: endpoints, request shapes, pagination
    and field mapping. It is ported to Python in `backend/src/nexscout/integrations/sources/`
    (`ats.py`, `boards.py`).
  - The preconfigured companies and boards in `templates/portals.example.yml` and
    `docs/SUPPORTED_JOB_BOARDS.md`, converted into `catalog.yaml` by `scripts/build_catalog.py`.
  - The visa-sponsorship phrase lists from `scan.mjs`, extended in
    `backend/src/nexscout/domain/signals.py`.
- **License:** MIT

```
MIT License

Copyright (c) 2026 Santiago Fernández de Valderrama

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## ISO 3166-1 country data

`backend/src/nexscout/domain/geo_data/countries.json` was generated once by
`scripts/gen_countries.py` with these tools:
- [pycountry](https://github.com/pycountry/pycountry), which ships the Debian `iso-codes`
  data (LGPL-2.1-or-later). It provides the country codes and names.
- [pycountry-convert](https://github.com/jefftune/pycountry-convert) (MIT). It provides the
  continents.

Neither tool is a runtime dependency. Country codes and names are facts from the ISO 3166-1
standard. NexScout added the aliases, local names, cities and groups itself.

## ECB euro foreign exchange reference rates

NexScout fetches the daily rates from
https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml to compare stated fees with your
budget. The ECB publishes these rates for information purposes only.
