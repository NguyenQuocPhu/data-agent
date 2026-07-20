# Design: Dọn rác + SOLIDify + Persona core độc lập tập data

**Date:** 2026-07-20
**Status:** Approved (design), pending implementation plan
**Author:** Le Minh Quan + Claude

## 1. Bối cảnh & vấn đề

POC phân tích persona churn telco (FTEL, tập `data_processed_t4.csv`) đã xong. Repo hiện
tại có hai vấn đề cần xử lý cùng lúc:

1. **Rác POC:** root repo đầy artifact dùng-một-lần — hàng chục PNG, model `*.pkl/*.joblib`,
   log, HTML report, script `test_*.py` one-off, và ~468MB CSV (`data_RM6T*.csv`). Ngoài ra
   có nhiều subsystem song song không còn tham chiếu.
2. **Khóa cứng vào tập churn/telco:** persona engine (`triadic_dgm/`) về mặt chat tương tác
   đã generic (tự chọn feature theo CSV upload), nhưng **convergence loop + report + prompts**
   thì hardcode telco/churn ở nhiều chỗ:
   - `FIXED_BEHAVIORAL_FEATURES` (danh sách cột telco cố định) trong `convergence_runner.py`.
   - Luật `_CHURN_DRIVER_RULES` / `_classify_churn_driver_from_stars` / `_DOMAIN_KEYWORD_GROUPS`
     (nhóm domain đặt tên telco) trong `convergence_runner.py`.
   - `data_processed_t4_metadata.json` ở root, nạp cứng lúc import trong `persona_json.py`;
     kèm `LOYALTY_RANK` tier labels, `PROFILE_ATTR_LABELS`.
   - Từ vựng churn (`POST_CHURN`, "rời mạng", business-insight maps, tier display) trong
     `report_generator.py` (131KB god-file).
   - Cột DB `churn_driver` trong `convergence_store.py`.
   - `prompts.py` (130KB) chứa kiến thức telco/churn nướng sẵn.

**Xác nhận từ code:** convergence loop KHÔNG hardcode đường dẫn CSV — nó tự lấy file tabular
đầu tiên trong `workspace/convergence/index.json`. Nên việc "đổi dataset" đã khả thi ở tầng
nạp file; cái còn khóa cứng là *ngữ nghĩa* (feature/domain/nhãn/driver/từ vựng).

## 2. Mục tiêu & phi-mục-tiêu

**Mục tiêu:**
- Persona engine **thuần unsupervised**: khám phá & mô tả persona từ hành vi, KHÔNG có khái
  niệm target/outcome. "driver" trở thành "dấu hiệu phân biệt nổi bật của cụm" (generic).
- **Auto-infer, zero config:** thêm dataset mới chỉ cần thả CSV vào workspace — không viết
  file config per-dataset, không sửa code.
- Giữ tính **"hội tụ"** (reproducibility) của convergence cho *bất kỳ* dataset.
- Repo `main` sạch; lịch sử POC được bảo toàn qua archive.
- Cấu trúc SOLID: tách god-file, mỗi module một trách nhiệm, phụ thuộc qua interface.

**Phi-mục-tiêu (YAGNI):**
- KHÔNG giữ chế độ phân tích churn riêng / target column (đã chốt: thuần unsupervised).
- KHÔNG hệ thống profile/adapter viết tay per-dataset (đã chốt: auto-infer hoàn toàn).
- KHÔNG refactor `dgm_agent_v2/`, `evolution_dgm/`, `langgraph_agent/` (giữ nguyên, không đụng).
- KHÔNG đụng `api/` routers hay `ui/` ngoài phần cần thiết để wire `DatasetProfile`.

## 3. Quyết định thiết kế (đã chốt với user)

