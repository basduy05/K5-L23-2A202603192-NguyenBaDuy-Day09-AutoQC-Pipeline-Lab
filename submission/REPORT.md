# Báo cáo Day 09 — Nguyễn Bá Duy, 2A202603192

## 1. Kết luận trước
Pipeline kết luận: **HOLD**.
- **Số lượng ảnh đầu vào**: 224 ảnh raw (quét qua bước Intake: chấp nhận **203/224** ảnh, loại bỏ **21** ảnh hỏng, quá nhỏ, trùng lặp hoặc rò rỉ từ tập test/val).
- **Số lượng ảnh xuất ra dataset**: **203** ảnh tại `submission/export/clean_v1/`.
- **Lý do chính**: Tỉ lệ ảnh có cảnh báo là **21.67%** (44/203 ảnh), vượt ngưỡng cho phép `warn_ratio_hold = 10.00%`. Sau bước sửa tự động và người duyệt theo ngân sách 80 ảnh, pipeline đã khắc phục hoàn toàn 100% lỗi bắt buộc (0 lỗi ERROR), nhưng do ngân sách duyệt giới hạn (80/130 ảnh trong hàng đợi) nên vẫn còn 44 ảnh mang cảnh báo ngữ nghĩa chưa được thẩm định. Do đó, dataset được xuất dưới dạng **bản nháp thử nghiệm (HOLD)**, chưa đủ điều kiện để phát hành chính thức (Release).

## 2. Lỗi và phân việc
Dưới đây là bảng thống kê lỗi từ `02_error_list_v1` (gom theo từng mã lỗi thực tế xuất hiện trong lô dữ liệu):

| Mã lỗi | Số ảnh/dòng | Ai sửa (máy/người) | Vì sao |
|---|---:|---|---|
| `CORRUPT_IMAGE` | 2 ảnh | Máy (autofix) | Ảnh bị hỏng cấu trúc file (`UnidentifiedImageError`, `OSError`), máy xoá an toàn. |
| `BAD_SIZE` | 3 ảnh | Máy (autofix) | Kích thước cạnh ngắn $< 250\text{px}$, không đạt chuẩn kích thước tối thiểu của dự án. |
| `DUP_IMAGE_EXACT` | 8 ảnh | Máy (autofix) | Trùng từng byte (md5) với ảnh đã giữ trước đó, máy loại bỏ ảnh trùng lặp. |
| `DUP_IMAGE_NEAR` | 3 ảnh | Máy (autofix) | Trùng gần đúng qua perceptual hash ($\text{phash} \le 8$), máy loại bỏ để tránh thiên lệch. |
| `LEAK_TEST` | 5 ảnh | Máy (autofix) | Trùng với ảnh trong kho tham chiếu (`data/test`, `data/gold_val`), loại bỏ để chống rò rỉ dữ liệu. |
| `BAD_CLASS_NAME` | 2 dòng | Máy (autofix) | Sai quy chuẩn tên lớp trong `data.yaml` ('Person' $\rightarrow$ 'person', 'Bus' $\rightarrow$ 'bus'), máy chuẩn hoá lại. |
| `BAD_FORMAT` | 3 dòng | Máy (autofix) | Dòng nhãn sai cú pháp (thiếu cột hoặc chứa giá trị `NaN`/`Inf`), máy xoá dòng lỗi. |
| `BAD_CLASS_ID` | 6 dòng | Máy (autofix) | Class ID ngoài phạm vi 0..3 (ví dụ ID 93, -1, 4, 7), máy xoá dòng lỗi. |
| `BOX_ZERO` | 4 dòng | Máy (autofix) | Box có chiều rộng hoặc chiều cao $\le 0$, máy xoá dòng lỗi. |
| `DUP_BOX` | 7 dòng | Máy (autofix) | Cùng lớp và trùng lặp vị trí ($\text{IoU} > 0.9$) với box xuất hiện trước, máy xoá dòng xuất hiện sau. |
| `BOX_OUT_OF_IMAGE` | 8 dòng | Máy (autofix) | Box tràn khỏi biên ảnh $> 0.002$, máy tự động cắt (clip) mép box về trong đoạn $[0, 1]$. |
| `MISSING_LABEL_FILE` | 6 ảnh | Người (hàng đợi) | Ảnh hoàn toàn chưa có file nhãn; máy không thể tự bịa nhãn nên chuyển người gán mới. |
| `EMPTY_LABEL` | 12 ảnh | Người (hàng đợi) | File nhãn rỗng; người cần xem để xác nhận đây là ảnh nền (background) hay bị thiếu nhãn. |
| `BOX_TINY` | 6 dòng | Người (hàng đợi) | Cạnh ngắn $< 12\text{px}$; người cần kiểm tra vật quá nhỏ có cần gán theo guideline không. |
| `BOX_HUGE` | 3 dòng | Người (hàng đợi) | Diện tích $> 0.95$; người cần kiểm tra box có bị gán bao trùm cả khung cảnh không. |
| `CLASS_RARE` | 4 lần | Người (hàng đợi) | Cảnh báo mất cân bằng dữ liệu khi lớp xuất hiện quá ít box trong lô. |
| `POSSIBLE_WRONG_CLASS` | 18 lần | Người (hàng đợi) | Nhãn người gán khác lớp so với dự đoán của model checker lớn (`yolo26l`). |
| `POSSIBLE_LOOSE_BOX` | 31 lần | Người (hàng đợi) | Nhãn cùng lớp với model nhưng $\text{IoU} < 0.5$ (box bị lỏng/lệch tâm). |
| `POSSIBLE_MISSING` | 68 lần | Người (hàng đợi) | Model `yolo26l` phát hiện vật thể rõ ràng nhưng trong nhãn chưa có box. |
| `POSSIBLE_FALSE_POS` | 29 dòng | Người (hàng đợi) | Box nhãn nằm ở vùng nền mà model không nhận diện được bất kỳ vật thể nào. |

