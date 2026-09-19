"""Export the two review workflows (prompts, tool trails, structured replies)
into docs/reviews/2026-09-18/architecture-evaluation/ as readable Markdown plus the
raw journals. Re-runnable: picks up agents that finished since the last run."""
from __future__ import annotations
import json, os, re, shutil, sys
from pathlib import Path
from collections import defaultdict, Counter

SESS = Path('/Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14')
WF = {
    'review': SESS / 'subagents/workflows/wf_07270914-dd5',
    'panel': SESS / 'subagents/workflows/wf_160a1894-e1e',
}
SCRIPTS = {
    'review': SESS / 'workflows/scripts/simorgh-architecture-review-wf_07270914-dd5.js',
    'panel': SESS / 'workflows/scripts/simorgh-rearchitecture-panel-wf_160a1894-e1e.js',
}
OUT = Path('/Users/saeed/ws/Simorgh/docs/reviews/2026-09-18/architecture-evaluation')

def slug(s: str, n: int = 70) -> str:
    s = re.sub(r'[^A-Za-z0-9]+', '-', s).strip('-').lower()
    return s[:n].rstrip('-') or 'agent'

def load_journal(d: Path):
    started, results, order = {}, {}, []
    for line in (d / 'journal.jsonl').read_text().splitlines():
        try: j = json.loads(line)
        except Exception: continue
        aid = j.get('agentId') or j.get('id')
        if j.get('type') == 'started':
            started[aid] = {'label': j.get('label') or '', 'phase': j.get('phase') or ''}
            order.append(aid)
        elif j.get('type') == 'result':
            results[aid] = j.get('result')
    return started, results, order

def blocks(msg):
    c = msg.get('content')
    if isinstance(c, str): return [{'type': 'text', 'text': c}]
    return c or []

def parse_agent(d: Path, aid: str):
    """Return (task_prompt, trail, final_text, structured, n_tool_calls)."""
    f = d / f'agent-{aid}.jsonl'
    if not f.exists(): return None
    user_texts, trail, final_text, structured = [], [], '', None
    pending = {}
    for line in f.read_text().splitlines():
        try: j = json.loads(line)
        except Exception: continue
        m = j.get('message') or {}
        role = m.get('role') or j.get('type')
        for b in blocks(m):
            t = b.get('type')
            if role == 'user' and t == 'text' and len(user_texts) < 2:
                user_texts.append(b.get('text', ''))
            elif role == 'assistant' and t == 'tool_use':
                name = b.get('name', ''); inp = b.get('input') or {}
                if name == 'StructuredOutput':
                    structured = inp
                    continue
                if name == 'Bash':
                    short = (inp.get('description') or inp.get('command') or '')[:140]
                elif name in ('Read',):
                    short = str(inp.get('file_path', ''))
                    if inp.get('offset'): short += f" (from line {inp['offset']})"
                elif name in ('Grep',):
                    short = f"{inp.get('pattern','')!r} in {inp.get('path') or '.'}"
                elif name == 'Glob':
                    short = str(inp.get('pattern', ''))
                else:
                    short = json.dumps(inp)[:140]
                pending[b.get('id')] = len(trail)
                trail.append({'tool': name, 'what': short, 'result': ''})
            elif role == 'user' and t == 'tool_result':
                i = pending.get(b.get('tool_use_id'))
                if i is not None:
                    rc = b.get('content')
                    if isinstance(rc, list):
                        rc = ' '.join(x.get('text', '') for x in rc if isinstance(x, dict))
                    rc = str(rc or '')
                    trail[i]['result'] = re.sub(r'\s+', ' ', rc)[:160]
            elif role == 'assistant' and t == 'text':
                if b.get('text', '').strip(): final_text = b['text']
    # the task prompt is the second user text (the first is the harness relay of the user's request)
    task = user_texts[1] if len(user_texts) > 1 else (user_texts[0] if user_texts else '')
    task = re.sub(r'^\[Workflow harness[^\n]*\n', '', task)
    return task, trail, final_text, structured, len(trail)

