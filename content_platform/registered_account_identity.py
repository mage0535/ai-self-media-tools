"""Read Root-admitted original actor identities; never logs in or enables delivery."""
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime
import hashlib,json,re,sqlite3,stat

PROJECT=Path('/srv/ai-self-media-tools')
IDENTITY_ROOT=Path('/etc/hermes/registered-account-identities')
IDENTITY_SOURCE='root_verified_original_account_identity_v1'
PROOF_SCHEMA='registered_account_identity_v1'
sha=lambda raw:hashlib.sha256(raw).hexdigest()

def proof_path(platform,registered_id):
    return IDENTITY_ROOT/(sha((platform+'\0'+registered_id).encode())+'.json')

def _private_bytes(path,limit=2*1024*1024):
    path=Path(path)
    if not path.is_absolute()or'..'in path.parts or any(p.is_symlink()for p in(path,*path.parents)):
        raise ValueError('registered_identity_original_nonlink_required')
    info=path.stat()
    if (not stat.S_ISREG(info.st_mode)or info.st_uid!=0 or info.st_nlink!=1
        or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>limit):
        raise ValueError('registered_identity_Root_private_bounded_original_required')
    raw=path.read_bytes();after=path.stat()
    if (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
        raise ValueError('registered_identity_original_changed')
    return raw

def validate_identity_proof(value,account,binding):
    keys={'schema','platform','registered_account_id','native_account_id','internal_account_alias',
          'registered_scope','evidence_kind','evidence_refs','admitted_at','producer'}
    if not isinstance(value,dict)or set(value)!=keys or value['schema']!=PROOF_SCHEMA:
        raise ValueError('registered_identity_exact_proof_required')
    config=binding.get('config')or{}
    expected=(account.get('platform'),account.get('id'),str(config.get('account_id')or''),binding.get('account_key'))
    actual=(value['platform'],value['registered_account_id'],value['native_account_id'],value['internal_account_alias'])
    if actual!=expected or config.get('registered_account_id')!=account.get('id')or config.get('internal_account_alias')!=binding.get('account_key'):
        raise ValueError('registered_identity_exact_GUID_native_alias_required')
    if binding.get('platform')!=value['platform']or config.get('identity_source')!=IDENTITY_SOURCE:
        raise ValueError('registered_identity_admitted_source_required')
    uid=value['native_account_id']
    if not isinstance(uid,str)or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',uid)or uid in{'main','creator','unknown'}:
        raise ValueError('registered_identity_stable_native_ID_required')
    scope={k:account.get(k)for k in('niche','lang','content_type')}
    if value['registered_scope']!=scope or any(not isinstance(v,str)or not v for v in scope.values()):
        raise ValueError('registered_identity_original_rule_scope_changed')
    if value['producer']!='Root_single_writer_original_identity_admission' or value['evidence_kind']not in{'original_operator_profile_uid','original_state_uid'}:
        raise ValueError('registered_identity_original_producer_required')
    try:stamp=datetime.fromisoformat(value['admitted_at'].replace('Z','+00:00'))
    except (ValueError,TypeError,AttributeError):raise ValueError('registered_identity_real_admission_time_required')from None
    if stamp.tzinfo is None:raise ValueError('registered_identity_real_admission_time_required')
    refs=value['evidence_refs']
    if not isinstance(refs,list)or not refs or len(refs)>16:
        raise ValueError('registered_identity_raw_evidence_required')
    seen=set()
    for ref in refs:
        if not isinstance(ref,dict)or set(ref)!={'kind','path','sha256'}or not isinstance(ref['kind'],str)or not ref['kind']or not re.fullmatch('[a-f0-9]{64}',str(ref['sha256'])):
            raise ValueError('registered_identity_exact_evidence_reference_required')
        if ref['path']in seen:raise ValueError('registered_identity_duplicate_evidence_reference')
        seen.add(ref['path'])
    return value

def read_identity_proof(reference,account,binding):
    if not isinstance(reference,dict)or set(reference)!={'path','sha256'}:
        raise ValueError('registered_identity_exact_proof_reference_required')
    if Path(reference['path'])!=proof_path(account.get('platform',''),account.get('id','')):
        raise ValueError('registered_identity_Root_managed_locator_required')
    raw=_private_bytes(reference['path'])
    if sha(raw)!=reference['sha256']:raise ValueError('registered_identity_proof_SHA_changed')
    proof=validate_identity_proof(json.loads(raw),account,binding)
    evidence={}
    for ref in proof['evidence_refs']:
        original=_private_bytes(ref['path'])
        if sha(original)!=ref['sha256']:raise ValueError('registered_identity_evidence_Source_SHA_changed')
        evidence.setdefault(ref['kind'],[]).append(original)
    if proof['platform']=='bilibili':
        if any(len(evidence.get(k,[]))!=1 for k in('original_native_nav','original_native_card')):
            raise ValueError('registered_identity_original_Bili_native_pair_required')
        nav=json.loads(evidence['original_native_nav'][0]);card=json.loads(evidence['original_native_card'][0]);uid=proof['native_account_id']
        if(nav.get('code')!=0 or(nav.get('data')or{}).get('isLogin')is not True or str((nav.get('data')or{}).get('mid'))!=uid
            or card.get('code')!=0 or str(((card.get('data')or{}).get('card')or{}).get('mid'))!=uid):
            raise ValueError('registered_identity_original_Bili_native_MID_changed')
    return proof

def resolve_registered_account_identity(project_root,account,*,binding_reader=None):
    project=Path(project_root)
    if project!=PROJECT or project.resolve()!=project:
        raise ValueError('registered_identity_formal_project_required')
    if not isinstance(account,dict)or not isinstance(account.get('id'),str)or not account.get('id')or not isinstance(account.get('platform'),str):
        raise ValueError('registered_identity_original_account_required')
    account=dict(account,platform='xiaohongshu' if account['platform']=='xhs' else account['platform'])
    if binding_reader is None:
        from .admin_store import AdminStore
        admin=AdminStore(project/'data/state.db')
        @contextmanager
        def readonly():
            c=sqlite3.connect(admin.path.as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON')
            try:yield c
            finally:c.close()
        admin.connect=readonly
        binding_reader=lambda platform:admin.list_bindings(platform)
    rows=[r for r in binding_reader(account['platform'])if(r.get('config')or{}).get('registered_account_id')==account['id']]
    if len(rows)!=1:raise ValueError('normal_registered_account_identity_not_verified_or_ambiguous')
    binding=rows[0];proof=read_identity_proof((binding.get('config')or{}).get('registered_identity_proof_ref'),account,binding)
    forms={'text_image':'image_text','video_stock':'video','video':'video','article':'article','text':'text'}
    form=forms.get(proof['registered_scope']['content_type'])
    if form is None:raise ValueError('registered_identity_original_content_form_unknown')
    return {'platform':proof['platform'],'account_id':proof['native_account_id'],
            'internal_account_alias':proof['internal_account_alias'],'lane':proof['registered_scope']['niche'],'content_form':form}
