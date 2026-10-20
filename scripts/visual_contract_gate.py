#!/usr/bin/env python3
"""Runtime gates for content-driven scene visual contracts."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

VISUAL_CONTRACT_GATE_VERSION = "visual-contract-gate-v1"
REQUIRED_FIELDS = (
    "beat_id", "visual_hook", "visual_mode", "template_id",
    "evidence_asset", "group_motion", "platform_reason",
)
FORBIDDEN_GENERIC = {"tile", "step", "panel", "module", "stat", "bubble"}
KNOWN_MOTION_ACTIONS = {
    "wipe_reveal", "type_in", "caret_follow", "callout_draw", "local_highlight",
    "orbit_select", "focus_shift", "split_reveal", "temperature_shift",
    "frame_draw", "push_in", "error_mark", "fix_reveal", "check_each", "stamp_lock",
}
KNOWN_TEMPLATE_IDS = {
    "meeting_hero_compare", "meeting_record_diff", "language_rule_compare",
    "owner_missing_state", "deadline_missing_state", "result_counter_compare",
    "transcribe_summarize_verify", "choice_cta",
    "predictive_maintenance_before_after_split_v3",
    "predictive_maintenance_input_branch_v3",
    "predictive_maintenance_source_trace_v3",
    "predictive_maintenance_error_fix_compare_v3",
    "predictive_maintenance_evidence_timeline_v3",
    "predictive_maintenance_checklist_lock_v3",
    "predictive_maintenance_flow_track_v3",
    "predictive_maintenance_result_audit_v3",
}
SHELL_CLASSES = {"bg", "veil", "head", "k", "t", "content", "contract-execution"}


def _norm(value):
    return str(value or "").strip()


def validate_scene_contract(contract, beat_count=8, *, strict_runtime=False):
    failures = []
    if not isinstance(contract, list) or len(contract) != beat_count:
        return {"passed": False, "failures": ["scene_contract_count"], "scenes": []}
    modes, templates = [], []
    for idx, scene in enumerate(contract, 1):
        if not isinstance(scene, dict):
            failures.append(f"scene_{idx}_not_object")
            continue
        missing = [field for field in REQUIRED_FIELDS if not _norm(scene.get(field))]
        if missing:
            failures.append(f"scene_{idx}_missing:{','.join(missing)}")
        if strict_runtime:
            unknown = sorted(set(str(item).strip() for item in (scene.get("group_motion") or [])) - KNOWN_MOTION_ACTIONS)
            if unknown:
                failures.append(f"scene_{idx}_unknown_group_motion:{','.join(unknown)}")
            template_id = _norm(scene.get("template_id"))
            if not (template_id.endswith("_v1") or template_id in KNOWN_TEMPLATE_IDS):
                failures.append(f"scene_{idx}_template_not_registered:{template_id}")
        if str(scene.get("beat_id")) not in {f"s{idx:02d}", f"beat_{idx:02d}", str(idx)}:
            failures.append(f"scene_{idx}_beat_id_mismatch")
        modes.append(_norm(scene.get("visual_mode")))
        templates.append(_norm(scene.get("template_id")))
    if len(set(modes)) < 3:
        failures.append("fewer_than_3_visual_modes")
    if len(set(templates)) < 3:
        failures.append("fewer_than_3_template_ids")
    if any(left and left == right for left, right in zip(modes, modes[1:])):
        failures.append("adjacent_visual_mode_duplicate")
    return {"passed": not failures, "failures": sorted(set(failures)), "scenes": contract}


class _SemanticDOMParser(HTMLParser):
    """Hash visible meaning while deliberately ignoring class-only changes."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth_ignored = 0
        self.tokens: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.depth_ignored += 1
            return
        if self.depth_ignored:
            return
        attrs = dict(attrs)
        classes = set(str(attrs.get("class") or "").split())
        if classes and classes.issubset(SHELL_CLASSES):
            return
        meaningful = []
        for key in ("src", "alt", "href", "role"):
            if attrs.get(key):
                value = re.sub(r"data:[^;]+;base64,[A-Za-z0-9+/=]+", "data:asset", str(attrs[key]))
                meaningful.append((key, value))
        self.tokens.append(f"<{tag}:{meaningful}>")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.depth_ignored:
            self.depth_ignored -= 1
            return
        if not self.depth_ignored:
            self.tokens.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.depth_ignored:
            text = re.sub(r"\s+", " ", data).strip()
            if text:
                self.tokens.append(text)


