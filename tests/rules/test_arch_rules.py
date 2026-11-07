"""Cases for the module graph rules: no import cycle, a fan-out cap."""
import ast

from rules import arch_rules
from rules.arch_rules import cyclic_components, fanout_problems, graph_of, problems
from tltestkit.case import Case


class ArchitectureRules(Case):
    def test_repository_has_no_import_cycle_and_no_module_over_the_fanout_cap(self):
        assert problems() == []

    def graph(self, sources):
        return graph_of({name: ast.parse(text) for name, text in sources.items()})

    def test_lazy_and_relative_imports_form_a_module_scc(self):
        graph = self.graph({"pkg.a": "def f():\n from . import b", "pkg.b": "from pkg.a import f"})
        assert cyclic_components(graph) == [("pkg.a", "pkg.b")]

    def test_imports_of_siblings_in_package_init_are_edges(self):
        graph = self.graph({"pkg": "from . import a", "pkg.a": "import pkg"})
        assert cyclic_components(graph) == [("pkg", "pkg.a")]

    def test_type_checking_imports_and_self_imports_are_included(self):
        graph = self.graph({"a": "if TYPE_CHECKING:\n import b", "b": "import a", "c": "import c"})
        assert cyclic_components(graph) == [("a", "b"), ("c",)]

    def test_a_diamond_is_not_a_cycle(self):
        graph = self.graph({"a": "import b, c", "b": "import d", "c": "import d", "d": ""})
        assert cyclic_components(graph) == []

    def test_dotted_imports_and_literal_dynamic_imports_include_the_leaf_module(self):
        graph = self.graph({"a": "from importlib import import_module as load\nload('pkg.b')",
                            "pkg.b": "import a"})
        assert cyclic_components(graph) == [("a", "pkg.b")]
        graph = self.graph({"a": "import pkg.b", "pkg.b": "import a"})
        assert cyclic_components(graph) == [("a", "pkg.b")]

    def test_the_parent_packages_of_an_imported_module_are_not_fanout(self):
        sources = {"hub": "from pkg.sub import leaf", "pkg": "", "pkg.sub": "", "pkg.sub.leaf": ""}
        assert fanout_problems(self.graph(sources), cap=1) == []

    def test_a_module_over_the_fanout_cap_is_named_and_one_at_the_cap_is_not(self):
        sources = {"hub": "import a, b, c", "a": "", "b": "", "c": ""}
        assert fanout_problems(self.graph(sources), cap=3) == []
        assert [line.split()[0] for line in fanout_problems(self.graph(sources), cap=2)] == ["hub"]


def test_production_trees_leave_out_the_test_support_member():
    names = set(arch_rules.production_trees())
    assert not any(n == "tltestkit" or n.startswith("tltestkit.") for n in names)
    assert "tlkernel.ids" in names


def test_selected_production_graph_matches_full_graph_and_parses_only_sources(tmp_path, monkeypatch):
    sources = {"src/pkg/__init__.py": "from . import leaf",
               "src/pkg/leaf.py": "from . import sibling\nimport external.tool",
               "src/pkg/sibling.py": "import pkg.leaf",
               "packages/other/src/other/__init__.py": "",
               "packages/other/src/other/leaf.py": "import pkg.leaf"}
    for name, text in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    full = graph_of(arch_rules.production_trees(tmp_path))
    parsed_paths = []
    original = arch_rules.parsed

    def record(path):
        parsed_paths.append(path.relative_to(tmp_path).as_posix())
        return original(path)

    monkeypatch.setattr(arch_rules, "parsed", record)
    selected = arch_rules.production_graph("pkg.leaf", tmp_path)
    assert selected == {"pkg.leaf": full["pkg.leaf"]}
    assert selected["pkg.leaf"] == {"pkg", "pkg.sibling"}
    assert parsed_paths == ["src/pkg/leaf.py"]
