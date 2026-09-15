import inspect
import json
import re
import tomllib
from pathlib import Path
from xml.etree import ElementTree

from django.apps import apps
from django.conf import settings
from django.db import models
from django.http import JsonResponse
from django.test import SimpleTestCase
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_RUNTIME_PACKAGES = {
    "cryptography",
    "django",
    "psycopg",
    "pyotp",
    "pillow",
    "fastembed",
    "whitenoise",
}
ALLOWED_DEV_PACKAGES = {"import-linter", "playwright"}
FORBIDDEN_APP_MARKERS = (
    "rest_framework",
    "api",

    "inventory",
    "order",
    "payment",
    "kyc",
    "document",
    "docs",
    "redis",
    "celery",
    "kafka",
    "aws",
    "azure",
    "gcp",
    "googlecloud",
    "cloudflare",
    "boto",
    "s3",
)
FORBIDDEN_MODEL_MARKERS = (

    "inventory",
    "order",
    "payment",
    "kyc",
    "document",
)
FIXTURE_SUFFIXES = {".json", ".yaml", ".yml", ".xml"}


def normalize_package_name(name):
    return re.sub(r"[-_.]+", "-", name.casefold())


def dependency_name(dependency):
    return normalize_package_name(
        re.split(r"\s*(?:\[|===|==|~=|!=|<=|>=|<|>|@|;)", dependency, maxsplit=1)[0]
    )


def iter_url_entries(patterns, prefix="", namespaces=()):
    for pattern in patterns:
        route = getattr(pattern.pattern, "_route", str(pattern.pattern))
        full_route = f"{prefix}{route}"
        if isinstance(pattern, URLResolver):
            namespace = getattr(pattern, "namespace", None)
            next_namespaces = namespaces + ((namespace,) if namespace else ())
            yield from iter_url_entries(
                pattern.url_patterns,
                prefix=full_route,
                namespaces=next_namespaces,
            )
        elif isinstance(pattern, URLPattern):
            yield full_route, namespaces, pattern.callback


def callback_modules(callback):
    values = [callback, getattr(callback, "func", None)]
    view_class = getattr(callback, "view_class", None)
    if view_class is not None:
        values.extend(view_class.__mro__)
    modules = set()
    for value in values:
        if value is None:
            continue
        modules.add(getattr(value, "__module__", ""))
        try:
            unwrapped = inspect.unwrap(value)
        except (ValueError, TypeError):
            unwrapped = value
        modules.add(getattr(unwrapped, "__module__", ""))
    return {module for module in modules if module}


def callback_return_annotation(callback):
    try:
        annotation = inspect.signature(callback).return_annotation
    except (TypeError, ValueError):
        return None
    if annotation is inspect.Signature.empty:
        return None
    return annotation


def callback_uses_json_response(callback):
    values = [callback, getattr(callback, "func", None)]
    for value in values:
        try:
            unwrapped = inspect.unwrap(value)
        except (ValueError, TypeError):
            unwrapped = value
        code = getattr(unwrapped, "__code__", None)
        globals_ = getattr(unwrapped, "__globals__", {})
        if code is None:
            continue
        for name in code.co_names:
            candidate = globals_.get(name)
            if candidate is JsonResponse:
                return True
            if inspect.isclass(candidate) and issubclass(candidate, JsonResponse):
                return True
    return False


def fixture_paths():
    paths = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in FIXTURE_SUFFIXES:
            continue
        parts = {part.casefold() for part in path.parts}
        if ".git" in parts or ".env" in path.name.casefold():
            continue
        if "fixtures" in parts or "fixture" in path.stem.casefold():
            paths.append(path)
    return sorted(paths)


def is_secret_key(key):
    normalized = re.sub(r"[^a-z0-9]+", "", str(key).casefold())
    return normalized in {
        "password",
        "passwd",
        "token",
        "rawtoken",
        "totp",
        "totpsecret",
        "totpcode",
        "recovery",
        "recoverycode",
        "recoverycodes",
        "encryptionkey",
        "encryptionsecret",
    } or normalized.startswith(
        ("password", "rawtoken", "totpsecret", "totpcode", "recoverycode", "encryptionkey")
    ) or normalized.endswith(
        ("password", "token", "totpsecret", "totpcode", "recoverycode", "recoverycodes", "encryptionkey")
    )


def has_secret_value(value):
    return value is not None and value != "" and value != [] and value != {}


