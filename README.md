<p align="center">
  <a href="README.md">🇬🇧 English</a> |
  <a href="README.es.md">🇦🇷 Español</a>
</p>

# Banking Promotions

![Status](https://img.shields.io/badge/STATUS-IN%20DEVELOPMENT-4C9A2A)
![Python](https://img.shields.io/badge/Python-3776AB?logo=python\&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?logo=pydantic\&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-3FCF8E?logo=supabase\&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?logo=githubactions\&logoColor=white)
![Pytest](https://img.shields.io/badge/Tests-Pytest-0A9EDC?logo=pytest\&logoColor=white)

# Description

A system designed to centralize and search banking promotions and payment method benefits available in Argentina.

The goal is to make it easier to save money by providing a quick and convenient way to find discounts, cashback offers, and other promotions without having to check each bank's, digital wallet's, or retailer's website or application individually.

The project collects information from multiple sources, preserves the original data, transforms it into a standardized format, and stores it in a database that is updated periodically.

It currently includes a Python backend that extracts, normalizes, and synchronizes promotions from Galicia, BBVA, and Patagonia.

The data is currently consumed by [Telegram Personal Assistant](https://github.com/PabloBottinelli/telegram-personal-assistant), another personal project that allows users to search for promotions directly through Telegram. I also plan to develop a standalone web interface in the future.

# Design Decisions

## Separation of Scraping and Normalization

Each bank publishes its promotions using different data structures and formats. Some provide information through APIs, while others require extracting data from HTML pages.

For this reason, the project separates data collection from data processing.

**Scrapers** are responsible for retrieving and preserving the original data from each source, while **normalizers** transform that information into a standardized structure.

## Unified Data Model

Promotions are represented using **Pydantic** models, which provide data structuring and validation across different sources.

The model includes information such as:

* Source bank and promotion identifier.
* Merchant, category, and description.
* Discount percentage and interest-free installments.
* Validity period and applicable days.
* Cashback limits and conditions.
* Accepted payment methods.
* Purchase channels and payment options.
* Eligibility requirements and terms and conditions.

Since not all sources provide the same information, the model supports optional fields for data that may be unavailable.

## Supabase as the Persistence Layer

Normalized promotions are stored in **Supabase**, using PostgreSQL as the database.

Each promotion is uniquely identified by the combination of its source and original identifier, allowing existing records to be updated through *upsert* operations without creating duplicates.

The system also tracks when each promotion was last observed.

When a scraping process completes successfully, promotions that are no longer found in the source can be marked as inactive.

To prevent valid promotions from being incorrectly deactivated due to extraction errors, this operation is skipped when scraping is incomplete.

## Automated Synchronization

The project uses **GitHub Actions** to periodically execute data extraction, normalization, and database synchronization processes.

Each bank is processed independently, ensuring that a failure in one source does not prevent synchronization attempts for the others.

Synchronization logic is centralized in `SyncRunner`.

Synchronizations can also be triggered manually, either through GitHub Actions or from the local development environment.

# Testing

The project uses **pytest** to test the behavior of scrapers and normalizers.

Tests verify aspects such as data retrieval, response processing, and the transformation of promotions into the unified data model.

Scraping tests use mocked HTTP responses to validate specific behaviors without relying on live requests to banking websites.

# Integration with Other Projects

This project is part of a collection of personal tools designed to work independently or integrate with one another.

It is currently integrated with **[Telegram Personal Assistant](https://github.com/PabloBottinelli/telegram-personal-assistant)**, which provides a conversational interface for searching banking promotions.

The integration maintains a clear separation of responsibilities:

* **Banking Promotions:** Data collection, processing, normalization, and storage.
* **Telegram Personal Assistant:** Handling user queries, searching promotions, and presenting results.

Both projects communicate through Supabase, allowing the assistant to access promotion data without needing to interact with or execute the internal scraping and synchronization processes.

# Future Improvements

* Add support for more banks and digital wallets.
* Improve normalization and the extraction of promotion-specific conditions.
* Expand search and filtering capabilities by merchant, payment method, bank, and category.
* Develop a web interface for searching and comparing promotions.
* Increase test coverage and automate test execution.
* Improve error monitoring and synchronization reporting.
* Implement mechanisms to identify equivalent promotions across different sources.

# Author

| [<img src="https://github.com/PabloBottinelli.png" width="115"><br><sub>Pablo Bottinelli</sub>](https://github.com/PabloBottinelli) |
| :---------------------------------------------------------------------------------------------------------------------------------: |
