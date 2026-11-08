#!/usr/bin/env python3
"""Conservative source-asset deduplication for Vietnam Film Network.

Reads source_review_queue.csv and optional gap/provenance files. It does not
fetch URLs, infer source independence, modify inputs, or verify any edge.
"""
from __future__ import annotations
import csv, hashlib, json, re
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path.cwd()
BASE = ROOT / 'data/evidence_validation/v2'
QUEUE = BASE / 'source_review_queue.csv'
GAP = BASE / 'edge_source_gap_queue.csv'
PROVENANCE = BASE / 'import_provenance_only.csv'
OUT = ROOT / 'data/evidence_validation/v3_source_dedup'
REPORTS = ROOT / 'reports'
TRACKING_KEYS = {'fbclid','gclid','dclid','mc_cid','mc_eid','ref_src','ref_url','igshid'}
TRACKING_PREFIXES = ('utm_',)

def read_csv(path: Path, required=True):
    if not path.exists():
        if required: raise FileNotFoundError(f'Required input missing: {path}')
        return []
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def write_csv(path: Path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader(); w.writerows(rows)

def make_id(key):
    return 'SRC_' + hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]

def normalize_p248(locator):
    raw = (locator or '').strip()
    m = re.search(r'(?:/wiki/|/entity/)(Q\d+)(?:$|[/?#])', raw) or re.fullmatch(r'(Q\d+)', raw)
    if m:
        qid = m.group(1)
        return 'WIKIDATA_PUBLICATION:' + qid, f'https://www.wikidata.org/wiki/{qid}', qid
    return 'P248_RAW:' + raw, raw, ''

def normalize_p854(locator):
    raw = (locator or '').strip()
    p = urlsplit(raw)
    if p.scheme.lower() not in {'http','https'} or not p.hostname:
        return 'P854_RAW:' + raw, raw, ''
    scheme, host = p.scheme.lower(), p.hostname.lower()
    if host.startswith('www.'): host = host[4:]
    try: port = p.port
    except ValueError: port = None
    if port and not ((scheme == 'http' and port == 80) or (scheme == 'https' and port == 443)):
        host = f'{host}:{port}'
    query = []
    for k,v in parse_qsl(p.query, keep_blank_values=True):
        kl = k.lower()
        if kl in TRACKING_KEYS or any(kl.startswith(x) for x in TRACKING_PREFIXES): continue
        query.append((k,v))
    canonical = urlunsplit((scheme, host, p.path or '/', urlencode(sorted(query), doseq=True), ''))
    domain = host.split(':')[0]
    return 'P854_URL:' + canonical, canonical, domain

