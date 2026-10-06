# Phase C analytics definitions

## Authority, scope, and identity

- `WEEKLY` is authoritative for current operational state.
- `LOG_HISTORY` is authoritative for recorded changes.
- `MASTER_DATA` is derived and optional; it is used only for discrepancy checks.
- Python never writes to the workbook and never runs workbook refreshes or VBA.
- `RowID` is the opaque permanent logical-record identity. It follows a real record through Week relocation and is never parsed for Week, BlockID, Year, or any other business meaning.
- `BlockID` is the opaque current physical Week-block identity. It may change while RowID remains unchanged.

A **stable identity row** has a nonblank `RowID`. An **analytically populated operational row** has both a stable identity and either meaningful shipment payload or explicit cancellation evidence (`RowStatus = Cancelled` or a CancelReason). Shipment payload excludes Week, RowID, BlockID, ordinary/default statuses, helper columns, and formulas. This distinction is necessary because the verified legacy workbook contains generated unused rows with RowIDs.

Generated identity-only rows do not affect totals, denominators, voyage counts, cancellations, customer/service analytics, or the Phase C quality report. Rows with shipment payload but no RowID are excluded from analytics and reported by validation.

Voyage-instance identity is the exact normalized current tuple `(Vessel, Voyage, BlockID)`. All three values must be present for voyage-level grouping, schedule analysis, comparison, and voyage counts. RowID is not substituted for voyage identity. Incomplete identities remain in current row-level totals, are reported as quality issues, and are not merged into an ambiguous voyage.

At workbook load, Python builds one current operational RowID index. Each LOG_HISTORY row receives separate current-context fields when its RowID resolves uniquely. Original historical Vessel, Voyage, BlockID, Week, and booking context remain unchanged. A duplicate current operational RowID marks related history as ambiguous; Python does not guess. Empty generated reservation slots do not participate in this index.

## Shared filtering

`FilterContext` centralizes current filters for Vessel, Voyage, explicit Week, ETA Month, ETA Year, SVC, POL, POD, CUSTOMER, LoadStatus, and RowStatus. Text matching trims whitespace and is case-insensitive. Week is numeric and comes only from the editable Week field.

- `ETA Month` is `YYYY-MM`, derived only from a valid ETA. Month numbers 1–12 are also accepted by the filtering API.
- `ETA Year` is derived only from a valid ETA. Missing or invalid ETA is `Unknown`. ETA Year is not an authoritative operational Year.
- `History Month`, `History Quarter`, and `History Year` derive only from `LOG_HISTORY.Timestamp`.

No ID-pattern filtering or ID-derived time dimension is used.

## LoadStatus and cancellation

LoadStatus normalization is:

- blank or whitespace → `Loaded` for backward compatibility;
- case-insensitive `Loaded` → `Loaded`;
- case-insensitive `Empty` → `Empty`;
- any other nonblank value → `Unknown` plus a Warning quality issue.

An otherwise valid active row with `Unknown` LoadStatus contributes to total Containers, TEU, GWT, and 20ft/40ft quantities. It contributes only to the corresponding Unclassified split and never to Loaded or Empty.

If `RowStatus` is `Cancelled` after trimming and case normalization, all operational quantities are zero. The row remains available for cancellation counts, reasons, and audit views.

## Current calculations

All quantities use normalized `CNTR AMT`, `SIZE`, `GWT`, LoadStatus, and RowStatus. Missing or malformed numeric inputs calculate as zero and remain separately reportable as input-quality problems. Workbook formula caches are retained for diagnostics, but are not analytical truth.

- Summary = CNTR AMT for an active row; otherwise 0.
- TEU = CNTR AMT × 1 when SIZE = 2, or CNTR AMT × 2 when SIZE = 4; otherwise 0.
- TS = GWT for an active row; otherwise 0.
- Total Containers = active CNTR AMT, including Unknown LoadStatus.
- Loaded/Empty/Unclassified Containers = Total Containers allocated by normalized LoadStatus.
- Total 20ft/40ft = active CNTR AMT where SIZE is 2/4, independent of LoadStatus.
- Loaded/Empty 20ft/40ft = the size quantity allocated by LoadStatus.
- Total TEU = active calculated TEU, including Unknown LoadStatus.
- Loaded/Empty/Unclassified TEU = Total TEU allocated by LoadStatus.
- Total GWT = active GWT, including Unknown LoadStatus.
- Loaded/Empty/Unclassified GWT = Total GWT allocated by LoadStatus.

