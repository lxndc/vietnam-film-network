from __future__ import annotations

import logging
import re
from typing import Any

from collectors.common import request_json, stable_id, utc_now

# Property set is based on Wikidata WikiProject Movies/Properties.
# Only item-valued production/credit relationships are included here.
# A supported property is not automatically a populated relationship type;
# the report counts only types that returned records.
PROPERTY_RELATIONSHIPS = {
    "P161": ("ACTED_IN", "Person", "Work"),
    "P57": ("DIRECTED", "Person", "Work"),
    "P162": ("PRODUCED", "Person", "Work"),
    "P58": ("WROTE", "Person", "Work"),
    "P344": ("CINEMATOGRAPHED", "Person", "Work"),
    "P1040": ("EDITED", "Person", "Work"),
    "P86": ("COMPOSED_MUSIC_FOR", "Person", "Work"),
    "P272": ("PRODUCED_BY", "Work", "Organization"),
    "P750": ("DISTRIBUTED_BY", "Work", "Organization"),
    "P1431": ("EXECUTIVE_PRODUCED", "Person", "Work"),
    "P725": ("VOICE_ACTED_IN", "Person", "Work"),
    "P6942": ("ANIMATED", "Person", "Work"),
    "P2554": ("PRODUCTION_DESIGNED", "Person", "Work"),
    "P2515": ("COSTUME_DESIGNED", "Person", "Work"),
    "P3275": ("STORYBOARDED", "Person", "Work"),
    "P5028": ("SOUND_DESIGNED", "Person", "Work"),
    "P2438": ("NARRATED", "Person", "Work"),
    "P676": ("WROTE_LYRICS_FOR", "Person", "Work"),
    "P11108": ("RECORDED_PARTICIPANT_IN", "Person", "Work"),
    "P449": ("BROADCAST_BY", "Work", "Organization"),
    # Additional documented audiovisual-production credits.
    "P4805": ("MAKEUP_ARTIST_FOR", "Person", "Work"),
    "P4608": ("SCENOGRAPHED", "Person", "Work"),
    "P5126": ("ASSISTANT_DIRECTED", "Person", "Work"),
    "P3092": ("OTHER_CREW_ROLE", "Person", "Work"),
    "P3174": ("ART_DIRECTED", "Person", "Work"),
}


def qid_from_uri(uri: str) -> str:
    match = re.search(r"(Q\d+)$", uri or "")
    return match.group(1) if match else ""


def _value(row: dict, key: str) -> str:
    return str(row.get(key, {}).get("value", ""))


def build_credit_candidate(row: dict, retrieved_at: str) -> dict | None:
    work_qid = qid_from_uri(_value(row, "work"))
    target_qid = qid_from_uri(_value(row, "target"))
    property_uri = _value(row, "property")
    property_id_match = re.search(r"P\d+$", property_uri)
    property_id = property_id_match.group(0) if property_id_match else ""
    mapping = PROPERTY_RELATIONSHIPS.get(property_id)
    if not work_qid or not target_qid or not mapping:
        return None

    relationship_type, graph_source_type, graph_target_type = mapping
    work_label = _value(row, "workLabel")
    statement_target_label = _value(row, "targetLabel")
    reference_urls = sorted({
        url.strip() for url in _value(row, "referenceUrls").split("|") if url.strip()
    })
    role_qid = qid_from_uri(_value(row, "role"))
    role_name = _value(row, "roleLabel") or role_qid
    # P3092 is a generic crew property and is meaningful only when the item
    # carries an explicit role qualifier. Do not create role-less generic edges.
    if property_id == "P3092" and not role_name:
        return None

    # Wikidata statements are stored on Work. For Person -> Work graph edges,
    # reverse the statement endpoints; for Work -> Organization, preserve them.
    if graph_source_type == "Person":
        source_qid, edge_target_qid = target_qid, work_qid
        source_label, edge_target_label = statement_target_label, work_label
        statement_target_type = "Person"
    else:
        source_qid, edge_target_qid = work_qid, target_qid
        source_label, edge_target_label = work_label, statement_target_label
        statement_target_type = graph_target_type

    evidence_urls = reference_urls or [f"https://www.wikidata.org/wiki/{work_qid}"]
    candidate_role_key = role_qid if property_id == "P3092" else ""
    return {
        "candidate_id": stable_id("wikidata-credit-v3", work_qid, property_id, target_qid, candidate_role_key),
        "work_qid": work_qid,
        "work_title": work_label,
        "property_id": property_id,
        "target_qid": target_qid,
        "target_label": statement_target_label,
        "relationship_type": relationship_type,
        "role_name": role_name or None,
        "role_qid": role_qid or None,
        "source_type": graph_source_type,
        "target_type": graph_target_type,
        "statement_target_type": statement_target_type,
        "source_qid": source_qid,
        "target_node_qid": edge_target_qid,
        "source_label": source_label,
        "target_node_label": edge_target_label,
        "source_url": f"https://www.wikidata.org/wiki/{work_qid}",
        "evidence_urls": evidence_urls,
        "evidence_reference_urls": reference_urls,
        "retrieved_at": retrieved_at,
        "extraction_method": "wikidata_structured_statement_with_reference_lookup",
        "derivation_method": "direct_wikidata_statement_candidate",
        "verification_status": "needs_review",
    }


