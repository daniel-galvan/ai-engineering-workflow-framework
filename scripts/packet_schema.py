"""Shared packet field validation for merging and finalization."""

def shape_errors(value: object, template: object, path: str) -> list[str]:
    if isinstance(template, dict):
        if not isinstance(value, dict):
            return [f"{path} must be an object"]
        errors = [f"{path}.{key} is missing" for key in template if key not in value]
        for key in template.keys() & value.keys():
            errors.extend(shape_errors(value[key], template[key], f"{path}.{key}"))
        return errors
    if isinstance(template, list):
        if not isinstance(value, list):
            return [f"{path} must be a list"]
        if template:
            return [
                error
                for index, item in enumerate(value)
                for error in shape_errors(item, template[0], f"{path}[{index}]")
            ]
        return []
    if not isinstance(value, type(template)):
        return [f"{path} must be {type(template).__name__}"]
    return []
