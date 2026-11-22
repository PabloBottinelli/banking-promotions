
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from normalization.models import NormalizedPromotion
from persistence.supabase_repository import SupabasePromotionRepository
from scraping.models import ScrapeResult
from processing.hybrid import HybridPromotion, process_promotion
from typing import Literal
from persistence.hybrid_repository import HybridPromotionRepository
from persistence.supabase_client import SUPABASE_URL, get_headers
from copy import deepcopy
from synchronization.incremental import execute_incremental

from persistence.hybrid_serializer import hash_raw_data


BACKEND_DIR = Path(__file__).resolve().parents[1]


class SyncRunner:
    def __init__(self, source: str, scraper_class: type, normalizer_class: type | None, normalize_many: bool = False, allow_deactivation: bool = False, storage_mode: Literal["legacy", "hybrid"] = "legacy") -> None:
        self.source = source
        self.scraper_class = scraper_class
        self.normalizer_class = normalizer_class
        self.normalize_many = normalize_many
        self.allow_deactivation = allow_deactivation
        self.raw_path = BACKEND_DIR / "data" / f"{source}_promotions.json"
        self.storage_mode = storage_mode

    def load_raw_promotions(self) -> list[dict]:
        with self.raw_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def scrape_promotions(self) -> tuple[object, ScrapeResult]:
        scraper = self.scraper_class()
        return scraper, scraper.scrape()

    def validate_raw_promotions(self, raw_promotions: list[dict]) -> None:
        if not isinstance(raw_promotions, list) or not raw_promotions:
            raise RuntimeError("Se esperaba una lista no vacía de promociones crudas")

        seen: set[str] = set()
        for index, raw in enumerate(raw_promotions, start=1):
            if not isinstance(raw, dict):
                raise RuntimeError(f"Registro crudo #{index} no es un objeto")
            raw_id = raw.get("source_id")
            if raw_id is None or not str(raw_id).strip():
                raise RuntimeError(f"Registro crudo #{index} sin source_id")
            raw_id = str(raw_id)
            if raw_id in seen:
                raise RuntimeError(f"source_id crudo duplicado: {raw_id!r}")
            seen.add(raw_id)
            if raw.get("source", self.source) != self.source:
                raise RuntimeError(f"Fuente incorrecta en crudo {raw_id!r}")

    def normalize_promotions(self, raw_promotions: list[dict]) -> list[NormalizedPromotion]:
        normalizer = self.normalizer_class()
        normalized: list[NormalizedPromotion] = []
        seen_ids: set[str] = set()

        for raw in raw_promotions:
            raw_id = str(raw["source_id"])
            try:
                variants = (
                    normalizer.normalize_many(raw)
                    if self.normalize_many
                    else [normalizer.normalize(raw)]
                )
                if not isinstance(variants, list) or not variants:
                    raise ValueError("la normalización no generó ninguna variante")

                for promotion in variants:
                    if not isinstance(promotion, NormalizedPromotion):
                        raise TypeError("la salida no es un NormalizedPromotion")
                    if promotion.source != self.source:
                        raise ValueError(f"source incorrecto: {promotion.source!r}")
                    if not promotion.source_id.strip():
                        raise ValueError("source_id normalizado vacío")
                    if promotion.source_id in seen_ids:
                        raise ValueError(f"source_id normalizado duplicado: {promotion.source_id!r}")
                    seen_ids.add(promotion.source_id)
                normalized.extend(variants)
            except Exception as exc:
                raise RuntimeError(f"Error al normalizar {raw_id!r}: {exc}") from exc

        return normalized

    def process_promotions(self, raw_promotions: list[dict], cache: dict[str, dict] | None = None) -> list[HybridPromotion]:
        self.validate_raw_promotions(raw_promotions)

        normalizer = self.normalizer_class() if self.normalizer_class else None

        processed = []
        reused = 0

        for raw in raw_promotions:
            source_id = str(raw["source_id"])
            previous = cache.get(source_id) if cache is not None else None

            variants = previous.get("normalized_data") if isinstance(previous, dict) else None

            can_reuse = (
                isinstance(previous, dict)
                and previous.get("normalization_status") == "normalized"
                and previous.get("raw_hash") == hash_raw_data(raw)
                and isinstance(variants, list)
                and len(variants) > 0
            )

            if can_reuse:
                variant_ids = []

                for variant in variants:
                    if (
                        not isinstance(variant, dict)
                        or variant.get("source") != self.source
                        or not isinstance(variant.get("source_id"), str)
                        or not variant["source_id"].strip()
                    ):
                        can_reuse = False
                        break

                    variant_ids.append(variant["source_id"])

                if len(variant_ids) != len(set(variant_ids)):
                    can_reuse = False

            if can_reuse:
                normalized_data = deepcopy(variants)

                if "scraped_at" in raw:
                    for variant in normalized_data:
                        variant["scraped_at"] = raw["scraped_at"]

                promotion = HybridPromotion(
                    source=self.source,
                    source_id=source_id,
                    raw_data=raw,
                    normalized_data=normalized_data,
                    normalization_status="normalized",
                )

                reused += 1

            else:
                promotion = process_promotion(raw, self.source, normalizer, self.normalize_many)

            processed.append(promotion)

        variant_owners = {}

        for promotion in processed:
            for variant in promotion.normalized_data:
                variant_owners.setdefault(variant["source_id"], []).append(promotion)

        for variant_id, owners in variant_owners.items():
            if len(owners) > 1:
                for promotion in owners:
                    promotion.normalization_status = "failed"
                    promotion.normalization_error = f"ID normalizado duplicado: {variant_id}"
                    promotion.normalized_data = []

        if cache is not None:
            print(f"Normalizaciones reutilizadas: {reused}/{len(processed)}")

        return processed

    def run(self, from_file: bool = False, validate_only: bool = False) -> None:
        if self.storage_mode == "hybrid" and from_file and not validate_only:
            raise RuntimeError("Para importar snapshots híbridos utilizá synchronization.import_hybrid")

        scraper = None
        result = None

        if from_file:
            print(f"Leyendo promociones desde {self.raw_path}")
            raw_promotions = self.load_raw_promotions()
        else:
            print(f"Scrapeando promociones de {self.source.upper()}...")
            scraper, result = self.scrape_promotions()
            raw_promotions = result.promotions

        if result is not None and not result.complete:
            raise RuntimeError(
                f"Scraping incompleto ({len(raw_promotions)}/{result.catalog_count}); "
                "se conserva el snapshot y no se sincroniza Supabase. "
                f"Errores: {result.failed_ids[:5]}"
            )

        self.validate_raw_promotions(raw_promotions)
        print(f"\nPromociones crudas: {len(raw_promotions)}")

        # Verificar cobertura antes de consultar Supabase
        coverage = getattr(scraper, "coverage", {}) if scraper is not None else {}

        if not isinstance(coverage, dict):
            coverage = {}

        if coverage.get("snapshot_replace_allowed") is False or coverage.get("requires_review") is True:
            raise RuntimeError(
                "La fuente no autoriza reemplazar su snapshot; "
                "se bloquea también la sincronización a Supabase"
            )

        # Procesamiento
        if self.storage_mode == "hybrid":
            print("\nProcesando promociones híbridas...")

            hybrid_repository = None
            existing = None

            if not validate_only:
                hybrid_repository = HybridPromotionRepository(SUPABASE_URL, get_headers())
                existing = hybrid_repository.get_existing_promotions(self.source)

                print(f"Promociones existentes: {len(existing)}")

            promotions = self.process_promotions(raw_promotions, cache=existing)

            normalized_count = sum(p.normalization_status == "normalized" for p in promotions)
            failed_count = sum(p.normalization_status == "failed" for p in promotions)
            pending_count = sum(p.normalization_status == "not_attempted" for p in promotions)

            print(f"Promociones procesadas: {len(promotions)}")
            print(f"Normalizadas: {normalized_count}")
            print(f"Fallidas: {failed_count}")
            print(f"Sin normalizador: {pending_count}")

        else:
            print("\nNormalizando y validando IDs...")
            promotions = self.normalize_promotions(raw_promotions)

            if not promotions:
                raise RuntimeError("La normalización no produjo promociones")

            print(f"Promociones normalizadas: {len(promotions)}")

        if validate_only:
            print("\n[VALIDATE ONLY] Validación completa; no se guardó raw ni se accedió a Supabase.")
            return

        # Guardar snapshot validado
        if scraper is not None:
            scraper.save_raw_promotions(raw_promotions)

        print("\nSincronizando con Supabase...")

        sync_started_at = datetime.now(timezone.utc)

        # Persistencia
        if self.storage_mode == "hybrid":
            total, plan = execute_incremental(
                hybrid_repository,
                self.source,
                promotions,
                existing,
                seen_at=sync_started_at,
            )

        else:
            repository = SupabasePromotionRepository()
            total = repository.upsert_many(promotions, batch_size=200, seen_at=sync_started_at)

        if total != len(promotions):
            raise RuntimeError(
                f"Sincronización incompleta: {total} de {len(promotions)} registros. "
                "No se desactiva ninguno."
            )

        # Desactivación
        can_deactivate = (
            not from_file
            and result is not None
            and result.complete
            and self.allow_deactivation
            and coverage.get("safe_to_deactivate") is True
        )

        if self.storage_mode == "hybrid":
            deactivated = 0
            print("Desactivación deshabilitada en almacenamiento híbrido.")

        elif can_deactivate:
            deactivated = repository.deactivate_not_seen(self.source, sync_started_at)

        else:
            deactivated = 0
            print(f"\nDesactivación omitida para {self.source}: no autorizada explícitamente.")

        # Resumen
        print("\nSincronización finalizada:")
        print(f"  Promociones crudas: {len(raw_promotions)}")
        print(f"  Promociones procesadas: {len(promotions)}")
        print(f"  Activas encontradas: {total}")
        print(f"  Desactivadas: {deactivated}")
        print(f"  Scraping completo: {'sí' if result is not None and result.complete else 'no verificado (desde archivo)'}")

    def main(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--from-file", action="store_true")
        parser.add_argument("--validate-only", action="store_true", help="Validar sin escribir raw ni Supabase")
        args = parser.parse_args()
        self.run(from_file=args.from_file, validate_only=args.validate_only)
