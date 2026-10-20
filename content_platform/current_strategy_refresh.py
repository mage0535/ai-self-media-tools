"""Refresh only native account/platform strategy inputs; original facts stay immutable."""
import copy,hashlib,json
from pathlib import Path

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()

def _same_lane_generation_ready(playbook):
 # Count native works; top_accounts is only an author-summary display.
 from urllib.parse import urlsplit
 import re
 from .same_lane_intelligence import _is_native_platform_url
 if not isinstance(playbook,dict)or playbook.get('version')!='same_lane_playbook_v1':return False
 radar=playbook.get('radar');works=playbook.get('top_works')
 if not isinstance(radar,dict)or not isinstance(works,list):return False
 ranked=radar.get('ranked_sample_count');platform=playbook.get('platform')
 if not(playbook.get('generation_status')=='ready'and radar.get('status')=='ready'
        and type(ranked)is int and ranked>=3):return False
 identities=set()
 for work in works:
  if not isinstance(work,dict)or not isinstance(work.get('url'),str):return False
  url=work['url'];parsed=urlsplit(url)
  if parsed.scheme not in {'http','https'}or parsed.username or parsed.password:return False
  if str(platform).casefold()in {'twitter','x'}:
   match=re.fullmatch(r'/[A-Za-z0-9_]{1,15}/status/([1-9][0-9]*)/?',parsed.path)
   if parsed.netloc.casefold()not in {'x.com','www.x.com','twitter.com','www.twitter.com'}or not match:return False
   identities.add(('twitter',match.group(1)))
  else:
   if not _is_native_platform_url(platform,url):return False
   identities.add((platform,url))
 return len(identities)>=3

def refresh_current_strategy_inputs(store,config,job,platform_contexts,runner=None):
 from .task_source_inputs import (_observed_strategy_inputs,_account_evidence_available,
  _NativeSourceObservation,SourceInputsBlocked,project_task_source_brief)
 from .cli import _load_collector_config
 from .performance_collectors import collect_platform_metrics,_platform
 from .platform_hot_adapters import collect_platform_hot_evidence
 from .same_lane_intelligence import distill_same_lane_samples
 from .intelligence import prepare_generation_strategy_inputs
 platforms=list(job.get('platforms')or[])
 if not platforms or set(platform_contexts)!=set(platforms):raise ValueError('current_strategy_platform_scope_changed')
 original=copy.deepcopy(job.get('brief')or{})
 def run(name,func):
  return runner.run(name,func,require_output=True)if runner is not None else func()
 settings=config.get('workflow_sources')or{}
 account_config,_=_load_collector_config(settings.get('performance_collector_config'))
 accounts=run('collect_current_strategy_accounts',lambda:collect_platform_metrics(platforms,account_config))
 source_path=settings.get('hot_source_config')
 hot_config=json.loads(Path(source_path).read_text(encoding='utf-8'))if source_path else{}
 # performance collectors include the existing AUTO-fresh source producer; hot adapters
 # consume its actual native raw refs. This function never changes observed_at.
 public=run('collect_current_strategy_platform_research',lambda:collect_platform_hot_evidence(hot_config))
 briefs={};refs={}
 for platform in platforms:
  observed=(accounts.get('platforms')or{}).get(_platform(platform))or{}
  if not _account_evidence_available(observed):
   raise SourceInputsBlocked('source_account_data_unavailable',{'platform':platform,'status':observed.get('status')})
  research=run('validate_current_strategy_raw['+platform+']',lambda platform=platform:_observed_strategy_inputs(platform,public))
  samples=research['viral_breakdown']['samples']
  same_lane=run('distill_current_strategy_same_lane['+platform+']',lambda platform=platform,samples=samples:
   distill_same_lane_samples(platform,[dict(row,url=row['canonical_url'],**row['metrics'])for row in samples]))
  if not _same_lane_generation_ready(same_lane):
   raise SourceInputsBlocked('source_same_lane_benchmark_unavailable',{'platform':platform})
  reference=_NativeSourceObservation(store,job).save('current-strategy-'+platform,
   {'job_id':job['id'],'platform':platform,'account_report':accounts,'public_report':public,
    'strategy_inputs':research,'original_factual_brief_sha256':digest(original),'Source_generation_model_calls':0})
  value=project_task_source_brief(original,platform)
  value.pop('platform_workflow_inputs',None)
  # Preserve original research/source references independently; refresh strategy references only.
  value['original_factual_reference_posts']=copy.deepcopy(value.get('reference_posts')or[])
  value.update(research,same_lane_intelligence=same_lane,reference_posts=samples,strategy_observation_ref=reference,
   account_analysis={'source':'native.performance_collectors','current_content_data':observed,'source_sha256':digest(accounts)})
  briefs[platform]=run('prepare_current_strategy['+platform+']',lambda platform=platform,value=value:
   prepare_generation_strategy_inputs(job['topic'],value))
  refs[platform]=reference
 result=copy.deepcopy(original);result['platform_workflow_inputs']=copy.deepcopy(briefs)
 audit={'producer':'native.current_strategy_refresh','platforms':platforms,'account_sha256':digest(accounts),
  'public_sha256':digest(public),'strategy_observation_refs':refs,
  'original_factual_brief_sha256':digest(original),'Source_generation_model_calls':0,
  'historical_generation_replayed':False,'observation_times_rewritten':False}
 return {'brief':result,'platform_briefs':briefs,'strategy_refresh_audit':audit}

