"""区分人工生产主题与实际原生材料标题；不产生调用者提供的来源证据。"""
import hashlib
import json
import re
from urllib.parse import urlparse,urldefrag
from .real_world_ai_policy import classify_discovery_text,load_real_world_ai_positioning,_contains
from .source_quality import source_is_rankable
from .trend_intelligence import _candidate_source_url_is_native

VERSION='manual-topic-native-material-v1'
ROOT_ACTION='source_manual_topic_intent'
PRODUCERS={'cli.create','quality_revision.create','root.manual_topic_source_recovery'}
SCENE_LOCALIZATION_VERSION='twitter-source-scene-localization-v1'
REPORT_SCENE_PHRASES=('tabular report','financial report','operational report')

def localized_scene_evidence(platform,terms,text):
    """只把版本化窄办公报表词义绑定原文；不改原生标题/全文。"""
    if platform not in {'twitter','x'} or terms!=['报表']:return None
    if re.search(r'\b(?:news|industry|vulnerability|breaking)\s+reports?\b',str(text),re.I):return None
    matches=re.findall(r'\b(?:tabular|financial|operational)\s+reports?\b',str(text),re.I)
    if not matches:return None
    return {'version':SCENE_LOCALIZATION_VERSION,'platform':platform,'canonical_scene':'报表',
        'pillar':'office_automation','matched_original_phrases':list(dict.fromkeys(matches)),
        'original_text_sha256':topic_hash(text),'derived_only':True}


RECEIPT_SCENE='report_delivery_receipt_check'
SCENE_TERMS={
 'report':r'报表|\breports?\b',
 'delivery':r'交付|交接|送达|发送|\b(?:deliver(?:y|ed|ing)?|handoff|send|sent|dispatch)\b',
 'receipt':r'回执|收件人|确认收到|签收|\b(?:receipts?|ack(?:nowledg(?:e|ement|ment))?|recipient|delivery confirmation)\b',
 'checking':r'核对|核验|验证|比对|校验|\b(?:check(?:ing)?|verif(?:y|ication)|validat(?:e|ion)|reconcil(?:e|iation)|match|audit|unconfirmed|evidence)\b'}
def scenario_support(text):
    return {name:bool(re.search(pattern,str(text),re.I))for name,pattern in SCENE_TERMS.items()}
def production_scenario(topic):
    support=scenario_support(topic)
    if all(support.values()):
        return {'version':'production-scenario-intent-v1','kind':RECEIPT_SCENE,'requested_topic':str(topic),
                'requested_topic_sha256':topic_hash(topic),'action':'verify_report_delivery_evidence',
                'object':'report_delivery_receipt','supporting_evidence_domains':['delivery_acknowledgement','file_identity_or_version','task_or_workflow_identity']}
    return None
def supports_requested_scenario(topic,title,summary):
    intent=production_scenario(topic)
    if intent is None:return None
    seen=scenario_support(str(title)+' '+str(summary))
    # A useful method source need not contain all three receipt field names.
    # It must support the same delivery-verification process, not report/news popularity.
    passed=seen['report']and seen['delivery']and(seen['receipt']or seen['checking'])
    return {'passed':bool(passed),'production_scenario':intent,'observed_semantic_groups':seen,
            'source_text_sha256':topic_hash((str(title)+' '+str(summary)).strip())}

def request_ranking_keywords(job,platform,store=None):
    terms=request_source_keywords(job,store)
    if production_scenario(job['topic']):return ['报表','交付','回执','report delivery','report handoff','delivery receipt','receipt verification']
    return terms+list(REPORT_SCENE_PHRASES) if platform in {'twitter','x'} and terms==['报表'] else terms

def manual_twitter_query(job,store=None):
    terms=request_source_keywords(job,store)
    if production_scenario(job['topic']):
        return '(AI OR automation OR workflow) (\"report delivery\" OR \"report handoff\" OR \"delivery receipt\" OR \"delivery acknowledgement\" OR 报表交付 OR 交付回执) (check OR verify OR receipt OR confirmation OR 核对 OR 回执)'
    if terms!=['报表'] or not classify_manual_intent(job['topic']).get('accepted'):
        raise ValueError('native_twitter_manual_query_scene_not_supported')
    return '(AI OR automation OR workflow) (报表 OR "tabular report" OR "financial report" OR "operational report") (tutorial OR case OR demo OR 案例 OR 实战)'
def topic_hash(value):
    return hashlib.sha256(str(value).encode()).hexdigest()
def _digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def manual_request_brief(topic,brief,producer='cli.create'):
    if not isinstance(brief,dict) or producer not in PRODUCERS:raise ValueError('manual_topic_request_provenance_invalid')
    if 'topic_request_contract' in brief:raise ValueError('topic_request_contract_reserved_for_creation_entry')
    result=dict(brief)
    result['topic_request_contract']={'version':VERSION,'mode':'manual_intent','producer':producer,'requested_topic_sha256':topic_hash(topic)}
    return result
