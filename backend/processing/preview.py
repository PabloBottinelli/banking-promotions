import argparse
import json
from collections import Counter
from importlib import import_module
from pathlib import Path

from persistence.hybrid_serializer import serialize_hybrid_promotion
from processing.hybrid import process_promotion


NORMALIZERS = {
    "bbva": ("normalization.sources.bbva", "BBVANormalizer", False),
    "buepp": ("normalization.sources.buepp", "BueppNormalizer", True),
    "banco_del_sol": ("normalization.sources.banco_del_sol", "BancoDelSolNormalizer", True),
    "patagonia": ("normalization.sources.patagonia", "PatagoniaNormalizer", True),
}


def preview_snapshot(source: str, path: Path, normalizer=None, normalize_many: bool = False) -> dict:
    raw_promotions = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(raw_promotions, list) or not raw_promotions:
        raise ValueError("El archivo debe contener una lista no vacía")

    ids = set()

    for raw in raw_promotions:
        if not isinstance(raw, dict):
            raise ValueError("Registro crudo inválido")

        source_id = str(raw.get("source_id") or "").strip()

        if not source_id or source_id in ids:
            raise ValueError(f"ID crudo inválido o duplicado: {source_id}")

        if raw.get("source", source) != source:
            raise ValueError(f"Fuente incorrecta: {source_id}")

        ids.add(source_id)

    processed = [process_promotion(raw, source, normalizer, normalize_many) for raw in raw_promotions]

    statuses = Counter(p.normalization_status for p in processed)
    variant_ids = Counter(v["source_id"] for p in processed for v in p.normalized_data)
    sizes = [len(json.dumps(serialize_hybrid_promotion(p), ensure_ascii=False).encode("utf-8")) for p in processed]

    return {
        "source": source,
        "total": len(processed),
        "normalized": statuses["normalized"],
        "failed": statuses["failed"],
        "not_attempted": statuses["not_attempted"],
        "variants": sum(len(p.normalized_data) for p in processed),
        "duplicate_variant_ids": sum(count > 1 for count in variant_ids.values()),
        "max_record_bytes": max(sizes),
        "errors": [{"source_id": p.source_id, "error": p.normalization_error} for p in processed if p.normalization_status == "failed"][:10],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--file", required=True)
    args = parser.parse_args()

    normalizer = None
    normalize_many = False

    if args.source in NORMALIZERS:
        module_name, class_name, normalize_many = NORMALIZERS[args.source]
        normalizer = getattr(import_module(module_name), class_name)()

    result = preview_snapshot(args.source, Path(args.file), normalizer, normalize_many)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()