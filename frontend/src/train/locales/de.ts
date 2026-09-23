// catalog, which is always loaded, so lookup here can never miss.

import type { Catalog } from "../../shared/i18nCore";

const CATALOG: Catalog = {
  "default":
    "Standard",
  "This model's own size. A job set to it follows whichever model it is pointed at.":
    "Die eigene Größe dieses Modells. Ein Lauf, der darauf steht, folgt dem Modell, auf das er zeigt.",
  "{n} px":
    "{n} px",
  "A run trains at one size at least.":
    "Ein Lauf trainiert bei mindestens einer Größe.",
  "A run trains at up to five sizes — each one is another pass over the dataset per epoch.":
    "Ein Lauf trainiert bei höchstens fünf Größen — jede ist ein weiterer Durchlauf durch den Datensatz pro Epoche.",
  "e.g. 704":
    "z. B. 704",
  "Another size…":
    "Weitere Größe …",
  "Pick every size this run should train at. A picture joins each one it is big enough for, so the same picture can be learnt at more than one scale — and each size is another pass over the dataset per epoch.":
    "Wählen Sie jede Größe, bei der dieser Lauf trainieren soll. Ein Bild kommt zu jeder Größe hinzu, für die es groß genug ist — dieselbe Aufnahme wird also in mehreren Maßstäben gelernt, und jede Größe ist ein weiterer Durchlauf durch den Datensatz pro Epoche.",
  "Left empty both fields use the model's own size — a test sample is not tied to the sizes the run trains at.":
    "Leer gelassen verwenden beide Felder die Größe des Modells — ein Testbild ist nicht an die Trainingsgrößen gebunden.",
  "The sizes images are trained at, each given as one number that stands for a pixel budget: 1024 means 'about a megapixel', which every aspect-ratio bucket then spends differently — 1024×1024, or 1216×832, or 832×1216.\n\nMatch them to what the base model was trained on (1024 for SDXL, Chroma and FLUX.2, 512 for SD 1.5); training far above that teaches little and costs a lot, while training below it is a genuine speed and memory lever at the price of fine detail. Cost scales with the area, so 768 is nearly half the work per step that 1024 is. The size the list marks as default is the model's own, and a job set to it follows whichever model it is pointed at.\n\nPicking more than one trains the same pictures at each of them. A model that has only ever seen a subject at 1024 has learnt it together with the canvas it was on: asked for something smaller it tends to answer with a crop or a doubled-up version of the same framing. Several sizes separate what the model learns about the subject from what it learns about the shape of the picture.\n\nEach size is a full family of buckets, and every image joins the ones it is large enough for — which is the other half of what this is for. Under Never upscale a 700-pixel scan is simply left out of a 1024 run; add 512 and it trains there instead of being dropped, while the large pictures keep training at both.\n\nIt is not free. A size is another pass over the dataset in every epoch and another cached latent per picture, and the batches at the largest one decide the peak memory — so adding a size above the others raises what the run needs on the card, and adding ones below mainly makes an epoch longer. Two or three an octave apart (512, 768, 1024) is the usual shape; at most five.":
    "Die Größen, bei denen die Bilder trainiert werden, jeweils als eine Zahl, die für ein Pixelbudget steht: 1024 heißt „etwa ein Megapixel“, das jeder Seitenverhältnis-Bucket anders ausgibt — 1024×1024, 1216×832 oder 832×1216.\n\nRichten Sie sie nach dem aus, worauf das Basismodell trainiert wurde (1024 für SDXL, Chroma und FLUX.2, 512 für SD 1.5); weit darüber zu trainieren bringt wenig und kostet viel, während darunter ein echter Geschwindigkeits- und Speicherhebel ist, zum Preis feiner Details. Die Kosten skalieren mit der Fläche, 768 ist also fast die halbe Arbeit pro Schritt von 1024. Die in der Liste als Standard markierte Größe ist die des Modells; ein Lauf, der darauf steht, folgt dem Modell, auf das er zeigt.\n\nMehr als eine zu wählen trainiert dieselben Bilder bei jeder von ihnen. Ein Modell, das ein Motiv nur bei 1024 gesehen hat, hat es zusammen mit der Leinwand gelernt, auf der es stand: Wird etwas Kleineres verlangt, antwortet es meist mit einem Ausschnitt oder einer verdoppelten Fassung derselben Bildaufteilung. Mehrere Größen trennen, was das Modell über das Motiv lernt, von dem, was es über die Form des Bildes lernt.\n\nJede Größe ist eine vollständige Bucket-Familie, und jedes Bild kommt zu denen hinzu, für die es groß genug ist — die andere Hälfte des Zwecks. Bei „Nie hochskalieren“ fällt ein 700-Pixel-Scan bei einem 1024er-Lauf einfach weg; mit 512 trainiert er dort, statt verworfen zu werden, während die großen Bilder weiterhin bei beiden trainieren.\n\nUmsonst ist das nicht. Eine Größe ist ein weiterer Durchlauf durch den Datensatz in jeder Epoche und ein weiteres zwischengespeichertes Latent pro Bild, und die Batches bei der größten bestimmen den Speicherbedarf — eine Größe oberhalb der anderen erhöht also, was der Lauf auf der Karte braucht, und Größen darunter verlängern vor allem die Epoche. Zwei oder drei im Oktavabstand (512, 768, 1024) sind die übliche Form; höchstens fünf.",
  "An image smaller than its bucket has to be enlarged to train at that size, and enlarging invents detail that was never in the picture: soft edges, smeared texture, the interpolation's own look. Trained on, that is what the model learns the subject looks like.\n\nThis is on by default. Those images are left out while the dataset is built — before anything is encoded, so they cost no time and no cache — and the run says how many it dropped. It is asked per resolution, so a picture too small for the largest size still trains at a smaller one rather than being dropped from the run; turn it off for a small dataset, where a slightly soft picture is usually worth more than no picture.":
    "Ein Bild, das kleiner ist als sein Bucket, muss vergrößert werden, um bei dieser Größe zu trainieren, und Vergrößern erfindet Details, die nie im Bild waren: weiche Kanten, verschmierte Textur, der Look der Interpolation selbst. Darauf trainiert, ist genau das, was das Modell als Aussehen des Motivs lernt.\n\nDas ist standardmäßig an. Diese Bilder fallen schon beim Aufbau des Datensatzes weg — bevor irgendetwas kodiert wird, sie kosten also weder Zeit noch Cache — und der Lauf nennt die Zahl. Es wird pro Auflösung gefragt: Ein Bild, das für die größte Größe zu klein ist, trainiert trotzdem bei einer kleineren, statt aus dem Lauf zu fallen. Für einen kleinen Datensatz schalten Sie es aus — dort ist ein leicht weiches Bild meist mehr wert als gar keins.",
  "New training job": "Neuer Trainingsauftrag",
  "Drafts": "Entwürfe",
  "Paused": "Pausiert",
  "Completed": "Fertig",
  "Failed": "Fehlgeschlagen",
  "Full finetune": "Komplettes Finetuning",
  "Loss appears here once training starts.": "Der Loss erscheint hier, sobald das Training startet.",
  "Test samples": "Testbilder",
  "Select a job to see its progress, samples and settings.": "Auftrag auswählen, um Fortschritt, Testbilder und Einstellungen zu sehen.",
  "No training jobs yet. Create one to fine-tune a model (LoRA or full) on images selected straight from your library.": "Noch keine Trainingsaufträge. Erstelle einen, um ein Modell (LoRA oder komplett) direkt mit Bildern aus deiner Bibliothek zu trainieren.",
  "Training environment not set up": "Trainingsumgebung nicht eingerichtet",
  "Edit training job": "Trainingsauftrag bearbeiten",
  "Save draft": "Entwurf speichern",
  "Save & queue": "Speichern & starten",
  "Method": "Methode",
  "Hyperparameters": "Hyperparameter",
  "Memory & speed": "Speicher & Tempo",
  "Canceled before any image was generated":
    "Abgebrochen, bevor ein Bild erzeugt wurde",
  "{done} of {total} images": "{done} von {total} Bildern",
  "not generated yet": "noch nicht erzeugt",
  "Download this LoRA": "Dieses LoRA herunterladen",
  "NVIDIA only": "nur NVIDIA",
  "Off (fused kernels)": "Aus (fusionierte Kernel)",
  "On (save VRAM)": "An (VRAM sparen)",
  "needs an NVIDIA GPU":
    "braucht eine NVIDIA-GPU",
  "needs an NVIDIA GPU (Ada or newer)":
    "braucht eine NVIDIA-GPU (Ada oder neuer)",
  "this model has none":
    "dieses Modell hat keinen",
  "8-bit float (fp8)":
    "8-Bit-Gleitkomma (fp8)",
  "8-bit (int8)":
    "8-Bit (int8)",
  "FLUX.2 Klein (base, 4B)":
    "FLUX.2 Klein (Basis, 4 Mrd.)",
  "Images are being generated":
    "Es werden Bilder erzeugt",
  "= 1 image":
    "= 1 Bild",
  "= {n} images":
    { one: "= 1 Bild", other: "= {n} Bilder" },
  "Length & learning rate": "Dauer & Lernrate",
  "Dataset": "Datensatz",
  "Add query": "Abfrage hinzufügen",
  "Remove query": "Abfrage entfernen",
  "invalid query": "ungültige Abfrage",
  "Empty query = every image in the library.": "Leere Abfrage = alle Bilder der Bibliothek.",
  "Total steps": "Schritte gesamt",
  "Learning rate": "Lernrate",
  "Batch size": "Batchgröße",
  "Gradient accumulation": "Gradienten-Akkumulation",
  "Rank": "Rang",
  "Train text encoder": "Text-Encoder trainieren",
  "Checkpoints": "Checkpoints",
  "Checkpoint every": "Checkpoint alle",
  "Cache latents": "Latents zwischenspeichern",
  "Random crop": "Zufälliger Ausschnitt",
  "Resolutions":
    "Auflösungen",
  "Crops & flips":
    "Zuschnitt & Spiegeln",
  "Max aspect ratio": "Max. Seitenverhältnis",
  "Horizontal flip probability": "Spiegel-Wahrscheinlichkeit",
  "Trigger word": "Triggerwort",
  "Only captions tagged": "Nur Bildtexte mit Meta-Tag",
  "Skip captions tagged": "Bildtexte überspringen mit Meta-Tag",
  "Only instructions tagged": "Nur Anweisungen mit Meta-Tag",
  "Skip instructions tagged": "Anweisungen überspringen mit Meta-Tag",
  "Comma-separated meta tags whose instructions are never used. Applied after the include list, so it also removes instructions the list let in.":
    "Kommagetrennte Meta-Tags, deren Anweisungen nie verwendet werden. Wird nach der Einschlussliste angewendet und entfernt daher auch Anweisungen, die diese durchgelassen hat.",
  "Comma-separated meta tags whose captions are never used. Applied after the include list, so it also removes captions the list let in.":
    "Kommagetrennte Meta-Tags, deren Bildtexte nie verwendet werden. Wird nach der Einschlussliste angewendet und entfernt daher auch Bildtexte, die diese zugelassen hat.",
  "Always include": "Immer enthalten",
  "Skip tag groups tagged": "Tag-Gruppen überspringen mit Meta-Tag",
  "Comma-separated meta tags naming whole tag groups to ignore: a tag placed only in such a group never reaches a prompt. The tags stay on your items.":
    "Kommagetrennte Meta-Tags, die ganze Tag-Gruppen benennen, die ignoriert werden: Ein Tag, das nur in einer solchen Gruppe liegt, erreicht nie einen Prompt. Die Tags bleiben an den Objekten.",
  "Min tags per prompt": "Min. Tags pro Prompt",
  "Max tags per prompt": "Max. Tags pro Prompt",
  "Pick probability": "Auswahlwahrscheinlichkeit",
  "Uniform": "Gleichverteilt",
  "Balance rare tags": "Seltene Tags ausgleichen",
  "Frequency measured in": "Häufigkeit gemessen in",
  "Training data": "Trainingsdaten",
  "Previous step": "Vorheriger Schritt",
  "Next step": "Nächster Schritt",
  "(empty prompt)": "(leerer Prompt)",
  "Show each step's min/max micro-batch loss":
    "Min/Max-Verlust der Mikro-Batches je Schritt anzeigen",
  "Expand graph": "Graph vergrößern",
  "Collapse graph": "Graph verkleinern",
  "steps/s": "Schritte/s",
  "Smooth the line (EMA)": "Linie glätten (EMA)",
  "Whole library": "Gesamte Bibliothek",
  "Weight loss by tag rarity": "Loss nach Tag-Seltenheit gewichten",
  "Shuffle tag order": "Tag-Reihenfolge mischen",
  "Caption dropout": "Prompt-Dropout",
  "Generate every": "Generieren alle",
  "Negative prompt": "Negativ-Prompt",
  "Nothing (trigger word only)": "Nichts (nur das Triggerwort)",
  "Every prompt is the trigger word and nothing else, so every selected picture is in the run whatever it carries. Tag and caption selection do not apply.": "Jeder Prompt ist nur das Triggerwort, also ist jedes ausgewählte Bild im Lauf, ganz gleich was es trägt. Tag- und Beschreibungsauswahl gelten nicht.",
  "Every prompt would be EMPTY — with no text at all, there is nothing for the model to bind what it sees to. Set a trigger word below.": "Jeder Prompt wäre LEER — ohne Text gibt es nichts, woran das Modell das Gesehene binden kann. Setze unten ein Triggerwort.",
  "Caption + tags": "Beschreibung + Tags",
  "Pause (saves a checkpoint)": "Pausieren (speichert einen Checkpoint)",
  "{d} trained": "{d} trainiert",
  "Training started": "Training gestartet",
  "Training resumed": "Training fortgesetzt",
  "Training paused": "Training pausiert",
  "Training completed": "Training abgeschlossen",
  "Training failed": "Training fehlgeschlagen",
  "Training canceled": "Training abgebrochen",
  "Baseline before training": "Referenz vor dem Training",
  "Checkpoint": "Checkpoint",
  "Download checkpoint": "Checkpoint herunterladen",
  "Delete checkpoint": "Checkpoint löschen",
  "Delete this checkpoint from disk?": "Diesen Checkpoint von der Festplatte löschen?",
  "Extend steps": "Schritte erweitern",
  "Edit steps": "Schritte ändern",
  "Base model": "Basismodell",
  "LoRAs": "LoRAs",
  "Edit this model": "Dieses Modell bearbeiten",
  "Edit model": "Modell bearbeiten",
  "Edit LoRA": "LoRA bearbeiten",
  "Edit this LoRA": "Dieses LoRA bearbeiten",
  "Unlock": "Entsperren",
  "Lock": "Sperren",
  "Unlock — deleting the job will take this LoRA with it": "Entsperren – beim Löschen des Jobs verschwindet dieses LoRA mit",
  "Lock — keeps this LoRA when the job is deleted": "Sperren – behält dieses LoRA, wenn der Job gelöscht wird",
  "Lock — protects this checkpoint from deletion, from the keep-last rule, and from the job being deleted": "Sperren – schützt diesen Checkpoint vor dem Löschen, vor der Behalte-die-letzten-Regel und vor dem Löschen des Jobs",
  "Add LoRA": "LoRA hinzufügen",
  "Click to use this value for the next generation": "Klicken, um diesen Wert für die nächste Generierung zu übernehmen",
  "Output": "Ausgabe",
  "Size presets": "Größen-Vorlagen",
  "Random seed": "Zufälliger Seed",
  "A new seed is drawn each time you click Generate; the field below shows the seed used for the last generation.": "Bei jedem Klick auf Generieren wird ein neuer Seed gezogen; das Feld darunter zeigt den zuletzt verwendeten Seed.",
  "Remove this generation and its images?": "Diese Generierung und ihre Bilder entfernen?",
  "Open the image in a new tab": "Das Bild in einem neuen Tab öffnen",
  "Remove the selected images? They cannot be recovered.": "Die ausgewählten Bilder entfernen? Sie können nicht wiederhergestellt werden.",
  "Remove the selected images (a generation that is still running stays)": "Die ausgewählten Bilder entfernen (eine noch laufende Generierung bleibt)",
  "Stop the selected generations (the images they have made are kept)": "Die ausgewählten Generierungen abbrechen (bereits erzeugte Bilder bleiben)",
  "Put every setting that made this picture into the form": "Alle Einstellungen, die dieses Bild erzeugt haben, ins Formular übernehmen",
  "Use all settings": "Alle Einstellungen übernehmen",
  "Preview the selected image (Space)": "Vorschau des ausgewählten Bilds (Leertaste)",
  "Image {i} of {n}": "Bild {i} von {n}",
  "Up next": "Als Nächstes",
  "Add to the queue": "In die Warteschlange aufnehmen",
  "A training job is running": "Ein Trainingsauftrag läuft",
  "Drag to change the queue order": "Ziehen, um die Reihenfolge der Warteschlange zu ändern",
  "How the drafts below are ordered":
    "Wie die Entwürfe darunter sortiert sind",
  "Newest first":
    "Neueste zuerst",
  "Manual order":
    "Manuelle Reihenfolge",
  "Drag to reorder — or into Up next to queue the job":
    "Ziehen zum Umsortieren — oder nach „Als Nächstes“, um den Job einzureihen",
  "Remove every finished job, with its checkpoints and samples":
    "Alle abgeschlossenen Jobs mit ihren Checkpoints und Beispielbildern entfernen",
  "Drag into Up next to queue the job": "In „Als Nächstes“ ziehen, um den Auftrag einzureihen",
  "Drop here to put the job on hold.": "Hier ablegen, um den Auftrag zurückzustellen.",
  "Prepare": "Vorbereiten",
  "Keep the last": "Behalte die letzten",
  "When a new snapshot is written the oldest of these is deleted, so the window never grows. A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk. The resumable checkpoint is kept outside this limit and never counts against it.": "Wird ein neuer Snapshot geschrieben, verschwindet der älteste aus diesem Fenster — es wächst also nie. Ein LoRA-Snapshot ist klein (einige zehn MB), ein Dutzend davon ist problemlos möglich; ein Full-Finetune-Snapshot ist so groß wie das ganze Modell, da sind zwei oder drei schon viel Platz. Der Fortsetzungs-Checkpoint liegt außerhalb dieser Grenze und zählt nie dagegen.",
  "Also keep one in": "Behalte außerdem einen von",
  "A rolling window at the end of the run. 0 keeps none by recency.": "Ein gleitendes Fenster am Ende des Laufs. 0 behält nichts nach Aktualität.",
  "Kept for good, on top of the window above.": "Bleiben dauerhaft erhalten, zusätzlich zum Fenster darüber.",
  "A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk.": "Ein LoRA-Snapshot ist klein (einige zehn MB), ein Dutzend davon ist problemlos möglich; ein Full-Finetune-Snapshot ist so groß wie das ganze Modell, da sind zwei oder drei schon viel Platz.",
  "in 1 step": "in 1 Schritt",
  "in {n} steps":
    { one: "in 1 Schritt", other: "in {n} Schritten" },
  "Keep as checkpoint": "Als Checkpoint behalten",
  "Backward": "Rückwärts",
  "warmup": "Aufwärmen",
  "Settings changed": "Einstellungen geändert",
  "Dataset changed": "Datensatz geändert",
  "{n} items added":
    { one: "1 Objekt hinzugefügt", other: "{n} Objekte hinzugefügt" },
  "{n} items removed":
    { one: "1 Objekt entfernt", other: "{n} Objekte entfernt" },
  "Measured over the last steps of this run": "Über die letzten Schritte dieses Laufs gemessen",
  "about {d} left": "noch etwa {d}",
  "The images this run trains on, sorted into aspect-ratio buckets": "Die Bilder, auf denen dieser Lauf trainiert, sortiert in Seitenverhältnis-Buckets",
  "{n} images":
    { one: "1 Bild", other: "{n} Bilder" },
  "{n} from video":
    { one: "1 aus Video", other: "{n} aus Video" },
  "{n} buckets":
    { one: "1 Bucket", other: "{n} Buckets" },
  "Training job settings": "Einstellungen des Trainingsauftrags",
  "Save as new job": "Als neuen Auftrag speichern",
  "Hide system statistics": "Systemstatistik ausblenden",
  "Show system statistics": "Systemstatistik anzeigen",
  "loading model": "Modell wird geladen",
  "caching latents": "Latents werden zwischengespeichert",
  "Degradation": "Verschlechterung",
  "Add variant": "Variante hinzufügen",
  "Remove every variant from this job": "Alle Varianten aus diesem Job entfernen",
  "Remove this variant": "Diese Variante entfernen",
  "JPEG re-encode": "JPEG-Neukodierung",
  "Video codec (h264 / h265)": "Video-Codec (h264 / h265)",
  "Resolution loss": "Auflösungsverlust",
  "JPEG": "JPEG",
  "video codec": "Video-Codec",
  "resolution loss": "Auflösungsverlust",
  "Chroma subsampling": "Farbunterabtastung",
  "How much color detail is thrown away. 4:2:0 is what almost every real JPEG uses.": "Wie viele Farbdetails weggeworfen werden. 4:2:0 nutzt praktisch jedes echte JPEG.",
  "Codec": "Codec",
  "CRF": "CRF",
  "The codec's quality number, counting the other way round: HIGHER is worse. Above about 32 a frame visibly falls apart.": "Die Qualitätszahl des Codecs, die andersherum zählt: HÖHER ist schlechter. Über etwa 32 zerfällt ein Bild sichtbar.",
  "Scale": "Skalierung",
  "Nearest gives the hard, blocky look of a badly upscaled screenshot; bilinear the soft one.": "Nächster Nachbar ergibt den harten, klotzigen Look eines schlecht hochskalierten Screenshots; bilinear den weichen.",
  "Bilinear": "Bilinear",
  "Bicubic": "Bikubisch",
  "Lanczos": "Lanczos",
  "Passes": "Durchgänge",
  "Visits per clean visit": "Besuche je sauberem Besuch",
  "How often this variant is drawn beside the picture it was made from. 0.25 = one degraded visit per four clean ones.": "Wie oft diese Variante neben dem Bild gezogen wird, aus dem sie gemacht wurde. 0,25 = ein verschlechterter Besuch auf vier saubere.",
  "Cached variations per picture": "Zwischengespeicherte Varianten je Bild",
  "How many separately-drawn values each picture gets. 1 already spreads the range across the dataset; more spreads it within one picture, and multiplies the cache.": "Wie viele getrennt gezogene Werte jedes Bild bekommt. 1 verteilt den Bereich bereits über den Datensatz; mehr verteilt ihn innerhalb eines Bildes und vervielfacht den Zwischenspeicher.",
  "jpeg_artifacts, low_quality": "jpeg_artifacts, low_quality",
  "Always in this sample's prompt: never dropped by the random tag pick, the tag cap, or caption dropout.": "Immer im Prompt dieses Beispiels: wird nie von der zufälligen Tag-Auswahl, der Tag-Obergrenze oder dem Beschreibungs-Dropout verworfen.",
  "Remove tags if present": "Tags entfernen, falls vorhanden",
  "masterpiece, absurdres": "masterpiece, absurdres",
  "Which pictures": "Welche Bilder",
  "Only pictures tagged": "Nur Bilder mit Tag",
  "Never pictures tagged": "Nie Bilder mit Tag",
  "Wins over the line above. Use it to leave pictures alone that are already marked as poor.": "Sticht die Zeile darüber. Damit bleiben Bilder unangetastet, die bereits als schlecht markiert sind.",
  "The preview failed": "Die Vorschau ist fehlgeschlagen",
  "Select an item in the library to preview this on.": "Wähle in der Bibliothek ein Objekt aus, an dem das gezeigt werden kann.",
  "gentlest": "am mildesten",
  "harshest": "am härtesten",
  "Variants": "Varianten",
  "Save the current variants, or load a saved set": "Die aktuellen Varianten speichern oder einen gespeicherten Satz laden",
  "Save current variants": "Aktuelle Varianten speichern",
  "Add a variant first": "Füge zuerst eine Variante hinzu",
  "Load this set, replacing the variants in this job": "Diesen Satz laden und die Varianten dieses Jobs ersetzen",
  "Of every 100 visits to a picture this applies to, {clean} are clean and the rest are degraded: {parts}.": "Von je 100 Besuchen eines Bildes, für das dies gilt, sind {clean} sauber und der Rest verschlechtert: {parts}.",
  "A variant with a tag filter applies to fewer pictures than the queries select, so its share is of those.": "Eine Variante mit Tag-Filter gilt für weniger Bilder, als die Abfragen auswählen; ihr Anteil bezieht sich auf diese.",
  "About {n} degraded files will be cached.": "Etwa {n} verschlechterte Dateien werden zwischengespeichert.",
  "Preset": "Vorlage",
  "Presets": "Vorlagen",
  "Preset name": "Name der Vorlage",
  "Save these settings as a preset, or load one": "Diese Einstellungen als Vorlage speichern oder eine laden",
  "Save current settings": "Aktuelle Einstellungen speichern",
  "Start new jobs from this preset": "Neue Jobs mit dieser Vorlage starten",
  "Delete this preset": "Diese Vorlage löschen",
  "Cosine": "Kosinus",
  "Base models": "Basismodelle",
  "1 result": "1 Ergebnis",
  "{n} results":
    { one: "1 Ergebnis", other: "{n} Ergebnisse" },
  "Delete every result in this session": "Alle Ergebnisse dieser Sitzung löschen",
  "Delete all {n} results from this session? The generated images go with them.": "Alle {n} Ergebnisse dieser Sitzung löschen? Die erzeugten Bilder verschwinden mit ihnen.",
  "sampling": "Testbilder werden erzeugt",
  "What does this do?": "Was macht das?",
  "This model's repository is gated: accept its license on the model page and set a Hugging Face access token, or the download will fail.":
    "Das Repository dieses Modells ist gesperrt: Akzeptiere die Lizenz auf der Modellseite und hinterlege ein Hugging-Face-Zugriffstoken, sonst schlägt der Download fehl.",
  "Click to use this prompt for the next generation": "Klicken, um diesen Prompt für die nächste Generierung zu übernehmen",
  "(no prompt)": "(kein Prompt)",
  "Click to use this negative prompt for the next generation": "Klicken, um diesen negativen Prompt für die nächste Generierung zu übernehmen",
  "Time so far, including loading the model": "Bisherige Zeit, inklusive Laden des Modells",
  "Total time, including loading the model": "Gesamtzeit, inklusive Laden des Modells",
  "Remove from the queue": "Aus der Warteschlange entfernen",
  "Select to copy": "Zum Kopieren markieren",
  "generation failed": "Generierung fehlgeschlagen",
  "Sampler steps": "Sampler-Schritte",
  "CFG scale": "CFG-Skala",
  "This model isn't downloaded yet, and downloads are switched off": "Dieses Modell ist noch nicht heruntergeladen, und Downloads sind ausgeschaltet",
  "Loss": "Verlust",
  "LoRA only": "Nur LoRA",
  "Native training resolution of these weights. Leave empty for the architecture's own.": "Native Trainingsauflösung dieser Gewichte. Leer lassen für die der Architektur.",
  "Includes 1 model you added.": "Enthält 1 selbst hinzugefügtes Modell.",
  "Includes": "Enthält",
  "models you added.": "selbst hinzugefügte Modelle.",
  "Open this model's page on Hugging Face": "Die Seite dieses Modells auf Hugging Face öffnen",
  "Remove this model": "Dieses Modell entfernen",
  "Based on": "Basiert auf",
  "/path/to/model (diffusers folder or .safetensors)": "/pfad/zum/modell (diffusers-Ordner oder .safetensors)",
  "owner/repo": "besitzer/repo",
  "Add model": "Modell hinzufügen",
  "On disk": "Auf der Festplatte",
  "Path missing": "Pfad fehlt",
  "Continue this download where it stopped": "Diesen Download dort fortsetzen, wo er abgebrochen ist",
  "Partly downloaded": "Teilweise heruntergeladen",
  "Discard partial download": "Unvollständigen Download verwerfen",
  "This path no longer exists": "Diesen Pfad gibt es nicht mehr",
  "Remove from the list (the file is left alone)": "Aus der Liste entfernen (die Datei bleibt unangetastet)",
  "The base model this LoRA was trained for": "Das Basismodell, für das dieses LoRA trainiert wurde",
  "/path/to/lora.safetensors": "/pfad/zum/lora.safetensors",
  "Download this checkpoint": "Diesen Checkpoint herunterladen",
  "Delete this checkpoint from disk": "Diesen Checkpoint von der Festplatte löschen",
  "Relative sampling probability: a weight-2 query's images are drawn twice as often as a weight-1 query's.": "Relative Ziehungswahrscheinlichkeit: Aus einer Abfrage mit Gewicht 2 werden Bilder doppelt so oft gezogen wie aus einer mit Gewicht 1.",
  "Steps": "Schritte",
  "Text encoder": "Text-Encoder",
  "trained": "trainiert",
  "Prompts": "Prompts",
  "Samples": "Testbilder",
  "Training log": "Trainingsprotokoll",
  "No output yet.": "Noch keine Ausgabe.",
  "about {v} of GPU memory": "etwa {v} GPU-Speicher",
  "more than this machine's {m}": "mehr als die {m} dieser Maschine",
  "e.g. watercolor style LoRA": "z. B. LoRA im Aquarellstil",
  "Model-specific": "Modellspezifisch",
  "Optimization": "Optimierung",
  "LR schedule": "LR-Zeitplan",
  "Constant": "Konstant",
  "Linear decay": "Lineares Abklingen",
  "Constant + warmup": "Konstant + Warmup",
  "Warmup steps": "Warmup-Schritte",
  "Ramp the learning rate up over the first N steps. Leave empty for no warmup.": "Die Lernrate über die ersten N Schritte hochfahren. Leer lassen für kein Warmup.",
  "bf16 is the safe modern default. fp32 doubles memory (automatic fallback on Macs without bf16); avoid fp16 for training.": "bf16 ist der sichere moderne Standard. fp32 verdoppelt den Speicher (automatischer Rückfall auf Macs ohne bf16); fp16 fürs Training meiden.",
  "Makes sampling, crops and tag picks reproducible.": "Macht Testbilder, Zuschnitte und Tag-Auswahl reproduzierbar.",
  "LoRA": "LoRA",
  "Scales the adapter's effect; the common convention is alpha = rank. Lower alpha = weaker influence at the same rank.": "Skaliert die Wirkung des Adapters; üblich ist Alpha = Rang. Niedrigeres Alpha = schwächerer Einfluss bei gleichem Rang.",
  "Helps the model learn a NEW trigger word, at higher overfitting risk. Guarded: it uses a lower learning rate and stops partway through training.": "Hilft dem Modell, ein NEUES Triggerwort zu lernen, bei höherem Überanpassungsrisiko. Abgesichert: niedrigere Lernrate und vorzeitiger Stopp im Training.",
  "Text encoder LR": "Lernrate Text-Encoder",
  "Left empty: half the main learning rate.": "Leer gelassen: die Hälfte der Haupt-Lernrate.",
  "Stop TE after": "TE stoppen nach",
  "Include the large encoder": "Den großen Encoder einbeziehen",
  "T5-XXL, the encoder that reads the whole prompt — most of the memory and most of the effect. Unticked, only the small CLIP-L trains: cheap, and what most FLUX LoRA tools mean by training the text encoder.": "T5-XXL, der Encoder, der den ganzen Prompt liest — der Großteil des Speichers und der Wirkung. Abgewählt trainiert nur der kleine CLIP-L: billig, und das, was die meisten FLUX-LoRA-Werkzeuge unter Text-Encoder-Training verstehen.",
  "of total steps": "der Gesamtschritte",
  "Keep step snapshots": "Schritt-Snapshots behalten",
  "Save a permanent snapshot every N steps, so the best-looking step can be picked afterwards. Off: only the resumable 'last' checkpoint is kept.": "Alle N Schritte einen dauerhaften Snapshot speichern, damit sich hinterher der beste Schritt auswählen lässt. Aus: nur der fortsetzbare „letzte“ Checkpoint bleibt erhalten.",
  "Gradient checkpointing": "Gradient-Checkpointing",
  "Trades ~25% speed for a large VRAM saving. Recommended for full finetunes and big models.": "Tauscht rund 25 % Geschwindigkeit gegen eine große VRAM-Ersparnis. Empfohlen für vollständige Finetunings und große Modelle.",
  "Attention slicing": "Attention-Slicing",
  "Half-precision master weights": "Master-Gewichte in halber Präzision",
  "Keeps the trained weights and their gradients at 16 bits instead of 32. What the rounding drops is carried to the next update, so the run learns what it would have learned; the cost is one more buffer of the same width.":
    "Hält die trainierten Gewichte und ihre Gradienten mit 16 statt 32 Bit. Was beim Runden wegfällt, wird in die nächste Aktualisierung übernommen, sodass der Lauf lernt, was er sonst gelernt hätte; der Preis ist ein weiterer Puffer derselben Breite.",
  "only for a full finetune": "nur für ein vollständiges Finetuning",
  "nothing to halve at full precision": "bei voller Präzision gibt es nichts zu halbieren",
  "Prodigy cannot be stepped one weight at a time": "Prodigy lässt sich nicht Gewicht für Gewicht ausführen",
  "Base model quantization": "Quantisierung des Basismodells",
  "None (full precision)": "Keine (volle Genauigkeit)",
  "4-bit (NF4)": "4 Bit (NF4)",
  "Optimizer": "Optimierer",
  "Images are sorted into width/height buckets of equal area so nothing gets squashed. This caps how extreme the buckets get (2 = up to 2:1 and 1:2).": "Bilder werden in Breite/Höhe-Buckets gleicher Fläche einsortiert, damit nichts gequetscht wird. Das hier begrenzt, wie extrem die Buckets werden (2 = bis 2:1 und 1:2).",
  "Never flip images whose tags are marked": "Nie spiegeln bei Tags mit Meta-Tag",
  "Comma-separated META tags. Any tag the library marks with one of these switches mirroring off for the pictures carrying that tag — so the rule is stated once in the Tags tab rather than listed here.": "Kommagetrennte META-Tags. Jeder Tag, den die Bibliothek so kennzeichnet, schaltet das Spiegeln für die Bilder mit diesem Tag ab — die Regel steht also einmal im Tags-Reiter statt hier aufgelistet.",
  "Always include tags marked": "Tags mit Meta-Tag immer aufnehmen",
  "Comma-separated META tags. Any tag the library marks with one of these is never dropped by the random pick — again, only where the image actually has that tag.": "Kommagetrennte META-Tags. Jeder Tag, den die Bibliothek so kennzeichnet, wird von der Zufallsauswahl nie verworfen — wieder nur dort, wo das Bild den Tag tatsächlich hat.",
  "Exclude tags marked": "Tags mit Meta-Tag ausschließen",
  "Comma-separated META tags. Any tag the library marks with one of these is stripped from prompts.": "Kommagetrennte META-Tags. Jeder Tag, den die Bibliothek so kennzeichnet, wird aus den Prompts entfernt.",
  "Remove tags marked": "Tags mit Meta-Tag entfernen",
  "Comma-separated META tags. Any tag the library marks with one of these comes off this sample.": "Kommagetrennte META-Tags. Jeder Tag, den die Bibliothek so kennzeichnet, entfällt bei dieser Kopie.",
  "Only pictures whose tags are marked": "Nur Bilder mit Tags mit Meta-Tag",
  "Comma-separated META tags — the same rule as the line above, said once in the library rather than tag by tag here.": "Kommagetrennte META-Tags — dieselbe Regel wie die Zeile darüber, einmal in der Bibliothek gesagt statt hier Tag für Tag.",
  "Never pictures whose tags are marked": "Nie Bilder mit Tags mit Meta-Tag",
  "Comma-separated META tags. Wins over both lines above.": "Kommagetrennte META-Tags. Schlägt beide Zeilen darüber.",
  "The same veto, said once in the library instead of tag by tag here. Any tag the Tags tab marks with one of these meta tags switches mirroring off for every picture carrying that tag.\n\nIt is worth the indirection for the reason a list of names goes stale: “text”, “logo”, “signature”, “left-handed”, a dozen characters with an eyepatch — the list in a job's settings is right the day it is written and wrong the next time somebody adds a tag it should have held. Marking the tags themselves puts the fact where the tag is, so a tag added later carries it into every run automatically, and a job written before that tag existed still does the right thing.\n\nBoth lists apply: a picture is left unmirrored if it carries a tag named above OR a tag marked here.":
    "Dasselbe Veto, einmal in der Bibliothek gesagt statt hier Tag für Tag. Jeder Tag, den der Tags-Reiter mit einem dieser Meta-Tags kennzeichnet, schaltet das Spiegeln für jedes Bild mit diesem Tag ab.\n\nDer Umweg lohnt sich aus dem Grund, aus dem eine Namensliste veraltet: „text“, „logo“, „signature“, „left-handed“, ein Dutzend Figuren mit Augenklappe — die Liste in den Einstellungen eines Jobs stimmt an dem Tag, an dem sie geschrieben wird, und stimmt nicht mehr, sobald jemand einen Tag hinzufügt, der darin hätte stehen müssen. Die Tags selbst zu kennzeichnen legt die Tatsache dorthin, wo der Tag ist: Ein später hinzugefügter Tag trägt sie von allein in jeden Lauf, und ein Job, der vor diesem Tag geschrieben wurde, tut trotzdem das Richtige.\n\nBeide Listen gelten: Ein Bild bleibt ungespiegelt, wenn es einen oben genannten Tag ODER einen hier gekennzeichneten Tag trägt.",
  "The rule above, named by what the library says ABOUT a tag rather than by the tag. Any tag marked with one of these meta tags bypasses the random pick — again only where the image actually has it.\n\nA meta tag put on “watermark”, “signature” and “logo” once means every run treats them that way, including runs written before the third of them existed. The two lists are unioned, so naming a tag here and above is simply the same instruction twice.":
    "Die Regel darüber, benannt nach dem, was die Bibliothek ÜBER einen Tag sagt, statt nach dem Tag selbst. Jeder Tag, der mit einem dieser Meta-Tags gekennzeichnet ist, umgeht die Zufallsauswahl — wieder nur dort, wo das Bild ihn tatsächlich hat.\n\nEin Meta-Tag, einmal auf „watermark“, „signature“ und „logo“ gesetzt, heißt, dass jeder Lauf sie so behandelt — auch Läufe, die geschrieben wurden, bevor es den dritten davon gab. Die beiden Listen werden vereinigt; einen Tag hier und darüber zu nennen ist also schlicht dieselbe Anweisung zweimal.",
  "The same, one level up: any tag the library marks with one of these meta tags is stripped from every prompt.\n\nThis is the one to reach for when the exclusions are a KIND of tag rather than a list of them. Quality ratings, scan notes, the booru's own housekeeping words — mark them “noprompt” in the Tags tab and every run drops them, instead of every job carrying a list that has to grow with the vocabulary.\n\nIt is not the same as a skipped tag GROUP below. This one is about the tag wherever it appears; that one is about a grouping on one item, and a tag placed in an excluded group and also somewhere else survives it.":
    "Dasselbe eine Ebene höher: Jeder Tag, den die Bibliothek mit einem dieser Meta-Tags kennzeichnet, wird aus jedem Prompt entfernt.\n\nDanach greift man, wenn die Ausschlüsse eine ART von Tag sind statt einer Liste von Tags. Qualitätsbewertungen, Scan-Notizen, die Hauswörter einer Booru — kennzeichne sie im Tags-Reiter mit „noprompt“, und jeder Lauf lässt sie weg, statt dass jeder Job eine Liste mitschleppt, die mit dem Vokabular mitwachsen muss.\n\nDas ist nicht dasselbe wie eine übersprungene Tag-GRUPPE weiter unten. Hier geht es um den Tag, wo immer er auftaucht; dort um eine Gruppierung auf einem Objekt, und ein Tag, der in einer ausgeschlossenen Gruppe UND anderswo liegt, überlebt sie.",
  "The list above, named by what the library says about a tag. Any tag marked with one of these meta tags comes off this sample.\n\nWhat it is for is that the claims a degraded copy no longer supports are a CATEGORY, not a list: 'masterpiece', 'absurdres', 'high quality', 'official art' and whatever the next dump adds are all \"a claim about the picture's quality\". Marking them once means every variant of every job drops them, and the same mark can then say something different per method — a 'resolution_claim' mark belongs on a resize variant's list, a 'fidelity_claim' on a JPEG one.":
    "Die Liste darüber, benannt nach dem, was die Bibliothek über einen Tag sagt. Jeder Tag, der mit einem dieser Meta-Tags gekennzeichnet ist, entfällt bei dieser Kopie.\n\nWofür das gut ist: Die Behauptungen, die eine degradierte Kopie nicht mehr stützt, sind eine KATEGORIE und keine Liste. „masterpiece“, „absurdres“, „high quality“, „official art“ und was der nächste Dump noch hinzufügt, sind alle „eine Behauptung über die Qualität des Bildes“. Einmal gekennzeichnet, lässt jede Variante jedes Jobs sie weg — und dieselbe Kennzeichnung kann dann je nach Methode etwas anderes sagen: Eine Kennzeichnung „resolution_claim“ gehört auf die Liste einer Resize-Variante, ein „fidelity_claim“ auf die einer JPEG-Variante.",
  "The line above by mark rather than by name: a picture is degraded only if it carries a tag the library marks this way.\n\nChecked against the picture's effective tags, so a tag it only carries by implication counts too. With both lists empty, every picture is fair game.":
    "Die Zeile darüber nach Kennzeichnung statt nach Namen: Ein Bild wird nur degradiert, wenn es einen Tag trägt, den die Bibliothek so kennzeichnet.\n\nGeprüft wird gegen die effektiven Tags des Bildes, ein Tag also, den es nur per Implikation trägt, zählt mit. Bleiben beide Listen leer, ist jedes Bild Freiwild.",
  "The veto by mark, and it wins over both lines above exactly as the named list does.\n\nThe pair is what makes a degrading run safe on a mixed library: mark the pictures that are already poor — a 'low_quality' or 'rescan' mark on the tags that say so — and no variant can ever degrade one of them further, however broadly the \"only pictures\" side is drawn.":
    "Das Veto nach Kennzeichnung, und es schlägt beide Zeilen darüber, genau wie es die Namensliste tut.\n\nDas Paar ist es, was einen degradierenden Lauf auf einer gemischten Bibliothek sicher macht: Kennzeichne die Bilder, die ohnehin schon schlecht sind — ein „low_quality“ oder „rescan“ auf den Tags, die das sagen — und keine Variante kann eines davon je weiter degradieren, wie weit die Seite „nur Bilder“ auch gefasst ist.",
  "Never flip images tagged": "Nie spiegeln bei Tag",
  "Comma-separated tags that switch mirroring off for the images carrying them, e.g. 'text'. Everything else still flips.": "Kommagetrennte Tags, die das Spiegeln für die Bilder mit diesen Tags abschalten, z. B. „text“. Alles andere wird weiterhin gespiegelt.",
  "Use alpha as a loss mask": "Alpha als Verlustmaske verwenden",
  "For cut-out images (transparent background): train on the visible pixels and largely ignore the rest. Images without transparency are unaffected.": "Für freigestellte Bilder (transparenter Hintergrund): auf den sichtbaren Pixeln trainieren und den Rest weitgehend ignorieren. Bilder ohne Transparenz bleiben unberührt.",
  "Background weight": "Hintergrundgewicht",
  "Build prompts from": "Prompts bilden aus",
  "What each training prompt is made of: the item's caption text, its tags, caption followed by tags, or nothing but the trigger word.": "Woraus jeder Trainings-Prompt besteht: der Beschriftungstext des Objekts, seine Tags, Beschriftung gefolgt von Tags oder nichts außer dem Triggerwort.",
  "Prepended to every prompt. Use a rare token (e.g. 'ohwx style') you'll later type to invoke the trained concept.": "Wird jedem Prompt vorangestellt. Nimm ein seltenes Token (z. B. „ohwx style“), das du später tippst, um das trainierte Konzept aufzurufen.",
  "Each image trains as the RESULT of one of its instructions, with that instruction's reference images as the input. Items carrying no instruction are left out of the run, and tag selection does not apply.":
    "Jedes Bild trainiert als ERGEBNIS einer seiner Anweisungen, mit deren Referenzbildern als Eingabe. Objekte ohne Anweisung bleiben aus dem Lauf heraus, und die Tag-Auswahl gilt hier nicht.",
  "Tag selection": "Tag-Auswahl",
  "Tags are re-picked and re-shuffled fresh every time an image is visited.": "Tags werden bei jedem Besuch eines Bildes neu gezogen und neu gemischt.",
  "Comma-separated tags stripped from prompts (e.g. quality tags or the concept itself when using a trigger word).": "Kommagetrennte Tags, die aus Prompts entfernt werden (z. B. Qualitäts-Tags oder das Konzept selbst, wenn ein Triggerwort verwendet wird).",
  "no limit": "kein Limit",
  "Lower bound of the random pick. Both limits empty = use all tags.": "Untergrenze der Zufallsauswahl. Beide Grenzen leer = alle Tags verwenden.",
  "Upper bound of the random pick. Picking a random subset each visit teaches tags independently instead of as a fixed clump.": "Obergrenze der Zufallsauswahl. Bei jedem Besuch eine zufällige Teilmenge zu ziehen lehrt Tags einzeln statt als festen Klumpen.",
  "Whether a tag's rarity is measured within the selected training images or across the whole library.": "Ob die Seltenheit eines Tags innerhalb der ausgewählten Trainingsbilder oder über die ganze Bibliothek gemessen wird.",
  "Skip partially matching tags": "Teilweise übereinstimmende Tags überspringen",
  "Standard practice: prevents the model from binding concepts to a fixed tag position.": "Übliche Praxis: verhindert, dass das Modell Konzepte an eine feste Tag-Position bindet.",
  "Underscores to spaces": "Unterstriche zu Leerzeichen",
  "Tag separator": "Tag-Trennzeichen",
  "Joins the prompt parts; comma + space is the standard.": "Verbindet die Teile des Prompts; Komma + Leerzeichen ist der Standard.",
  "Generate preview images with the in-training model to watch progress in the job's timeline.": "Vorschaubilder mit dem gerade trainierten Modell erzeugen, um den Fortschritt in der Zeitleiste des Jobs zu verfolgen.",
  "Generate test samples": "Testbilder erzeugen",
  "Sample seed": "Seed für Testbilder",
  "Fixed per prompt so consecutive samples differ only by training progress.": "Pro Prompt fest, damit sich aufeinanderfolgende Testbilder nur durch den Trainingsfortschritt unterscheiden.",
  "Test prompts": "Test-Prompts",
  "negative prompt (optional)": "negativer Prompt (optional)",
  "Use the shared size for this prompt": "Für diesen Prompt die gemeinsame Größe verwenden",
  "Give this prompt its own size": "Diesem Prompt eine eigene Größe geben",
  "Remove this prompt": "Diesen Prompt entfernen",
  "Add prompt": "Prompt hinzufügen",
  "Remove every prompt from this job": "Alle Prompts aus diesem Job entfernen",
  "Remove all": "Alle entfernen",
  "Save the current prompts, or load a saved set": "Die aktuellen Prompts speichern oder einen gespeicherten Satz laden",
  "Write a prompt first": "Zuerst einen Prompt schreiben",
  "Save current prompts": "Aktuelle Prompts speichern",
  "Set name": "Name des Satzes",
  "Load this set into the job": "Diesen Satz in den Job laden",
  "Delete this set": "Diesen Satz löschen",
  "train from scratch": "von Grund auf trainieren",
  "Finished result": "Fertiges Ergebnis",
  "Intermediate checkpoint": "Zwischen-Checkpoint",
  "Continues": "Setzt fort",
  "Train on video frames": "Auf Videobildern trainieren",
  "Off, a video the queries match is skipped. On, its frames are extracted while the dataset is built, trained on as images, and deleted with the run.":
    "Aus wird ein passendes Video übersprungen. An werden beim Erstellen des Datensatzes seine Einzelbilder extrahiert, als Bilder trainiert und mit dem Lauf wieder gelöscht.",
  "One frame every": "Ein Bild alle",
  "Interval unit": "Einheit des Abstands",
  "Seconds follows the clock whatever the frame rate; frames counts the file's own frames.":
    "Sekunden folgt der Uhr, unabhängig von der Bildrate; Einzelbilder zählt die Bilder der Datei selbst.",
  "Drop repeated frames": "Wiederholte Bilder verwerfen",
  "A shot held for five seconds is one picture, not five. Each kept frame is compared with the ones already kept from the same video.":
    "Eine fünf Sekunden gehaltene Einstellung ist ein Bild, nicht fünf. Jedes behaltene Bild wird mit den bereits behaltenen desselben Videos verglichen.",
  "Label each block with": "Jeden Block beschriften mit",
  "The subjects it is about": "Den Motiven, um die es geht",
  "The tag group's name": "Dem Namen der Tag-Gruppe",
  "Between groups": "Zwischen Gruppen",
  "Group tags by tag group": "Tags nach Tag-Gruppe gruppieren",
  "Lay the picked tags out one block per tag group instead of one flat list, so what belongs to the same thing in the picture stays together.": "Die gewählten Tags als einen Block pro Tag-Gruppe schreiben statt als eine flache Liste, damit zusammengehört, was zum selben Ding im Bild gehört.",
  "Put between blocks. A newline by default, which is what makes them read as separate statements.": "Kommt zwischen die Blöcke. Standardmäßig ein Zeilenumbruch – der lässt sie als getrennte Aussagen lesen.",
  "Includes {n} models you added.":
    { one: "Enthält 1 selbst hinzugefügtes Modell.",
      other: "Enthält {n} selbst hinzugefügte Modelle." },
  // The job list's selection bar.
  "Remove {n} training jobs? Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone.":
    "{n} Trainingsaufträge entfernen? Ihre Checkpoints, Testbilder und trainierten Ergebnisse werden mit entfernt, und das lässt sich nicht rückgängig machen. Ausgenommen ist alles Gesperrte, das in der LoRA-Liste erhalten bleibt.",
  "Remove the selected jobs — a running job is left alone":
    "Ausgewählte Aufträge entfernen — ein laufender bleibt unangetastet",
  "Remove the selected jobs, with their checkpoints and samples":
    "Ausgewählte Aufträge mitsamt Checkpoints und Testbildern entfernen",
  // The Models page: adding a model, and removing one.
  "Remove “{name}” from the model list?":
    "„{name}“ aus der Modellliste entfernen?",
  "Delete the downloaded weights as well? They can be downloaded again later.":
    "Auch die heruntergeladenen Gewichte löschen? Sie lassen sich später erneut herunterladen.",
  "Which model these weights are a version of — it decides the engine, the hyperparameters and the memory profile":
    "Von welchem Modell diese Gewichte eine Variante sind — das bestimmt Engine, Hyperparameter und Speicherbedarf",
  "owner/repo, or a path on this machine":
    "owner/repo oder ein Pfad auf diesem Rechner",
  "A Hugging Face repository, or a diffusers folder or .safetensors file on this machine — which one it is is read off what you type.":
    "Ein Hugging-Face-Repository oder ein diffusers-Ordner bzw. eine .safetensors-Datei auf diesem Rechner — was davon es ist, wird aus der Eingabe gelesen.",
  "Read as a path on this machine":
    "Als Pfad auf diesem Rechner gelesen",
  "Read as a Hugging Face repository":
    "Als Hugging-Face-Repository gelesen",
  "Left unnamed, the model is listed under its repository or path":
    "Ohne Namen wird das Modell unter seinem Repository oder Pfad geführt",
  // The Models page's LoRA lists, grouped by architecture.
  "No LoRAs yet — add a file above, or finish a training job.":
    "Noch keine LoRAs — füge oben eine Datei hinzu oder schließe ein Training ab.",
  "These work on any model of this architecture. Each row says which one it was trained for.":
    "Diese funktionieren mit jedem Modell dieser Architektur. Jede Zeile nennt das Modell, für das sie trainiert wurde.",
  // The Evaluate tab: the LoRA rows, and the results grid.
  "Strength":
    "Stärke",
  "no image":
    "kein Bild",
  "Weights": "Gewichte",
  "File": "Datei",
  "Trained for": "Trainiert für",
  "defaults to the file name": "standardmäßig der Dateiname",
  "Waiting…": "Wartet …",
  "Another download is running": "Ein anderer Download läuft",
  "macOS keeps GPU temperature and power for root only. To see them here, allow this one command without a password, then press Try again:":
    "macOS gibt GPU-Temperatur und -Leistung nur an root weiter. Um sie hier zu sehen, erlaube diesen einen Befehl ohne Passwort und drücke dann „Erneut versuchen“:",
  "Check again — no restart needed once the rule is in":
    "Erneut prüfen — nach dem Eintragen der Regel ist kein Neustart nötig",
  "Copied": "Kopiert",
  "Press ⌘C to copy it": "Mit ⌘C kopieren",
  "Write tags as an alias": "Tags als Alias schreiben",
  "Chance of writing a picked tag as one of its aliases instead of its own name, rolled per tag every time an image is visited.":
    "Wahrscheinlichkeit, dass ein gewähltes Tag als eines seiner Aliase statt unter seinem eigenen Namen geschrieben wird — pro Tag bei jedem Besuch eines Bildes neu ausgewürfelt.",
  "Your library's aliases are the other words for one thing — “cat”, “kitty”, “feline”. Assigning any of them stores the canonical name, so every prompt says the same word and the model learns to answer to that word alone; at generation time the others do less, or nothing.\n\nWith this above 0, each picked tag is sometimes written as one of its aliases instead. The roll happens per tag per visit, so one image seen twice reads differently and the whole vocabulary is spread across the run rather than one alias being chosen per tag and then repeated.\n\nOnly the PROMPT changes. Tag matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all keep using the canonical name — so this cannot skew any of them. A tag with no aliases is always written as itself, and 0 is exactly what every run did before this setting existed.":
    "Die Aliase deiner Bibliothek sind die anderen Wörter für dieselbe Sache — „cat“, „kitty“, „feline“. Wird eines davon vergeben, wird der kanonische Name gespeichert, also sagt jeder Prompt dasselbe Wort und das Modell lernt, nur auf dieses eine zu reagieren; beim Generieren bewirken die anderen wenig oder nichts.\n\nÜber 0 wird ein gewähltes Tag manchmal als einer seiner Aliase geschrieben. Gewürfelt wird pro Tag und Besuch, sodass ein zweimal gesehenes Bild unterschiedlich gelesen wird und sich das ganze Vokabular über den Lauf verteilt, statt einen Alias pro Tag einmal zu wählen und zu wiederholen.\n\nNur der PROMPT ändert sich. Tag-Abgleich, Immer-/Ausschlusslisten, Häufigkeitsausgleich, Loss-Gewicht und die Boxen, die ein Zuschnitt enthalten muss, verwenden weiterhin den kanonischen Namen — verzerren kann das also nichts. Ein Tag ohne Aliase wird immer als es selbst geschrieben, und 0 ist genau das, was jeder Lauf vor dieser Einstellung getan hat.",
  "Whether a tag's rarity is measured within the selected training images, across the whole library, or across the whole library plus what each tag has elsewhere.":
    "Ob die Seltenheit eines Tags innerhalb der ausgewählten Trainingsbilder, über die ganze Bibliothek oder über die ganze Bibliothek plus die Bilder gemessen wird, die jedes Tag anderswo hat.",
  "Rarity is relative to some population, and this picks which one.\n\n“Training data” counts only the images this job selected, so balancing works within the set you are actually training on — usually what you want. “Whole library” counts every item you own, which makes a tag that is common in your dataset but rare overall still count as rare. That is occasionally useful when the training set is a deliberate slice of a much larger, differently balanced collection.\n\n“Whole library + count offsets” adds each tag’s highest meta-tag count — the pictures it has somewhere this library is not, counted per site on the tag’s meta tags (“tumblr 50”, “twitter 100”), of which the largest single figure is used, never the sum, since the sites count overlapping pictures. Nowhere else in the app is that number added to a count, because a total including it would be a claim about somewhere else; for BALANCING it is often the honest one. A tag with four pictures here and forty thousand where they came from is not a rare word, and treating it as rare spends the run teaching the model something it already knows.":
    "Seltenheit ist immer relativ zu einer Grundgesamtheit, und hier wird sie gewählt.\n\n„Trainingsdaten“ zählt nur die von diesem Job ausgewählten Bilder, der Ausgleich wirkt also innerhalb der Menge, mit der du tatsächlich trainierst — meist das Gewünschte. „Ganze Bibliothek“ zählt alles, was du besitzt; ein Tag, das in deinem Datensatz häufig, insgesamt aber selten ist, gilt damit weiter als selten. Das ist gelegentlich nützlich, wenn der Trainingssatz ein bewusster Ausschnitt einer viel größeren, anders verteilten Sammlung ist.\n\n„Ganze Bibliothek + Bestände anderswo“ addiert den höchsten Meta-Tag-Zähler jedes Tags — die Bilder, die es irgendwo hat, wo diese Bibliothek nicht ist, pro Seite auf den Meta-Tags des Tags gezählt („tumblr 50“, „twitter 100“); verwendet wird die größte einzelne Zahl, nie die Summe, denn die Seiten zählen sich überschneidende Bilder. Nirgends sonst in der App wird diese Zahl zu einer Zählung addiert, denn eine Summe, die sie enthält, wäre eine Aussage über anderswo; fürs AUSGLEICHEN ist sie oft die ehrliche. Ein Tag mit vier Bildern hier und vierzigtausend dort, woher sie stammen, ist kein seltenes Wort, und es als selten zu behandeln verbraucht den Lauf damit, dem Modell etwas beizubringen, das es schon kann.",
  "Caption selection": "Auswahl der Beschreibungen",
  "Instruction selection": "Auswahl der Anweisungen",
  "Start now — pauses the running job and puts this one first":
    "Jetzt starten – pausiert den laufenden Auftrag und stellt diesen nach vorn",
  "Start now — puts this job first and starts the queue":
    "Jetzt starten – stellt diesen Auftrag nach vorn und startet die Warteschlange",
  "Save as duplicate":
    "Als Duplikat speichern",
  "Batch & seed": "Batch & Seed",
  "Device": "Gerät",
  "Precision & quantization": "Genauigkeit & Quantisierung",
  "Memory savers": "Speicher sparen",
  "Training images": "Trainingsbilder",
  "Length measured in":
    "Länge gemessen in",
  "Steps are a fixed amount of work; epochs are full passes over your images, so the run grows with the dataset.":
    "Schritte sind eine feste Menge Arbeit; Epochen sind vollständige Durchläufe durch deine Bilder, der Lauf wächst also mit dem Datensatz.",
  "A STEP is one batch pushed through the model and one update of the weights — a fixed amount of work whatever the dataset holds. An EPOCH is one pass over every training image, so the same number means a longer run on a bigger set and the model sees each picture the same number of times either way.\n\nEpochs are usually the easier thing to reason about: “each image about ten times” transfers between datasets, where “3000 steps” does not. The exact step count is worked out when the run starts, because only then is it known how many entries the dataset has — a film contributes its frames, a degraded copy is an extra sample, and an item can contribute one per caption.":
    "Ein SCHRITT ist ein Batch durch das Modell und eine Aktualisierung der Gewichte — eine feste Menge Arbeit, egal wie groß der Datensatz ist. Eine EPOCHE ist ein Durchlauf über jedes Trainingsbild; dieselbe Zahl bedeutet bei einem größeren Datensatz also einen längeren Lauf, und das Modell sieht jedes Bild in beiden Fällen gleich oft.\n\nEpochen lassen sich meist leichter überblicken: „jedes Bild etwa zehnmal“ lässt sich auf andere Datensätze übertragen, „3000 Schritte“ nicht. Die genaue Schrittzahl wird beim Start des Laufs ermittelt, denn erst dann steht fest, wie viele Einträge der Datensatz hat — ein Film steuert seine Einzelbilder bei, eine degradierte Kopie ist ein zusätzliches Sample, und ein Objekt kann einen Eintrag pro Beschreibung beisteuern.",
  "Epochs":
    "Epochen",
  "Full passes over the dataset. The exact step count is worked out when the run starts and shown in its log.":
    "Vollständige Durchläufe durch den Datensatz. Die genaue Schrittzahl wird beim Start des Laufs ermittelt und im Log ausgegeben.",
  "How many times the run works through every training image. Each pass visits every entry exactly once, in a fresh random order.\n\nWhat counts as an entry is the dataset after it has been built, not the number of pictures you selected: a video contributes one entry per kept frame, a degradation variant adds an extra sample beside the clean picture, and with “every caption” an item contributes one entry per caption. That is why the step count appears when the run starts rather than here.":
    "Wie oft der Lauf jedes Trainingsbild durcharbeitet. Jeder Durchlauf besucht jeden Eintrag genau einmal, in neuer zufälliger Reihenfolge.\n\nEin Eintrag ist dabei der fertig gebaute Datensatz, nicht die Zahl der ausgewählten Bilder: ein Video steuert einen Eintrag pro behaltenem Einzelbild bei, eine Degradationsvariante ein zusätzliches Sample neben dem sauberen Bild, und mit „jede Beschreibung“ steuert ein Objekt einen Eintrag pro Beschreibung bei. Deshalb erscheint die Schrittzahl beim Start des Laufs und nicht hier.",
  "Query weight":
    "Abfragegewicht",
  "A weight buys":
    "Ein Gewicht bewirkt",
  "Whether a heavier query's images are seen more often, or seen the same and counted for more.":
    "Ob die Bilder einer stärker gewichteten Abfrage häufiger gesehen werden oder gleich oft, aber stärker zählen.",
  "Both spend the same ratio; they differ in what they spend it on.\n\nSEEN MORE OFTEN is the classic behaviour: a weight-2 query's pictures get twice the visits, which means they take those visits from the rest — a fixed-length run spends more of itself on them and less on everything else.\n\nCOUNTED FOR MORE gives every picture the same number of visits and multiplies the weighted ones' effect on the weights instead. Nothing loses coverage; the emphasis comes out of the gradient rather than out of the other images' training time. It is the better default when the queries are different KINDS of picture rather than different amounts of importance.":
    "Beide geben dasselbe Verhältnis aus; sie unterscheiden sich darin, wofür.\n\nHÄUFIGER GESEHEN ist das klassische Verhalten: die Bilder einer Abfrage mit Gewicht 2 bekommen doppelt so viele Besuche — und nehmen diese Besuche dem Rest weg. Ein Lauf fester Länge gibt mehr von sich für sie aus und weniger für alles andere.\n\nZÄHLT MEHR gibt jedem Bild gleich viele Besuche und multipliziert stattdessen die Wirkung der gewichteten Bilder auf die Gewichte. Nichts verliert an Abdeckung; die Betonung kommt aus dem Gradienten statt aus der Trainingszeit der anderen Bilder. Das ist die bessere Voreinstellung, wenn die Abfragen verschiedene ARTEN von Bildern beschreiben und nicht verschiedene Grade von Wichtigkeit.",
  "Seen more often":
    "Häufiger gesehen",
  "Counted for more":
    "Zählt mehr",
  "An item with several captions":
    "Ein Objekt mit mehreren Beschreibungen",
  "Whether every caption is used each pass, or one is drawn per visit.":
    "Ob in jedem Durchlauf jede Beschreibung verwendet wird oder pro Besuch eine gezogen wird.",
  "Items often carry more than one caption — a short one and a long one, a translation, a machine draft somebody approved.\n\nONE AT RANDOM gives the item a single visit each pass and draws a different caption each time, so the whole set is seen across a long run and an item counts once however many ways it has been described.\n\nEVERY CAPTION gives it one visit per caption, so all of them are used every pass — and an item with ten is therefore seen ten times, which is usually an accident of tooling rather than a claim that the picture matters ten times as much.\n\nEVERY CAPTION, SHARED is that with the accident removed: each caption still gets its visit, and together they carry one item's worth of gradient.":
    "Objekte tragen oft mehr als eine Beschreibung — eine kurze und eine lange, eine Übersetzung, einen maschinellen Entwurf, den jemand freigegeben hat.\n\nEINE ZUFÄLLIGE gibt dem Objekt pro Durchlauf einen Besuch und zieht jedes Mal eine andere Beschreibung; über einen langen Lauf werden so alle gesehen, und ein Objekt zählt einmal, wie viele Beschreibungen es auch hat.\n\nJEDE BESCHREIBUNG gibt ihm einen Besuch pro Beschreibung, also werden in jedem Durchlauf alle verwendet — ein Objekt mit zehn wird damit zehnmal gesehen, was meist ein Zufall der Werkzeuge ist und keine Aussage darüber, dass das Bild zehnmal so wichtig wäre.\n\nJEDE BESCHREIBUNG, GETEILT ist dasselbe ohne diesen Zufall: jede Beschreibung bekommt ihren Besuch, und zusammen tragen sie den Gradienten eines einzigen Objekts.",
  "One at random each visit":
    "Pro Besuch eine zufällige",
  "Every caption, once each":
    "Jede Beschreibung, je einmal",
  "Every caption, sharing one item's weight":
    "Jede Beschreibung, teilt sich das Gewicht eines Objekts",
  "Unsupported":
    "Nicht unterstützt",
  "not available on Apple silicon":
    "auf Apple Silicon nicht verfügbar",
  "not used on Apple silicon, where the run trains in fp32":
    "wird auf Apple Silicon nicht verwendet, dort trainiert der Lauf in fp32",
  "a full finetune trains the base weights, so there is nothing to quantize":
    "ein komplettes Finetuning trainiert die Basisgewichte, es gibt also nichts zu quantisieren",
  "only offered for LoRA training":
    "nur beim LoRA-Training verfügbar",
  "too large to finetune on any GPU this app has constants for":
    "zu groß für ein Finetuning auf jeder GPU, für die diese App Werte hat",
  "Another picture": "Anderes Bild",
  "{n} jobs selected. One at a time shows its progress, samples and settings.":
    "{n} Aufträge ausgewählt. Fortschritt, Testbilder und Einstellungen zeigt einer nach dem anderen.",
  "original":
    "Original",
  "Show this at full size":
    "In voller Größe anzeigen",
  "Each snapshot is about {size}.":
    "Jeder Schnappschuss ist etwa {size} groß.",
  "Cadence measured in":
    "Abstand gemessen in",
  "How often a snapshot is written: after a fixed number of steps, or after a number of full passes over the dataset.":
    "Wie oft ein Schnappschuss geschrieben wird: nach einer festen Zahl Schritte oder nach einer Zahl vollständiger Durchläufe durch den Datensatz.",
  "How often a round of samples is rendered: after a fixed number of steps, or after a number of full passes over the dataset.": "Wie oft eine Runde Testbilder gerendert wird: nach einer festen Anzahl Schritte oder nach einer Anzahl vollständiger Durchläufe durch den Datensatz.",
  "Rendered after this many full passes. The equivalent step count appears in the job's log when the run starts.": "Wird nach so vielen vollständigen Durchläufen gerendert. Die entsprechende Schrittzahl steht im Log des Jobs, sobald der Lauf startet.",
  "A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 250 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both. It is the choice the checkpoint cadence and the run’s own length already offer, and setting all three the same way is what makes a sample, its checkpoint and a pass over your pictures line up in the timeline.\n\nHow many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has — a film’s frames, a degraded copy and an item contributing one entry per caption all count.": "Ein Schritt ist eine feste Menge Arbeit und eine Epoche ist ein Durchlauf über jedes Trainingsbild, daher driften die beiden Takte auseinander, wenn ein Datensatz wächst — „alle 250 Schritte“ ist bei einem kleinen Lauf fast alles und bei einem großen ein Bruchteil, während „jede Epoche“ in beiden dasselbe bedeutet. Es ist dieselbe Wahl, die der Checkpoint-Takt und die Länge des Laufs schon anbieten, und wenn alle drei gleich eingestellt sind, liegen ein Testbild, sein Checkpoint und ein Durchlauf über deine Bilder in der Zeitleiste beieinander.\n\nWie viele Schritte eine Epoche dauert, wird beim Start des Laufs ermittelt, denn nur der fertig gebaute Datensatz weiß, wie viele Einträge er hat — die Einzelbilder eines Films, eine verschlechterte Kopie und ein Element mit einem Eintrag pro Bildtext zählen alle mit.",
  "Rendered after this many full passes over the dataset. The equivalent step count is printed in the job’s log when the run starts, so a glance there says what the cadence came out as for this particular dataset.\n\nSampling interrupts training while it renders, so on a large dataset one round per epoch may be further apart than you want and on a tiny one it may be a pause every few seconds — the log’s step figure is what tells you which.": "Wird nach so vielen vollständigen Durchläufen durch den Datensatz gerendert. Die entsprechende Schrittzahl steht beim Start im Log des Jobs; ein Blick dorthin sagt, was der Takt für genau diesen Datensatz ergibt.\n\nDas Rendern unterbricht das Training, daher kann eine Runde pro Epoche bei einem großen Datensatz weiter auseinanderliegen als gewünscht und bei einem winzigen alle paar Sekunden pausieren — die Schrittzahl im Log sagt, welches von beidem.",
  "Rendered every this many steps, whatever the dataset is. 250–500 is a good rhythm: often enough to catch a concept going wrong, rare enough that the pauses do not dominate the run.": "Wird alle so vielen Schritte gerendert, unabhängig vom Datensatz. 250–500 ist ein guter Rhythmus: oft genug, um ein entgleisendes Konzept zu bemerken, selten genug, dass die Pausen den Lauf nicht bestimmen.",
  "A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 500 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both.\n\nHow many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has. That is also why the disk estimate below can only be given when the run's length is set in epochs too.":
    "Ein Schritt ist eine feste Menge Arbeit, eine Epoche ein Durchlauf über jedes Trainingsbild — die beiden Abstände laufen also auseinander, sobald ein Datensatz wächst: „alle 500 Schritte“ ist bei einem kleinen Lauf fast alles und bei einem großen ein Bruchteil, während „jede Epoche“ in beiden dasselbe bedeutet.\n\nWie viele Schritte eine Epoche braucht, wird beim Start des Laufs ermittelt, denn erst der fertig gebaute Datensatz weiß, wie viele Einträge er hat. Deshalb kann die Speicherschätzung unten nur dann etwas sagen, wenn auch die Länge des Laufs in Epochen angegeben ist.",
  "epochs":
    "Epochen",
  "Written after this many full passes. The equivalent step count appears in the job's log when the run starts.":
    "Wird nach so vielen vollständigen Durchläufen geschrieben. Was das in Schritten bedeutet, steht beim Start im Log des Auftrags.",
  "Every snapshot is a usable model file: the Evaluate tab can generate with any of them, so you can compare one pass against another and keep whichever looks best.\n\nCounted in passes, the cadence follows the dataset: add pictures and the snapshots stay one-per-pass rather than quietly becoming more frequent than a pass. The trainer prints what it works out to in steps, so the timeline and the log still agree about what a checkpoint is.":
    "Jeder Schnappschuss ist eine benutzbare Modelldatei: der Evaluate-Tab kann mit jedem davon erzeugen, du kannst also einen Durchlauf gegen einen anderen halten und den besten behalten.\n\nIn Durchläufen gezählt folgt der Abstand dem Datensatz: kommen Bilder dazu, bleibt es bei einem Schnappschuss pro Durchlauf, statt still häufiger zu werden als ein Durchlauf. Der Trainer schreibt ins Log, was das in Schritten ergibt, damit Zeitachse und Log sich einig bleiben, was ein Checkpoint ist.",
  "Never upscale":
    "Nie hochskalieren",
  "Leave out any image smaller than the bucket it would be fitted to, rather than enlarging it.":
    "Bilder, die kleiner sind als der Bucket, in den sie kämen, weglassen statt sie zu vergrößern.",
  "Loads the frozen base weights in 8-bit or 4-bit so big models fit in little memory (QLoRA). 8-bit (int8) runs on Apple silicon too; fp8 and 4-bit need an NVIDIA GPU.":
    "Lädt die eingefrorenen Basisgewichte in 8 oder 4 Bit, damit große Modelle in wenig Speicher passen (QLoRA). 8 Bit (int8) läuft auch auf Apple-Silicon; fp8 und 4 Bit brauchen eine NVIDIA-GPU.",
  "Quantize the text encoder":
    "Text-Encoder quantisieren",
  "Applies the same scheme to the text encoder, the other big frozen model. On the largest models it is worth several GB.":
    "Wendet dasselbe Verfahren auf den Text-Encoder an, das andere große eingefrorene Modell. Bei den größten Modellen sind das mehrere GB.",
  "cannot be combined with training the text encoder":
    "nicht zusammen mit dem Training des Text-Encoders möglich",

  // ---- adapter type, layer targeting, optimizers, noise levels,
  // weight averaging and regularization ----
  "Adapter":
    "Adapter",
  "Adapter type":
    "Adapter-Typ",
  "Kronecker factor":
    "Kronecker-Faktor",
  "How each weight is split into LoKr's two parts. Leave empty unless you have a reason not to.":
    "Wie jedes Gewicht in LoKrs zwei Teile zerlegt wird. Lass es leer, wenn du keinen Grund dagegen hast.",
  "Only these layers":
    "Nur diese Schichten",
  "all of them":
    "alle",
  "Comma-separated parts of a layer's name. Leave empty to train every attention layer — which is what you want unless you have a reason not to.":
    "Kommagetrennte Teile eines Schichtnamens. Leer lassen, um jede Attention-Schicht zu trainieren — was du willst, solange du keinen Grund dagegen hast.",
  "By default the adapter attaches to every attention layer in the image model. This narrows that to the layers whose name contains one of the words you list.\n\nWhy you might: different parts of the network do different jobs. The later ones carry more of what a picture LOOKS like, and the earlier ones more of how it is put together — so training only part of the network is how a style is learned without also disturbing composition and anatomy. It also makes the adapter smaller and each step faster, since there is less to train.\n\nThe names come from the model itself, and the chevron at the end of the field lists the ones worth knowing for the architecture you picked — clicking one adds or removes it, and a tick marks the ones the field already holds. For SD and SDXL they are down_blocks, mid_block and up_blocks, plus attn1 (the picture attending to itself) and attn2 (where the prompt gets in); for the newer transformer models, transformer_blocks and single_transformer_blocks. The field stays free text, because you can be as coarse or as fine as you like: 'up_blocks' takes a whole third of a UNet, 'transformer_blocks.12' takes one block, 'to_k' takes one kind of projection everywhere. The job's page draws a map of the whole model once a run has started.\n\nIf what you type matches no layers at all, the run stops and says so rather than training an adapter attached to nothing — which would otherwise look exactly like a normal run that learned nothing.":
    "Standardmäßig hängt sich der Adapter an jede Attention-Schicht des Bildmodells. Das hier grenzt es auf die Schichten ein, deren Name eines der aufgezählten Wörter enthält.\n\nWarum: Verschiedene Teile des Netzes tun verschiedene Dinge. Die späteren tragen mehr davon, wie ein Bild AUSSIEHT, die früheren mehr davon, wie es aufgebaut ist — nur einen Teil des Netzes zu trainieren ist also der Weg, einen Stil zu lernen, ohne Komposition und Anatomie mitzustören. Außerdem wird der Adapter kleiner und jeder Schritt schneller, weil weniger zu trainieren ist.\n\nDie Namen kommen aus dem Modell selbst, und der Pfeil am Ende des Feldes listet die für die gewählte Architektur wissenswerten auf — ein Klick fügt einen hinzu oder entfernt ihn, und ein Haken markiert die, die im Feld schon stehen. Bei SD und SDXL sind das down_blocks, mid_block und up_blocks sowie attn1 (das Bild, das sich selbst betrachtet) und attn2 (wo der Prompt hineinkommt); bei den neueren Transformer-Modellen transformer_blocks und single_transformer_blocks. Das Feld bleibt freier Text, denn du kannst so grob oder so fein werden, wie du willst: „up_blocks“ nimmt ein ganzes Drittel eines UNet, „transformer_blocks.12“ einen einzelnen Block, „to_k“ überall eine Art von Projektion. Die Seite des Auftrags zeichnet eine Karte des ganzen Modells, sobald ein Lauf gestartet ist.\n\nWenn das Getippte auf gar keine Schicht passt, bricht der Lauf ab und sagt es, statt einen Adapter zu trainieren, der an nichts hängt — was sonst exakt wie ein normaler Lauf aussähe, der nichts gelernt hat.",
  "Except these layers":
    "Außer diese Schichten",
  "Comma-separated parts of a layer's name to leave out. Applied after the field above, and it wins.":
    "Kommagetrennte Teile eines Schichtnamens, die ausgelassen werden. Wird nach dem Feld darüber angewendet und gewinnt.",
  "The same kind of list, subtracting instead of selecting. A layer whose name matches anything here is left out even if the field above selected it.\n\nIt is the easier way to say 'everything except' — excluding 'down_blocks' is shorter and stays correct if the model gains a block, where listing every other block by hand does not.":
    "Dieselbe Art Liste, nur abziehend statt auswählend. Eine Schicht, deren Name auf irgendetwas hier passt, bleibt draußen, auch wenn das Feld darüber sie ausgewählt hat.\n\nDas ist der einfachere Weg, „alles außer“ zu sagen — „down_blocks“ auszuschließen ist kürzer und bleibt richtig, wenn das Modell einen Block dazubekommt; jeden anderen Block von Hand aufzuzählen bleibt es nicht.",
  "Output size: a small fraction of a LoRA of the same rank — usually under a tenth.":
    "Ausgabegröße: ein kleiner Bruchteil eines LoRA gleichen Rangs — meist unter einem Zehntel.",
  "Learning rate multiplier":
    "Lernraten-Faktor",
  "Prodigy works the rate out for itself; this scales what it finds. 1 leaves it alone — lower it if the run overshoots, raise it if it never gets going.":
    "Prodigy ermittelt die Rate selbst; das hier skaliert das Gefundene. 1 lässt es unverändert — senke es, wenn der Lauf überschießt, erhöhe es, wenn er nie in Gang kommt.",
  "The Prodigy optimizer measures how far the weights have moved from where they started and derives a learning rate from that, so the rate is not something you set here — it comes out of the run.\n\nWhat this field does is scale the answer. 1 accepts it as found and is what you want almost always. Below 1 is a brake, worth reaching for if the run overshoots and samples come out burnt; above 1 pushes harder, which is occasionally useful on a very small dataset.\n\nProdigy needs a few hundred steps to work its estimate up from nearly nothing, so early samples in a Prodigy run look untrained even when everything is fine. Judge it from about a fifth of the way in, not from the first sample round.":
    "Der Optimierer Prodigy misst, wie weit sich die Gewichte von ihrem Ausgangspunkt entfernt haben, und leitet daraus eine Lernrate ab — die Rate wird hier also nicht gesetzt, sie kommt aus dem Lauf.\n\nDieses Feld skaliert nur die Antwort. 1 nimmt sie so, wie sie gefunden wurde, und ist fast immer das Richtige. Unter 1 ist eine Bremse, sinnvoll wenn der Lauf überschießt und Testbilder verbrannt aussehen; über 1 drückt stärker, was gelegentlich bei sehr kleinen Datensätzen hilft.\n\nProdigy braucht ein paar hundert Schritte, um seine Schätzung von fast nichts hochzuarbeiten — frühe Testbilder eines Prodigy-Laufs sehen deshalb untrainiert aus, auch wenn alles stimmt. Beurteile ihn etwa ab einem Fünftel der Strecke, nicht an der ersten Testbildrunde.",
  "How far the weights move on every update. It is the single most sensitive setting here.\n\nToo high and training diverges: samples turn into over-saturated, high-contrast mush ('deep fried'), often within a few hundred steps. Too low and nothing visibly changes no matter how long you wait. Typical values: 1e-4 for a LoRA, 1e-5 or lower for a full finetune (which touches every weight and needs far gentler updates).\n\nLearning rate and total steps trade off against each other — halving the rate roughly doubles the steps needed. If early samples look burnt, halve it; if they look identical to the baseline after a third of the run, double it.\n\nIf finding this number is the part you would rather not do, the Prodigy optimizer (Memory & speed) works it out for itself.":
    "Wie weit sich die Gewichte bei jedem Update bewegen. Das ist die empfindlichste Einstellung hier.\n\nZu hoch und das Training divergiert: Testbilder werden zu übersättigtem, kontrastüberladenem Brei („deep fried“), oft schon nach ein paar hundert Schritten. Zu niedrig und es ändert sich sichtbar nichts, egal wie lange du wartest. Typische Werte: 1e-4 für ein LoRA, 1e-5 oder niedriger für ein komplettes Finetuning (das jedes Gewicht anfasst und viel sanftere Updates braucht).\n\nLernrate und Gesamtschritte spielen gegeneinander — die Rate zu halbieren verdoppelt ungefähr die nötigen Schritte. Sehen frühe Testbilder verbrannt aus, halbiere sie; sehen sie nach einem Drittel des Laufs noch aus wie die Ausgangsbasis, verdopple sie.\n\nWenn du diese Zahl lieber nicht suchen möchtest: Der Optimierer Prodigy (Speicher & Tempo) ermittelt sie selbst.",
  "Noise levels":
    "Rauschstufen",
  "Train on":
    "Trainieren auf",
  "Which stage of denoising to spend the run on. High noise decides a picture's layout, low noise its detail — so this decides what the training is mostly about.":
    "Auf welcher Stufe der Rauschentfernung der Lauf verbracht wird. Hohes Rauschen entscheidet über den Bildaufbau, niedriges über die Details — das hier entscheidet also, worum es im Training hauptsächlich geht.",
  "Every training step takes a picture, adds some amount of noise to it, and asks the model to undo that. How much noise is picked fresh each time — and the two extremes teach completely different things.\n\nAt HIGH noise there is barely a picture left, so all the model can learn is layout: what is where, how big, the overall shape and colour. At LOW noise the composition is already settled and what is left to learn is detail and texture — edges, surfaces, small features.\n\nSo where a run spends its steps decides what it mostly teaches. A style is largely texture; a character's proportions are largely layout.\n\n'The model's own' is what this model family has always done here, and is the right answer unless you have a specific reason: the older models spread their steps evenly, and the newer ones concentrate on the middle, which is what their published recipes do and part of why they train efficiently. 'Evenly' spreads across the whole range. 'Bell curve' is the newer models' behaviour made adjustable, so you can lean it towards layout or towards detail. 'Cosine' leans towards higher noise without abandoning the low end.\n\nChanging this does not make a run better or worse in general — it moves what the run is good at.":
    "Jeder Trainingsschritt nimmt ein Bild, gibt eine gewisse Menge Rauschen darauf und lässt das Modell das rückgängig machen. Wie viel Rauschen, wird jedes Mal neu gezogen — und die beiden Extreme lehren völlig Verschiedenes.\n\nBei HOHEM Rauschen ist kaum ein Bild übrig, das Modell kann also nur den Aufbau lernen: was wo ist, wie groß, Gesamtform und Farbe. Bei NIEDRIGEM Rauschen steht die Komposition schon, und zu lernen bleiben Details und Textur — Kanten, Oberflächen, kleine Merkmale.\n\nWo ein Lauf seine Schritte verbringt, entscheidet also, was er hauptsächlich beibringt. Ein Stil ist größtenteils Textur; die Proportionen einer Figur sind größtenteils Aufbau.\n\n„Das eigene des Modells“ ist das, was diese Modellfamilie hier immer getan hat, und die richtige Antwort, solange du keinen bestimmten Grund hast: Die älteren Modelle verteilen ihre Schritte gleichmäßig, die neueren konzentrieren sich auf die Mitte — so machen es ihre veröffentlichten Rezepte, und das ist Teil des Grundes, warum sie effizient trainieren. „Gleichmäßig“ verteilt über den ganzen Bereich. „Glockenkurve“ ist das Verhalten der neueren Modelle, nur einstellbar, sodass du es Richtung Aufbau oder Richtung Detail neigen kannst. „Kosinus“ neigt zu höherem Rauschen, ohne das untere Ende aufzugeben.\n\nDas zu ändern macht einen Lauf nicht allgemein besser oder schlechter — es verschiebt, worin er gut wird.",
  "The model's own (recommended)":
    "Das eigene des Modells (empfohlen)",
  "Evenly across all levels":
    "Gleichmäßig über alle Stufen",
  "A bell curve I can aim":
    "Eine Glockenkurve, die ich ausrichte",
  "Leaning towards layout":
    "Neigung zum Bildaufbau",
  "Aim at":
    "Ausrichten auf",
  "0 is the middle. Positive leans towards layout and composition, negative towards detail and texture. ±1 is already a strong lean.":
    "0 ist die Mitte. Positiv neigt zu Aufbau und Komposition, negativ zu Detail und Textur. ±1 ist bereits eine starke Neigung.",
  "Where the centre of the bell curve sits along the noise range.\n\n0 puts it in the middle, which is what the newer models do by default and a good place to stay. Move it positive and the run spends more of itself at high noise, learning layout and composition — useful when what you are teaching is a shape or an arrangement. Move it negative and it spends more at low noise, learning detail and texture — useful for a style, a medium, a surface quality.\n\n±0.5 is a noticeable lean and ±1 is a strong one. Beyond ±2 the run largely stops seeing one end of the range at all.":
    "Wo die Mitte der Glockenkurve auf dem Rauschbereich liegt.\n\n0 setzt sie in die Mitte — das tun die neueren Modelle standardmäßig, und dort zu bleiben ist gut. Ins Positive verschoben verbringt der Lauf mehr von sich bei hohem Rauschen und lernt Aufbau und Komposition — nützlich, wenn du eine Form oder eine Anordnung beibringst. Ins Negative verschoben verbringt er mehr bei niedrigem Rauschen und lernt Detail und Textur — nützlich für einen Stil, ein Medium, eine Oberflächenqualität.\n\n±0,5 ist eine merkliche Neigung, ±1 eine starke. Jenseits von ±2 sieht der Lauf ein Ende des Bereichs praktisch gar nicht mehr.",
  "Spread":
    "Streuung",
  "How wide the curve is. 1 is the default; smaller concentrates the run on a narrow band around the aim, larger reaches both extremes.":
    "Wie breit die Kurve ist. 1 ist der Standard; kleiner konzentriert den Lauf auf ein schmales Band um die Ausrichtung, größer erreicht beide Extreme.",
  "The width of the bell curve.\n\n1 is the standard setting. Smaller values concentrate the run on a narrow band around wherever you have aimed it, which sharpens what it teaches at the cost of everything else. Larger values spread it out and reach both extremes more often, which is closer to training evenly.\n\nIf you are unsure, leave it at 1 and move the aim instead — the aim is the setting that changes what the run learns, and this one changes how single-minded it is about it.":
    "Die Breite der Glockenkurve.\n\n1 ist die Standardeinstellung. Kleinere Werte konzentrieren den Lauf auf ein schmales Band um die gewählte Ausrichtung, was schärft, was er beibringt — auf Kosten von allem anderen. Größere Werte streuen ihn und erreichen beide Extreme häufiger, was näher am gleichmäßigen Training liegt.\n\nWenn du unsicher bist, lass sie bei 1 und verschiebe stattdessen die Ausrichtung — die Ausrichtung ändert, was der Lauf lernt, und diese hier, wie einseitig er dabei ist.",
  "Weight averaging":
    "Gewichtsmittelung",
  "Average the weights":
    "Gewichte mitteln",
  "Save a smoothed version of the weights instead of whatever the last step happened to produce. Makes checkpoints more consistent and overtraining slower to bite.":
    "Speichert eine geglättete Fassung der Gewichte statt dessen, was der letzte Schritt zufällig ergeben hat. Macht Checkpoints gleichmäßiger und lässt Übertraining langsamer zuschlagen.",
  "Every training step moves the weights a little, and each of those moves is noisy — it is worked out from a handful of images, and a different handful would have pulled somewhere slightly different. So the weights at step 1400 are not reliably better than the weights at step 1200; part of the difference is just which pictures came up.\n\nWith this on, the run keeps a second, smoothed copy of the weights alongside the real ones and nudges it a little way towards the current weights after every step. That smoothed copy is what gets saved — as the checkpoints, as the final result, and as what the test samples are rendered from. Training itself is completely unaffected.\n\nWhat you get is a result that depends less on exactly where the run stopped: the quality difference between neighbouring checkpoints shrinks, and a run that goes on too long degrades more gradually, because an average lags behind. What it costs is one extra copy of whatever is being trained — nothing worth thinking about for a LoRA, a second whole model for a full finetune, which the memory estimate below accounts for.\n\nThe early part of a run is handled for you: a fresh average starts out equal to the untrained weights, so the run keeps it short at first and lengthens it as training goes on. Without that, a short run would save an average still holding its own random starting point.":
    "Jeder Trainingsschritt bewegt die Gewichte ein wenig, und jede dieser Bewegungen ist verrauscht — sie wird aus einer Handvoll Bilder berechnet, und eine andere Handvoll hätte etwas anders gezogen. Die Gewichte bei Schritt 1400 sind deshalb nicht verlässlich besser als die bei Schritt 1200; ein Teil des Unterschieds ist einfach, welche Bilder gerade kamen.\n\nMit dieser Option hält der Lauf eine zweite, geglättete Kopie der Gewichte neben den echten und schiebt sie nach jedem Schritt ein Stück in Richtung der aktuellen Gewichte. Diese geglättete Kopie wird gespeichert — als Checkpoints, als Endergebnis und als das, woraus die Testbilder gerendert werden. Das Training selbst bleibt völlig unberührt.\n\nWas du bekommst, ist ein Ergebnis, das weniger davon abhängt, wo genau der Lauf aufgehört hat: Der Qualitätsunterschied zwischen benachbarten Checkpoints schrumpft, und ein Lauf, der zu lange weitergeht, verschlechtert sich allmählicher, weil ein Mittel hinterherhinkt. Es kostet eine zusätzliche Kopie dessen, was trainiert wird — bei einem LoRA nicht der Rede wert, bei einem kompletten Finetuning ein zweites ganzes Modell, was die Speicherschätzung unten berücksichtigt.\n\nUm den Anfang des Laufs kümmert sich die App: Ein frisches Mittel startet gleich den untrainierten Gewichten, der Lauf hält es also zunächst kurz und verlängert es im Verlauf des Trainings. Ohne das würde ein kurzer Lauf ein Mittel speichern, das noch seinen eigenen zufälligen Startpunkt enthält.",
  "Averaging window":
    "Mittelungsfenster",
  "How much of the old average is kept each step. 0.999 averages roughly the last 1000 steps; lower follows training more closely, higher smooths harder.":
    "Wie viel vom alten Mittel pro Schritt erhalten bleibt. 0,999 mittelt ungefähr die letzten 1000 Schritte; niedriger folgt dem Training enger, höher glättet stärker.",
  "The fraction of the existing average kept at each step, with the rest taken from the current weights. It decides how long a stretch of training the saved result reflects — roughly 1 ÷ (1 − this value) steps.\n\n0.999 is about the last 1000 steps and is a sensible default for runs of a few thousand. On a short run (say 800 steps) that window is longer than the run itself, so the average never quite catches up — drop to 0.99 (about 100 steps) there. On a very long run you can go higher for a steadier result.\n\nAs a rule of thumb, keep the window well under the total number of steps.":
    "Der Anteil des bestehenden Mittels, der bei jedem Schritt erhalten bleibt; der Rest kommt aus den aktuellen Gewichten. Er entscheidet, wie langen Trainingsabschnitt das gespeicherte Ergebnis widerspiegelt — ungefähr 1 ÷ (1 − dieser Wert) Schritte.\n\n0,999 sind etwa die letzten 1000 Schritte und ein sinnvoller Standard für Läufe von einigen Tausend. Bei einem kurzen Lauf (sagen wir 800 Schritte) ist dieses Fenster länger als der Lauf selbst, das Mittel holt also nie ganz auf — geh dort auf 0,99 (etwa 100 Schritte) herunter. Bei einem sehr langen Lauf kannst du für ein ruhigeres Ergebnis höher gehen.\n\nFaustregel: Halte das Fenster deutlich unter der Gesamtzahl der Schritte.",
  "Mostly a memory choice, except for Prodigy, which works the learning rate out for itself. Adafactor saves the most memory and runs on every GPU; 8-bit AdamW saves less and needs an NVIDIA or AMD card.":
    "Vor allem eine Speicherentscheidung — außer bei Prodigy, das die Lernrate selbst ermittelt. Adafactor spart am meisten Speicher und läuft auf jeder GPU; AdamW (8-Bit) spart weniger und braucht eine NVIDIA- oder AMD-Karte.",
  "The optimizer is what actually turns gradients into weight changes. It does that using running statistics it keeps for every weight being trained — and those statistics are memory, which for a full finetune is usually most of what the run needs.\n\nAdamW is the standard choice and the safest. It keeps two statistics per trained weight, so a full finetune pays for the model roughly three times over: the weights themselves, plus two more of the same size.\n\nAdamW (8-bit) stores those two statistics at one byte each instead of four. It is a smaller saving than it sounds, because the weights and their gradients do not shrink, and it needs an NVIDIA or AMD (ROCm) GPU — elsewhere the run says so and uses plain AdamW.\n\nAdafactor replaces the larger of the two statistics with a per-row and a per-column summary of it, which is a fraction of the size. It saves considerably more than the 8-bit variant and it runs on every GPU, including Apple silicon — where it is the only memory saving available at all, since the 8-bit variant cannot run there. What it costs is a little stability: it usually wants a slightly higher learning rate than AdamW, so if a run learns nothing after a few hundred steps, raise the rate before changing anything else.\n\nProdigy is a different kind of answer. It measures how far the weights have travelled from where they started and works the learning rate out from that as it goes, which removes the one setting here that genuinely has to be found by trial: the right rate depends on the model, the dataset size and what is being taught, so a value that suits one job is wrong for the next. With it selected, the learning rate on the Optimization page becomes a multiplier on what it finds, and 1 means 'as found'. It uses a little more memory than AdamW, and it needs a few hundred steps to work its estimate up — so early samples look untrained even when the run is fine.\n\nFor LoRA training the memory differences are a rounding error, since only the small adapter has optimizer state. Leave it on AdamW for a first run; reach for Prodigy when you are tired of guessing the rate, and for Adafactor when a full finetune will not fit.":
    "Der Optimierer ist das, was Gradienten tatsächlich in Gewichtsänderungen übersetzt. Er tut das mit laufenden Statistiken, die er für jedes trainierte Gewicht führt — und diese Statistiken sind Speicher, der bei einem kompletten Finetuning meist den größten Teil dessen ausmacht, was der Lauf braucht.\n\nAdamW ist die Standardwahl und die sicherste. Er führt zwei Statistiken pro trainiertem Gewicht, ein komplettes Finetuning zahlt das Modell also grob dreifach: die Gewichte selbst plus zwei weitere derselben Größe.\n\nAdamW (8-Bit) speichert diese beiden Statistiken mit je einem Byte statt vier. Die Ersparnis ist kleiner, als es klingt, weil Gewichte und Gradienten nicht schrumpfen, und es braucht eine NVIDIA- oder AMD-GPU (ROCm) — anderswo sagt der Lauf das und nimmt normales AdamW.\n\nAdafactor ersetzt die größere der beiden Statistiken durch je eine Zusammenfassung pro Zeile und pro Spalte, was einen Bruchteil der Größe ausmacht. Er spart deutlich mehr als die 8-Bit-Variante und läuft auf jeder GPU, auch auf Apple Silicon — wo er überhaupt die einzige verfügbare Speicherersparnis ist, weil die 8-Bit-Variante dort nicht laufen kann. Es kostet etwas Stabilität: Er will meist eine etwas höhere Lernrate als AdamW — wenn ein Lauf nach ein paar hundert Schritten nichts lernt, erhöhe zuerst die Rate, bevor du etwas anderes änderst.\n\nProdigy ist eine andere Art von Antwort. Er misst, wie weit die Gewichte von ihrem Ausgangspunkt gewandert sind, und ermittelt daraus laufend die Lernrate — das nimmt die eine Einstellung hier weg, die wirklich durch Probieren gefunden werden muss: Die richtige Rate hängt vom Modell, der Datensatzgröße und dem Gelehrten ab, ein Wert, der zu einem Auftrag passt, ist beim nächsten falsch. Ist er gewählt, wird die Lernrate auf der Seite Optimierung zu einem Faktor auf das Gefundene, und 1 heißt „wie gefunden“. Er braucht etwas mehr Speicher als AdamW und ein paar hundert Schritte, um seine Schätzung hochzuarbeiten — frühe Testbilder sehen deshalb untrainiert aus, auch wenn der Lauf in Ordnung ist.\n\nBeim LoRA-Training sind die Speicherunterschiede ein Rundungsfehler, weil nur der kleine Adapter Optimiererzustand hat. Lass es beim ersten Lauf auf AdamW; greif zu Prodigy, wenn du das Raten der Rate satt hast, und zu Adafactor, wenn ein komplettes Finetuning nicht passt.",
  "AdamW (8-bit)":
    "AdamW (8-Bit)",
  "Prodigy (finds its own rate)":
    "Prodigy (findet seine Rate selbst)",
  "Prodigy works the learning rate out for itself, so the rate on the Optimization page becomes a multiplier on what it finds — 1 leaves it alone. It needs a few hundred steps to settle, so early samples will look untrained.":
    "Prodigy ermittelt die Lernrate selbst — die Rate auf der Seite Optimierung wird damit zu einem Faktor auf das Gefundene, 1 lässt es unverändert. Er braucht ein paar hundert Schritte, bis er sich eingependelt hat, frühe Testbilder sehen deshalb untrainiert aus.",
  "Regularization":
    "Regularisierung",
  "How much reminders count":
    "Wie stark Erinnerungsbilder zählen",
  "1 gives a regularization picture the same say as a training picture, which is the usual setting. Lower makes it a gentler reminder.":
    "1 gibt einem Regularisierungsbild dasselbe Gewicht wie einem Trainingsbild, das ist die übliche Einstellung. Niedriger macht daraus eine sanftere Erinnerung.",
  "Regularization pictures are in the run to hold the model's existing idea of a thing in place while you teach it something new. This is how much each of them counts against a training picture, which counts 1.\n\n1 is the classic setting and a good starting point. Lower it if the run seems reluctant to learn what you are actually training — the reminders are pulling too hard. Raise it if what you are training keeps leaking into everything else of the same kind, which is the problem they exist to solve.\n\nThis is separate from a query's weight, which decides how OFTEN those pictures come up. How often and how much are different questions: a set of reminders is usually wanted often but quietly.":
    "Regularisierungsbilder sind im Lauf, um die bestehende Vorstellung des Modells von einer Sache festzuhalten, während du ihm etwas Neues beibringst. Das hier ist, wie viel jedes davon gegenüber einem Trainingsbild zählt, das 1 zählt.\n\n1 ist die klassische Einstellung und ein guter Ausgangspunkt. Senke es, wenn der Lauf sich zu sträuben scheint, das eigentlich Trainierte zu lernen — dann ziehen die Erinnerungsbilder zu stark. Erhöhe es, wenn das Trainierte immer wieder in alles andere derselben Art überläuft; genau dafür sind sie da.\n\nDas ist unabhängig vom Gewicht einer Abfrage, das entscheidet, wie OFT diese Bilder drankommen. Wie oft und wie stark sind verschiedene Fragen: Ein Satz Erinnerungsbilder soll meist oft, aber leise dabei sein.",
  "Pictures that remind the model what it already knows, instead of teaching it something new — they stop what you are training from spreading to everything else of the same kind. They never get the trigger word.":
    "Bilder, die das Modell an das erinnern, was es schon kann, statt ihm etwas Neues beizubringen — sie verhindern, dass das Trainierte auf alles andere derselben Art überspringt. Sie bekommen nie den Trigger.",
  "These pictures hold the model's existing idea of the subject in place: pick the same KIND of thing you are training, but not the thing itself. You do not need to exclude your training pictures — anything an ordinary query matches stays a training picture. A reminder query that matches only training pictures leaves this pool empty, and the run says so in its log.":
    "Diese Bilder halten die bestehende Vorstellung des Modells vom Gegenstand fest: Wähle dieselbe ART von Sache wie das Trainierte, aber nicht die Sache selbst. Die Trainingsbilder musst du nicht ausschließen — was eine gewöhnliche Abfrage trifft, bleibt ein Trainingsbild. Trifft eine Erinnerungsabfrage nur Trainingsbilder, bleibt dieser Pool leer, und der Lauf sagt es im Protokoll.",
  "Keep the text encoder on the CPU":
    "Text-Encoder im Arbeitsspeicher lassen",
  "Frees all of its VRAM instead of some. The next batch's prompt is encoded while this one trains, so it costs nothing as long as the processor keeps up with the card.": "Gibt seinen ganzen VRAM frei statt nur einen Teil. Der Prompt des nächsten Batches wird kodiert, während dieser trainiert — es kostet also nichts, solange der Prozessor mit der Karte mithält.",
  "The row above makes the text encoder smaller; this one takes it off the graphics card altogether. Its weights stay in ordinary system memory and each prompt is turned into an embedding there, so the encoder occupies no VRAM at all — where quantizing it leaves roughly a third of it resident.\n\nMeasured on an RTX 5070 Ti at 4-bit, this takes Chroma from 9.6 GB to 5.3 and FLUX.1 from 11.4 to 7.0, which was enough to train FLUX.2 Klein at a resolution that did not previously fit.\n\nWhat it costs is one pass over the encoder per step, on the processor instead of the graphics card — and the next batch's prompt is encoded while the current one trains, so the card only waits where the processor is slower than a whole step. Measured on a 16-core desktop, T5-XXL takes about 1.3 seconds a prompt: a 1024-pixel step on an RTX 5090 hides that entirely, a 512-pixel step (half a second) does not. It cannot be combined with training the text encoder, which would mean doing that training on the processor.":
    "Die Zeile darüber verkleinert den Text-Encoder; diese nimmt ihn ganz von der Grafikkarte. Seine Gewichte bleiben im normalen Arbeitsspeicher, und jeder Prompt wird dort in ein Embedding umgewandelt — der Encoder belegt also gar keinen VRAM, während Quantisieren rund ein Drittel davon liegen lässt.\n\nGemessen auf einer RTX 5070 Ti mit 4 Bit: Chroma sinkt von 9,6 GB auf 5,3 und FLUX.1 von 11,4 auf 7,0 — genug, um FLUX.2 Klein in einer Auflösung zu trainieren, die vorher nicht passte.\n\nWas es kostet, ist ein Durchlauf durch den Encoder pro Schritt, auf dem Prozessor statt auf der Grafikkarte — und der Prompt des nächsten Batches wird kodiert, während der aktuelle trainiert, sodass die Karte nur dort wartet, wo der Prozessor langsamer ist als ein ganzer Schritt. Gemessen auf einem 16-Kern-Desktop braucht T5-XXL etwa 1,3 Sekunden pro Prompt: Ein 1024-Pixel-Schritt auf einer RTX 5090 verdeckt das vollständig, ein 512-Pixel-Schritt (eine halbe Sekunde) nicht. Es lässt sich nicht mit dem Training des Text-Encoders kombinieren, denn das hieße, dieses Training auf dem Prozessor auszuführen.",

  // ---- the METHOD is an adapter, of which LoRA is one kind ----
  "An adapter is a small add-on file layered over the untouched model — fast, low memory, ideal for styles, characters and concepts. Full finetune rewrites the whole model: much more VRAM and data needed, only worth it for broad domain shifts. Which kind of adapter is the next question down.":
    "Ein Adapter ist eine kleine Zusatzdatei über dem unangetasteten Modell — schnell, wenig Speicher, ideal für Stile, Figuren und Konzepte. Komplettes Finetuning schreibt das ganze Modell um: deutlich mehr VRAM und Daten nötig, nur bei breiten Domänenwechseln sinnvoll. Welche Art von Adapter ist die nächste Frage darunter.",
  "An adapter leaves the base model untouched and trains a small add-on (a few dozen MB) that is layered on top at generation time. It is quick, fits ordinary hardware, can be mixed with other adapters and dialled up or down by weight — and it is enough for styles, characters, objects and most concepts. There are two kinds, LoRA and LoKr, and the Adapter section below picks between them; LoRA is the one to start with.\n\nA full finetune rewrites every weight of the model. It produces a multi-gigabyte model of its own, needs far more VRAM, far more images and much lower learning rates, and it can forget things it used to know. Reach for it only when you are moving the model into a genuinely different domain, not to teach it one more subject.":
    "Ein Adapter lässt das Basismodell unangetastet und trainiert eine kleine Zusatzdatei (ein paar Dutzend MB), die beim Generieren darübergelegt wird. Das geht schnell, passt auf gewöhnliche Hardware, lässt sich mit anderen Adaptern mischen und per Gewicht stärker oder schwächer stellen — und für Stile, Figuren, Objekte und die meisten Konzepte reicht es. Es gibt zwei Arten, LoRA und LoKr; der Abschnitt Adapter weiter unten wählt zwischen ihnen, und LoRA ist die zum Anfangen.\n\nEin komplettes Finetuning schreibt jedes Gewicht des Modells um. Es erzeugt ein eigenes Modell von mehreren Gigabyte, braucht viel mehr VRAM, viel mehr Bilder und deutlich niedrigere Lernraten, und es kann vergessen, was es einmal konnte. Greif nur dazu, wenn du das Modell in eine wirklich andere Domäne bewegst — nicht, um ihm ein weiteres Motiv beizubringen.",
  "Start from an existing adapter":
    "Von einem vorhandenen Adapter ausgehen",
  "A fresh adapter starts from noise and has to learn your concept from nothing. Starting from an existing one keeps everything it already learned and refines it — the usual reasons are adding new images to a concept you trained before, or nudging one that came out almost right.\n\nWeight sets trained on the same base model are offered — including ones trained on another model built on it — and the new job has to match the one it continues: the same adapter type, the same rank, and the same layer targeting. The trainer stops with a message naming what it found otherwise. Picking a job's finished result continues where it ended; picking an intermediate checkpoint rewinds to that point and continues from there.":
    "Ein frischer Adapter startet aus Rauschen und muss dein Konzept aus dem Nichts lernen. Von einem vorhandenen auszugehen behält alles Gelernte und verfeinert es — die üblichen Gründe sind neue Bilder zu einem schon trainierten Konzept oder das Nachjustieren eines Adapters, der fast passte.\n\nAngeboten werden Gewichtssätze, die auf demselben Basismodell trainiert wurden — auch solche von einem anderen darauf aufbauenden Modell —, und der neue Auftrag muss zu dem passen, den er fortsetzt: gleicher Adapter-Typ, gleicher Rang, gleiche Schichtauswahl. Sonst bricht der Trainer ab und benennt, was er vorgefunden hat. Das fertige Ergebnis eines Auftrags setzt dort fort, wo es endete; ein Zwischen-Checkpoint spult auf diesen Punkt zurück und macht von dort weiter.",
  "Pick a finished adapter":
    "Einen fertigen Adapter wählen",
  "No finished adapter for this base model yet":
    "Für dieses Basismodell gibt es noch keinen fertigen Adapter",
  "Optional: continue training an existing adapter instead of starting from scratch.":
    "Optional: einen vorhandenen Adapter weitertrainieren, statt von vorn zu beginnen.",
  "No full finetune":
    "Kein komplettes Finetuning",

  // ---- adapter wording: an adapter is LoRA or LoKr ----
  "The standard choice, and the format every other tool understands — a LoRA can be used anywhere.":
    "Die Standardwahl, und das Format, das jedes andere Werkzeug versteht — ein LoRA lässt sich überall verwenden.",
  "An adapter does not rewrite the model — it adds a small 'side channel' to certain layers, and rank is how wide that channel is: how much new information the adapter can hold.\n\nLow ranks (4–8) are plenty for a style or a colour palette and are very hard to overfit. Mid ranks (16–32) suit characters and objects with consistent details. High ranks (64+) mostly grow the file and the overfitting risk without helping, unless you are teaching a genuinely broad new domain.\n\nIt means slightly different things to the two adapter types. For a LoRA it is the hard ceiling on the change: a rank-16 adapter can only ever make a rank-16 change. For a LoKr it bounds only part of the structure, so a LoKr is not confined the way a LoRA is and its file grows far more slowly as you raise it — which is why the size estimate below is a figure for LoRA and a comparison for LoKr.":
    "Ein Adapter schreibt das Modell nicht um — er legt bestimmten Schichten einen kleinen „Nebenkanal“ bei, und der Rang ist dessen Breite: wie viel neue Information der Adapter fassen kann.\n\nNiedrige Ränge (4–8) reichen für einen Stil oder eine Farbpalette völlig und lassen sich kaum überfitten. Mittlere (16–32) passen zu Figuren und Objekten mit gleichbleibenden Details. Hohe (64+) vergrößern meist nur Datei und Überfittungsrisiko, ohne zu helfen — außer du bringst eine wirklich breite neue Domäne bei.\n\nFür die beiden Adapter-Typen bedeutet er etwas Unterschiedliches. Bei einem LoRA ist er die harte Obergrenze der Änderung: ein Adapter mit Rang 16 kann nur eine Änderung vom Rang 16 ausdrücken. Bei einem LoKr begrenzt er nur einen Teil der Struktur, ein LoKr ist also nicht so eingeschnürt wie ein LoRA, und seine Datei wächst beim Erhöhen weit langsamer — deshalb steht unten für LoRA eine Zahl und für LoKr ein Vergleich.",
  "The adapter's output is multiplied by alpha ÷ rank before being added to the model, so alpha sets how loudly the adapter speaks at a given capacity. It works the same way for both adapter types.\n\nThe usual convention is alpha = rank, which makes the scale factor 1 and keeps behaviour comparable when you change rank. Setting alpha to half the rank is a common way to soften an adapter that comes out too strong. It interacts with the learning rate — halving alpha has a similar effect to halving the rate — so change one at a time.":
    "Die Ausgabe des Adapters wird mit Alpha ÷ Rang multipliziert, bevor sie zum Modell addiert wird — Alpha bestimmt also, wie laut der Adapter bei gegebener Kapazität spricht. Das funktioniert bei beiden Adapter-Typen gleich.\n\nÜblich ist Alpha = Rang, was den Faktor auf 1 bringt und das Verhalten beim Ändern des Rangs vergleichbar hält. Alpha auf den halben Rang zu setzen ist ein gängiger Weg, einen zu starken Adapter abzumildern. Es wirkt mit der Lernrate zusammen — Alpha zu halbieren hat einen ähnlichen Effekt wie die Rate zu halbieren — also ändere immer nur eines.",
  "This architecture can only be trained as an adapter (LoRA or LoKr) alongside the frozen model. The \"Full finetune\" method, which rewrites the model's own weights, is not offered for it.":
    "Diese Architektur lässt sich nur als Adapter (LoRA oder LoKr) neben dem eingefrorenen Modell trainieren. Die Methode „Komplettes Finetuning“, die die eigenen Gewichte des Modells umschreibt, wird dafür nicht angeboten.",
  "No adapters for this base model yet.": "Für dieses Basismodell gibt es noch keine Adapter.",
  "No trained adapters yet.": "Noch keine trainierten Adapter.",
  "Which adapter this row applies":
    "Welchen Adapter diese Zeile anwendet",
  "Adapter strength: 1 = as trained, below weakens, above strengthens (can distort past ~1.5).":
    "Adapter-Stärke: 1 = wie trainiert, darunter schwächer, darüber stärker (ab ca. 1,5 kann es verzerren).",
  "Add adapter":
    "Adapter hinzufügen",
  "Adapters":
    "Adapter",
  "Finetune": "Finetune",
  "Generate with a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.":
    "Mit den Gewichten eines vollständigen Finetunes statt denen des Basismodells generieren. Adapter werden auf das gestapelt, was hier gewählt ist.",
  "none — the base model": "keins — das Basismodell",
  "loading finetune": "Finetune wird geladen",
  "Stack trained adapters on the base model, each with its own strength — LoRA or LoKr. An adapter fits the model it was trained on and any other built on the same one.":
    "Trainierte Adapter auf dem Basismodell stapeln, jeder mit eigener Stärke — LoRA oder LoKr. Ein Adapter passt zu dem Modell, mit dem er trainiert wurde, und zu jedem anderen, das darauf aufbaut.",
  "Generated images appear here — try out a trained adapter against its base model.":
    "Erzeugte Bilder erscheinen hier — probier einen trainierten Adapter gegen sein Basismodell aus.",
  "A much smaller file, and not limited by the rank the way a LoRA is. Whether it can be used outside this app depends on the model — see the ⓘ.":
    "Eine viel kleinere Datei, und nicht wie eine LoRA durch den Rang begrenzt. Ob sie außerhalb dieser App nutzbar ist, hängt vom Modell ab — siehe das ⓘ.",
  "Both add a small trainable layer over the frozen model; they differ in the shape of change they can express.\n\nA LoRA adds a 'low-rank' change: two thin matrices whose product is added to each targeted weight. Its capacity is exactly its rank — a rank-16 adapter can only ever make a rank-16 change, however long you train it. That is ample for a character, an object, a colour palette. It trains a little faster, it is the format every tool reads, and it carries better between related checkpoints: a LoRA trained on one finetune of a model usually still works on another.\n\nLoKr builds the change as a Kronecker product of two much smaller matrices instead. The saving comes from that structure rather than from throwing rank away, so the change is not confined to a thin slice of the weight while the file stays a small fraction of a LoRA's — under a tenth of the trainable parameters at rank 8. LyCORIS, whose method this is, suggests reaching for it when a LoRA 'does not learn well enough', and it is generally the better fit for styles and broad visual qualities, where a LoRA's rank ceiling is what you meet first. Its own caveats are the mirror image: slightly slower to train, and a very small LoKr transfers less well if you later swap the base model for a different finetune.\n\nWhat each can be USED by differs, and it is the file rather than the method. A LoRA is written in the layout every tool reads. A LoKr cannot be: that layout has a place for two matrices and nowhere to put a Kronecker factor. What it gets instead is a copy named the way ComfyUI names LoKr layers, and that works for the models whose layers ComfyUI addresses that way — FLUX.1, FLUX.1 Kontext and the Qwen-Image releases. On the others (SD 1.5, SDXL, Chroma, FLUX.2, Z-Image) a LoKr stays here: it works in the Evaluate tab and as the starting point of another job, but there is no file to hand over. On those, pick LoRA if the result has to leave this app.":
    "Beide legen eine kleine trainierbare Schicht über das eingefrorene Modell; sie unterscheiden sich darin, welche Form von Änderung sie ausdrücken können.\n\nEine LoRA fügt eine „Low-Rank“-Änderung hinzu: zwei schmale Matrizen, deren Produkt auf jedes angesprochene Gewicht addiert wird. Ihre Kapazität ist genau ihr Rang — ein Rang-16-Adapter kann immer nur eine Rang-16-Änderung ausdrücken, egal wie lange du trainierst. Für eine Figur, ein Objekt, eine Farbpalette ist das reichlich. Sie trainiert etwas schneller, ist das Format, das jedes Werkzeug liest, und lässt sich besser zwischen verwandten Checkpoints übertragen: eine LoRA, die auf einem Finetune eines Modells trainiert wurde, funktioniert meist auch auf einem anderen.\n\nLoKr baut die Änderung stattdessen als Kronecker-Produkt zweier viel kleinerer Matrizen. Die Ersparnis kommt aus dieser Struktur und nicht daraus, Rang wegzuwerfen — die Änderung ist also nicht auf eine dünne Scheibe des Gewichts beschränkt, während die Datei ein Bruchteil einer LoRA bleibt: bei Rang 8 unter einem Zehntel der trainierbaren Parameter. LyCORIS, von dem die Methode stammt, empfiehlt sie, wenn eine LoRA „nicht gut genug lernt“, und sie passt in der Regel besser zu Stilen und breiten bildnerischen Qualitäten, wo man zuerst an die Rang-Grenze einer LoRA stößt. Ihre eigenen Vorbehalte sind das Spiegelbild: etwas langsameres Training, und eine sehr kleine LoKr überträgt sich schlechter, wenn du das Basismodell später gegen ein anderes Finetune tauschst.\n\nWofür beide VERWENDBAR sind, unterscheidet sich — und das liegt an der Datei, nicht an der Methode. Eine LoRA wird in dem Format geschrieben, das jedes Werkzeug liest. Eine LoKr kann das nicht: dieses Format hat Platz für zwei Matrizen und keinen für einen Kronecker-Faktor. Stattdessen bekommt sie eine Kopie, benannt so, wie ComfyUI LoKr-Schichten benennt — und das funktioniert für die Modelle, deren Schichten ComfyUI so anspricht: FLUX.1, FLUX.1 Kontext und die Qwen-Image-Releases. Bei den übrigen (SD 1.5, SDXL, Chroma, FLUX.2, Z-Image) bleibt eine LoKr hier: sie funktioniert im Evaluate-Tab und als Ausgangspunkt eines weiteren Jobs, aber es gibt keine Datei zum Weitergeben. Nimm dort LoRA, wenn das Ergebnis diese App verlassen soll.",
  "LoKr expresses a weight's change as one small matrix combined with another. This number decides where the weight is cut into those two parts.\n\nLeft empty, the split is chosen to make the two parts as close to square as possible, which is where they are SMALLEST. Moving it either way grows the file, and the two directions are not the same thing: a low factor (4–8) pushes the weight into the second part, which is where the adapter's capacity is — that is the LyCORIS recipe for a LoKr that is not learning enough. A factor far above the square split grows the first, dense part instead, which costs size for nothing.\n\nMeasured on a 1280-wide layer at rank 8, against the same layer's LoRA: automatic 0.08x, factor 8 0.13x, factor 4 0.25x, factor 128 0.81x.\n\nThere is rarely a reason to set it. If a LoKr adapter is not learning enough, raise the rank first, then try a low factor.":
    "LoKr drückt die Änderung eines Gewichts als eine kleine Matrix in Kombination mit einer weiteren aus. Diese Zahl entscheidet, wo das Gewicht in diese zwei Teile geschnitten wird.\n\nLeer gelassen, wird der Schnitt so gewählt, dass die beiden Teile möglichst quadratisch sind — und genau dort sind sie am KLEINSTEN. In beide Richtungen wächst die Datei, und die Richtungen bedeuten nicht dasselbe: ein niedriger Faktor (4–8) schiebt das Gewicht in den zweiten Teil, wo die Kapazität des Adapters sitzt — das ist das LyCORIS-Rezept für eine LoKr, die nicht genug lernt. Ein Faktor weit über dem quadratischen Schnitt lässt stattdessen den ersten, dichten Teil wachsen, was Größe kostet und nichts bringt.\n\nGemessen an einer 1280 breiten Schicht bei Rang 8, gegen die LoRA derselben Schicht: automatisch 0,08x, Faktor 8 0,13x, Faktor 4 0,25x, Faktor 128 0,81x.\n\nEs gibt selten einen Grund, ihn zu setzen. Lernt eine LoKr nicht genug, erhöhe zuerst den Rang und probiere dann einen niedrigen Faktor.",
  "Every picture this finds is also matched by a training query, so it contributes nothing and the run will not be regularized. Narrow it to pictures the run is NOT about.":
    "Jedes Bild, das dies findet, trifft auch eine Trainingsabfrage — der Pool trägt also nichts bei und der Lauf wird nicht regularisiert. Grenze ihn auf Bilder ein, um die es im Lauf NICHT geht.",
  "val": "Val.",
  "stable": "stabil",
  "validation": "Validierung",
  "Validate": "Validieren",
  "Masked regions": "Maskierte Bereiche",
  "Mask out regions tagged": "Bereiche dieser Tags maskieren",
  "Comma-separated tags whose bounding boxes are largely ignored by the loss — e.g. 'watermark'. The picture still trains; the region inside the boxes stops teaching. Tags without boxes on an image mask nothing there.": "Kommagetrennte Tags, deren Boxen vom Verlust weitgehend ignoriert werden — z. B. 'watermark'. Das Bild trainiert weiterhin; nur der Bereich in den Boxen lehrt nichts mehr. Tags ohne Boxen auf einem Bild maskieren dort nichts.",
  "Mask out regions of tags marked": "Bereiche von so markierten Tags maskieren",
  "Comma-separated META tags. Any tag the library marks with one of these has its boxes masked — so the rule is stated once in the Tags tab rather than listed here.": "Kommagetrennte META-Tags. Jeder Tag, den die Bibliothek so kennzeichnet, bekommt seine Boxen maskiert — die Regel steht also einmal im Tags-Reiter statt hier aufgelistet.",
  "Masked region weight": "Gewicht maskierter Bereiche",
  "How much a masked region still counts. 0 hides it from training entirely; 1 is the same as not masking.": "Wie viel ein maskierter Bereich noch zählt. 0 blendet ihn vollständig aus dem Training aus; 1 ist dasselbe wie keine Maskierung.",
  "Validation": "Validierung",
  "Score a validation loss": "Validierungsverlust messen",
  "A few images are held out of training and re-scored on a fixed seed as the run goes. Falling: still learning. Rising while the training loss falls: memorizing — pick an earlier checkpoint.": "Einige Bilder werden aus dem Training herausgehalten und mit festem Seed regelmäßig neu bewertet. Fallend: lernt noch. Steigend, während der Trainingsverlust fällt: Auswendiglernen — einen früheren Checkpoint wählen.",
  "Validate every": "Validieren alle",
  "Each round costs one forward pass per scored image — a small set every few hundred steps is barely noticeable.": "Eine Runde kostet einen Forward-Durchlauf pro bewertetem Bild — ein kleiner Satz alle paar hundert Schritte fällt kaum auf.",
  "Held-out images": "Zurückgehaltene Bilder",
  "Taken OUT of training entirely and scored each round. Capped at half the dataset; 16 is plenty for a LoRA-sized run. 0 turns the held-out series off.": "Vollständig aus dem Training genommen und jede Runde bewertet. Auf die Hälfte des Datensatzes begrenzt; 16 reichen für einen LoRA-großen Lauf. 0 schaltet die Serie ab.",
  "Stable-loss images": "Bilder für stabilen Verlust",
  "Ordinary TRAINING images re-scored the same fixed way — the training curve without its sampling noise. They stay in training; 0 turns the series off.": "Gewöhnliche TRAININGS-Bilder, auf dieselbe feste Weise neu bewertet — die Trainingskurve ohne ihr Sampling-Rauschen. Sie bleiben im Training; 0 schaltet die Serie ab.",
  "Some pictures are worth training on except for one rectangle: a watermark, a shop’s caption strip, a censor bar. Left alone, the model learns the rectangle along with the picture — a run over watermarked photographs reliably teaches the watermark. Throwing those pictures out costs the dataset; this keeps them and hides the rectangle from training instead.\n\nThe regions come from the boxes already on the tag: draw a box for `watermark` in the annotator (or let the watermark detector’s tag carry one), name the tag here, and every image carrying such a box trains with the loss inside it turned down. Where a subject tag has no drawn box, its detected faces stand in, exactly as they do for crop-aware training. An image whose named tags have no boxes trains completely normally — nothing is masked there.\n\nOnly the LOSS is masked. The pixels still pass through the image encoder, so the cached latents are the ordinary ones shared with unmasked runs, and nothing is re-encoded when this setting changes. The mask lives in latent space, where one cell covers 8×8 pixels rounded outward to whole cells — so it cannot hide anything much thinner than that, and a pixel-accurate outline is not something it can promise. It also cannot conjure what is UNDER the watermark: the model simply receives no signal about that area, from this picture.\n\nPairs naturally with a tag the prompt always includes (Always include under Tag selection): the prompt says the watermark is there, the mask stops the pixels teaching it, and at generation time the model has no reason to produce one unprompted.": "Manche Bilder lohnen das Training bis auf ein Rechteck: ein Wasserzeichen, die Textleiste eines Shops, ein Zensurbalken. Unbehandelt lernt das Modell das Rechteck mit dem Bild — ein Lauf über Fotos mit Wasserzeichen bringt dem Modell zuverlässig das Wasserzeichen bei. Diese Bilder wegzuwerfen kostet den Datensatz; dies behält sie und versteckt stattdessen das Rechteck vor dem Training.\n\nDie Bereiche kommen von den Boxen, die der Tag schon hat: eine Box für `watermark` im Annotator zeichnen (oder den Tag des Wasserzeichen-Detektors eine tragen lassen), den Tag hier nennen, und jedes Bild mit so einer Box trainiert mit heruntergedrehtem Verlust darin. Wo ein Personen-Tag keine gezeichnete Box hat, springen die erkannten Gesichter ein, genau wie beim zuschnittbewussten Training. Ein Bild, dessen genannte Tags keine Boxen haben, trainiert völlig normal — dort wird nichts maskiert.\n\nNur der VERLUST wird maskiert. Die Pixel laufen weiterhin durch den Bild-Encoder, die zwischengespeicherten Latents sind also die gewöhnlichen, die auch unmaskierte Läufe teilen, und nichts wird neu kodiert, wenn sich diese Einstellung ändert. Die Maske lebt im Latent-Raum, wo eine Zelle 8×8 Pixel abdeckt, nach außen auf ganze Zellen gerundet — viel Dünneres kann sie also nicht verstecken, und eine pixelgenaue Kontur kann sie nicht versprechen. Sie kann auch nicht herbeizaubern, was UNTER dem Wasserzeichen liegt: das Modell bekommt über diese Fläche schlicht kein Signal, aus diesem Bild.\n\nPasst natürlich zu einem Tag, den der Prompt immer enthält (Immer einschließen unter Tag-Auswahl): der Prompt sagt, dass das Wasserzeichen da ist, die Maske hindert die Pixel daran, es zu lehren, und beim Generieren hat das Modell keinen Grund, ungefragt eines zu malen.",
  "The same rule, stated once in the library instead of tag by tag here. A meta tag put on the tags whose boxes should never teach — `masked`, say — covers every such tag at once, including ones created after this job was written.\n\nThe list is resolved to tag names when the dataset is built, so the job’s log says how many images actually carried a masked region. A run where that line says zero has a rule pointing at tags nobody drew boxes for.": "Dieselbe Regel, einmal in der Bibliothek gesagt statt Tag für Tag hier. Ein Meta-Tag auf den Tags, deren Boxen nie lehren sollen — etwa `masked` — deckt alle solchen Tags auf einmal ab, auch später angelegte.\n\nDie Liste wird beim Aufbau des Datensatzes zu Tag-Namen aufgelöst, das Log des Auftrags sagt also, wie viele Bilder tatsächlich einen maskierten Bereich trugen. Steht dort null, zeigt die Regel auf Tags, für die niemand Boxen gezeichnet hat.",
  "What a cell inside a masked box still counts for. 0 hides the region entirely, which is the usual choice for a watermark — there is nothing in it worth a whisper. A small value (0.05–0.2) keeps a faint signal, which can be worth it when the boxes are generous and cover real picture around the thing being hidden.\n\n1 is the unmasked loss, so setting it there is the same as clearing the tag lists. Where an image also trains with an alpha mask, the two multiply: a masked region on a transparent background is doubly not the picture.": "Wie viel eine Zelle in einer maskierten Box noch zählt. 0 blendet den Bereich vollständig aus — die übliche Wahl für ein Wasserzeichen, in dem nichts ein Flüstern wert ist. Ein kleiner Wert (0,05–0,2) behält ein schwaches Signal, was sich lohnen kann, wenn die Boxen großzügig sind und echtes Bild um das zu Versteckende herum abdecken.\n\n1 ist der unmaskierte Verlust, es dort zu setzen ist also dasselbe wie die Tag-Listen zu leeren. Trainiert ein Bild zugleich mit Alpha-Maske, multiplizieren sich die beiden: ein maskierter Bereich auf transparentem Hintergrund ist doppelt nicht das Bild.",
  "The training loss cannot answer the question people ask of it. It is drawn from the pictures being trained on, at a different random noise level every step, so it is noisy by construction — and it keeps falling for as long as the model memorizes, which means it looks healthiest exactly when a run has gone on too long.\n\nThis scores two extra series that can answer it, both with the plain per-sample loss on a fixed seed, so every round asks the model exactly the same questions and the number moves only when the model does. The series appear as their own lines on the loss graph, and each round is a line in the job’s log.\n\nReading it: the validation loss falls while the model generalizes and flattens or turns when it starts memorizing — the turning point is roughly where to stop, and with step snapshots on, the checkpoint to pick. Expect it to sit above the training loss and to move in small amounts; what matters is the direction, not the level. It stays comparable across pauses, resumes and step extensions, because the scored images and the seed never change within a job.": "Der Trainingsverlust kann die Frage nicht beantworten, die man ihm stellt. Er wird aus den trainierten Bildern gezogen, jeden Schritt auf einem anderen zufälligen Rauschniveau, ist also konstruktionsbedingt verrauscht — und er fällt weiter, solange das Modell auswendig lernt, sieht also genau dann am gesündesten aus, wenn ein Lauf zu lange lief.\n\nDies misst zwei zusätzliche Serien, die sie beantworten können, beide mit dem einfachen Verlust pro Bild auf festem Seed, sodass jede Runde dem Modell exakt dieselben Fragen stellt und sich die Zahl nur bewegt, wenn das Modell es tut. Die Serien erscheinen als eigene Linien im Verlustgraphen, und jede Runde ist eine Zeile im Log des Auftrags.\n\nSo liest man es: der Validierungsverlust fällt, solange das Modell generalisiert, und flacht ab oder dreht, wenn es anfängt auswendig zu lernen — der Wendepunkt ist ungefähr, wo man aufhören sollte, und mit Schritt-Snapshots der Checkpoint, den man nimmt. Er liegt erwartbar über dem Trainingsverlust und bewegt sich in kleinen Beträgen; was zählt, ist die Richtung, nicht das Niveau. Über Pausen, Fortsetzungen und Schritt-Verlängerungen bleibt er vergleichbar, weil die bewerteten Bilder und der Seed sich innerhalb eines Auftrags nie ändern.",
  "How often a round runs, in steps. A round costs one forward pass per scored image — no gradients, no optimizer — so a 16-image set is a few seconds; matching the sample or checkpoint cadence keeps the graph, the images and the snapshots telling one story at the same steps.\n\nVery frequent rounds buy little: overfitting announces itself over hundreds of steps, not five.": "Wie oft eine Runde läuft, in Schritten. Eine Runde kostet einen Forward-Durchlauf pro bewertetem Bild — keine Gradienten, kein Optimizer — ein Satz von 16 Bildern ist also ein paar Sekunden; die Kadenz der Testbilder oder Checkpoints zu übernehmen lässt Graph, Bilder und Snapshots an denselben Schritten eine Geschichte erzählen.\n\nSehr häufige Runden bringen wenig: Overfitting kündigt sich über hunderte Schritte an, nicht über fünf.",
  "How many images are set aside for the validation loss. They are taken OUT of training entirely — never visited, in no pool, their captions never seen — because a loss over pictures the model is also memorizing measures nothing. The pick is random but fixed per job, whole images at a time (a picture cannot be half in training), regularization pools are not eligible, and it is capped at half the dataset so the setting can never eat the run it protects.\n\nMore images make a steadier line at a linearly higher cost per round. On a small dataset every held-out image is also a training image lost, which is the real price — 8–16 is usually enough to see the turn, and the job’s log says exactly how many were held out.": "Wie viele Bilder für den Validierungsverlust beiseitegelegt werden. Sie werden vollständig aus dem Training genommen — nie besucht, in keinem Pool, ihre Captions nie gesehen — denn ein Verlust über Bilder, die das Modell zugleich auswendig lernt, misst nichts. Die Auswahl ist zufällig, aber je Auftrag fest, immer ganze Bilder (ein Bild kann nicht halb im Training sein), Regularisierungs-Pools sind nicht wählbar, und sie ist auf die Hälfte des Datensatzes begrenzt, damit die Einstellung nie den Lauf auffrisst, den sie schützt.\n\nMehr Bilder machen eine ruhigere Linie zu linear höheren Kosten pro Runde. Bei einem kleinen Datensatz ist jedes zurückgehaltene Bild auch ein verlorenes Trainingsbild, was der eigentliche Preis ist — 8–16 reichen meist, um die Wende zu sehen, und das Log des Auftrags sagt genau, wie viele zurückgehalten wurden.",
  "A second series over ordinary TRAINING images: a fixed slice, re-scored with the same fixed seed each round. Nothing is held out — these stay in training — so it costs no data at all.\n\nWhat it shows is the training curve with the sampling noise removed. The per-step loss jumps around because every step draws different pictures at different noise levels; this line asks the same pictures at the same noise every time, so it is readable where the raw curve is a cloud. Compared against the held-out line it also localizes trouble: both falling is learning, stable falling while held-out rises is memorizing, and neither falling means the run is not learning at all.": "Eine zweite Serie über gewöhnliche TRAININGS-Bilder: ein fester Ausschnitt, jede Runde mit demselben festen Seed neu bewertet. Nichts wird zurückgehalten — diese bleiben im Training — es kostet also gar keine Daten.\n\nSie zeigt die Trainingskurve ohne das Sampling-Rauschen. Der Verlust pro Schritt springt, weil jeder Schritt andere Bilder auf anderen Rauschniveaus zieht; diese Linie stellt jedes Mal denselben Bildern dieselben Fragen und ist lesbar, wo die rohe Kurve eine Wolke ist. Gegen die zurückgehaltene Linie gehalten verortet sie auch das Problem: fallen beide, wird gelernt; fällt die stabile, während die zurückgehaltene steigt, wird auswendig gelernt; fällt keine, lernt der Lauf gar nichts.",
  "Save the current rules, or load a saved set": "Aktuelle Regeln speichern oder einen gespeicherten Satz laden",
  "Rule sets": "Regelsätze",
  "Remember the current rules — name the set in this list afterwards": "Aktuelle Regeln merken — den Satz danach in dieser Liste benennen",
  "Add a rule first": "Zuerst eine Regel hinzufügen",
  "Save current rules": "Aktuelle Regeln speichern",
  "Add this set's rules to the job — rows it already has stay put": "Die Regeln dieses Satzes dem Job hinzufügen — vorhandene Zeilen bleiben",
  "Value rules": "Wert-Regeln",
  "Turn numeric value tags (height:172cm) into words at prompt time. The first matching rule wins — drag rows to reorder.": "Numerische Wert-Tags (height:172cm) zur Prompt-Zeit in Worte übersetzen. Die erste passende Regel gewinnt — Zeilen per Ziehen ordnen.",
  "namespace, e.g. height": "Namensraum, z. B. height",
  "Keep the raw tag in the prompt beside the rule's text": "Den rohen Tag neben dem Text der Regel im Prompt behalten",
  "keep tag": "Tag behalten",
  "Remove this rule": "Diese Regel entfernen",
  "Add rule": "Regel hinzufügen",
  "Any tag shaped `<name>:<number><unit>` is a value tag — `people:3`, `height:172cm`, `height:1.72m`, or a ranking’s own `quality:7` — and a rule here turns a range of those numbers into words at prompt time: where `height` is greater than 190cm, write `tall`. A raw `height:172cm` token teaches a text encoder nothing it can read back at generation time; a word does.\n\nA matching tag is replaced by the rule’s text, and a per-rule toggle keeps the raw tag alongside for whoever wants both spellings in the prompt. The metric length and mass families convert, so one rule covers `172cm` and `1.72m` alike; an unknown unit compares only against the same unit, and a plain number only against plain numbers.\n\nRanges may overlap, and the first matching rule wins — the rows are dragged into order, and that order is part of the configuration. A value tag no rule matches passes through the prompt unchanged, so nothing is dropped silently. The rule’s phrase rides the ordinary random pick and dropout like the tag it replaced: prompts sometimes carry it and sometimes do not, which is exactly the variation score-tag conditioning wants.\n\nThe rules are resolved when the dataset is built — the job’s log says how many tags they matched — and a set of rules can be saved and loaded by name, so a house vocabulary is written once and reused across jobs. Loading a set adds its missing rules to the job rather than replacing the rows already there.": "Jeder Tag der Form `<name>:<zahl><einheit>` ist ein Wert-Tag — `people:3`, `height:172cm`, `height:1.72m` oder das `quality:7` eines Rankings — und eine Regel hier übersetzt einen Zahlenbereich zur Prompt-Zeit in Worte: wo `height` größer als 190cm ist, schreibe `tall`. Ein rohes `height:172cm`-Token lehrt einen Text-Encoder nichts, was er bei der Generierung zurücklesen könnte; ein Wort schon.\n\nEin passender Tag wird durch den Text der Regel ersetzt, und ein Schalter pro Regel behält den rohen Tag daneben, wenn beide Schreibweisen im Prompt stehen sollen. Die metrischen Längen- und Massefamilien rechnen um, eine Regel deckt also `172cm` und `1.72m` gleichermaßen ab; eine unbekannte Einheit vergleicht sich nur mit derselben Einheit und eine reine Zahl nur mit reinen Zahlen.\n\nBereiche dürfen sich überlappen, die erste passende Regel gewinnt — die Zeilen werden per Ziehen geordnet, und diese Reihenfolge ist Teil der Konfiguration. Ein Wert-Tag, auf den keine Regel passt, geht unverändert in den Prompt, nichts wird still verworfen. Die Formulierung der Regel folgt der gewohnten Zufallsauswahl und dem Dropout wie der ersetzte Tag: Prompts tragen sie mal und mal nicht — genau die Variation, die Score-Tag-Konditionierung braucht.\n\nDie Regeln werden beim Aufbau des Datensatzes aufgelöst — das Log des Jobs sagt, wie viele Tags sie getroffen haben — und ein Regelsatz lässt sich unter Namen speichern und laden, ein Haus-Vokabular wird also einmal geschrieben und über Jobs hinweg verwendet. Das Laden eines Satzes ergänzt die fehlenden Regeln, statt vorhandene Zeilen zu ersetzen.",
  "Write tags as":
    "Tags schreiben als",
  "Their name":
    "ihr Name",
  "Their comment":
    "ihr Kommentar",
  "Name and comment":
    "Name und Kommentar",
  "A tag's comment is the one line beside its name in the Tags tab — the same idea in words a text encoder can read. A tag with no comment is written as its name.":
    "Der Kommentar eines Tags ist die eine Zeile neben seinem Namen im Tags-Tab – dieselbe Idee in Worten, die ein Text-Encoder lesen kann. Ein Tag ohne Kommentar wird als sein Name geschrieben.",
  "A tag's comment is the one line beside its name in the Tags tab — “one girl in the picture” for `1girl`, “from below, looking up at the subject” for `from_below`. A booru vocabulary is compact for the people typing it and opaque to a text encoder; the comment is the same idea in words the encoder can read.\n\n“Their name” is what every run did: the tag as it is spelled. “Their comment” writes the comment in place of the name wherever a picked tag has one, and “Name and comment” writes the name with the comment in brackets after it, so the model learns both spellings of one thing. A tag with no comment is written as its name whatever this says.\n\nOnly the PROMPT changes. Matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all stay keyed on the tag's name, exactly as with aliases — and the comment is read from the library when the dataset is built, so editing a comment later changes the next run, not this one.":
    "Der Kommentar eines Tags ist die eine Zeile neben seinem Namen im Tags-Tab – „ein Mädchen im Bild“ für `1girl`, „von unten, zum Motiv aufblickend“ für `from_below`. Ein Booru-Vokabular ist kompakt für die, die es tippen, und undurchsichtig für einen Text-Encoder; der Kommentar ist dieselbe Idee in Worten, die der Encoder lesen kann.\n\n„Ihr Name“ ist, was jeder Lauf bisher tat: das Tag, wie es geschrieben ist. „Ihr Kommentar“ schreibt den Kommentar an die Stelle des Namens, wo ein gewähltes Tag einen hat, und „Name und Kommentar“ schreibt den Namen mit dem Kommentar in Klammern dahinter, sodass das Modell beide Schreibweisen einer Sache lernt. Ein Tag ohne Kommentar wird in jedem Fall als sein Name geschrieben.\n\nNur der PROMPT ändert sich. Matching, die Immer-/Ausschluss-Listen, die Häufigkeitsbalance, das Loss-Gewicht und die Boxen, die ein Ausschnitt behalten muss, bleiben am Namen des Tags verankert, genau wie bei Aliassen – und der Kommentar wird beim Bauen des Datensatzes aus der Bibliothek gelesen, sodass ein später geänderter Kommentar den nächsten Lauf ändert, nicht diesen.",
  "Remove the selected images?": "Die ausgewählten Bilder entfernen?",
  "They cannot be recovered.": "Sie können nicht wiederhergestellt werden.",
  "Delete all {n} results from this session?": "Alle {n} Ergebnisse dieser Sitzung löschen?",
  "The generated images go with them.": "Die erzeugten Bilder verschwinden mit ihnen.",
  "Its downloaded weights can go with it, or stay in the cache for a later download to find.": "Die heruntergeladenen Gewichte können mit entfernt werden oder im Cache bleiben, wo ein späterer Download sie findet.",
  "Remove and delete weights": "Entfernen und Gewichte löschen",
  "Remove the training job “{name}”?": "Trainingsauftrag „{name}“ entfernen?",
  "Remove {n} training jobs?": "{n} Trainingsaufträge entfernen?",
  "Its checkpoints, test samples and trained result are deleted with it — except anything locked, which is kept in the LoRAs list. This cannot be undone.": "Seine Checkpoints, Testbilder und das trainierte Ergebnis werden mit entfernt, und das lässt sich nicht rückgängig machen. Ausgenommen ist alles Gesperrte, das in der LoRA-Liste erhalten bleibt.",
  "Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone.": "Ihre Checkpoints, Testbilder und trainierten Ergebnisse werden mit entfernt, und das lässt sich nicht rückgängig machen. Ausgenommen ist alles Gesperrte, das in der LoRA-Liste erhalten bleibt.",
  "The Train tab": "Der Trainieren-Tab",
  "The Evaluate tab": "Der Auswerten-Tab",
  "The Models tab": "Der Modelle-Tab",
  "Your models": "Deine Modelle",
  "Finetunes": "Finetunes",
  "Based on {model}": "Basiert auf {model}",
  "A full finetune of {model}": "Ein vollständiges Finetune von {model}",
  "The built-in release, one of your own models, or a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.": "Die eingebaute Version, eines deiner eigenen Modelle oder die Gewichte eines vollständigen Finetunes anstelle der des Basismodells. Adapter kommen auf das, was hier gewählt ist, obendrauf.",
};

export default CATALOG;
