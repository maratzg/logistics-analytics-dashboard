# Logistics Analytics Dashboard

A desktop analytics application designed around a real operational logistics workflow, providing structured analysis of weekly operations, historical changes, voyage performance, equipment movements, data quality, and operational trends stored in Excel.

The project extends an existing Excel-based workflow with a Python analytics layer. Excel remains the operational source of truth, while the Python application reads the workbook without modifying it and provides dedicated interfaces for analysis, historical exploration, comparison, validation, and reporting.

> **Portfolio version:** Production workbooks and operational data are intentionally excluded. The included demo workbook and all tests use synthetic data only.

---

## Problem

Operational logistics data is often maintained in Excel because spreadsheets work well for day-to-day data entry and operational processes. As the amount of data and history grows, however, spreadsheets become increasingly difficult to use for:

- historical analysis and change tracking;
- voyage and schedule comparison;
- equipment, cargo, TEU, and weight analysis;
- customer, vessel, and service analytics;
- data-quality monitoring;
- searching large change histories;
- management-level operational summaries.

Replacing the operational workbook entirely was not the objective.

Instead, this project preserves Excel as the operational interface while building a separate analytical application around its structured data.

```text
Operational Excel workflow
          ↓
Read-only Python data layer
          ↓
Validation and normalization
          ↓
Analytics and history resolution
          ↓
Desktop dashboard
```

This allows existing Excel workflows to continue while providing a substantially more capable analytical and historical interface.

---

## Architecture

The application follows a read-only analytics architecture:

```text
┌─────────────────────────────┐
│      Excel Workbook         │
│                             │
│  WEEKLY                     │
│  LOG_HISTORY                │
│  MASTER_DATA                │
│  REPORT                     │
└──────────────┬──────────────┘
               │
               │ OneDrive / SharePoint sync
               ▼
┌─────────────────────────────┐
│ Local synchronized workbook │
└──────────────┬──────────────┘
               │
               │ read only
               ▼
┌─────────────────────────────┐
│      Python Data Layer      │
│                             │
│ Workbook loading            │
│ Schema normalization        │
│ Validation                  │
│ Identity resolution         │
│ Independent calculations    │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│       Analytics Layer       │
│                             │
│ Operational analytics       │
│ Historical analytics        │
│ Schedule analytics          │
│ Comparison                  │
│ Data quality                │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│         Desktop GUI         │
│                             │
│ Dashboard                   │
│ Voyages                     │
│ Vessel / Service analytics  │
│ Customers                   │
│ History Explorer            │
│ Compare                     │
│ Data Quality                │
└─────────────────────────────┘
```

The Python application does **not** write analytical changes back to the operational workbook.

---

## Data Flow

A typical workflow is:

1. Operational data is maintained in a structured Excel `.xlsm` workbook.
2. The workbook may be stored in a SharePoint document library and synchronized locally through OneDrive.
3. The Python application opens the local workbook in read-only analytical mode.
4. Workbook sheets are loaded into an application snapshot.
5. Data is normalized into a canonical schema.
6. Operational calculations and validation are performed independently.
7. Historical events are resolved against current logical records where possible.
8. Analytics and presentation models are built from the snapshot.
9. GUI pages consume the shared application state without repeatedly reopening Excel.
10. The user can refresh the snapshot when the source workbook changes.

This deliberately separates operational data entry from analytical processing.

---

## Core Features

The application provides:

- operational dashboard and KPI summaries;
- voyage browser and voyage-level drill-down;
- vessel analytics;
- service analytics;
- customer analytics;
- searchable history exploration;
- voyage comparison;
- schedule-change analysis;
- cargo and equipment analysis;
- loaded and empty equipment metrics;
- TEU and gross-weight analytics;
- anomaly and data-quality detection;
- shared analytical filters;
- CSV exports;
- workbook health diagnostics;
- OneDrive/SharePoint-compatible workbook discovery;
- read-only source-workbook handling.

---

## Workbook Model

The application is designed around structured workbook sheets including:

### Included demo workbook

[`demo/logistics_operations_demo.xlsm`](demo/logistics_operations_demo.xlsm) is a sanitized, macro-enabled workbook for portfolio review and hands-on testing. It contains 22 synthetic operational records across three weekly blocks and 35 synthetic history events, including active and cancelled shipments, loaded and empty equipment, multiple vessels, voyages, customers, and one relocation-aware RowID scenario.

The demo retains the workbook structure required by the application:

- the 45-column `WEEKLY` operational schema;
- `LOG_HISTORY`, `MASTER_DATA`, `REPORT`, `TEMPLATE`, and `README` sheets;
- the original workbook formulas, formatting, validations, tables, controls, and VBA project;
- synthetic formula caches for non-Excel readers, with full recalculation requested when Excel opens the file.

