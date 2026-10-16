#!/usr/bin/env python3
"""Check completion and basic scientific-output integrity for the mini search."""
import argparse
import json
from pathlib import Path
import re

import h5py
import numpy as np


def one(root, pattern):
    matches = list(root.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f'Expected one {pattern} under {root}, found {len(matches)}')
    return matches[0]


def validate(root, allow_incomplete=False, require_unattended=False):
    log = root / 'submitdir/work/gw.dax-0.dag.dagman.out'
    exits = re.findall(r'EXITING WITH STATUS (\d+)', log.read_text())
    complete = bool(exits and exits[-1] == '0')
    if not complete and not allow_incomplete:
        raise ValueError('Root DAG has not completed successfully')
    report = {'workflow_complete': complete, 'triggers': []}
    if require_unattended:
        if not complete:
            raise ValueError('Unattended acceptance requires a completed workflow')
        metrics = sorted({p.resolve() for p in root.rglob('*.dag.metrics')})
        if not metrics:
            raise ValueError('No DAGMan completion metrics found')
        report['dags'] = []
        for path in metrics:
            data = json.loads(path.read_text())
            if data['exitcode'] != 0 or data['DagStatus'] != 0:
                raise ValueError('A child DAG did not succeed: ' + str(path))
            if data['rescue_dag_number'] != 0:
                raise ValueError('Rescue restart found: ' + str(path))
            report['dags'].append({'name': path.name, 'nodes': data['total_nodes'],
                'jobs_failed': data['jobs_failed'], 'rescue_dag_number': data['rescue_dag_number']})
        report['no_rescue_restarts'] = True
    with h5py.File(one(root / 'bank', '*-BANK2HDF-*.hdf')) as bank:
        m1, m2 = bank['mass1'][:], bank['mass2'][:]
        if not (len(m1) == len(m2) > 0 and np.isfinite(m1).all()
                and np.isfinite(m2).all() and (m1 > 0).all() and (m2 > 0).all()):
            raise ValueError('Invalid template-bank masses')
        report['templates'] = len(m1)
    for category in ('full_data', 'BBH_coinc'):
        for ifo in ('H1', 'L1', 'V1'):
            path = one(root / category, ifo + '-HDF_TRIGGER_MERGE_*.hdf')
            with h5py.File(path) as data:
                snr = data[ifo]['snr'][:]
                if not (len(snr) and np.isfinite(snr).all() and (snr > 0).all()):
                    raise ValueError('Invalid trigger SNRs: ' + str(path))
                report['triggers'].append({'category': category, 'ifo': ifo,
                    'count': len(snr), 'max_snr': float(snr.max())})
    with h5py.File(one(root / 'inj_files', '*-OPTIMAL_SNR_MERGE_*.hdf')) as injections:
        report['injections'] = len(injections['mass1'])
        for ifo in ('H1', 'L1', 'V1'):
            snr = injections['optimal_snr_' + ifo][:]
            if not (len(snr) == report['injections'] > 0 and np.isfinite(snr).all()
                    and (snr >= 0).all() and (snr > 0).any()):
                raise ValueError('Invalid injection optimal SNRs for ' + ifo)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--allow-incomplete', action='store_true')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--require-unattended', action='store_true',
                        help='Also require every DAG metric to succeed with no rescue restart')
    args = parser.parse_args()
    result = validate(args.output, args.allow_incomplete, args.require_unattended)
    text = json.dumps(result, indent=2) + '\n'
    if args.report:
        args.report.write_text(text)
    print(text, end='')
