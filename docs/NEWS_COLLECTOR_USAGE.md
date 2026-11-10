# RSS collector usage

Run from the project root after installing dependencies:

```bash
pip install -r requirements-news.txt
python -m scripts.collect_news_articles
```

Collect selected outlets:

```bash
python -m scripts.collect_news_articles --source TT --source TN --source VNE --source VTV
```

Limit the number of feed records per outlet:

```bash
python -m scripts.collect_news_articles --max-per-feed 100 --delay 3
```

Outputs:
- `data/staging/articles/articles.csv`
- `reports/news_collection_report.json`

This first-stage collector only reads RSS metadata and creates article candidates. It does not fetch full article bodies, extract entities or relations, or verify any Edge. Review source terms and feed availability before running. A zero-candidate result can mean feed format or keywords need adjustment; it does not prove that a publisher has no relevant stories.
