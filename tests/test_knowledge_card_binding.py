import hashlib
import json

import pytest

from content_platform.quality_gates import render_wechat_knowledge_cards


class _Store:
    def __init__(self, rows):
        self.rows = rows

    def artifacts(self, job_id):
        return self.rows


def _setup(tmp_path, body, section, *, text_sha=None, register=True):
    root = tmp_path / "artifacts" / "job1"
    root.mkdir(parents=True)
    image = root / "s1.png"
    image.write_bytes(b"png")
    checksum = hashlib.sha256(b"png").hexdigest()
    (root / "section_image_map.json").write_text(json.dumps([{"section": section, "asset_hash": checksum,
                                                               **({"section_text_sha256": text_sha} if text_sha else {})}]))
    (tmp_path / "r.py").write_text("")
    (tmp_path / "SKILL.md").write_text("x")
    config = {"media": {"knowledge_cards": {"renderer_path": str(tmp_path / "r.py"), "skill_path": str(tmp_path / "SKILL.md")}}}
    draft = {"title": "t", "body": body, "draft_meta": {"tool_invocation_manifest": {"planned_tools": {"knowledge_card_designer": {}}}}}
    store = _Store([{"kind": "image", "checksum": checksum, "path": str(image)}] if register else [])
    return store, draft, config


def test_h1_section_heading_binds_with_the_image_parser(tmp_path):
    # The renderer's own parser only knew ##-####; the image map was built from #-######.
    store, draft, config = _setup(tmp_path, "# 一、背景\n\n工厂质检用AI后，人工复核仍保留。\n", "一、背景")
    with pytest.raises(ValueError, match="knowledge_card_sections_missing"):
        render_wechat_knowledge_cards(store, tmp_path, "job1", draft, config)


@pytest.mark.parametrize("kwargs,code", [({"text_sha": "0" * 64}, "knowledge_card_section_text_changed"),
                                         ({"register": False}, "knowledge_card_image_artifact_missing")])
def test_binding_failures_name_their_cause(tmp_path, kwargs, code):
    store, draft, config = _setup(tmp_path, "## 一、背景\n\n工厂质检用AI后，人工复核仍保留。\n", "一、背景", **kwargs)
    with pytest.raises(ValueError, match=code):
        render_wechat_knowledge_cards(store, tmp_path, "job1", draft, config)