def reuse_current_strategy_inputs(store,config,job,platform_contexts,observation_refs,runner=None):
 """Read current exact observation originals; never recollect or refresh timestamps."""
 import os,stat,re
 from .task_source_inputs import (_observed_strategy_inputs,_account_evidence_available,
  SourceInputsBlocked,project_task_source_brief)
 from .same_lane_intelligence import distill_same_lane_samples
 from .intelligence import prepare_generation_strategy_inputs
 platforms=list(job.get('platforms')or[])
 if set(platform_contexts)!=set(platforms)or set(observation_refs)!=set(platforms):
  raise ValueError('current_strategy_reuse_platform_scope_changed')
 original=copy.deepcopy(job.get('brief')or{});briefs={};account_pins={};public_pins={}
 def run(name,func):return runner.run(name,func,require_output=True)if runner is not None else func()
 for platform in platforms:
  ref=observation_refs[platform]
  if not isinstance(ref,dict)or not {'path','sha256'}<=set(ref)or not re.fullmatch('[a-f0-9]{64}',str(ref.get('sha256'))):
   raise PermissionError('current_strategy_actual_observation_reference_required')
  path=Path(ref['path']);expected_root=Path(store.path).parent/'jobs'/job['id']/'source-observations'
  if path.parent!=expected_root or any(p.is_symlink()for p in(path,*path.parents)):
   raise PermissionError('current_strategy_same_job_observation_path_required')
  info=path.stat();raw=path.read_bytes()
  if (not stat.S_ISREG(info.st_mode)or info.st_uid!=0 or info.st_mode&0o777!=0o600
      or info.st_nlink!=1 or not 0<len(raw)<=2097152 or hashlib.sha256(raw).hexdigest()!=ref['sha256']):
   raise PermissionError('current_strategy_original_observation_changed')
  observation=json.loads(raw)
  if observation.get('job_id')!=job['id']or observation.get('platform')!=platform:
   raise PermissionError('current_strategy_original_observation_scope_changed')
  accounts=observation.get('account_report')or{};public=observation.get('public_report')or{}
  observed=(accounts.get('platforms')or{}).get(platform)or{}
  if not _account_evidence_available(observed):raise SourceInputsBlocked('source_account_data_unavailable',{'platform':platform})
  research=run('revalidate_current_strategy_raw['+platform+']',lambda platform=platform,public=public:_observed_strategy_inputs(platform,public))
  original_research=observation.get('strategy_inputs')or{}
  if (research['viral_breakdown']['samples']!=(original_research.get('viral_breakdown')or{}).get('samples')
      or research['viral_collection'].get('collected_at')!=(original_research.get('viral_collection')or{}).get('collected_at')):
   raise PermissionError('current_strategy_bound_research_changed')
  samples=research['viral_breakdown']['samples']
  same_lane=run('redistill_current_strategy_same_lane['+platform+']',lambda platform=platform,samples=samples:
   distill_same_lane_samples(platform,[dict(row,url=row['canonical_url'],**row['metrics'])for row in samples]))
  if not _same_lane_generation_ready(same_lane):
   raise SourceInputsBlocked('source_same_lane_benchmark_unavailable',{'platform':platform})
  value=project_task_source_brief(original,platform);value.pop('platform_workflow_inputs',None)
  value['original_factual_reference_posts']=copy.deepcopy(value.get('original_factual_reference_posts')or value.get('reference_posts')or[])
  value.update(research,same_lane_intelligence=same_lane,reference_posts=samples,strategy_observation_ref=ref,
   account_analysis={'source':'native.performance_collectors','current_content_data':observed,'source_sha256':digest(accounts)})
  briefs[platform]=run('reprepare_current_strategy['+platform+']',lambda platform=platform,value=value:
   prepare_generation_strategy_inputs(job['topic'],value))
  account_pins[platform]=digest(accounts);public_pins[platform]=digest(public)
 result=copy.deepcopy(original);result['platform_workflow_inputs']=copy.deepcopy(briefs)
 return {'brief':result,'platform_briefs':briefs,'strategy_refresh_audit':{
  'producer':'native.current_strategy_observation_reuse','strategy_observation_refs':copy.deepcopy(observation_refs),
  'account_sha256':account_pins,'public_sha256':public_pins,'Source_generation_model_calls':0,
  'historical_generation_replayed':False,'observation_times_rewritten':False,'native_recollection_calls':0}}
