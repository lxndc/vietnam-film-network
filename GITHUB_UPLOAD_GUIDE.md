# Đưa Vietnam Film Network lên GitHub (WSL Ubuntu)

## 0. Chuẩn bị

Từ thư mục gốc dự án:

```bash
cd ~/projects/vietnam-film-network/vietnam-film-network
```

Giải nén gói tài liệu README/.gitignore/.env.example đã tải. Sao chép ba file vào thư mục gốc repository:

```bash
cp /path/to/README.md ./README.md
cp /path/to/.gitignore ./.gitignore
cp /path/to/.env.example ./.env.example
```

Không thay `.env` đang dùng bằng `.env.example`.

## 1. Rà soát trước khi commit

```bash
# Kiểm tra trạng thái Git
 git status --short

# Xác nhận file môi trường thật sẽ bị ignore
 git check-ignore -v .env .venv 2>/dev/null

# Tìm file lớn hơn 50 MiB
 find . -type f -not -path './.git/*' -size +50M -printf '%s %p\n' | sort -nr

# Xem dung lượng tổng
 du -sh .
```

Nếu `.env` chưa bị ignore, sửa `.gitignore` trước khi `git add`. Đừng commit thư mục Neo4j data/volume, log, `.venv` hoặc credentials. Rà soát CSV/JSONL để chắc chắn không chứa thông tin cá nhân, thông tin hạn chế chia sẻ hoặc dữ liệu không có quyền phân phối.

## 2. Đặt tên branch và khởi tạo Git

Nếu repository chưa được khởi tạo:

```bash
 git init -b main
```

Nếu đã có Git repository:

```bash
 git branch -M main
```

## 3. Stage và kiểm tra chính xác nội dung sẽ commit

```bash
 git add -A
 git status --short
 git diff --cached --stat
 git diff --cached --name-only
```

Kiểm tra không có `.env`, `.venv`, credential hoặc database files trong danh sách. Nếu có file nhạy cảm đã được stage:

```bash
 git restore --staged PATH/TO/FILE
```

Sau đó bổ sung đường dẫn tương ứng vào `.gitignore`.

## 4. Commit

```bash
 git commit -m "Initial commit: Vietnam Film Network"
```

Nếu Git yêu cầu cấu hình danh tính:

```bash
 git config --global user.name "Your Name"
 git config --global user.email "YOUR_GITHUB_EMAIL"
```

Chạy lại lệnh commit.

## 5. Tạo GitHub repository và push

### Cách A — GitHub CLI

Cài GitHub CLI theo hướng dẫn chính thức nếu máy chưa có `gh`, sau đó:

```bash
 gh auth login
 gh repo create vietnam-film-network --private --source=. --remote=origin --push
```

Lệnh trên tạo repository private, thêm remote `origin` và push commit hiện tại.

### Cách B — Tạo repository trên website

1. Mở https://github.com/new.
2. Repository name: `vietnam-film-network`.
3. Chọn **Private** trong giai đoạn đầu.
4. Không chọn tạo README, `.gitignore` hoặc license trên GitHub vì các file này đã có ở local.
5. Create repository.
6. Sao chép URL HTTPS repository, dạng `https://github.com/USERNAME/vietnam-film-network.git`.
7. Quay lại WSL và chạy:

```bash
 git remote add origin https://github.com/USERNAME/vietnam-film-network.git
 git push -u origin main
```

Thay `USERNAME` bằng GitHub username thật.

Nếu `origin` đã tồn tại:

```bash
 git remote -v
 git remote set-url origin https://github.com/USERNAME/vietnam-film-network.git
 git push -u origin main
```

## 6. Kiểm tra sau push

```bash
 git remote -v
 git status
 git log -1 --oneline
```

Mở repository trên GitHub và kiểm tra README, thư mục `scripts/`, cấu hình Docker, báo cáo và các file dữ liệu dự định chia sẻ.

## 7. Cập nhật các lần sau

```bash
 git status --short
 git add -A
 git diff --cached --stat
 git diff --cached --name-only
 git commit -m "Describe the changes"
 git push
```

Không dùng `git add -A` trước khi kiểm tra `.gitignore` và danh sách file. Nếu có file lớn hơn 100 MiB, GitHub sẽ chặn push qua Git thông thường; cân nhắc Git LFS hoặc lưu dataset ngoài repository.
