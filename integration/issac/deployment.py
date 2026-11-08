"""Verified candidate admission; a preparation receipt cannot authorize runtime."""
from __future__ import annotations

from pathlib import Path
import re
import subprocess

from .common import AdmissionError, digest, file_hash, inside, native_only, read_json


def require_candidate(root, *, hardware=True):
    native_only()
    root=Path(root).resolve()
    selected=read_json(inside(root,'configs/deployment-target.json'))
    if selected.get('target')!='issac-rtx4090' or selected.get('branch')!='issac':
        raise AdmissionError('ISAAC_INSTALLATION_TARGET_REQUIRED')
    origin=read_json(inside(root,'.setup/deployment-origin.json'))
    candidate=read_json(inside(root,'.setup/candidate.json'))
    manifest=read_json(inside(root,'.setup/source-manifest.json'))
    if (origin.get('target')!='issac-rtx4090' or origin.get('branch')!='issac'
            or origin.get('kind')!='verified_source_archive_installation'
            or not origin.get('verified_source_manifest')
            or not re.fullmatch('[0-9a-f]{40}',origin.get('source_commit',''))
            or not re.fullmatch('[0-9a-f]{64}',origin.get('archive_sha256',''))
            or origin.get('source_manifest_sha256')!=digest(manifest)
            or candidate.get('source_commit')!=origin.get('source_commit')
            or candidate.get('source_manifest_sha256')!=digest(manifest)
            or candidate.get('id')!=manifest.get('candidate_id')):
        raise AdmissionError('VERIFIED_FROZEN_SOURCE_INSTALLATION_REQUIRED')
    if (manifest.get('branch')!='issac' or manifest.get('all_round_code_complete') is not True
            or manifest.get('tests_started_at_freeze') is not False):
        raise AdmissionError('WHOLE_ROUND_FREEZE_REQUIRED')
    for row in manifest['files']:
        path=inside(root,row['path'])
        if not path.is_file() or path.stat().st_size!=row['bytes'] or file_hash(path)!=row['sha256']:
            raise AdmissionError('FROZEN_SOURCE_CHANGED')
    if hardware:
        result=subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total',
                    '--format=csv,noheader,nounits'],text=True,timeout=10,creationflags=0x08000000)
        rows=[line.rsplit(',',1) for line in result.splitlines() if line.strip()]
        if len(rows)!=1 or not re.search(r'RTX\s+4090(?:\s|$)',rows[0][0]) or int(rows[0][1])<45000:
            raise AdmissionError('PINNED_RTX4090_HARDWARE_REQUIRED')
    return {'candidate_id':candidate['id'],'source_commit':origin['source_commit'],
            'source_files_verified':len(manifest['files']),'production_accepted':False,
            'public_broadcast_allowed':False}


def require_acceptance(root):
    candidate=require_candidate(root)
    evidence=read_json(inside(root,'state/issac-acceptance/release.json'))
    from .delivery import recording_gate
    required={'native_game','save_protection','ordinary_inputs','wiki_prompt_tools','local_model',
              'verified_events','seven_extensions','ncm01','mouth_fangs_25fps','body_continuity',
              'mc_programme','single_audio','fault_recovery','cohost_1800','cohost_7200',
              'full_run_outcome','rollback',recording_gate(root)}
    if (evidence.get('candidate_id')!=candidate['candidate_id'] or evidence.get('accepted') is not True
            or set(evidence.get('passed',[]))!=required):
        raise AdmissionError('COMPLETE_REAL_ACCEPTANCE_EVIDENCE_REQUIRED')
    return evidence
