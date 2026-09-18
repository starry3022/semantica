"""Explicit candidate-data LLM dispatch must never fall back to heuristics."""

from unittest.mock import patch

import pytest

from semantica.ontology.engine import OntologyEngine
from semantica.ontology.ontology_generator import OntologyGenerator
from semantica.utils.exceptions import ProcessingError, ValidationError


FACTS = {
    "entities": [{"id": "one", "type": "RequiredDocument", "text": "合法有效的合同"}],
    "relationships": [],
}


@pytest.mark.parametrize("engine", [False, True])
@pytest.mark.parametrize("configured", [False, True])
def test_explicit_llm_request_propagates_provider_failure(engine, configured):
    with patch(
        "semantica.ontology.llm_generator.create_provider", autospec=True
    ) as factory:
        factory.return_value.generate_structured.side_effect = RuntimeError("offline")
        config = {"provider": "openai", "model": "test-model"}
        if configured:
            config["method"] = "llm"
        instance = OntologyEngine(**config) if engine else OntologyGenerator(**config)
        generate = instance.from_data if engine else instance.generate_ontology
        with pytest.raises(ProcessingError):
            generate(
                FACTS,
                name="CandidateDraft",
                base_uri="https://example.test/ontology/",
                **({} if configured else {"method": "llm"}),
            )
        factory.return_value.generate_structured.assert_called_once()
        assert factory.call_args.kwargs == {"model": "test-model"}


@pytest.mark.parametrize("engine", [False, True])
def test_unknown_candidate_generation_method_fails_before_inference(engine):
    instance = OntologyEngine(provider=None) if engine else OntologyGenerator()
    generate = instance.from_data if engine else instance.generate_ontology
    with pytest.raises(ValidationError, match="method"):
        generate(FACTS, method="unknown")


@pytest.mark.parametrize(
    "configured,override",
    [("max_completion_tokens", "max_tokens"), ("max_tokens", "max_completion_tokens")],
)
def test_runtime_token_limit_replaces_configured_alias(configured, override):
    with patch(
        "semantica.ontology.llm_generator.create_provider", autospec=True
    ) as factory:
        factory.return_value.generate_structured.side_effect = RuntimeError("offline")
        generator = OntologyGenerator(provider="openai", **{configured: 2000})
        with pytest.raises(ProcessingError):
            generator.generate_ontology(FACTS, method="llm", **{override: 6000})
        actual = factory.return_value.generate_structured.call_args.kwargs
        assert actual[override] == 6000
        assert configured not in actual


def test_provider_switch_does_not_inherit_old_credentials_endpoint_or_model():
    with patch(
        "semantica.ontology.llm_generator.create_provider", autospec=True
    ) as factory:
        factory.return_value.generate_structured.side_effect = RuntimeError("offline")
        generator = OntologyGenerator(
            provider="openai",
            api_key="old-private-key",
            base_url="https://old.example",
            model="old-model",
        )
        with pytest.raises(ProcessingError):
            generator.generate_ontology(FACTS, method="llm", provider="ollama")
        assert factory.call_args.args == ("ollama",)
        for key in ("api_key", "base_url", "model"):
            assert key not in factory.call_args.kwargs
        assert (
            "old-model"
            not in factory.return_value.generate_structured.call_args.kwargs.values()
        )
