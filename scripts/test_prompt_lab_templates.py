from pathlib import Path
from scripts.film_renderer import build_prompt_lab_shot

ROOT = Path(__file__).resolve().parents[1]
modes=['before_after_split','prompt_typewriter','annotation_callout','location_selector','light_split_compare','composition_push_in','error_fix_compare','checklist_stamp']
bg=str(ROOT / 'data' / 'local_ops_douyin_ai' / '20260912' / 'visual_assets' / 'subject.jpg')
htmls=[build_prompt_lab_shot(i,'测试标题','测试文本',bg,m,'测试') for i,m in enumerate(modes,1)]
assert all('<!DOCTYPE html>' in h and '测试标题' in h for h in htmls)
assert len({h.split('</style>')[0] for h in htmls}) == 1
print('templates_generated',len(htmls),'modes',','.join(modes))
