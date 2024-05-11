############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2024/03/28
# Last modified:   2024/05/11
# License:         MIT
# Copyright (c) 2024 International Atomic Energy Agency (IAEA)
#
############################################################

from .expr_utils.equation_utils import get_variables_in_expr
from . import cpp_primitives as cpp
from .cpp_types.cpp_varops_query import did_read_var
from .cpp_types.cpp_varaux import check_variable, get_cpp_varname
from .lookahead_management import in_lookahead


def define_current_template(template):
    tmpl = template.replace("\n", r"\n")
    code = cpp.statement(f'cpp_template = "{tmpl}"')
    return code


def get_current_template():
    return "cpp_template"


def read_raw_line():
    code = cpp.statement("cpp_line = cpp_read_raw_line(cont)")
    return code


def read_send(mat, mf, parse_opts):
    code = cpp.statement(f"cpp_read_send(cont, {mat}, {mf}, {parse_opts})")
    return code


def is_fend(parse_opts):
    return f"cpp_is_fend_record(cpp_line, {parse_opts})"
    return code


def is_mend(parse_opts):
    return f"cpp_is_mend_record(cpp_line, {parse_opts})"


def is_tend(parse_opts):
    return f"cpp_is_tend_record(cpp_line, {parse_opts})"


def is_blank_line():
    return "cpp_is_blank_line(cpp_line)"


def read_line(mat, mf, mt, parse_opts):
    code = cpp.statement(
        f"cpp_line = cpp_read_line(cont, {mat}, {mf}, {mt}, {parse_opts})"
    )
    return code


def read_line_la(mat, mf, mt, parse_opts, vardict):
    if in_lookahead(vardict):
        return read_raw_line()
    else:
        return read_line(mat, mf, mt, parse_opts)


def get_mat_number():
    code = "cpp_read_mat_number(cpp_line.c_str())"
    return code


def get_mf_number():
    code = "cpp_read_mf_number(cpp_line.c_str())"
    return code


def get_mt_number():
    code = "cpp_read_mt_number(cpp_line.c_str())"
    return code


def get_int_field(idx, parse_opts):
    code = f"cpp_read_field<int>(cpp_line.c_str(), {idx}, {parse_opts})"
    return code


def get_custom_int_field(start_pos, length):
    code = f"cpp_read_custom_int_field(cpp_line.c_str(), {start_pos}, {length})"
    return code


def get_int_vec(numel, parse_opts):
    code = cpp.statement("cpp_read_vec<int>(cont, {numel}, {parse_opts})")
    return code


def get_float_vec(nume, parse_opts):
    code = cpp.statement(f"cpp_read_vec<double>(cont, {numel}, {parse_opts})")
    return code


def get_numeric_field(fieldpos, dtype, parse_opts):
    dtypestr = {float: "double", int: "int"}[dtype]
    code = f"cpp_read_field<{dtypestr}>(cpp_line.c_str(), {fieldpos}, {parse_opts})"
    return code


def get_text_field(start, length):
    code = f"cpp_line.substr({start}, {length})"
    return code


def _map_bool(boolexpr):
    return "true" if boolexpr else "false"


def validate_field(
    expected_value,
    actual_value,
    contains_variable,
    contains_desired_number,
    contains_inconsistent_varspec,
    exprstr,
    line_template,
    parse_opts,
):
    cont_var = _map_bool(contains_variable)
    cont_des_num = _map_bool(contains_desired_number)
    cont_incons_var = _map_bool(contains_inconsistent_varspec)
    code = cpp.statement(
        f"cpp_validate_field({expected_value}, {actual_value}, "
        + f" {cont_var}, {cont_des_num}, {cont_incons_var}, "
        + f"{exprstr},"
        + ("\n" + " " * cpp.INDENT if line_template else " ")
        + f"{line_template}, cpp_line, {parse_opts})"
    )
    return code


def get_tab1_body(xvar, yvar, nr, np, mat, mf, mt, parse_opts):
    code = cpp.statement(
        f"read_tab1_body(cont, {nr}, {np}, {mat}, {mf}, {mt}, {parse_opts})"
    )
    return code


def get_tab2_body(nr, mat, mf, mt, parse_opts):
    code = cpp.statement(f"read_tab2_body(cont, {nr}, {mat}, {mf}, {mt}, {parse_opts})")
    return code


