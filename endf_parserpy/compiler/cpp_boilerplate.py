############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2024/04/12
# Last modified:   2024/04/27
# License:         MIT
# Copyright (c) 2024 International Atomic Energy Agency (IAEA)
#
############################################################

from . import cpp_primitives as cpp
from .cpp_types.cpp_type_information import get_vartype_definitions


def module_header():
    code = r"""
    #include <pybind11/pybind11.h>
    #include <pybind11/stl.h> // Necessary for STL containers like std::map

    #include <stdexcept>
    #include <iostream>
    #include <sstream>
    #include <fstream>
    #include <vector>
    #include <string>

    namespace py = pybind11;


    double endfstr2float(const char* str) {
        char tbuf[13];
        int j = 0;
        bool in_number = false;
        bool in_exponent = false;
        for (int i=0; i < 11; i++) {
            char c = str[i];
            if (c == ' ') continue;
            if (in_number) {
                if (!in_exponent) {
                    if (c=='+' || c=='-') {
                        tbuf[j++] = 'e';
                        in_exponent = true;
                    } else if (c=='e' || c=='E') {
                        in_exponent = true;
                    }
                }
            } else {
                if (c == '.' || (c >= '0' && c <= '9')) {
                    in_number = true;
                }
            }
            tbuf[j++] = c;
        }
        if (j==0) tbuf[j++] = '0';
        tbuf[j++] = '\0';
        return std::stod(tbuf);
    }


    int endfstr2int(const std::string& str) {
        if (str.find_first_not_of(' ') == std::string::npos) {
            return 0;
        }
        return std::stoi(str);
    }


    double cpp_read_float_field(const char *str, const char fieldnum) {
        return endfstr2float(str+fieldnum*11);
    }


    double cpp_read_int_field(const std::string& str, const char fieldnum) {
        return endfstr2int(str.substr(fieldnum*11, 11));
    }


    double cpp_read_custom_int_field(const std::string& str, int start_pos, int length) {
        return endfstr2int(str.substr(start_pos, length));
    }


    std::string cpp_read_line(std::istream& cont) {
        std::string line;
        std::getline(cont, line);
        return line;
    }


    void cpp_read_send(std::istream& cont) {
        std::string line = cpp_read_line(cont);
        int mtnum = std::stoi(line.substr(72, 3));
        if (cpp_read_float_field(line.c_str(), 0) != 0.0 ||
            cpp_read_float_field(line.c_str(), 1) != 0.0 ||
            cpp_read_int_field(line, 2) != 0 ||
            cpp_read_int_field(line, 3) != 0 ||
            cpp_read_int_field(line, 4) != 0 ||
            cpp_read_int_field(line, 5) != 0 ||
            mtnum != 0) {

            std::cout << line << std::endl;  // debug
            throw std::runtime_error("expected SEND record");
        }
    }


    std::vector<int> cpp_read_int_vec(std::istream& cont, const int numel) {
        int j = 0;
        std::vector<int> res;
        std::string line = cpp_read_line(cont);
        for (int i=0; i < numel; i++) {
            res.push_back(cpp_read_int_field(line, j++));
            if (j > 5 && i+1 < numel) {
                line = cpp_read_line(cont);
                j = 0;
            }
        }
        return res;
    }


    std::vector<double> cpp_read_float_vec(std::istream& cont, const int numel) {
        int j = 0;
        std::vector<double> res;
        std::string line = cpp_read_line(cont);
        for (int i=0; i < numel; i++) {
            res.push_back(cpp_read_float_field(line.c_str(), j++));
            if (j > 5 && i+1 < numel) {
                line = cpp_read_line(cont);
                j = 0;
            }
        }
        return res;
    }
    """
    code = cpp.indent_code(code, -4)
    for vartype_definition in get_vartype_definitions():
        code += vartype_definition
    return code


def parsefun_header(fun_name):
    code = cpp.indent_code(
        rf"""
        py::dict {fun_name}(std::istream& cont) {{
            std::vector<int> cpp_intvec;
            std::vector<double> cpp_floatvec;
            py::dict cpp_parent_dict;
            py::dict cpp_current_dict;
            py::dict cpp_workdict;
            int cpp_idxnum;
            std::string cpp_line;
            double cpp_float_val;
        """,
        -8,
    )
    return code


def parsefun_footer():
    code = cpp.statement("return cpp_current_dict", 4)
    code += cpp.close_block()
    return code


def register_cpp_parsefuns(parsefuns, module_name):
    code = cpp.line("") + cpp.line("")
    code += cpp.line(f"PYBIND11_MODULE({module_name}, m) {{")
    for parsefun in parsefuns:
        curcode = cpp.statement(f'm.def("{parsefun}", &{parsefun}, "parsing function")')
        code += cpp.indent_code(curcode, 4)
    code += "\n}"
    return code


def generate_cmake_content(module_name):
    code = cpp.indent_code(
        f"""
        cmake_minimum_required(VERSION 3.12)
        project({module_name})

        find_package(pybind11 REQUIRED)

        # Create the C++ executable
        pybind11_add_module({module_name} SHARED {module_name}.cpp)

        add_compile_options(-O3)
        set_property(TARGET {module_name} PROPERTY CXX_STANDARD 11)
        """,
        -8,
    )
    return code
