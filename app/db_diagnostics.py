"""Safe database diagnostics: never render driver messages, SQL or URL values."""
import re


class SchemaValidationError(ValueError):
    """A validator-authored message containing only schema/role descriptions."""


def diagnostic(error, phase):
    detail = str(error) if isinstance(error, SchemaValidationError) else 'Check connection settings and database permissions.'
    original = getattr(error, 'orig', None)
    state = getattr(original, 'sqlstate', None)
    state = state if isinstance(state, str) and re.fullmatch(r'[A-Z0-9]{5}', state) else 'unknown'
    return f'phase={phase} error_type={type(error).__name__} sqlstate={state}: {detail}'