def resolve_request_contract(job,store=None):
    contract=(job.get('brief') or {}).get('topic_request_contract')
    if contract is None and store is not None and getattr(store,'_root_source_repair',None) is not None:
        from .source_repair_runtime import active_grant
        grant=active_grant(store);candidate=grant.get('manual_topic_request_contract')
        if candidate is not None:
            payload=grant['policy'].verify(grant['token'],ROOT_ACTION)
            if (grant.get('action')!=ROOT_ACTION or payload.get('job_id')!=job.get('id')
                    or payload.get('manual_topic_request_contract_sha256')!=_digest(candidate)
                    or payload.get('allow_requested_topic_intent_unchanged') is not True):
                raise ValueError('manual_topic_same_store_root_authority_required')
            contract=candidate
    if contract is None:return {'mode':'native_title','requested_topic_sha256':topic_hash(job['topic'])}
    if (not isinstance(contract,dict) or contract.get('version')!=VERSION or contract.get('mode')!='manual_intent'
            or contract.get('producer') not in PRODUCERS or contract.get('requested_topic_sha256')!=topic_hash(job['topic'])):
        raise ValueError('manual_topic_request_contract_invalid')
    if contract['producer']=='root.manual_topic_source_recovery':
        if store is None or getattr(store,'_root_source_repair',None) is None:
            raise ValueError('manual_topic_root_provenance_requires_active_native_scope')
        from .source_repair_runtime import active_grant
        grant=active_grant(store);payload=grant['policy'].verify(grant['token'],ROOT_ACTION)
        if (grant.get('action')!=ROOT_ACTION or payload.get('job_id')!=job.get('id')
                or payload.get('manual_topic_request_contract_sha256')!=_digest(contract)
                or payload.get('allow_requested_topic_intent_unchanged') is not True):
            raise ValueError('manual_topic_same_store_root_authority_required')
    return dict(contract)
def _specific_scene_terms(terms):
    terms=list(dict.fromkeys(str(value) for value in terms if str(value)))
    return [value for value in terms if not any(value.casefold()!=other.casefold() and value.casefold() in other.casefold() for other in terms)]

def classify_manual_intent(topic):
    # 原完整分类器保持排除项与AI能力判据；编辑意图不承担来源的案例证明。
    original=classify_discovery_text(topic)
    if not original.get('accepted') and original.get('reason')!='outcome_or_case_signal_missing':return original
    policy=load_real_world_ai_positioning()
    matched={pillar:_contains(str(topic),list(terms or [])) for pillar,terms in (policy.get('pillars') or {}).items()}
    matched={pillar:terms for pillar,terms in matched.items() if terms}
    specific=_specific_scene_terms(term for terms in matched.values() for term in terms)
    if len(specific)!=1:return {'accepted':False,'reason':'manual_intent_original_scene_not_unique'}
    # 同一个政策原词跨相邻分类时，使用原分类器的确定性选择；不加别名或跨场景通融。
    pillar,_=max(matched.items(),key=lambda item:(max((len(str(term)) for term in item[1]),default=0),len(item[1])))
    return {'accepted':True,'pillar':pillar,'scenario_terms':specific,
            'policy_profile':policy['policy_profile'],'policy_revision':policy['policy_revision'],
            'ai_capability_terms':_contains(str(topic),list(policy.get('ai_capability_terms') or [])),
            'classification_object':'manual_editorial_intent','implementation_result_claimed':False,
            'production_scenario':production_scenario(topic),'requested_topic':str(topic),'requested_topic_sha256':topic_hash(topic)}

def request_source_keywords(job,store=None):
    contract=resolve_request_contract(job,store)
    if contract['mode']!='manual_intent':return [job['topic']]
    classification=classify_manual_intent(job['topic'])
    if not classification.get('accepted'):return []
    return list(classification['scenario_terms'])
