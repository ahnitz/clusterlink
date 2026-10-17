"""Select native REMOTE_* attributes for one enrolled destination."""
import re
import classad2

ENVIRONMENT = ('environment', 'env', 'envdelim')
# These describe Clusterlink's transport and wrapper, rather than the payload.
MANAGED = {'cmd', 'iwd', 'gridresource', 'jobuniverse', 'transferinput',
           'transferoutput', 'transferoutputremaps', 'transferexecutable',
           'shouldtransferfiles', 'whentotransferoutput'}


def select(ad, site_name, site_names):
    result = classad2.ClassAd(str(ad))
    specific = {}
    names = sorted(set(site_names), key=len, reverse=True)
    for key in list(result):
        if not key.lower().startswith('remote_'):
            continue
        for name in names:
            suffix = '_' + name
            if key.lower().endswith(suffix.lower()):
                if name.lower() == (site_name or '').lower():
                    specific[key[:-len(suffix)]] = result.lookup(key)
                del result[key]
                break
    for group in (ENVIRONMENT, ('args', 'arguments')):
        if any(k.lower()[7:] in group for k in specific):
            for field in group:
                key = 'REMOTE_' + field
                if key in result:
                    del result[key]
    for key, expression in specific.items():
        result[key] = expression
    for key in result:
        if key.lower().startswith('remote_'):
            field = key[7:]
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', field):
                raise ValueError('Invalid remote ClassAd attribute name: ' + key)
            if field.lower() in MANAGED:
                raise ValueError(key + ' overrides Clusterlink-managed staging or execution; use ordinary payload submit settings')
    return result


def expression(ad, name):
    return str(ad.lookup(name)).replace('\n', ' ').replace('\r', ' ')


def condor_lines(ad):
    """The batch Condor adapter does not forward arbitrary attributes itself."""
    handled = {*ENVIRONMENT, 'requirements', 'rank', 'batchextrasubmitargs',
               'requestdisk', 'requestcpus', 'requestmemory', 'requestgpus'}
    lines = []
    for key in ad:
        if key.lower().startswith('remote_') and key[7:].lower() not in handled:
            lines.append('+' + key[7:] + ' = ' + expression(ad, key))
    return ''.join(line + '\n' for line in lines)
