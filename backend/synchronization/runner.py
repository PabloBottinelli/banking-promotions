"""Orquestación compartida: validar antes de escribir raw o Supabase."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from normalization.models import NormalizedPromotion
from persistence.supabase_repository import SupabasePromotionRepository
from scraping.models import ScrapeResult


BACKEND_DIR = Path(__file__).resolve().parents[1]


class SyncRunner:
    def __init__(
        self,
        source: str,
        scraper_class: type,
        normalizer_class: type,
        normalize_many: bool = False,
        allow_deactivation: bool = False,
    ) -> None:
        self.source = source
        self.scraper_class = scraper_class
        self.normalizer_class = normalizer_class
        self.normalize_many = normalize_many
        # Opt-in: habilitar esto no basta sin evidencia explícita del scraper.
        self.allow_deactivation = allow_deactivation
        self.raw_path = BACKEND_DIR / "data" / f"{source}_promotions.json"

    def load_raw_promotions(self) -> list[dict]:
        with self.raw_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def scrape_promotions(self) -> tuple[object, ScrapeResult]:
        """Scrapear sin guardar. El guardado ocurre tras validar normalización."""
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

                # El control se realiza POR registro: no alcanza con un total > 0.
                for promotion in variants:
                    if not isinstance(promotion, NormalizedPromotion):
                        raise TypeError("la salida no es un NormalizedPromotion V2")
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

    def run(self, from_file: bool = False, validate_only: bool = False) -> None:
        scraper = None
        result = None

        if from_file:
            print(f"Leyendo promociones desde {self.raw_path}")
            raw_promotions = self.load_raw_promotions()
        else:
            print(f"Scrapeando promociones de {self.source.upper()}...")
            scraper, result = self.scrape_promotions()
            raw_promotions = result.promotions

        self.validate_raw_promotions(raw_promotions)
        print(f"\nPromociones crudas: {len(raw_promotions)}")

        # Fail closed: ni snapshot ni Supabase reciben extracciones incompletas.
        if result is not None and not result.complete:
            raise RuntimeError(
                f"Scraping incompleto ({len(raw_promotions)}/{result.catalog_count}); "
                "se conserva el snapshot y no se sincroniza Supabase. "
                f"Errores: {result.failed_ids[:5]}"
            )

        print("\nNormalizando y validando IDs...")
        promotions = self.normalize_promotions(raw_promotions)
        if not promotions:
            raise RuntimeError("La normalización no produjo promociones")
        print(f"Promociones normalizadas: {len(promotions)}")

        coverage = getattr(scraper, "coverage", {}) if scraper is not None else {}
        if not isinstance(coverage, dict):
            coverage = {}
        if coverage.get("snapshot_replace_allowed") is False or coverage.get("requires_review") is True:
            raise RuntimeError(
                "La fuente no autoriza reemplazar su snapshot; "
                "se bloquea también la sincronización a Supabase"
            )

        if validate_only:
            print("\n[VALIDATE ONLY] Validación completa; no se guardó raw ni se accedió a Supabase.")
            return

        # Se guarda SOLO DESPUÉS de validar todas las filas y variantes.
        # El scraper sigue siendo dueño de las validaciones y el guardado atómico.
        if scraper is not None:
            scraper.save_raw_promotions(raw_promotions)

        print("\nSincronizando con Supabase...")
        repository = SupabasePromotionRepository()
        sync_started_at = datetime.now(timezone.utc)
        total = repository.upsert_many(promotions, batch_size=200, seen_at=sync_started_at)
        if total != len(promotions):
            raise RuntimeError(
                f"Upsert incompleto: {total} de {len(promotions)} registros. "
                "No se desactiva ninguno."
            )

        can_deactivate = (
            not from_file
            and result is not None
            and result.complete
            and self.allow_deactivation
            and coverage.get("safe_to_deactivate") is True
        )
        if can_deactivate:
            deactivated = repository.deactivate_not_seen(self.source, sync_started_at)
        else:
            deactivated = 0
            print(f"\nDesactivación omitida para {self.source}: no autorizada explícitamente.")

        print("\nSincronización finalizada:")
        print(f"  Promociones crudas: {len(raw_promotions)}")
        print(f"  Promociones normalizadas: {len(promotions)}")
        print(f"  Activas encontradas: {total}")
        print(f"  Desactivadas: {deactivated}")
        print(f"  Scraping completo: {'sí' if result is not None and result.complete else 'no verificado (desde archivo)'}")

    def main(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--from-file", action="store_true")
        parser.add_argument("--validate-only", action="store_true", help="Validar sin escribir raw ni Supabase")
        args = parser.parse_args()
        self.run(from_file=args.from_file, validate_only=args.validate_only)
