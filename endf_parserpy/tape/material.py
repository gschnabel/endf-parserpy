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

"""Read-only view of a single material within an :class:`EndfFile`."""


def _as_mfmt(key):
    """Validate and normalise an ``(MF, MT)`` section key."""
    if not (isinstance(key, tuple) and len(key) == 2):
        raise KeyError(
            "a section is addressed by an (MF, MT) pair, e.g. material[3, 2]"
        )
    mf, mt = key
    return int(mf), int(mt)


class MaterialView:
    """A lightweight, read-only handle to one material of an ``EndfFile``.

    Sections are addressed by an ``(MF, MT)`` pair and parsed lazily on
    access::

        section = material[3, 2]

    The view supports ``in``, iteration over its ``(MF, MT)`` keys and
    ``len()``.
    """

    def __init__(self, endf_file, entry):
        self._file = endf_file
        self._entry = entry

    @property
    def position(self):
        """Zero-based position of the material on the tape."""
        return self._entry.position

    @property
    def mat(self):
        """ENDF MAT number of the material."""
        return self._entry.mat

    @property
    def za(self):
        """ZA identifier of the material, or ``None`` if unknown."""
        return self._entry.za

    @property
    def awr(self):
        """Atomic weight ratio of the material, or ``None`` if unknown."""
        return self._entry.awr

    def sections(self):
        """Return the list of ``(MF, MT)`` section keys of this material."""
        return list(self._entry.sections.keys())

    def __getitem__(self, key):
        mf, mt = _as_mfmt(key)
        return self._file._get_section(self._entry.position, mf, mt)

    def __contains__(self, key):
        try:
            mfmt = _as_mfmt(key)
        except KeyError:
            return False
        return mfmt in self._entry.sections

    def __iter__(self):
        return iter(self._entry.sections.keys())

    def __len__(self):
        return len(self._entry.sections)

    def __repr__(self):
        return (
            f"<MaterialView position={self._entry.position} "
            f"MAT={self._entry.mat} ZA={self._entry.za}>"
        )
