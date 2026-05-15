.. _multimaterial_files_sec:

Multi-Material Files
====================

An ENDF-6 file may contain several materials, stored one
after another; such a file is traditionally called a *tape*.
The :ref:`ordinary parser <getting_started_sec>` expects a
single material per file, but ``endf-parserpy`` provides a
dedicated interface for tapes. It also covers the PENDF and
GENDF tapes produced by :ref:`processing codes <related_software>`,
which repeat the same material at several temperatures.
On this page, we explain how to read, write and navigate
such files.

Reading and writing a tape
--------------------------

The :func:`~endf_parserpy.parse_tape` function reads a
multi-material file and returns a list with one entry per
material:

.. code:: Python

   from endf_parserpy import parse_tape
   materials = parse_tape('tape.endf')

The argument can be a file path or a list of strings with
ENDF-6 formatted data. Each entry is an ordinary dictionary,
identical to what the :func:`~endf_parserpy.EndfParserPy.parsefile`
method returns for a single-material file, and can be accessed
and modified in the same way, unless that material failed to
parse (see below). As for
:func:`~endf_parserpy.EndfParserPy.parsefile`, the ``include``
and ``exclude`` arguments restrict parsing to parts of each
material.

The companion function :func:`~endf_parserpy.write_tape`
performs the reverse operation:

.. code:: Python

   from endf_parserpy import write_tape
   write_tape(materials, 'output.endf')

If a material cannot be parsed, the ``on_error`` argument
determines what happens. With the default ``'mark'``, the
offending material is returned as a
:class:`~endf_parserpy.FailedMaterial` object that preserves
its raw content, so that the remaining materials are still
parsed and the tape can be written back without loss. With
``on_error='raise'``, the first failure aborts the operation.

For large tapes, the :func:`~endf_parserpy.iter_parse_tape`
function yields one material at a time instead of returning
the complete list, so that the peak memory consumption stays
bounded by the size of the largest material:

.. code:: Python

   from endf_parserpy import iter_parse_tape
   for material in iter_parse_tape('tape.endf'):
       ...   # process one material

Lazy access with EndfFile
-------------------------

When only some materials or sections of a large tape are
relevant, parsing the complete file is wasteful. The
:class:`~endf_parserpy.EndfFile` class indexes the file on
construction and reads and parses an individual section from
disk only when it is accessed:

.. code:: Python

   from endf_parserpy import EndfFile
   endf_file = EndfFile('tape.endf')
   print(len(endf_file))        # number of materials on the tape

A material is addressed by its zero-based position on the
tape and an MF/MT section by an ``(MF, MT)`` pair:

.. code:: Python

   material = endf_file[0]      # the first material
   section = material[3, 2]     # its parsed MF=3/MT=2 section

Because the same material number (``MAT``) may occur several
times on a tape — a PENDF tape repeats it for every
temperature — materials are identified by position rather
than by ``MAT``. The :meth:`~endf_parserpy.EndfFile.by_mat`
and :meth:`~endf_parserpy.EndfFile.by_za` methods return the
positions that match a given ``MAT`` or ``ZA`` number.

Sections can be replaced, added or deleted, and the edited
tape written back with the :meth:`~endf_parserpy.EndfFile.save`
method:

.. code:: Python

   material[3, 2] = section     # replace a section
   del material[3, 18]          # delete a section
   endf_file.save('edited.endf')

Sections that were not edited are written back verbatim, so
an unedited tape is reproduced byte for byte. Whole materials
can likewise be deleted, appended with
:meth:`~endf_parserpy.EndfFile.append_material` or reordered
with :meth:`~endf_parserpy.EndfFile.reorder`.

.. note::

   The structural index that :class:`~endf_parserpy.EndfFile`
   builds on construction is faster to compute when
   `NumPy <https://numpy.org/>`_ is available. Installing the
   package with the ``fast`` extra pulls in this optional
   dependency; without it a pure-Python fallback is used.

Selecting a material by its content
-----------------------------------

On a tape that repeats the same material, the position is
often not the most convenient way to pick a particular copy.
A PENDF tape, for example, stores the same material at a
series of temperatures, and one usually wants the copy at a
specific temperature. The :meth:`~endf_parserpy.EndfFile.query`
method selects materials by the value of a field in one of
their sections:

.. code:: Python

   from endf_parserpy import EndfParserCpp, EndfFile

   parser = EndfParserCpp(endf_format='pendf')
   endf_file = EndfFile('file.pendf', parser=parser)

   # the materials whose MF1/MT451 temperature is 293.6 K
   room_temp = endf_file.query('1/451/TEMP', 293.6, tol=1.0)

The first argument is a path into an MF/MT section — here the
``TEMP`` field of the MF1/MT451 section — and the second the
value to match; the ``tol`` argument allows for a numerical
tolerance. The method returns the matching materials, which
can then be accessed as usual:

.. code:: Python

   xs = room_temp[0][3, 1]      # MF=3/MT=1 at 293.6 K

If the same query is needed repeatedly, the
:meth:`~endf_parserpy.EndfFile.build_index` method builds a
reusable mapping from field values to material positions.

A single value can also be retrieved directly with the
:meth:`~endf_parserpy.EndfFile.get` method and a
material-qualified path. Such a path, described by the
:class:`~endf_parserpy.EndfMaterialPath` class, extends an
ordinary :class:`~endf_parserpy.EndfPath` with a leading
material selector — a ``MAT`` number, ``MAT#k`` for the
``k``-th material carrying that ``MAT`` number, or ``#k``
for the material at position ``k``:

.. code:: Python

   awr = endf_file.get('#0/1/451/AWR')
