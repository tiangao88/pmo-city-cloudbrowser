# D14 — CRM SME Validation Evidence (2026-08-29)

Status: **COMPLETE — read-only CRM validation recorded; Tigo acceptance
recorded; W2 D14 closed.**

## Scope and method

- **SME / acceptance:** Tigo (Lee re-validates in a later phase when
  available).
- **Application:** GetUnlatch CRM, accessed through the live CloudBrowser
  slot.
- **Interaction constraint:** attached to the existing first tab. No tab was
  created or evicted, and no CRM data was modified.
- **Programme:** **Les Jardins de Vaucelles — TAVERNY**.
- **Programme filter:** `idp=1596334675`.
- **Data path:** CRM's authenticated read-only data endpoint, paginated at 100
  rows per request.

## Verified August result

The programme-filtered response contained **630 raw rows**. Contact IDs were
then deduplicated before counting.

| Measure | Result |
|---|---:|
| Raw programme rows | 630 |
| Distinct contact IDs | 348 |
| Distinct contacts modified in August 2026 (`last_modification_date`) | **6** |
| Distinct contacts created in August 2026 (`lead_created`) | 4 |
| Distinct contacts in the modified-or-created union | **6** |
| Overlap between the modified and created groups | 4 |

The answer to the scoped CRM question is therefore **6 distinct contacts**.
The six August-modified contacts were:

1. Cheklat — modified August 1
2. Tiop — created and modified August 1
3. Marie-laure Regnault — created and modified August 3
4. Guyon — modified August 7
5. Thierry PECOT — created and modified August 22
6. Aussel romain — created and modified August 28

An unfiltered tenant-wide cross-check found 28 distinct contacts in the
August modified-or-created union. That is a separate tenant-wide reference
figure; it is not substituted for the Vaucelles programme result.

## Workflow and gaps

The executed D14 validation covered authenticated CRM access, programme
selection/filtering, paginated read-only retrieval, August modification
counting, and contact-level result inspection. The following follow-ups are
recorded rather than silently treated as complete:

- The CRM date-filter UI/API semantics were not used as the source of the
  count because the tested date-filter request shapes were ignored by the
  application. The count was calculated from the complete programme-filtered
  result set instead.
- A broader CRM rehearsal of opening a lead detail, qualifying/updating a
  lead, and contacting a lead remains a W3 workflow follow-up; this D14 record
  deliberately performed no write operation.
- No CRM write, qualification, contact action, or other business mutation was
  performed during this evidence run.

## Acceptance record

Tigo accepted the D1/D14 pilot evidence in the 2026-08-29 continuation:

- D1: corrected pilot identities, per-user labels/isolation, rotated internal
  Neko credentials, and qualified agent queue timeout are recorded in
  `79-d1-pilot-evidence.md`.
- D14: the scoped CRM result and read-only workflow evidence are recorded in
  this document.
- W2 closure: all retained W2 rows are green; D13 screen-follow and strict
  authenticated-surface continuity remain explicitly scoped to W3.
