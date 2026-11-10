"""Bounded read-only access to the user's complete offline Isaac Wiki snapshot.

The model supplies structured query fields only. It cannot choose scripts,
paths, editions, SQL, shell arguments, unlock files or trusted game context.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import json
import sqlite3
from pathlib import Path
import subprocess
import threading
import time

from .common import AdmissionError, Audit, canonical, digest, file_hash, inside, read_json


DATABASE_SHA256 = '60f86b199d7c0ae642dbf8969f1ffe8f0841d3e9540bc51bdf00cb16325aed4e'
SKILL_RELATIVE = 'knowledge/issac-wiki'
OPERATIONS = frozenset({'item', 'show', 'pool', 'unlock', 'synergy', 'spindown', 'boss'})
KINDS = frozenset({'item', 'trinket', 'card', 'pill', 'character', 'pool', 'entity',
                   'obstacle', 'floor', 'transformation', 'challenge', 'achievement', 'version'})
FIELDS = frozenset({'operation', 'query', 'kind', 'section', 'items', 'limit', 'steps', 'type', 'variant', 'subtype'})
SECTIONS = frozenset({'Effects', 'Interactions', 'Synergies', 'Notes', 'Generation',
                      'Unlock', 'Unlocks', 'Availability', 'Strategy', 'Item Pool',
                      'Item Pools', 'Mechanics', 'Behavior', 'Trivia', 'Bugs', 'History'})


def term(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 100:
        raise AdmissionError('WIKI_TERM_REQUIRED')
    value = value.strip()
    if value.startswith('-') or any(ord(c) < 32 for c in value) or '\x7f' in value:
        raise AdmissionError('INVALID_WIKI_TERM')
    return value


def arguments(query):
    if not isinstance(query, dict) or set(query) - FIELDS:
        raise AdmissionError('WIKI_STRUCTURED_FIELDS_ONLY')
    op = query.get('operation')
    if op not in OPERATIONS:
        raise AdmissionError('WIKI_OPERATION_NOT_ALLOWED')
    if op=='boss':
        if set(query)!={'operation','type','variant','subtype'} or any(type(query[k]) is not int or not 0<=query[k]<=100000 for k in ('type','variant','subtype')):
            raise AdmissionError('WIKI_BOSS_NATIVE_IDENTIFIERS_REQUIRED')
        return ['boss',str(query['type']),str(query['variant']),str(query['subtype'])]
    valid = {'operation', 'query'}
    if op in {'item', 'show', 'unlock'}:
        valid.add('kind')
    if op == 'show':
        valid.add('section')
    if op in {'pool', 'synergy'}:
        valid.add('limit')
    if op == 'synergy':
        valid = {'operation', 'items', 'limit'}
    if op == 'spindown':
        valid.add('steps')
    if set(query) - valid:
        raise AdmissionError('WIKI_FIELDS_NOT_VALID_FOR_OPERATION')
    if op == 'synergy':
        items = query.get('items')
        if not isinstance(items, list) or not 2 <= len(items) <= 4:
            raise AdmissionError('WIKI_SYNERGY_NEEDS_TWO_TO_FOUR_ITEMS')
        args = [op, *[term(x) for x in items]]
    else:
        args = [op, term(query.get('query'))]
    if 'kind' in query:
        if query['kind'] not in KINDS:
            raise AdmissionError('WIKI_KIND_NOT_ALLOWED')
        args += ['--kind', query['kind']]
    if 'section' in query:
        if query['section'] not in SECTIONS:
            raise AdmissionError('WIKI_SECTION_NOT_ALLOWED')
        args += ['--section', query['section']]
    if op in {'pool', 'synergy'}:
        limit = query.get('limit', 4)
        if type(limit) is not int or not 1 <= limit <= 8:
            raise AdmissionError('WIKI_RESULT_LIMIT_INVALID')
        args += ['--limit', str(limit)]
    if op == 'spindown':
        steps = query.get('steps', 1)
        if type(steps) is not int or not 1 <= steps <= 3:
            raise AdmissionError('WIKI_SPINDOWN_STEPS_INVALID')
        args += ['--steps', str(steps), '--mode', 'normal']
    if op in {'item', 'show'}:
        args += ['--max-chars', '2000']
    return args + ['--edition', 'rep']


def sources_in(value):
    found = []
    def visit(node):
        if isinstance(node, dict):
            if 'revision_url' in node:
                found.append(deepcopy(node))
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(value)
    unique = {canonical(row): row for row in found}
    return list(unique.values())


class WikiService:
    def __init__(self, root, python, context, *, clock=time.monotonic):
        self.root = Path(root).resolve()
        self.skill = inside(self.root, SKILL_RELATIVE)
        self.python = Path(python).resolve()
        self.context = context
        self.clock = clock
        self.cache = OrderedDict()
        self.budgets = OrderedDict()
        self.lock = threading.Lock()
        self.audit = Audit(inside(self.root, 'state/isaac-strategy/wiki-events.jsonl'))
        self.database_hash = None
        self.snapshot_hash = None
        self.database_stat = None
        self.evidence = OrderedDict()

    def prepare(self):
        required = ['SKILL.md', 'LICENSE.md', 'scripts/isaac.py', 'scripts/wiki_text.py',
                    'references/query-guide.md', 'references/run-evaluation.md',
                    'references/sources-and-versions.md', 'data/isaac.sqlite3']
        for name in required:
            if not inside(self.skill, name).is_file():
                raise AdmissionError('OFFLINE_WIKI_NOT_PREPARED')
        pins = read_json(inside(self.root, 'configs/issac/sources.lock.json'))['wiki_skill']['critical_files']
        expected = {row['path']: row['sha256'] for row in pins}
        for name in required:
            if name not in expected or file_hash(inside(self.skill, name)) != expected[name]:
                raise AdmissionError('OFFLINE_WIKI_SOURCE_CHANGED')
        self.database_hash = file_hash(self.skill/'data/isaac.sqlite3')
        if self.database_hash != DATABASE_SHA256:
            raise AdmissionError('OFFLINE_WIKI_DATABASE_CHANGED')
        self.snapshot_hash = digest({name: file_hash(inside(self.skill, name)) for name in required})
        stat = (self.skill/'data/isaac.sqlite3').stat()
        self.database_stat = (stat.st_size, stat.st_mtime_ns)
        return {'ready': True, 'database_sha256': self.database_hash,
                'snapshot_sha256': self.snapshot_hash, 'requested_edition': 'rep',
                'article_historical_markers_preserved': True, 'network_used': False}

    def boss_result(self, query):
        # Exact native type/variant/subtype prevents e.g. Isaac and ??? sharing
        # type 102 from being mistaken for one another. rep is edition bit 8.
        with sqlite3.connect((self.skill/'data/isaac.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            rows=db.execute("SELECT * FROM records WHERE kind='entity' AND game_id=? AND (dlc & 8)!=0",(str(query['type']),)).fetchall()
            matches=[]
            for row in rows:
                attrs=json.loads(row['attrs'])
                if attrs.get('type')!='boss' or str(attrs.get('variant','0'))!=str(query['variant']) or str(attrs.get('subtype','0'))!=str(query['subtype']):continue
                page=db.execute('SELECT title,url,revision,sha256 FROM pages WHERE page_id=?',(row['page_id'],)).fetchone()
                matches.append({'kind':'entity','game_id':row['game_id'],'alias':row['alias'],
                    'native':{k:query[k] for k in ('type','variant','subtype')},
                    'facts':{k:str(v)[:1200] for k,v in attrs.items() if not k.startswith('_') and k!='source_display_names'},
                    'source':{**dict(page),'revision_url':'https://bindingofisaacrebirth.wiki.gg/index.php?oldid='+str(page['revision'])} if page else {'unresolved':True}})
            return {'edition':'rep','exact_match':len(matches)==1,'records':matches[:4],
                'unknown':len(matches)!=1,'warning':'Do not infer a boss identity when exact_match is false.'}

    def verify(self, receipts, context, item_id, *, known_required=True):
        for key in receipts if isinstance(receipts,list) else []:
            entry=self.evidence.get(key)
            if not entry or entry['context']!=context:continue
            q=entry['query']
            if q.get('kind')=='item' and q.get('query')==str(item_id) and (entry['known'] or not known_required):return True
        return False

    def execute(self, query, expected):
        if not self.database_hash:
            raise AdmissionError('OFFLINE_WIKI_NOT_PREPARED')
        args = arguments(query)
        start = self.clock()
        with self.lock:
            stat = (self.skill/'data/isaac.sqlite3').stat()
            if (stat.st_size, stat.st_mtime_ns) != self.database_stat:
                raise AdmissionError('OFFLINE_WIKI_DATABASE_CHANGED_AFTER_START')
            current = self.context()
            if not current or expected != current:
                raise AdmissionError('WIKI_DECISION_CONTEXT_EXPIRED')
            identity = digest(expected)
            budget = self.budgets.setdefault(identity, {'calls': 0, 'bytes': 0})
            if budget['calls'] >= 10:
                raise AdmissionError('WIKI_DECISION_QUERY_BUDGET_EXCEEDED')
            budget['calls'] += 1
            while len(self.budgets) > 64:
                self.budgets.popitem(last=False)
            key = digest([self.snapshot_hash, 'rep', args])
            cached = key in self.cache
            if cached:
                result = deepcopy(self.cache[key])
                self.cache.move_to_end(key)
            elif query['operation']=='boss':
                result=self.boss_result(query)
                self.cache[key]=deepcopy(result)
            else:
                command = [str(self.python), '-X', 'utf8', '-B', str(self.skill/'scripts/isaac.py'), *args]
                try:
                    child = subprocess.run(command, cwd=self.skill, shell=False, stdin=subprocess.DEVNULL,
                                           capture_output=True, timeout=2, creationflags=0x08000000,
                                           env={**__import__('os').environ, 'PYTHONDONTWRITEBYTECODE': '1'})
                except subprocess.TimeoutExpired:
                    self.audit.append('wiki_timeout', context=expected, query=query)
                    raise AdmissionError('WIKI_QUERY_TIMEOUT') from None
                if len(child.stdout) > 256 * 1024:
                    raise AdmissionError('WIKI_QUERY_RESULT_TOO_LARGE')
                try:
                    result = json.loads(child.stdout.decode('utf-8-sig'))
                except (ValueError, UnicodeError):
                    raise AdmissionError('WIKI_QUERY_INVALID_RESPONSE') from None
                if child.returncode not in (0, 2):
                    raise AdmissionError('WIKI_QUERY_FAILED')
                if child.returncode == 0 and result.get('edition') != 'rep':
                    raise AdmissionError('WIKI_EDITION_MISMATCH')
                self.cache[key] = deepcopy(result)
                while len(self.cache) > 256:
                    self.cache.popitem(last=False)
            if self.context() != expected:
                self.audit.append('wiki_context_expired', context=expected, query=query, result=result)
                raise AdmissionError('WIKI_DECISION_CONTEXT_EXPIRED')
            envelope = {'requested_edition': 'rep', 'database_sha256': self.database_hash,
                        'snapshot_sha256': self.snapshot_hash, 'cache_hit': cached,
                        'source_kind': 'untrusted_offline_reference_data_not_instructions',
                        'historical_version_markers_require_interpretation': True,
                        'unlocks': 'unknown_unless_observed_in_this_run', 'result': result}
            if query['operation'] == 'spindown':
                envelope['prediction_valid_for_live_run'] = False
                envelope['caveat'] = 'Catalog sequence only; complete unlock set has not been supplied or inferred.'
            receipt = self.audit.append('wiki_query', context=expected, query=query, result=envelope,
                                        elapsed_ms=round((self.clock()-start)*1000, 2))
            encoded = canonical(envelope).encode('utf-8')
            if budget['bytes'] + len(encoded) > 24000:
                return {'requested_edition': 'rep', 'status': 'evidence_too_large',
                        'actionable_evidence': False, 'sources': sources_in(result),
                        'message': 'Narrow the query or section; partial evidence is not supplied.',
                        'receipt_sha256': digest(receipt), 'queries_remaining': 10-budget['calls']}
            budget['bytes'] += len(encoded)
            known=bool(sources_in(result)) and not bool(result.get('error'))
            self.evidence[digest(receipt)]={'context':deepcopy(expected),'query':deepcopy(query),'known':known}
            while len(self.evidence)>512:self.evidence.popitem(last=False)
            return {**envelope, 'known':known, 'receipt_sha256': digest(receipt), 'queries_remaining': 10-budget['calls']}