| Chủ đề | Quyết định |
|--------|-----------|
| Onboard dataset mới | Auto-infer hoàn toàn từ CSV + metadata tự sinh; không config per-dataset |
| Reproducibility convergence | Suy feature 1 lần rồi **freeze/cache theo dataset fingerprint** |
| Khái niệm outcome/target | Bỏ hẳn — pipeline thuần unsupervised; `churn_driver` → `distinguishing_signal` generic |
| Dead code archive | `triadic_dgm/benchmark/`, `Understand-Anything/`, `LAMBDA.py` (giữ dgm_agent_v2, evolution_dgm, langgraph_agent) |
| Cách dọn | Tạo git tag/branch `archive/poc` rồi xoá khỏi `main` + gitignore artifact |

## 4. Kiến trúc đích

### 4.1 `DatasetProfile` — object auto-inferred tại load-time

Trái tim của việc tách cứng. KHÔNG phải config viết tay; được **sinh tự động** từ CSV + metadata
json (đúng metadata mà path EDA/chat đã tạo mỗi lần upload). Là data object bất biến, truyền
vào các tầng dưới (Dependency Inversion — convergence_runner phụ thuộc `DatasetProfile`, không
phụ thuộc dict telco).

Nội dung:
- `labels: dict[col → nhãn người-đọc]` — từ metadata, ngôn ngữ nào cũng được.
  → thay `FEATURE_LABELS`, `PROFILE_ATTR_LABELS`, `LOYALTY_RANK` tier labels, `_FEATURE_METADATA_PATH`.
- `behavioral_features: list[str]` — tự chọn numeric columns (loại ID/thời gian/hằng số/near-constant).
  → thay `FIXED_BEHAVIORAL_FEATURES`.
- `domains: dict[domain_name → list[col]]` — tự nhóm cột từ metadata/tên cột bằng heuristic
  generic (KHÔNG đặt tên telco như "complaint"/"call"). Ví dụ nhóm theo prefix/tương quan.
  → thay `_DOMAIN_KEYWORD_GROUPS`.
- `fingerprint: str` — hash(cột đã sort + n_rows). Khóa cache freeze.

**Freeze/cache:** lần convergence run đầu cho một dataset, chạy feature-selection một lần rồi
persist `behavioral_features` + scaler + domains vào `cache/convergence/profiles/<fingerprint>.json`.
Run sau nạp lại profile đã khóa → cùng feature space → KMeans (cùng random_state) học ranh
giới ổn định → convergence hội tụ. Cơ chế này thay việc hardcode `FIXED_BEHAVIORAL_FEATURES`
mà vẫn đúng cho mọi dataset.

### 4.2 Đặc trưng cụm generic — `distinguishing_signal`

Thay `_classify_churn_driver_from_stars` + `_CHURN_DRIVER_RULES`:
- Với mỗi cụm: tính lệch tương đối từng feature vs global mean → chấm sao theo domain (giữ
  thang star hiện có, nhưng domain là generic từ `DatasetProfile.domains`).
- Kết quả `signature = {dominant_domain, stars_per_domain, top_features, evidence}` — mô tả
  cụm nổi bật ở nhóm hành vi nào, bằng nhãn của chính dataset. Không từ vựng churn.

### 4.3 Narrative / report generic

- Narrative mô tả persona theo `signature` + `DatasetProfile.labels`, ở ngôn ngữ của metadata.
  Bỏ map `POST_CHURN` / telco business-insight.
- Tách `report_generator.py` (131KB) và `prompts.py` (130KB) thành package
  `triadic_dgm/persona/`:
  - `dataset_profile.py` — build & cache `DatasetProfile`.
  - `characterization.py` — tính `signature` (SRP).
  - `narrative.py` — sinh narrative generic (deterministic fallback + LLM).
  - `report.py` — lắp report từ các phần trên.
  - Mỗi module hiểu độc lập, test độc lập.

### 4.4 Prompt độc lập dataset (rủi ro cao nhất → làm cuối)

- Persona-generation prompt nhận **metadata + nhãn cột** làm input động, thay vì kiến thức
  telco nướng sẵn. Trích phần churn/telco ra khỏi template; parameterize theo `DatasetProfile`.

### 4.5 Lưu trữ

