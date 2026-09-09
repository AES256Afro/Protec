"""Bounded, self-reported delivery capabilities, separate from operator authority."""
import re

UNREPORTED=object()
# Every executable kind must be explicitly admitted here. Advertising cannot add handlers.
LEGACY_INVENTORY=frozenset({('refresh_inventory',0),('refresh_inventory',1)})
SUPPORTED=LEGACY_INVENTORY | frozenset({('preview_packages',1)})


def inventory_offer(apt_previews=False):
    jobs=[{'kind':'refresh_inventory','versions':[1]}]
    if apt_previews:jobs.append({'kind':'preview_packages','versions':[1]})
    return {'version':1,'jobs':jobs}


def parse_offer(value):
    if (not isinstance(value,dict) or set(value)!={'version','jobs'} or
            type(value['version']) is not int or value['version']!=1 or
            not isinstance(value['jobs'],list) or len(value['jobs'])>32):
        raise ValueError('Invalid job capability report')
    contracts=set()
    kinds=set()
    for entry in value['jobs']:
        if (not isinstance(entry,dict) or set(entry)!={'kind','versions'} or
                not isinstance(entry['kind'],str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',entry['kind']) or
                entry['kind'] in kinds or not isinstance(entry['versions'],list) or
                not 1<=len(entry['versions'])<=8):
            raise ValueError('Invalid job capability entry')
        kinds.add(entry['kind'])
        for version in entry['versions']:
            if type(version) is not int or not 0<=version<=65535 or (entry['kind'],version) in contracts:
                raise ValueError('Invalid or duplicate capability contract version')
            contracts.add((entry['kind'],version))
    return frozenset(contracts)


def admitted(value,protocol):
    # Omission preserves only the existing read-only compatibility path.
    offered=LEGACY_INVENTORY if value is UNREPORTED else parse_offer(value)
    return frozenset(contract for contract in SUPPORTED & offered if contract[1]==protocol)


def validate_delivery(jobs,offer,admission):
    """Agent defense even if a server ignores its report or returns an unsafe contract."""
    if admission is not UNREPORTED and (type(admission) is not int or admission!=1):
        raise ValueError('Unsupported capability admission response')
    offered=parse_offer(offer)
    for job in jobs:
        contract=(job['kind'],job.get('version',0))
        if contract in offered and contract in SUPPORTED:
            continue
        if admission is UNREPORTED and contract==('refresh_inventory',0):
            continue
        raise ValueError('Delivered job was not advertised by this agent')
