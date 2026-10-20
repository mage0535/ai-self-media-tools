"""Caller-declared content-specific prosody; positional templates cannot prove intent."""
from __future__ import annotations
import re
from typing import Any

def validate_voice_plan(plan:list[dict[str,Any]]|None,segments:list[str]|None=None)->dict:
 failures=[]
 if not isinstance(plan,list) or not plan:return {'passed':False,'failures':['voice_plan_missing']}
 if segments is not None and len(plan)!=len(segments):failures.append('voice_plan_count_mismatch')
 required={'index','text','style','semantic_direction','rate','pitch','pause_after_ms'}
 for index,row in enumerate(plan):
  if not isinstance(row,dict) or not required.issubset(row):failures.append('voice_plan_segment_invalid:'+str(index));continue
  if type(row['index']) is not int or row['index']!=index:failures.append('voice_plan_index_invalid:'+str(index))
  if not isinstance(row['text'],str) or not row['text'].strip():failures.append('voice_plan_text_missing:'+str(index))
  if segments is not None and index<len(segments) and row['text']!=segments[index]:failures.append('voice_plan_text_mismatch:'+str(index))
  if not isinstance(row['style'],str) or not row['style'].strip() or not isinstance(row['semantic_direction'],str) or not row['semantic_direction'].strip():failures.append('voice_plan_content_intent_missing:'+str(index))
  if not re.fullmatch(r'[+-]\d+%',str(row['rate'])):failures.append('voice_plan_rate_invalid:'+str(index))
  if not re.fullmatch(r'[+-]\d+Hz',str(row['pitch'])):failures.append('voice_plan_pitch_invalid:'+str(index))
  if type(row['pause_after_ms']) is not int or not 0<=row['pause_after_ms']<=5000:failures.append('voice_plan_pause_invalid:'+str(index))
 return {'passed':not failures,'failures':failures}

def build_voice_plan(segments:list[str],*,segment_styles:list[dict[str,Any]]|None=None)->list[dict[str,Any]]:
 result=validate_voice_plan(segment_styles,segments)
 if not result['passed']:raise ValueError(';'.join(result['failures']))
 return [dict(row) for row in segment_styles]
