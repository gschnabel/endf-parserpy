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
   materials = parse_tape('tape.endf')   # a list, one entry per material
   len(materials)                        # number of materials on the tape

The argument can be a file path or a list of strings with
ENDF-6 formatted data. Each entry of the list is an ordinary
dictionary, identical to what the
:func:`~endf_parserpy.EndfParserPy.parsefile` method returns
for a single-material file, and is therefore indexed by MF
and then by MT number:

.. code:: Python

   material = materials[0]      # the first material, a dict
   section = material[3][2]     # its MF=3/MT=2 section, also a dict
   section['AWR']               # a field of that section

As for :func:`~endf_parserpy.EndfParserPy.parsefile`, the
``include`` and ``exclude`` arguments restrict parsing to
parts of each material; sections that are not parsed are
kept as lists of raw strings:

.. code:: Python

   # parse only MF=3 of every material, keep the rest as raw text
   materials = parse_tape('tape.endf', include=[3])

Because each material is an ordinary dictionary, modifying the
data before writing it back is a plain assignment. To change,
for instance, the atomic weight ratio in the MF1/MT451 section
of the first material:

.. code:: Python

   materials[0][1][451]['AWR'] = 63.5   # modify a value in place

The :ref:`guide on ENDF-6 file plumbing <endf6_file_plumbing_sec>`
covers modifying, adding and deleting data in more depth; the
same operations apply to every material of a tape.

The companion function :func:`~endf_parserpy.write_tape`
performs the reverse operation. Given a path, it writes the
tape to that file; without a path, it returns the assembled
ENDF-6 lines as a list of strings:

.. code:: Python

   from endf_parserpy import write_tape
   write_tape(materials, 'output.endf')      # write to a file
   lines = write_tape(materials)             # or obtain the lines

If a material cannot be parsed, the ``on_error`` argument
decides what happens. With the default ``'mark'``, the
offending material is returned as a
:class:`~endf_parserpy.FailedMaterial` object instead of a
dictionary. It keeps the raw content of the material, so the
remaining materials are still parsed and the tape can be
written back without loss:

.. code:: Python

   from endf_parserpy import FailedMaterial

   materials = parse_tape('tape.endf')   # on_error='mark' is the default
   for material in materials:
       if isinstance(material, FailedMaterial):
           # .mat is the MAT number, .exception the error that
           # occurred and .raw_lines the original text of the material
           print(material.mat, material.exception)
       else:
           ...   # an ordinary material dictionary

With ``on_error='raise'`` the first failure aborts the
operation instead:

.. code:: Python

   materials = parse_tape('tape.endf', on_error='raise')

For large tapes, the :func:`~endf_parserpy.iter_parse_tape`
function yields one material at a time instead of returning
the complete list, so that the peak memory consumption stays
bounded by the size of the largest material:

.. code:: Python

   from endf_parserpy import iter_parse_tape
   for material in iter_parse_tape('tape.endf'):
       ...   # one material, a dict or a FailedMaterial

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
   len(endf_file)                # number of materials on the tape

A material is addressed by its zero-based position on the
tape. Indexing an :class:`~endf_parserpy.EndfFile` returns a
:class:`~endf_parserpy.tape.MaterialView` — a lightweight
handle to one material — and iterating over the file yields
these handles in turn:

.. code:: Python

   material = endf_file[0]            # a MaterialView
   for material in endf_file:         # iterate over all materials
       print(material.position, material.mat, material.za)

Besides ``position``, ``mat``, ``za`` and ``awr``, a
:class:`~endf_parserpy.tape.MaterialView` reports the
sections the material contains:

.. code:: Python

   material.sections()        # list of the (MF, MT) pairs present

A section is addressed on a material by an ``(MF, MT)`` pair.
Accessing it parses that section and returns it as a
dictionary; a section for which no recipe exists is returned
as a list of raw strings instead:

