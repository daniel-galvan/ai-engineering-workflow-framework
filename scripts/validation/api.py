"""In-process validation for trusted framework callers; no cached artifact results."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from .common import fail
from .library import validate_library
from .provider_policy import _plugin_version_refresh_error
from .work_records import validate_work_record


def checked(check, *args, **kwargs):
    """Translate the validators' CLI failure protocol into an API exception."""
    output = StringIO()
    with redirect_stdout(output):
        try:
            return check(*args, **kwargs)
        except SystemExit as error:
            raise ValueError(output.getvalue().strip() or f"validation exited with status {error.code}") from error


def validate_package() -> None:
    validate_library()
    error = _plugin_version_refresh_error()
    if error:
        fail(error)


def record_validation_output(path: Path, *, allow_unreleased: bool = False) -> str:
    handoff = checked(validate_work_record, path.resolve(), require_terminal=not allow_unreleased,
                      allow_unreleased=allow_unreleased)
    return "Workflow-framework validation: passed\n" + ("" if allow_unreleased else handoff + "\n")