All division is safe: a zero or unavailable denominator returns unavailable, never infinity or an invented zero percentage.

## Ratios and voyage load profile

Per complete voyage instance, the load profile exposes identity/schedule metadata, all container/TEU/GWT totals and splits, equipment counts, active/cancelled row counts, and these definitions:

- Loaded % = Loaded Containers / Total Containers.
- Empty % = Empty Containers / Total Containers.
- Classified Containers = Loaded Containers + Empty Containers.
- Empty Container Ratio = Empty Containers / Classified Containers.
- Classified TEU = Loaded TEU + Empty TEU.
- Empty TEU Ratio = Empty TEU / Classified TEU.
- Loaded GWT / Loaded TEU = Loaded GWT / Loaded TEU.
- Loaded GWT / Loaded Container = Loaded GWT / Loaded Containers.
- Total GWT / Total TEU = Total GWT / Total TEU.
- Total, Loaded, and Empty 20ft/40ft share use the corresponding known 20ft + 40ft quantity as denominator.
- Cancellation Rate = Cancelled rows / all analytically populated rows in scope.

Unknown cargo stays visible in Total and Unclassified values. It is deliberately excluded from classified-empty ratios.

Reusable aggregation supports voyage, vessel, explicit Week, ETA Month, ETA Year, POL, POD, SVC, customer, and other observed columns. Customer/service/route results use normalized case/whitespace grouping only; no fuzzy entity merging is performed.

## Distribution and anomaly semantics

Weight and anomaly baselines are empirical. With a sufficient sample, the engine calculates P10, P25, median, P75, P90, and IQR. It does not apply universal good/bad thresholds.

Explainable anomaly signals include Empty TEU Ratio, ETA revision count, cumulative ETA movement, Week change count, cancellation rate, weight intensity, and 40ft share. High-direction signals are flagged above P90; two-sided signals may also be flagged below P10. `High` means the observation also exceeds the 1.5×IQR fence; otherwise the category is `Watch`.

Default anomaly minimum sample is 8. Distribution views default to 5. If the relevant group has fewer usable observations, no anomaly is emitted. Every emitted result contains entity, metric, actual value, group baseline, reason, category, and sample size. There is no composite risk score.

## History normalization and voyage-event deduplication

Raw `LOG_HISTORY` stays queryable and unchanged. Normalization retains `_raw_OldValue` and `_raw_NewValue`. Legacy `[bulk edit]` means the historical value is unavailable; it is never interpreted as a real business value or schedule date.

The voyage-event dataset collapses only exact duplicate events with a complete key:

`effective current BlockID + effective current Vessel + effective current Voyage + Field + exact Timestamp + normalized OldValue + normalized NewValue`

For uniquely resolved RowIDs, effective current context comes from authoritative WEEKLY. For unresolved legacy events, the historical event context is used. Ambiguous RowIDs are retained individually and never guessed. The retained row includes `_source_event_count`. RowID is intentionally not part of this voyage-level key, allowing the same bulk transition recorded on many booking rows at the exact same timestamp to count once. Different transitions, timestamps, or voyages remain separate. Events missing any identity component or Timestamp are retained individually and never merged.

No timestamp tolerance is used. Real-history inspection found both exact timestamp batches and legitimate-looking events separated by a few seconds; without a reliable transaction/batch identifier, fuzzy time grouping could merge distinct actions.

## Schedule reliability

Only deduplicated, material ETA changes contribute to movement:

- both old and new values must be meaningful valid dates;
- old and new must differ;
- blank → value is initial population, not a revision;
- value → blank remains a history event but is not ordinary schedule movement;
- legacy `[bulk edit]` movement is unavailable.

Per voyage:

- Original ETA = earliest reconstructable ETA state.
- Current ETA = authoritative current WEEKLY ETA when available, otherwise the latest reconstructable history state.
- Net ETA Movement = Current ETA − Original ETA in days; positive means later.
- Cumulative ETA Movement = sum of absolute material ETA movements.
- ETA Revision Count = number of deduplicated material ETA revisions.
- Largest Single ETA Revision = signed movement with greatest absolute magnitude.
- First/Last ETA Revision Timestamp = first/last material revision timestamp.

Aggregates include voyage count, percent delayed, mean/median net movement, median revision count, median cumulative movement, and largest observed revision. Net movement and volatility remain separate.

