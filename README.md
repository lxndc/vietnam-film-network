# Vietnam Film Network

Hệ thống thu thập, chuẩn hóa và xây dựng mạng lưới quan hệ trong lĩnh vực điện ảnh Việt Nam từ các nguồn dữ liệu công khai. Dự án áp dụng Social Network Analysis (SNA), mô hình hóa dữ liệu dưới dạng đồ thị dị thể và lưu trữ đồ thị bằng Neo4j.

> **Trạng thái dữ liệu:** README này mô tả pipeline và tiêu chí nghiệm thu. Dữ liệu ứng viên không đồng nghĩa với dữ liệu đã xác minh. Chỉ các quan hệ có bằng chứng và vượt qua quy trình kiểm định mới được đưa vào graph production.

## 1. Mục tiêu

Dự án xây dựng mạng lưới giữa cá nhân, tác phẩm điện ảnh và tổ chức có liên quan đến điện ảnh Việt Nam. Dữ liệu được thu thập từ các nguồn công khai, sau đó trải qua các bước chuẩn hóa định danh, kiểm tra phạm vi Việt Nam, xác minh bằng chứng, đánh giá độ chính xác và import vào Neo4j.

Các mục tiêu định lượng hiện được đặt ra:

| Tiêu chí | Ngưỡng nghiệm thu |
|---|---:|
| Core Nodes (`Person`, `Work`, `Organization`) | Ít nhất 4.000 |
| Valid Edges | Ít nhất 10.000 |
| Relationship Types có dữ liệu | Ít nhất 20 |
| Edge Precision trên tập Gold Standard | Lớn hơn 90% |

Các ngưỡng trên là mục tiêu nghiệm thu, không phải số liệu đã đạt. Số lượng candidate không được tính thay cho số lượng node/edge đã xác minh.

## 2. Mô hình dữ liệu

### 2.1. Node labels

| Label | Nội dung |
|---|---|
| `Person` | Diễn viên, đạo diễn, biên kịch, nhà sản xuất, thành viên đoàn phim và cá nhân khác |
| `Work` | Phim điện ảnh, phim truyền hình hoặc tác phẩm nghe nhìn nằm trong phạm vi nghiên cứu |
| `Organization` | Hãng phim, đơn vị sản xuất, đài truyền hình, đơn vị phát hành và tổ chức liên quan |

### 2.2. Relationships

Các quan hệ mô tả đóng góp hoặc liên hệ giữa `Person`, `Work` và `Organization`. Một số loại quan hệ được sử dụng trong tập candidate gồm:

`ACTED_IN`, `VOICE_ACTED_IN`, `DIRECTED`, `ASSISTANT_DIRECTED`, `PRODUCED`, `EXECUTIVE_PRODUCED`, `WROTE`, `EDITED`, `CINEMATOGRAPHED`, `COMPOSED_MUSIC_FOR`, `PRODUCTION_DESIGNED`, `COSTUME_DESIGNED`, `SOUND_DESIGNED`, `ART_DIRECTED`, `ANIMATED`, `STORYBOARDED`, `NARRATED`, `DISTRIBUTED_BY`, `PRODUCED_BY`, `BROADCAST_BY`, `OTHER_CREW_ROLE`, `RECORDED_PARTICIPANT_IN`, `SCENOGRAPHED`.

Danh sách trên là ontology/relationship candidates đã xuất hiện trong quá trình xử lý. Một loại quan hệ chỉ được tính là **populated** khi có ít nhất một quan hệ hợp lệ, không phải chỉ vì tên loại quan hệ xuất hiện trong code hoặc schema.

### 2.3. Evidence và provenance

Mỗi Edge cần giữ được khả năng truy ngược về statement và nguồn hỗ trợ. Dữ liệu nguồn được quản lý tách biệt để tránh nhầm lẫn giữa:

