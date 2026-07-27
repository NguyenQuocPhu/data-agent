# Nhật ký thay đổi prompt

Theo `CLAUDE.md`: mọi thay đổi system prompt của Persona Agent phải ghi lại version và lý do,
để giữ vết thực nghiệm.

---

## 2026-07-27 — `PROGRAMMER_PROMPT_V2`: gỡ định danh dataset khỏi prompt tĩnh

**Lý do.** Người dùng upload một dataset bán lẻ 17 cột (Olist) và model sinh ra
`behavioral_features = ['cl_total_6m', 'cl_avg_6m', ...]` rồi chết vì
`ValueError: No valid behavioral features found`. Model không bịa — nó lặp lại những gì
prompt đã nói với nó về dữ liệu.

Prompt tĩnh được gửi cho **mọi** dataset, nên bất kỳ định danh nào trong đó đều là khẳng
định sai với mọi dataset không phải telco.

**Đã đổi.**

| Trước | Sau | Vì sao |
|---|---|---|
| `*** FTEL BUSINESS POC — COMPREHENSIVE CLUSTERING (V3: TIME-SERIES 113 COLUMNS) ***` | `*** PERSONA CLUSTERING PIPELINE ***` | Nêu tên khách hàng **và** số cột. Đây là dòng đầu tiên model đọc; một dataset 17 cột bị bảo rằng nó có 113 cột, và model tự "bù" phần thiếu bằng schema telco. |
| `nếu dataset KHÔNG CÓ cột doanh thu (cuoc_hang_thang) và/hoặc cột nhãn (RMDT), TUYỆT ĐỐI KHÔNG hardcode ARPU = 609,620 … KHÔNG dùng CTBDV làm proxy (như CTBDV * 2)` | Diễn đạt lại không nêu tên cột, không nêu con số | Quy tắc chống ảo giác lại **cung cấp** chính con số nó cấm: `609,620` không tồn tại ở đâu khác trong hệ thống. Ba tên cột telco đi kèm cũng vậy. |
| `LOẠI BỎ ID, Địa lý và Cước khi train` | `LOẠI BỎ … cột định danh, cột địa danh/mã vùng, và các cột đơn giá/doanh thu — nhận biết qua ngữ nghĩa tên cột CỦA CHÍNH DATASET NÀY` | "Cước" là khái niệm telco. Ý định (bỏ ID/địa lý/giá khỏi feature) đúng và được giữ, chỉ diễn đạt theo ngữ nghĩa thay vì theo miền. |
| `churn driver (chỉ khi POST_CHURN)` | `` `churn_driver` (CHỈ sinh ra khi dataset_mode = POST_CHURN; dataset khác không có field này) `` | `churn_driver` là tên field thật do `profiling.classify_churn_driver` sinh, nên hợp lệ — nhưng phải viết như định danh có điều kiện, không phải một khái niệm mặc định có. |

**KHÔNG đổi.** `PRE_CHURN` / `POST_CHURN` giữ nguyên: đó là dataset mode mà pipeline tự chọn
từ cột thực tế, không phải giả định về dữ liệu.

**Bảo vệ.** `tests/test_prompt_invariant.py` — bốn test mới. Danh sách cột telco trong test cũ
đã được mở rộng: nó vẫn xanh trong khi prompt vẫn nêu tên một dataset, vì danh sách thiếu
đúng những định danh đang rò. Thêm test `test_churn_appears_only_as_a_pipeline_mode` phân biệt
mode name hợp lệ với "churn" trần.

### Hai nguồn rò rỉ lớn hơn, nằm ngoài prompt tĩnh

Prompt chỉ là nguồn nhỏ nhất trong ba. Cả ba đều ở `api/routers/chat.py`, và cả ba đều nối
thêm text vào context của model mà không đối chiếu với dataset đang phân tích.

