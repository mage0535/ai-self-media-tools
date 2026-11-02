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
