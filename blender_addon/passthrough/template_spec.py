"""Shot template parameter schemas.

Pure Python, no ``bpy`` (SPEC.md section 6). The schemas live as JSON in
``templates/`` and are the single source of truth: the panel's properties are
generated from them at registration, and the builders read the same validated
dict. Adding a parameter means editing one JSON file, not three Python files.

SPEC.md section 6 also lists ``.blend`` files in ``templates/``. There are none.
A checked-in ``.blend`` is an opaque binary that cannot be reviewed in a diff,
has to be rebuilt by hand whenever anything changes, and is tied to the Blender
version that wrote it. The scenes are built procedurally instead, from these
schemas, which is what "the add-on builds and updates scenes from JSON" needs
anyway.
"""

import json
import os
from dataclasses import dataclass, field

TEMPLATE_DIR = "templates"

#: Parameter kinds a schema may declare.
KINDS = ("float", "int", "bool", "string", "enum", "color")


class TemplateError(ValueError):
    """A schema or a set of parameters is not usable."""


@dataclass(frozen=True)
class Parameter:
    key: str
    label: str
    kind: str
    default: object
    description: str = ""
    minimum: float = None
    maximum: float = None
    items: tuple = ()
    subtype: str = "NONE"

    def coerce(self, value):
        """Force ``value`` into this parameter's type and range."""
        if self.kind == "float":
            value = float(value)
        elif self.kind == "int":
            value = int(round(float(value)))
        elif self.kind == "bool":
            value = bool(value)
        elif self.kind == "string":
            value = str(value)
        elif self.kind == "color":
            value = tuple(float(component) for component in value)[:3]
            if len(value) != 3:
                raise TemplateError(f"{self.key}: a colour needs three components")
            return tuple(min(1.0, max(0.0, component)) for component in value)
        elif self.kind == "enum":
            value = str(value)
            allowed = [item[0] for item in self.items]
            if value not in allowed:
                raise TemplateError(f"{self.key}: {value!r} is not one of {allowed}")
            return value

        if self.kind in ("float", "int"):
            if self.minimum is not None:
                value = max(value, type(value)(self.minimum))
            if self.maximum is not None:
                value = min(value, type(value)(self.maximum))
        return value


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    description: str
    parameters: tuple = field(default_factory=tuple)

    def parameter(self, key):
        for parameter in self.parameters:
            if parameter.key == key:
                return parameter
        raise KeyError(key)

    def defaults(self):
        return {parameter.key: parameter.default for parameter in self.parameters}

    def validate(self, params=None):
        """Fill in defaults and coerce everything. Unknown keys are dropped.

        Dropping rather than raising is deliberate: a scene saved by an older
        version of the add-on should still build after a parameter is renamed.
        """
        params = dict(params or {})
        result = {}
        for parameter in self.parameters:
            if parameter.key in params:
                result[parameter.key] = parameter.coerce(params[parameter.key])
            else:
                result[parameter.key] = parameter.default
        return result


def _parameter_from_json(data):
    kind = data.get("kind")
    if kind not in KINDS:
        raise TemplateError(f"{data.get('key')!r}: unknown kind {kind!r}")
    items = tuple(tuple(item) for item in data.get("items", ()))
    if kind == "enum" and not items:
        raise TemplateError(f"{data.get('key')!r}: an enum needs items")
    default = data["default"]
    if kind == "color":
        default = tuple(float(component) for component in default)
    return Parameter(
        key=data["key"],
        label=data.get("label", data["key"].replace("_", " ").title()),
        kind=kind,
        default=default,
        description=data.get("description", ""),
        minimum=data.get("min"),
        maximum=data.get("max"),
        items=items,
        subtype=data.get("subtype", "NONE"),
    )


def template_from_json(data):
    try:
        return Template(
            key=data["key"],
            name=data["name"],
            description=data.get("description", ""),
            parameters=tuple(_parameter_from_json(entry) for entry in data.get("parameters", ())),
        )
    except KeyError as exc:
        raise TemplateError(f"schema is missing {exc}") from exc


def template_directory():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), TEMPLATE_DIR)


def load_templates(directory=None):
    """Every schema in ``directory``, keyed by template key, in name order."""
    directory = directory or template_directory()
    templates = {}
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        template = template_from_json(data)
        if template.key in templates:
            raise TemplateError(f"duplicate template key {template.key!r} in {name}")
        templates[template.key] = template
    if not templates:
        raise TemplateError(f"no template schemas found in {directory}")
    return templates


def enum_items(templates):
    """``(key, name, description)`` triples for a Blender enum property."""
    return tuple(
        (template.key, template.name, template.description) for template in templates.values()
    )
