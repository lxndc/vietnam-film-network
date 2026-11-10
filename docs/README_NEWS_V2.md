# Vietnam Film Network — RSS Newspaper-Only Pipeline V2

Pipeline này chỉ đọc dữ liệu báo chí, không đọc hoặc nhập các file `data/raw/wikidata`, `data/resolution/entity_resolution_*`, `data/evidence_validation` hay dataset Wiki cũ.

## Chỉ tiêu nghiệm thu

- **Core Nodes đã xác minh:** ≥ 2.200
- **Edge đã xác minh:** ≥ 5.500
- **Relationship Types có Edge đã xác minh:** ≥ 11
- **Edge Precision:** > 90%, đo từ Gold Standard độc lập.

Mục tiêu này cao hơn 10% so với chuẩn suy ra 2.000/5.000/10. Không đảm bảo chỉ RSS mới nhất đủ nguồn; phải tích lũy RSS qua nhiều kỳ hoặc bổ sung kho lưu trữ báo chí được phép sử dụng. Số lượng chỉ tính sau khi kiểm duyệt.

## Cài đặt và chạy

Tại project root `~/projects/vietnam-film-network/vietnam-film-network`:

```bash
source .venv/bin/activate
pip install -r requirements-news-v2.txt
python -m news_pipeline.cli collect --limit 200 --delay 3
python -m news_pipeline.cli fetch --limit 200 --delay 3
python -m news_pipeline.cli extract
python -m news_pipeline.cli audit
python -m news_pipeline.cli prepare-reviews
python -m news_pipeline.cli sample --size 329
python -m news_pipeline.cli evaluate
python -m news_pipeline.cli export
python -m news_pipeline.cli status
```

`collect` là **incremental**: cùng một bài chỉ được thêm một lần, những lần chạy tiếp theo giữ lại dữ liệu trước đó. Không chạy nhiều tiến trình ghi vào cùng CSV đồng thời.

## File đầu ra duy nhất của pipeline mới

```text
data/news_v2/
  articles.csv                   # RSS metadata
  article_documents.csv         # fetch/robots result
  private/article_text/*.txt    # local-only, tuyệt đối không commit
  relation_assertions.csv       # machine candidates
  article_audit.csv              # 100% article audit
  edge_audit.csv                 # 100% relation audit
  edge_review.csv                # human review queue
  gold_standard_sample.csv      # gold labels are intentionally blank
  export/verified/nodes.csv
  export/verified/edges.csv
  export/verified/edge_evidence.csv
reports/news_v2/*.json
```

Tất cả vị trí đọc/ghi dữ liệu nằm trong `data/news_v2` ngoại trừ danh sách nguồn báo `config/news_sources.csv` và các file báo cáo `reports/news_v2`. Không có việc tự động sử dụng Wikidata QID/Edge.

## Phân biệt 3 loại trạng thái

1. `candidate`: thuật toán trích xuất từ bài báo gốc nhưng chưa được xác minh.
2. `auto_pass_needs_independent_review`: tất cả kiểm tra kỹ thuật đã vượt qua, vẫn có thể sai ngữ nghĩa/phạm vi/định danh.
3. `verified`: kết quả `edge_review.csv` được kiểm duyệt độc lập với `supports_exact_edge=yes`, `review_decision=correct`, `scope_decision=include_vietnam` hoặc `include_coproduction`, `source_independence=independent` và có reviewer+notes.

**100% kiểm tra tự động** có nghĩa là mọi hàng đều đi qua audit và có nhãn `auto_pass` hoặc `needs_review`; hoàn toàn không có nghĩa dữ liệu 100% chính xác. Không dùng nhãn tự động để tính Gold Standard.

## Gold Standard

Chỉ tạo mẫu từ dữ liệu báo chí mới. `sample` bảo vệ file mẫu đã tồn tại. Hai người đánh giá độc lập `reviewer_a_label`, `reviewer_b_label`, rồi quyết định nhãn cuối `adjudicated_label`. Nhãn hợp lệ: `correct`, `incorrect`, `uncertain`; không có việc tự động điền `correct`.

Với bảng Gold Standard, cần điền tên 2 reviewer khác nhau, URL bài đã kiểm chứng vào `evidence_checked_url`, `review_notes`; nếu có bất đồng thì điền `adjudicator`. Lệnh `evaluate` chỉ tính Precision khi tất cả mẫu hợp lệ và đủ cỡ mẫu, đồng thời xuất Wilson lower 95% để tham khảo.

Không lấy lại Gold Standard 329 mẫu cũ từ Wikidata; mẫu cũ không kiểm chứng được tính độc lập cho dataset báo chí.