def fixture_secret_paths(value, path=()):
    hits = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = path + (str(key),)
            if is_secret_key(key) and has_secret_value(child):
                hits.append(child_path)
            hits.extend(fixture_secret_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(fixture_secret_paths(child, path + (str(index),)))
    return hits


def load_fixture(path):
    if path.suffix.casefold() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix.casefold() in {".yaml", ".yml"}:
        try:
            import yaml
        except ModuleNotFoundError as error:
            raise AssertionError(f"Cannot inspect YAML fixture without PyYAML: {path}") from error
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    return None


def xml_secret_paths(path):
    hits = []
    root = ElementTree.parse(path).getroot()
    for element in root.iter():
        text = (element.text or "").strip()
        field_name = element.attrib.get("name")
        if field_name and is_secret_key(field_name) and has_secret_value(text):
            hits.append((element.tag, field_name))
        if is_secret_key(element.tag) and has_secret_value(text):
            hits.append((element.tag,))
        for name, value in element.attrib.items():
            if name != "name" and is_secret_key(name) and has_secret_value(value):
                hits.append((element.tag, name))
    return hits


class ScopeBoundaryTests(SimpleTestCase):
    def test_runtime_and_dev_dependencies_match_catalog_release_allowlists_and_lock(self):
        with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)
        with (PROJECT_ROOT / "uv.lock").open("rb") as stream:
            lock = tomllib.load(stream)

        runtime = {
            dependency_name(dependency)
            for dependency in project["project"]["dependencies"]
        }
        dev = {
            dependency_name(dependency)
            for dependency in project.get("dependency-groups", {}).get("dev", [])
        }
        locked_project = next(
            package
            for package in lock["package"]
            if package["name"] == project["project"]["name"]
        )
        locked_runtime = {
            normalize_package_name(dependency["name"])
            for dependency in locked_project["dependencies"]
        }
        locked_dev = {
            normalize_package_name(dependency["name"])
            for dependency in locked_project["dev-dependencies"]["dev"]
        }

        self.assertEqual(runtime, ALLOWED_RUNTIME_PACKAGES)
        self.assertEqual(dev, ALLOWED_DEV_PACKAGES)
        self.assertEqual(locked_runtime, ALLOWED_RUNTIME_PACKAGES)
        self.assertEqual(locked_dev, ALLOWED_DEV_PACKAGES)

    def test_installed_apps_exclude_future_non_goals(self):
        app_values = [str(value).casefold() for value in settings.INSTALLED_APPS]
        app_values.extend(
            f"{config.name} {config.label}".casefold()
            for config in apps.get_app_configs()
        )
        forbidden = {
            value: marker
            for value in app_values
            for marker in FORBIDDEN_APP_MARKERS
            if marker in value
        }
        self.assertEqual(forbidden, {})

    def test_project_urls_have_no_api_prefix_or_json_drf_callback(self):
        entries = list(iter_url_entries(get_resolver().url_patterns))
        api_entries = []
        project_entries = []
        for route, namespaces, callback in entries:
            route_parts = {
                part.casefold()
                for part in re.split(r"[/^$]+", route)
                if part
            }
            if "api" in route_parts or any(
                namespace.casefold() == "api" for namespace in namespaces
            ):
                api_entries.append(route)
            modules = callback_modules(callback)
            if any(module.startswith("open_marketplace.") for module in modules):
                project_entries.append((route, callback, modules))

        self.assertEqual(api_entries, [])
        for route, callback, modules in project_entries:
            with self.subTest(route=route, callback=callback):
                self.assertFalse(
                    any(
                        module == "rest_framework"
                        or module.startswith("rest_framework.")
                        for module in modules
                    )
                )
                self.assertFalse(callback_uses_json_response(callback))
                annotation = callback_return_annotation(callback)
                if isinstance(annotation, str):
                    self.assertNotIn("jsonresponse", annotation.casefold())
                elif inspect.isclass(annotation):
                    self.assertFalse(issubclass(annotation, JsonResponse))

    def test_registered_project_models_exclude_future_domains_and_upload_fields(self):
        project_models = [
            model
            for model in apps.get_models()
            if model.__module__.startswith("open_marketplace.")
        ]
        for model in project_models:
            with self.subTest(model=model._meta.label_lower):
                metadata = " ".join(
                    (model._meta.label_lower, model.__module__)
                ).casefold()
                self.assertFalse(
                    any(marker in metadata for marker in FORBIDDEN_MODEL_MARKERS)
                )
                self.assertEqual(
                    [
                        field.name
                        for field in model._meta.get_fields(include_hidden=True)
                        if isinstance(field, models.FileField)
                    ],
                    [],
                )

    def test_project_fixtures_contain_no_structural_secret_values(self):
        for path in fixture_paths():
            with self.subTest(fixture=path.relative_to(PROJECT_ROOT)):
                if path.suffix.casefold() == ".xml":
                    hits = xml_secret_paths(path)
                else:
                    hits = fixture_secret_paths(load_fixture(path))
                self.assertEqual(hits, [])
