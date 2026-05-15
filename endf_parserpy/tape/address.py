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

"""Material-qualified addressing for multi-material ENDF files.

An :class:`EndfMaterialPath` extends an :class:`EndfPath` with a leading
*material selector* so that a location can be addressed across a whole
tape. The two grammars are kept separate (design decision D13):
``EndfPath`` is unchanged and still addresses a location within one
material's parsed data; ``EndfMaterialPath`` prepends a material
selector to it.

Material selector grammar -- ``#`` selects the zero-based k-th member of
the candidate set to its left:

* ``MAT``    -- the unique material with that MAT number
* ``MAT#k``  -- the k-th material with that MAT number (PENDF tapes
                repeat a MAT number, once per temperature)
* ``#k``     -- the material at tape position k

The selector is followed by an ordinary ``EndfPath``, so
``9237#1/3/2/xstable`` selects the second material with MAT 9237 and the
``xstable`` field of its MF=3/MT=2 section.
"""

from ..utils.accessories import EndfPath
from .errors import AmbiguousMaterialError


class EndfMaterialPath:
    """A material selector followed by an :class:`EndfPath`.

    Parameters
    ----------
    pathspec : str or EndfMaterialPath
        The path, e.g. ``"9237#1/3/2/TEMP"``, ``"#0/1/451"`` or
        ``"2925/3/1"``.

    Attributes
    ----------
    mf, mt : int or None
        The section addressed by the path, or ``None`` if the path stops
        at material level.
    subpath : EndfPath or None
        The path *within* the parsed section, or ``None`` for the whole
        section.
    """

    def __init__(self, pathspec):
        if isinstance(pathspec, EndfMaterialPath):
            self.__dict__.update(pathspec.__dict__)
            return
        self._spec = str(pathspec).strip()
        parts = self._spec.strip("/").split("/")
        if parts == [""]:
            raise ValueError("an EndfMaterialPath must not be empty")
        self._parse_material(parts[0])
        rest = parts[1:]
        self.mf = int(rest[0]) if len(rest) >= 1 else None
        self.mt = int(rest[1]) if len(rest) >= 2 else None
        self.subpath = EndfPath("/".join(rest[2:])) if len(rest) > 2 else None

    def _parse_material(self, token):
        try:
            if token.startswith("#"):
                self._kind = "position"
                self._position = int(token[1:])
                self._mat = None
                self._occurrence = None
                if self._position < 0:
                    raise ValueError
            elif "#" in token:
                mat_str, occ_str = token.split("#", 1)
                self._kind = "mat"
                self._mat = int(mat_str)
                self._occurrence = int(occ_str)
                self._position = None
                if self._occurrence < 0:
                    raise ValueError
            else:
                self._kind = "mat"
                self._mat = int(token)
                self._occurrence = None
                self._position = None
        except ValueError:
            raise ValueError(
                f"invalid material selector {token!r}; expected MAT, MAT#k "
                "or #k with non-negative integers"
            ) from None

    def resolve_material(self, index):
        """Resolve the material selector against a :class:`TapeIndex`.

        Returns the zero-based position of the selected material.
        """
        if self._kind == "position":
            if not 0 <= self._position < len(index):
                raise IndexError(
                    f"material position {self._position} out of range; the "
                    f"tape has {len(index)} materials"
                )
            return self._position
        positions = index.by_mat(self._mat)
        if not positions:
            raise KeyError(f"no material with MAT={self._mat}")
        if self._occurrence is None:
            if len(positions) > 1:
                raise AmbiguousMaterialError(
                    f"MAT={self._mat} matches {len(positions)} materials at "
                    f"positions {positions}; use MAT#k to select one"
                )
            return positions[0]
        if not 0 <= self._occurrence < len(positions):
            raise IndexError(
                f"occurrence {self._occurrence} out of range; MAT={self._mat} "
                f"matches {len(positions)} materials"
            )
        return positions[self._occurrence]

    def __repr__(self):
        return f"EndfMaterialPath({self._spec!r})"

    def __eq__(self, other):
        if isinstance(other, EndfMaterialPath):
            return self._spec == other._spec
        return NotImplemented

    def __hash__(self):
        return hash(self._spec)


def parse_section_path(spec):
    """Parse a section-relative path ``"MF/MT[/field...]"``.

    Returns ``(mf, mt, subpath)`` where ``subpath`` is an
    :class:`EndfPath` or ``None`` (meaning the whole section). Used by
    the bulk query operations, which apply the same section path to
    every material.
    """
    parts = str(spec).strip().strip("/").split("/")
    if len(parts) < 2 or parts[0] == "":
        raise ValueError(
            f"section path {spec!r} must have at least MF/MT, e.g. '1/451'"
        )
    try:
        mf = int(parts[0])
        mt = int(parts[1])
    except ValueError:
        raise ValueError(f"section path {spec!r}: MF and MT must be integers") from None
    subpath = EndfPath("/".join(parts[2:])) if len(parts) > 2 else None
    return mf, mt, subpath


def section_has(section, subpath):
    """Return whether ``subpath`` is present within a parsed section."""
    if subpath is None:
        return True
    return subpath.exists(section)


def walk_section(section, subpath):
    """Return the value at ``subpath`` within a parsed section.

    ``subpath`` is an :class:`EndfPath`, or ``None`` for the whole
    section.
    """
    if subpath is None:
        return section
    return subpath.get(section)
