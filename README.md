<p align="center">
  <a href="README.md">🇬🇧 English</a> |
  <a href="README.es.md">🇦🇷 Español</a>
</p>

# Banking Promotions

![Status](https://img.shields.io/badge/Status-In%20development-4C9A2A)
![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?logo=pydantic&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-3FCF8E?logo=supabase&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)
![Pytest](https://img.shields.io/badge/Tests-Pytest-0A9EDC?logo=pytest&logoColor=white)

A system for centralizing and searching banking promotions and payment method benefits available in Argentina.

The goal is to make saving money easier by providing a quick and convenient way to find discounts, cashback offers, and other promotions without having to check each bank’s, digital wallet’s, or retailer’s website or application individually.

The project collects information from multiple sources, preserves the original data, transforms it into a standardized format, and stores it in a periodically updated database.

It currently includes a Python backend that extracts, normalizes, and synchronizes promotions from **BBVA, Buepp, Banco del Sol, and Patagonia**.

The data is consumed by [Telegram Personal Assistant](https://github.com/PabloBottinelli/telegram-personal-assistant), another personal project that allows users to search for promotions directly through Telegram. I also plan to develop a standalone web interface.

## Design Decisions

### Separation of Collection, Normalization, and Persistence

Each source publishes its promotions using different structures and formats. For this reason, the project separates data collection from processing and storage:

1. **Scrapers** retrieve the original data and report whether extraction completed successfully.
2. **Normalizers** transform each record into one or more variants validated with **Pydantic**.
3. **SyncRunner** validates the data before requesting snapshot storage and synchronizing it with **Supabase**.

This separation allows each source’s collection process to be adapted without changing the shared data contract used by the rest of the system.

### Unified Data Model

The model represents benefits, monetary caps, minimum purchase requirements, stock, usage limits, payment methods, validity periods, applicable days, purchase channels, conditions, and legal terms.

It also preserves the official URL and can indicate when an external list of participating merchants needs to be consulted.

A campaign can produce multiple variants when its benefits depend on different conditions. Each variant has a stable `source_id`, unique within its source; `promotion_group_id` links variants belonging to the same campaign.

Since not all sources provide the same information, the model supports unknown values.

### Supabase as the Persistence Layer

Normalized promotions are stored in **Supabase**, using PostgreSQL as the database.

Each variant is identified by the combination `(source, source_id)`, allowing existing records to be updated through *upsert* operations without creating duplicates.

The system tracks whether each promotion is active through `active` and when it was last observed through `last_seen_at`.

Deactivation of promotions no longer found in a source is implemented but currently disabled, pending additional safeguards to prevent incorrect deactivation.

### Validation Before Writing

The runner checks that extraction is complete and that records have valid, unique identifiers. It also verifies that each raw record produces valid normalized variants before requesting snapshot storage or accessing Supabase.

If a source reports that its snapshot cannot be replaced or that review is required, synchronization is blocked.

### Automated Synchronization

The project uses **GitHub Actions** to execute data extraction, normalization, and database updates.

Scheduled synchronization runs **once a week**.

Each source is processed in a separate job, allowing synchronization attempts for the remaining sources to continue if one fails.

Synchronization logic is centralized in `SyncRunner`. Sources included in the workflow can also be triggered manually through GitHub Actions.

## Testing

The project uses **pytest** to verify the behavior of scrapers, normalizers, the JSON exporter, the data model structure, and the runner’s validation checks.

Tests use mocks and fixtures to evaluate data retrieval and transformation without depending on requests to live websites.

They also cover error scenarios such as incomplete captures, duplicate identifiers, normalization failures, and deactivation restrictions.

## Assisted Development

Development is assisted by Codex, following the rules defined in `AGENTS.md` and the source integration skill.

The main Codex agent implements and coordinates the work, while `promotion_qa` performs an audit in an independent context.

A QA `PASS` means the implementation is ready for review; it does not by itself authorize automatic synchronization.

## Integration with Other Projects

This project is part of a collection of personal tools designed to work independently or integrate with one another.

It is currently integrated with **[Telegram Personal Assistant](https://github.com/PabloBottinelli/telegram-personal-assistant)**, which provides a conversational interface for searching banking promotions.

The integration maintains a clear separation of responsibilities:

- **Banking Promotions:** Data collection, processing, normalization, and storage.
- **Telegram Personal Assistant:** Handling user queries, searching promotions, and presenting results.

Both projects communicate through Supabase, so the assistant does not need to execute the internal extraction and synchronization processes.

## Planned Improvements

- Add a persistent historical baseline per source to detect data loss between runs.
- Improve error reporting and recovery from partial writes.
- Expand test coverage and automate test execution in CI.
- Improve condition extraction and add more banks and digital wallets.
- Identify equivalent promotions across sources.
- Develop a web interface for searching and comparing promotions.

## Author

[Pablo Bottinelli](https://github.com/PabloBottinelli)