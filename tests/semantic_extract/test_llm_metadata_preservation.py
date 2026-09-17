"""LLM metadata survives conversion without overriding extraction provenance."""

import unittest
from unittest.mock import MagicMock, patch

from semantica.semantic_extract import methods
from semantica.semantic_extract.cache import ExtractionCache
from semantica.semantic_extract.schemas import (
    EntitiesResponse,
    RelationsResponse,
    RelationsWithTemporalResponse,
)
from semantica.semantic_extract.types import Entity


class TestLLMMetadataPreservation(unittest.TestCase):
    def setUp(self):
        cache_patch = patch.object(methods, "_result_cache", ExtractionCache())
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        self.entities = [
            Entity(text="申请人", label="ROLE", start_char=0, end_char=3),
            Entity(text="紧急采购", label="ACTIVITY", start_char=4, end_char=8),
        ]

    def extract(self, response, *, temporal=False):
        # Replace only the external provider; exercise real schemas, conversion,
        # matching and caching without credentials or a network request.
        provider = MagicMock()
        provider.is_available.return_value = True
        provider.generate_typed.return_value = response
        with patch.object(methods, "create_provider", return_value=provider):
            if isinstance(response, EntitiesResponse):
                return methods.extract_entities_llm(
                    "申请人办理紧急采购。", provider="openai", model="test-model"
                )
            return methods.extract_relations_llm(
                "申请人办理紧急采购。",
                self.entities,
                provider="openai",
                model="test-model",
                extract_temporal_bounds=temporal,
            )

    def test_entity_keeps_model_metadata_without_inventing_offsets(self):
        response = EntitiesResponse(
            entities=[
                {
                    "text": "申请人",
                    "label": "ROLE",
                    "metadata": {"evidence_text": "申请人", "clause_ids": ["c1"]},
                }
            ]
        )
        entity = self.extract(response)[0]
        self.assertEqual(entity.metadata.get("evidence_text"), "申请人")
        self.assertEqual(entity.metadata.get("clause_ids"), ["c1"])
        self.assertEqual((entity.start_char, entity.end_char), (0, 0))

    def test_entity_model_metadata_cannot_assert_governance_approval(self):
        response = EntitiesResponse(
            entities=[
                {
                    "text": "申请人",
                    "label": "ROLE",
                    "metadata": {
                        "fact_status": "verified",
                        "review_status": "approved",
                        "evidence_verified": True,
                        "clause_id": "c1",
                    },
                }
            ]
        )
        metadata = self.extract(response)[0].metadata
        for key in ("fact_status", "review_status", "evidence_verified"):
            self.assertNotIn(key, metadata)
        self.assertEqual(metadata["clause_id"], "c1")

    def test_relation_model_metadata_cannot_assert_governance_approval(self):
        response = RelationsResponse(
            relations=[
                {
                    "subject": "申请人",
                    "predicate": "办理",
                    "object": "紧急采购",
                    "metadata": {
                        "fact_status": "verified",
                        "review_status": "approved",
                        "evidence_verified": True,
                        "clause_id": "c1",
                    },
                }
            ]
        )
        metadata = self.extract(response)[0].metadata
        for key in ("fact_status", "review_status", "evidence_verified"):
            self.assertNotIn(key, metadata)
        self.assertEqual(metadata["clause_id"], "c1")

    def test_entity_system_provenance_wins_over_model_metadata(self):
        response = EntitiesResponse(
            entities=[
                {
                    "text": "申请人",
                    "label": "ROLE",
                    "metadata": {
                        "provider": "forged",
                        "model": "forged",
                        "extraction_method": "human_reviewed",
                        "clause_id": "c1",
                    },
                }
            ]
        )
        metadata = self.extract(response)[0].metadata
        self.assertEqual(
            metadata,
            {
                "provider": "openai",
                "model": "test-model",
                "extraction_method": "llm_typed",
                "clause_id": "c1",
            },
        )
        self.assertEqual(response.entities[0].metadata["provider"], "forged")

    def test_empty_entity_metadata_retains_existing_output(self):
        response = EntitiesResponse(entities=[{"text": "申请人", "label": "ROLE"}])
        self.assertEqual(
            self.extract(response)[0].metadata,
            {
                "provider": "openai",
                "model": "test-model",
                "extraction_method": "llm_typed",
            },
        )

    def test_entity_metadata_cannot_claim_temporal_extraction(self):
        response = EntitiesResponse(
            entities=[
                {
                    "text": "申请人",
                    "label": "ROLE",
                    "metadata": {
                        "valid_from": "2030-01-01",
                        "valid_until": "2040-01-01",
                        "temporal_confidence": 1.0,
                        "temporal_source_text": "invented",
                        "clause_id": "c1",
                    },
                }
            ]
        )
        self.assertEqual(
            self.extract(response)[0].metadata,
            {
                "provider": "openai",
                "model": "test-model",
                "extraction_method": "llm_typed",
                "clause_id": "c1",
            },
        )

    def test_relation_keeps_qualifiers_and_system_provenance(self):
        response = RelationsResponse(
            relations=[
                {
                    "subject": "申请人",
                    "predicate": "办理",
                    "object": "紧急采购",
                    "metadata": {
                        "provider": "forged",
                        "model": "forged",
                        "extraction_method": "human_reviewed",
                        "conditions": [{"kind": "exception", "text": "紧急采购"}],
                        "evidence_text": "申请人办理紧急采购。",
                    },
                }
            ]
        )
        relation = self.extract(response)[0]
        self.assertEqual(
            relation.metadata,
            {
                "provider": "openai",
                "model": "test-model",
                "extraction_method": "llm_typed",
                "conditions": [{"kind": "exception", "text": "紧急采购"}],
                "evidence_text": "申请人办理紧急采购。",
            },
        )
        self.assertEqual(relation.context, "申请人办理紧急采购。")
        self.assertEqual(response.relations[0].metadata["provider"], "forged")

    def test_parsed_temporal_fields_win_over_model_metadata(self):
        response = RelationsWithTemporalResponse(
            relations=[
                {
                    "subject": "申请人",
                    "predicate": "办理",
                    "object": "紧急采购",
                    "valid_from": None,
                    "valid_until": None,
                    "temporal_confidence": 0.0,
                    "temporal_source_text": None,
                    "metadata": {
                        "valid_from": "2030-01-01",
                        "valid_until": "2040-01-01",
                        "temporal_confidence": 1.0,
                        "temporal_source_text": "invented",
                        "clause_id": "c1",
                    },
                }
            ]
        )
        self.assertEqual(
            self.extract(response, temporal=True)[0].metadata,
            {
                "provider": "openai",
                "model": "test-model",
                "extraction_method": "llm_typed",
                "clause_id": "c1",
                "valid_from": None,
                "valid_until": None,
                "temporal_confidence": 0.0,
                "temporal_source_text": None,
            },
        )

    def test_empty_relation_metadata_retains_existing_output(self):
        response = RelationsResponse(
            relations=[
                {
                    "subject": "申请人",
                    "predicate": "办理",
                    "object": "紧急采购",
                }
            ]
        )
        self.assertEqual(
            self.extract(response)[0].metadata,
            {
                "provider": "openai",
                "model": "test-model",
                "extraction_method": "llm_typed",
            },
        )

    def test_temporal_metadata_cannot_bypass_disabled_extraction(self):
        response = RelationsResponse(
            relations=[
                {
                    "subject": "申请人",
                    "predicate": "办理",
                    "object": "紧急采购",
                    "metadata": {
                        "valid_from": "2030-01-01",
                        "valid_until": "2040-01-01",
                        "temporal_confidence": 1.0,
                        "temporal_source_text": "invented",
                        "clause_id": "c1",
                    },
                }
            ]
        )
        self.assertEqual(
            self.extract(response)[0].metadata,
            {
                "provider": "openai",
                "model": "test-model",
                "extraction_method": "llm_typed",
                "clause_id": "c1",
            },
        )

    def test_untyped_invalid_metadata_keeps_legacy_parser_behavior(self):
        for metadata in (None, [], "unexpected"):
            with self.subTest(metadata=metadata):
                relations = methods._parse_relation_result(
                    [
                        {
                            "subject": "申请人",
                            "predicate": "办理",
                            "object": "紧急采购",
                            "metadata": metadata,
                        }
                    ],
                    self.entities,
                    "申请人办理紧急采购。",
                    "openai",
                    "test-model",
                )
                self.assertEqual(
                    relations[0].metadata,
                    {
                        "provider": "openai",
                        "model": "test-model",
                        "extraction_method": "llm",
                    },
                )


if __name__ == "__main__":
    unittest.main()