- URL hoặc publication item được ghi nhận trong dữ liệu nguồn;
- nguồn đã truy cập được;
- nguồn có nội dung hỗ trợ đúng Edge;
- nguồn độc lập với các nguồn khác;
- Edge đã được người kiểm duyệt xác nhận.

Việc một URL tồn tại hoặc một Wikidata statement có reference không tự động chứng minh Edge chính xác.

## 3. Pipeline xử lý

Pipeline hiện được tổ chức theo các giai đoạn sau:

1. **Collection:** thu thập Work, Person, Organization và relationship candidates từ nguồn công khai.
2. **Normalization:** chuẩn hóa tên, QID, loại entity và các trường dữ liệu.
3. **Entity Resolution:** hợp nhất bản ghi cùng thực thể, giải quyết QID trùng loại và đưa trường hợp mơ hồ vào hàng đợi kiểm tra.
4. **Vietnam Scope Audit:** phân loại tác phẩm thuộc phạm vi phim Việt Nam, đồng sản xuất hoặc ngoài phạm vi.
5. **Source Inventory:** chuẩn hóa nguồn tham chiếu và thống kê miền nguồn.
6. **Source Deduplication:** gom các locator trùng lặp thành Source Assets, đồng thời giữ mapping tới từng Edge/statement.
7. **Evidence Review:** kiểm tra nguồn có truy cập được và có hỗ trợ chính xác quan hệ tương ứng hay không.
8. **Gold Standard Evaluation:** tạo mẫu đánh giá độc lập và tính Edge Precision.
9. **Verified Dataset:** tách Edge đã xác minh, Edge cần kiểm tra và Edge bị loại.
10. **Graph Export:** xuất nodes, edges và evidence cho Neo4j.
11. **Neo4j Import:** import staging để kiểm tra trước; chỉ import production khi toàn bộ tiêu chí nghiệm thu đạt.

Không bỏ qua bước kiểm duyệt để tăng số lượng Edge hoặc làm tăng Precision trên báo cáo.

## 4. Công nghệ

- Python 3.13+ (môi trường phát triển hiện tại)
- Neo4j 5 Community
- Docker Desktop / Docker Compose
- WSL2 Ubuntu (môi trường đã sử dụng trong quá trình phát triển)
- Python packages được khai báo trong file dependency của repository (ví dụ `requirements.txt` nếu repository đang sử dụng file này)

## 5. Cấu hình môi trường

### 5.1. Yêu cầu

Cài đặt:

- Git
- Python 3.13 trở lên
- Docker Desktop có tích hợp WSL2, hoặc Docker Engine và Docker Compose trên Linux
- Neo4j 5 Community thông qua cấu hình Docker Compose của dự án

### 5.2. Tạo virtual environment

Từ thư mục gốc repository:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Nếu repository có `requirements.txt`:

```bash
pip install -r requirements.txt
```

### 5.3. Cấu hình biến môi trường

Tạo file `.env` từ `.env.example`:

```bash
cp .env.example .env
```

Các biến kết nối Neo4j được sử dụng trong môi trường hiện tại:

```dotenv
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=CHANGE_ME
```

Thay `CHANGE_ME` bằng mật khẩu đã cấu hình cho Neo4j cục bộ. Giá trị trong `.env` phải tương ứng với cấu hình container Neo4j. **Không commit `.env` lên GitHub.**

### 5.4. Khởi động Neo4j

Từ thư mục có file Docker Compose:

```bash
docker compose up -d
docker compose ps
```

Neo4j Browser mặc định trong cấu hình phát triển hiện tại:

```text
http://localhost:7474
```

Bolt endpoint:

```text
bolt://localhost:7687
```

Không xóa Docker volume đang chứa database để xử lý lỗi xác thực. Việc xóa volume có thể làm mất dữ liệu Neo4j.

## 6. Các đường dẫn dữ liệu chính

Các đường dẫn dưới đây là những khu vực dữ liệu đã được sử dụng trong pipeline:

