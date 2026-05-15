.. currentmodule:: endf_parserpy

Tape functions
--------------

The following functions read and write ENDF-6 files that
contain several materials. They express a tape as a list of
ordinary material dictionaries, each of the same form as the
result of :func:`~endf_parserpy.EndfParserPy.parsefile`.

.. autofunction:: parse_tape

.. autofunction:: iter_parse_tape

.. autofunction:: write_tape

.. autoclass:: FailedMaterial
   :members:
