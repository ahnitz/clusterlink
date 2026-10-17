"""Decode HTCondor's two environment encodings without shell evaluation."""
import re


def values(ad):
    # GridManager gives REMOTE_* environment attributes precedence as a group.
    remote = any(name in ad for name in ('REMOTE_Environment', 'REMOTE_Env', 'REMOTE_EnvDelim'))
    prefix = 'REMOTE_' if remote else ''
    def read(name, default=None):
        if name not in ad:
            return default
        return ad.eval(name) if hasattr(ad, 'eval') else ad[name]
    encoded = read(prefix + 'Environment')
    if prefix + 'Environment' in ad and not isinstance(encoded, str):
        raise ValueError('Job Environment must evaluate to a string before routing')
    entries = []
    if isinstance(encoded, str):
        token, quoted, i = '', False, 0
        while i < len(encoded):
            char = encoded[i]
            if char == "'":
                if quoted and i + 1 < len(encoded) and encoded[i + 1] == "'":
                    token += "'"
                    i += 2
                    continue
                quoted = not quoted
            elif char in ' \t\r\n' and not quoted:
                if token:
                    entries.append(token)
                    token = ''
            else:
                token += char
            i += 1
        if quoted:
            raise ValueError('Unterminated quote in job Environment')
        if token:
            entries.append(token)
    else:
        encoded = read(prefix + 'Env', '')
        delimiter = read(prefix + 'EnvDelim', ';')
        if isinstance(encoded, str) and encoded:
            if not isinstance(delimiter, str) or len(delimiter) != 1:
                raise ValueError('Invalid job EnvDelim')
            entries = encoded.split(delimiter)
    result = {}
    for entry in entries:
        if not entry:
            continue
        name, sep, value = entry.partition('=')
        if name.startswith('BASH_FUNC_'):
            continue
        if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) or '\x00' in value:
            raise ValueError('Unsupported job environment entry')
        result[name] = value
    return result
