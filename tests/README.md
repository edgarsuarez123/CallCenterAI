# Test Suite for CallCenterAI

## Overview

This directory contains unit tests for the CallCenterAI application, focusing on the Google Calendar service integration.

## Running Tests

### Prerequisites

Ensure all dependencies are installed:

```bash
pip install -r requirements.txt
```

### Run All Tests

```bash
pytest
```

### Run Specific Test File

```bash
pytest tests/test_google_calendar.py
```

### Run Specific Test Class

```bash
pytest tests/test_google_calendar.py::TestRetryLogic
```

### Run Specific Test

```bash
pytest tests/test_google_calendar.py::TestRetryLogic::test_retry_on_rate_limit
```

### Run with Coverage

```bash
pytest --cov=Clinic_app --cov-report=html
```

### Run with Verbose Output

```bash
pytest -v
```

## Test Structure

### `test_google_calendar.py`

Comprehensive unit tests for the Google Calendar service, covering:

- **Service Account Validation**: Tests for JSON validation and parsing
- **Extended Properties**: Tests for building and parsing metadata
- **Retry Logic**: Tests for rate limit handling, transient errors, and graceful degradation
- **CRUD Operations**: Tests for list, create, update, delete, and get operations
- **Bulk Operations**: Tests for `delete_multiple_events`
- **Error Handling**: Tests for 404, 403, and other error scenarios
- **Calendar Validation**: Tests for access validation
- **Timezone Handling**: Tests for RFC3339 formatting and timezone preservation
- **Event Filtering**: Tests for filtering by source

## Test Fixtures

The test suite uses pytest fixtures for common test data:

- `sample_clinic_id`: Sample clinic UUID
- `sample_calendar_id`: Sample Google Calendar ID (email)
- `sample_service_account_json`: Valid service account JSON structure
- `sample_clinic_integration`: Mock ClinicIntegration object
- `mock_db_session`: Mock async database session
- `mock_calendar_service`: Mock Google Calendar API service
- `sample_event`: Sample Google Calendar event with extended properties

## Mocking Strategy

All tests use mocks to avoid making real API calls:

- Google Calendar API calls are mocked using `unittest.mock`
- Database sessions are mocked using `AsyncMock`
- HTTP errors are simulated using `HttpError` from `googleapiclient.errors`

## Writing New Tests

When adding new tests:

1. Follow the existing test class structure
2. Use appropriate fixtures for common test data
3. Mock external dependencies (API calls, database)
4. Test both success and error scenarios
5. Include docstrings explaining what each test validates
6. Use descriptive test names that explain the scenario

## Continuous Integration

Tests should be run as part of CI/CD pipeline:

```yaml
# Example GitHub Actions workflow
- name: Run tests
  run: |
    pip install -r requirements.txt
    pytest
```

