import json
import re
from pathlib import Path

from scripts.visual_contract_gate import _body_attribute, enforce_entry, validate_scene_contract, validate_rendered_html
from scripts.film_renderer import build_prompt_lab_shot


def contract(modes=None):
    modes = modes or [f'mode_{i}' for i in range(8)]
    return [{
        'beat_id': f's{i+1:02d}',
        'visual_hook': f'hook {i}',
        'visual_mode': modes[i],
        'template_id': f'template_{i}',
        'evidence_asset': f'/tmp/asset_{i}.jpg',
        'group_motion': ['local_reveal'],
        'platform_reason': 'content-specific',
    } for i in range(8)]


def _shot_html(mode, purpose, marker, *, extra_class="", background="#315d7d"):
    return f'''<!doctype html><html><head><style>
    html,body{{margin:0;width:1080px;height:1920px;background:{background};color:white}}
    .bg{{position:absolute;inset:0;background:linear-gradient(135deg,#315d7d,#8d5b45)}}
    .scene{{position:absolute;z-index:2;left:90px;top:300px;width:900px;height:900px;background:#315d7dcc}}
    .evidence{{width:700px;height:500px;background:#d77b35;font-size:48px}}
    </style></head><body data-beat-id="s01" data-template-id="template" data-visual-mode="{mode}"
      data-shot-purpose="{purpose}" data-group-motion="local_reveal" data-platform-reason="content-specific">
      <div class="bg"></div><main class="scene {extra_class}"><section class="evidence">{marker}</section></main>
    </body></html>'''


def _write_pairs(html_dir, *, class_only=False, dark=False):
    html_dir.mkdir()
    for i in range(8):
        scene = contract()[i]
        common = dict(
            marker=f"evidence-{i}",
            background="#000" if dark else "#315d7d",
        )
        a = _shot_html(scene['visual_mode'], f"establish-{i}", **common)
        b = _shot_html(
            f"detail_{i}",
            f"inspect-{i}",
            common['marker'] if class_only else f"detail-evidence-{i}",
            extra_class=f"variant-{i}",
            background=common['background'],
        )
        if class_only:
            b = re.sub(r'class="scene"', f'class="scene variant-{i}"', a).replace(
                f'establish-{i}', f'inspect-{i}'
            ).replace(scene['visual_mode'], f"detail_{i}")
        (html_dir / f'shot_{i+1:02d}A.html').write_text(a, encoding='utf-8')
        (html_dir / f'shot_{i+1:02d}B.html').write_text(b, encoding='utf-8')


def test_direct_entry_requires_contract(tmp_path):
    result = enforce_entry(tmp_path, 'bilibili')
    assert not result['passed']
    assert 'scene_contract_missing' in result['failures']


def test_direct_entry_accepts_valid_contract(tmp_path):
    (tmp_path / 'scene_contract.json').write_text(json.dumps({'scenes': contract()}, ensure_ascii=False), encoding='utf-8')
    result = enforce_entry(tmp_path, 'bilibili')
    assert result['passed']
    assert result['legacy'] is False


def test_registered_predictive_maintenance_v3_templates_pass_strict_runtime():
    modes = [
        'before_after_split', 'input_branch', 'source_trace', 'error_fix_compare',
        'evidence_timeline', 'checklist_lock', 'flow_track', 'result_audit',
    ]
    scenes = contract(modes)
    for scene, mode in zip(scenes, modes):
        scene['template_id'] = f'predictive_maintenance_{mode}_v3'
        scene['group_motion'] = ['local_highlight']

    result = validate_scene_contract(scenes, strict_runtime=True)

    assert result['passed'] is True
    assert result['failures'] == []


def test_renderer_consumes_contract_provenance(tmp_path):
    from PIL import Image
    bg = tmp_path / 'bg.jpg'
    Image.new('RGB', (32, 32), (20, 40, 60)).save(bg)
    a = build_prompt_lab_shot(1, 'title', 'body', str(bg), 'before_after_split', 'k', 'template_A', ['wipe_A'], 'reason_A')
    b = build_prompt_lab_shot(1, 'title', 'body', str(bg), 'before_after_split', 'k', 'template_B', ['wipe_B'], 'reason_B')
    assert 'data-template-id="template_A"' in a
    assert 'data-group-motion="wipe_A"' in a
    assert 'data-platform-reason="reason_A"' in a
    assert 'data-template-id="template_B"' in b
    assert a != b


