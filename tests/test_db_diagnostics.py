from sqlalchemy.exc import ProgrammingError
from app.db_diagnostics import SchemaValidationError, diagnostic


def test_driver_secrets_are_not_rendered():
    class DriverError(Exception):
        sqlstate = '42501'
    error = ProgrammingError('SECRET SQL', {'password': 'SECRET PARAMETER'}, DriverError('SECRET URL'))
    result = diagnostic(error, 'connection')
    assert 'sqlstate=42501' in result
    assert 'error_type=ProgrammingError' in result
    assert 'SECRET' not in result


def test_only_validator_messages_are_displayed():
    assert 'missing grant' in diagnostic(SchemaValidationError('missing grant'), 'schema_and_permissions')
    assert 'SECRET' not in diagnostic(ValueError('SECRET URL'), 'configuration')


def test_invalid_sqlstate_is_not_rendered():
    class DriverError(Exception):
        sqlstate = 'SECRET'
    error = ProgrammingError('', {}, DriverError())
    assert 'sqlstate=unknown' in diagnostic(error, 'connection')
