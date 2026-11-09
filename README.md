# Vietnam Film Network

**Mạng lưới quan hệ điện ảnh Việt Nam được xây dựng từ dữ liệu báo chí bằng Python, xử lý ngôn ngữ tự nhiên và Neo4j.**

Dự án phục vụ học phần **Phân tích phương tiện mạng xã hội (Social Media Analytics / Social Network Analysis)**. Hệ thống thu thập bài báo từ RSS và các trang lưu trữ của cơ quan báo chí, trích xuất quan hệ giữa nhân vật, tác phẩm và tổ chức, kiểm tra bằng chứng tự động, khử trùng lặp và nhập dữ liệu vào một đồ thị Neo4j.

> **Trạng thái:** Đang phát triển và mở rộng dữ liệu (News V3 + RSS V4). Pipeline tự động hoạt động được; các chỉ tiêu nghiệm thu **chưa được chứng minh là đã đạt**. Kết quả kiểm tra tự động không phải phép đo Precision độc lập.

## 1. Mục tiêu và phạm vi

Đối tượng nghiên cứu gồm người tham gia sản xuất phim, tác phẩm điện ảnh/truyền hình và tổ chức liên quan đến ngành phim Việt Nam. Quan hệ chỉ được tạo khi bộ trích xuất tìm thấy phát biểu cụ thể trong nội dung bài báo đã tải, kèm nguồn và câu bằng chứng.

| Chỉ tiêu | Mục tiêu dự án |
| --- | ---: |
| Nút trong đồ thị | ≥ 2.200 |
| Cạnh quan hệ | ≥ 5.500 |
| Loại quan hệ có dữ liệu thực tế | ≥ 11 |
| Edge Precision | > 90% khi được đánh giá bằng tập tham chiếu độc lập |

Các mốc trên là **mục tiêu**, không phải kết quả đã đạt. Dữ liệu Wiki/Wikidata cũ được cách ly và **không được sử dụng làm nguồn đầu vào** cho pipeline báo chí hiện tại.

### Kết quả gần nhất đã quan sát

*Snapshot trước khi chạy mở rộng RSS V4, dựa trên kết quả thực nghiệm tại máy phát triển:*

| Chỉ số | Giá trị |
| --- | ---: |
| URL bài báo đã phát hiện | 482 |
| Bài báo tải nội dung thành công | 451 |
| Quan hệ ứng viên được trích xuất | 7 |
| Nút có trong Neo4j | 11 |
| Cạnh có trong Neo4j | 6 |
| Loại quan hệ có trong Neo4j | 1 (`DIRECTED`) |

Đây là số liệu lịch sử, **không tự cập nhật** theo mỗi lần chạy. Số liệu mới nhất nằm trong `reports/news_v2/` và được lấy bằng các lệnh ở phần **Kiểm tra kết quả**.

## 2. Kiến trúc xử lý

```text
RSS / Publisher Archive / Sitemap
             |
             v
  Khám phá URL và lọc chủ đề
             |
             v
  Tải nội dung bài báo gốc
             |
             v
  Nhận diện thực thể và quan hệ
             |
             v
  Kiểm tra kỹ thuật từng assertion
  (URL, publisher, hash, evidence, offset,
   kiểu thực thể và tái chạy quy tắc)
             |
             v
  Gộp quan hệ trùng và xuất CSV
             |
             v
      Neo4j :NewsV2
```

Hệ thống thực hiện các giai đoạn trên tự động, không yêu cầu nhập nhãn kiểm duyệt bằng tay để chạy pipeline. **Kiểm tra kỹ thuật 100% assertion không đồng nghĩa với độ chính xác thực tế 100% hay Precision >90%.**

### Công nghệ

- **Python 3.13**: thu thập và xử lý dữ liệu, khai thác quan hệ dựa trên mẫu câu tiếng Việt.
- **Requests, feedparser, Beautiful Soup, trafilatura**: xử lý RSS và nội dung bài báo.
- **CSV / JSON**: lưu dữ liệu trung gian, kết quả kiểm tra và báo cáo.
- **Neo4j**: quản lý và truy vấn mạng lưới quan hệ.
- **WSL2 / Ubuntu**: môi trường chạy trong quá trình phát triển.

## 3. Nguồn dữ liệu

Nguồn được quản lý tại [`config/news_sources.csv`](config/news_sources.csv). Pipeline hiện cấu hình các cơ quan báo chí như Tuổi Trẻ, Thanh Niên, VnExpress, VTV, Dân trí, Tiền Phong, Báo Văn Hóa và Báo Điện tử Chính phủ. Không phải nguồn nào cũng cung cấp RSS: một số nguồn được sử dụng qua trang lưu trữ hoặc sitemap.

Bản RSS V4 bổ sung các kênh chuyên mục điện ảnh, giải trí, truyền hình và hậu trường. Việc một feed có trong cấu hình **không bảo đảm** feed còn hoạt động hoặc có bài báo phù hợp. Mỗi URL được kiểm tra để bảo đảm thuộc nhà xuất bản đã khai báo; việc tải bài tuân thủ giới hạn truy cập và quy tắc của nguồn.