def test_renderer_builds_substantive_ab_variants(tmp_path):
    from PIL import Image

    bg = tmp_path / 'bg.jpg'
    Image.new('RGB', (32, 32), (20, 40, 60)).save(bg)
    a = build_prompt_lab_shot(
        1, 'title', 'body', str(bg), 'before_after_split', 'k',
        shot_purpose='establish-result',
    )
    b = build_prompt_lab_shot(
        1, 'title', 'body', str(bg), 'annotation_callout', 'k',
        shot_purpose='inspect-fields',
    )

    assert 'data-visual-mode="before_after_split"' in a
    assert 'data-visual-mode="annotation_callout"' in b
    assert 'data-shot-purpose="establish-result"' in a
    assert 'data-shot-purpose="inspect-fields"' in b
    assert a != b


def test_gate_reads_mode_from_body_not_css_selector(tmp_path):
    from PIL import Image

    bg = tmp_path / 'bg.jpg'
    Image.new('RGB', (32, 32), (20, 40, 60)).save(bg)
    html = build_prompt_lab_shot(
        1, 'title', 'body', str(bg), 'annotation_callout', 'k',
        shot_purpose='inspect-fields',
    )

    assert 'body[data-visual-mode="prompt_typewriter"]' in html
    assert _body_attribute(html, 'data-visual-mode') == 'annotation_callout'


def test_non_invoice_contract_does_not_inject_invoice_or_english_review_labels(tmp_path):
    from PIL import Image
    bg = tmp_path / 'bg.jpg'
    Image.new('RGB', (32, 32), (20, 40, 60)).save(bg)
    html = build_prompt_lab_shot(
        6,
        'AI 工业质检',
        '漏检率和误报率必须由质检员复核',
        str(bg),
        'legacy_generic_mode',
        '工业现场',
        'failure_boundary_v1',
        ['error_mark'],
        '人工接管边界',
        'checklist_lock',
    )
    assert 'Vendor' not in html
    assert 'Duplicate' not in html
    assert 'HUMAN CHECK' not in html
    assert '01 输入' in html
    assert '04 责任' in html


def test_invoice_contract_keeps_invoice_specific_visuals(tmp_path):
    from PIL import Image
    bg = tmp_path / 'bg.jpg'
    Image.new('RGB', (32, 32), (20, 40, 60)).save(bg)
    html = build_prompt_lab_shot(
        1,
        '发票自动核对',
        '采购单和发票进入付款前复核',
        str(bg),
        'legacy_generic_mode',
        '财务流程',
        'invoice_check_v1',
        ['check_each'],
        '发票异常交人工',
        'checklist_lock',
    )
    assert 'VENDOR' in html
    assert 'DUPLICATE' in html


def test_scene_contract_requires_all_fields():
    data = contract()
    data[2]['visual_hook'] = ''
    result = validate_scene_contract(data)
    assert not result['passed']
    assert any('visual_hook' in item for item in result['failures'])


def test_scene_contract_rejects_adjacent_duplicate_modes():
    data = contract(['same', 'same', 'c', 'd', 'e', 'f', 'g', 'h'])
    result = validate_scene_contract(data)
    assert not result['passed']
    assert 'adjacent_visual_mode_duplicate' in result['failures']


def test_scene_contract_accepts_eight_distinct_modes():
    assert validate_scene_contract(contract())['passed']


def test_html_gate_rejects_square_majority(tmp_path):
    html_dir = tmp_path / 'html'
    _write_pairs(html_dir)
    for path in html_dir.glob('shot_*.html'):
        path.write_text(path.read_text(encoding='utf-8').replace('class="evidence"', 'class="tile evidence"'), encoding='utf-8')
    result = validate_rendered_html(html_dir, contract())
    assert not result['passed']
    assert 'generic_square_container_majority' in result['failures']


