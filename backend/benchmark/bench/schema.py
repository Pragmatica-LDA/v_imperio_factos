"""Schema de saída da análise (v1).

Compatível com os três providers: structured outputs da Anthropic, `strict` da OpenAI e `format` do Ollama.
Por isso: todos os campos em `required`, `additionalProperties: false`, nulos via `anyOf`, e sem
`minimum`/`maximum`/`minLength` (os intervalos são validados no scoring).
"""

from __future__ import annotations

import jsonschema

PIECE_TYPES = ["noticia", "opiniao", "entrevista", "analise", "editorial", "reportagem", "outro"]
ENTITY_TYPES = [
    "pessoa", "partido", "governo", "instituicao", "empresa", "organizacao", "meio_comunicacao",
    "local", "outro",
]
ROLES = ["visado", "citado", "acusado", "vitima", "fonte", "autor_opiniao", "entrevistado", "mencionado"]
SENTIMENTS = ["positivo", "negativo", "neutro"]
SOURCE_TYPES = [
    "anonima", "oficial", "documento", "agencia", "redes_sociais", "especialista", "outro_meio",
    "testemunha", "outro",
]
THEME_KINDS = ["tema", "evento", "caso"]
LOCATION_LEVELS = ["freguesia", "concelho", "distrito", "regiao", "pais", "internacional"]


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def _obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_STR = {"type": "string"}

OUTPUT_SCHEMA_V1 = _obj({
    "piece_type": {"type": "string", "enum": PIECE_TYPES},
    "entities": {"type": "array", "items": _obj({
        "name": _STR,
        "canonical_name": _STR,
        "type": {"type": "string", "enum": ENTITY_TYPES},
        "is_public": {"type": "boolean"},
        "roles": {"type": "array", "items": {"type": "string", "enum": ROLES}},
        "position_at_date": _nullable(_STR),
        "sentiment": {"type": "string", "enum": SENTIMENTS},
        "sentiment_reason": _STR,
    })},
    "sources": {"type": "array", "items": _obj({
        "type": {"type": "string", "enum": SOURCE_TYPES},
        "entity_name": _nullable(_STR),
        "partial_attribute": _nullable(_STR),
        "excerpt": _STR,
    })},
    "themes": {"type": "array", "items": _obj({
        "path": {"type": "array", "items": _STR},
        "kind": {"type": "string", "enum": THEME_KINDS},
        "edition": _nullable(_STR),
        "weight": {"type": "number"},
        "is_new": {"type": "boolean"},
    })},
    "locations": {"type": "array", "items": _obj({
        "name": _STR,
        "level": {"type": "string", "enum": LOCATION_LEVELS},
        "parent": _nullable(_STR),
    })},
    "ai_indicator": _obj({
        "score": {"type": "integer"},
        "signals": {"type": "array", "items": _STR},
    }),
    "debug": _obj({
        "reasoning": _STR,
        "sources_used": {"type": "array", "items": _STR},
        "sources_discarded": {"type": "array", "items": _STR},
    }),
})


def validate(output: object, schema: dict) -> list[str]:
    """Erros de validação (lista vazia = válido). Inclui os intervalos que o schema não pode exprimir."""
    validator = jsonschema.Draft202012Validator(schema)
    errors = [f"{'/'.join(map(str, e.absolute_path)) or '<raiz>'}: {e.message}" for e in validator.iter_errors(output)]
    if not isinstance(output, dict):
        return errors
    themes = output.get("themes")
    for i, theme in enumerate(themes if isinstance(themes, list) else []):
        weight = theme.get("weight") if isinstance(theme, dict) else None
        if isinstance(weight, (int, float)) and not 0 <= weight <= 1:
            errors.append(f"themes/{i}/weight: {weight} fora de 0–1")
    ai = output.get("ai_indicator")
    score = ai.get("score") if isinstance(ai, dict) else None
    if isinstance(score, int) and not 0 <= score <= 100:
        errors.append(f"ai_indicator/score: {score} fora de 0–100")
    return errors