Production data, personal metadata, custom document properties, SharePoint metadata, printer paths, external links, queries, connections, and credentials are not included.

To try the demo, install the dependencies and launch the application normally. On first run, choose `demo/logistics_operations_demo.xlsm` when prompted for a workbook. The selection is stored in the user-specific configuration, not committed to the repository.

### `WEEKLY`

The authoritative source for current operational records.

The canonical schema includes fields such as:

- Week
- Vessel
- Voyage
- ETA / ETD
- Cut-Off
- ETA T/S
- Booking number
- Service
- Booking status
- Container amount
- Container size and type
- Gross weight
- POL / POD
- Customer
- Row status
- Cancellation reason
- Load status
- calculated container, TEU, and GWT metrics
- BlockID
- RowID

### `LOG_HISTORY`

The structured history of tracked changes.

History records can contain:

- timestamp;
- user;
- BlockID;
- RowID;
- Week;
- Vessel;
- Voyage;
- booking number;
- changed field;
- old value;
- new value.

### `MASTER_DATA`

Treated as derived data rather than a silent substitute for missing authoritative operational data.

### `REPORT`

Allows the workbook to retain its own lightweight Excel-based overview independently of the Python application.

---

## Stable Record Identity

One of the central engineering problems in the project was separating **logical record identity** from **physical spreadsheet location**.

The application distinguishes between three concepts:

### RowID

`RowID` represents the permanent logical identity of a record.

It is treated as an opaque identifier and is not parsed to infer the record's current Week or physical location.

### BlockID

`BlockID` represents the current physical weekly block containing the record.

### Week

`Week` is editable business data.

A record can therefore move between weekly blocks without changing its permanent identity:

```text
Before relocation:

RowID:   2026-W36|R05
BlockID: 2026-W36
Week:    36

After relocation:

RowID:   2026-W36|R05
BlockID: 2026-W37
Week:    37
```

The `RowID` prefix is deliberately not required to match the current `BlockID`.

This preserves historical continuity when operational records move between weekly blocks.

---

## Relocation-Aware History

Historical events are not assumed to remain associated with their original physical spreadsheet location forever.

When history is loaded, current operational `RowID` values are indexed. Historical records can then be classified as:

- **Resolved**: exactly one current operational record matches;
- **Unresolved**: no current operational record matches;
- **Ambiguous**: multiple current records use the same RowID;
- **Unavailable**: the historical event has no usable RowID.

When resolution is safe, historical events can be associated with the record's current voyage context while their original event context remains intact.

The application deliberately refuses to guess when identity is ambiguous.

This prevents relocated records from disappearing from current voyage history, creating false voyage instances, or being assigned to the wrong current record.

---

## Analytics

### Dashboard

The main dashboard provides an operational overview based on the active filter context, including container, TEU, weight, voyage, and other operational metrics.

### Voyages

Voyage-level exploration includes:

- container totals;
- TEU totals;
- gross weight;
- loaded versus empty cargo;
- equipment distribution;
- booking activity;
- schedule information;
- cancellations;
- historical revisions.

Voyage instances use the current:

```text
(Vessel, Voyage, BlockID)
```

context.

`RowID` provides logical record continuity rather than replacing voyage identity.

### Voyage Detail

Voyage Detail combines current operational information with the historical timeline associated with the voyage's records.

Relocation-aware history allows events recorded before a weekly relocation to remain associated with the current logical record when identity can be resolved safely.

### Vessel, Service, and Customer Analytics

Operational information can be aggregated by vessel, service, and customer, providing higher-level views without requiring users to manually inspect individual spreadsheet blocks.

### History Explorer

The History Explorer provides searchable access to structured workbook history using information such as:

- booking number;
- vessel and voyage;
- RowID;
- Week;
- user;
- changed field;
- old and new values;
- historical BlockID;
- resolved current context;
- date range.

Historical context and current physical context remain separate so record relocation does not rewrite what originally happened.

### Voyage Comparison

Voyage instances can be compared side by side using metrics including:

- total containers;
- total TEU;
- total GWT;
- loaded and empty TEU;
- loaded and empty GWT;
- cancellations;
- ETA-related changes;
- booking churn.

---

## Operational Calculations

The application independently calculates operational quantities rather than relying exclusively on cached Excel formula results.

Metrics include:

- loaded, empty, and total containers;
- 20 ft and 40 ft equipment totals;
- loaded, empty, and total TEU;
- loaded, empty, and total GWT.

For the current workbook model:

```text
SIZE = 2  -> 20 ft container
SIZE = 4  -> 40 ft container
```

Cancelled operational records remain visible for audit and history purposes while contributing zero to active operational quantities.

### Load Status

