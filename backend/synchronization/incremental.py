from datetime import datetime, timezone

from persistence.hybrid_serializer import hash_raw_data
from processing.hybrid import HybridPromotion

def build_incremental_plan(promotions, existing: dict[str, dict], force_reprocess: bool = False) -> dict[str, list[str]]:
    plan = {
        "new": [],
        "modified": [],
        "retry": [],
        "reactivate": [],
        "unchanged": [],
        "reprocess": [],
        "missing": [],
    }

    current_ids = set()

    for promotion in promotions:
        source_id = promotion.source_id
        current_ids.add(source_id)

        previous = existing.get(source_id)

        if previous is None:
            plan["new"].append(source_id)
            continue

        if force_reprocess:
            plan["reprocess"].append(source_id)
            continue

        if previous.get("raw_hash") != hash_raw_data(promotion.raw_data):
            plan["modified"].append(source_id)
            continue

        if previous.get("active") is not True:
            plan["reactivate"].append(source_id)
            continue

        variants = previous.get("normalized_data")
        valid_variants = isinstance(variants, list) and bool(variants)

        if valid_variants:
            variant_ids = []

            for variant in variants:
                if not isinstance(variant, dict) or variant.get("source") != promotion.source or not isinstance(variant.get("source_id"), str) or not variant["source_id"].strip():
                    valid_variants = False
                    break

                variant_ids.append(variant["source_id"])

            if len(variant_ids) != len(set(variant_ids)):
                valid_variants = False

        if previous.get("normalization_status") != "normalized" or promotion.normalization_status != "normalized" or not valid_variants:
            plan["retry"].append(source_id)
            continue

        plan["unchanged"].append(source_id)

    plan["missing"] = sorted(
        source_id
        for source_id, previous in existing.items()
        if source_id not in current_ids and previous.get("active") is True
    )

    return plan

def execute_incremental(repository, source: str, promotions: list[HybridPromotion], existing: dict[str, dict], seen_at: datetime | None = None) -> tuple[int, dict]:
    if not promotions:
        raise ValueError("No hay promociones para sincronizar")

    if any(p.source != source for p in promotions):
        raise ValueError("Existen promociones de otra fuente")

    ids = [p.source_id for p in promotions]

    if len(ids) != len(set(ids)):
        raise ValueError("Existen IDs duplicados")

    seen_at = seen_at or datetime.now(timezone.utc)

    plan = build_incremental_plan(promotions, existing)

    upsert_ids = set()

    for category in ("new", "modified", "retry", "reactivate"):
        upsert_ids.update(plan[category])

    unchanged_ids = set(plan["unchanged"])

    to_upsert = [p for p in promotions if p.source_id in upsert_ids]

    to_touch = [
        (p.source_id, hash_raw_data(p.raw_data))
        for p in promotions
        if p.source_id in unchanged_ids
    ]

    if len(to_upsert) + len(to_touch) != len(promotions):
        raise RuntimeError("El plan incremental no cubre todas las promociones")

    print("\nEjecutando sincronización incremental...")
    print(f"Registros completos: {len(to_upsert)}")
    print(f"Registros sin cambios: {len(to_touch)}")

    upserted = repository.upsert_many(to_upsert, batch_size=50, seen_at=seen_at)

    if upserted != len(to_upsert):
        raise RuntimeError(f"Upsert incompleto: {upserted}/{len(to_upsert)}")

    touched = repository.touch_unchanged(source, to_touch, batch_size=200, seen_at=seen_at)

    if touched != len(to_touch):
        raise RuntimeError(f"Actualización incompleta: {touched}/{len(to_touch)}")

    print(f"Insertadas o actualizadas: {upserted}")
    print(f"Actualizadas parcialmente: {touched}")
    print(f"Desaparecidas sin modificar: {len(plan['missing'])}")

    return upserted + touched, plan