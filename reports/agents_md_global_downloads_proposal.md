# Proposal: AGENTS.md changes for phase 2 and 3 downloads (D55)

**Status: proposed, not applied.** AGENTS.md is Riley's to change. Ticket #13 (map #6) agreed the design in D55; this lists the wording that follows from it. Principle as in `reports/agents_md_forecast_proposal.md`: AGENTS.md states the rule and points to the decision, and the detail stays in `docs/decisions.md`.

---

## 1. Data safety → Downloads (replace the last sub-bullet, and edit the lead-in)

**Now (lead-in):**
> - **Downloads:** GRIB, day-sized requests, each tracked in the SQLite manifest …

**Proposed:**
> - **Downloads:** GRIB, each request sized as below and tracked in the SQLite manifest …

**Now (last sub-bullet):**
> - Global and regional runs stay one day per request unless gate 1 changes it.

**Proposed (replaces it, and adds two bullets):**
> - **Global runs (D55):** one campaign serves phases 2 and 3; there are no separate regional downloads. Pressure levels go in half-monthly requests (at most 16 days, ~104 GB); single levels one month per request, or up to 3 months once the cost check in D55 has passed. A smaller size is fine; a larger one needs Riley's OK. Check each size with the CDS's cost estimate before a campaign.
> - **One large request on `/staging` at a time:** download → verify → ingest → verify the Zarr → delete the raw GRIB, then download the next. The next request is still submitted to the CDS while this happens (D39).
> - **Validation boxes** stay as they are (the existing sub-bullet).

## 2. Phase 2, step 1 "Regional data" (replace)

**Now:**
> 1. **Regional data.** About 20°×20° each, 2021–2025:
>    - Regions: …
>    - Pressure levels (with `cc`) and single levels, hourly unless phase 1 showed 3-hourly is enough. [ASK] if over 50 GB.

**Proposed:**
> 1. **Regional data: a global pilot year (D55).** Global, hourly, 2023, pressure levels (with `cc`) and single levels, from the CDS. The regions below are cut from it at ingest; they are not downloaded separately. [ASK] before the pilot year starts (~2.4 TB of raw GRIB over its run, one request on `/staging` at a time).
>    - Regions, about 20°×20° each: Tibetan Plateau/Qinghai, Atacama, SW USA/Baja, Hawaii, Canaries/Iberia, South Africa, SE Australia, Timau/Nusa Tenggara.
>    - The NCAR equivalence test (D55) runs alongside, without blocking anything.

The "(2021–2025)" goes: the pilot is 2023, and gate 2 decides the rest.

## 3. Gate 2 (one clause)

**Now:** "…and a recommendation on cadence (hourly or 3-hourly) and number of years for phase 3. [ASK]"

**Proposed:** no change to the sentence. Add: "The pilot year is hourly, so a 3-hourly choice means subsetting it, not downloading again."

## 4. Phase 3, Downloader (replace)

**Now:**
> - **Downloader:** a resumable service fetching one global day per request, then verify → ingest → delete raw. There's no data cap, but respect CDS etiquette and concurrency limits.

**Proposed:**
> - **Downloader:** a resumable service fetching global requests sized as in D55 (the remaining years after gate 2), then verify → ingest → delete raw. It keeps polling the CDS while an ingest runs. There's no data cap, but respect CDS etiquette and concurrency limits.

## 5. Phase 3, "Done when" (replace one bullet)

**Now:** "the phase 2 regions match the global run cell for cell;"

**Proposed:** "the pilot year's products are unchanged in the global run (same requests, same code), and the regions show no seams;"

The old check assumed two separate downloads that could differ. With one campaign they are the same data, so the check would pass by construction.

## 6. Working with Riley → [ASK] (no wording change, one note)

The rule "any download campaign over 50 GB or 24 h, unless already listed with its size in an approved plan" still applies. D55 lists the sizes, which is what the phase 2 [ASK] approves. The 104 GB test request in D55 is approved already.

## 7. Environment (a number)

"One global day of hourly profiles is about 7 GB in GRIB" is 6.5 GB measured (`reports/cds_throughput_one_job.md` §6.2). It can stay as it is, or become "6.5 GB".
