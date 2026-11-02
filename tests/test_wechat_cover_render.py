import shutil
from pathlib import Path

import pytest
from PIL import Image

from content_platform import wechat_cover_render as W

FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")


def test_title_match_absorbs_glyph_confusion_only():
    assert W._title_matches("AI运营视频号用什么工具?别再全流程硬扛", "Al运营视频号用什么工具?别再全流程硬拭")
    assert W._title_matches("报表自动生成:财务月结从5天缩到1天", "报表自动生成:财务月结从5天绾到1天")


@pytest.mark.parametrize("expected,text", [
    ("工业质检用上AI后,漏检率从3%降到0.5%", "工业质检用上AI后,漏检率从3%降到5%"),
    ("AI排班实战:连锁门店人力成本降了12%", "AI排班实战:连锁门店人力成本降了21%"),
    ("会议纪要自动化:一个销售团队的落地复盘", "会议纪要自动化:一个团队的落地复盘"),
    ("数字孪生工厂:一条汽车焊装线的仿真落地", "FEET:一条汽车焊装线的仿真落地"),
    ("合同审查交给AI:法务团队的30天实测", ""),
])
def test_title_match_rejects_changed_numbers_missing_or_garbled_text(expected, text):
    assert not W._title_matches(expected, text)


@pytest.mark.skipif(not shutil.which("tesseract") or not FONT.is_file(), reason="needs tesseract + Noto CJK")
@pytest.mark.parametrize("title", ["数字孪生工厂：一条汽车焊装线的仿真落地", "AI排班实战：连锁门店人力成本降了12%",
                                   "招聘初筛自动化：HR团队的两周改造记录"])
def test_rendered_cover_title_passes_real_ocr(tmp_path, title):
    Image.new("RGB", W.SIZE, "#4a7aa0").save(tmp_path / "bg.png")
    result = W.render_wechat_cover(tmp_path / "bg.png", tmp_path / "cover.png", artifact_root=tmp_path, draft_title=title)
    assert result["provider_result"]["cover_render_evidence"]["ocr"]["matched"]


@pytest.mark.skipif(not shutil.which("tesseract") or not FONT.is_file(), reason="needs tesseract + Noto CJK")
@pytest.mark.parametrize("platform,size,title", [("juejin", (1920, 1080), "微信AI客服搭建避坑指南：从知识库切分到转人工分流的落地规范"),
                                                 ("xiaohongshu", (1200, 1600), "非研发背景做智能告警")])
def test_article_platform_cover_uses_its_own_size_and_passes_the_cover_gate(tmp_path, platform, size, title):
    # 11-03: Juejin/Zhihu/XHS covers had no rendered title; the gate reads the title through the render proof.
    import hashlib
    from content_platform.cover_quality import validate_cover
    rng = __import__("random").Random(7)
    background = Image.new("RGB", (1024, 1024))
    background.putdata([(rng.randrange(40, 200), rng.randrange(60, 160), rng.randrange(80, 220)) for _ in range(1024 * 1024)])
    background = background.resize((64, 64)).resize((1024, 1024))  # soft texture, no text
    background.save(tmp_path / "bg.png")
    result = W.render_wechat_cover(tmp_path / "bg.png", tmp_path / "cover.png", artifact_root=tmp_path,
                                   draft_title=title, platform=platform)
    proof = result["provider_result"]["cover_render_evidence"]
    assert proof["dimensions"] == list(size) and Image.open(tmp_path / "cover.png").size == size
    evidence = {"platform": platform, "layout_key": "checklist_poster", "hook": "h", "conflict_or_payoff": "c",
                "content_match_reason": "m", "focal_subjects": ["s"], "title": title, "independent_render": True,
                "cover_sha256": hashlib.sha256((tmp_path / "cover.png").read_bytes()).hexdigest(),
                "background_provenance": {"path": str(tmp_path / "bg.png"), "visible_required": True},
                "title_render_proof": {"path": result["evidence_path"], "sha256": result["evidence_sha256"]}}
    gate = validate_cover(tmp_path / "cover.png", evidence, platform)
    assert gate["ocr"]["title_reader"] == "render_proof_line_ocr" and gate["ocr"]["title_recall"] == 1.0
    assert gate["thumbnail_ocr"]["title_recall"] == 1.0
    assert not {"title_ocr_recall_too_low", "thumbnail_title_unreadable", "independent_cover_render_missing",
                "background_provenance_missing", "xiaohongshu_cover_aspect_invalid", "background_crushed_to_solid"} & set(gate["failures"])
    evidence["title_render_proof"]["sha256"] = "0" * 64  # an unbound proof falls back to whole-image OCR
    assert validate_cover(tmp_path / "cover.png", evidence, platform)["ocr"].get("title_reader") is None