.. code:: Python

   section = endf_file[0][3, 2]       # parsed MF=3/MT=2 section, a dict

Because the same material number (``MAT``) may occur several
times on a tape — a PENDF tape repeats it for every
temperature — materials are identified by position rather
than by ``MAT``. The :meth:`~endf_parserpy.EndfFile.by_mat`,
:meth:`~endf_parserpy.EndfFile.by_za` and
:meth:`~endf_parserpy.EndfFile.find` methods look materials
up by their identifiers:

.. code:: Python

   material = endf_file.by_mat(2925)     # the single material with MAT 2925
   materials = endf_file.by_za(29063)    # a list of materials with that ZA
   materials = endf_file.find(mat=2925)  # a list matching every criterion

:meth:`~endf_parserpy.EndfFile.by_mat` returns a single
:class:`~endf_parserpy.tape.MaterialView`, whereas
:meth:`~endf_parserpy.EndfFile.by_za` and
:meth:`~endf_parserpy.EndfFile.find` return a list of them.
If the ``MAT`` number is not unique,
:meth:`~endf_parserpy.EndfFile.by_mat` raises
:class:`~endf_parserpy.tape.AmbiguousMaterialError`, and the
copy of interest must then be selected with the
``occurrence`` argument:

.. code:: Python

   material = endf_file.by_mat(2925, occurrence=0)   # the first such material

The sections of a material can be replaced, added or
deleted, and whole materials can be deleted, appended or
reordered. Every edit is kept in memory until the tape is
written back:

.. code:: Python

   endf_file[0][3, 2] = section          # replace (or add) a section
   del endf_file[0][3, 18]               # delete a section
   del endf_file[1]                      # delete the second material

A new material — an ordinary ``{MF: {MT: section}}`` mapping,
such as one entry of a :func:`~endf_parserpy.parse_tape`
result — is appended with
:meth:`~endf_parserpy.EndfFile.append_material`, which
returns a :class:`~endf_parserpy.tape.MaterialView` of the
added material:

.. code:: Python

   donor = parse_tape('other.endf')[0]                 # a material dictionary
   new_material = endf_file.append_material(donor, mat=9999)

The materials can be reordered by passing a permutation of
their positions to :meth:`~endf_parserpy.EndfFile.reorder`:

.. code:: Python

   endf_file.reorder([1, 0])             # swap the first two materials

Finally, :meth:`~endf_parserpy.EndfFile.save` writes the
edited tape. As for :func:`~endf_parserpy.write_tape`, a path
writes the file and ``out=None`` returns the lines. Sections
that were not edited are written back verbatim, so an
unedited tape is reproduced byte for byte:

.. code:: Python

   endf_file.save('edited.endf')                 # write to a new file
   endf_file.save('tape.endf', overwrite=True)   # or overwrite the source

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
their sections and returns the matches as a list of
:class:`~endf_parserpy.tape.MaterialView` objects:

.. code:: Python

   from endf_parserpy import EndfParserCpp, EndfFile

   parser = EndfParserCpp(endf_format='pendf')
   endf_file = EndfFile('file.pendf', parser=parser)

   # the materials whose MF1/MT451 temperature is 293.6 K
   room_temp = endf_file.query('1/451/TEMP', 293.6, tol=1.0)
   xs = room_temp[0][3, 1]      # MF=3/MT=1 of the first match

The first argument is a path into an MF/MT section — here the
``TEMP`` field of the MF1/MT451 section — and the second the
value to match; the ``tol`` argument allows for a numerical
tolerance. Instead of a value, a ``predicate`` callable can
be supplied to match on an arbitrary condition:

.. code:: Python

   hot = endf_file.query('1/451/TEMP', predicate=lambda t: t > 1000.0)

If the same lookup is needed repeatedly, the
:meth:`~endf_parserpy.EndfFile.build_index` method parses the
section once per material and returns a dictionary that maps
each field value to the list of material positions carrying
it:

.. code:: Python

   temperatures = endf_file.build_index('1/451/TEMP')
   # e.g. {293.6: [0, 3], 600.0: [1, 4], ...}
   positions = temperatures[293.6]

A single value can also be retrieved directly with the
:meth:`~endf_parserpy.EndfFile.get` method and a
material-qualified path. Such a path, described by the
:class:`~endf_parserpy.EndfMaterialPath` class, extends an
ordinary :class:`~endf_parserpy.EndfPath` with a leading
material selector — a ``MAT`` number, ``MAT#k`` for the
``k``-th material carrying that ``MAT`` number, or ``#k``
for the material at position ``k``:

.. code:: Python

   endf_file.get('#0/1/451/AWR')        # AWR of the material at position 0
   endf_file.get('2925/3/2')            # the whole MF=3/MT=2 section of MAT 2925
   endf_file.get('2925#1/1/451/TEMP')   # a field of the 2nd MAT-2925 material

The path may stop at a section, in which case the whole
section is returned, or continue into it to address a single
field.

Path-addressed access and editing
---------------------------------

The :meth:`~endf_parserpy.EndfFile.get` method has a shorter
spelling: an :class:`~endf_parserpy.EndfFile` can be indexed
directly with an :class:`~endf_parserpy.EndfMaterialPath`. The
``[]``, ``[]=``, ``del`` and ``in`` operators all accept such a
path — a string or an :class:`~endf_parserpy.EndfMaterialPath`
object — in addition to an integer material position, so a tape
reads and edits like a path-addressable mapping:

.. code:: Python

   awr = endf_file['9237#1/3/2/AWR']     # read a field
   endf_file['9237#1/3/2/AWR'] = 63.5    # write a field
   section = endf_file['#0/3/2']         # read a whole section
   del endf_file['#0/3/18']              # delete a section
   del endf_file['#1']                   # delete a material
   present = '#0/1/451/TEMP' in endf_file  # test for presence

``endf_file.get(path)`` is the explicit-method synonym of
``endf_file[path]``; both return the same thing — a
:class:`~endf_parserpy.tape.MaterialView` for a material-depth
path, a section for an ``MF/MT`` path, and the value at the
field for a deeper path.

A retrieved section is not a plain dictionary but a *view* over
the tape, and what that view permits is governed by the
``check_edits`` argument of the :class:`~endf_parserpy.EndfFile`
constructor:

.. code:: Python

   from endf_parserpy import EndfFile

   strict = EndfFile('tape.endf')                          # check_edits='eager'
   relaxed = EndfFile('tape.endf', check_edits='deferred')

With ``check_edits='eager'`` (the default) every edit is rendered
through the parser's writer immediately, so a change that breaks
the ENDF recipe raises :class:`~endf_parserpy.tape.SectionRenderError`
at the offending assignment. A section retrieved in this mode is
a *read-only* view; to edit it, take a standalone copy with its
``detach()`` method, change the copy and assign it back:

.. code:: Python

   section = strict['#0/3/2'].detach()   # a plain, mutable dict
   section['QI'] = 0.0
   strict['#0/3/2'] = section            # rendered and checked here

With ``check_edits='deferred'`` a retrieved section is instead a
*live* view: assigning into it writes straight through to the
tape, exactly as for an :class:`~endf_parserpy.EndfDict`.
Recipe-conformity is then checked only when the tape is saved, or
on demand via :meth:`~endf_parserpy.EndfFile.verify`:

.. code:: Python

   relaxed['#0/3/2']['QI'] = 0.0         # writes through to the tape
   report = relaxed.verify()             # [] if every edit is conformant

A view — frozen or live — is itself path-addressable: a string
key is read as an :class:`~endf_parserpy.EndfPath` relative to
the view, so ``relaxed['#0/3/2']['xstable/E']`` and
``relaxed['#0/3/2/xstable/E']`` reach the same data.