**Giải thích cơ chế hàng đợi duyệt (`05_review_queue.csv`)**:
Hàng đợi ưu tiên xếp các ảnh có điểm số nguy cơ cao nhất lên đầu dựa trên trọng số cấu hình:
- Các ảnh dính lỗi `NEEDS_LABEL` (trọng số 10) và vừa có dòng bị xoá `FIXED_DROP_LINE` (2.0) vừa dính `POSSIBLE_WRONG_CLASS` (3.0) + `POSSIBLE_MISSING` (2.0) được ưu tiên tuyệt đối ở top đầu (điểm từ 10.0 đến 14.5).
- Với ngân sách 80 ảnh, người duyệt mô phỏng đã xem và xử lý được 80 ảnh có rủi ro cao nhất, giải quyết triệt để 6 ảnh thiếu nhãn bắt buộc và phần lớn các lỗi gán nhầm lớp nghiêm trọng. Tuy nhiên, do tổng số ảnh có cảnh báo là 130 ảnh, ngân sách 80 ảnh còn thiếu 50 ảnh để duyệt hết toàn bộ các cảnh báo ngữ nghĩa còn lại.

## 3. Calibration (2 ngưỡng)
Bảng kết quả trước và sau khi thực hiện calibration trên tập dữ liệu chuẩn `data/calib/`:

| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | **8** | DUP_IMAGE_NEAR: (1.00 / 0.50) → **(1.00 / 0.67)**, F1: 0.67 → **0.80** | Ngưỡng 2 quá khắt khe, bỏ sót các ảnh bị crop/resize nhẹ. Tăng lên 8 giúp Recall tăng lên 67% mà vẫn giữ Precision tuyệt đối 100%. |
| `second_opinion.conf` | 0.25 | **0.50** | POSSIBLE_MISSING: (0.50 / 1.00) → **(0.57 / 1.00)**, F1: 0.67 → **0.73** | Ngưỡng 0.25 sinh nhiều báo động giả (Precision chỉ 0.50). Nâng lên 0.50 giúp tăng độ chính xác của cảnh báo lên 57% trong khi vẫn giữ trọn vẹn 100% Recall (không bỏ sót lỗi). |

**Một chỗ calibration có thể đánh lừa bạn**:
Tập calibration `data/calib/` chỉ có quy mô nhỏ gồm **39 ảnh** với các lỗi được chèn nhân tạo theo kịch bản có sẵn. Trong bảng sweep, nếu ta chọn `phash_dist = 16` thì trên tập calib Recall đạt tới 83% mà Precision vẫn hiển thị 1.00. Tuy nhiên, đây là điểm đánh lừa (overfitting vào tập calib nhỏ): khi áp dụng vào tập dữ liệu thực tế gồm 224 ảnh, các góc chụp ngoại cảnh tương đồng nhau (ví dụ các xe ô tô đỗ ven đường ở cùng một góc phối cảnh) sẽ có khoảng cách Hamming nhỏ hơn 16 và bị thuật toán coi là ảnh trùng lặp, dẫn tới việc xoá nhầm ảnh hợp lệ. Do đó, việc giữ ngưỡng an toàn ở mức **8** là quyết định bảo toàn dữ liệu thật.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
**(a) Chứng minh cửa chặn Gate hoạt động chính xác**:
Thực hiện thí nghiệm với kịch bản không có người duyệt (`--budget 0`):
```powershell
python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb
```
- **Kết quả**: Pipeline phát hiện còn 6 lỗi bắt buộc `MISSING_LABEL_FILE` chưa được xử lý. Cửa chặn Gate lập tức ra kết luận:
  `kết luận: REWORK — Còn 6 lỗi bắt buộc (severity error) cần sửa trước khi phát hành.`
