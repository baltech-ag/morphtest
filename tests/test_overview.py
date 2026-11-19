import abc
import io

from morphtest.component import ComponentMeta, Dependency, if_not_overwritten, mixin
from morphtest.overview import write_components_overview


def test_writes_every_component_once() -> None:
    # fmt: off
    class Base(metaclass=ComponentMeta): pass
    class A(Base, abc.ABC): """A docstring"""
    @mixin
    class A_Mixin(A, abc.ABC): pass
    class A_0(A): pass
    class A_0_Mixin(A_Mixin, A_0): pass
    class Entry(Base): a: Dependency[A] = if_not_overwritten(A_0)
    # fmt: on

    html = io.StringIO()
    write_components_overview(
        html,
        Base,
        entry_component=Entry,
        source_url=lambda c: f"https://example.com/{c}",
        toggles={"Mixins": lambda c: issubclass(c, A_Mixin)},
    )
    content = html.getvalue()

    for component in (A, A_Mixin, A_0, A_0_Mixin, Entry):
        assert content.count(f'id="{component}"') == 1
    assert "https://example.com/" in content
    assert "A docstring" in content
    assert content.index(f'id="{Entry}"') < content.index(f'id="{A}"')