## Độ phủ và giới hạn

- Bộ extractor dùng những quy tắc tiếng Việt hẹp, ưu tiên tránh tạo quan hệ từ đồng xuất hiện. Nó không bảo đảm bắt được mọi cách diễn đạt và có thể tạo một số nhầm lẫn về tên/ngữ cảnh.
- Entity resolution hiện dùng ID ổn định theo **loại và tên**; trùng tên khác người cần được kiểm duyệt và tách trước khi được tính vào graph production.
- Bài báo nước ngoài xuất hiện trên báo Việt Nam không tự động thuộc phạm vi phim Việt; scope phải được xác minh.
- RSS thường chỉ chứa bài mới, nên một lần chạy không đủ đạt mục tiêu số lượng. Dữ liệu báo chí lịch sử chỉ có thể thu thập bằng phương pháp được phép, không vượt paywall/robots/CAPTCHA.
- Chưa tích hợp Neo4j production importer mới. Không dùng `GRAPH_IMPORT_STATUS=production python -m scripts.neo4j_import` của pipeline cũ cho dữ liệu news_v2.

## Kiểm tra sau khi chạy

```bash
python -m json.tool reports/news_v2/collect.json
python -m json.tool reports/news_v2/fetch.json
python -m json.tool reports/news_v2/audit.json
python -m json.tool reports/news_v2/evaluation.json
python -m json.tool reports/news_v2/acceptance.json
```

Mở file CSV trong Windows Explorer:

```bash
explorer.exe "$(wslpath -w "$PWD/data/news_v2")"
```

## Tránh công bố dữ liệu báo chí có bản quyền

Không commit `data/news_v2/private/`, file văn bản toàn bài, cookies, tokens, HTML hoặc thông tin truy cập cá nhân. RSS chỉ được dùng cho discovery và metadata, còn nguồn bài gốc phải được truy cập theo chính sách của từng nhà xuất bản. Ghi rõ outlet/URL/ngày xuất bản khi sử dụng dữ liệu.

## Cách ly vật lý dữ liệu Wiki cũ (không xóa)

Lệnh chỉ hiển thị đường dẫn sẽ chuyển:

```bash
bash ISOLATE_LEGACY_WIKI.sh "$PWD" --preview
```

Chuyển các thư mục Wikidata/Wikipedia và các tập dữ liệu kiểm duyệt Wiki cũ vào `.legacy_archive/wiki-<timestamp>/`:

```bash
bash ISOLATE_LEGACY_WIKI.sh "$PWD" --apply
```

Đây là thao tác **di chuyển** các thư mục cũ nhưng không xóa. Thư mục dữ liệu mới `data/news_v2` không bị tác động. Có thể đưa các thư mục từ archive trở lại nếu cần khôi phục, nhưng không nhập chung với dataset báo chí. Dù có cách ly vật lý, các script Wiki cũ vẫn nằm trong repository; chỉ dùng lệnh `python -m news_pipeline.cli ...` cho pipeline mới.

## Import Neo4j riêng biệt

Sau khi có các file verified và thực hiện `export`, kiểm tra chế độ staging:

```bash
python -m news_pipeline.cli neo4j --mode staging
```

Công cụ mới dùng label `:NewsV2` kết hợp `:Person`, `:Work`, `:Organization`, chỉ match Node có label `NewsV2` và không sử dụng ID/Wiki cũ. Khi chưa có verified edges, staging sẽ bị chặn để tránh import rỗng.

Chế độ production được khóa cứng nếu không đạt **đồng thời** các ngưỡng 2.200 Node, 5.500 Edge, 11 loại quan hệ và Gold Standard Precision >90%:

```bash
python -m news_pipeline.cli neo4j --mode production
```

Không dùng `python -m scripts.neo4j_import` thuộc pipeline Wiki cũ. Chế độ production chỉ kiểm tra báo cáo và dữ liệu từ `news_v2`, không công bố kết quả khi Gold Standard chưa hợp lệ.

### Lưu ý quan trọng

Bộ trích xuất ban đầu dựa trên mẫu câu nên **không thể bảo đảm** tự đạt 5.500 Edges hoặc 11 loại quan hệ populated. Có 12 loại quan hệ được định nghĩa trong rule extractor, nhưng chưa có bằng chứng rằng tất cả đều xuất hiện trong dữ liệu RSS. Cần mở rộng cách diễn đạt, phạm vi RSS hợp lệ và kiểm duyệt nguồn để tăng độ phủ. Tỷ lệ Precision chỉ được công bố sau khi Gold Standard độc lập hoàn tất.