def main():
    rows = read_csv(QUEUE)
    gaps = read_csv(GAP, required=False)
    provenance = read_csv(PROVENANCE, required=False)
    required = {'review_item_id','edge_id','relationship_type','work_qid','property_id','statement_id','target_qid','source_kind','source_locator'}
    if rows:
        missing = required - set(rows[0])
        if missing: raise ValueError(f'Missing source queue columns: {sorted(missing)}')

    assets, mappings, edge_pairs = {}, [], {}
    kind_counts = Counter(); unknown_count = 0
    for row in rows:
        kind = (row.get('source_kind') or '').strip()
        locator = (row.get('source_locator') or '').strip()
        if kind == 'P248_publication_item':
            key, canonical, qid = normalize_p248(locator); domain = 'wikidata.org' if qid else ''; normalized_kind = kind
        elif kind == 'P854_reference_url':
            key, canonical, domain = normalize_p854(locator); qid = ''; normalized_kind = kind
        else:
            key, canonical, qid, domain, normalized_kind = f'UNKNOWN:{kind}:{locator}', locator, '', '', kind or 'UNKNOWN'
            unknown_count += 1
        aid = make_id(key); kind_counts[normalized_kind] += 1
        a = assets.setdefault(aid, {'source_asset_id':aid,'source_kind':normalized_kind,'canonical_locator':canonical,'publication_qid':qid,'source_domain':domain,'titles':set(),'dates':set(),'originals':set(),'edges':set(),'types':set()})
        if row.get('source_title'): a['titles'].add(row['source_title'].strip())
        if row.get('publication_date'): a['dates'].add(row['publication_date'].strip())
        if locator: a['originals'].add(locator)
        if row.get('edge_id'): a['edges'].add(row['edge_id'])
        if row.get('relationship_type'): a['types'].add(row['relationship_type'])
        mappings.append({'source_asset_id':aid,'review_item_id':row.get('review_item_id',''),'edge_id':row.get('edge_id',''),'relationship_type':row.get('relationship_type',''),'work_qid':row.get('work_qid',''),'property_id':row.get('property_id',''),'statement_id':row.get('statement_id',''),'target_qid':row.get('target_qid',''),'source_kind':normalized_kind,'original_locator':locator,'canonical_locator':canonical,'review_decision':row.get('review_decision','pending')})
        pair = (aid, row.get('edge_id',''))
        ep = edge_pairs.setdefault(pair, {'source_asset_id':aid,'edge_id':row.get('edge_id',''),'relationship_type':row.get('relationship_type',''),'work_qid':row.get('work_qid',''),'property_id':row.get('property_id',''),'statement_ids':set(),'target_qids':set(),'source_kind':normalized_kind})
        if row.get('statement_id'): ep['statement_ids'].add(row['statement_id'])
        if row.get('target_qid'): ep['target_qids'].add(row['target_qid'])

    asset_rows = []
    for a in sorted(assets.values(), key=lambda x:x['source_asset_id']):
        asset_rows.append({'source_asset_id':a['source_asset_id'],'source_kind':a['source_kind'],'canonical_locator':a['canonical_locator'],'publication_qid':a['publication_qid'],'source_domain':a['source_domain'],'source_title_values':json.dumps(sorted(a['titles']),ensure_ascii=False),'publication_date_values':json.dumps(sorted(a['dates']),ensure_ascii=False),'original_locator_count':len(a['originals']),'linked_edge_count':len(a['edges']),'linked_relationship_types':json.dumps(sorted(a['types']),ensure_ascii=False),'source_accessible':'pending','asset_review_decision':'pending','independence_group':'','independence_status':'not_assessed','reviewer':'','review_notes':''})
    edge_review_rows = [{'source_asset_id':e['source_asset_id'],'edge_id':e['edge_id'],'relationship_type':e['relationship_type'],'work_qid':e['work_qid'],'property_id':e['property_id'],'statement_ids':json.dumps(sorted(e['statement_ids'])),'target_qids':json.dumps(sorted(e['target_qids'])),'source_kind':e['source_kind'],'supports_exact_edge':'pending','review_decision':'pending','reviewer':'','review_notes':''} for e in sorted(edge_pairs.values(), key=lambda x:(x['edge_id'],x['source_asset_id']))]
    independence_rows = [{'source_asset_id':a['source_asset_id'],'source_kind':a['source_kind'],'canonical_locator':a['canonical_locator'],'source_domain':a['source_domain'],'independence_group':'','parent_source_asset_id':'','syndication_status':'unknown','independence_status':'not_assessed','reviewer':'','review_notes':''} for a in asset_rows]

    OUT.mkdir(parents=True, exist_ok=True); REPORTS.mkdir(parents=True, exist_ok=True)
    write_csv(OUT/'source_assets.csv',['source_asset_id','source_kind','canonical_locator','publication_qid','source_domain','source_title_values','publication_date_values','original_locator_count','linked_edge_count','linked_relationship_types','source_accessible','asset_review_decision','independence_group','independence_status','reviewer','review_notes'],asset_rows)
    write_csv(OUT/'source_edge_map.csv',['source_asset_id','review_item_id','edge_id','relationship_type','work_qid','property_id','statement_id','target_qid','source_kind','original_locator','canonical_locator','review_decision'],mappings)
    write_csv(OUT/'edge_source_support_review.csv',['source_asset_id','edge_id','relationship_type','work_qid','property_id','statement_ids','target_qids','source_kind','supports_exact_edge','review_decision','reviewer','review_notes'],edge_review_rows)
    write_csv(OUT/'source_independence.csv',['source_asset_id','source_kind','canonical_locator','source_domain','independence_group','parent_source_asset_id','syndication_status','independence_status','reviewer','review_notes'],independence_rows)

    unique_edges = len({r.get('edge_id','') for r in rows if r.get('edge_id')})
    unique_assets = len(asset_rows)
    report = {'stage':'source_deduplication_v1','input_source_review_tasks':len(rows),'unique_edge_ids_in_source_queue':unique_edges,'unique_source_assets':unique_assets,'deduplication_reduction':len(rows)-unique_assets,'source_asset_reduction_percent':round((len(rows)-unique_assets)/len(rows)*100,2) if rows else 0,'edge_source_mappings_preserved':len(mappings),'unique_edge_asset_pairs':len(edge_review_rows),'source_assets_reused_by_multiple_edges':sum(int(a['linked_edge_count'])>1 for a in asset_rows),'input_tasks_by_kind':dict(kind_counts),'edges_without_p854_or_p248_source':len(gaps),'p143_provenance_rows_kept_separate':len(provenance),'unknown_source_kind_rows':unknown_count,'integrity_checks':{'all_source_review_tasks_mapped':len(mappings)==len(rows),'no_edge_source_mapping_dropped':len(mappings)==len(rows),'source_independence_auto_assigned':False,'all_edge_support_reviews_pending':all(r['review_decision']=='pending' for r in edge_review_rows)},'outputs':{'source_assets':str(OUT/'source_assets.csv'),'source_edge_map':str(OUT/'source_edge_map.csv'),'edge_source_support_review':str(OUT/'edge_source_support_review.csv'),'source_independence':str(OUT/'source_independence.csv')},'important':['Deduplication applies to source assets only; all task-to-edge mappings are preserved.','Different paths on the same domain are not merged.','HTTP and HTTPS are not merged automatically.','Only known tracking parameters and URL fragments are removed.','P248 is keyed by publication QID.','P143 provenance remains separate and is not treated as evidence.','Source independence is left unassessed.','No URLs are fetched and no Edge is marked verified.']}
    (REPORTS/'source_dedup_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == '__main__': main()