**1. Từ điển dữ liệu telco (nguồn chính).** Route glob `/app/*metadata*.json` — tức thư mục
gốc repo — rồi nhét nguyên nội dung kèm câu "Hãy tham khảo và **tuân thủ chặt chẽ** metadata
sau đây cho dữ liệu". Ở gốc repo có `data_processed_t4_metadata.json`: **11,8 KB từ điển dữ
liệu telco**, mô tả 94 cột gồm `cl_total_6m` ("Tổng số Yêu cầu hỗ trợ kĩ thuật (CL) trong 6
tháng"), `cl_avg_6m`, `complaint_total_6m`, `fee_total`, `OBJID`, `LOYALTY_RANK`. Nó được nhét
vào **mọi** phiên chat bất kể người dùng upload gì. Đây chính là nơi
`behavioral_features = ['cl_total_6m', 'cl_avg_6m', ...]` sinh ra; lời model tự ghi trong
trace — *"based on metadata provided"* — là đúng nghĩa đen.

`api/services/metadata_gate.py` (mới) chỉ nhét từ điển khi các cột nó mô tả **thật sự có**
trong dataset đang phân tích (ngưỡng giao nhau 50%). Cố ý là phép thử **khớp schema**, không
phải phép thử từ vựng: một từ điển sai không phải vì nó thuộc miền telco, mà vì nó mô tả
những cột không tồn tại — nên cùng cổng này cũng bảo vệ dataset thứ ba khỏi từ điển của
dataset thứ hai. Không xác minh được cột (peek lỗi, chưa upload gì) thì **không nhét**: đó
đúng là trạng thái đã gây ra lỗi, và im lặng chỉ khiến model mất phần mô tả — nó vẫn có
dataframe thật trong tay. Xem `tests/test_metadata_injection_gate.py`.

**2. Luật RIMRULE.** Dòng 166: 5 luật điểm MDL cao nhất được tiêm nguyên văn khi câu hỏi nhắc
tới phân cụm. 83/284 luật trong archive nêu định danh telco, và 2 trong 5 luật được chọn
khẳng định dữ liệu có `RMDT` và ARPU — một luật còn nêu đích danh tên công ty (FTEL).
`retrieve_rules_symbolic()` giờ nhận `active_columns` và loại các luật thuộc miền telco khi
dataset không phải telco — lọc **trước** khi cắt `top_k`, vì luật telco ngắn nên điểm MDL cao
và sẽ chiếm hết slot, để lại cho người dùng 3 luật thay vì 5.
Xem `tests/test_rule_injection_generic.py`.

**3. Ví dụ cột phân loại.** Khối "Anti-Hallucination for Categorical Data" hardcode cột
`khu_vuc` và các giá trị `'Vung Tau'`/`'Binh Duong'`. Đã viết lại không nêu tên cột.

---

## 2026-07-27 (lần 2) — `PROGRAMMER_PROMPT_V2`: cấm cắt phân tích thành nhiều lượt

**Lý do.** Lộ ra ngay sau khi bịt rò rỉ telco: luồng chạy được xa hơn trước nên gặp lỗi kế
tiếp. Model gửi một khối code load dữ liệu → chốt `behavioral_features` → lưu
`intermediate_features.csv` rồi **dừng**, không gọi `run_persona_pipeline`. Người dùng nhận
`[LLM ERROR: Total support must be greater than 0]` trên một lần chạy mà phân cụm hoàn toàn
làm được (chạy pipeline trực tiếp trên đúng file đó: 4 persona, k=4, silhouette 0.426).

Nguyên nhân là hai câu trong prompt đọc ghép lại thành nghĩa thứ ba:

- đầu prompt: *"You must **wait** for the actual execution result from the Sandbox"*
- mục 3b: *"chỉ cần gõ ĐÚNG đoạn dưới đây và **DỪNG**"* — ý gốc là *đừng chép lại 800 dòng
  hàm ở mục 4*, nhưng model hiểu thành *viết xong khối này thì dừng lượt, chờ kết quả rồi
  viết tiếp*.

Không có lượt tiếp theo: tầng báo cáo chạy ngay sau lần thực thi.

**Đã đổi.** Bỏ chữ "và DỪNG". Thêm ràng buộc **MỘT KHỐI CODE DUY NHẤT, KHÔNG CHIA LƯỢT** đi
trọn từ load → feature → `run_persona_pipeline` → in JSON, kèm nói rõ lệnh "chờ kết quả
sandbox" chỉ có nghĩa *không được bịa kết quả khi chưa chạy*.

**Bảo đảm cứng đi kèm** (vì prompt chỉ là soft steering). `ReportValidator.validate` từng
dùng `assert total_customers > 0, "Total support must be greater than 0"`. Thông báo đó hiện
nguyên văn cho người dùng và đọc như *"dataset rỗng"* — trong khi dataset có 50.000 dòng. Nay
là `ValueError` nêu đúng vấn đề: số persona, tổng `support`, khẳng định dataset không rỗng, và
**liệt kê các key thực có** trong JSON để nhận ra ngay ai đã sinh ra nó.
Xem `tests/test_report_validator_message.py`.

---

## 2026-07-27 (lần 3) — `behavioral_features` chỉ còn là đầu vào kiểm tra schema

**Lý do.** Lõi đã tất định, nhưng *đầu vào* của nó thì chưa. Model tự chọn danh sách feature
mỗi lần chạy, và hai lần trên cùng một file 50k dòng cho:

| Nguồn feature | Số cột | k | Silhouette |
|---|---:|---:|---:|
| Model, lần 1 | 12 | 4 | **0.426** |
| Model, lần 2 | 9 | 3 | 0.286 |
| Pipeline tự chọn | 12 | 4 | **0.426** |

Cùng dữ liệu, cùng code, hai phân khúc khác nhau — lần sau kém 33% chỉ vì lần đó model nhớ
ra ít cột hơn. Sếp chạy hai lần sẽ thấy hai kết quả.

**Phương án đầu tiên đã thử và loại bỏ.** Chấm điểm cả hai tập rồi giữ silhouette cao hơn.
Không dùng được: silhouette đo độ gọn của phân hoạch *tìm được*, không đo cấu trúc đó có
thật hay không, nên k-means chia nhiễu Gaussian 2 chiều thành các blob gọn gàng và **hai cột
nhiễu thuần tuý đạt 0.351 trong khi tập chứa tín hiệu thật chỉ 0.308**. Một thước đo ưu tiên
nhiễu thì không đủ tư cách phân xử. Ghi lại thành test chạy được:
`tests/test_feature_set_choice.py::test_silhouette_alone_cannot_arbitrate`.

**Đã đổi.** Với dataset GENERIC, pipeline phân cụm trên **mọi cột số có biến thiên**. Danh
sách model truyền vào vẫn được **kiểm tra schema** (đó mới là giá trị thật của nó — bắt được
danh sách chép từ dataset khác) nhưng không quyết định kết quả. Muốn giới hạn feature thì lọc
DataFrame trước, đúng như prompt vốn đã hướng dẫn. Mỗi persona nay mang `feature_selection`
(`auto`/`caller`) và `features_used` để đọc được đã dùng tập nào.

Đường telco **không đổi**: ở đó danh sách cột mang ý nghĩa nghiệp vụ mà không thước đo phân
cụm nào nhìn thấy.

**Đổi hợp đồng có chủ đích.** `tests/test_pipeline.py::test_explicit_feature_list_is_respected`
trước đây khẳng định điều ngược lại; nay đổi tên thành
`test_an_explicit_feature_list_no_longer_decides_on_generic_data` và ghi rõ lý do.

**Prompt.** Nói thẳng với model rằng danh sách của nó dùng để kiểm tra schema, pipeline tự
chọn feature trên dataset generic, và nếu cần mô tả chính xác thì đọc `features_used` trong
JSON thay vì tự khẳng định "đã phân cụm trên đúng N cột tôi chọn".

---

### Đo lại sau khi sửa (archive thật 284 luật, repo root thật)

| Dataset (cột thật) | Luật bơm | Metadata bơm | Định danh telco lọt |
|---|---:|---:|---|
| Olist bán lẻ — 17 cột | 5 | 0 | **không có** |
| Telco — 94 cột | 5 | 18.067 ký tự | đầy đủ (đúng như mong đợi) |

Olist vẫn nhận **đủ 5** luật dùng được, không phải 3.