Phase F presentation adds an availability safeguard without changing those Phase C calculations: vessel/service ETA aggregates include only voyage instances with at least one comparable, non-legacy old/new ETA event. If an entity has no such event, its schedule movement, revision, and volatility values display as **Unavailable**, not zero. This prevents absence of history from being presented as stable schedule performance.

## Week rollover

Week analytics use explicit numeric Week values only. Current Week comes from WEEKLY, never BlockID or RowID. Original Week is the earliest valid old Week, with initial new value or current Week as a conservative fallback.

- Week Change Count counts deduplicated valid old → new transitions where values differ.
- Net Week Movement = Current Week − Original Week when both are numeric.
- malformed or legacy-unavailable events are retained as unavailable events and do not create numeric movement.
- first/last Week change timestamps cover valid material changes only.

Aggregates expose percent of voyages moved, percent moved exactly one Week, percent moved multiple Weeks, median change count, and unavailable-event counts.

The Phase F vessel/service Week-rollover percentage similarly requires at least one comparable, non-legacy old/new Week event for the voyage instance. Missing Week history displays as **Unavailable**.

## Customer, service, route, and time analytics

- Customer: voyage count, booking/row count, active/cancelled rows, quantities, equipment/load mix, average active booking size, cancellation rate, share of overall TEU, POD/voyage distributions, and ETA-month trend data.
- Service: quantities and mix, cancellation rate, mean/median ETA movement, revision count, cumulative-movement volatility, Week rollover rate, customer count, major observed PODs, and voyage drilldown structures.
- Destination: observed POD + POD CODE quantities, load/equipment mix, voyage count, and observed service mix. No route relationship is invented.
- Current periods: explicit Week, ETA Month, ETA Year, with quantities, voyage/cancellation counts, and optional trailing averages only after the full requested window exists.
- History periods: Timestamp-derived History Month, Quarter, and Year, using raw or deduplicated event counts as explicitly requested.

## Booking churn and cancellation

Booking churn is a transparent set of counts by RowID, Booking number, or complete voyage identity. It tracks material changes to CNTR AMT, Week, ETA, ETD, Cut-Off, RowStatus, LoadStatus, SIZE, and GWT. Timeline-ready raw events remain available. No churn score is generated.

Current cancellation state and historical cancellation timing are kept distinct:

- current cancelled rows, rates, reasons, and current period/entity breakdowns come from WEEKLY;
- cancellation transition events require RowStatus changing from a non-cancelled value to `Cancelled` in LOG_HISTORY;
- historical trends use the event Timestamp.

## Data-quality issues and severity

Each issue is a row with Severity, Category, Message, RowID, BlockID, Vessel, Voyage, Booking number, Field, Raw Value, and Suggested Correction.

- `Critical`: identity collisions or impossible negative source/calculated analytical results that can materially corrupt aggregation.
- `Warning`: a likely operational data problem requiring review, including incomplete voyage identity, missing/invalid equipment or weight, invalid dates/Week, unexpected status, inconsistent voyage metadata, or orphan history.
- `Information`: useful audit context that may be legitimate, such as duplicate-looking bookings, missing POD CODE context, or formula-cache mismatch.

Blank LoadStatus is valid and is not reported. Generated identity-only rows are outside the operational quality population. Duplicate-looking bookings are informational because equipment splits can legitimately repeat a booking number.

## Cargo evolution and forecast readiness

Cargo-evolution foundations reconstruct recorded quantity and size state at 14, 7, 3, and 1 days before ETD by rolling later history transitions backward from current WEEKLY state. Cancelled rows are excluded.

No historical state is fabricated:

- Containers are published only when every voyage row has reconstructable CNTR AMT at the checkpoint.
- TEU is published only when every row also has reconstructable supported SIZE.
- known partial totals, row/checkpoint completeness, incomplete-row count, and the reason remain visible.
- missing ETD, missing history, malformed transition values, or legacy `[bulk edit]` old values make the affected reconstruction incomplete.

Forecast readiness reports complete checkpoints, comparable complete voyages in the same exact normalized SVC, and history completeness. Defaults require at least 3 complete checkpoints and 3 comparable historical voyages. `Ready for method evaluation` does not produce a forecast; Phase C deliberately implements no ML or confident prediction.

## Comparison engine

The backend accepts 2–5 distinct complete voyage-instance keys and compares Containers, Loaded/Empty percentages, 20ft/40ft, TEU, GWT, weight intensity, ETA revisions, net/cumulative movement, Week changes, and cancellations. Missing, incomplete, or unknown identities are rejected rather than merged.
