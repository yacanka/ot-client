"""Check local imports against exact filenames, even on Windows/macOS."""

import ast
import importlib
import importlib.util
from pathlib import Path
import runpy
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ImportTests(unittest.TestCase):
    def test_local_import_paths_and_symbols_exist_with_exact_case(self):
        sources = [ROOT / "otClient.py", ROOT / "ot_desktop.pyw",
                   *ROOT.joinpath("ot_app").glob("*.py"),
                   *ROOT.joinpath("tests").glob("*.py")]
        modules = {".".join(path.relative_to(ROOT).with_suffix("").parts)
                   for path in sources if path.suffix == ".py"}
        modules.update(name.removesuffix(".__init__") for name in tuple(modules)
                       if name.endswith(".__init__"))
        local_roots = {name.split(".")[0].casefold() for name in modules}
        for source in sources:
            package = ".".join(source.relative_to(ROOT).parts[:-1])
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    imports = [(alias.name, []) for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    name = "." * node.level + (node.module or "")
                    if node.level:
                        name = importlib.util.resolve_name(name, package)
                    imports = [(name, node.names)]
                else:
                    continue
                for name, symbols in imports:
                    if name.split(".")[0].casefold() not in local_roots:
                        continue
                    with self.subTest(file=str(source.relative_to(ROOT)), line=node.lineno, module=name):
                        self.assertIn(name, modules, "Local module filename/case mismatch")
                        module = importlib.import_module(name)
                        for symbol in symbols:
                            self.assertTrue(hasattr(module, symbol.name),
                                            f"{name} has no symbol {symbol.name}")

    def test_all_application_modules_load(self):
        for path in ROOT.joinpath("ot_app").glob("*.py"):
            name = "ot_app" if path.stem == "__init__" else f"ot_app.{path.stem}"
            with self.subTest(module=name):
                module = importlib.import_module(name)
                self.assertEqual(Path(module.__file__).resolve(), path.resolve())
        importlib.import_module("otClient")

    def test_desktop_script_loads_without_starting_gui_on_import(self):
        namespace = runpy.run_path(str(ROOT / "ot_desktop.pyw"))
        self.assertTrue(callable(namespace["startup_error"]))

    def test_missing_local_module_requests_complete_application_update(self):
        namespace = runpy.run_path(str(ROOT / "ot_desktop.pyw"))
        for name in ("OTClient", "otClient", "OT_app", "ot_app.app"):
            with self.subTest(module=name):
                error = ModuleNotFoundError(name=name)
                message = namespace["import_error_message"](error)
                self.assertIn("birlikte", message)
                self.assertIn("otClient.py", message)
                self.assertNotIn("Kurulum.cmd", message)

    def test_missing_dependency_requests_environment_setup(self):
        namespace = runpy.run_path(str(ROOT / "ot_desktop.pyw"))
        message = namespace["import_error_message"](ModuleNotFoundError(name="requests"))
        self.assertIn("Kurulum.cmd", message)
        self.assertIn("Baslat.cmd", message)