def test_html_gate_accepts_real_structure_diversity(tmp_path):
    html_dir = tmp_path / 'html'
    _write_pairs(html_dir)
    result = validate_rendered_html(html_dir, contract())
    assert result['passed']
    assert len(result['records']) == 16
    assert all(record['visible_area_ratio'] > 0.02 for record in result['records'])
    assert all(record['background_visible'] for record in result['records'])


def test_html_gate_rejects_missing_a_variant(tmp_path):
    html_dir = tmp_path / 'html'
    _write_pairs(html_dir)
    (html_dir / 'shot_03A.html').unlink()

    result = validate_rendered_html(html_dir, contract())

    assert not result['passed']
    assert 'html_scene_pair_count' in result['failures']


def test_html_gate_rejects_same_mode_purpose_and_dom_for_ab(tmp_path):
    html_dir = tmp_path / 'html'
    _write_pairs(html_dir)
    a = (html_dir / 'shot_01A.html').read_text(encoding='utf-8')
    (html_dir / 'shot_01B.html').write_text(a, encoding='utf-8')

    result = validate_rendered_html(html_dir, contract())

    assert not result['passed']
    assert 'shot_01_ab_visual_mode_duplicate' in result['failures']
    assert 'shot_01_ab_purpose_duplicate' in result['failures']
    assert 'shot_01_ab_html_duplicate' in result['failures']
    assert 'shot_01_ab_dom_duplicate' in result['failures']


def test_html_gate_rejects_class_only_ab_difference(tmp_path):
    html_dir = tmp_path / 'html'
    _write_pairs(html_dir, class_only=True)

    result = validate_rendered_html(html_dir, contract())

    assert not result['passed']
    assert any(item.endswith('_ab_dom_duplicate') for item in result['failures'])


def test_html_gate_rejects_invisible_semantic_content_and_background(tmp_path):
    html_dir = tmp_path / 'html'
    _write_pairs(html_dir)
    target = html_dir / 'shot_04B.html'
    text = target.read_text(encoding='utf-8').replace(
        '.evidence{', '.bg{display:none}.scene{display:none}.evidence{'
    )
    target.write_text(text, encoding='utf-8')

    result = validate_rendered_html(html_dir, contract())

    assert not result['passed']
    assert 'html_shot_04B.html_semantic_area_too_small' in result['failures']
    assert 'html_shot_04B.html_background_not_visible' in result['failures']


def test_html_gate_rejects_black_or_overdark_frames(tmp_path):
    html_dir = tmp_path / 'html'
    _write_pairs(html_dir)
    target = html_dir / 'shot_05A.html'
    target.write_text('''<!doctype html><html><head><style>
    html,body{margin:0;width:1080px;height:1920px;background:#000;color:#050505}
    .bg{position:absolute;inset:0;background:#000}.evidence{position:absolute;z-index:2;width:900px;height:900px;background:#030303}
    </style></head><body data-visual-mode="mode_4" data-shot-purpose="establish-4"><div class="bg"></div><div class="evidence">dark</div></body></html>''', encoding='utf-8')

    result = validate_rendered_html(html_dir, contract())

    assert not result['passed']
    assert 'html_shot_05A.html_frame_too_dark' in result['failures']


def test_html_gate_rejects_public_shell_overuse(tmp_path):
    html_dir = tmp_path / 'html'
    _write_pairs(html_dir)
    first_a = (html_dir / 'shot_01A.html').read_text(encoding='utf-8')
    first_b = (html_dir / 'shot_01B.html').read_text(encoding='utf-8')
    for i in range(8):
        (html_dir / f'shot_{i+1:02d}A.html').write_text(first_a.replace('s01', f's{i+1:02d}'), encoding='utf-8')
        (html_dir / f'shot_{i+1:02d}B.html').write_text(first_b.replace('s01', f's{i+1:02d}'), encoding='utf-8')

    result = validate_rendered_html(html_dir, contract())

    assert not result['passed']
    assert 'public_shell_overuse' in result['failures']


