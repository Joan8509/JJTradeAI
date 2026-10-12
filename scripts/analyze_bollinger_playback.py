"""Export a fixed, reproducible playback without changing live alerts."""
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bollinger_strategy_study import build_report
from watchlist_config import load_watchlist


def main():
    now = datetime.now(timezone.utc)
    report = build_report(as_of=now, days=30)
    output = Path(__file__).resolve().parents[1] / "exports" / "bollinger_playback" / now.strftime("%Y%m%d_%H%M%S")
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = [r for r in report["summary"] if r["origin"] == "RECONSTRUIDA"]
    observations = [r for r in report["observations"] if r["origin"] == "RECONSTRUIDA"]
    if rows:
        with (output / "resumen.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    lines = ["# Playback: salida de Bollinger con volatilidad, 15 minutos", "",
             f"Corte UTC: {now.isoformat()}. Ventana: últimos 30 días naturales.",
             f"Versión fija: {report['version']}. Fuente: barras disponibles; cada proveedor/feed se mantiene separado.", "",
             "Se reconstruye minuto a minuto la vela de 15m en formación, sin usar su cierre futuro. Se exige cierre previo dentro de bandas, apertura dentro de las bandas previas, expansión de ambas bandas y pendiente del centro a favor de la salida. Se excluyen aperturas ya expuestas fuera de las bandas previas.", "",
             "Positivo significa que el precio del subyacente termina a favor de la salida. No mide rentabilidad de opciones ni incluye spread, comisiones o deslizamiento. Las alertas son observaciones tempranas. Este estudio no demuestra precisión futura.", "",
             "Los porcentajes usan ventanas completas sin solapamiento dentro de cada compañía/dirección/fuente/horizonte. Los casos sin datos completos se excluyen: esto puede sesgar la muestra. No se suman horizontes como operaciones independientes.", "",
             "## Continuidad por horizonte y fuente", "",
             "| Fuente | Minutos | Casos | Positivos | Negativos | Sin cambio | % positivo |", "|---|---:|---:|---:|---:|---:|---:|"]
    for provider, feed in sorted({(r['provider'], r['feed']) for r in rows}):
        for horizon in (5, 15, 30, 60):
            group = [r for r in rows if (r['provider'], r['feed'], r['horizon']) == (provider, feed, horizon)]
            n = sum(r['sample'] for r in group)
            p = sum(r['positive'] for r in group)
            negative = sum(r['negative'] for r in group)
            zero = sum(r['unchanged'] for r in group)
            rate = f"{100*p/n:.1f}" if n else "—"
            lines.append(f"| {provider}/{feed} | {horizon} | {n} | {p} | {negative} | {zero} | {rate} |")
    lines += ["", "## Cada compañía: continuidad a 15 minutos", "",
              "| Compañía | Fuente | Salida | Casos | Sesiones | % positivo | Intervalo descriptivo 95% | Retorno direccional medio % | Evidencia |",
              "|---|---|---|---:|---:|---:|---|---:|---|"]
    for symbol in load_watchlist()['symbols']:
        group = [r for r in rows if r['symbol'] == symbol and r['horizon'] == 15]
        if not group:
            lines.append(f"| {symbol} | — | — | 0 | 0 | — | — | — | Sin historial evaluable |")
        for r in group:
            side = 'Alcista' if r['side'] == 'SUPERIOR' else 'Bajista'
            lines.append(f"| {symbol} | {r['provider']}/{r['feed']} | {side} | {r['sample']} | {r['sessions']} | {r['positive_pct']} | {r['interval_low']}–{r['interval_high']} | {r['average_return_pct']} | {r['status']} |")
    lines += ["", "## Comportamiento y exclusiones", "",
              "Las excursiones miden el máximo avance favorable y el máximo retroceso adverso dentro de la ventana; no indican cuál ocurrió primero. Las medias siguientes incluyen todas las detecciones evaluables, incluidas ventanas solapadas; son exploratorias."]
    for horizon in (5, 15, 30, 60):
        group = [r for r in observations if r['horizon'] == horizon]
        valid = [r for r in group if r['status'] == 'EVALUADA']
        excluded = Counter(r['status'] for r in group if r['status'] != 'EVALUADA')
        if valid:
            favorable = sum(r['favorable_excursion_pct'] for r in valid)/len(valid)
            adverse = sum(r['adverse_excursion_pct'] for r in valid)/len(valid)
            reversed_count = sum(r['favorable_excursion_pct'] > 0 and r['result'] == 'NEGATIVO' for r in valid)
            lines.append(f"\n- {horizon}m: {len(valid)} detecciones evaluables; avance favorable medio {favorable:.3f}%; retroceso adverso medio {adverse:.3f}%; {reversed_count} tuvieron algún avance favorable pero terminaron negativas. Exclusiones: {dict(excluded)}.")
    stamps = sorted({r['source_timestamp'] for r in observations})
    if stamps:
        lines += ["", f"Detecciones reconstruidas desde {stamps[0]} hasta {stamps[-1]} (UTC)."]
    lines += ["", "Los intervalos de Wilson son descriptivos: las compañías pueden moverse juntas y no hay una validación fuera de muestra. No se optimizaron parámetros usando estos resultados. Se necesita contrastar las detecciones en vivo y ampliar la cobertura antes de establecer filtros de aprobación."]
    (output / "analisis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(output))
    print("\n".join(lines[10:22]))


if __name__ == '__main__':
    main()
