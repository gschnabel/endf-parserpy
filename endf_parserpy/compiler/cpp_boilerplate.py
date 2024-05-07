############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2024/04/12
# Last modified:   2024/05/07
# License:         MIT
# Copyright (c) 2024 International Atomic Energy Agency (IAEA)
#
############################################################

from . import cpp_primitives as cpp
from .cpp_types.cpp_type_information import get_vartype_definitions
from .cpp_types.cpp_vartype_handling import (
    construct_vartype_dtype_enum,
    construct_vartype2str_func,
    construct_vartype_validation_func,
)


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


    struct ParsingOptions {
      bool ignore_number_mismatch;
      bool ignore_zero_mismatch;
      bool ignore_varspec_mismatch;
      bool accept_spaces;
      bool ignore_send_records;
      bool ignore_missing_tpid;
      bool validate_control_records;
    };


    ParsingOptions default_parsing_options() {
      return ParsingOptions{
        false,  // ignore_number_mismatch
        true,  // ignore_zero_mismatch
        false,  // ignore_varspec_mismatch
        true,  // accept_spaces
        false,  // ignore_send_records
        false,  // ignore_missing_tpid
        false  // validate_control_records
      };
    }


    namespace pybind11 { namespace detail {
      template <> struct type_caster<ParsingOptions> {
      public:
        PYBIND11_TYPE_CASTER(ParsingOptions, _("ParsingOptions"));

        // conversion from Python to C++
        bool load(handle src, bool) {
          if (!py::isinstance<py::dict>(src))
            return false;
          auto d = reinterpret_borrow<py::dict>(src);

          if (d.contains("ignore_number_mismatch")) {
            value.ignore_number_mismatch = d["ignore_number_mismatch"].cast<bool>();
          } else {
            value.ignore_number_mismatch = false;
          }

          if (d.contains("ignore_zero_mismatch")) {
            value.ignore_zero_mismatch = d["ignore_zero_mismatch"].cast<bool>();
          } else {
            value.ignore_zero_mismatch = true;
          }

          if (d.contains("ignore_varspec_mismatch")) {
            value.ignore_varspec_mismatch = d["ignore_varspec_mismatch"].cast<bool>();
          } else {
            value.ignore_varspec_mismatch = false;
          }

          if (d.contains("accept_spaces")) {
            value.accept_spaces = d["accept_spaces"].cast<bool>();
          } else {
            value.accept_spaces = true;
          }

          if (d.contains("ignore_send_records")) {
            value.ignore_send_records = d["ignore_send_records"].cast<bool>();
          } else {
            value.ignore_send_records = false;
          }

          if (d.contains("ignore_missing_tpid")) {
            value.ignore_missing_tpid = d["ignore_missing_tpid"].cast<bool>();
          } else {
            value.ignore_missing_tpid = false;
          }

          if (d.contains("validate_control_records")) {
            value.validate_control_records = d["validate_control_records"].cast<bool>();
          } else {
            value.validate_control_records = false;
          }

          return true;
        }

        // conversion from C++ to Python
        static handle cast(const ParsingOptions &src, return_value_policy, handle) {
          py::dict d;
          d["ignore_number_mismatch"] = src.ignore_number_mismatch;
          d["ignore_zero_mismatch"] = src.ignore_zero_mismatch;
          d["ignore_varspec_mismatch"] = src.ignore_varspec_mismatch;
          d["accept_spaces"] = src.accept_spaces;
          d["ignore_send_records"] = src.ignore_send_records;
          d["ignore_missing_tpid"] = src.ignore_missing_tpid;
          d["validate_control_records"] = src.validate_control_records;
          return d.release();
        }

      };
    }}


    template<typename U, typename V, typename W>
    void throw_mismatch_error(U quantity, V expected_value, W actual_value, std::string line) {
      std::stringstream errmsg;
      errmsg << "Invalid " << quantity << " encountered! "
             << "Expected " << quantity << "=" << expected_value
             << " but found " << quantity <<"=" << actual_value << std::endl;
      if (line.size() > 0) {
        errmsg << "This happened while processing the following line:" << std::endl
               << line;
      }
      throw std::runtime_error(errmsg.str());
    }


    double endfstr2float(const char* str, ParsingOptions &parse_opts) {
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
          if (c == '.' || (c >= '0' && c <= '9') || c == '-' || c == '+') {
            in_number = true;
          }
        }
        tbuf[j++] = c;
      }
      if (j==0) tbuf[j++] = '0';
      tbuf[j++] = '\0';
      return std::stod(tbuf);
    }


    int endfstr2int(const char* str, ParsingOptions &parse_opts) {
      char strzero[12];
      std::memcpy(strzero, str, 11);
      strzero[11] = '\0';
      for (int i=0; i < 11; i++) {
        if (str[i] != ' ') {
          return std::atoi(strzero);
        }
      }
      return 0;
    }


    template<typename T>
    T cpp_read_field(const char *str, const char fieldnum, ParsingOptions &parse_opts) {
      static_assert(std::is_same<T, double>::value || std::is_same<T, int>::value, "T must be int or double");
      if (std::is_same<T, double>::value) {
        return endfstr2float(str+fieldnum*11, parse_opts);
      } else {
        return endfstr2int(str+fieldnum*11, parse_opts);
      }
    }


    double cpp_read_custom_int_field(const char *str, int start_pos, int length) {
      char strzero[length+1];
      std::memcpy(strzero, str+start_pos, length);
      strzero[length] = '\0';
      for (int i=0; i < length; i++) {
        if (strzero[i] != ' ') {
          return std::atoi(strzero);
        }
      }
      return 0;
    }


    int cpp_read_mat_number(const char *str) {
      return cpp_read_custom_int_field(str, 66, 4);
    }


    int cpp_read_mf_number(const char *str) {
      return cpp_read_custom_int_field(str, 70, 2);
    }


    int cpp_read_mt_number(const char *str) {
      return cpp_read_custom_int_field(str, 72, 3);
    }


    std::string cpp_read_raw_line(std::istream& cont) {
      std::string line;
      std::getline(cont, line);
      return line;
    }


    std::string cpp_read_line(
      std::istream& cont, int mat, int mf, int mt, ParsingOptions &parse_opts
    ) {
      std::string line;
      std::getline(cont, line);
      return line;
    }


    std::string cpp_read_send(std::istream& cont, int mat, int mf, ParsingOptions &parse_opts) {
      std::string line = cpp_read_line(cont, mat, mf, 0, parse_opts);
      int mtnum = cpp_read_custom_int_field(line.c_str(), 72, 3);
      if (cpp_read_field<double>(line.c_str(), 0, parse_opts) != 0.0 ||
        cpp_read_field<double>(line.c_str(), 1, parse_opts) != 0.0 ||
        cpp_read_field<int>(line.c_str(), 2, parse_opts) != 0 ||
        cpp_read_field<int>(line.c_str(), 3, parse_opts) != 0 ||
        cpp_read_field<int>(line.c_str(), 4, parse_opts) != 0 ||
        cpp_read_field<int>(line.c_str(), 5, parse_opts) != 0 ||
        mtnum != 0) {

        std::cout << line << std::endl;  // debug
        throw std::runtime_error("expected SEND record");
      }
      return line;
    }


    template<typename T>
    std::vector<T> cpp_read_vec(
      std::istream& cont, const int numel, int mat, int mf, int mt, ParsingOptions &parse_opts
    ) {
      int j = 0;
      std::vector<T> res;
      std::string line = cpp_read_line(cont, mat, mf, mt, parse_opts);
      for (int i=0; i < numel; i++) {
        res.push_back(cpp_read_field<T>(line.c_str(), j++, parse_opts));
        if (j > 5 && i+1 < numel) {
          line = cpp_read_line(cont, mat, mf, mt, parse_opts);
          j = 0;
        }
      }
      return res;
    }


    struct Tab1Body {
      std::vector<int> INT;
      std::vector<int> NBT;
      std::vector<double> X;
      std::vector<double> Y;
    };


    struct Tab2Body {
      std::vector<int> INT;
      std::vector<int> NBT;
    };


    Tab2Body read_tab2_body(
      std::istream& cont, int nr, int mat, int mf, int mt, ParsingOptions &parse_opts
    ) {
      Tab2Body tab_body;
      std::vector<int> interp = cpp_read_vec<int>(cont, 2*nr, mat, mf, mt, parse_opts);
      int j = 0;
      for (int i=0; i < nr; i++) {
        tab_body.NBT.push_back(interp[j++]);
        tab_body.INT.push_back(interp[j++]);
      }
      return tab_body;
    }


    Tab1Body read_tab1_body(
      std::istream& cont, int nr, int np,
      int mat, int mf, int mt, ParsingOptions &parse_opts
    ) {
      Tab1Body tab_body;
      std::vector<int> interp = cpp_read_vec<int>(cont, 2*nr, mat, mf, mt, parse_opts);
      int j = 0;
      for (int i=0; i < nr; i++) {
        tab_body.NBT.push_back(interp[j++]);
        tab_body.INT.push_back(interp[j++]);
      }
      std::vector<double> data = cpp_read_vec<double>(cont, 2*np, mat, mf, mt, parse_opts);
      j = 0;
      for (int i=0; i < np; i++) {
        tab_body.X.push_back(data[j++]);
        tab_body.Y.push_back(data[j++]);
      }
      return tab_body;
    }


    bool seq_contains(py::sequence seq, py::object value) {
      int i = 0;
      for (const auto& item : seq) {
        if (py::cast<py::object>(item).equal(value)) {
          return true;
        }
      }
      return false;
    }


    bool should_parse_section(int mf, int mt, py::object& exclude, py::object& include) {
      py::tuple mf_mt_tup = py::make_tuple(mf, mt);
      if (! exclude.is_none()) {
        if (! py::isinstance<py::sequence>(exclude)) {
          throw std::runtime_error("`exclude` argument must be of sequence type");
        }
        if (seq_contains(exclude, py::int_(mf)) || seq_contains(exclude, mf_mt_tup)) {
          return false;
        } else {
          return true;
        }
      } else if (! include.is_none()) {
        if (! py::isinstance<py::sequence>(include)) {
          throw std::runtime_error("`include` argument must be of sequence type");
        }
        if (seq_contains(include, py::int_(mf)) || seq_contains(include, mf_mt_tup)) {
          return true;
        } else {
          return false;
        }
      } else {
        return true;
      }
    }


    std::vector<std::string> read_section_verbatim(
        int mat, int mf, int mt, std::istream& cont, bool is_first, ParsingOptions &parse_opts
    ) {
      std::streampos curpos;
      std::string line;
      std::vector<std::string> secvec;
      int curmf;
      int curmt;
      size_t lastpos;
      while (! cont.eof()) {
        line = cpp_read_line(cont, mat, mf, mt, parse_opts);
        // remove trailing \r that we may
        // get from reading win-style line endings
        lastpos = line.size() - 1;
        if (line[lastpos] == '\r') {
          line.erase(lastpos);
        }
        curmf = std::stoi(line.substr(70, 2));
        curmt = std::stoi(line.substr(72, 3));
        if (curmf != mf || curmt != mt) break;
        // the newline for compatibility with the Python parser
        secvec.push_back(line + "\n");
        curpos = cont.tellg();
      }
      if (! is_first && (curmf != mf || curmt != 0)) {
         std::string errmsg = "expected SEND of MF/MT " +
                              std::to_string(mf) + "/" + std::to_string(mt);
         throw std::runtime_error(errmsg);
      }
      if (is_first) {
        // we rewind one line because in the case of MF0/MT0 (tapeid)
        // we have also consumed the HEAD record of the next section
        cont.seekg(curpos);
      }
      return secvec;
    }
    """
    code = cpp.indent_code(code, -4)
    code += cpp.line("")
    code += construct_vartype_dtype_enum()
    code += cpp.line("")
    code += construct_vartype2str_func()
    code += cpp.line("")
    code += construct_vartype_validation_func()
    for vartype_definition in get_vartype_definitions():
        code += vartype_definition
    return code


def parsefun_header(fun_name):
    code = cpp.indent_code(
        rf"""
        py::dict {fun_name}(
          std::istream& cont, ParsingOptions &parse_opts
        ) {{
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
    code = cpp.statement("return cpp_current_dict", cpp.INDENT)
    code += cpp.close_block()
    return code


def _register_reading_options():
    code = r"""
    py::class_<ParsingOptions>(m, "ParsingOptions")
      .def(py::init<>())
      .def_readwrite("ignore_number_mismatch", &ParsingOptions::ignore_number_mismatch)
      .def_readwrite("ignore_zero_mismatch", &ParsingOptions::ignore_zero_mismatch)
      .def_readwrite("ignore_varspec_mismatch", &ParsingOptions::ignore_varspec_mismatch)
      .def_readwrite("accept_spaces", &ParsingOptions::accept_spaces)
      .def_readwrite("ignore_send_records", &ParsingOptions::ignore_send_records)
      .def_readwrite("ignore_missing_tpid", &ParsingOptions::ignore_missing_tpid)
      .def_readwrite("validate_control_records", &ParsingOptions::validate_control_records);
    """
    return cpp.indent_code(code, -4)


def register_pybind_module(module_name, inner_code):
    code = cpp.line("") + cpp.line("")
    code += cpp.line(f"PYBIND11_MODULE({module_name}, m) {{")
    code += cpp.indent_code(_register_reading_options(), cpp.INDENT)
    code += cpp.indent_code(inner_code, cpp.INDENT)
    code += cpp.close_block()
    return code


def register_cpp_parsefuns(parsefuns, module_name, *extra_args):
    args_str = ", ".join(arg for arg in extra_args)
    args_str = ", " + args_str if args_str != "" else args_str
    code = ""
    for parsefun in parsefuns:
        curcode = cpp.statement(
            f'm.def("{parsefun}", &{parsefun}, "parsing function"{args_str})'
        )
        code += curcode
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