def md_json(obj, depth=0) -> str:
    """Render a structured result as readable Markdown rather than JSON."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            title = k.replace('_', ' ')
            if isinstance(v, (dict, list)) and v:
                out.append(f"{'#' * min(3 + depth, 6)} {title}\n")
                out.append(md_json(v, depth + 1))
            else:
                out.append(f"**{title}:** {v}\n")
    elif isinstance(obj, list):
        for i, v in enumerate(obj, 1):
            if isinstance(v, dict):
                head = v.get('title') or v.get('decision') or v.get('capability') or v.get('stage') or v.get('name') or v.get('key') or v.get('current') or f'item {i}'
                out.append(f"{'#' * min(4 + depth, 6)} {i}. {head}\n")
                for k, w in v.items():
                    if k in ('title',): continue
                    kk = k.replace('_', ' ')
                    if isinstance(w, list):
                        out.append(f"- **{kk}:**")
                        for x in w: out.append(f"  - {x}")
                    elif isinstance(w, dict):
                        out.append(f"- **{kk}:**"); out.append(md_json(w, depth + 2))
                    else:
                        out.append(f"- **{kk}:** {w}")
                out.append('')
            else:
                out.append(f"- {v}")
    else:
        out.append(str(obj))
    return '\n'.join(out) + '\n'

def write_agent(path: Path, wf: str, aid: str, meta: dict, parsed, result):
    task, trail, final_text, structured, n = parsed if parsed else ('', [], '', None, 0)
    lines = [f"# {meta['label'] or aid}", '',
             f"*Workflow: {wf} · Phase: {meta['phase'] or '?'} · Agent id: `{aid}` · Tool calls: {n}*", '',
             '## Task given to the agent', '', '```text', task.strip(), '```', '']
    if trail:
        lines += ['## What the agent did (tool trail)', '', '| # | Tool | What | Result (first 160 chars) |', '|---|---|---|---|']
        for i, t in enumerate(trail, 1):
            w = t['what'].replace('|', '\\|').replace('\n', ' ')
            r = t['result'].replace('|', '\\|')
            lines.append(f"| {i} | {t['tool']} | {w} | {r} |")
        lines.append('')
    res = result if result is not None else structured
    lines += ['## Structured reply', '']
    if res is None:
        lines.append('_No result recorded (agent still running, skipped, or failed)._')
    elif isinstance(res, str):
        lines += ['```text', res, '```']
    else:
        lines.append(md_json(res))
    if final_text and (res is None or isinstance(res, str)):
        lines += ['', '## Final text', '', final_text]
    path.write_text('\n'.join(lines))

def main():
    OUT.mkdir(exist_ok=True)
    (OUT / 'raw').mkdir(exist_ok=True)
    (OUT / 'scripts').mkdir(exist_ok=True)
    index = ['# Deep-dive archive: Simorgh architecture evaluation, 2026-09-18', '',
             'This folder preserves the multi-agent investigation behind',
             '[`../architecture-evaluation.md`](../architecture-evaluation.md).',
             'Generated by Claude Code using Claude Fable 5.1. For every agent it holds the exact task it was',
             'given, the trail of files it read and commands it ran (with the first 160 characters of each result),',
             'and its full structured reply. Nothing here was edited; the report was written from this material.', '',
             'Start with [`APPROACH.md`](APPROACH.md): why the investigation was shaped this way, what was verified by hand,',
             'what the adversarial pass changed, where the method is weak, and how to re-run or continue it.', '',
             '## Layout', '',
             '- `APPROACH.md` — the method and the operator manual for continuing this work.',
             '- `tools/export_deepdive.py` — regenerates this folder from the Claude Code session transcripts.',
             '- `scripts/` — the two workflow scripts exactly as run (the orchestration logic, prompts and schemas).',
             '- `review/readers/` — nine readers, one per architectural concern: task, trail, findings, strengths, measurements.',
             '- `review/refutations/` — two skeptics per finding (correctness lens, proportionality lens), grouped by concern.',
             '- `review/critic.md` — the completeness critic.',
             '- `panel/proposals/` — four independent re-architecture proposals (harness, cognitive, systems, embodied).',
             '- `panel/judges/` — three judges scoring all four and resolving their disagreements.',
             '- `panel/synthesis.md` — the synthesised target architecture Part II of the report is built from.',
             '- `raw/` — the workflow journals (`*.journal.jsonl`: one `result` line per agent with its verbatim structured reply)',
             '  and a manifest of every agent. The full per-agent tool transcripts (about 76 MB of JSONL) are not committed;',
             '  they remain in the Claude Code session directory named in `raw/manifest.json`.', '']
    manifest = {'session_dir': str(SESS), 'workflows': {}}
    for wf, d in WF.items():
        started, results, order = load_journal(d)
        shutil.copy(d / 'journal.jsonl', OUT / 'raw' / f'{wf}.journal.jsonl')
        shutil.copy(SCRIPTS[wf], OUT / 'scripts' / SCRIPTS[wf].name)
        counts = Counter()
        entries = []
        for aid in order:
            meta = started[aid]; label = meta['label']
            parsed = parse_agent(d, aid)
            res = results.get(aid)
            # destination
            if wf == 'review':
                if label.startswith('read:'):
                    sub = OUT / 'review' / 'readers'; name = slug(label[5:]) + '.md'
                elif label.startswith('refute:'):
                    _, lens, title = label.split(':', 2)
                    concern = _concern_for(title)
                    sub = OUT / 'review' / 'refutations' / concern; name = slug(title) + f'.{lens}.md'
                elif label == 'completeness-critic':
                    sub = OUT / 'review'; name = 'critic.md'
                else:
                    sub = OUT / 'review' / 'other'; name = slug(label) + '.md'
            else:
                if label.startswith('propose:'):
                    sub = OUT / 'panel' / 'proposals'; name = slug(label[8:]) + '.md'
                elif label.startswith('judge:'):
                    sub = OUT / 'panel' / 'judges'; name = 'judge-' + slug(label[6:]) + '.md'
                elif label == 'synthesis':
                    sub = OUT / 'panel'; name = 'synthesis.md'
                else:
                    sub = OUT / 'panel' / 'other'; name = slug(label) + '.md'
            sub.mkdir(parents=True, exist_ok=True)
            write_agent(sub / name, wf, aid, meta, parsed, res)
            counts['done' if res is not None else 'pending'] += 1
            entries.append({'agentId': aid, 'label': label, 'phase': meta['phase'],
                            'tool_calls': parsed[4] if parsed else 0, 'has_result': res is not None,
                            'file': str((sub / name).relative_to(OUT)),
                            'transcript': f'agent-{aid}.jsonl'})
        manifest['workflows'][wf] = {'dir': str(d), 'script': SCRIPTS[wf].name, 'agents': entries,
                                     'done': counts['done'], 'pending': counts['pending']}
        index += [f"## Workflow `{wf}`: {len(order)} agents ({counts['done']} with results, {counts['pending']} without)", '',
                  f"Script: [`scripts/{SCRIPTS[wf].name}`](scripts/{SCRIPTS[wf].name}). Journal: [`raw/{wf}.journal.jsonl`](raw/{wf}.journal.jsonl).", '',
                  '| Phase | Agent | Tool calls | Result | File |', '|---|---|---|---|---|']
        for e in entries:
            index.append(f"| {e['phase']} | {e['label']} | {e['tool_calls']} | {'yes' if e['has_result'] else 'no'} | [{e['file']}]({e['file']}) |")
        index.append('')
    (OUT / 'raw' / 'manifest.json').write_text(json.dumps(manifest, indent=1))
    (OUT / 'README.md').write_text('\n'.join(index))
    total = sum(f.stat().st_size for f in OUT.rglob('*') if f.is_file())
    print(f"wrote {sum(1 for _ in OUT.rglob('*.md'))} markdown files, {total/1e6:.1f} MB total under {OUT}")
    for wf, w in manifest['workflows'].items(): print(wf, 'done', w['done'], 'pending', w['pending'])

# map a finding title to the reader concern via the reader results
_TITLE2CONCERN = None
def _concern_for(title: str) -> str:
    global _TITLE2CONCERN
    if _TITLE2CONCERN is None:
        _TITLE2CONCERN = {}
        started, results, order = load_journal(WF['review'])
        for aid in order:
            lab = started[aid]['label']
            if lab.startswith('read:') and isinstance(results.get(aid), dict):
                for f in results[aid].get('findings', []):
                    _TITLE2CONCERN[(f.get('title') or '').strip()] = lab[5:]
    t = title.strip()
    if t in _TITLE2CONCERN: return _TITLE2CONCERN[t]
    # the label carried only the first 40 characters of the title
    for full, concern in _TITLE2CONCERN.items():
        if full[:40].strip() == t or full.startswith(t): return concern
    return 'unassigned'

if __name__ == '__main__':
    main()
