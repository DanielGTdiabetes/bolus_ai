from app.core.db import _is_schema_init_retryable


def test_duplicate_table_schema_race_is_retryable():
    error = RuntimeError(
        'asyncpg.exceptions.DuplicateTableError: relation "companion_episodes" already exists'
    )

    assert _is_schema_init_retryable(error) is True


def test_unrelated_schema_programming_error_is_not_retryable():
    assert _is_schema_init_retryable(RuntimeError("column user_id does not exist")) is False
