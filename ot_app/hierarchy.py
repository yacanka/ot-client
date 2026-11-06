"""Immutable manual hierarchy operations on a forest in contiguous preorder.

Keys identify queue entries, independently of their document numbers. Every
parent must precede its children, and a subtree occupies one continuous range.
Invalid input or an incompatible selection raises ``HierarchyError`` without
changing the supplied entries.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class HierarchyEntry:
    key: str
    parent_key: str | None = None


class HierarchyError(ValueError):
    """The hierarchy or selected sibling block is invalid."""


def validate_hierarchy(entries: Sequence[HierarchyEntry]) -> None:
    """Validate unique keys and contiguous preorder in linear time, iteratively."""
    seen: set[str] = set()
    ancestors: list[str] = []
    active: set[str] = set()
    for entry in entries:
        if not isinstance(entry.key, str):
            raise HierarchyError("Satır anahtarı metin olmalıdır.")
        if entry.parent_key is not None and not isinstance(entry.parent_key, str):
            raise HierarchyError("Üst satır anahtarı metin veya boş olmalıdır.")
        if entry.key in seen:
            raise HierarchyError("Hiyerarşide yinelenen satır anahtarı var.")
        parent_key = entry.parent_key
        if parent_key is not None and parent_key not in seen:
            raise HierarchyError("Üst satır mevcut olmalı ve alt satırdan önce gelmelidir.")
        if parent_key is not None and parent_key not in active:
            raise HierarchyError("Bir üst satırın alt satırları kesintisiz sıralanmalıdır.")
        while ancestors and ancestors[-1] != parent_key:
            active.remove(ancestors.pop())
        ancestors.append(entry.key)
        active.add(entry.key)
        seen.add(entry.key)


def hierarchy_indices(entries: Sequence[HierarchyEntry]) -> dict[str, str]:
    """Return 1-based dotted indices in O(entries + output length), iteratively."""
    validate_hierarchy(entries)
    indices: dict[str, str] = {}
    sibling_counts: dict[str | None, int] = {}
    for entry in entries:
        parent_key = entry.parent_key
        sibling_counts[parent_key] = sibling_counts.get(parent_key, 0) + 1
        suffix = str(sibling_counts[parent_key])
        indices[entry.key] = suffix if parent_key is None else indices[parent_key] + "." + suffix
    return indices


def _selected_keys(entries: Sequence[HierarchyEntry], selected_keys: Iterable[str]) -> set[str]:
    selected = set(selected_keys)
    if selected.difference(entry.key for entry in entries):
        raise HierarchyError("Seçilen satırlardan biri hiyerarşide bulunamadı.")
    return selected


def _subtree_ends(entries: Sequence[HierarchyEntry]) -> dict[str, int]:
    """Return exclusive subtree boundaries; input has already been validated."""
    ends: dict[str, int] = {}
    ancestors: list[str] = []
    for index, entry in enumerate(entries):
        while ancestors and ancestors[-1] != entry.parent_key:
            ends[ancestors.pop()] = index
        ancestors.append(entry.key)
    for key in ancestors:
        ends[key] = len(entries)
    return ends


def _selected_roots(
    entries: Sequence[HierarchyEntry], selected: set[str], ends: dict[str, int]
) -> list[int]:
    roots: list[int] = []
    covered_until = 0
    for index, entry in enumerate(entries):
        if index >= covered_until and entry.key in selected:
            roots.append(index)
            covered_until = ends[entry.key]
    return roots


def _validate_sibling_block(
    entries: Sequence[HierarchyEntry], roots: Sequence[int], ends: dict[str, int]
) -> None:
    parent_key = entries[roots[0]].parent_key
    for previous, current in zip(roots, roots[1:]):
        if entries[current].parent_key != parent_key or ends[entries[previous].key] != current:
            raise HierarchyError("Aynı üst satıra bağlı, ardışık kardeş satırları seçin.")


def _reorder_sibling_block(
    entries: tuple[HierarchyEntry, ...], roots: Sequence[int], ends: dict[str, int], direction: str
) -> tuple[HierarchyEntry, ...]:
    start, stop = roots[0], ends[entries[roots[-1]].key]
    parent_key = entries[start].parent_key
    if direction == "up":
        previous = next((index for index in range(start - 1, -1, -1)
                         if entries[index].parent_key == parent_key), None)
        if previous is None:
            return entries
        return entries[:previous] + entries[start:stop] + entries[previous:start] + entries[stop:]
    if stop == len(entries) or entries[stop].parent_key != parent_key:
        return entries
    next_stop = ends[entries[stop].key]
    return entries[:start] + entries[stop:next_stop] + entries[start:stop] + entries[next_stop:]


def move_hierarchy(
    entries: Sequence[HierarchyEntry], selected_keys: Iterable[str], direction: str
) -> tuple[HierarchyEntry, ...]:
    """Reorder or indent/outdent consecutive siblings with their whole subtrees.

    Selected descendants of selected ancestors are ignored. Indenting the first
    sibling or outdenting roots leaves the forest unchanged. Outdented subtrees
    follow their former parent's entire remaining subtree. Up/down swaps the
    block with one adjacent sibling subtree, retaining every parent relationship;
    a block already at its parent's boundary is unchanged.
    """
    validate_hierarchy(entries)
    if direction not in ("indent", "outdent", "up", "down"):
        raise HierarchyError("Taşıma yönü 'indent', 'outdent', 'up' veya 'down' olmalıdır.")
    selected = _selected_keys(entries, selected_keys)
    original = tuple(entries)
    if not selected:
        return original
    ends = _subtree_ends(entries)
    roots = _selected_roots(entries, selected, ends)
    _validate_sibling_block(entries, roots, ends)
    if direction in ("up", "down"):
        return _reorder_sibling_block(original, roots, ends, direction)
    first = entries[roots[0]]
    parent_key = first.parent_key
    by_key = {entry.key: entry for entry in entries}
    if direction == "outdent":
        if parent_key is None:
            return original
        new_parent = by_key[parent_key].parent_key
    else:
        new_parent = None
        for entry in entries[:roots[0]]:
            if entry.parent_key == parent_key:
                new_parent = entry.key
        if new_parent is None:
            return original

    root_keys = {entries[index].key for index in roots}
    start, stop = roots[0], ends[entries[roots[-1]].key]
    block = tuple(
        replace(entry, parent_key=new_parent) if entry.key in root_keys else entry
        for entry in entries[start:stop]
    )
    if direction == "indent":
        return original[:start] + block + original[stop:]
    parent_stop = ends[parent_key]
    return original[:start] + original[stop:parent_stop] + block + original[parent_stop:]


def remove_hierarchy(
    entries: Sequence[HierarchyEntry], selected_keys: Iterable[str]
) -> tuple[HierarchyEntry, ...]:
    """Remove only selected entries and promote children to a surviving ancestor.

    Surviving entries retain preorder and any surviving parent relationships.
    Removed chains are resolved iteratively, including chains starting at roots.
    """
    validate_hierarchy(entries)
    selected = _selected_keys(entries, selected_keys)
    surviving_ancestor: dict[str | None, str | None] = {None: None}
    result: list[HierarchyEntry] = []
    for entry in entries:
        parent_key = surviving_ancestor[entry.parent_key]
        if entry.key in selected:
            surviving_ancestor[entry.key] = parent_key
            continue
        surviving_ancestor[entry.key] = entry.key
        result.append(replace(entry, parent_key=parent_key) if entry.parent_key != parent_key else entry)
    return tuple(result)
