"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line  # noqa: F401
from ..model_cache import get_preds  # noqa: F401


def run(ds, cfg, preds=None):
    if preds is None:
        preds = get_preds(ds, cfg, "checker")

    so_cfg = cfg.get("second_opinion", {})
    conf_th = so_cfg.get("conf", 0.25)
    min_area_px = so_cfg.get("min_area_px", 600)
    fp_conf = so_cfg.get("fp_conf", 0.1)
    iou_missing = so_cfg.get("iou_missing", 0.3)
    iou_match = so_cfg.get("iou_match", 0.5)
    iou_loose = so_cfg.get("iou_loose", 0.5)

    issues = []

    for img_p in ds.image_files():
        stem = img_p.stem
        if stem not in preds:
            continue
        if not ds.label_path(stem).exists():
            continue

        size = ds.image_size(stem)
        if not size:
            continue
        W, H = size

        img_preds = preds.get(stem, [])
        label_boxes = ds.valid_boxes(stem)

        # 1. Dự đoán của model -> Missing / Loose / Wrong class
        P = [r for r in img_preds if r[1] >= conf_th and (r[4] * W * r[5] * H) >= min_area_px]

        for r in P:
            pred_cls, pred_conf, pcx, pcy, pw, ph = int(r[0]), float(r[1]), r[2], r[3], r[4], r[5]
            pbox = (pcx, pcy, pw, ph)

            cands = []
            for l_cls, lcx, lcy, lw, lh in label_boxes:
                lbox = (lcx, lcy, lw, lh)
                iou = iou_xywh(pbox, lbox)
                if iou >= iou_missing:
                    cands.append((l_cls, iou))

            if not cands:
                issues.append(Issue(
                    "second_opinion", WARN, "POSSIBLE_MISSING", stem,
                    f"model thấy vật {ds.classes[pred_cls]} (conf={pred_conf:.2f}) mà nhãn không có",
                    extra={"conf": pred_conf}
                ))
            else:
                same_cands = [c for c in cands if c[0] == pred_cls]
                if same_cands:
                    best_same_iou = max(c[1] for c in same_cands)
                    if best_same_iou < iou_loose:
                        issues.append(Issue(
                            "second_opinion", WARN, "POSSIBLE_LOOSE_BOX", stem,
                            f"box nhãn {ds.classes[pred_cls]} lệch so với dự đoán (IoU={best_same_iou:.2f} < {iou_loose})",
                            extra={"conf": pred_conf, "iou": best_same_iou}
                        ))
                else:
                    diff_cands = [c for c in cands if c[0] != pred_cls]
                    if diff_cands:
                        best_diff_iou = max(c[1] for c in diff_cands)
                        if best_diff_iou >= iou_match:
                            issues.append(Issue(
                                "second_opinion", WARN, "POSSIBLE_WRONG_CLASS", stem,
                                f"nhãn gán khác lớp với dự đoán (IoU={best_diff_iou:.2f} >= {iou_match})",
                                extra={"conf": pred_conf, "iou": best_diff_iou}
                            ))

        # 2. Quét False Positives trên từng dòng nhãn
        fp_preds = [r for r in img_preds if r[1] >= fp_conf]
        try:
            raw_lines = ds.label_path(stem).read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            raw_lines = []

        for line_idx, raw_line in enumerate(raw_lines, 1):
            line_str = raw_line.strip()
            if not line_str:
                continue
            try:
                c, lcx, lcy, lw, lh = parse_yolo_line(line_str)
            except ValueError:
                continue
            if not (0 <= c < len(ds.classes)):
                continue

            lbox = (lcx, lcy, lw, lh)
            max_iou = max([iou_xywh(lbox, (r[2], r[3], r[4], r[5])) for r in fp_preds], default=0.0)
            if max_iou < iou_missing:
                issues.append(Issue(
                    "second_opinion", WARN, "POSSIBLE_FALSE_POS", stem,
                    f"box nhãn không khớp dự đoán nào (max IoU={max_iou:.2f} < {iou_missing})",
                    line=line_idx, extra={"line": line_idx}
                ))

    return issues
