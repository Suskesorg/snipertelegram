"""A small JSON Schema validator covering the subset the skill's schemas use.

Written instead of depending on `jsonschema` so the validation helpers run on a
bare Python 3.8+ install, which is the environment most users will have. The
supported keywords are listed in SUPPORTED; anything else in a schema is
ignored rather than silently treated as satisfied, and `unsupported_keywords`
reports what was skipped so a schema author is never misled about coverage.
"""

from __future__ import annotations

import re

SUPPORTED = {
    "$schema", "$id", "$ref", "$defs", "title", "description", "examples", "default",
    "type", "enum", "const", "properties", "required", "additionalProperties",
    "patternProperties", "propertyNames", "items", "prefixItems", "minItems", "maxItems",
    "uniqueItems", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "multipleOf", "minLength", "maxLength", "pattern", "anyOf", "oneOf", "allOf", "not",
    "minProperties", "maxProperties", "format", "deprecated",
}

#: `format` is advisory here. Schemas in this skill express real constraints
#: with `pattern` so that nothing depends on format support.
IGNORED_FOR_VALIDATION = {"format", "default", "examples", "title", "description", "deprecated"}

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _is_type(value, name: str) -> bool:
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    expected = _TYPES.get(name)
    if expected is None:
        return True
    if expected is str:
        return isinstance(value, str)
    return isinstance(value, expected) and not isinstance(value, bool)


def unsupported_keywords(schema, path="#") -> list:
    """List keywords present in the schema that this validator ignores."""
    found = []
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key not in SUPPORTED:
                found.append("%s/%s" % (path, key))
            if key in ("properties", "patternProperties", "$defs"):
                if isinstance(value, dict):
                    for sub, subschema in value.items():
                        found.extend(unsupported_keywords(subschema, "%s/%s/%s" % (path, key, sub)))
            elif key in ("anyOf", "oneOf", "allOf", "prefixItems"):
                if isinstance(value, list):
                    for index, subschema in enumerate(value):
                        found.extend(unsupported_keywords(subschema, "%s/%s/%d" % (path, key, index)))
            elif key in ("items", "not", "additionalProperties", "propertyNames"):
                if isinstance(value, dict):
                    found.extend(unsupported_keywords(value, "%s/%s" % (path, key)))
    return found


