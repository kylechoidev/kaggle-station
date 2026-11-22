#!/usr/bin/env python3
"""stream_summary.py - one-screen summary of Claude Code `--output-format stream-json --verbose` logs.

usage: python3 -I stream_summary.py <worker>_session.log [...]
Prints, per log: model, permission mode, number of assistant turns, tool calls by tool, background tasks,
the latest rate-limit status, whether a final `result` event arrived (and its subtype/turns/duration), and
non-JSON lines (crashes, `timeout` kills). It prints NO message text or tool output, so it is safe to run on
logs that contain private inputs and to paste its output somewhere.
"""
import collections
import json
import sys


def summarize(path):
    tools = collections.Counter()
    ev = collections.Counter()
    init, rate, result, bad = {}, {}, None, 0
    for line in open(path, errors='replace'):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            bad += 1
            continue
        t = d.get('type')
        ev['%s/%s' % (t, d.get('subtype') or '')] += 1
        if t == 'system' and d.get('subtype') == 'init':
            init = d
        elif t == 'assistant':
            for c in (d.get('message') or {}).get('content') or []:
                if isinstance(c, dict) and c.get('type') == 'tool_use':
                    tools[c.get('name')] += 1
        elif t == 'rate_limit_event':
            rate = d.get('rate_limit_info') or {}
        elif t == 'result':
            result = d
    print('==', path)
    print('  model %s  permissionMode %s  claude_code %s  apiKeySource %s' % (
        init.get('model'), init.get('permissionMode'), init.get('claude_code_version'), init.get('apiKeySource')))
    print('  assistant events %d  tool calls %d  %s' % (ev['assistant/'], sum(tools.values()),
                                                      ', '.join('%s %d' % kv for kv in tools.most_common())))
    print('  background tasks started %d, notifications %d' % (ev['system/task_started'], ev['system/task_notification']))
    if rate:
        print('  rate limit: %s, window %s, utilization %s' % (rate.get('status'), rate.get('rateLimitType'),
                                                             rate.get('utilization')))
    if result:
        print('  result: %s  turns %s  duration %.0f s  is_error %s' % (
            result.get('subtype'), result.get('num_turns'), (result.get('duration_ms') or 0) / 1000,
            result.get('is_error')))
    else:
        print('  result: none yet (still running, or killed by timeout)')
    if bad:
        print('  non-JSON lines: %d' % bad)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for p in sys.argv[1:]:
        summarize(p)