Load status is interpreted explicitly:

```text
blank   -> Loaded
Loaded  -> Loaded
Empty   -> Empty
other   -> Unknown
```

Unexpected values are preserved and surfaced as data-quality issues rather than silently converted into convenient categories.

Unknown cargo can remain part of overall totals without being incorrectly classified as Loaded or Empty.

---

## Data Quality

The application includes a dedicated validation and Data Quality layer.

Checks include conditions such as:

- duplicate operational RowIDs;
- ambiguous current logical identity;
- missing operational BlockID;
- missing Vessel or Voyage;
- unresolved historical RowIDs;
- invalid operational values;
- unexpected LoadStatus values;
- unsupported container sizes;
- insufficient equipment information;
- schedule/date inconsistencies;
- calculation inconsistencies.

Validation is also designed to avoid known false positives:

- RowID prefixes do not need to match current BlockIDs;
- RowIDs are not parsed to infer Week;
- blank LoadStatus is valid;
- reservation-only rows are not treated as duplicate operational records;
- cancelled records remain visible while contributing zero operational quantities.

Identity-critical problems are surfaced rather than automatically repaired or guessed.

---

## Application State and Refresh

The workbook is loaded into a shared application snapshot.

GUI navigation operates on that state rather than reopening Excel for every screen.

```text
Workbook
   ↓
Normalized snapshot
   ↓
Shared application state
   ↓
Analytics / presentation models
   ↓
GUI views
```

Models can be cached and reused during navigation. A refresh explicitly reloads the workbook when updated operational data is required.

If a later refresh cannot be completed, the application can retain the last successfully loaded data rather than immediately discarding the usable snapshot.

---

## Desktop Interface

The GUI includes routes for:

- Dashboard
- Voyages
- Voyage Detail
- Vessel Analytics
- Service Analytics
- Customers
- History Explorer
- Compare
- Data Quality

The interface supports shared filtering, analytical navigation, table views, drill-down, Back navigation, workbook refresh, source status, quality inspection, and CSV export.

The GUI consumes presentation models rather than accessing Excel directly.

---

## CSV Export

Analytical results can be exported locally as CSV.

Export behavior is intentionally separated from the operational workbook. The application rejects Excel as an analytical export destination rather than writing results into the source workbook.

This preserves the boundary between operational input and analytical output.

---

## Source Workbook Safety

Protecting the operational workbook is a core design requirement.

The Python application treats it as **read-only input** and does not:

- save the source workbook;
- overwrite cells;
- update formulas;
- modify VBA;
- write analytical results into Excel;
- use the source workbook as an export destination.

Workbook integrity is covered by integration testing.

The original production workbook and production operational data are **not included in this public repository**. The included demo workbook preserves the Excel-side VBA workflow using synthetic data so reviewers can inspect the end-to-end architecture.

The Python application is designed to understand the identity and history model produced by that workflow without modifying it.

---

## Technologies

### Python

The application targets **Python 3.13** and uses:

- pandas
- openpyxl
- CustomTkinter
- Matplotlib
- Python filesystem, configuration, and logging utilities

### Operational Environment

The wider workflow supports:

- Microsoft Excel
- macro-enabled `.xlsm` workbooks
- OneDrive synchronization
- SharePoint document libraries
- Windows batch launch scripts
- VBScript no-console startup

---

## Repository Structure

```text
logistics-analytics-dashboard/
├── main.py
├── check_environment.py
├── requirements.txt
├── config.example.json
├── demo/
│   └── logistics_operations_demo.xlsm
│
├── src/
│   ├── analytics modules
│   ├── data processing
│   ├── validation and diagnostics
│   ├── application state
│   └── gui/
│       ├── views
│       ├── presentation models
│       ├── reusable components
│       └── exporting
│
├── tests/
│   └── automated regression tests
│
├── install_dependencies.bat
├── launch_history_dashboard.bat
├── launch_history_dashboard.vbs
│
├── ANALYTICS_DEFINITIONS.md
├── GUI_GUIDE.md
├── WINDOWS_SETUP.md
└── README.md
```

Virtual environments, runtime files, production workbooks, local configuration, and operational exports are excluded from version control. The sanitized workbook under `demo/` is the sole intentional workbook exception.

---

## Installation

### Requirements

The intended desktop deployment uses:

- Windows 10/11
- Python 3.13
- Excel Desktop when working with a macro-enabled operational workbook
- OneDrive when the workbook is synchronized from SharePoint

Clone the repository:

```bash
git clone https://github.com/<username>/logistics-analytics-dashboard.git
cd logistics-analytics-dashboard
```

For Windows deployment, follow:

```text
WINDOWS_SETUP.md
```

The repository also includes:

```text
install_dependencies.bat
```

