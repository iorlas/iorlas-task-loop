"""Cases for the module graph rules: no import cycle, a fan-out cap."""
import ast

from support.case import Case

from rules.arch_rules import cyclic_components, fanout_problems, graph_of, problems


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
