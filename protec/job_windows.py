"""One-shot UTC delivery windows for repeatable inventory reads."""
import time


def validate(value,now=None):
    if value is None:return None,None
    now=time.time() if now is None else now
    if (not isinstance(value,dict) or set(value)!={'start','end'} or
            type(value['start']) is not int or type(value['end']) is not int or
            not now<=value['start']<value['end']<=now+30*86400 or value['end']-value['start']>86400):
        raise ValueError('Use integer UTC start/end times: start now or later, end within 30 days, and a window no longer than 24 hours')
    return value['start'],value['end']
