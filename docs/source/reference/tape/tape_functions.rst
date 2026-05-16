.. currentmodule:: endf_parserpy

Tape functions
--------------

The following functions read and write ENDF-6 files that
contain several materials. They express a tape as a list of
ordinary material dictionaries, each of the same form as the
result of :func:`~endf_parserpy.EndfParserPy.parsefile`.

Each operation comes as a pair, mirroring the ``parse`` /
``parsefile`` naming of the single-material parser: the bare
name works on an in-memory ENDF-6 string, the ``_file`` variant
on a file path.

.. autofunction:: parse_tape

.. autofunction:: parse_tape_file

.. autofunction:: iter_parse_tape

.. autofunction:: iter_parse_tape_file

.. autofunction:: write_tape

.. autofunction:: write_tape_file

.. autoclass:: FailedMaterial
   :members:
