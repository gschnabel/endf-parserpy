import sys
import os
from glob import glob
from pybind11.setup_helpers import (
    Pybind11Extension,
    intree_extensions,
    build_ext as pybind11_build_ext,
)
import logging
import platform


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# create a console handler to inform user about progress
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

# create a formatter
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)

# add the handler to the logger
logger.addHandler(console_handler)


def determine_optimization_flags():
    optim_env_var = os.environ.get("INSTALL_ENDF_PARSERPY_CPP_OPTIM", None)
    if optim_env_var is None:
        return []
    try:
        optim_level = int(optim_env_var)
    except ValueError:
        optim_level = None

    if optim_level is None or optim_level not in (0, 1, 2, 3):
        raise ValueError(
            "Optimization level provided in environment variable "
            "`INSTALL_ENDF_PARSERPY_CPP_OPTIM` must be 0, 1, 2 or 3"
        )

    if platform.system() in ("Darwin", "Linux"):  # macOS and Linux (gcc/clang)
        return [f"-O{optim_level}"]
    elif platform.system() == "Windows":  # Windows (MSVC)
        if optim_level == 3:
            optim_level = "x"
        return [f"/O{optim_level}"]
    else:
        return []  # use compiler default on unknown platform


class OptionalBuildExt(pybind11_build_ext):
    def run(self):
        try:
            logger.info(
                "Attempting to compile C++ code for reading/writing ENDF-6 files..."
            )
            super().run()
        except Exception as exc:
            logger.warn(
                f"Failed to compile C++ read/write module code. "
                + "Accelerated parsing will not be available."
            )


def build(setup_kwargs):
    # parse all ready-made endf recipes and put result files
    # in package cache directory so that they don't need to
    # be parsed again during package invocation by user
    from endf_parserpy.endf_recipes.utils import _populate_recipe_cache

    _populate_recipe_cache(clear_dir=True)

    # perform option C++ module compilation
    compile_env_var = os.environ.get("INSTALL_ENDF_PARSERPY_CPP", "optional")
    if compile_env_var == "no":
        logger.info(
            "Skipping generation of C++ ENDF-6 read/write module as per environment variable."
        )
        return

    optim_flags = determine_optimization_flags()
    # import function to generate C++ code
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    from endf_parserpy.compiler.compiler import _prepare_cpp_parsers_subpackage

    # generate the C++ code module with functions for reading and writing ENDF-6
    logger.info(
        "Generate the C++ modules with functions for reading and writing ENDF-6 files."
    )
    _prepare_cpp_parsers_subpackage(overwrite=True)
    # ext_modules = intree_extensions(glob("endf_parserpy/cpp_parsers/*.cpp"))
    subpackage_prefix = "endf_parserpy.cpp_parsers."
    cpp_files = glob("endf_parserpy/cpp_parsers/*.cpp")
    ext_modules = [
        Pybind11Extension(
            subpackage_prefix + os.path.splitext(os.path.basename(cpp_file))[0],
            [cpp_file],
            extra_compile_args=["-std=c++11"] + optim_flags,
        )
        for cpp_file in cpp_files
    ]

    my_build_ext = pybind11_build_ext if compile_env_var == "yes" else OptionalBuildExt
    setup_kwargs.update(
        {
            "ext_modules": ext_modules,
            "cmdclass": {"build_ext": my_build_ext},
            "zip_safe": False,
        }
    )
