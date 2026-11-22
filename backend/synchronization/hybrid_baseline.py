import argparse
import json

from datetime import datetime, timezone
from pathlib import Path


def write_baseline(path: Path, source: str, promotions) -> None:
    ids = sorted(p.source_id for p in promotions)

    if not ids:
        raise ValueError("No hay promociones para crear una referencia")

    if len(ids) != len(set(ids)):
        raise ValueError("La referencia contiene IDs duplicados")

    if any(not isinstance(i, str) or not i.strip() for i in ids):
        raise ValueError("La referencia contiene IDs inválidos")

    baseline = {
        "source": source,
        "count": len(ids),
        "source_ids": ids,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Referencia generada: {path} ({len(ids)} promociones)")


def load_baseline(path: Path, source: str) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict) or data.get("source") != source:
        raise ValueError("Fuente incorrecta en referencia histórica")

    ids = data.get("source_ids")
    count = data.get("count")

    if not isinstance(ids, list) or not ids:
        raise ValueError("Referencia histórica sin IDs válidos")

    if any(not isinstance(i, str) or not i.strip() for i in ids):
        raise ValueError("Referencia histórica con IDs inválidos")

    if len(ids) != len(set(ids)):
        raise ValueError("Referencia histórica con IDs duplicados")

    if type(count) is not int or count != len(ids):
        raise ValueError("Conteo inconsistente en referencia histórica")

    return set(ids)


def compare_baselines(
    source: str,
    current_path: Path,
    previous_path: Path | None = None,
    allow_initial: bool = False,
) -> dict:
    current = load_baseline(current_path, source)

    if previous_path is None:
        if not allow_initial:
            raise RuntimeError(
                "No existe una referencia histórica aprobada. "
                "Se requiere autorización explícita para crearla."
            )

        print(f"Primera referencia aprobada: {len(current)} promociones")

        return {
            "new": sorted(current),
            "missing": [],
            "unchanged": [],
        }

    previous = load_baseline(previous_path, source)

    result = {
        "new": sorted(current - previous),
        "missing": sorted(previous - current),
        "unchanged": sorted(current & previous),
    }

    print(f"\nComparación histórica de {source.upper()}:")
    print(f"  Referencia anterior: {len(previous)}")
    print(f"  Captura actual: {len(current)}")
    print(f"  Nuevas: {len(result['new'])}")
    print(f"  Desaparecidas: {len(result['missing'])}")
    print(f"  Sin cambios: {len(result['unchanged'])}")

    if result["missing"]:
        print(f"IDs desaparecidos: {result['missing'][:50]}")

        raise RuntimeError(
            f"Se detectaron {len(result['missing'])} "
            "promociones desaparecidas. Requieren revisión."
        )

    return result


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--source",
        required=True,
        choices=["bbva", "buepp"],
    )

    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--previous", type=Path)

    parser.add_argument(
        "--allow-initial",
        action="store_true",
    )

    args = parser.parse_args()

    compare_baselines(
        source=args.source,
        current_path=args.current,
        previous_path=args.previous,
        allow_initial=args.allow_initial,
    )


if __name__ == "__main__":
    main()