def manual_material_evidence(job,platform,candidate,report,store=None):
    def reject(reason):return {'passed':False,'reason':reason}
    try:contract=resolve_request_contract(job,store)
    except (ValueError,PermissionError):return reject('manual_topic_request_contract_invalid')
    if contract['mode']!='manual_intent':return reject('manual_topic_contract_not_active')
    if not source_is_rankable(candidate):return reject('manual_material_unavailable_or_synthetic')
    source=str(candidate.get('source') or '').casefold();prefix,_,suffix=source.partition(':')
    if prefix!=str(platform).casefold() or suffix in {'source_fallback','github','external','search'}:
        return reject('manual_material_not_platform_native')
    url=str(candidate.get('canonical_url') or candidate.get('url') or '').strip();parsed=urlparse(url)
    if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
            or not _candidate_source_url_is_native(platform,{'source':str(platform)+':web_search','url':url})):
        return reject('manual_material_url_not_native')
    request=classify_manual_intent(job['topic'])
    title=str(candidate.get('title') or '');summary=str(candidate.get('summary') or candidate.get('excerpt') or '')
    material=classify_discovery_text(title,summary)
    terms=request_source_keywords(job,store)
    text=(str(candidate.get('title') or '')+' '+str(candidate.get('summary') or candidate.get('excerpt') or '')).casefold()
    requested_support=supports_requested_scenario(job['topic'],title,summary)
    if requested_support is not None and not requested_support['passed']:
        return reject('manual_material_not_same_delivery_verification_process')
    localization=localized_scene_evidence(platform,terms,(title+' '+summary).strip())
    if requested_support is not None and requested_support['passed']and localization is None:
        localization={'version':'production-scenario-intent-v1','canonical_scene':'报表','pillar':'office_automation',
            'original_text_sha256':topic_hash((title+' '+summary).strip()),'derived_only':True,'semantic_support':requested_support}
    matched=[term for term in terms if term.casefold() in text]
    classification_object="selected_native_material_title_and_summary"
    if localization is not None:
        # 排除、AI能力、案例/结果信号先在原文过；只补其缺失的规范场景分类。
        if not material.get('accepted') and material.get('reason')=='concrete_application_scene_missing':
            derived_summary=summary+' [规范办公场景本地化分类参考：报表]'
            material=classify_discovery_text(title,derived_summary)
            localization.update(classifier_input_sha256=topic_hash((title+' '+derived_summary).strip()),
                classifier_input_derivation='original_title_and_summary_plus_versioned_scene_classification_reference')
            classification_object='derived_versioned_scene_classification_reference_bound_to_original_title_and_summary'
        if material.get('accepted') and material.get('pillar')=='office_automation':matched=list(terms)
    if (not request.get('accepted') or not material.get('accepted') or request.get('pillar')!=material.get('pillar')
            or not terms or len(matched)!=len(terms)):
        return reject('manual_material_not_same_specific_request_scene')
    url_sha=topic_hash(urldefrag(url)[0]);raw_sha=None;observed=None
    for row in report.get('sources') or []:
        label=str(row.get('source') or '').casefold()
        if label!=prefix or row.get('status') not in {'ok','success','saved','usable'}:continue
        proof=row.get('fetch_provenance') or {}
        if proof.get('result_kind')!='live_http' or url_sha not in (proof.get('source_url_sha256s') or []):continue
        for attempt in proof.get('attempts') or []:
            pin=str(attempt.get('response_sha256') or '')
            if (attempt.get('transport')=='http' and attempt.get('status')=='ok' and re.fullmatch('[0-9a-f]{64}',pin)
                    and (suffix!='native_query' or (candidate.get('raw_response_hash')==pin
                        and url_sha in (attempt.get('source_url_sha256s') or [])))):
                raw_sha=pin;observed=row.get('collected_at');break
        if raw_sha:break
    if not raw_sha or not observed:return reject('manual_material_real_response_url_binding_missing')
    return {'passed':True,'version':VERSION,'requested_topic':job['topic'],'requested_topic_sha256':contract['requested_topic_sha256'],
            'platform':platform,'source':candidate['source'],'source_title':candidate['title'],'source_title_sha256':topic_hash(candidate['title']),
            'source_url':url,'source_url_sha256':url_sha,'raw_response_sha256':raw_sha,'observed_at':observed,
            'same_specific_scene_terms':matched,'policy_revision':material['policy_revision'],'pillar':material['pillar'],
            'source_material_text_sha256':topic_hash((title+' '+summary).strip()),
            'source_classification':material,'classification_object':classification_object,
            'scene_localization':localization}
def bind_selected_material(job,task,materials,store=None):
    contract=resolve_request_contract(job,store)
    if contract['mode']!='manual_intent':
        if task.get('topic')!=job['topic']:raise ValueError('source_requested_topic_not_selected')
        return {'selected_topic':task['topic'],'requested_topic':job['topic']}
    urls=(task.get('brief') or {}).get('sources') or []
    matches=[v for v in materials if v.get('passed') and v.get('platform')==task.get('platform')
             and v.get('source_title')==task.get('topic') and v.get('source')==(task.get('brief') or {}).get('source')
             and v.get('source_url') in urls and v.get('requested_topic_sha256')==topic_hash(job['topic'])]
    if len(matches)!=1:raise ValueError('manual_selected_material_not_bound_to_actual_native_candidate')
    return dict(matches[0],selected_topic=task['topic'],production_topic=job['topic'])