def _html_evidence(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    body = re.split(r"<body\b[^>]*>", text, maxsplit=1, flags=re.I)[-1].split("</body>", 1)[0]
    classes = [token for value in re.findall(r'class=["\']([^"\']+)["\']', body) for token in value.split()]
    tags = re.findall(r"<([a-zA-Z][\w-]*)\b", body)
    semantic_classes = [item for item in classes if item not in SHELL_CLASSES]
    structure_text = json.dumps({"tags": tags, "classes": semantic_classes}, ensure_ascii=False, sort_keys=True)
    parser = _SemanticDOMParser()
    parser.feed(body)
    semantic_text = json.dumps(parser.tokens, ensure_ascii=False, separators=(",", ":"))
    return {
        "text": text,
        "html_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "structure_signature": hashlib.sha256(structure_text.encode()).hexdigest(),
        "dom_signature": hashlib.sha256(semantic_text.encode()).hexdigest(),
        "classes": semantic_classes,
    }


def html_structure_signature(path: Path):
    evidence = _html_evidence(path)
    return evidence["structure_signature"], evidence["classes"]


def _body_attribute(text: str, name: str) -> str:
    body_match = re.search(r"<body\b([^>]*)>", text, flags=re.I | re.S)
    if not body_match:
        return ""
    attr_match = re.search(
        rf"\b{re.escape(name)}=[\"']([^\"']*)[\"']",
        body_match.group(1),
        flags=re.I,
    )
    return _norm(attr_match.group(1) if attr_match else "")


def _computed_evidence(files: list[Path]):
    """Collect real browser-computed area/background and pixel darkness evidence."""
    from PIL import Image, ImageStat
    from playwright.sync_api import sync_playwright
    from scripts.film_renderer import _chromium_executable_path, _chromium_launch_environment

    results = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=_chromium_executable_path(),
            env=_chromium_launch_environment(), args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 540, "height": 960}, device_scale_factor=1)
            for path in files:
                page.set_content(path.read_text(encoding="utf-8", errors="replace"), wait_until="domcontentloaded", timeout=10_000)
                page.evaluate("() => { if (typeof window.renderFrame === 'function') window.renderFrame(1.5); }")
                computed = page.evaluate("""() => {
                    const viewportArea = Math.max(1, innerWidth * innerHeight);
                    const excluded = new Set(['bg','veil','head','k','t','content','contract-execution','contract-motion']);
                    const visible = el => {
                      const s = getComputedStyle(el), r = el.getBoundingClientRect();
                      return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0.05 && r.width > 1 && r.height > 1;
                    };
                    const semantic = [...document.body.querySelectorAll('*')].filter(el =>
                      ![...el.classList].some(name => excluded.has(name)) && visible(el));
                    const maxArea = semantic.reduce((best, el) => {
                      const r = el.getBoundingClientRect(); return Math.max(best, r.width * r.height);
                    }, 0);
                    const bg = document.querySelector('.bg');
                    let backgroundVisible = false, backgroundAreaRatio = 0;
                    if (bg && visible(bg)) {
                      const r = bg.getBoundingClientRect(), s = getComputedStyle(bg);
                      backgroundAreaRatio = (r.width * r.height) / viewportArea;
                      backgroundVisible = backgroundAreaRatio >= .8 &&
                        (s.backgroundImage !== 'none' || s.backgroundColor !== 'rgba(0, 0, 0, 0)');
                    }
                    const cta = document.querySelector('[data-role="visual-cta"], [data-visual-role="cta"], .visual-cta');
                    let ctaVisible = false, ctaAreaRatio = 0;
                    if (cta && visible(cta)) {
                      const r = cta.getBoundingClientRect();
                      ctaAreaRatio = (r.width * r.height) / viewportArea;
                      ctaVisible = ctaAreaRatio >= .01;
                    }
                    const roles = [...document.querySelectorAll('[data-visual-role]')].filter(visible).map(el => {
                      const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                      return {el, role: el.dataset.visualRole, key: el.dataset.semanticKey || '', text: (el.innerText || '').replace(/\\s+/g, ' ').trim(),
                        x:r.x, y:r.y, right:r.right, bottom:r.bottom, width:r.width, height:r.height,
                        color:s.color, backgroundColor:s.backgroundColor};
                    });
                    const rgb = value => {
                      const m = String(value || '').match(/rgba?\\(([^)]+)\\)/);
                      if (!m) return null;
                      const parts = m[1].split(',').map(Number);
                      return parts.length >= 3 ? parts.slice(0,3) : null;
                    };
                    const channel = value => { const v=value/255; return v <= .03928 ? v/12.92 : Math.pow((v+.055)/1.055,2.4); };
                    const luminance = value => { const c=rgb(value); return c ? .2126*channel(c[0])+.7152*channel(c[1])+.0722*channel(c[2]) : null; };
                    const contrastRatios = roles.map(item => {
                      const fg=luminance(item.color), bg=luminance(item.backgroundColor);
                      return fg === null || bg === null ? null : (Math.max(fg,bg)+.05)/(Math.min(fg,bg)+.05);
                    }).filter(value => value !== null);
                    const collisions = [];
                    for (let i=0;i<roles.length;i++) for (let j=i+1;j<roles.length;j++) {
                      const a=roles[i], b=roles[j];
                      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
                      const area=Math.max(0,Math.min(a.right,b.right)-Math.max(a.x,b.x))*Math.max(0,Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y));
                      const smaller=Math.max(1,Math.min(a.width*a.height,b.width*b.height));
                      if (area/smaller >= .08) collisions.push([a.role,b.role]);
                    }
                    const semanticKeys = roles.map(item => item.key).filter(Boolean);
                    const duplicateKeys = [...new Set(semanticKeys.filter((key, index) => semanticKeys.indexOf(key) !== index))];
                    return {visible_area_ratio: maxArea / viewportArea, background_visible: backgroundVisible,
                            background_area_ratio: backgroundAreaRatio, cta_visible: ctaVisible,
                            cta_area_ratio: ctaAreaRatio, visual_role_count: roles.length,
                            visual_role_collisions: collisions, min_local_contrast_ratio: contrastRatios.length ? Math.min(...contrastRatios) : null,
                            duplicate_semantic_keys: duplicateKeys};
                }""")
                image = Image.open(io.BytesIO(page.screenshot(type="png"))).convert("L").resize((90, 160))
                pixels = list(image.get_flattened_data())
                computed["mean_luminance"] = round(float(ImageStat.Stat(image).mean[0]), 3)
                computed["dark_pixel_ratio"] = round(sum(value < 12 for value in pixels) / len(pixels), 4)
                results[path.name] = computed
        finally:
            browser.close()
    return results


