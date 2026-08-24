from PIL import Image
from content_platform.cover_quality import normalize_cover_resolution
def test_cover_resolution_is_normalized_without_changing_aspect(tmp_path):
 path=tmp_path/"cover.png"; Image.new("RGB",(768,768),"white").save(path); result=normalize_cover_resolution(path); assert result["passed"] is True; assert result["dimensions"] == [1200,1200]