Nguyên tắc dữ liệu:

- Chỉ sử dụng nội dung bài báo gốc đã tải để trích xuất quan hệ; metadata RSS dùng để tìm URL, không được coi là bằng chứng xác nhận cạnh.
- Loại URL từ Wikipedia, Wikidata và các miền Wiki liên quan khỏi pipeline News V2/V3/V4.
- Lưu URL xuất xứ, mã bài viết, câu bằng chứng và vị trí xuất hiện trong bài.
- Không tự tạo nút/cạnh thiếu căn cứ để đáp ứng chỉ tiêu số lượng.
- Không đưa toàn văn bài báo lưu trong cache riêng tư lên GitHub.

## 4. Cài đặt

### Yêu cầu

- Python 3.13 và `pip`.
- Neo4j đang chạy, có thể kết nối qua Bolt.
- Git; WSL2/Ubuntu hoặc môi trường Linux tương đương.

Thực hiện từ **thư mục gốc repository**:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-news-v2.txt
```

Tạo file `.env` trong thư mục gốc và điền thông tin Neo4j thực tế:

```dotenv
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=YOUR_NEO4J_PASSWORD
NEO4J_DATABASE=neo4j
```

**Không commit `.env`, mật khẩu, dữ liệu riêng tư hoặc cache nội dung bài báo lên GitHub.**

> Repository cần có các module `news_pipeline/unified.py`, `news_pipeline/rss_expand.py` và `news_pipeline/film_patterns_plus.py` của các bản cập nhật đã cài. Nếu các module chưa có, README không tự cài đặt chúng.

## 5. Chạy pipeline

### 5.1. Thu thập RSS, xử lý và import Neo4j bằng một lệnh

```bash
mkdir -p reports/news_v2
set -o pipefail
python -u -m news_pipeline.rss_expand run \
  --limit 300 \
  --delay 2 \
  --fetch-limit 200 \
  --fetch-batches 30 \
  --batch-size 200 \
  2>&1 | tee reports/news_v2/rss_v4.log
```

`--limit` giới hạn số entry đọc **trên mỗi feed**, không phải tổng URL. `--fetch-limit` là số bài được thử trong một đợt; `--fetch-batches` giới hạn số đợt tải. Dữ liệu RSS mới được lưu checkpoint sau từng feed. Dữ liệu đã có được tái sử dụng và các URL trùng được khử trùng lặp.

### 5.2. Chạy lại trên dữ liệu đã tải, không thu thập RSS mới

```bash
python -u -m news_pipeline.unified run \
  --discover none \
  --skip-fetch \
  2>&1 | tee reports/news_v2/unified.log
```

Lệnh này tái tạo assertion, kiểm tra bằng chứng, xuất CSV và cập nhật graph từ những bài đã có nội dung.

### 5.3. Chỉ xuất dữ liệu, chưa import Neo4j

```bash
python -u -m news_pipeline.rss_expand run \
  --limit 300 \
  --delay 2 \
  --fetch-limit 200 \
  --fetch-batches 10 \
  --no-import
```

### 5.4. Thu thập bổ sung bằng sitemap hoặc kho bài báo

```bash
python -u -m news_pipeline.unified run \
  --discover both \
  --discover-limit 1500 \
  --max-sitemaps 10 \
  --max-pages 10 \
  --max-attempts 20 \
  --fetch-limit 200 \
  --fetch-batches 10 \
  --delay 2
```

Các giới hạn giúp kiểm soát thời gian chạy và số lượt yêu cầu. Đối với sitemap, các trang không cho phép thu thập sẽ được bỏ qua, không tìm cách vượt hạn chế của nhà xuất bản.

## 6. Mô hình đồ thị Neo4j

Tất cả thực thể trong pipeline hiện tại sử dụng nhãn chung `NewsV2` và thuộc tính `dataset = 'news_v2'`.

| Loại thực thể | Nhãn phụ trong bản import đã sửa constraint |
| --- | --- |
| Cá nhân | `NewsV2Person` |
| Tác phẩm | `NewsV2Work` |
| Tổ chức | `NewsV2Organization` |

Ví dụ quan hệ: `DIRECTED`, `ACTED_IN`, `WROTE`, `PRODUCED`, `DISTRIBUTED_BY` và các loại khác được khai báo trong bộ trích xuất. **Chỉ những loại có cạnh thực tế mới được tính vào chỉ tiêu 11 loại quan hệ.**

Importer sử dụng `MERGE` theo `NewsV2.node_id` và nhãn phụ `NewsV2*` để tránh xung đột với các ràng buộc duy nhất của `Person`/`Work` từ những đồ thị cũ. Nhãn phụ này là bản sửa đã áp dụng trên máy phát triển, không phải mặc định của mọi bản V3 trước đó.

### Truy vấn xác minh trên Neo4j Browser

Đếm nút:

```cypher
MATCH (n:NewsV2)
WHERE n.dataset = 'news_v2'
RETURN count(n) AS TotalNodes;
```

Đếm cạnh và số loại quan hệ:

```cypher
MATCH (:NewsV2)-[r]->(:NewsV2)
WHERE r.dataset = 'news_v2'
RETURN count(r) AS TotalEdges,
       count(DISTINCT type(r)) AS RelationshipTypes;