- Mã thoát trả về là **20** và bước xuất dữ liệu bị huỷ hoàn toàn:
  `Bước 5/5 KHÔNG xuất: còn lỗi bắt buộc (Rework) — trả về bước 3`. Thư mục `work/exp_nb/clean_v1` hoàn toàn không tồn tại. Điều này chứng minh cửa chặn hoạt động chặt chẽ, không bao giờ phát hành dữ liệu khi còn lỗi bắt buộc.

**(b) Hai điểm mù pipeline KHÔNG bắt được**:
1. **Vật thể bị che khuất một phần hoặc góc khuất (Occlusion)**: Khi một chiếc xe bị khuất 80% sau cây cối hoặc toà nhà, cả người gán nhãn lẫn model checker `yolo26l` đều không đủ tự tin để phát hiện (conf $< 0.10$). Cả hai bên cùng bỏ sót, dẫn đến việc lỗi này hoàn toàn vô hình trước pipeline.
2. **Box bị lệch/lỏng nhẹ nhưng IoU vẫn $\ge 0.50$**: Quy tắc của `second_opinion` chỉ cảnh báo `POSSIBLE_LOOSE_BOX` khi $\text{IoU} < 0.50$. Nếu annotator vẽ một box rộng hơn vật thể khoảng 15–20% khiến IoU đạt mức 0.55–0.60, model vẫn đánh giá là khớp tốt và bỏ qua, dù box đó trên thực tế chưa đạt độ khít tối ưu.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)
Chưa chạy trên Google Colab do môi trường máy cá nhân không có card đồ hoạ rời (GPU) và tập trung hoàn thiện 100% độ tin cậy của pipeline kiểm soát chất lượng nhãn cùng bộ test tự động.

## 6. Quyết định và ghi chú AI
**(a) Quyết định cuối cùng**:
- Quyết định hiện tại của lô dữ liệu là **HOLD**.
- **Điều kiện để chuyển thành RELEASE**: 
  1. Tăng ngân sách người duyệt từ 80 ảnh lên ít nhất **130 ảnh** để duyệt toàn bộ các cảnh báo còn lại trong hàng đợi.
  2. Hoặc nếu theo guideline dự án đánh giá các cảnh báo còn lại là chấp nhận được trong ngưỡng nhiễu, quản lý dự án có thể phê duyệt nới lỏng `warn_ratio_hold` lên mức 25% để phát hành bản clean_v1 phục vụ huấn luyện thử nghiệm.

**(b) Ghi chú sử dụng AI**:
- **Prompt chính**: *"Phân tích kiến trúc Day 09 AutoQC, lập trình 4 module (label_format, gate, autofix, second_opinion) theo chuẩn TDD, đảm bảo xử lý triệt để các ca biên về dòng trống, thứ tự ưu tiên drop_line và không sửa đổi các file mẫu đã được bảo vệ."*
- **Cách kiểm tra code AI**: Chạy bộ unit test độc lập cho từng module (`pytest tests/test_<module>.py -q`), chạy bài test tích hợp E2E (`test_pipeline_e2e.py`), và đối chiếu sha1 với `_protected.json`.
- **Một lần AI sai**: Khi chạy kiểm tra bài nộp trên Windows, công cụ `check_submission.py` so sánh đường dẫn dạng chuỗi bị lệch dấu gạch chéo (`pipeline\calibrate.py` thay vì `pipeline/calibrate.py`), AI đã phát hiện và chuẩn hoá đường dẫn với `.as_posix()`.

---

### *(Thưởng +2, tùy chọn)* CVAT: Lọc box bất thường
- **Thực hành lọc box nhỏ**:
  Trên giao diện CVAT, mở task với ảnh từ `work/run/ds/images/` (ví dụ `img_0001`), mở công cụ **Filters** và thêm rule: `width < 20` (hoặc `height < 20`).
- **Đối chiếu với Pipeline**:
  Bộ lọc CVAT phát hiện chính xác các box có kích thước nhỏ li ti (ví dụ người đứng ở hậu cảnh xa). Kết quả này khớp hoàn toàn với các dòng cảnh báo `BOX_TINY` do pipeline sinh ra (pipeline sử dụng ngưỡng cạnh ngắn $< 12\text{px}$, trong khi quy tắc lọc nhanh trên CVAT dùng 20px).
- **Ý nghĩa của thuộc tính `can_review`**:
  Trong CVAT, thuộc tính `can_review = true` được annotator đánh dấu khi gặp các trường hợp mập mờ, tranh chấp (vật thể bị che khuất, hình dáng không rõ nét) để chuyên viên kiểm duyệt cấp cao (QC Reviewer) xem xét lại. Trong pipeline tự động, cơ chế này tương đương với việc model gắn cờ cảnh báo `WARN` (`POSSIBLE_LOOSE_BOX`, `POSSIBLE_WRONG_CLASS`, `POSSIBLE_MISSING`) kèm điểm số ưu tiên trong `05_review_queue.csv` để đưa vào ngân sách xem xét của con người.
