# Operational GUI Guide

Version: 1.0.0-rc1

## Shared controls

The filter bar applies one centralized Phase C `FilterContext` to Dashboard, the Voyages browser, History, and compatible secondary pages. Vessel, Voyage, Week, and ETA Month are visible by default. ETA Year, SVC, POL, POD, Customer, LoadStatus, and RowStatus are under **More filters**.

**Clear** resets the shared filters. Filter choices are reconciled after Refresh: a valid selection remains selected, while a value that no longer exists is cleared safely.

The header shows the workbook filename, source health, last successful refresh, data-quality counts, and the manual **Refresh** action. If Refresh fails after a successful load, the last successful snapshot remains visible.

## Dashboard

Dashboard is a current operational overview, not a general history dump. It contains:

- Total, Loaded, and Empty Containers;
- Total TEU and GWT;
- known 20ft and 40ft quantities;
- cancelled row count;
- Loaded/Empty/Unclassified cargo by voyage;
- 20ft/40ft equipment mix by voyage;
- TEU by vessel;
- an explainable Needs Attention list;
- recent deduplicated operational changes.

Unclassified cargo remains in Total but is never forced into Loaded or Empty. Cancelled rows remain available for audit and contribute zero operational quantities.

Needs Attention is not a risk score. It presents existing structured quality warnings, unclassified cargo, cancellations, repeated material ETA revisions, Week changes, and Phase C sample-supported anomalies. Every item states the observed reason.

Voyage charts show at most the ten largest voyage instances by current containers. When this limit applies, the Dashboard states how many additional voyages remain accessible on the Voyages page.

## Voyages

The browser contains one row per complete safe identity:

```text
Vessel + Voyage + BlockID
```

Voyage text is never used as the sole identity. When the same Vessel/Voyage text has multiple BlockIDs, the human label receives a small instance suffix. BlockID itself remains hidden from the normal table.

Sort columns by selecting their headers. Select a row and choose **Open voyage**, or double-click the row.

## Voyage Detail

Voyage Detail shows:

- Vessel, Voyage, Week, service, route, ETA, ETD, and Cut-Off;
- current cargo KPIs and Loaded/Empty percentages;
- explicit unclassified cargo context;
- original/current ETA, net and cumulative movement, revision count, largest revision, and Week changes;
- compact cargo breakdowns;
- current booking rows, including cancelled rows and CancelReason;
- grouped voyage history by default, with raw row events available;
- compact voyage-specific data-quality context.

History follows stable RowID across a Week relocation. A pre-move event can therefore appear in the current Voyage Detail even when its historical BlockID differs from the record's current BlockID. The raw event keeps its original physical context; the current context is attached separately.

Positive ETA movement means **later**. No good/bad interpretation is attached. If history cannot support an original ETA, the screen shows **Unavailable** and does not fabricate a movement.

An explicitly opened Voyage Detail is resolved against the complete current snapshot. It intentionally ignores later unrelated global Voyage selections until the user returns to the browser. This keeps the selected voyage stable. Refresh keeps the detail open when that identity still exists; otherwise an intentional unavailable state is shown.

## History Explorer

**Grouped / Operational** is the default. It collapses identical voyage-wide row events using the approved Phase B/C deduplication key and shows how many raw LOG_HISTORY records each grouped event represents.

**Raw Row Events** retains every authoritative LOG_HISTORY row for audit and debugging. Switching modes never mutates the raw history.

Local History controls provide:

- Field;
- User;
- From/To date using `DD.MM.YYYY`;
- case-insensitive, whitespace-safe search across Vessel, Voyage, Booking number, current Customer context, Field, and old/new values.

Search also covers RowID, BlockID, Week, User, and resolved current Vessel/Voyage/Week/BlockID context. Event detail distinguishes the historical event BlockID from current physical context.

Historical dates and filtering use LOG_HISTORY Timestamp only. RowID and BlockID are never parsed. Legacy `[bulk edit]` is presented as **Unavailable**, never as a business value.

## Vessel Analytics

The overview compares current vessel usage: voyages, containers, Loaded/Empty mix, TEU, GWT, equipment, cancellations, ETA movement/revisions, schedule volatility, and Week rollover. Double-click an overview row or use the selector to open a vessel detail.

