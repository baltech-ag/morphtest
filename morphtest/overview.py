"""HTML overview of a component hierarchy (roots, implementations, specializations, dependencies, mixins)."""

import html as html_lib
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import TextIO

from morphtest.component import Component, ComponentMeta

# https://lucide.dev/icons/circle-help
ICON_CIRCLE_HELP = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiIGNsYXNzPSJsdWNpZGUgbHVjaWRlLWNpcmNsZS1oZWxwLWljb24gbHVjaWRlLWNpcmNsZS1oZWxwIj48Y2lyY2xlIGN4PSIxMiIgY3k9IjEyIiByPSIxMCIvPjxwYXRoIGQ9Ik05LjA5IDlhMyAzIDAgMCAxIDUuODMgMWMwIDItMyAzLTMgMyIvPjxwYXRoIGQ9Ik0xMiAxN2guMDEiLz48L3N2Zz4="
# https://lucide.dev/icons/external-link
ICON_SOURCE = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik0xNSAzaDZ2NiIvPjxwYXRoIGQ9Ik0xMCAxNCAyMSAzIi8+PHBhdGggZD0iTTE4IDEzdjZhMiAyIDAgMCAxLTIgMkg1YTIgMiAwIDAgMS0yLTJWOGEyIDIgMCAwIDEgMi0yaDYiLz48L3N2Zz4="

_STYLE = """
.indented { padding-left: 1em; }
.small { font-size: smaller; }
.bold { font-weight: bold; }
.green { color: green; }
.orange { color: orange; }
.gray { color: gray; }
.blue { color: blue; }
.fixed-right-top { position: fixed; top: 0px; right: 1rem; }
.border { border: solid; padding: 0.5rem; }
.margin-bottom { margin-bottom: 1rem; }
.icon { height: 0.75rem; padding: 0 0 0 0.5rem; }
.leaf { display: list-item; list-style: disc inside; }
.hidden { display: none; }
.unset { all: unset; }
:target { background-color: rgba(45,170,225,0.25); }
"""

SourceUrl = Callable[[ComponentMeta], str | None]
Toggles = Mapping[str, Callable[[ComponentMeta], bool]]


class _OverviewWriter:
    def __init__(
        self,
        html: TextIO,
        *,
        entry_component: ComponentMeta | None,
        source_url: SourceUrl | None,
        toggles: Toggles,
    ) -> None:
        self.html = html
        self.entry_component = entry_component
        self.source_url = source_url
        self.toggles = dict(toggles)

    def write(self, roots: Iterable[ComponentMeta]) -> None:
        w = self.html.write
        w(f"<html><head><style>{_STYLE}</style></head><body>")

        w('<div style="width: 10%;" class="fixed-right-top border">')
        w("Legend:<ul>")
        w('<li class="bold">Root</li>')
        w('<li class="green">Implementation</li>')
        w('<li class="orange">Specialization</li>')
        w('<li class="blue">Dependency</li>')
        w('<li class="gray">Mixin</li>')
        w("</ul>")
        w('<button id="collapse" class="small">collapse</button>')
        w('<button id="expand" class="small">expand</button>')
        for idx, label in enumerate(self.toggles):
            w(
                f'<div><input type="checkbox" class="toggle" data-toggle="toggle-{idx}" id="toggle-{idx}" checked />'
                f'<label for="toggle-{idx}">{html_lib.escape(label)}</label></div>'
            )
        w("</div>")

        w('<div style="width: 85%;">')
        for root in self._sorted(roots):
            self._write_tree(root)
        w("</div>")

        w("<script>")
        w(
            "function toggle(classname, open) { document.querySelectorAll(`details.${classname}`).forEach(e => e.open = open) }\n"
            'document.querySelector("#collapse")?.addEventListener("click", () => toggle("component", false));\n'
            'document.querySelector("#expand")?.addEventListener("click", () => toggle("component", true));\n'
            'document.querySelectorAll("input.toggle").forEach(input => input.addEventListener("click", (e) =>'
            ' document.querySelectorAll(`.${e.target.dataset.toggle}`).forEach(c => c.classList.toggle("hidden", !e.target.checked))));\n'
        )
        if self.entry_component is not None:
            w(
                f'if(!window.location.hash) window.location.hash = "#{self.entry_component}";'
            )
        w("</script>")
        w("</body></html>")

    def _toggle_classes(self, component: ComponentMeta) -> list[str]:
        return [
            f"toggle-{idx}"
            for idx, predicate in enumerate(self.toggles.values())
            if predicate(component)
        ]

    def _write_tree(self, component: ComponentMeta) -> None:
        w = self.html.write
        details_classes = ["component", *self._toggle_classes(component)]
        summary_classes = _component_classes(component)
        if component.is_root:
            details_classes.append("margin-bottom")

        source_link = ""
        if self.source_url is not None and (url := self.source_url(component)):
            source_link = f'<a href="{html_lib.escape(url)}" target="_new"><img class="icon" src="{ICON_SOURCE}" /></a>'

        docstring = (component.__doc__ or "").strip()
        docstring_icon = (
            f'<button class="unset" popovertarget="{component}__docstring"><img class="icon" src="{ICON_CIRCLE_HELP}" /></button>'
            f'<pre popover id="{component}__docstring">{html_lib.escape(docstring)}</pre>'
            if docstring
            else ""
        )

        summary = f"{component}{source_link}{docstring_icon}{_mixins(component)}"

        if not component.dependencies() and not component.subclasses():
            # ohne Kinder gibt es nichts aufzuklappen -> Punkt statt Dreieck
            w(
                f'<div id="{component}" class="leaf {" ".join(details_classes)}">'
                f'<span class="{" ".join(summary_classes)}">{summary}</span></div>'
            )
            return

        w(f'<details id="{component}" open class="{" ".join(details_classes)}">')
        w(f'<summary class="{" ".join(summary_classes)}">{summary}</summary>')
        w('<div class="indented">')

        w('<div class="indented small">')
        for name, dependency in component.dependencies().items():
            link_to = dependency.component
            if not component.is_abstract and dependency.if_not_overwritten:
                link_to = dependency.if_not_overwritten
            w(f"{name}: {_link(link_to, ['blue'])}<br/>")
        w("</div>")

        for sub in self._sorted(component.subclasses()):
            if _primary_base(sub) is component:
                self._write_tree(sub)
            else:
                toggle_classes = self._toggle_classes(sub)
                cls_attr = (
                    f' class="{" ".join(toggle_classes)}"' if toggle_classes else ""
                )
                w(f"<li{cls_attr}>{_link(sub, _component_classes(sub))}</li>")

        w("</div>")
        w("</details>")

    def _sorted(self, components: Iterable[ComponentMeta]) -> Iterator[ComponentMeta]:
        yield from sorted(
            components,
            key=lambda component: (
                component is not self.entry_component,
                component.is_mixin,
                str(component),
            ),
        )


