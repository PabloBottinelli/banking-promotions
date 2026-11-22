import argparse
import hashlib
import json
from pathlib import Path

from normalization.sources.bbva import BBVANormalizer
from synchronization.import_buepp_hybrid import prepare_import as prepare_buepp_import
from synchronization.runner import SyncRunner
from persistence.hybrid_serializer import hash_raw_data

def prepare_bbva_import(snapshot_path: Path, coverage_path: Path, cache: dict[str, dict] | None = None):
    raw_bytes = snapshot_path.read_bytes()
    raw = json.loads(raw_bytes)

    if not isinstance(raw, list) or not raw:
        raise ValueError("El snapshot debe contener promociones")

    for record in raw:
        if not isinstance(record, dict) or record.get("source") != "bbva":
            raise ValueError("Registro BBVA inválido")

        source_id = str(record.get("source_id"))

        catalog = record.get("catalog")
        detail = record.get("detail")

        if not isinstance(catalog, dict) or not isinstance(detail, dict):
            raise ValueError(f"Catálogo o detalle inválido: {source_id}")

        if str(catalog.get("id")) != source_id or str(detail.get("id")) != source_id:
            raise ValueError(f"IDs inconsistentes: {source_id}")

    runner = SyncRunner("bbva", object, BBVANormalizer, storage_mode="hybrid")
    promotions = runner.process_promotions(raw, cache=cache)

    snapshot_hash = hashlib.sha256(raw_bytes).hexdigest()
    verified = False

    if coverage_path.exists():
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))

        if not isinstance(coverage, dict):
            raise ValueError("Informe de cobertura inválido")

        if coverage.get("source") != "bbva":
            raise ValueError("Fuente incorrecta en informe de cobertura")

        if coverage.get("snapshot_sha256") != snapshot_hash:
            raise ValueError("El informe no corresponde al snapshot")

        if coverage.get("catalog_complete") is not True:
            raise ValueError("La captura BBVA no está marcada como completa")

        if coverage.get("terminal_verified") is not True:
            raise ValueError("No se verificó el final de la paginación BBVA")

        if coverage.get("limited") is not False:
            raise ValueError("No se verificó que la captura sea completa")

        if coverage.get("failed_ids") != []:
            raise ValueError("La captura contiene errores")

        if coverage.get("catalog_count") != len(promotions):
            raise ValueError("Conteo de catálogo inconsistente")

        if coverage.get("detail_success") != len(promotions):
            raise ValueError("Conteo de detalles inconsistente")

        verified = True

    return promotions, snapshot_hash, verified


def prepare_import(source: str, snapshot_path: Path, coverage_path: Path, cache: dict[str, dict] | None = None):
    if source == "buepp":
        promotions, snapshot_hash = prepare_buepp_import(snapshot_path, coverage_path, cache=cache)
        return promotions, snapshot_hash, True

    if source == "bbva":
        return prepare_bbva_import(snapshot_path, coverage_path, cache=cache)

    raise ValueError(f"Fuente no soportada: {source}")

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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, choices=["buepp", "bbva"])
    parser.add_argument("--file")
    parser.add_argument("--coverage")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--expect-count", type=int)
    parser.add_argument("--expect-sha256")
    parser.add_argument("--force-reprocess", action="store_true")
    parser.add_argument("--plan", action="store_true", help="Comparar con Supabase sin escribir cambios")
    args = parser.parse_args()

    if args.write and (args.expect_count is None or args.expect_sha256 is None):
        parser.error("--write requiere --expect-count y --expect-sha256")

    snapshot_path = Path(args.file or f"data/{args.source}_promotions.json")
    coverage_path = Path(args.coverage or f"data/{args.source}_coverage.json")

    repository = None
    existing = None
    cache = None

    if args.write:
        current_bytes = snapshot_path.read_bytes()
        current_hash = hashlib.sha256(current_bytes).hexdigest()

        if current_hash != args.expect_sha256.lower():
            raise ValueError("El archivo cambió desde la revisión")

        current_raw = json.loads(current_bytes)

        if not isinstance(current_raw, list) or len(current_raw) != args.expect_count:
            raise ValueError("La cantidad de promociones cambió")

    if args.write or args.plan:
        from persistence.hybrid_repository import HybridPromotionRepository
        from persistence.supabase_client import SUPABASE_URL, get_headers

        repository = HybridPromotionRepository(SUPABASE_URL, get_headers())

        if args.plan or not args.force_reprocess:
            existing = repository.get_existing_promotions(args.source)

            print(f"Promociones existentes en Supabase: {len(existing)}")

            if not args.force_reprocess:
                cache = existing

    promotions, snapshot_hash, verified = prepare_import(args.source, snapshot_path, coverage_path, cache=cache)

    normalized = sum(p.normalization_status == "normalized" for p in promotions)
    failed = sum(p.normalization_status == "failed" for p in promotions)
    pending = sum(p.normalization_status == "not_attempted" for p in promotions)
    variants = sum(len(p.normalized_data) for p in promotions)

    print(f"Fuente: {args.source}")
    print(f"Promociones originales: {len(promotions)}")
    print(f"Normalizadas: {normalized}")
    print(f"Fallidas: {failed}")
    print(f"Sin normalizador: {pending}")
    print(f"Variantes: {variants}")
    print(f"SHA256: {snapshot_hash}")
    print(f"Snapshot verificado: {'sí' if verified else 'no'}")

    if existing is not None:
        plan = build_incremental_plan(promotions, existing, args.force_reprocess)

        print("\nPlan incremental:")
        print(f"  Nuevas: {len(plan['new'])}")
        print(f"  Modificadas: {len(plan['modified'])}")
        print(f"  Reintentar normalización: {len(plan['retry'])}")
        print(f"  Reactivar: {len(plan['reactivate'])}")
        print(f"  Sin cambios: {len(plan['unchanged'])}")
        print(f"  Reprocesamiento forzado: {len(plan['reprocess'])}")
        print(f"  Ausentes del snapshot: {len(plan['missing'])}")

        if plan["missing"]:
            print(f"  IDs ausentes (primeros 20): {plan['missing'][:20]}")

    if not args.write:
        print("Modo de revisión: no se escribió en Supabase")
        return

    if not verified:
        raise ValueError("No se permite importar un snapshot sin cobertura verificada")

    if args.expect_count != len(promotions):
        raise ValueError("La cantidad de promociones cambió")

    if args.expect_sha256.lower() != snapshot_hash:
        raise ValueError("El archivo cambió desde la revisión")

    total = repository.upsert_many(promotions, batch_size=50)

    if total != len(promotions):
        raise RuntimeError(f"Carga incompleta: {total}/{len(promotions)}")

    print(f"Carga finalizada: {total} promociones enviadas")


if __name__ == "__main__":
    main()