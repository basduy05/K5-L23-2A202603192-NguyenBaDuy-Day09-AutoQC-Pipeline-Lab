"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict  # noqa: F401

import yaml  # noqa: F401

from ..common import ERROR, parse_yolo_line  # noqa: F401


def fix(ds, issues, cfg):
    err_issues = [i for i in issues if i.severity == ERROR]
    if not err_issues:
        return []

    fixes = []
    removed_stems = set()

    # 1. remove_image
    remove_codes = {"DUP_IMAGE_EXACT", "DUP_IMAGE_NEAR", "LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}
    for iss in err_issues:
        if iss.code in remove_codes:
            stem = iss.image
            if stem not in removed_stems:
                img_p = ds.image_path(stem)
                if img_p and img_p.exists():
                    img_p.unlink()
                lbl_p = ds.label_path(stem)
                if lbl_p.exists():
                    lbl_p.unlink()
                removed_stems.add(stem)
                fixes.append({
                    "image": stem,
                    "line": None,
                    "action": "remove_image",
                    "before": img_p.name if img_p else stem,
                    "after": "(đã xoá)"
                })

    # 2. rename_classes
    for iss in err_issues:
        if iss.code == "BAD_CLASS_NAME":
            old_names = ds.yaml_names()
            target_classes = cfg.get("classes", [])
            data = {}
            if ds.yaml_path.exists():
                try:
                    data = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    data = {}
            data["names"] = target_classes
            ds.yaml_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
            fixes.append({
                "image": "data.yaml",
                "line": None,
                "action": "rename_classes",
                "before": str(old_names),
                "after": str(target_classes)
            })

    # 3. needs_label
    for iss in err_issues:
        if iss.code == "MISSING_LABEL_FILE":
            if iss.image not in removed_stems:
                fixes.append({
                    "image": iss.image,
                    "line": None,
                    "action": "needs_label",
                    "before": "(không có file)",
                    "after": "chuyển người gán"
                })

    # 4. drop_line / clip_box
    label_issues_by_stem = defaultdict(list)
    line_err_codes = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX", "BOX_OUT_OF_IMAGE"}
    for iss in err_issues:
        if iss.code in line_err_codes and iss.line is not None and iss.image not in removed_stems:
            label_issues_by_stem[iss.image].append(iss)

    for stem, stem_issues in label_issues_by_stem.items():
        lbl_p = ds.label_path(stem)
        if not lbl_p.exists():
            continue

        raw_lines = lbl_p.read_text(encoding="utf-8", errors="replace").splitlines()
        issues_per_line = defaultdict(list)
        for iss in stem_issues:
            issues_per_line[iss.line].append(iss)

        new_lines = []
        for line_idx, orig_line in enumerate(raw_lines, 1):
            if line_idx not in issues_per_line:
                new_lines.append(orig_line)
                continue

            curr_line_issues = issues_per_line[line_idx]
            codes_on_line = {i.code for i in curr_line_issues}

            drop_codes = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
            if any(c in drop_codes for c in codes_on_line):
                fixes.append({
                    "image": stem,
                    "line": line_idx,
                    "action": "drop_line",
                    "before": orig_line,
                    "after": "(đã xoá)"
                })
                continue

            if "BOX_OUT_OF_IMAGE" in codes_on_line:
                try:
                    c, cx, cy, w, h = parse_yolo_line(orig_line)
                    x1 = max(0.0, cx - w / 2.0)
                    y1 = max(0.0, cy - h / 2.0)
                    x2 = min(1.0, cx + w / 2.0)
                    y2 = min(1.0, cy + h / 2.0)
                    new_w = x2 - x1
                    new_h = y2 - y1

                    if new_w <= 0.0 or new_h <= 0.0:
                        fixes.append({
                            "image": stem,
                            "line": line_idx,
                            "action": "drop_line",
                            "before": orig_line,
                            "after": "(đã xoá)"
                        })
                    else:
                        new_cx = (x1 + x2) / 2.0
                        new_cy = (y1 + y2) / 2.0
                        clipped_str = f"{c} {new_cx:.6g} {new_cy:.6g} {new_w:.6g} {new_h:.6g}"
                        new_lines.append(clipped_str)
                        fixes.append({
                            "image": stem,
                            "line": line_idx,
                            "action": "clip_box",
                            "before": orig_line,
                            "after": clipped_str
                        })
                except Exception:
                    fixes.append({
                        "image": stem,
                        "line": line_idx,
                        "action": "drop_line",
                        "before": orig_line,
                        "after": "(đã xoá)"
                    })

        lbl_p.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")

    return fixes
