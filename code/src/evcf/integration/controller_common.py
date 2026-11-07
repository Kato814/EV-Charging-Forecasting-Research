"""Small shared contracts; metadata validation does not prove source truth."""
from .reuse_contracts import ContractError, _keys, _number, _utc


class AdmissionError(ValueError):
    """A declared input cannot be admitted under an explicit contract."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f'{code}: {message}')


def utc(value, label):
    try:
        return _utc(value, label)
    except ContractError as exc:
        raise AdmissionError('INVALID_TIME', str(exc)) from exc


def number(value, label, nonnegative=True):
    try:
        return _number(value, label, nonnegative=nonnegative)
    except ContractError as exc:
        raise AdmissionError('INVALID_NUMBER', str(exc)) from exc


def exact_keys(value, expected, label):
    try:
        return _keys(value, expected, label)
    except ContractError as exc:
        raise AdmissionError('INVALID_SCHEMA', str(exc)) from exc


def identifier(value, label):
    if not isinstance(value, str) or not value or value.strip() != value:
        raise AdmissionError('INVALID_IDENTIFIER', f'{label} must be a nonempty clean string')
    return value