def _link(component: ComponentMeta, classes: list[str]) -> str:
    return f'<a href="#{component}" class="link {" ".join(classes)}">{component}</a>'


def _mixins(component: ComponentMeta) -> str:
    mixins = [base for base in component.bases() if base.is_mixin]
    if mixins:
        return f' <span class="small gray">({", ".join(_link(mixin, ["gray"]) for mixin in sorted(mixins, key=str))})</span>'
    return ""


def _primary_base(component: ComponentMeta) -> ComponentMeta:
    """Basis, unter der die Komponente im Baum vollständig dargestellt wird.

    Bei Mehrfachvererbung wird die Komponente unter allen anderen Basen nur verlinkt,
    damit jede Komponente (und damit jede HTML-ID) genau einmal vorkommt.
    """
    bases = [base for base in component.__bases__ if isinstance(base, ComponentMeta)]
    return next((base for base in bases if not base.is_mixin), bases[0])


def _component_classes(component: ComponentMeta) -> list[str]:
    classes = []
    if component.is_root:
        classes.append("bold")
    if not component.is_abstract:
        if all(b.is_abstract for b in component.bases()):
            classes.append("green")
        else:
            classes.append("orange")
    if component.is_mixin:
        classes.append("gray")
    return classes


def write_components_overview(  # noqa: PLR0913
    html: TextIO,
    meta_root: ComponentMeta = Component,
    *,
    roots: Iterable[ComponentMeta] | None = None,
    entry_component: ComponentMeta | None = None,
    source_url: SourceUrl | None = None,
    toggles: Toggles | None = None,
) -> None:
    """
    Writes an HTML overview of all (imported) components below meta_root.

    roots: the root components to show instead of all roots below meta_root
        (e.g. roots of several meta roots)
    entry_component: shown first and selected when the page is opened
    source_url: returns a link to the source of a component (e.g. on GitHub) or None
    toggles: label -> predicate; adds a checkbox per label which hides the matching components
    """
    if roots is None:
        roots = [
            component
            for component in meta_root.subclasses()
            if _primary_base(component) is meta_root
        ]
    _OverviewWriter(
        html,
        entry_component=entry_component,
        source_url=source_url,
        toggles=toggles or {},
    ).write(roots)


def save_components_overview(  # noqa: PLR0913
    path: Path | str,
    meta_root: ComponentMeta = Component,
    *,
    roots: Iterable[ComponentMeta] | None = None,
    entry_component: ComponentMeta | None = None,
    source_url: SourceUrl | None = None,
    toggles: Toggles | None = None,
) -> None:
    with Path(path).open(mode="w", encoding="utf-8") as html:
        write_components_overview(
            html,
            meta_root,
            roots=roots,
            entry_component=entry_component,
            source_url=source_url,
            toggles=toggles,
        )