def enforce_entry(video_dir, platform, *, allow_legacy=False, require_native=False):
    """Fail closed for direct renderers unless a validated scene contract exists."""
    root = Path(video_dir)
    contract_path = Path(__import__('os').environ.get('VIDEO_SCENE_CONTRACT_PATH', ''))
    if not contract_path.is_file():
        contract_path = root / 'scene_contract.json'
    if not contract_path.is_file():
        if allow_legacy or __import__('os').environ.get('VIDEO_ALLOW_LEGACY') == '1':
            return {'passed': True, 'legacy': True, 'platform': platform, 'path': ''}
        return {'passed': False, 'failures': ['scene_contract_missing'], 'platform': platform, 'path': str(contract_path)}
    try:
        data = json.loads(contract_path.read_text(encoding='utf-8'))
        contract = data.get('scenes') if isinstance(data, dict) else data
        result = validate_scene_contract(contract, beat_count=8)
        result.update({'platform': platform, 'path': str(contract_path), 'legacy': False})
        if result.get('passed') and require_native and __import__('os').environ.get('VIDEO_ALLOW_LEGACY') != '1':
            return {'passed': False, 'failures': ['renderer_not_contract_aware_use_main_runner'], 'platform': platform, 'path': str(contract_path)}
        return result
    except (OSError, json.JSONDecodeError) as exc:
        return {'passed': False, 'failures': [f'scene_contract_invalid:{type(exc).__name__}'], 'platform': platform, 'path': str(contract_path)}