- DB `personas.churn_driver` → `signature` (TEXT). Migration an toàn: `ALTER TABLE` thêm cột
  mới, backfill từ cột cũ nếu tồn tại, giữ tương thích DB cũ (giống pattern migration
  `persona_fingerprint` đã có trong `convergence_store.py`).

## 5. Kế hoạch phân pha

| Phase | Nội dung | Rủi ro |
|-------|----------|--------|
| 0 | Dọn rác: tag/branch `archive/poc`, xoá dead code + artifact khỏi `main`, cập nhật `.gitignore` | Thấp |
| 1 | `DatasetProfile` (auto-infer + freeze/cache); wire `persona_json` + `convergence_runner`; bỏ `FIXED_BEHAVIORAL_FEATURES` & metadata-path hardcode | Trung bình |
| 2 | `distinguishing_signal` thay `churn_driver`; migration DB cột `signature` | Trung bình |
| 3 | Narrative/report generic; tách god-file thành package `triadic_dgm/persona/` | Cao (nhiều dòng) |
| 4 | Prompt độc lập dataset | Cao |

Mỗi phase độc lập chạy được và có test; có thể dừng giữa chừng mà hệ thống vẫn hoạt động.

## 6. Chi tiết dọn rác (Phase 0)

**Archive trước khi xoá:** `git tag archive/poc-2026-07 && git branch archive/poc` (chụp
nguyên trạng).

**Xoá khỏi `main`:**
- Subsystem: `triadic_dgm/benchmark/`, `Understand-Anything/`, `.understand-anything/`, `LAMBDA.py`.
- Artifact root: `*.png`, `*.pkl`, `*.joblib`, `*.log`, `data_RM6T*.csv` (~468MB), HTML report
  (`bao-cao-persona-churn-t4-2026.html`, `pipeline_flow.html`), `test_*.py` one-off ở root,
  `app_compile/`, `tutorials/`, các CSV trung gian (`intermediate_features.csv`,
  `persona_analysis_with_text.csv`).

**Giữ nguyên:** `dgm_agent_v2/`, `evolution_dgm/`, `langgraph_agent/`, `api/`, `ui/`, `utils/`,
`triadic_dgm/` (trừ benchmark), `data_demo_golden.csv` (fixture test), `config*.yaml`.

**`.gitignore` bổ sung:** `*.png`, `*.pkl`, `*.joblib`, `*.log`, `cache/`, `workspace/`,
`data_*.csv` (whitelist `data_demo_golden.csv` nếu muốn giữ tracked), `*.html` report tạm.

## 7. Kiểm thử & nghiệm thu

- `pytest tests/` xanh sau mỗi phase.
- **Test generalize (nghiệm thu chính):** chạy pipeline trên `data_demo_golden.csv` (khác
  telco) → sinh persona hợp lý, `DatasetProfile` auto-infer đúng, KHÔNG lỗi thiếu cột telco.
- **Test reproducibility:** chạy convergence ≥3 lần trên cùng dataset → cùng feature set
  (đã freeze) → số cụm & fingerprint ổn định.
- Không còn tham chiếu `data_processed_t4_metadata.json` / `FIXED_BEHAVIORAL_FEATURES` /
  `churn_driver` trong code path persona (grep sạch).

## 8. Rủi ro & giảm thiểu

- **Convergence mất ổn định khi bỏ fixed features** → cơ chế freeze/cache per-fingerprint
  (4.1) tái lập đúng tính chất đã khiến telco hội tụ.
- **Prompt generic ra chất lượng kém hơn telco chuyên biệt** → làm cuối (Phase 4), có test
  so sánh; giữ deterministic fallback trong `narrative.py`.
- **God-file tách ra làm vỡ import** → tách từng bước, chạy `pytest` + smoke test API sau mỗi
  lần di chuyển; giữ shim tương thích tạm nếu cần.
- **Migration DB cột `churn_driver`** → theo pattern ALTER an toàn đã có; DB POC cũ có thể bỏ.
