"""Compatibility entrypoint for packaged validation self-check scenarios."""


def self_test_reasoning_records() -> None:
    try:
        from self_check import run_self_check
    except ModuleNotFoundError:
        from scripts.self_check import run_self_check
    run_self_check("validation_self_tests", "self_test_reasoning_records")
