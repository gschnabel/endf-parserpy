############################################################
#
# Author(s):       Georg Schnabel
# Email:           g.schnabel@iaea.org
# Creation date:   2022/05/30
# License:         MIT
# Copyright (c) 2022 International Atomic Energy Agency (IAEA)
#
############################################################

from collections.abc import MutableMapping, Sequence


def locate(dic, varname, as_string=False):
    path = []
    locations = []

    def recfun(dic):
        nonlocal path
        nonlocal locations
        if varname in dic:
            path.append(varname)
            locations.append(tuple(path))
            del path[-1]
            return
        else:
            for key, item in dic.items():
                if isinstance(item, dict):
                    path.append(key)
                    recfun(item)
                    del path[-1]
        return
    recfun(dic)
    if as_string:
        locations = ['/'.join(str(s) for s in loc) for loc in locations]
    return tuple(locations)


def get_endf_values(dic, locations):
    values = []
    for loc in locations:
        curdic = dic
        for locpart in loc[:-1]:
            curdic = curdic[locpart]
        values.append(curdic[loc[-1]])
    return tuple(values)


def list_unparsed_sections(dic):
    unparsed = []
    for mf, mfsec in dic.items():
        for mt, mtsec in mfsec.items():
            if isinstance(mtsec, list):
                unparsed.append((mf,mt))
    return tuple(unparsed)


def list_parsed_sections(dic):
    parsed = []
    for mf, mfsec in dic.items():
        for mt, mtsec in mfsec.items():
            if isinstance(mtsec, dict):
                parsed.append((mf, mt))
    return tuple(parsed)


def sanitize_fieldname_types(dic):
    if not isinstance(dic, dict):
        raise TypeError('please provide dictionary')
    keys = tuple(dic.keys())
    for key in keys:
        try:
            intkey = int(key)
        except Exception:
            intkey = None
        if intkey is not None:
            if intkey in dic:
                raise IndexError('integer version of key already exists, something wrong')
            cont = dic[key]
            dic[intkey] = cont
            del dic[key]
    # recurse into sub-dictionaries
    keys = tuple(dic.keys())
    for key in keys:
        if isinstance(dic[key], dict):
            sanitize_fieldname_types(dic[key])


def path_to_list(path):
    if not isinstance(path, str):
        return path
    path_parts = path.split('/')
    path_parts = [cur for cur in path_parts if cur != '']
    path_parts = [int(cur) if cur.isdigit() else cur for cur in path_parts]
    ret = []
    for el in path_parts:
        if isinstance(el, str) and '[' in el:
            if not el.endswith(']'):
                raise ValueError('missing closing bracket')
            start = el.index('[') + 1
            ret.append(el[:start-1])
            indices_str = el[start:-1].split(',')
            indices = [int(x) for x in indices_str]
            ret.extend(indices)
        else:
            ret.append(el)
    return ret


def list_to_path(path):
    return '/'.join([str(x) for x in path])


def enter_section(endf_dic, path, create_missing=False, trunc=0):
    curdic = endf_dic
    path_parts = path_to_list(path)
    if trunc > 0:
        path_parts = path_parts[:-trunc]
    for cur in path_parts:
        if cur not in curdic and create_missing:
            curdic[cur] = dict()
        curdic = curdic[cur]
    return curdic


def show_content(endf_dic, maxlevel=0, prefix='/'):
    maxlen = max(len(prefix+str(s)) for s in endf_dic.keys())
    for k, v in endf_dic.items():
        if isinstance(v, dict):
            if maxlevel > 0:
                show_content(v, maxlevel-1,
                             prefix=prefix+str(k)+'/')
            else:
                fp = (prefix + str(k) + ':').ljust(maxlen+2)
                print(fp + 'subsection or array')
        else:
            fp = (prefix + str(k) + ':').ljust(maxlen+2)
            print(fp + str(v))


class EndfPath(Sequence):

    def __init__(self, pathspec):
        if isinstance(pathspec, int):
            pathspec = str(pathspec)
        if isinstance(pathspec, str):
            pathspec = pathspec.split('/')
        if not isinstance(pathspec, Sequence):
            raise TypeError('expected pathspec to be sequence or string')
        self._path_elements = self._standardize_path_tuple(pathspec)

    def _standardize_path_tuple(self, path_tuple):
        p = path_tuple
        p = (str(x) for x in p)
        p = (x.strip() for x in p)
        p = (x for x in p if x != '')
        res = tuple()
        for t in p:
            res = res + self._expand_array_notation(t)
        res = tuple(int(x) if x.isdigit() else x for x in res)
        self._validate_path(res)
        return res

    def _expand_array_notation(self, extvarname):
        t = extvarname
        if '[' not in t:
            return (extvarname,)
        if not t.endswith(']'):
            raise ValueError(f'invalid path element `{t}`')
        idx = t.index('[')
        varname = t[:idx]
        indices = t[idx+1:-1].split(',')
        indices = tuple(s.strip() for s in indices)
        return (varname,) + indices

    def _validate_path(self, path_elements):
        for el in path_elements:
            if not isinstance(el, int):
                if not el.replace('_', '').isalnum() or el[0].isdigit():
                    raise ValueError(f'invalid path element `{el}`')

    def __str__(self):
        return '/'.join([str(x) for x in self._path_elements])

    def __repr__(self):
        return f"EndfPath('{str(self)}')"

    def __getitem__(self, key):
        return EndfPath(self._path_elements[key])

    def __len__(self, *args, **kwargs):
        return len(self._path_elements)

    def __add__(self, other):
        if not isinstance(other, EndfPath):
            other = EndfPath(other)
        return EndfPath(self._path_elements + other._path_elements)

    def get(self, dict_like):
        cur = dict_like
        for el in self._path_elements:
            cur = cur[el]
        return cur

    def set(self, dict_like, value):
        cur = dict_like
        for el in self._path_elements[:-1]:
            cur = cur.setdefault(el, {})
        if isinstance(value, EndfDict):
            value = value.unwrap()
        cur[self._path_elements[-1]] = value

    def exists(self, dict_like):
        try:
            self.get(dict_like)
        except KeyError:
            return False
        except TypeError:
            return False
        return True

    def remove(self, dict_like):
        cur = dict_like
        for el in self._path_elements[:-1]:
            cur = cur[el]
        del cur[self._path_elements[-1]]


class EndfVariable:

    def __init__(self, endf_path, endf_dict, value=None):
        if isinstance(endf_dict, EndfDict):
            endf_dict = endf_dict.unwrap()
        if not isinstance(endf_path, EndfPath):
            endf_path = EndfPath(endf_path)
        if not endf_path.exists(endf_dict):
            if value is None:
                raise KeyError(f'variable `{endf_path}` does not exist')
            endf_path.set(endf_dict, value)

        self._endf_dict = endf_dict
        self._path = endf_path
        self._varname = endf_path[-1]
        self._parent = endf_path[:-1].get(endf_dict)

    def __repr__(self):
        return (f'EndfVariable({self._path!r}, ' +
                f'{type(self._endf_dict)} at {hex(id(self._endf_dict))}, ' +
                f'value={self.value})')

    def __call__(self):
        return self.value

    @property
    def name(self):
        return self._varname

    @property
    def value(self):
        return self._varname.get(self._parent)

    @value.setter
    def value(self, value):
        self._varname.set(self._parent, value)

    @property
    def path(self):
        return self._path

    @property
    def endf_dict(self):
        return self._endf_dict

    @property
    def parent_dict(self):
        return self._parent


class EndfDict(MutableMapping):

    def __init__(self, mapping=None):
        if mapping is None:
            self._store = dict()
        elif isinstance(mapping, MutableMapping):
            if isinstance(mapping, EndfDict):
                mapping = mapping.unwrap()
            self._store = mapping
        else:
            raise TypeError(
                'expected `mapping` to be an instance of MutableMapping'
            )
        self._root = self
        self._path = EndfPath('')

    def __repr__(self):
        return f'{self._store!r}'

    def __str__(self):
        return str(self._store)

    def __getitem__(self, key):
        endf_path = EndfPath(key)
        ret = endf_path.get(self._store)
        if isinstance(ret, MutableMapping) and not isinstance(ret, EndfDict):
            ret = EndfDict(ret)
            ret._root = self._root
            ret._path = endf_path
        return ret

    def __setitem__(self, key, value):
        if isinstance(value, EndfDict):
            value = value.unwrap()
        endf_path = EndfPath(key)
        endf_path.set(self._store, value)

    def __delitem__(self, key):
        if not isinstance(key, EndfPath):
            endf_path = EndfPath(key)
        endf_path.remove(self._store)

    def __iter__(self):
        return iter(self._store)

    def __len__(self):
        return len(self._store)

    def keys(self):
        return self._store.keys()

    def values(self):
        return self._store.values()

    def items(self):
        return self._store.items()

    def _recursive_unwrap(self, element):
        if isinstance(element, MutableMapping):
            if isinstance(element, EndfDict):
                element = element.unwrap()
            for curkey in element:
                element[curkey] = self._recursive_unwrap(element[curkey])
        return element

    def unwrap(self, recursive=False):
        if recursive:
            self._store = self._recursive_unwrap(self._store)
        return self._store

    @property
    def root(self):
        return self._root

    @property
    def path(self):
        return self._path