```

Thống kê từng loại quan hệ:

```cypher
MATCH (:NewsV2)-[r]->(:NewsV2)
WHERE r.dataset = 'news_v2'
RETURN type(r) AS RelationshipType,
       count(r) AS Total
ORDER BY Total DESC;
```

## 7. Dữ liệu đầu ra và báo cáo

```text
config/
  news_sources.csv               # Danh mục báo và RSS/archive
  film_keywords.txt              # Từ khóa lọc bài
  project_targets.yaml           # Mục tiêu nghiệm thu
news_pipeline/
  rss_expand.py                  # Mở rộng và thu thập RSS V4
  unified.py                     # Điều phối pipeline và import Neo4j
  high_yield.py                  # Bộ trích xuất quan hệ
  film_patterns_plus.py          # Các mẫu câu mở rộng
  ...
data/news_v2/
  articles.csv                   # URL và metadata
  article_documents.csv          # Trạng thái fetch
  relation_assertions.csv        # Các assertion ứng viên
  unified_screening.csv          # Kết quả kiểm tra từng assertion
  private/article_text/         # Bài báo gốc: KHÔNG COMMIT
  export/graph/
    nodes.csv
    edges.csv
    edge_evidence.csv
reports/news_v2/
  rss_v4_collect.json
  rss_v4_progress.json
  unified_extraction.json
  unified_graph.json
  unified_neo4j.json
  rss_v4.log
```

Các file `data/news_v2/` và `reports/news_v2/` được tạo hoặc cập nhật trong quá trình chạy; không nhất thiết tồn tại trong một bản clone mới.

Xem tiến độ:

```bash
python -m news_pipeline.rss_expand report
python -m news_pipeline.unified status
python -m json.tool reports/news_v2/unified_graph.json
python -m json.tool reports/news_v2/unified_neo4j.json
```

## 8. Kiểm định chất lượng và Precision

Pipeline hiện tại tự động kiểm tra URL nguồn, hostname nhà xuất bản, nội dung được tải, mã SHA-256, câu bằng chứng nguyên văn, vị trí ký tự, cấu trúc thực thể, khả năng tái trích xuất và trùng lặp. Mỗi assertion nhận trạng thái `machine_pass` hoặc `rejected` cùng nguyên nhân tương ứng.

Đây là **machine screening**, không phải bộ Gold Standard đã được chấm độc lập. Các chỉ số `automatic_coverage_percent` hoặc `machine_pass_assertions` không thể thay thế phép đo **Edge Precision**. Báo cáo hiện tại chưa có kết quả đáng tin cậy để khẳng định Precision >90%; README không tự điền hoặc suy diễn chỉ số đó.

Mục tiêu học phần chỉ được xem là đạt đầy đủ khi số nút, số cạnh, số loại quan hệ và độ chính xác được đo và chứng minh bằng phương pháp phù hợp.

## 9. Kiểm thử và xử lý lỗi

Kiểm thử các module cập nhật:

```bash
python -m unittest discover -s tests -p 'test_unified_v3.py' -v
python -m unittest discover -s tests -p 'test_rss_v4.py' -v
```

Nếu Neo4j chỉ có vài nút/cạnh, đối chiếu số bài và quan hệ ở từng giai đoạn thay vì import lặp lại:

```bash
python -m news_pipeline.rss_expand report
python -m json.tool reports/news_v2/unified_extraction.json
python -m json.tool reports/news_v2/unified_graph.json
```

Nếu gặp `ModuleNotFoundError: No module named 'news_pipeline'`, chạy từ thư mục gốc bằng `python -m news_pipeline.rss_expand ...` thay vì gọi trực tiếp file `.py` trong thư mục con.

Nếu Neo4j báo uniqueness constraint khi import, kiểm tra `news_pipeline/unified.py`: `MERGE` phải xác định nút theo nhãn chung `NewsV2` và `node_id`, còn nhãn phân loại phải thuộc namespace `NewsV2*` để tránh va chạm với dữ liệu cũ. Không xóa constraint hoặc database để giải quyết lỗi này.

## 10. Repository và cách đóng góp

Repository: **[lxndc/vietnam-film-network](https://github.com/lxndc/vietnam-film-network)**.

Chỉ đưa lên GitHub mã nguồn, cấu hình không chứa bí mật, kiểm thử, tài liệu và báo cáo tổng hợp phù hợp. Không commit `.env`, `.venv`, `.backup`, tệp văn bản báo chí đầy đủ, dữ liệu bí mật hoặc log chứa thông tin nhạy cảm.

```bash
git status --short
git add README.md
git diff --cached --check
git commit -m "docs: update README for RSS V4 unified news graph"
git push origin main
```

---

**Phạm vi hiện tại:** mạng quan hệ ngành phim Việt Nam trích xuất từ báo chí; vận hành bằng pipeline tự động và một đồ thị Neo4j. Việc tăng dữ liệu hoặc cải tiến NLP phải đi kèm bằng chứng nguồn và đánh giá chất lượng, không được thay bằng số liệu tự tạo.
