"""Reverse import graph construction and transitive closure."""

from __future__ import annotations

from collections import deque

from testsniper.scanner import ModuleInfo


def build_reverse_graph(infos: dict[str, ModuleInfo]) -> dict[str, set[str]]:
    """Map each file to the set of files that import it.

    Module names can collide (every ``conftest.py`` is named ``conftest``),
    so nodes are relative paths and a dotted name resolves to every file
    that carries it. Collisions can only over-select, never under-select.
    """
    by_name: dict[str, set[str]] = {}
    for rel, info in infos.items():
        by_name.setdefault(info.module, set()).add(rel)

    reverse: dict[str, set[str]] = {rel: set() for rel in infos}
    for rel, info in infos.items():
        deps = set(info.deps) | info.star_imports
        for candidate in info.candidates:
            if candidate in by_name:
                deps.add(candidate)
        for dep in deps:
            for target in by_name.get(dep, ()):
                if target != rel:
                    reverse[target].add(rel)
    return reverse


def reverse_closure(reverse: dict[str, set[str]], seeds: dict[str, int]) -> dict[str, int]:
    """BFS over the reverse graph from seed files with initial distances.

    Returns the minimum import distance from any seed for every reachable
    file. Distance 0 is the changed file itself, 1 a direct importer, and
    so on.
    """
    dist = {rel: d for rel, d in seeds.items() if rel in reverse}
    queue: deque[str] = deque(sorted(dist, key=lambda r: dist[r]))
    while queue:
        current = queue.popleft()
        for importer in reverse.get(current, ()):
            if importer not in dist:
                dist[importer] = dist[current] + 1
                queue.append(importer)
    return dist


def importers_of(infos: dict[str, ModuleInfo], dotted: str) -> set[str]:
    """Files that reference a dotted module name directly.

    Used for deleted modules, which no longer exist on disk but whose
    importers still need their tests run.
    """
    return {rel for rel, info in infos.items() if dotted in info.all_referenced()}
