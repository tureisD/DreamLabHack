# DreamLabHack: Arbeitsliste und Abnahme

Stand: 22. November 2026. Feature-Branch `codex/teach-task-coach-liam` auf dem Team-Commit `7de454d`; eigenständiger Evaluator `c679621`. Die Abnahme betrifft die Software, nicht die Leistung eines Robotermodells.

| Ticket | Liefergegenstand und Abnahme | Geprüfter Stand |
| --- | --- | --- |
| A | Explizite Task-ID/Zelle und Modellherkunft prüfen; Zuordnung, Labelrevision, Kopie, Neustart und parallele Bestätigung testen | [x] `test_offline_workflow.py`; isolierter Ende-zu-Ende-API-Test |
| B | Offene und geprüfte Stationsbefunde unterscheiden; Grund/Zeit erhalten, erneuten Stopp separat behandeln | [x] Verlauf, Doppelklick, Neustart und neuer Stopp in isolierten Tests bestanden |
| C | Ungedeckte Fehlerzelle vorziehen, Keep/Redo und ungültige Medien berücksichtigen; nur ausgewählte Skriptdemos resamplen, vor Freeze alle Kameraframes prüfen | [~] Coverage/Keep-Redo-Tests bestanden; Frame-/FPS-QC ergänzt; selektiver Resampler ohne vollständige Konvertierungsabnahme |
| D | Task-ID durch Guide, Aufnahme und Demo erhalten; optionale Diagnose darf Kernansicht nicht blockieren; zwei Tasks, Rücksprung und Kamerawechsel im Browser testen | Navigation vorhanden, Browserabnahme offen |
| S1 | Unveränderliche Szene mit Taskregel, Modell-/Assetkennung und vollständigem Integrationszustand; zwei frische Instanzen, deterministischer Reset, abweichende Pose erkennen | [~] Content-Addressed Snapshot auf `mjSTATE_INTEGRATION`; zwei Instanzen bestanden. Deterministischer Aktionslauf, abweichende Pose und Manipulationsfälle noch offen |
| S2 | Zeitlich zugeordnetes Verhalten: Position, TCP-Abstand, Kontakt, Hub, Halt, Warmup, Budget und fehlende Telemetrie; Menschenurteil getrennt | [~] Fingerkontakt, Hub, Halt, Kontaktzeit und Videobild vorhanden; TCP-Mindestabstand und Modell-Request-Zeitachse fehlen |
| S3 | Zwei Szenen: vollständiges Fixture-Paar und fehlende/inkompatible Seite; Versuche, Belegvideos, Budgets, Rohdifferenz und Ausschlussgrund ausgeben, keine Promotion | [~] Deskriptives Fixture erzeugt und eine fehlende Kandidatenseite ausgeschlossen; Startzustandsabgleich derzeit Hash nach Warmup, nicht exakter Pre-Action-Snapshot |
| E | Processing-Retry derselben Version mit Historie, Manifest, atomarem Claim und Remote-Abgleich. Fake-Gateway-Zähler für Doppelklick, Neustart, Timeout und erneuten Fehler | [~] Retry und Doppelklick mit unveränderter Dataset-ID getestet (1 Upload, 1 Retry, 1 Submit); Timeout nach Remote-Annahme abgeglichen (1 Upload, 1 Retry, 0 Submits bis zum Abgleich). Weitere Fehler- und Neustartfälle offen |
| F | Gepaarte Regel versioniert erklären; fehlende Seiten und Quellen kennzeichnen; 8:0:22-Grenzfall prüfen. Keine reale Hardwarefreigabe durch simulierte Daten | [~] Report markiert Version und Vollständigkeit, schließt Simulationsdaten aus; Grenzfall 8:0:22 noch nicht ergänzt. Verdict bleibt bewusst unverändert |
| G | Summe/Peak erhalten, Mittelwert pro Übergang ergänzen; Kalibrierung und beurteilte Läufe trennen; Nullfall und verschiedene Längen testen | [~] Mittelwert und getrennte Kalibrierungs-/Holdoutzählung implementiert; API-/UI-Tests und historische Score-Kompatibilität prüfen |
| S4 | Historie mit Datum, Manifest, Regel, Budget, Datenfingerprint und nutzbaren Paaren; zwei Wiederholungen und Regelwechsel unterscheiden | [~] Fixture-Bericht/Hash-Historie in eigenem Skript; persistente Coach-API und Szenarioänderungsfälle offen |
| H | Frisches Arbeitsverzeichnis; Tests, Ruff, Produktionsbuild, EGL-Rendering, Browser, Datenbankkopie nach Neustart, Einstieg in README | [~] 77 Tests ohne Skip bestanden; Produktionsbuild, Ruff-Lint und Diff-Prüfung bestanden. Browser-Regression und Migration einer bestehenden Datenbank bleiben eigene Abnahmen |

## Zwischenstand · 22. November 2026

- Ausgangsarbeit: lokales Pickup-Evidence samt Coach-UI und A–D. Ergänzt wurden Frame-/FPS-Prüfung, Auswahl eingecheckter Demonstrationen beim 20→10-Hz-Resampling, versionierte paarweise Berichte, ein Simulator-Snapshot-Prototyp, beschreibende Fixture-Vergleiche, ein Retry-Gerüst für Dataset-Processing und eine längennormalisierte Konsistenz-Metrik. Davon sind mehrere Funktionen noch Prototypen; die Einzelliste oben markiert die offenen Abnahmen.
- Basis ist der Team-Commit `7de454d`: Skriptdemos akzeptieren `--start-pose`; beim Aufwärmen bleibt die anfängliche Armstellung erhalten.
- Vollständiger Coach-Lauf im eigenen, aus den Lockfiles installierten Checkout: **77 Tests bestanden, keine übersprungen**. Frontend-Produktionsbuild samt TypeScript-Prüfung bestanden. Neuer, rein geskripteter Referenzlauf: Seed 41, `wrist-visible`, 325 Frames/16,25 s, drei decodierbare 20-Hz-Kameras; gemessener Hub 14,54 cm, Halt 3,40 s. Die automatische Beobachtung meldete `held`, das menschliche Label blieb `null`. Das ist ein Referenzlauf, keine Dream-1-Leistung.
- Die Zwei-Szenen-Probe verwendete synthetische Stillhalte-/Skript-Fixtures: 3 Aufnahmen, 1/2 auswertbare Paare, die fehlende Kandidatenseite wurde ausgeschlossen; null menschliche Labels, keine Promotion.
- Offen: Browser-Regression und Taskwechsel; Demoauswahl/Resampling Ende-zu-Ende; S1-Aktionsreplay und Fehlermodi; S2 TCP-Abstand und genaue Request-Zeitachse; S3 exakter Startzustandsabgleich (derzeit wird ein Hash nach Warmup genutzt); E-Fake-Gateway-Matrix und Crash-/Timeout-Reconciliation; F-Grenzfall 8:0:22; G-API/UI- und Legacy-Tests; frische Datenbankmigration. Ruff-Lint für `src`, `tests` und `experiments/yam_sim_faas` ist bestanden.
- Für diese Abnahme wurden keine Dream-Cloudaufrufe, Trainingsjobs oder Stationsstarts ausgelöst.

## Grenzen

Eine Fixture darf den Import- und Berichtspfad belegen, nicht die Leistung von Dream-1. Ein zurückgehaltener Testseed wird nicht zum gezielten Sammeln neuer Trainingsdaten verwendet. Echte Checkpoints, Dienststatus, Modellverbesserung und gegebenenfalls kostenpflichtige Schritte sind getrennte Teamabnahmen.
