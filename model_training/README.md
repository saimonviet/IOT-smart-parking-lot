# Huấn luyện mô hình nhận diện ô trống / có xe

Mô hình phân loại từng ô đỗ (`empty` / `occupied`), dùng trong server qua `DETECTOR=classifier`.
Camera cố định và vị trí 12 ô đã biết, nên phân loại từng ô (cắt theo ROI) nhẹ và chính xác hơn phát hiện vật thể kiểu YOLO,
và không phụ thuộc vật trong ô có "giống xe thật" hay không.

## Dữ liệu: CNRPark+EXT

| Phần | Số ảnh | Dùng để |
|---|---|---|
| CNR-EXT train | 94.493 | huấn luyện |
| CNR-EXT val | 18.647 | chọn epoch, ngưỡng, nhiệt độ, Optuna |
| CNR-EXT test | 31.825 | đánh giá (các **ngày** khác hẳn train) |
| CNRPark A/B | 12.584 | đánh giá trên **camera chưa từng thấy** |

9 camera, 3 kiểu thời tiết (nắng / âm u / mưa), nhiều góc nhìn, có che khuất và bóng cây.
Nguồn: Amato et al., *Deep learning for decentralized parking lot occupancy detection*, Expert Systems with Applications, 2017
(http://cnrpark.it, bản lưu trữ của tác giả: github.com/fabiocarrara/deep-parking).

## Chạy

```powershell
cd model_training
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126   # GPU NVIDIA
pip install -r requirements.txt
python -m ipykernel install --user --name parking-train --display-name "Python (parking-train)"

python download_dataset.py     # ~500 MB vào data/
python build_cache.py          # gói ~157k ảnh vào data/cache/patches.bin (đọc nhanh hơn ~10 lần)
jupyter lab train_occupancy.ipynb     # chọn kernel "Python (parking-train)", Run All
```

> Môi trường `.venv`, dữ liệu và cache trên máy này đã được cài và tải sẵn.

**Trước khi train trên laptop:** cắm sạc và đặt Windows Power mode = *Best performance*. Lúc kiểm tra trên máy này,
GPU chỉ đạt ~120–220 ảnh/s (thấp hơn nhiều so với khả năng của RTX 3050 Ti, nhiều khả năng do đang tiết kiệm điện).
Ở tốc độ đó, chạy đủ notebook mất khoảng 3–4 giờ. Muốn nhanh hơn: giảm `final_epochs`, `trials` trong ô `CFG`,
hoặc chạy trên Google Colab.

Chạy thử nhanh để kiểm tra lỗi (vài phút, dữ liệu rất nhỏ, kết quả không có ý nghĩa): đặt `$env:SMOKE="1"` trước khi mở Jupyter.

Chạy không cần mở Jupyter:
```powershell
.\.venv\Scripts\jupyter.exe nbconvert --to notebook --execute train_occupancy.ipynb --inplace --ExecutePreprocessor.timeout=-1
```

## Train trên Kaggle (GPU miễn phí)

Không cần upload dữ liệu: ô đầu tiên của notebook tự tải CNRPark+EXT (~500 MB) từ GitHub.

1. **Bật Internet cho tài khoản**: kaggle.com → Settings → *Phone verification* (bắt buộc để notebook dùng GPU + Internet).
2. **Tạo Dataset chứa code**: *Create → New Dataset*, kéo thả `parking_lib.py` và `download_dataset.py`,
   đặt tên ví dụ `parking-code`, *Create*.
   Có ảnh xe mô hình tự thu thì nén thư mục `data/custom` (bên trong có `empty/`, `occupied/`) thành `custom.zip` và thả vào cùng Dataset.
3. **Tạo Notebook**: *Create → New Notebook → File → Import Notebook*, chọn `train_occupancy.ipynb`.
4. Trong notebook, panel bên phải:
   - *Input → Add Input* → chọn Dataset `parking-code` vừa tạo.
   - *Settings → Accelerator* = **GPU T4 x2** (notebook dùng 1 GPU; tránh P100, PyTorch bản mới không còn hỗ trợ).
   - *Settings → Internet* = **On**.
5. **Chạy**: *Save Version → Save & Run All (Commit)*. Notebook chạy nền trên máy chủ Kaggle (tối đa 12 giờ),
   có thể tắt trình duyệt. Muốn chạy thử nhanh trước: thêm ô `import os; os.environ["SMOKE"] = "1"` lên đầu rồi *Run All* trong phiên tương tác.
6. **Tải kết quả**: mở bản Version vừa chạy → tab *Output* → tải `models/occupancy.pt`, `models/occupancy.json`
   (chép vào `pc_server/models/`) và thư mục `results/` (biểu đồ, bảng).

Lưu ý:
- Kaggle chỉ có 4 nhân CPU nên `workers` tự giảm theo `os.cpu_count()`; tăng cường ảnh trên CPU thường là phần chậm nhất.
- Hạn mức GPU miễn phí ~30 giờ/tuần.
- "Tốc độ CPU (12 ô)" trong kết quả là đo trên CPU của Kaggle, không phải CPU máy chạy server.
- `occupancy.pt` là TorchScript: server nên dùng PyTorch cùng bản hoặc mới hơn bản trên Kaggle (in ở ô cấu hình).

## Notebook làm gì

1. **Khám phá dữ liệu**: số ảnh theo split / thời tiết / camera, kiểm tra không trùng ngày giữa các split, ảnh mẫu, ảnh tăng cường.
2. **Sàng lọc kiến trúc**: mAlexNet (baseline của bài báo gốc), MobileNetV3-Small/Large, EfficientNet-B0, ResNet18.
   Chọn theo F1 **và** thời gian CPU cho 12 ô.
3. **Optuna** (TPE + MedianPruner): learning rate, weight decay, label smoothing, dropout, warmup, batch size.
4. **Huấn luyện cuối**: AdamW, cosine + warmup, AMP fp16, EMA trọng số, early stopping theo val loss.
5. **Đánh giá**: accuracy / precision / recall / F1 / ROC-AUC / AP, ma trận nhầm lẫn, ROC & PR, hiệu chỉnh xác suất
   (ECE + temperature scaling), theo thời tiết và camera, camera chưa thấy, độ bền với nhiễu (sáng/tối, nhiễu, mờ,
   độ phân giải thấp, che khuất), ảnh sai tự tin nhất, Grad-CAM, tốc độ.
6. **Tinh chỉnh với xe mô hình** nếu có `data/custom/` (xem bên dưới).
7. **Xuất** `pc_server/models/occupancy.pt` (TorchScript) + `occupancy.json` (ngưỡng, nhiệt độ, metric).

Hình và bảng kết quả lưu trong `results/`.

## Dùng mô hình trong server

```powershell
cd pc_server
$env:DETECTOR="classifier"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Ghi đè ngưỡng nếu cần: `$env:CLASSIFIER_THRESHOLD="0.6"`.

## Tinh chỉnh với xe mô hình (rất nên làm)

Ảnh CNRPark là bãi xe thật chụp chéo từ trên cao; xe mô hình dưới Pi Camera trông khác nhiều. Thu vài trăm ảnh của chính bãi bạn:

```powershell
# đặt xe vào ô 1, 3, 5, 8 (ô khác để trống)
python collect_crops.py --url http://<ip-pi>:8081/snapshot.jpg --occupied 1,3,5,8 --frames 40
# đổi vị trí xe, ánh sáng... chạy lại vài lần; bãi trống hoàn toàn:
python collect_crops.py --url http://<ip-pi>:8081/snapshot.jpg --occupied "" --frames 20
```
Xem lại `data/custom/empty` và `data/custom/occupied`, xoá ảnh sai, rồi chạy lại notebook. Bước 6 sẽ tự tinh chỉnh
(trộn thêm 5k ảnh CNR-EXT để mô hình không quên) và báo kết quả trước/sau.

## Lưu ý về OneDrive

Thư mục `data/` (~157k file nhỏ) và `.venv` (vài GB) nằm trong OneDrive sẽ bị đồng bộ lên mây. Cách xử lý:
- Sau khi chạy `build_cache.py`, có thể **xoá** `data/CNR-EXT/PATCHES`, `data/CNRPark/A`, `data/CNRPark/B` và `data/raw`:
  notebook chỉ cần `data/cache/` + các file nhãn `data/CNR-EXT/LABELS`. Còn lại vài file lớn thay vì 157k file nhỏ.
- Không dùng "Free up space" cho `data/` hay `.venv` (file chuyển thành chỉ-trên-mây, đọc rất chậm hoặc lỗi).
- Tốt nhất: chuyển cả dự án ra ngoài thư mục OneDrive (ví dụ `C:\Projects\IOT_CKY`).

---

# Huấn luyện nhận diện biển số xe (ESP32-CAM ở cổng vào/ra)

Hai mô hình cho `pc_server/app/plates.py`: **YOLO phát hiện biển** (2 lớp `plate_1row` / `plate_2row`) và
**CRNN + CTC đọc ký tự**. Biển 2 dòng được cắt đôi theo chiều cao rồi ghép ngang trước khi đọc, nên một mô hình
đọc được cả biển dài lẫn biển vuông / xe máy.

## Dữ liệu

| Bộ | Số ảnh | Dùng cho | Nguồn |
|---|---|---|---|
| VNLP | ~37.300 (19k biển 1 dòng, 18k biển 2 dòng) | phát hiện (lấy 9k) + **OCR** (nhãn chữ trong tên file) | github.com/fict-labs/VNLP — Trinh et al. MAPR 2022; Pham, The Visual Computer 2023 |
| LP_detection | ~8.300 ảnh đường phố | phát hiện (đa dạng bối cảnh) | github.com/trungdinh22/License-Plate-Recognition |
| Biển tổng hợp | sinh mới 40k/epoch | OCR (đủ định dạng, nền trắng/vàng, giả lập ảnh ESP32 nhỏ/mờ) | font + nền của github.com/NNDam/Vietnamese-License-Plate-Generator |

Chia train/val/test **theo biển số** (cùng một xe không nằm ở cả train và test). Các bộ dữ liệu không ghi giấy phép
rõ ràng — chỉ dùng cho học tập/nghiên cứu và trích dẫn nguồn trong báo cáo.

## Chạy

```powershell
cd D:\model_training
.\.venv\Scripts\Activate.ps1
pip install ultralytics gdown          # (đã cài sẵn trên máy này)
python prepare_plates.py               # tải ~4 GB, tạo data/plates/det + data/plates/ocr (~1.5 GB). --cleanup để xoá zip
jupyter lab train_plate.ipynb          # Run All (~3–5 giờ trên RTX 3050 Ti). Chạy thử nhanh: $env:SMOKE="1"
```
Không mở Jupyter: `python -m nbconvert --to notebook --execute train_plate.ipynb --inplace --ExecutePreprocessor.timeout=-1`

Notebook: sàng lọc YOLO11n / YOLO26n / YOLO11s (mAP + tốc độ CPU) → train đầy đủ mô hình được chọn → đánh giá test,
độ bền (ảnh nhỏ, mờ, tối, nén JPEG) → train CRNN (thật + tổng hợp, AMP, OneCycle, dừng sớm) → độ chính xác cả biển,
CER, theo 1 dòng / 2 dòng, ngưỡng tin cậy → đánh giá toàn pipeline như server → xuất
`plate_det.pt`, `plate_ocr.pt` (TorchScript), `plate_ocr.json` và **tự chép vào `pc_server/models/`**.
Trên dashboard: *Thiết bị → Camera biển số → Nạp lại mô hình* (không cần khởi động lại server).

Sửa notebook: chỉnh `make_plate_notebook.py` rồi `python make_plate_notebook.py` (sinh lại `train_plate.ipynb`).

## Xe mô hình: in biển + tinh chỉnh (rất nên làm)

Biển trên xe đồ chơi chụp bằng ESP32-CAM rất nhỏ và khác ảnh bãi xe thật:

```powershell
python print_plates.py --random 12 --width-mm 40          # data/plates/print/bien_so_A4.png, in 100% (300 dpi), dán lên xe
python collect_plates.py --url http://<ip-esp32> --key <CAM_KEY> --count 30 --label 51G12345   # đặt từng xe ở cổng
```
`collect_plates.py` lưu ảnh gốc + biển đã cắt vào `data/plates/custom/` và ghi `labels.csv`
(không truyền `--label` thì tự đoán bằng OCR hiện tại → **mở file sửa lại nhãn**). Chạy lại notebook: ảnh tự thu được
trộn vào train OCR (nhân 5). Muốn tinh chỉnh cả YOLO, gán khung cho `data/plates/custom/frames` (vd. bằng Roboflow /
CVAT, xuất YOLO) rồi chép vào `data/plates/det/images|labels/train`.