def open_section(vartok, vardict):
    check_variable(vartok, vardict)
    secname = vartok
    indices = vartok.indices
    code = cpp.indent_code(
        f"""
    {{
        py::dict cpp_parent_dict = cpp_current_dict;
        if (! cpp_parent_dict.contains("{secname}")) {{
          cpp_parent_dict["{secname}"] = py::dict();
        }}
        py::dict cpp_current_dict = cpp_parent_dict["{secname}"];
        """,
        -4,
    )
    for idx in indices:
        cpp_idxstr = get_cpp_varname(idx, vardict)
        idxstr = f"py::cast({cpp_idxstr})"
        code += cpp.indent_code(
            f"""
        if (! cpp_current_dict.contains({idxstr})) {{
          cpp_current_dict[{idxstr}] = py::dict();
        }}
        cpp_current_dict = cpp_current_dict[{idxstr}];
        """,
            -4,
        )
    return code


def close_section():
    code = cpp.statement("cpp_current_dict = cpp_parent_dict", cpp.INDENT)
    code += cpp.close_block()
    return code


def did_not_read_var(vartok, vardict, indices=None):
    return "(! " + did_read_var(vartok, vardict, indices) + ")"


def any_unread_vars(vartoks, vardict, glob=False):
    if glob:
        return cpp.logical_or(did_not_read_var(v, vardict) for v in vartoks)
    else:
        return cpp.logical_or(did_not_read_var(v, vardict, v.indices) for v in vartoks)


def did_encounter_var(vartok, vardict):
    while vartok not in vardict and "__up" in vardict:
        vardict = vardict["__up"]
    return vartok in vardict


def count_not_encountered_vars(node, vardict):
    varset = get_variables_in_expr(node)
    return sum(not did_encounter_var(v, vardict) for v in varset)


def should_parse_section(mf, mt, exclude, include):
    return f"should_parse_section({mf}, {mt}, {exclude}, {include})"


def should_not_parse_section(mf, mt, exclude, include):
    return cpp.logical_not(should_parse_section(mf, mt, exclude, include))


def read_section_verbatim(tarvec, mat, mf, mt, cont, is_firstline, parse_opts):
    code = cpp.statement(
        f"{tarvec} = read_section_verbatim({mat}, {mf}, {mt}, {cont}, "
        + "{is_firstline}, {parse_opts})"
    )
    return code


class ListBodyRecorder:

    @staticmethod
    def start_list_body_loop(mat, mf, mt, parse_opts):
        code = cpp.open_block()
        cpp_npl_val = get_int_field(4, parse_opts)
        code += cpp.statement(f"int cpp_npl = {cpp_npl_val}", cpp.INDENT)
        code += cpp.statement("int cpp_i = 0", cpp.INDENT)
        code += cpp.statement("int cpp_j = 0", cpp.INDENT)
        read_line_call = read_line(mat, mf, mt, parse_opts)
        code += cpp.statement(f"std::string line = {read_line_call}", cpp.INDENT)
        return code

    @staticmethod
    def finish_list_body_loop():
        code = cpp.indent_code(
            cpp.pureif(
                "cpp_i != cpp_npl",
                cpp.statement(
                    'throw std::runtime_error("not exactly NPL elements consumed")'
                ),
            ),
            4,
        )
        code += cpp.close_block()
        return cpp.close_block()

    @staticmethod
    def get_element(parse_opts):
        return f"cpp_read_field<double>(line.c_str(), cpp_j, {parse_opts})"

    @staticmethod
    def update_counters_and_line(mat, mf, mt, parse_opts):
        code = cpp.statement("cpp_i++")
        code += cpp.statement("cpp_j++")
        read_line_call = read_line(mat, mf, mt, parse_opts)
        code += cpp.pureif(
            cpp.logical_and(["cpp_j > 5", "cpp_i < cpp_npl"]),
            cpp.concat(
                [
                    cpp.statement(f"line = {read_line_call}"),
                    cpp.statement("cpp_j = 0"),
                ]
            ),
        )
        return code

    @staticmethod
    def indent(code):
        return cpp.indent_code(code, cpp.INDENT)
