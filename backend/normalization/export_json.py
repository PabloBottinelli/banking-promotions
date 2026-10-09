"""Export normalized promotions from saved raw JSON without touching Supabase.

Run from backend/:
    python -m normalization.export_json --source all
    python -m normalization.export_json --source galicia

The existing raw files in backend/data/ are never modified. If a record
fails to normalize, no incomplete export is written for that source.
"""

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from normalization.sources.bbva import BBVANormalizer
from normalization.sources.galicia import GaliciaNormalizer
from normalization.sources.patagonia import PatagoniaNormalizer

BACKEND_DIR = Path(__file__).resolve().parents[1]
SOURCES = {
    "bbva": (BBVANormalizer, False),
    "galicia": (GaliciaNormalizer, False),
    "patagonia": (PatagoniaNormalizer, True),
}


def export_source(
    source: str,
    *,
    input_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Normalize a raw snapshot and atomically write its JSON export.

    Raises without overwriting an older valid export if normalization fails.
    """
    if source not in SOURCES:
        raise ValueError(f"Fuente desconocida: {source}. Opciones: {', '.join(SOURCES)}")

    input_dir = Path(input_dir) if input_dir is not None else BACKEND_DIR / "data"
    output_dir = Path(output_dir) if output_dir is not None else input_dir / "normalized"
    input_path = input_dir / f"{source}_promotions.json"
    output_path = output_dir / f"{source}_promotions.json"

    with input_path.open("r", encoding="utf-8") as file:
        raw_promotions = json.load(file)
    if not isinstance(raw_promotions, list) or not raw_promotions:
        raise ValueError(f"{input_path}: se esperaba una lista no vacía de promociones")

    normalizer_class, multiple = SOURCES[source]
    normalizer = normalizer_class()
    normalized = []
    source_ids: set[str] = set()

    for index, raw in enumerate(raw_promotions, start=1):
        try:
            promotions = normalizer.normalize_many(raw) if multiple else [normalizer.normalize(raw)]
            for promotion in promotions:
                if promotion.source != source:
                    raise ValueError(f"source incorrecto: {promotion.source!r}")
                if promotion.source_id in source_ids:
                    raise ValueError(f"source_id duplicado: {promotion.source_id!r}")
                source_ids.add(promotion.source_id)
                normalized.append(promotion.model_dump(mode="json"))
        except Exception as exc:
            identifier = raw.get("source_id", "sin ID") if isinstance(raw, dict) else "registro inválido"
            raise RuntimeError(
                f"Error normalizando {source}, registro {index}/{len(raw_promotions)}, "
                f"source_id={identifier!r}: {exc}"
            ) from exc

    if not normalized:
        raise ValueError(f"La normalización de {source} no produjo promociones")

    output_dir.mkdir(parents=True, exist_ok=True)
    # The temporary file is in the same directory, so os.replace is atomic.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=output_dir,
            prefix=f".{source}_", suffix=".json.tmp", delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(normalized, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
        os.replace(temp_path, output_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    return {
        "source": source,
        "raw_count": len(raw_promotions),
        "normalized_count": len(normalized),
        "output": str(output_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generar JSON V2 normalizado a partir de backend/data/*_promotions.json (sin Supabase)."
    )
    parser.add_argument("--source", choices=[*SOURCES, "all"], default="all")
    parser.add_argument("--input-dir", type=Path, default=BACKEND_DIR / "data")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    sources = list(SOURCES) if args.source == "all" else [args.source]
    failed = []
    for source in sources:
        try:
            result = export_source(source, input_dir=args.input_dir, output_dir=args.output_dir)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            failed.append(source)
            print(f"[ERROR] {source}: {exc}")
        else:
            print(
                f"[OK] {source}: {result['raw_count']} crudas → "
                f"{result['normalized_count']} normalizadas → {result['output']}"
            )

    if failed:
        parser.exit(1, f"No se pudieron exportar: {', '.join(failed)}\n")


if __name__ == "__main__":
    main()
