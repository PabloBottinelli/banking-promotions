import argparse
import hashlib
import json
from pathlib import Path

from normalization.sources.buepp import BueppNormalizer
from synchronization.runner import SyncRunner


def prepare_import(snapshot_path: Path, coverage_path: Path):
    raw_bytes = snapshot_path.read_bytes()
    raw = json.loads(raw_bytes)
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))

    if not isinstance(raw, list) or not raw:
        raise ValueError("El snapshot debe contener promociones")

    if coverage.get("catalog_complete") is not True:
        raise ValueError("La captura no está marcada como completa")

    if coverage.get("requires_review") is True or coverage.get("snapshot_replace_allowed") is False:
        raise ValueError("La captura requiere revisión")

    for field in ("catalog_count", "detail_success", "unique_discovered"):
        if coverage.get(field) != len(raw):
            raise ValueError(f"Conteo inconsistente en {field}")

    if any(not isinstance(item, dict) for item in raw):
        raise ValueError("Existen registros crudos inválidos")

    capture_times = {item.get("scraped_at") for item in raw}

    if len(capture_times) != 1 or None in capture_times:
        raise ValueError("Las promociones no pertenecen a una misma captura")

    if coverage.get("scraped_at") not in capture_times:
        raise ValueError("El informe de cobertura no corresponde al snapshot")

    runner = SyncRunner("buepp", object, BueppNormalizer, normalize_many=True, storage_mode="hybrid")
    promotions = runner.process_promotions(raw)

    return promotions, hashlib.sha256(raw_bytes).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="data/buepp_promotions.json")
    parser.add_argument("--coverage", default="data/buepp_coverage.json")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--expect-count", type=int)
    parser.add_argument("--expect-sha256")
    args = parser.parse_args()

    if args.write and (args.expect_count is None or args.expect_sha256 is None):
        parser.error("--write requiere --expect-count y --expect-sha256")

    promotions, snapshot_hash = prepare_import(Path(args.file), Path(args.coverage))

    normalized = sum(p.normalization_status == "normalized" for p in promotions)
    failed = sum(p.normalization_status == "failed" for p in promotions)
    pending = sum(p.normalization_status == "not_attempted" for p in promotions)
    variants = sum(len(p.normalized_data) for p in promotions)

    print(f"Promociones originales: {len(promotions)}")
    print(f"Normalizadas: {normalized}")
    print(f"Fallidas: {failed}")
    print(f"Sin normalizador: {pending}")
    print(f"Variantes: {variants}")
    print(f"SHA256 del snapshot: {snapshot_hash}")

    if not args.write:
        print("Modo de revisión: no se escribió en Supabase")
        return

    if args.expect_count != len(promotions):
        raise ValueError("La cantidad de promociones cambió")

    if args.expect_sha256.lower() != snapshot_hash:
        raise ValueError("El archivo cambió desde la revisión")

    from persistence.hybrid_repository import HybridPromotionRepository
    from persistence.supabase_client import SUPABASE_URL, get_headers

    repository = HybridPromotionRepository(SUPABASE_URL, get_headers())
    total = repository.upsert_many(promotions, batch_size=50)

    if total != len(promotions):
        raise RuntimeError(f"Carga incompleta: {total}/{len(promotions)}")

    print(f"Carga finalizada: {total} promociones enviadas")


if __name__ == "__main__":
    main()