Vessel detail adds cargo and equipment summaries plus a safe voyage-instance breakdown. Double-click a voyage to open Voyage Detail. If comparable ETA or Week history does not exist, the related schedule statistics show **Unavailable**, not zero.

## Service Analytics

Service Analytics uses `SVC` exactly as stored in the workbook and never invents a service mapping. Blank service values appear explicitly as **Unassigned**. The overview compares cargo, mix, cancellations, customers, and schedule behavior. Selected-service detail shows major observed PODs, customers, and its voyage breakdown.

Observed distributions describe the current data only; they do not imply causation or service quality scores.

## Customers

Customers groups names only through the approved case/whitespace normalization. It does not use fuzzy matching. Blank customer values remain **Unassigned**.

The overview contains current volume, equipment, cancellations, average active-booking size, and share of total TEU. Selected-customer detail adds POD, service, load/equipment mix, voyage activity, and an ETA-month TEU trend when at least two valid ETA periods exist. Sparse trends are identified explicitly.

## Compare

Choose 2–5 voyage instances. Human selectors show Vessel, Voyage, Week, and ETA; the opaque BlockID remains internal. Duplicate selection is rejected, and voyage instances sharing the same Voyage text remain separate.

The comparison matrix covers total/Loaded/Empty containers, total/Loaded/Empty TEU, total/Loaded/Empty GWT, equipment, weight intensity, ETA history, Week changes, and cancellations. Unavailable historical measures remain **Unavailable**. The screen does not declare a winner. Select or double-click a comparison row to open Voyage Detail.

## Data Quality

Data Quality is an operational correction queue built from the structured Phase C quality engine. It shows Critical, Warning, Information, total issue, affected-row, and safely identified voyage counts. Filter by severity/category, search messages and source context, sort the table, and select an issue for its explanation, raw value, identifiers, and suggested correction.

Double-click a quality issue, or choose **Open related voyage**, when the issue has a complete `(Vessel, Voyage, BlockID)` identity. Python reports issues only; it does not repair Excel. Blank LoadStatus remains valid and means Loaded. Invalid date-formatted values such as `20260913` remain visible as invalid-date issues and are not reinterpreted.

## Cross-page drill-down and Back behavior

Vessel Analytics, Service Analytics, Customers, Compare, and Data Quality can open the existing Voyage Detail screen using safe composite identity. The Back button returns to the originating analytical page. This navigation uses the existing `ApplicationState` snapshot and does not invoke Refresh or reload Excel.

## CSV export

The five Phase F pages can export their current visible or filtered analytical table to a user-selected local `.csv` file. Internal presentation keys are excluded; Data Quality includes RowID and BlockID only because they are useful for audit/correction. An empty result is handled without creating a file. Export never writes to the source workbook.

## Manual launch and smoke checks

macOS development environment:

```bash
cd /path/to/logistics-analytics-dashboard
MPLCONFIGDIR=/tmp/history-dashboard-mpl .venv/bin/python main.py
```

macOS brief smoke launch:

```bash
cd /path/to/logistics-analytics-dashboard
MPLCONFIGDIR=/tmp/history-dashboard-mpl .venv/bin/python main.py --smoke-test
```

Windows normal launch:

```text
Double-click launch_history_dashboard.vbs
```

`launch_history_dashboard.bat` remains available as a visible troubleshooting launcher. Both use the project-local `.venv` and never reinstall dependencies.

Windows Command Prompt smoke launch from the project directory:

```text
python main.py --smoke-test
```

If the Windows project uses a virtual environment:

```text
.venv\Scripts\python.exe main.py --smoke-test
```

## Known limitations

- The application does not write, repair, refresh, or run macros in Excel.
- Invalid Excel date cells remain quality warnings and are not reinterpreted as arbitrary `YYYYMMDD` values.
- Schedule aggregates are available only where at least one comparable, non-legacy old/new event exists for the relevant voyage instance; missing history is not treated as stable performance.
- Customer normalization is intentionally limited to case and surrounding whitespace; genuine aliases remain separate.
- Customer trends require at least two valid ETA-month periods.
- Only complete `(Vessel, Voyage, BlockID)` identities support voyage-level drill-down.
- `foundation_view.py` and `vessel_view.py` are retained legacy modules but are no longer routed.