def validate_rendered_html(
    html_dir,
    contract,
    *,
    strict_runtime=False,
    require_independent_cta=False,
):
    root = Path(html_dir)
    files = sorted(root.glob("shot_*[AB].html"))
    expected_names = [f"shot_{index:02d}{variant}.html" for index in range(1, len(contract) + 1) for variant in "AB"]
    if [path.name for path in files] != expected_names:
        return {"passed": False, "failures": ["html_scene_pair_count"], "records": []}

    failures: list[str] = []
    try:
        computed = _computed_evidence(files)
    except Exception as exc:  # fail closed: static class strings are not visibility evidence
        return {
            "passed": False,
            "failures": [f"computed_evidence_unavailable:{type(exc).__name__}"],
            "records": [],
        }

    records = []
    by_name = {}
    for path in files:
        match = re.fullmatch(r"shot_(\d{2})([AB])\.html", path.name)
        index = int(match.group(1))
        variant = match.group(2)
        scene = contract[index - 1]
        evidence = _html_evidence(path)
        text = evidence.pop("text")
        mode = _body_attribute(text, "data-visual-mode")
        purpose = _body_attribute(text, "data-shot-purpose")
        record = {
            "file": str(path), "beat_id": scene.get("beat_id"), "variant": variant,
            "template_id": scene.get("template_id"), "visual_mode": mode,
            "shot_purpose": purpose, **evidence, **computed[path.name],
        }
        records.append(record)
        by_name[(index, variant)] = record
        if not purpose:
            failures.append(f"html_{path.name}_shot_purpose_missing")
        if record["visible_area_ratio"] < 0.02:
            failures.append(f"html_{path.name}_semantic_area_too_small")
        if not record["background_visible"]:
            failures.append(f"html_{path.name}_background_not_visible")
        if record["mean_luminance"] < 14 or record["dark_pixel_ratio"] > 0.94:
            failures.append(f"html_{path.name}_frame_too_dark")
        if record.get("visual_role_collisions"):
            failures.append(f"html_{path.name}_visual_role_collision")
        if record.get("min_local_contrast_ratio") is not None and record["min_local_contrast_ratio"] < 4.5:
            failures.append(f"html_{path.name}_local_contrast_too_low")
        if record.get("duplicate_semantic_keys"):
            failures.append(f"html_{path.name}_duplicate_semantic_layer")
        if strict_runtime:
            expected = {
                "beat_id": _norm(scene.get("beat_id")),
                "template_id": _norm(scene.get("template_id")),
                "group_motion": ",".join(str(x).strip() for x in (scene.get("group_motion") or [])),
                "platform_reason": _norm(scene.get("platform_reason")),
            }
            if variant == "A":
                expected["visual_mode"] = _norm(scene.get("visual_mode"))
            for key, value in expected.items():
                attr = f'data-{key.replace("_", "-")}="{value}"'
                if attr not in text:
                    failures.append(f"html_{path.name}_{key}_not_bound")
            for action in scene.get("group_motion") or []:
                token = f'class="contract-motion motion-{action}"'
                if token not in text or "data-applied-motion" not in text:
                    failures.append(f"html_{path.name}_motion_not_executable:{action}")

    for index in range(1, len(contract) + 1):
        a, b = by_name[(index, "A")], by_name[(index, "B")]
        prefix = f"shot_{index:02d}_ab"
        if a["visual_mode"] == b["visual_mode"]:
            failures.append(f"{prefix}_visual_mode_duplicate")
        if a["shot_purpose"] == b["shot_purpose"]:
            failures.append(f"{prefix}_purpose_duplicate")
        if a["html_sha256"] == b["html_sha256"]:
            failures.append(f"{prefix}_html_duplicate")
        if a["dom_signature"] == b["dom_signature"]:
            failures.append(f"{prefix}_dom_duplicate")

    square_count = sum(bool(set(record["classes"]) & FORBIDDEN_GENERIC) for record in records)
    if square_count > len(records) // 2:
        failures.append("generic_square_container_majority")
    semantic_counts = Counter(record["dom_signature"] for record in records)
    if semantic_counts and max(semantic_counts.values()) >= len(records) // 2:
        failures.append("public_shell_overuse")
    if require_independent_cta:
        final_record = by_name.get((len(contract), "B"), {})
        if not final_record.get("cta_visible"):
            failures.append("independent_visual_cta_missing_or_invisible")
    return {"passed": not failures, "failures": sorted(set(failures)), "records": records}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", required=True)
    ap.add_argument("--html-dir")
    args = ap.parse_args()
    data = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    contract = data.get("scenes") if isinstance(data, dict) else data
    result = validate_scene_contract(contract, len(contract) if isinstance(contract, list) else 8)
    if args.html_dir and result.get("passed"):
        result["html"] = validate_rendered_html(args.html_dir, contract)
        result["passed"] = result["passed"] and result["html"]["passed"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
