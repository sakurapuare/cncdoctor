# Architecture

## Overview

The project is organized around a service-oriented backend that isolates
domain logic from Django transport concerns.

## Layers

### API layer

- `Shukongdashi/api_views.py`
- `Shukongdashi/urls.py`
- `Shukongdashi/middleware.py`

Responsibilities:

- Normalize HTTP inputs from query strings, form posts, and JSON posts
- Apply consistent JSON responses
- Attach CORS and request metadata
- Map endpoints to service methods

### Application layer

- `Shukongdashi/core/services.py`
- `Shukongdashi/core/container.py`

Responsibilities:

- Coordinate diagnosis, Q&A, autocomplete, online analysis, and feedback
- Compose dependencies through a single runtime container
- Handle fallback behavior between graph-backed and local-case workflows

### Domain layer

- `Shukongdashi/core/models.py`
- `Shukongdashi/core/text.py`

Responsibilities:

- Define immutable request and response objects
- Parse CNC fault descriptions into machine fragments, operations, symptoms, parts, and alarm codes
- Provide similarity scoring and hybrid text classification

### Infrastructure layer

- `Shukongdashi/core/repositories.py`
- `Shukongdashi/toolkit/pre_load.py`
- `Shukongdashi/Model/neo_models.py`

Responsibilities:

- Persist seeded and user feedback cases in SQLite
- Integrate with Neo4j when configured
- Expose compatibility shims for legacy imports

## Runtime flow

1. API view receives a request and normalizes the payload.
2. `ServiceContainer` resolves parser, repositories, and services.
3. The service applies graph reasoning when Neo4j is configured.
4. The service falls back to seeded cases when graph dependencies are unavailable.
5. The response is serialized as a stable JSON envelope.

## Operational notes

- Runtime case data is created under `Shukongdashi/runtime/`.
- `python manage.py rebuild_case_db` recreates the SQLite database from `guzhanganli.sql`.
- `python manage.py system_doctor` reports the active backend state.