```text
scripts/
  # Các module thu thập, resolution, evidence validation, export và import

data/
  resolution/
    entity_resolution_v2/
  evidence_validation/
    v2/
    v3_scope/
    v3_source_dedup/
    precision_preparation/   # Có thể chưa tồn tại ở mọi bản checkout
  evaluation/
    gold_standard_sample.csv
  export/
    verified/                # Thư mục export theo cấu hình pipeline

reports/
  # Báo cáo collection, resolution, evidence validation, evaluation và import
```

Không phải mọi thư mục đều được tạo ngay sau khi clone. Một số thư mục chỉ xuất hiện sau khi chạy module tương ứng.

## 7. Các lệnh pipeline

Chạy lệnh từ thư mục gốc repository, sau khi kích hoạt virtual environment và cấu hình `.env`.

### 7.1. Entity Resolution

Ví dụ lệnh Entity Resolution v2 đã sử dụng:

```bash
python -m scripts.entity_resolution \
  --review-dir data/resolution/entity_resolution_v2_input \
  --output-dir data/resolution/entity_resolution_v2
```

### 7.2. Chuẩn bị và khử trùng lặp nguồn

```bash
python -m scripts.prepare_source_review
python -m scripts.source_deduplication
```

### 7.3. Tạo Verified Dataset và đánh giá Precision

Chỉ chạy sau khi hoàn thành kiểm duyệt phạm vi Work, Source Assets, Edge–Source support và Gold Standard:

```bash
python -m scripts.build_verified_dataset
python -m scripts.evaluate_precision
```

Kiểm tra báo cáo:

```bash
python -m json.tool reports/verified_dataset_report.json
python -m json.tool reports/evaluation_report.json
```

### 7.4. Export và import staging

```bash
python -m scripts.export_verified_graph
GRAPH_IMPORT_STATUS=staging python -m scripts.neo4j_import
```

Kiểm tra báo cáo import:

```bash
python -m json.tool reports/neo4j_import_report.json
```

### 7.5. Production import

Chỉ thực hiện sau khi báo cáo evaluation xác nhận Edge Precision **lớn hơn 90%**, dữ liệu verified đạt các ngưỡng node/edge/relationship type, không còn lỗi endpoint hoặc evidence và importer chấp nhận điều kiện production:

```bash
GRAPH_IMPORT_STATUS=production python -m scripts.neo4j_import
```

Không sửa ngưỡng trong `scripts/neo4j_import.py` để bỏ qua điều kiện nghiệm thu.

## 8. Kiểm tra đồ thị trong Neo4j

Đếm node theo label sau khi import:

```cypher
MATCH (n)
WHERE n.dataset_status = 'staging'
RETURN labels(n) AS node_type, count(n) AS total;
```

Đếm relationship theo type:

```cypher
MATCH ()-[r]->()
WHERE r.dataset_status = 'staging'
RETURN type(r) AS relationship_type, count(r) AS total
ORDER BY total DESC;
```

Kiểm tra Edge chưa verified:

```cypher
MATCH ()-[r]->()
WHERE r.dataset_status = 'staging'
  AND r.verification_status <> 'verified'
RETURN count(r) AS unverified_edges;
```

Điều chỉnh `dataset_status` trong truy vấn nếu cấu hình importer của phiên bản hiện tại sử dụng giá trị khác.

## 9. Đánh giá chất lượng dữ liệu

Edge Precision phải được đo trên Gold Standard có nhãn kiểm duyệt độc lập. Nhãn `correct` trong candidate CSV, Wikidata statement hoặc trạng thái URL hợp lệ không thay thế được việc xác minh nội dung nguồn.

Quy tắc tối thiểu:

- Mỗi Edge cần xác định đúng Person/Organization và Work endpoint.
- Bằng chứng phải hỗ trợ đúng quan hệ và đúng tác phẩm.
- Phân biệt nguồn gốc độc lập với bài viết sao chép hoặc đăng lại.
- Work ngoài phạm vi nghiên cứu phải bị loại hoặc giữ ở trạng thái chưa xác định.
- Trường hợp thiếu nguồn hoặc bằng chứng mơ hồ phải ở `needs_review`/`uncertain`, không được tự chuyển thành `verified`.
- Gold Standard cần có người đánh giá, quyết định cuối cùng và ghi chú/bằng chứng; các nhãn chưa adjudicate không được tính là xác nhận đúng.

## 10. Trạng thái dữ liệu tại lần cập nhật README

Snapshot dựa trên các báo cáo đã trao đổi đến ngày **2026-11-09**:

| Chỉ số | Trạng thái đã ghi nhận |
|---|---:|
| Edge candidates sau Entity Resolution v2 | 5.568 |
| Edge được đánh dấu verified trong gói precision-preparation đã kiểm tra | 0 |
| Gold Standard sample cần đánh giá | 329 |
| Gold Standard có adjudicated label độc lập | 0 |
| Edge Precision | Chưa tính được / chưa có cơ sở xác nhận |

Đây là trạng thái của bộ dữ liệu kiểm định đã trao đổi, không phải cam kết rằng working tree hiện tại có cùng nội dung. Cần chạy lại pipeline và cập nhật báo cáo khi dữ liệu thay đổi.

## 11. Cấu trúc commit và dữ liệu

Nên đưa lên GitHub:

- Mã nguồn `scripts/` và các module hỗ trợ.
- Docker Compose config và file cấu hình mẫu.
- `README.md`, tài liệu phương pháp, schema và hướng dẫn kiểm duyệt.
- Báo cáo cần thiết để tái lập kết quả.
- CSV/JSONL dữ liệu nghiên cứu mà nhóm có quyền chia sẻ và có kích thước phù hợp.

Không đưa lên GitHub:

- `.env`, mật khẩu Neo4j, API key, access token hoặc private key.
- `.venv/`, cache, bytecode, log runtime.
- Neo4j database files, Docker volumes hoặc bản dump chứa dữ liệu không được phép công bố.
- Dữ liệu cá nhân hoặc nội dung nguồn có bản quyền mà nhóm không có quyền phân phối.

Kiểm tra file lớn trước commit:

```bash
find . -type f -not -path './.git/*' -size +50M -printf '%s %p\n' | sort -nr
```

GitHub cảnh báo với file lớn hơn 50 MiB và chặn file lớn hơn 100 MiB trong Git thông thường. Sử dụng Git LFS cho file lớn thật sự cần version control, hoặc lưu dataset bên ngoài và ghi hướng dẫn tải trong repository.

## 12. Bảo mật và giấy phép

- Giữ repository ở chế độ **Private** trong giai đoạn phát triển nếu chưa rà soát dữ liệu và quyền phân phối.
- Commit `.env.example`, không commit `.env`.
- Không commit token, mật khẩu, credential JSON, private key hoặc database password.
- Nếu secret đã bị commit/push, cần revoke/rotate secret trước; chỉ xóa file ở commit mới không xóa secret khỏi Git history.
- Chưa đặt giấy phép mở cho repository này. Trước khi public, cần xác định license cho code và rà soát quyền sử dụng/phân phối dữ liệu bên thứ ba.

## 13. Tài liệu tham khảo và nguồn dữ liệu

Dự án sử dụng dữ liệu và reference từ các nguồn công khai như Wikidata, Wikipedia và các cơ sở dữ liệu/trang thông tin điện ảnh. Mỗi bản phát hành dữ liệu nên lưu lại ngày thu thập, locator, nguồn, phương pháp xử lý và ghi chú giấy phép/điều khoản sử dụng tương ứng.

---

**Project:** Vietnam Film Network  
**Purpose:** Social Network Analysis of the Vietnamese film domain  
**Graph database:** Neo4j 5 Community  
**Status:** Research pipeline; production acceptance depends on evidence validation and independent Precision evaluation.