for creating the project-local environment and installing dependencies.

Virtual environments should be created independently on each computer rather than copied between machines.

---

## Running

For normal Windows use:

```text
launch_history_dashboard.vbs
```

starts the application without leaving a console window open.

For troubleshooting:

```text
launch_history_dashboard.bat
```

keeps console output visible.

The typical workflow is:

```text
1. Install Python 3.13
2. Clone or copy the application
3. Run install_dependencies.bat
4. Launch with launch_history_dashboard.vbs
5. Select a compatible workbook
6. Refresh when synchronized workbook data changes
```

The selected workbook can be remembered through user-specific configuration.

---

## OneDrive / SharePoint

The application works with the **local synchronized representation** of a workbook rather than directly editing a SharePoint-hosted file.

```text
SharePoint
    ↓
OneDrive synchronization
    ↓
Local .xlsm workbook
    ↓
Python analytics application
```

Synchronization itself remains the responsibility of OneDrive/SharePoint.

---

## Testing

The current sanitized portfolio build contains:

```text
189 tests
188 passing
1 expected skip
0 failures
0 errors
```

The expected skip is an opt-in GUI display test rather than an application failure.

The regression suite covers:

- workbook normalization;
- canonical schema handling;
- operational calculations;
- LoadStatus and cancellation behavior;
- filtering;
- application-state caching;
- GUI presentation models;
- navigation and drill-down;
- operational and historical analytics;
- data-quality checks;
- voyage comparison;
- CSV export safety;
- relocation-aware history;
- identity resolution;
- ghost-voyage prevention;
- ambiguous duplicate RowIDs;
- reservation-row handling;
- Windows setup and launcher contracts.

Synthetic relocation tests verify that a single logical RowID can retain continuous history while moving between physical weekly blocks.

Run the suite with:

```bash
python -m unittest discover -s tests -v
```

---

## Key Design Decisions

### Excel remains the operational source of truth

The project does not replace a working operational spreadsheet simply because a Python application exists. Python provides analysis around the workflow rather than becoming a competing operational data source.

### Python is read-only

The analytical application does not save changes to the source workbook, reducing the risk of analytical code corrupting operational data.

### Logical identity is independent of spreadsheet position

Excel row numbers and weekly locations are not stable identities. `RowID` represents the logical record, while `BlockID` represents its current physical placement.

### Ambiguous identity is never guessed

If multiple current records share the same RowID, history resolution becomes ambiguous. The application surfaces that condition instead of selecting whichever record happens to appear first.

### Historical context is preserved

Resolving an old event to a current logical record does not overwrite the original event context.

The system can therefore distinguish between:

> Where was this record when the event occurred?

and:

> Where is this logical record now?

### Calculations are independently verified

Python calculates operational metrics independently rather than depending exclusively on cached Excel formulas.

### Unknown data remains unknown

Unexpected values are preserved and surfaced instead of silently converted into known categories.

### Cancelled records remain auditable

Cancelled records remain available for history and review while contributing zero to active operational quantities.

### Workbook access is separated from GUI navigation

The workbook is loaded into shared application state. GUI pages consume that state instead of repeatedly reopening the source file.

---

## Documentation

Additional project documentation is available in:

- [`ANALYTICS_DEFINITIONS.md`](ANALYTICS_DEFINITIONS.md)
- [`GUI_GUIDE.md`](GUI_GUIDE.md)
- [`WINDOWS_SETUP.md`](WINDOWS_SETUP.md)

---

## Portfolio and Data Privacy

This repository is a sanitized portfolio version of the application.

It does **not** include:

- production workbooks;
- real customer or employee data;
- real booking identifiers;
- private SharePoint URLs;
- confidential operational history;
- credentials or secrets;
- user-specific configuration;
- private filesystem paths.

Tests and the included demo workbook use synthetic fixtures and portfolio-only entities.

---

## Project Status

The core application and release-hardening work represented in this portfolio build are complete.

The current build includes operational and historical analytics, relocation-aware identity handling, voyage comparison, data-quality analysis, desktop GUI navigation, CSV export, read-only workbook integration, Windows deployment tooling, and an automated regression suite.

Production-specific behavior involving real-world Excel coauthoring and OneDrive/SharePoint synchronization remains dependent on the deployment environment.

---

## Why This Project Was Built

This project addresses a practical operational question:

> **How can an existing Excel workflow become significantly more analytical and auditable without immediately replacing the workflow itself?**

The resulting architecture combines:

```text
Excel for operational input
        +
structured historical tracking
        +
Python for validation and analytics
        +
a desktop interface for exploration
```

The emphasis is not only on producing dashboards, but on preserving reliable identity, historical continuity, data quality, and a clear separation between operational and analytical responsibilities.
