############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2026/05/15
# Last modified:   2026/05/15
# License:         MIT
# Copyright (c) 2026 International Atomic Energy Agency (IAEA)
#
############################################################

"""Bounded caches for the lazy multi-material tape interface.

Two cache tiers sit below the always-resident structural index:

* :class:`_RawCache` (Tier 1) holds the raw text of sections, keyed by
  ``(position, MF, MT)`` and bounded by a byte budget.
* :class:`_SectionCache` (Tier 2) holds parsed sections. It keeps strong
  references only within its byte budget; evicted entries are still held
  *weakly*, so a section the caller is still holding keeps its identity
  if it is looked up again before being garbage-collected.

Both caches weight an entry by the raw-text byte size of its section,
which is available for free from the structural index.
"""

from collections import OrderedDict
from weakref import WeakValueDictionary


class _Section(dict):
    """A parsed ENDF section.

    Behaves exactly like a :class:`dict`. It is defined as a ``dict``
    subclass so that instances can be weakly referenced, which
    :class:`_SectionCache` relies on to preserve object identity across
    eviction.
    """

    __slots__ = ("__weakref__",)


class _RawCache:
    """Byte-budgeted LRU cache of raw section text (Tier 1)."""

    def __init__(self, max_bytes):
        self.max_bytes = max_bytes
        self._od = OrderedDict()
        self._weights = {}
        self._size = 0

    def get(self, key):
        if key in self._od:
            self._od.move_to_end(key)
            return self._od[key]
        return None

    def put(self, key, value, weight):
        if key in self._od:
            self._size -= self._weights[key]
        self._od[key] = value
        self._od.move_to_end(key)
        self._weights[key] = weight
        self._size += weight
        # an item larger than the whole budget is kept on its own
        while self._size > self.max_bytes and len(self._od) > 1:
            old, _ = self._od.popitem(last=False)
            self._size -= self._weights.pop(old)

    def drop_material(self, position):
        for key in [k for k in self._od if k[0] == position]:
            self._size -= self._weights.pop(key)
            del self._od[key]

    def clear(self):
        self._od.clear()
        self._weights.clear()
        self._size = 0

    @property
    def nbytes(self):
        return self._size

    def __len__(self):
        return len(self._od)

    def __contains__(self, key):
        return key in self._od


class _SectionCache:
    """Weighted LRU cache of parsed sections (Tier 2).

    Strong references are kept only within ``max_bytes``; an evicted
    entry remains weakly referenced, so if the caller still holds the
    section it is returned (with its identity) on the next lookup
    instead of being re-parsed.
    """

    def __init__(self, max_bytes):
        self.max_bytes = max_bytes
        self._strong = OrderedDict()
        self._weak = WeakValueDictionary()
        self._weights = {}
        self._size = 0

    def get(self, key):
        if key in self._strong:
            self._strong.move_to_end(key)
            return self._strong[key]
        obj = self._weak.get(key)
        if obj is not None:
            # evicted from the strong cache but still alive elsewhere
            self._promote(key, obj)
            return obj
        return None

    def put(self, key, value, weight):
        self._weights[key] = weight
        try:
            self._weak[key] = value
        except TypeError:
            pass  # value not weakly referenceable; identity not preserved
        self._promote(key, value)

    def _promote(self, key, value):
        if key in self._strong:
            self._size -= self._weights[key]
        self._strong[key] = value
        self._strong.move_to_end(key)
        self._size += self._weights[key]
        while self._size > self.max_bytes and len(self._strong) > 1:
            old, _ = self._strong.popitem(last=False)
            self._size -= self._weights[old]

    def drop_material(self, position):
        for key in [k for k in self._strong if k[0] == position]:
            self._size -= self._weights[key]
            del self._strong[key]
        for key in [k for k in self._weights if k[0] == position]:
            del self._weights[key]
        for key in [k for k in list(self._weak) if k[0] == position]:
            self._weak.pop(key, None)

    def clear(self):
        self._strong.clear()
        self._weak.clear()
        self._weights.clear()
        self._size = 0

    @property
    def nbytes(self):
        return self._size

    def __len__(self):
        return len(self._strong)

    def __contains__(self, key):
        return key in self._strong or self._weak.get(key) is not None