class WikidataClient:
    def __init__(self, session, settings: dict[str, Any]) -> None:
        self.session = session
        self.settings = settings
        self.endpoint = settings["sources"]["wikidata"]["sparql_endpoint"]
        self.collection = settings["collection"]
        self.country_qid = settings["sources"]["wikidata"]["country_qid"]
        self.work_type_qids = settings["sources"]["wikidata"]["work_type_qids"]

    def _query(self, sparql: str, label: str) -> dict[str, Any]:
        return request_json(
            self.session,
            self.endpoint,
            params={"query": sparql, "format": "json"},
            timeout=self.collection["request_timeout_seconds"],
            max_retries=self.collection["max_retries"],
            delay_seconds=max(
                float(self.collection.get("wikidata_credit_delay_seconds", 6.0)),
                float(self.collection["request_delay_seconds"]),
            ),
            source_name=f"Wikidata-{label}",
        )

    def collect_work_seeds(self, limit: int, offset: int = 0) -> list[dict]:
        if not 1 <= int(limit) <= 500:
            raise ValueError("Wikidata seed page limit must be between 1 and 500")
        if int(offset) < 0:
            raise ValueError("Wikidata seed offset must be >= 0")
        type_values = " ".join(f"wd:{qid}" for qid in self.work_type_qids)
        year_start = int(self.collection.get("year_start", 1900))
        year_end = int(self.collection.get("year_end", 2026))
        sparql = f"""
        PREFIX schema: <http://schema.org/>
        PREFIX wikibase: <http://wikiba.se/ontology#>
        PREFIX bd: <http://www.bigdata.com/rdf#>
        SELECT ?work ?workLabel ?workDescription
               (GROUP_CONCAT(DISTINCT STR(?workType); separator="|") AS ?workTypeUris)
               (GROUP_CONCAT(DISTINCT STR(?workTypeLabel); separator="|") AS ?workTypeLabels)
               (SAMPLE(?date) AS ?releaseDate)
               (SAMPLE(?article) AS ?wikipediaArticle)
               (SAMPLE(?basis) AS ?inclusionBasis)
        WHERE {{
          VALUES ?workType {{ {type_values} }}
          ?work wdt:P31 ?workType .
          {{
            ?work wdt:P495 wd:{self.country_qid} .
            BIND("country_of_origin" AS ?basis)
          }} UNION {{
            ?work wdt:P272 ?company .
            ?company wdt:P17 wd:{self.country_qid} .
            BIND("vietnam_production_company" AS ?basis)
          }}
          OPTIONAL {{ ?work wdt:P577 ?date . }}
          FILTER(!BOUND(?date) || (YEAR(?date) >= {year_start} && YEAR(?date) <= {year_end}))
          OPTIONAL {{
            ?article schema:about ?work ;
                     schema:isPartOf <https://vi.wikipedia.org/> .
          }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "vi,en". }}
        }}
        GROUP BY ?work ?workLabel ?workDescription
        ORDER BY ?work
        LIMIT {int(limit)} OFFSET {int(offset)}
        """
        payload = self._query(sparql, f"work-seeds-{offset}")
        rows = payload.get("results", {}).get("bindings", [])
        retrieved_at = utc_now()
        records = []
        for row in rows:
            qid = qid_from_uri(_value(row, "work"))
            if not qid:
                continue
            release_date = _value(row, "releaseDate") or None
            records.append({
                "qid": qid,
                "canonical_title": _value(row, "workLabel"),
                "description": _value(row, "workDescription"),
                "work_type_qids": [qid_from_uri(uri) for uri in _value(row, "workTypeUris").split("|") if qid_from_uri(uri)],
                "work_type_labels": [label for label in _value(row, "workTypeLabels").split("|") if label],
                "work_type_qid": next((qid_from_uri(uri) for uri in _value(row, "workTypeUris").split("|") if qid_from_uri(uri)), None),
                "work_type_label": next((label for label in _value(row, "workTypeLabels").split("|") if label), ""),
                "release_date": release_date,
                "release_year": release_date[:4] if release_date and len(release_date) >= 4 else None,
                "wikipedia_url": _value(row, "wikipediaArticle") or None,
                "wikidata_url": f"https://www.wikidata.org/wiki/{qid}",
                "inclusion_basis": _value(row, "inclusionBasis"),
                "source_name": "Wikidata Query Service",
                "retrieved_at": retrieved_at,
                "verification_status": "needs_review",
            })
        logging.info("Wikidata offset %d: %d tác phẩm ứng viên", offset, len(records))
        return records

    def collect_credits(self, work_qids: list[str], row_limit: int) -> list[dict]:
        qids = sorted({qid for qid in work_qids if re.fullmatch(r"Q\d+", qid)})
        if not qids:
            return []
        if not 1 <= int(row_limit) <= 10000:
            raise ValueError("Credit row limit must be between 1 and 10000")

        property_values = " ".join(f"wd:{pid}" for pid in PROPERTY_RELATIONSHIPS)
        work_values = " ".join(f"wd:{qid}" for qid in qids)
        sparql = f"""
        PREFIX wikibase: <http://wikiba.se/ontology#>
        PREFIX bd: <http://www.bigdata.com/rdf#>
        PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX pr: <http://www.wikidata.org/prop/reference/>
        PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
        SELECT ?work ?workLabel ?property ?target ?targetLabel ?role ?roleLabel
               (GROUP_CONCAT(DISTINCT STR(?referenceUrl); separator="|") AS ?referenceUrls)
        WHERE {{
          VALUES ?work {{ {work_values} }}
          VALUES ?property {{ {property_values} }}
          ?property wikibase:claim ?claimPredicate ;
                    wikibase:statementProperty ?statementPredicate .
          ?work ?claimPredicate ?statement .
          ?statement ?statementPredicate ?target .
          OPTIONAL {{
            ?statement pq:P3831 ?role .
          }}
          # Narrators and recorded participants can be fictional characters or
          # groups. Keep them as Person -> Work only when Wikidata identifies
          # the target as a human (Q5 or a subclass).
          FILTER(
            (?property NOT IN (wd:P2438, wd:P11108, wd:P3092) ||
             EXISTS {{ ?target wdt:P31/wdt:P279* wd:Q5 }})
          )
          OPTIONAL {{
            ?statement prov:wasDerivedFrom ?referenceNode .
            OPTIONAL {{ ?referenceNode pr:P854 ?referenceUrl . }}
          }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "vi,en". }}
        }}
        GROUP BY ?work ?workLabel ?property ?target ?targetLabel ?role ?roleLabel
        ORDER BY ?work ?property ?target
        LIMIT {int(row_limit)}
        """
        payload = self._query(sparql, f"credits-{len(qids)}-works")
        rows = payload.get("results", {}).get("bindings", [])
        retrieved_at = utc_now()
        records = [
            candidate for row in rows
            if (candidate := build_credit_candidate(row, retrieved_at)) is not None
        ]
        logging.info("Wikidata: %d quan hệ ghi công ứng viên từ %d Works", len(records), len(qids))
        return records