def test_html_gate_requires_independent_visible_cta_when_quality_contract_is_active(tmp_path):
    html_dir = tmp_path / 'html'
    _write_pairs(html_dir)

    result = validate_rendered_html(
        html_dir,
        contract(),
        require_independent_cta=True,
    )

    assert result['passed'] is False
    assert 'independent_visual_cta_missing_or_invisible' in result['failures']


def test_all_routable_visual_modes_have_visible_layout(tmp_path):
    from PIL import Image
    from scripts.film_renderer import ROUTABLE_VISUAL_MODES

    bg = tmp_path / 'bg.jpg'
    Image.new('RGB', (64, 64), (55, 95, 125)).save(bg)
    for index, mode in enumerate(sorted(ROUTABLE_VISUAL_MODES), 1):
        html = build_prompt_lab_shot(index, '可见布局', '证据内容', str(bg), mode, '验收')
        assert f'data-visual-mode="{mode}"' in html
        assert f'body[data-visual-mode="{mode}"]' in html
        assert 'data-shot-purpose=' in html


def test_html_gate_accepts_independent_cta_with_safe_geometry_and_contrast(tmp_path):
    html_dir = tmp_path / 'html'
    _write_pairs(html_dir)
    target = html_dir / 'shot_08B.html'
    text = target.read_text(encoding='utf-8').replace(
        '</main>', '<div data-role="visual-cta" data-visual-role="cta" data-semantic-key="next-value" style="position:absolute;left:100px;top:1400px;width:700px;height:120px;color:#111111;background:#ffd166">下一步</div></main>'
    )
    target.write_text(text, encoding='utf-8')
    result = validate_rendered_html(html_dir, contract(), require_independent_cta=True)
    assert result['passed'] is True
    record = next(item for item in result['records'] if item['file'].endswith('shot_08B.html'))
    assert record['min_local_contrast_ratio'] >= 4.5
    assert record['visual_role_collisions'] == []
    assert record['duplicate_semantic_keys'] == []


def test_html_gate_rejects_end_card_role_collision(tmp_path):
    html_dir = tmp_path / 'html'
    _write_pairs(html_dir)
    target = html_dir / 'shot_08B.html'
    text = target.read_text(encoding='utf-8').replace(
        '</main>', '<div data-visual-role="label" style="position:absolute;left:120px;top:400px;width:400px;height:120px">标签</div><div data-visual-role="cta" style="position:absolute;left:300px;top:450px;width:400px;height:120px">行动</div></main>'
    )
    target.write_text(text, encoding='utf-8')
    result = validate_rendered_html(html_dir, contract(), require_independent_cta=True)
    assert not result['passed']
    assert 'html_shot_08B.html_visual_role_collision' in result['failures']


def test_html_gate_rejects_local_text_background_contrast(tmp_path):
    html_dir = tmp_path / 'html'
    _write_pairs(html_dir)
    target = html_dir / 'shot_08B.html'
    text = target.read_text(encoding='utf-8').replace(
        '</main>', '<div data-visual-role="cta" style="position:absolute;left:100px;top:1400px;width:700px;height:120px;color:#ffffff;background:#eeeeee">CTA</div></main>'
    )
    target.write_text(text, encoding='utf-8')
    result = validate_rendered_html(html_dir, contract(), require_independent_cta=True)
    assert not result['passed']
    assert 'html_shot_08B.html_local_contrast_too_low' in result['failures']


def test_html_gate_rejects_duplicate_semantic_layers(tmp_path):
    html_dir = tmp_path / 'html'
    _write_pairs(html_dir)
    target = html_dir / 'shot_08B.html'
    text = target.read_text(encoding='utf-8').replace(
        '</main>', '<div data-visual-role="label" data-semantic-key="next-value" style="position:absolute;left:100px;top:1400px;width:200px;height:80px">下一步</div><div data-visual-role="cta" data-semantic-key="next-value" style="position:absolute;left:100px;top:1550px;width:300px;height:80px">下一步</div></main>'
    )
    target.write_text(text, encoding='utf-8')
    result = validate_rendered_html(html_dir, contract(), require_independent_cta=True)
    assert not result['passed']
    assert 'html_shot_08B.html_duplicate_semantic_layer' in result['failures']
