"""Caller-owned Python edit surfaces; independent of model review advice.

AST preservation protects declared scientific controls, not arbitrary runtime
semantics. This is not a replacement for execution isolation.
"""

import ast
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PythonEditBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    boundary_id: str = Field(min_length=1)
    writable_symbols: dict[str, tuple[str, ...]]
    allow_new_functions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def safe_paths(self):
        for path in {*self.writable_symbols, *self.allow_new_functions}:
            parsed = PurePosixPath(path)
            if parsed.is_absolute() or ".." in parsed.parts or parsed.suffix != ".py":
                raise ValueError("edit boundary paths must be relative Python sources")
        return self

    def validate_candidate(self, sources: dict[str, str], replacements: dict[str, str]) -> None:
        if not set(replacements).issubset(sources):
            raise ValueError("candidate edits an unprovided file")
        if not {*self.writable_symbols, *self.allow_new_functions}.issubset(sources):
            raise ValueError("boundary refers to an unprovided file")
        for path, original in sources.items():
            candidate = replacements.get(path, original)
            allowed = set(self.writable_symbols.get(path, ()))
            before = ast.parse(original, filename=path)
            after = ast.parse(candidate, filename=path)
            original_bindings = _module_bindings(before)
            if path in self.allow_new_functions:
                retained = []
                added_names = set()
                for item in after.body:
                    if (
                        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name not in original_bindings
                    ):
                        if item.name in added_names:
                            raise ValueError("duplicate added helper definition")
                        added_names.add(item.name)
                        _passive_definition(item)
                    else:
                        retained.append(item)
                after.body = retained
            seen_before: set[str] = set()
            seen_after: set[str] = set()
            _mask(before, "", allowed, seen_before)
            _mask(after, "", allowed, seen_after)
            if seen_before != allowed or seen_after != allowed:
                raise ValueError(f"allowed symbols missing or removed: {path}")
            if ast.dump(before) != ast.dump(after):
                raise ValueError(f"protected Python structure changed: {path}")


def _module_bindings(module: ast.Module) -> set[str]:
    names = []
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.extend(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.extend(
                item.id
                for target in targets
                for item in ast.walk(target)
                if isinstance(item, ast.Name)
            )
    return set(names)


def _passive_definition(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    if node.decorator_list:
        raise ValueError("new helper decorators execute outside the allowed method body")
    for default in [*node.args.defaults, *node.args.kw_defaults]:
        if default is not None:
            try:
                ast.literal_eval(default)
            except (ValueError, TypeError) as exc:
                raise ValueError("new helper defaults must be literal") from exc
    annotations = [
        arg.annotation for arg in [*node.args.args, *node.args.kwonlyargs, *node.args.posonlyargs]
    ]
    annotations.append(node.returns)
    if any(
        isinstance(part, (ast.Call, ast.NamedExpr))
        for annotation in annotations
        if annotation is not None
        for part in ast.walk(annotation)
    ):
        raise ValueError("new helper annotations cannot invoke code")


def _mask(node, prefix: str, allowed: set[str], seen: set[str]) -> None:
    body = []
    local_names = set()
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if item.name in local_names:
                raise ValueError("duplicate class or function definition")
            local_names.add(item.name)
            name = prefix + item.name
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and name in allowed:
                _passive_definition(item)
                seen.add(name)
                item = ast.Expr(value=ast.Constant(value="editable:" + name))
            elif isinstance(item, ast.ClassDef):
                _mask(item, name + ".", allowed, seen)
        body.append(item)
    node.body = body