class Validator:
    def __init__(self, schema: dict):
        self.schema = schema
        self.defs = schema.get("$defs", {})

    def resolve(self, schema):
        seen = 0
        while isinstance(schema, dict) and "$ref" in schema:
            ref = schema["$ref"]
            if not ref.startswith("#/$defs/"):
                raise ValueError("only local #/$defs/ references are supported, got %r" % ref)
            target = self.defs.get(ref[len("#/$defs/"):])
            if target is None:
                raise ValueError("unresolved reference %r" % ref)
            schema = target
            seen += 1
            if seen > 20:
                raise ValueError("reference loop at %r" % ref)
        return schema

    def validate(self, instance, schema=None, path="") -> list:
        schema = self.schema if schema is None else schema
        schema = self.resolve(schema)
        errors = []
        if not isinstance(schema, dict):
            return errors
        here = path or "(root)"

        if "type" in schema:
            types = schema["type"]
            types = types if isinstance(types, list) else [types]
            if not any(_is_type(instance, t) for t in types):
                errors.append("%s: expected type %s, got %s" % (here, "/".join(types), _typename(instance)))
                return errors

        if "enum" in schema and instance not in schema["enum"]:
            errors.append("%s: %r is not one of %s" % (here, instance, schema["enum"]))
        if "const" in schema and instance != schema["const"]:
            errors.append("%s: expected %r" % (here, schema["const"]))

        if isinstance(instance, str):
            errors.extend(self._string(instance, schema, here))
        if isinstance(instance, (int, float)) and not isinstance(instance, bool):
            errors.extend(self._number(instance, schema, here))
        if isinstance(instance, list):
            errors.extend(self._array(instance, schema, here))
        if isinstance(instance, dict):
            errors.extend(self._object(instance, schema, here))

        for key in ("allOf",):
            for index, subschema in enumerate(schema.get(key, [])):
                errors.extend(self.validate(instance, subschema, here))
        if "anyOf" in schema:
            branches = [self.validate(instance, s, here) for s in schema["anyOf"]]
            if all(b for b in branches):
                errors.append("%s: does not match any allowed shape (%s)"
                              % (here, "; ".join(b[0] for b in branches if b)))
        if "oneOf" in schema:
            branches = [self.validate(instance, s, here) for s in schema["oneOf"]]
            passed = [i for i, b in enumerate(branches) if not b]
            if len(passed) != 1:
                errors.append("%s: expected exactly one matching shape, %d matched" % (here, len(passed)))
        if "not" in schema and not self.validate(instance, schema["not"], here):
            errors.append("%s: matched a forbidden shape" % here)
        return errors

    def _string(self, instance, schema, here):
        errors = []
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append("%s: shorter than %d characters" % (here, schema["minLength"]))
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append("%s: longer than %d characters" % (here, schema["maxLength"]))
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append("%s: %r does not match %s" % (here, _clip(instance), schema["pattern"]))
        return errors

    def _number(self, instance, schema, here):
        errors = []
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append("%s: %s is below minimum %s" % (here, instance, schema["minimum"]))
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append("%s: %s is above maximum %s" % (here, instance, schema["maximum"]))
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append("%s: %s must exceed %s" % (here, instance, schema["exclusiveMinimum"]))
        if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
            errors.append("%s: %s must be under %s" % (here, instance, schema["exclusiveMaximum"]))
        if "multipleOf" in schema:
            step = schema["multipleOf"]
            if step and (instance % step) != 0:
                errors.append("%s: %s is not a multiple of %s" % (here, instance, step))
        return errors

    def _array(self, instance, schema, here):
        errors = []
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append("%s: needs at least %d entries" % (here, schema["minItems"]))
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append("%s: allows at most %d entries" % (here, schema["maxItems"]))
        if schema.get("uniqueItems") and _has_duplicates(instance):
            errors.append("%s: entries must be unique" % here)
        if "items" in schema:
            for index, item in enumerate(instance):
                errors.extend(self.validate(item, schema["items"], "%s[%d]" % (here, index)))
        return errors

    def _object(self, instance, schema, here):
        errors = []
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in instance:
                errors.append("%s: missing required key %r" % (here, name))
        for name, value in instance.items():
            child = "%s.%s" % (here, name) if here != "(root)" else name
            if name in properties:
                errors.extend(self.validate(value, properties[name], child))
                continue
            matched = False
            for pattern, subschema in schema.get("patternProperties", {}).items():
                if re.search(pattern, name):
                    errors.extend(self.validate(value, subschema, child))
                    matched = True
            if matched:
                continue
            extra = schema.get("additionalProperties", True)
            if extra is False:
                suggestion = _closest(name, list(properties))
                hint = " (did you mean %r?)" % suggestion if suggestion else ""
                errors.append("%s: unknown key %r%s" % (here, name, hint))
            elif isinstance(extra, dict):
                errors.extend(self.validate(value, extra, child))
        if "minProperties" in schema and len(instance) < schema["minProperties"]:
            errors.append("%s: needs at least %d keys" % (here, schema["minProperties"]))
        return errors


def _typename(value):
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if value is None:
        return "null"
    return {dict: "object", list: "array", str: "string"}.get(type(value), type(value).__name__)


def _clip(text, limit=48):
    return text if len(text) <= limit else text[:limit] + "..."


def _has_duplicates(items):
    seen = []
    for item in items:
        if item in seen:
            return True
        seen.append(item)
    return False


def _closest(name, candidates):
    """Cheap typo suggestion so a misspelled config key is easy to fix."""
    best, best_score = None, 0.0
    for candidate in candidates:
        score = _similarity(name.lower(), candidate.lower())
        if score > best_score:
            best, best_score = candidate, score
    return best if best_score >= 0.7 else None


def _similarity(a, b):
    if not a or not b:
        return 0.0
    shared = 0
    remaining = list(b)
    for ch in a:
        if ch in remaining:
            remaining.remove(ch)
            shared += 1
    return (2.0 * shared) / (len(a) + len(b))


def validate(instance, schema) -> list:
    """Validate and return a list of human-readable errors (empty means valid)."""
    return Validator(schema).validate(instance)
