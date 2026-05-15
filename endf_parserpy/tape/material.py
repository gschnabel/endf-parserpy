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

"""Per-material state and views for :class:`EndfFile`."""


def _as_mfmt(key):
    """Validate and normalise an ``(MF, MT)`` section key."""
    if not (isinstance(key, tuple) and len(key) == 2):
        raise KeyError(
            "a section is addressed by an (MF, MT) pair, e.g. material[3, 2]"
        )
    mf, mt = key
    return int(mf), int(mt)


class _MaterialSlot:
    """Mutable per-material state in an :class:`EndfFile`.

    A slot represents one material in the (possibly edited) tape. For a
    material that came from the file ``original_position`` indexes the
    backing :class:`TapeIndex`; for a material added in memory it is
    ``None``. ``overlay`` holds sections that were set or added (keyed
    by ``(MF, MT)``), and ``deleted`` the ``(MF, MT)`` keys removed from
    the original material.
    """

    def __init__(self, original_position=None, mat=None, za=None, awr=None):
        self.original_position = original_position
        self.mat = mat
        self.za = za
        self.awr = awr
        self.overlay = {}
        self.deleted = set()

    @property
    def is_modified(self):
        """Whether the slot differs from its original on-disk material."""
        return bool(self.overlay or self.deleted or self.original_position is None)


class MaterialView:
    """A handle to one material of an :class:`EndfFile`.

    Sections are addressed by an ``(MF, MT)`` pair and parsed lazily on
    access. A section can be read, replaced, added or deleted::

        section = material[3, 2]
        material[3, 2] = edited_section
        del material[3, 2]

    The view is bound to the underlying material, so it stays valid if
    the tape is reordered; it becomes invalid only if that material is
    deleted.
    """

    def __init__(self, endf_file, slot):
        self._file = endf_file
        self._slot = slot

    @property
    def position(self):
        """The material's current zero-based position on the tape."""
        return self._file._position_of(self._slot)

    @property
    def mat(self):
        """ENDF MAT number of the material."""
        return self._slot.mat

    @property
    def za(self):
        """ZA identifier of the material, or ``None`` if unknown."""
        return self._slot.za

    @property
    def awr(self):
        """Atomic weight ratio of the material, or ``None`` if unknown."""
        return self._slot.awr

    @property
    def is_modified(self):
        """Whether this material has been edited."""
        return self._slot.is_modified

    def sections(self):
        """Return the list of ``(MF, MT)`` section keys of this material."""
        return self._file._slot_section_keys(self._slot)

    def __getitem__(self, key):
        return self._file._get_slot_section(self._slot, *_as_mfmt(key))

    def __setitem__(self, key, value):
        self._file._set_slot_section(self._slot, *_as_mfmt(key), value)

    def __delitem__(self, key):
        self._file._delete_slot_section(self._slot, *_as_mfmt(key))

    def __contains__(self, key):
        try:
            mfmt = _as_mfmt(key)
        except KeyError:
            return False
        return mfmt in self._file._slot_section_keys(self._slot)

    def __iter__(self):
        return iter(self._file._slot_section_keys(self._slot))

    def __len__(self):
        return len(self._file._slot_section_keys(self._slot))

    def __repr__(self):
        return (
            f"<MaterialView position={self.position} "
            f"MAT={self._slot.mat} ZA={self._slot.za}>"
        )
