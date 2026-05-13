############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2024/04/23
# Last modified:   2026/05/13
# License:         MIT
# Copyright (c) 2024-2026 International Atomic Energy Agency (IAEA)
#
############################################################

import os
from endf_parserpy.endf_recipes import (
    get_recipe_dict,
    list_endf_flavors,
)
from .endf2cpp import generate_cpp_module_code, generate_shared_cpp_code
from .cpp_boilerplate import generate_cmake_content


SHARED_CPP_FILENAME = "_shared.cpp"


def create_cpp_parser_module(
    cpp_module_file, module_name, recipes=None, overwrite=False, shared_registry=None
):
    if not overwrite and os.path.exists(cpp_module_file):
        raise FileExistsError(f"file {cpp_module_file} exists already!")
    if recipes is None:
        recipes = get_recipe_dict("endf6-ext")
    cpp_module_code = generate_cpp_module_code(
        recipes, module_name, shared_registry=shared_registry
    )
    with open(cpp_module_file, "w") as f:
        f.write(cpp_module_code)


def create_cmake_file(project_path, module_name, overwrite=False):
    cmake_file = os.path.join(project_path, "CMakeLists.txt")
    if not overwrite and os.path.exists(cmake_file):
        raise FileExistsError(f"file {cmake_file} exists already!")
    cmake_content = generate_cmake_content(module_name)
    with open(cmake_file, "w") as f:
        f.write(cmake_content)


def create_project_files(
    project_path, module_name, recipes=None, path_exist_ok=False, overwrite_files=False
):
    if recipes is None:
        recipes = get_recipe_dict("endf6-ext")
    try:
        os.makedirs(project_path, exist_ok=path_exist_ok)
        os.makedirs(os.path.join(project_path, "build"), exist_ok=path_exist_ok)
    except FileExistsError:
        raise FileExistsError(f"the directory {project_path} exists already!")

    cpp_module_file = os.path.join(project_path, f"{module_name}.cpp")
    cmake_file = os.path.join(project_path, "CMakeLists.txt")

    create_cpp_parser_module(
        cpp_module_file, module_name, recipes, overwrite=overwrite_files
    )
    create_cmake_file(project_path, module_name, overwrite=overwrite_files)


def _prepare_cpp_parsers_subpackage(overwrite=False, only_filenames=False, dedup=True):
    """Generate per-flavor C++ pybind11 module sources.

    When ``dedup`` is True (default), parse and write function bodies
    that have an identical underlying ENDF recipe across multiple
    flavors are emitted only once into a separate ``_shared.cpp``,
    which is meant to be compiled once and linked into each flavor's
    extension module via ``extra_objects``.
    """
    endf_flavors = list_endf_flavors()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cpp_parsers_dir = os.path.join(script_dir, "../cpp_parsers")
    flavor_filenames = [f"{f.replace('-', '_')}.cpp" for f in endf_flavors]
    filenames = list(flavor_filenames)
    if dedup:
        filenames.append(SHARED_CPP_FILENAME)
    if only_filenames:
        return filenames
    shared_registry = {} if dedup else None
    for endf_flavor, module_file in zip(endf_flavors, flavor_filenames):
        print(f"---- compilation of {endf_flavor} ----")
        module_name = endf_flavor.replace("-", "_")
        cpp_module_path = os.path.join(cpp_parsers_dir, module_file)
        if not overwrite and os.path.exists(cpp_module_path):
            raise FileExistsError(f"The module {cpp_module_path} exists already!")
        recipe = get_recipe_dict(endf_flavor)
        create_cpp_parser_module(
            cpp_module_path,
            module_name,
            recipe,
            overwrite=overwrite,
            shared_registry=shared_registry,
        )
    if dedup:
        shared_path = os.path.join(cpp_parsers_dir, SHARED_CPP_FILENAME)
        if not overwrite and os.path.exists(shared_path):
            raise FileExistsError(f"The module {shared_path} exists already!")
        n_parse = len(shared_registry.get("parse", {}))
        n_write = len(shared_registry.get("write", {}))
        print(
            f"---- writing {SHARED_CPP_FILENAME} with {n_parse} parse + "
            f"{n_write} write deduplicated functions ----"
        )
        with open(shared_path, "w") as f:
            f.write(generate_shared_cpp_code(shared_registry))
    return filenames
