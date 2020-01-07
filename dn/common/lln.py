import urllib.error
import urllib.parse
import urllib.request

import simplejson as json


class LLNFormatError(Exception):
    pass


_not_safe = '%|\r\n='
_safe_map = {}
for i, c in zip(list(range(256)), str(bytearray(list(range(256))))):
    _safe_map[c] = c if c not in _not_safe else '%{:02x}'.format(i)


def _encode_char(c):
    return _safe_map.get(c, c)


def _encode(s):
    if s is None:
        return 'None'
    elif isinstance(s, bool):
        return str(s)
    elif isinstance(s, (int, float)):
        return repr(s)
    elif isinstance(s, str):
        return ''.join(map(_encode_char, s))

    return s


def _decode(s):
    if not s:
        return s
    if s.startswith('$'):
        return json.loads(urllib.parse.unquote(s[1:]))
    index = s.find('=')
    if index != -1:
        return urllib.parse.unquote(
            s[0:index]), \
            urllib.parse.unquote(s[index + 1:])

    return urllib.parse.unquote(s)


def to_bytes(s, encoding='utf-8', errors='strict'):
    if isinstance(s, str):
        s = bytes(s, encoding)
    return s


def to_str(s, decoding='utf-8'):
    if isinstance(s, bytes):
        s = s.decode(decoding)
    else:
        raise LLNFormatError('bytes input required.')
    return s


def escape_string(data):
    _escape_map = {
        '\r': '\\r',
        '\n': '\\n',
    }
    escaped = data
    for k, v in list(_escape_map.items()):
        escaped = escaped.replace(k, v)
    return escaped


# 这个逻辑应该不用if else 了 since python3 unified str and unicode
def translate_left(left):
    filtered = '\r\n\t =!@#$:;,+-()[]~`'
    # if isinstance(left, str):
    #     left = left.translate(None, filtered)
    # elif isinstance(left, str):
    #     left = left.translate({ord(i): None for i in filtered})
    if isinstance(left, str):
        left = left.translate({ord(i): None for i in filtered})
    return left


def dump_string(data):
    if not data:
        return str(data).encode("utf8")
    data = to_bytes(escape_string(data))
    if b'|' in data or b'=' in data or data[0] == b'$'[0]:
        return b'$%d$ %s' % (len(data), data)
    else:
        return data


def dump_binop(left, right):
    left = translate_left(to_bytes('%s' % (left)))

    if isinstance(right, (list, dict)):
        try:
            right = json.dumps(right)
        except Exception:
            right = '%s' % right
    right = to_bytes(escape_string('%s' % right))

    if b'|' in left or b'=' in left or b'|' in right or left[0] == b'$'[0]:
        return b'$%d,%d$ %s=%s' % (len(left), len(right), left, right)
    else:
        return b'%s=%s' % (left, right)


def dump_dict(data):
    try:
        d = json.dumps(data)
        if '|' in d or d[0] == '$':
            return b'$$%d$ %s' % (len(d), to_bytes(d))
        else:
            return b'$%s' % (to_bytes(d))
    except Exception:
        return dump_string(repr(data))


def dump_object(data):
    return dump_string(repr(data))


def dumps2(msgs):
    s = []
    for msg in msgs:
        if msg is None:
            s.append(b'None')
        elif isinstance(msg, bool):
            s.append(to_bytes(str(msg)))
        elif isinstance(msg, (int, float)):
            s.append(to_bytes(repr(msg)))
        elif isinstance(msg, str):
            s.append(dump_string(msg))
        elif isinstance(msg, tuple):
            if len(msg) == 2:
                s.append(dump_binop(msg[0], msg[1]))
            else:
                s.append(dump_string(repr(msg)))
        elif isinstance(msg, (list, dict)):
            s.append(dump_dict(msg))
        else:
            s.append(dump_object(msg))
    return b'|'.join(s)


def string_list_to_bytes(str_lst):
    # make sure every item in str_lst is of type bytes, modified in place.
    for i in range(len(str_lst)):
        if isinstance(str_lst[i], str):
            str_lst[i] = to_bytes(str_lst[i])


def load_meta(s, i):
    m1 = s[i + 1:i + 2]
    if m1 == b'{' or m1 == b'[':
        return s[i:i + 1]
    elif m1 == b'$' or m1 in b'0123456789':
        j = s.find(b'$ ', i + 1)
        if j == -1:
            raise LLNFormatError(
                'meta <%s> info not completed. <:> not found' % (s[i:]))
        else:
            return s[i:j + 2]
    else:
        raise LLNFormatError('meta <%s> is invalid' % (s[i:]))


def load_data_withmeta(s, i, meta):
    meta = meta.rstrip()
    if meta == b'$':
        string = load_string(s, i)
        return json.loads(to_str(string)), len(string)
    exp = meta[1:-1].replace(b' ', b'')
    if not exp:
        raise LLNFormatError('meta <%s> is invalid' % (meta))
    if b',' in exp:
        pair = exp.split(b',')
        if len(pair) != 2:
            raise LLNFormatError(
                'meta <%s> only support one <,> now.' % (meta))
        llen, rlen = int(pair[0]), int(pair[1])
        left = s[i:i + llen]
        i += llen
        if s[i:i + 1] != b'=':
            raise LLNFormatError('LLN expect <=> but <%s> found.' % (s[i]))
        i += 1
        right = s[i:i + rlen]
        i += rlen
        return {to_str(left): to_str(right)}, llen + rlen + 1
    elif exp[0:1] == b'$':
        data_len = int(exp[1:])
        string = s[i:i + data_len]
        return json.loads(to_str(string)), len(string)
    else:
        data_len = int(exp)
        string = s[i:i + data_len]
        return to_str(string), len(string)


def load_string(s, i):
    j = s.find(b'|', i)
    if j == -1:
        return s[i:]
    return s[i:j]


def loads2(s):
    if isinstance(s, str):
        s = to_bytes(s)

    loaded = []
    check_separator = False
    i = 0
    while i < len(s):
        c = s[i]
        if check_separator:
            if c == b'|'[0]:
                i += 1
                check_separator = False
                continue
            else:
                raise LLNFormatError(
                    'separator | expected, but <%s> found.' % chr(c))
        if c == b'$'[0]:
            meta = load_meta(s, i)
            i += len(meta)
            data, length = load_data_withmeta(s, i, meta)
            loaded.append(data)
            i += length
        else:
            string = load_string(s, i)
            if b'=' in string:
                loaded.append(
                    dict((json_load_right(
                        to_str(string).split('=', 1)[0:2]), )))
            else:
                loaded.append(to_str(string))
            i += len(string)
        check_separator = True
    return loaded


def json_load_right(lst):
    if not isinstance(lst, list):
        raise LLNFormatError('in json_load_right function string required!')
    left = lst[0]
    right = lst[1]
    try:
        right = str(json.loads(right))
    except Exception:
        right = '%s' % right

    return [left] + [right]


loads = loads2
dumps = dumps2
