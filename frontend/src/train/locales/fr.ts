// territory like locales/de.ts; see docs/translating.md for conventions.

import type { Catalog } from "../../shared/i18nCore";

const CATALOG: Catalog = {
  "default":
    "par défaut",
  "This model's own size. A job set to it follows whichever model it is pointed at.":
    "La taille propre de ce modèle. Une session réglée dessus suit le modèle vers lequel elle pointe.",
  "{n} px":
    "{n} px",
  "A run trains at one size at least.":
    "Une session s'entraîne à au moins une taille.",
  "A run trains at up to five sizes — each one is another pass over the dataset per epoch.":
    "Une session s'entraîne à cinq tailles au maximum — chacune est un passage de plus sur le jeu de données par époque.",
  "e.g. 704":
    "p. ex. 704",
  "Another size…":
    "Une autre taille…",
  "Pick every size this run should train at. A picture joins each one it is big enough for, so the same picture can be learnt at more than one scale — and each size is another pass over the dataset per epoch.":
    "Choisissez chaque taille à laquelle cette session doit s'entraîner. Une image rejoint chacune de celles pour lesquelles elle est assez grande : la même image est donc apprise à plusieurs échelles — et chaque taille est un passage de plus sur le jeu de données par époque.",
  "Left empty both fields use the model's own size — a test sample is not tied to the sizes the run trains at.":
    "Laissés vides, les deux champs utilisent la taille propre du modèle — une image de test n'est pas liée aux tailles auxquelles la session s'entraîne.",
  "The sizes images are trained at, each given as one number that stands for a pixel budget: 1024 means 'about a megapixel', which every aspect-ratio bucket then spends differently — 1024×1024, or 1216×832, or 832×1216.\n\nMatch them to what the base model was trained on (1024 for SDXL, Chroma and FLUX.2, 512 for SD 1.5); training far above that teaches little and costs a lot, while training below it is a genuine speed and memory lever at the price of fine detail. Cost scales with the area, so 768 is nearly half the work per step that 1024 is. The size the list marks as default is the model's own, and a job set to it follows whichever model it is pointed at.\n\nPicking more than one trains the same pictures at each of them. A model that has only ever seen a subject at 1024 has learnt it together with the canvas it was on: asked for something smaller it tends to answer with a crop or a doubled-up version of the same framing. Several sizes separate what the model learns about the subject from what it learns about the shape of the picture.\n\nEach size is a full family of buckets, and every image joins the ones it is large enough for — which is the other half of what this is for. Under Never upscale a 700-pixel scan is simply left out of a 1024 run; add 512 and it trains there instead of being dropped, while the large pictures keep training at both.\n\nIt is not free. A size is another pass over the dataset in every epoch and another cached latent per picture, and the batches at the largest one decide the peak memory — so adding a size above the others raises what the run needs on the card, and adding ones below mainly makes an epoch longer. Two or three an octave apart (512, 768, 1024) is the usual shape; at most five.":
    "Les tailles auxquelles les images sont entraînées, chacune donnée comme un nombre qui représente un budget de pixels : 1024 veut dire « environ un mégapixel », que chaque bucket de rapport d'aspect dépense autrement — 1024×1024, 1216×832 ou 832×1216.\n\nAlignez-les sur ce sur quoi le modèle de base a été entraîné (1024 pour SDXL, Chroma et FLUX.2, 512 pour SD 1.5) ; s'entraîner bien au-dessus apprend peu et coûte cher, tandis qu'en dessous c'est un vrai levier de vitesse et de mémoire, au prix du détail fin. Le coût suit la surface : 768 est presque moitié moins de travail par pas que 1024. La taille que la liste marque par défaut est celle du modèle, et une session réglée dessus suit le modèle vers lequel elle pointe.\n\nEn choisir plusieurs entraîne les mêmes images à chacune d'elles. Un modèle qui n'a jamais vu un sujet qu'à 1024 l'a appris avec la toile sur laquelle il se trouvait : si on lui demande plus petit, il répond en général par un recadrage ou une version dédoublée du même cadrage. Plusieurs tailles séparent ce que le modèle apprend du sujet de ce qu'il apprend de la forme de l'image.\n\nChaque taille est une famille de buckets complète, et chaque image rejoint celles pour lesquelles elle est assez grande — l'autre moitié de son intérêt. Avec « Ne jamais agrandir », un scan de 700 pixels est simplement écarté d'une session à 1024 ; ajoutez 512 et il s'y entraîne au lieu d'être abandonné, tandis que les grandes images continuent de s'entraîner aux deux.\n\nCe n'est pas gratuit. Une taille, c'est un passage de plus sur le jeu de données à chaque époque et un latent mis en cache de plus par image, et les lots à la plus grande décident de la mémoire de pointe — ajouter une taille au-dessus des autres augmente donc ce que la session demande à la carte, et en ajouter en dessous allonge surtout l'époque. Deux ou trois séparées d'une octave (512, 768, 1024) est la forme habituelle ; cinq au maximum.",
  "An image smaller than its bucket has to be enlarged to train at that size, and enlarging invents detail that was never in the picture: soft edges, smeared texture, the interpolation's own look. Trained on, that is what the model learns the subject looks like.\n\nThis is on by default. Those images are left out while the dataset is built — before anything is encoded, so they cost no time and no cache — and the run says how many it dropped. It is asked per resolution, so a picture too small for the largest size still trains at a smaller one rather than being dropped from the run; turn it off for a small dataset, where a slightly soft picture is usually worth more than no picture.":
    "Une image plus petite que son bucket doit être agrandie pour s'entraîner à cette taille, et agrandir invente du détail qui n'a jamais été dans l'image : bords mous, texture étalée, le rendu propre de l'interpolation. Entraîné là-dessus, c'est ce que le modèle apprend de l'apparence du sujet.\n\nC'est activé par défaut. Ces images sont écartées pendant la construction du jeu de données — avant tout encodage, elles ne coûtent donc ni temps ni cache — et la session dit combien elle en a écartées. La question est posée par résolution : une image trop petite pour la plus grande taille s'entraîne quand même à une plus petite au lieu d'être abandonnée. Désactivez-le pour un petit jeu de données, où une image un peu molle vaut généralement mieux que pas d'image.",
  "New training job": "Nouveau job d'entraînement",
  "Drafts": "Brouillons",
  "Paused": "En pause",
  "Completed": "Terminés",
  "Failed": "Échoués",
  "Full finetune": "Finetuning complet",
  "Loss appears here once training starts.": "La perte apparaît ici quand l'entraînement démarre.",
  "Test samples": "Échantillons de test",
  "Select a job to see its progress, samples and settings.": "Sélectionnez un job pour voir son avancement, ses échantillons et ses réglages.",
  "No training jobs yet. Create one to fine-tune a model (LoRA or full) on images selected straight from your library.": "Pas encore de job d'entraînement. Créez-en un pour affiner un modèle (LoRA ou complet) sur des images choisies directement dans votre bibliothèque.",
  "Training environment not set up": "Environnement d'entraînement non configuré",
  "Edit training job": "Modifier le job d'entraînement",
  "Save draft": "Enregistrer le brouillon",
  "Save & queue": "Enregistrer et mettre en file",
  "Method": "Méthode",
  "Hyperparameters": "Hyperparamètres",
  "Memory & speed": "Mémoire et vitesse",
  "Canceled before any image was generated": "Annulé avant toute génération d'image",
  "{done} of {total} images": "{done} images sur {total}",
  "not generated yet": "pas encore généré",
  "Download this LoRA": "Télécharger ce LoRA",
  "NVIDIA only": "NVIDIA seulement",
  "Off (fused kernels)": "Désactivé (noyaux fusionnés)",
  "On (save VRAM)": "Activé (économise la VRAM)",
  "needs an NVIDIA GPU": "exige un GPU NVIDIA",
  "needs an NVIDIA GPU (Ada or newer)": "exige un GPU NVIDIA (Ada ou plus récent)",
  "this model has none": "ce modèle n'en a pas",
  "8-bit float (fp8)": "flottant 8 bits (fp8)",
  "8-bit (int8)": "8 bits (int8)",
  "FLUX.2 Klein (base, 4B)": "FLUX.2 Klein (base, 4B)",
  "Images are being generated": "Les images sont en cours de génération",
  "= 1 image": "= 1 image",
  "= {n} images": { one: "= {n} image", other: "= {n} images" },
  "Length & learning rate": "Durée et taux d'apprentissage",
  "Dataset": "Données",
  "Add query": "Ajouter une requête",
  "Remove query": "Retirer la requête",
  "invalid query": "requête invalide",
  "Empty query = every image in the library.": "Requête vide = toutes les images de la bibliothèque.",
  "Total steps": "Pas au total",
  "Learning rate": "Taux d'apprentissage",
  "Batch size": "Taille de lot",
  "Gradient accumulation": "Accumulation de gradient",
  "Rank": "Rang",
  "Train text encoder": "Entraîner l'encodeur de texte",
  "Checkpoints": "Checkpoints",
  "Checkpoint every": "Checkpoint tous les",
  "Cache latents": "Mettre les latents en cache",
  "Random crop": "Recadrage aléatoire",
  "Resolutions":
    "Résolutions",
  "Crops & flips":
    "Recadrage et miroir",
  "Max aspect ratio": "Rapport d'aspect max",
  "Horizontal flip probability": "Probabilité de miroir horizontal",
  "Trigger word": "Mot déclencheur",
  "Only captions tagged": "Seulement les légendes taguées",
  "Skip captions tagged": "Ignorer les légendes taguées",
  "Only instructions tagged": "Seulement les instructions taguées",
  "Skip instructions tagged": "Ignorer les instructions taguées",
  "Comma-separated meta tags whose instructions are never used. Applied after the include list, so it also removes instructions the list let in.": "Méta-tags séparés par des virgules dont les instructions ne sont jamais utilisées. Appliqué après la liste d'inclusion, il retire donc aussi les instructions qu'elle avait laissées entrer.",
  "Comma-separated meta tags whose captions are never used. Applied after the include list, so it also removes captions the list let in.": "Méta-tags séparés par des virgules dont les légendes ne sont jamais utilisées. Appliqué après la liste d'inclusion, il retire donc aussi les légendes qu'elle avait laissées entrer.",
  "Always include": "Toujours inclure",
  "Skip tag groups tagged": "Ignorer les groupes de tags tagués",
  "Comma-separated meta tags naming whole tag groups to ignore: a tag placed only in such a group never reaches a prompt. The tags stay on your items.": "Méta-tags séparés par des virgules nommant des groupes de tags entiers à ignorer : un tag placé seulement dans un tel groupe n'atteint jamais un prompt. Les tags restent sur vos éléments.",
  "Min tags per prompt": "Tags min par prompt",
  "Max tags per prompt": "Tags max par prompt",
  "Pick probability": "Probabilité de tirage",
  "Uniform": "Uniforme",
  "Balance rare tags": "Équilibrer les tags rares",
  "Frequency measured in": "Fréquence mesurée dans",
  "Training data": "Données d'entraînement",
  "Previous step": "Pas précédent",
  "Next step": "Pas suivant",
  "(empty prompt)": "(prompt vide)",
  "Show each step's min/max micro-batch loss": "Afficher la perte min/max des micro-lots de chaque pas",
  "Expand graph": "Déplier le graphique",
  "Collapse graph": "Replier le graphique",
  "steps/s": "pas/s",
  "Smooth the line (EMA)": "Lisser la courbe (EMA)",
  "Whole library": "Bibliothèque entière",
  "Weight loss by tag rarity": "Pondérer la perte par rareté de tag",
  "Shuffle tag order": "Mélanger l'ordre des tags",
  "Caption dropout": "Dropout de légende",
  "Generate every": "Générer tous les",
  "Negative prompt": "Prompt négatif",
  "Nothing (trigger word only)": "Rien (mot déclencheur seul)",
  "Every prompt is the trigger word and nothing else, so every selected picture is in the run whatever it carries. Tag and caption selection do not apply.": "Chaque invite est le mot déclencheur et rien d’autre : chaque image sélectionnée est donc dans le run, quel que soit ce qu’elle porte. La sélection de tags et de légendes ne s’applique pas.",
  "Every prompt would be EMPTY — with no text at all, there is nothing for the model to bind what it sees to. Set a trigger word below.": "Chaque invite serait VIDE — sans aucun texte, le modèle n’a rien à quoi rattacher ce qu’il voit. Définissez un mot déclencheur ci-dessous.",
  "Caption + tags": "Légende + tags",
  "Pause (saves a checkpoint)": "Pause (enregistre un checkpoint)",
  "{d} trained": "{d} d'entraînement",
  "Training started": "Entraînement démarré",
  "Training resumed": "Entraînement repris",
  "Training paused": "Entraînement en pause",
  "Training completed": "Entraînement terminé",
  "Training failed": "Entraînement échoué",
  "Training canceled": "Entraînement annulé",
  "Baseline before training": "Référence avant entraînement",
  "Checkpoint": "Checkpoint",
  "Download checkpoint": "Télécharger le checkpoint",
  "Delete checkpoint": "Supprimer le checkpoint",
  "Delete this checkpoint from disk?": "Supprimer ce checkpoint du disque ?",
  "Extend steps": "Prolonger les pas",
  "Edit steps": "Modifier les pas",
  "Base model": "Modèle de base",
  "LoRAs": "LoRA",
  "Edit this model": "Modifier ce modèle",
  "Edit model": "Modifier le modèle",
  "Edit LoRA": "Modifier le LoRA",
  "Edit this LoRA": "Modifier ce LoRA",
  "Unlock": "Déverrouiller",
  "Lock": "Verrouiller",
  "Unlock — deleting the job will take this LoRA with it": "Déverrouiller — supprimer la tâche emportera ce LoRA",
  "Lock — keeps this LoRA when the job is deleted": "Verrouiller — conserve ce LoRA à la suppression de la tâche",
  "Lock — protects this checkpoint from deletion, from the keep-last rule, and from the job being deleted": "Verrouiller — protège ce point de contrôle de la suppression, de la règle des derniers conservés et de la suppression de la tâche",
  "Add LoRA": "Ajouter un LoRA",
  "Click to use this value for the next generation": "Cliquez pour utiliser cette valeur à la prochaine génération",
  "Output": "Sortie",
  "Size presets": "Préréglages de taille",
  "Random seed": "Graine aléatoire",
  "A new seed is drawn each time you click Generate; the field below shows the seed used for the last generation.": "Une nouvelle graine est tirée à chaque clic sur Générer ; le champ ci-dessous montre celle de la dernière génération.",
  "Remove this generation and its images?": "Supprimer cette génération et ses images ?",
  "Open the image in a new tab": "Ouvrir l'image dans un nouvel onglet",
  "Remove the selected images? They cannot be recovered.": "Supprimer les images sélectionnées ? Elles ne pourront pas être récupérées.",
  "Remove the selected images (a generation that is still running stays)": "Supprimer les images sélectionnées (une génération encore en cours est conservée)",
  "Stop the selected generations (the images they have made are kept)": "Arrêter les générations sélectionnées (les images déjà produites sont conservées)",
  "Put every setting that made this picture into the form": "Reporter dans le formulaire tous les réglages qui ont produit cette image",
  "Use all settings": "Utiliser tous les réglages",
  "Preview the selected image (Space)": "Aperçu de l'image sélectionnée (Espace)",
  "Image {i} of {n}": "Image {i} sur {n}",
  "Up next": "À suivre",
  "Add to the queue": "Ajouter à la file",
  "A training job is running": "Un job d'entraînement est en cours",
  "Drag to change the queue order": "Glissez pour changer l'ordre de la file",
  "How the drafts below are ordered":
    "L’ordre des brouillons ci-dessous",
  "Newest first":
    "Plus récents d’abord",
  "Manual order":
    "Ordre manuel",
  "Drag to reorder — or into Up next to queue the job":
    "Faites glisser pour réordonner — ou vers À suivre pour mettre le job en file",
  "Remove every finished job, with its checkpoints and samples":
    "Supprimer tous les jobs terminés, avec leurs points de contrôle et leurs échantillons",
  "Drag into Up next to queue the job": "Glissez dans « À suivre » pour mettre le job en file",
  "Drop here to put the job on hold.": "Déposez ici pour mettre le job en attente.",
  "Prepare": "Préparer",
  "Keep the last": "Garder les derniers",
  "When a new snapshot is written the oldest of these is deleted, so the window never grows. A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk. The resumable checkpoint is kept outside this limit and never counts against it.": "Quand un nouvel instantané s'écrit, le plus ancien de ceux-ci est supprimé, la fenêtre ne grandit donc jamais. Un instantané LoRA est petit (dizaines de Mo) et vous pouvez en garder une douzaine ; un instantané de finetuning complet fait la taille du modèle entier, deux ou trois font donc déjà beaucoup de disque. Le checkpoint de reprise est tenu hors de cette limite et n'y compte jamais.",
  "Also keep one in": "En garder aussi un sur",
  "A rolling window at the end of the run. 0 keeps none by recency.": "Une fenêtre glissante en fin de run. 0 n'en garde aucun par récence.",
  "Kept for good, on top of the window above.": "Gardés pour de bon, en plus de la fenêtre ci-dessus.",
  "A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk.": "Un instantané LoRA est petit (dizaines de Mo) et vous pouvez en garder une douzaine ; un instantané de finetuning complet fait la taille du modèle entier, deux ou trois font donc déjà beaucoup de disque.",
  "in 1 step": "dans 1 pas",
  "in {n} steps": { one: "dans {n} pas", other: "dans {n} pas" },
  "Keep as checkpoint": "Garder comme checkpoint",
  "Backward": "Passe arrière",
  "warmup": "échauffement",
  "Settings changed": "Réglages modifiés",
  "Dataset changed": "Jeu de données modifié",
  "{n} items added":
    { one: "{n} élément ajouté", other: "{n} éléments ajoutés" },
  "{n} items removed":
    { one: "{n} élément retiré", other: "{n} éléments retirés" },
  "Measured over the last steps of this run": "Mesuré sur les derniers pas de ce run",
  "about {d} left": "environ {d} restant",
  "The images this run trains on, sorted into aspect-ratio buckets": "Les images de ce run, triées en buckets de rapport d'aspect",
  "{n} images": { one: "{n} image", other: "{n} images" },
  "{n} from video": { one: "{n} depuis une vidéo",
                     other: "{n} depuis une vidéo" },
  "{n} buckets": { one: "{n} bucket", other: "{n} buckets" },
  "Training job settings": "Réglages du job d'entraînement",
  "Save as new job": "Enregistrer comme nouveau job",
  "Hide system statistics": "Masquer les statistiques système",
  "Show system statistics": "Afficher les statistiques système",
  "loading model": "chargement du modèle",
  "caching latents": "mise en cache des latents",
  "Degradation": "Dégradation",
  "Add variant": "Ajouter une variante",
  "Remove every variant from this job": "Retirer toutes les variantes de ce job",
  "Remove this variant": "Retirer cette variante",
  "JPEG re-encode": "Réencodage JPEG",
  "Video codec (h264 / h265)": "Codec vidéo (h264 / h265)",
  "Resolution loss": "Perte de résolution",
  "JPEG": "JPEG",
  "video codec": "codec vidéo",
  "resolution loss": "perte de résolution",
  "Chroma subsampling": "Sous-échantillonnage chromatique",
  "How much color detail is thrown away. 4:2:0 is what almost every real JPEG uses.": "Combien de détail de couleur est jeté. 4:2:0 est ce qu'utilise presque chaque vrai JPEG.",
  "Codec": "Codec",
  "CRF": "CRF",
  "The codec's quality number, counting the other way round: HIGHER is worse. Above about 32 a frame visibly falls apart.": "Le nombre de qualité du codec, compté à l'envers : PLUS HAUT est pire. Au-dessus de 32 environ, une image se délite visiblement.",
  "Scale": "Échelle",
  "Nearest gives the hard, blocky look of a badly upscaled screenshot; bilinear the soft one.": "Au plus proche donne l'aspect dur et pixelisé d'une capture mal agrandie ; bilinéaire l'aspect doux.",
  "Bilinear": "Bilinéaire",
  "Bicubic": "Bicubique",
  "Lanczos": "Lanczos",
  "Passes": "Passes",
  "Visits per clean visit": "Visites par visite propre",
  "How often this variant is drawn beside the picture it was made from. 0.25 = one degraded visit per four clean ones.": "À quelle fréquence cette variante est tirée à côté de l'image dont elle vient. 0,25 = une visite dégradée pour quatre propres.",
  "Cached variations per picture": "Variations en cache par image",
  "How many separately-drawn values each picture gets. 1 already spreads the range across the dataset; more spreads it within one picture, and multiplies the cache.": "Combien de valeurs tirées séparément chaque image reçoit. 1 étale déjà la plage sur le jeu de données ; plus l'étale dans une même image, et multiplie le cache.",
  "jpeg_artifacts, low_quality": "jpeg_artifacts, low_quality",
  "Always in this sample's prompt: never dropped by the random tag pick, the tag cap, or caption dropout.": "Toujours dans le prompt de cet échantillon : jamais écarté par le tirage aléatoire, le plafond de tags ou le dropout de légende.",
  "Remove tags if present": "Retirer les tags si présents",
  "masterpiece, absurdres": "masterpiece, absurdres",
  "Which pictures": "Quelles images",
  "Only pictures tagged": "Seulement les images taguées",
  "Never pictures tagged": "Jamais les images taguées",
  "Wins over the line above. Use it to leave pictures alone that are already marked as poor.": "Gagne sur la ligne du dessus. Sert à laisser tranquilles les images déjà marquées médiocres.",
  "The preview failed": "L'aperçu a échoué",
  "Select an item in the library to preview this on.": "Sélectionnez un élément dans la bibliothèque pour prévisualiser ceci dessus.",
  "gentlest": "le plus doux",
  "harshest": "le plus dur",
  "Variants": "Variantes",
  "Save the current variants, or load a saved set": "Enregistrer les variantes actuelles, ou charger un jeu enregistré",
  "Save current variants": "Enregistrer les variantes actuelles",
  "Add a variant first": "Ajoutez d'abord une variante",
  "Load this set, replacing the variants in this job": "Charger ce jeu, en remplaçant les variantes du job",
  "Of every 100 visits to a picture this applies to, {clean} are clean and the rest are degraded: {parts}.": "Sur 100 visites d'une image concernée, {clean} sont propres et le reste dégradé : {parts}.",
  "A variant with a tag filter applies to fewer pictures than the queries select, so its share is of those.": "Une variante avec filtre de tags s'applique à moins d'images que les requêtes n'en sélectionnent ; sa part vaut donc parmi celles-là.",
  "About {n} degraded files will be cached.": "Environ {n} fichiers dégradés seront mis en cache.",
  "Preset": "Préréglage",
  "Presets": "Préréglages",
  "Preset name": "Nom du préréglage",
  "Save these settings as a preset, or load one": "Enregistrer ces réglages comme préréglage, ou en charger un",
  "Save current settings": "Enregistrer les réglages actuels",
  "Start new jobs from this preset": "Démarrer les nouveaux jobs depuis ce préréglage",
  "Delete this preset": "Supprimer ce préréglage",
  "Cosine": "Cosinus",
  "Base models": "Modèles de base",
  "1 result": "1 résultat",
  "{n} results": { one: "{n} résultat", other: "{n} résultats" },
  "Delete every result in this session": "Supprimer chaque résultat de cette session",
  "Delete all {n} results from this session? The generated images go with them.": "Supprimer les {n} résultats de cette session ? Les images générées partent avec.",
  "sampling": "échantillonnage",
  "What does this do?": "À quoi cela sert-il ?",
  "This model's repository is gated: accept its license on the model page and set a Hugging Face access token, or the download will fail.": "Le dépôt de ce modèle est restreint : acceptez sa licence sur la page du modèle et définissez un jeton d'accès Hugging Face, sinon le téléchargement échouera.",
  "Click to use this prompt for the next generation": "Cliquez pour utiliser ce prompt à la prochaine génération",
  "(no prompt)": "(sans prompt)",
  "Click to use this negative prompt for the next generation": "Cliquez pour utiliser ce prompt négatif à la prochaine génération",
  "Time so far, including loading the model": "Temps écoulé, chargement du modèle compris",
  "Total time, including loading the model": "Temps total, chargement du modèle compris",
  "Remove from the queue": "Retirer de la file",
  "Select to copy": "Sélectionnez pour copier",
  "generation failed": "génération échouée",
  "Sampler steps": "Pas d'échantillonneur",
  "CFG scale": "Échelle CFG",
  "This model isn't downloaded yet, and downloads are switched off": "Ce modèle n'est pas encore téléchargé, et les téléchargements sont désactivés",
  "Loss": "Perte",
  "LoRA only": "LoRA seulement",
  "Native training resolution of these weights. Leave empty for the architecture's own.": "Résolution d'entraînement native de ces poids. Laissez vide pour celle de l'architecture.",
  "Includes 1 model you added.": "Comprend 1 modèle que vous avez ajouté.",
  "Includes": "Comprend",
  "models you added.": "modèles que vous avez ajoutés.",
  "Open this model's page on Hugging Face": "Ouvrir la page de ce modèle sur Hugging Face",
  "Remove this model": "Retirer ce modèle",
  "Based on": "Basé sur",
  "/path/to/model (diffusers folder or .safetensors)": "/path/to/model (dossier diffusers ou .safetensors)",
  "owner/repo": "owner/repo",
  "Add model": "Ajouter le modèle",
  "On disk": "Sur disque",
  "Path missing": "Chemin manquant",
  "Continue this download where it stopped": "Reprendre ce téléchargement où il s'est arrêté",
  "Partly downloaded": "Partiellement téléchargé",
  "Discard partial download": "Abandonner le téléchargement partiel",
  "This path no longer exists": "Ce chemin n'existe plus",
  "Remove from the list (the file is left alone)": "Retirer de la liste (le fichier n'est pas touché)",
  "The base model this LoRA was trained for": "Le modèle de base pour lequel ce LoRA a été entraîné",
  "/path/to/lora.safetensors": "/path/to/lora.safetensors",
  "Download this checkpoint": "Télécharger ce checkpoint",
  "Delete this checkpoint from disk": "Supprimer ce checkpoint du disque",
  "Relative sampling probability: a weight-2 query's images are drawn twice as often as a weight-1 query's.": "Probabilité relative d'échantillonnage : les images d'une requête de poids 2 sont tirées deux fois plus souvent que celles d'une requête de poids 1.",
  "Steps": "Pas",
  "Text encoder": "Encodeur de texte",
  "trained": "entraîné",
  "Prompts": "Prompts",
  "Samples": "Échantillons",
  "Training log": "Journal d'entraînement",
  "No output yet.": "Pas encore de sortie.",
  "about {v} of GPU memory": "environ {v} de mémoire GPU",
  "more than this machine's {m}": "plus que les {m} de cette machine",
  "e.g. watercolor style LoRA": "p. ex. watercolor style LoRA",
  "Model-specific": "Propre au modèle",
  "Optimization": "Optimisation",
  "LR schedule": "Plan de LR",
  "Constant": "Constant",
  "Linear decay": "Décroissance linéaire",
  "Constant + warmup": "Constant + échauffement",
  "Warmup steps": "Pas d'échauffement",
  "Ramp the learning rate up over the first N steps. Leave empty for no warmup.": "Monte le taux d'apprentissage sur les N premiers pas. Vide = pas d'échauffement.",
  "bf16 is the safe modern default. fp32 doubles memory (automatic fallback on Macs without bf16); avoid fp16 for training.": "bf16 est le défaut moderne sûr. fp32 double la mémoire (repli automatique sur les Mac sans bf16) ; évitez fp16 pour l'entraînement.",
  "Makes sampling, crops and tag picks reproducible.": "Rend échantillonnage, recadrages et tirages de tags reproductibles.",
  "LoRA": "LoRA",
  "Scales the adapter's effect; the common convention is alpha = rank. Lower alpha = weaker influence at the same rank.": "Met à l'échelle l'effet de l'adaptateur ; la convention courante est alpha = rang. Alpha plus bas = influence plus faible à rang égal.",
  "Helps the model learn a NEW trigger word, at higher overfitting risk. Guarded: it uses a lower learning rate and stops partway through training.": "Aide le modèle à apprendre un NOUVEAU mot déclencheur, à risque de surapprentissage plus élevé. Sous garde : il utilise un taux plus bas et s'arrête en cours d'entraînement.",
  "Text encoder LR": "LR de l'encodeur de texte",
  "Left empty: half the main learning rate.": "Vide : la moitié du taux principal.",
  "Stop TE after": "Arrêter le TE après",
  "Include the large encoder": "Inclure le grand encodeur",
  "T5-XXL, the encoder that reads the whole prompt — most of the memory and most of the effect. Unticked, only the small CLIP-L trains: cheap, and what most FLUX LoRA tools mean by training the text encoder.": "T5-XXL, l'encodeur qui lit tout le prompt — l'essentiel de la mémoire et de l'effet. Décoché, seul le petit CLIP-L s'entraîne : peu coûteux, et ce que la plupart des outils LoRA pour FLUX entendent par entraîner l'encodeur de texte.",
  "of total steps": "des pas totaux",
  "Keep step snapshots": "Garder des instantanés de pas",
  "Save a permanent snapshot every N steps, so the best-looking step can be picked afterwards. Off: only the resumable 'last' checkpoint is kept.": "Écrit un instantané permanent tous les N pas, pour choisir ensuite le pas qui rend le mieux. Désactivé : seul le checkpoint « last » de reprise est gardé.",
  "Gradient checkpointing": "Checkpointing de gradient",
  "Trades ~25% speed for a large VRAM saving. Recommended for full finetunes and big models.": "Échange ~25 % de vitesse contre une grande économie de VRAM. Recommandé pour les finetunings complets et les grands modèles.",
  "Attention slicing": "Découpage de l'attention",
  "Half-precision master weights": "Poids maîtres en demi-précision",
  "Keeps the trained weights and their gradients at 16 bits instead of 32. What the rounding drops is carried to the next update, so the run learns what it would have learned; the cost is one more buffer of the same width.":
    "Garde les poids entraînés et leurs gradients sur 16 bits au lieu de 32. Ce que l'arrondi laisse tomber est reporté sur la mise à jour suivante, si bien que l'entraînement apprend ce qu'il aurait appris ; le prix est un tampon de plus de la même largeur.",
  "only for a full finetune": "uniquement pour un finetuning complet",
  "nothing to halve at full precision": "rien à réduire de moitié en pleine précision",
  "Prodigy cannot be stepped one weight at a time": "Prodigy ne peut pas être exécuté poids par poids",
  "Base model quantization": "Quantification du modèle de base",
  "None (full precision)": "Aucune (pleine précision)",
  "4-bit (NF4)": "4 bits (NF4)",
  "Optimizer": "Optimiseur",
  "Images are sorted into width/height buckets of equal area so nothing gets squashed. This caps how extreme the buckets get (2 = up to 2:1 and 1:2).": "Les images sont triées en buckets largeur/hauteur de surface égale, rien n'est donc écrasé. Ceci plafonne l'extrémité des buckets (2 = jusqu'à 2:1 et 1:2).",
  "Never flip images whose tags are marked": "Ne jamais retourner les images dont les tags sont marqués",
  "Comma-separated META tags. Any tag the library marks with one of these switches mirroring off for the pictures carrying that tag — so the rule is stated once in the Tags tab rather than listed here.": "Méta-tags séparés par des virgules. Tout tag que la bibliothèque marque ainsi désactive le miroir pour les images le portant — la règle est donc énoncée une fois dans l'onglet Tags plutôt que listée ici.",
  "Always include tags marked": "Toujours inclure les tags marqués",
  "Comma-separated META tags. Any tag the library marks with one of these is never dropped by the random pick — again, only where the image actually has that tag.": "Méta-tags séparés par des virgules. Tout tag que la bibliothèque marque ainsi n'est jamais écarté par le tirage aléatoire — là encore, seulement là où l'image porte réellement ce tag.",
  "Exclude tags marked": "Exclure les tags marqués",
  "Comma-separated META tags. Any tag the library marks with one of these is stripped from prompts.": "Méta-tags séparés par des virgules. Tout tag que la bibliothèque marque ainsi est retiré des prompts.",
  "Remove tags marked": "Retirer les tags marqués",
  "Comma-separated META tags. Any tag the library marks with one of these comes off this sample.": "Méta-tags séparés par des virgules. Tout tag que la bibliothèque marque ainsi est retiré de cet échantillon.",
  "Only pictures whose tags are marked": "Seulement les images dont les tags sont marqués",
  "Comma-separated META tags — the same rule as the line above, said once in the library rather than tag by tag here.": "Méta-tags séparés par des virgules — la même règle que la ligne au-dessus, dite une fois dans la bibliothèque plutôt que tag par tag ici.",
  "Never pictures whose tags are marked": "Jamais les images dont les tags sont marqués",
  "Comma-separated META tags. Wins over both lines above.": "Méta-tags séparés par des virgules. L'emporte sur les deux lignes au-dessus.",
  "The same veto, said once in the library instead of tag by tag here. Any tag the Tags tab marks with one of these meta tags switches mirroring off for every picture carrying that tag.\n\nIt is worth the indirection for the reason a list of names goes stale: “text”, “logo”, “signature”, “left-handed”, a dozen characters with an eyepatch — the list in a job's settings is right the day it is written and wrong the next time somebody adds a tag it should have held. Marking the tags themselves puts the fact where the tag is, so a tag added later carries it into every run automatically, and a job written before that tag existed still does the right thing.\n\nBoth lists apply: a picture is left unmirrored if it carries a tag named above OR a tag marked here.":
    "Le même veto, dit une fois dans la bibliothèque au lieu d'être listé tag par tag ici. Tout tag que l'onglet Tags marque avec l'un de ces méta-tags désactive le miroir pour chaque image portant ce tag.\n\nLe détour vaut la peine pour la raison qui périme une liste de noms : « text », « logo », « signature », « left-handed », une douzaine de personnages avec un bandeau sur l'œil — la liste dans les réglages d'un job est juste le jour où elle est écrite et fausse dès que quelqu'un ajoute un tag qu'elle aurait dû contenir. Marquer les tags eux-mêmes place le fait là où le tag est : un tag ajouté plus tard l'emporte tout seul dans chaque exécution, et un job écrit avant l'existence de ce tag fait quand même ce qu'il faut.\n\nLes deux listes s'appliquent : une image reste non miroitée si elle porte un tag nommé au-dessus OU un tag marqué ici.",
  "The rule above, named by what the library says ABOUT a tag rather than by the tag. Any tag marked with one of these meta tags bypasses the random pick — again only where the image actually has it.\n\nA meta tag put on “watermark”, “signature” and “logo” once means every run treats them that way, including runs written before the third of them existed. The two lists are unioned, so naming a tag here and above is simply the same instruction twice.":
    "La règle ci-dessus, nommée par ce que la bibliothèque dit À PROPOS d'un tag plutôt que par le tag. Tout tag marqué de l'un de ces méta-tags contourne le tirage aléatoire — là encore, seulement là où l'image le porte réellement.\n\nUn méta-tag posé une fois sur « watermark », « signature » et « logo » signifie que chaque exécution les traite ainsi, y compris celles écrites avant l'existence du troisième. Les deux listes sont réunies : nommer un tag ici et au-dessus revient simplement à donner deux fois la même instruction.",
  "The same, one level up: any tag the library marks with one of these meta tags is stripped from every prompt.\n\nThis is the one to reach for when the exclusions are a KIND of tag rather than a list of them. Quality ratings, scan notes, the booru's own housekeeping words — mark them “noprompt” in the Tags tab and every run drops them, instead of every job carrying a list that has to grow with the vocabulary.\n\nIt is not the same as a skipped tag GROUP below. This one is about the tag wherever it appears; that one is about a grouping on one item, and a tag placed in an excluded group and also somewhere else survives it.":
    "La même chose un niveau plus haut : tout tag que la bibliothèque marque avec l'un de ces méta-tags est retiré de chaque prompt.\n\nC'est vers cela qu'il faut se tourner quand les exclusions sont un GENRE de tag plutôt qu'une liste de tags. Notes de qualité, remarques de scan, le vocabulaire interne d'un booru — marquez-les « noprompt » dans l'onglet Tags et chaque exécution les écarte, au lieu que chaque job traîne une liste qui doit grandir avec le vocabulaire.\n\nCe n'est pas la même chose qu'un GROUPE de tags ignoré plus bas. Ici il s'agit du tag partout où il apparaît ; là, d'un regroupement sur un élément, et un tag placé dans un groupe exclu et aussi ailleurs y survit.",
  "The list above, named by what the library says about a tag. Any tag marked with one of these meta tags comes off this sample.\n\nWhat it is for is that the claims a degraded copy no longer supports are a CATEGORY, not a list: 'masterpiece', 'absurdres', 'high quality', 'official art' and whatever the next dump adds are all \"a claim about the picture's quality\". Marking them once means every variant of every job drops them, and the same mark can then say something different per method — a 'resolution_claim' mark belongs on a resize variant's list, a 'fidelity_claim' on a JPEG one.":
    "La liste ci-dessus, nommée par ce que la bibliothèque dit d'un tag. Tout tag marqué de l'un de ces méta-tags est retiré de cet échantillon.\n\nÀ quoi cela sert : les affirmations qu'une copie dégradée ne soutient plus sont une CATÉGORIE, pas une liste. « masterpiece », « absurdres », « high quality », « official art » et ce que le prochain dump ajoutera sont toutes « une affirmation sur la qualité de l'image ». Les marquer une fois fait que chaque variante de chaque job les écarte, et la même marque peut alors dire autre chose selon la méthode : une marque « resolution_claim » a sa place dans la liste d'une variante de redimensionnement, un « fidelity_claim » dans celle d'une variante JPEG.",
  "The line above by mark rather than by name: a picture is degraded only if it carries a tag the library marks this way.\n\nChecked against the picture's effective tags, so a tag it only carries by implication counts too. With both lists empty, every picture is fair game.":
    "La ligne ci-dessus par marque plutôt que par nom : une image n'est dégradée que si elle porte un tag que la bibliothèque marque ainsi.\n\nLa vérification se fait sur les tags effectifs de l'image : un tag qu'elle ne porte que par implication compte aussi. Les deux listes laissées vides, toute image est éligible.",
  "The veto by mark, and it wins over both lines above exactly as the named list does.\n\nThe pair is what makes a degrading run safe on a mixed library: mark the pictures that are already poor — a 'low_quality' or 'rescan' mark on the tags that say so — and no variant can ever degrade one of them further, however broadly the \"only pictures\" side is drawn.":
    "Le veto par marque, et il l'emporte sur les deux lignes au-dessus exactement comme le fait la liste par nom.\n\nC'est la paire qui rend une exécution dégradante sûre sur une bibliothèque mêlée : marquez les images déjà mauvaises — un « low_quality » ou « rescan » sur les tags qui le disent — et aucune variante ne pourra jamais en dégrader une davantage, si large que soit le côté « seulement les images ».",
  "Never flip images tagged": "Ne jamais refléter les images taguées",
  "Comma-separated tags that switch mirroring off for the images carrying them, e.g. 'text'. Everything else still flips.": "Tags séparés par des virgules qui coupent le miroir pour les images qui les portent, p. ex. 'text'. Tout le reste se reflète toujours.",
  "Use alpha as a loss mask": "Utiliser l'alpha comme masque de perte",
  "For cut-out images (transparent background): train on the visible pixels and largely ignore the rest. Images without transparency are unaffected.": "Pour les images détourées (fond transparent) : entraîner sur les pixels visibles et ignorer largement le reste. Les images sans transparence ne sont pas concernées.",
  "Background weight": "Poids de l'arrière-plan",
  "Build prompts from": "Construire les prompts depuis",
  "What each training prompt is made of: the item's caption text, its tags, caption followed by tags, or nothing but the trigger word.": "De quoi est faite chaque invite d’entraînement : la légende de l’élément, ses tags, la légende suivie des tags, ou rien d’autre que le mot déclencheur.",
  "Prepended to every prompt. Use a rare token (e.g. 'ohwx style') you'll later type to invoke the trained concept.": "Préfixé à chaque prompt. Utilisez un jeton rare (p. ex. 'ohwx style') que vous taperez plus tard pour invoquer le concept entraîné.",
  "Each image trains as the RESULT of one of its instructions, with that instruction's reference images as the input. Items carrying no instruction are left out of the run, and tag selection does not apply.": "Chaque image s'entraîne comme le RÉSULTAT d'une de ses instructions, avec les images de référence de cette instruction en entrée. Les éléments sans instruction sont laissés hors du run, et la sélection de tags ne s'applique pas.",
  "Tag selection": "Sélection de tags",
  "Tags are re-picked and re-shuffled fresh every time an image is visited.": "Les tags sont retirés et remélangés à neuf à chaque visite d'une image.",
  "Comma-separated tags stripped from prompts (e.g. quality tags or the concept itself when using a trigger word).": "Tags séparés par des virgules retirés des prompts (p. ex. tags de qualité ou le concept lui-même quand un mot déclencheur est utilisé).",
  "no limit": "sans limite",
  "Lower bound of the random pick. Both limits empty = use all tags.": "Borne basse du tirage aléatoire. Les deux limites vides = tous les tags.",
  "Upper bound of the random pick. Picking a random subset each visit teaches tags independently instead of as a fixed clump.": "Borne haute du tirage. Tirer un sous-ensemble aléatoire à chaque visite enseigne les tags indépendamment plutôt qu'en bloc figé.",
  "Whether a tag's rarity is measured within the selected training images or across the whole library.": "Si la rareté d'un tag se mesure dans les images d'entraînement sélectionnées ou dans toute la bibliothèque.",
  "Skip partially matching tags": "Ignorer les tags en correspondance partielle",
  "Standard practice: prevents the model from binding concepts to a fixed tag position.": "Pratique standard : empêche le modèle de lier les concepts à une position fixe du tag.",
  "Underscores to spaces": "Tirets bas en espaces",
  "Tag separator": "Séparateur de tags",
  "Joins the prompt parts; comma + space is the standard.": "Joint les parties du prompt ; virgule + espace est le standard.",
  "Generate preview images with the in-training model to watch progress in the job's timeline.": "Génère des aperçus avec le modèle en cours d'entraînement pour suivre le progrès dans la chronologie du job.",
  "Generate test samples": "Générer des échantillons de test",
  "Sample seed": "Graine d'échantillon",
  "Fixed per prompt so consecutive samples differ only by training progress.": "Fixe par prompt : des échantillons consécutifs ne diffèrent que par le progrès de l'entraînement.",
  "Test prompts": "Prompts de test",
  "negative prompt (optional)": "prompt négatif (facultatif)",
  "Use the shared size for this prompt": "Utiliser la taille partagée pour ce prompt",
  "Give this prompt its own size": "Donner à ce prompt sa propre taille",
  "Remove this prompt": "Retirer ce prompt",
  "Add prompt": "Ajouter un prompt",
  "Remove every prompt from this job": "Retirer tous les prompts de ce job",
  "Remove all": "Tout retirer",
  "Save the current prompts, or load a saved set": "Enregistrer les prompts actuels, ou charger un jeu enregistré",
  "Write a prompt first": "Écrivez d'abord un prompt",
  "Save current prompts": "Enregistrer les prompts actuels",
  "Set name": "Nom du jeu",
  "Load this set into the job": "Charger ce jeu dans le job",
  "Delete this set": "Supprimer ce jeu",
  "train from scratch": "entraîner de zéro",
  "Finished result": "Résultat final",
  "Intermediate checkpoint": "Checkpoint intermédiaire",
  "Continues": "Poursuit",
  "Train on video frames": "Entraîner sur des images de vidéos",
  "Off, a video the queries match is skipped. On, its frames are extracted while the dataset is built, trained on as images, and deleted with the run.": "Désactivé : une vidéo correspondant aux requêtes est ignorée. Activé : ses images sont extraites à la construction du jeu de données, entraînées comme des images, et supprimées avec le run.",
  "One frame every": "Une image toutes les",
  "Interval unit": "Unité d'intervalle",
  "Seconds follows the clock whatever the frame rate; frames counts the file's own frames.": "Les secondes suivent l'horloge quelle que soit la cadence ; les images comptent celles du fichier.",
  "Drop repeated frames": "Écarter les images répétées",
  "A shot held for five seconds is one picture, not five. Each kept frame is compared with the ones already kept from the same video.": "Un plan tenu cinq secondes est une image, pas cinq. Chaque image gardée est comparée à celles déjà gardées de la même vidéo.",
  "Label each block with": "Étiqueter chaque bloc avec",
  "The subjects it is about": "Les sujets dont il parle",
  "The tag group's name": "Le nom du groupe de tags",
  "Between groups": "Entre les groupes",
  "Group tags by tag group": "Grouper les tags par groupe de tags",
  "Lay the picked tags out one block per tag group instead of one flat list, so what belongs to the same thing in the picture stays together.": "Dispose les tags tirés en un bloc par groupe de tags plutôt qu'en liste plate, pour que ce qui appartient à la même chose de l'image reste ensemble.",
  "Put between blocks. A newline by default, which is what makes them read as separate statements.": "Placé entre les blocs. Un saut de ligne par défaut — c'est lui qui les fait lire comme des énoncés séparés.",
  "Includes {n} models you added.": { one: "Comprend {n} modèle que vous avez ajouté.", other: "Comprend {n} modèles que vous avez ajoutés." },
  // The job list's selection bar.
  "Remove {n} training jobs? Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone.":
    "Supprimer {n} tâches d'entraînement ? Leurs points de contrôle, échantillons et résultats entraînés sont supprimés avec elles, et c'est irréversible. Sauf ce qui est verrouillé, qui est conservé dans la liste des LoRA.",
  "Remove the selected jobs — a running job is left alone":
    "Supprimer les tâches sélectionnées — une tâche en cours est laissée telle quelle",
  "Remove the selected jobs, with their checkpoints and samples":
    "Supprimer les tâches sélectionnées, avec leurs points de contrôle et échantillons",
  // The Models page: adding a model, and removing one.
  "Remove “{name}” from the model list?":
    "Retirer « {name} » de la liste des modèles ?",
  "Delete the downloaded weights as well? They can be downloaded again later.":
    "Supprimer aussi les poids téléchargés ? Ils peuvent être retéléchargés plus tard.",
  "Which model these weights are a version of — it decides the engine, the hyperparameters and the memory profile":
    "De quel modèle ces poids sont une version — cela décide du moteur, des hyperparamètres et du profil mémoire",
  "owner/repo, or a path on this machine":
    "owner/repo, ou un chemin sur cette machine",
  "A Hugging Face repository, or a diffusers folder or .safetensors file on this machine — which one it is is read off what you type.":
    "Un dépôt Hugging Face, ou un dossier diffusers ou un fichier .safetensors sur cette machine — lequel des deux est déduit de ce que vous saisissez.",
  "Read as a path on this machine":
    "Lu comme un chemin sur cette machine",
  "Read as a Hugging Face repository":
    "Lu comme un dépôt Hugging Face",
  "Left unnamed, the model is listed under its repository or path":
    "Sans nom, le modèle est listé sous son dépôt ou son chemin",
  // The Models page's LoRA lists, grouped by architecture.
  "No LoRAs yet — add a file above, or finish a training job.":
    "Pas encore de LoRA — ajoutez un fichier ci-dessus ou terminez un entraînement.",
  "These work on any model of this architecture. Each row says which one it was trained for.":
    "Ils fonctionnent avec tout modèle de cette architecture. Chaque ligne indique celui pour lequel il a été entraîné.",
  // The Evaluate tab: the LoRA rows, and the results grid.
  "Strength":
    "Intensité",
  "no image":
    "pas d'image",
  "Weights": "Poids",
  "File": "Fichier",
  "Trained for": "Entraîné pour",
  "defaults to the file name": "par défaut, le nom du fichier",
  "Waiting…": "En attente…",
  "Another download is running": "Un autre téléchargement est en cours",
  "macOS keeps GPU temperature and power for root only. To see them here, allow this one command without a password, then press Try again:":
    "macOS réserve la température et la puissance du GPU à root. Pour les voir ici, autorisez cette seule commande sans mot de passe, puis appuyez sur « Réessayer » :",
  "Check again — no restart needed once the rule is in":
    "Vérifier à nouveau — une fois la règle en place, aucun redémarrage n’est nécessaire",
  "Copied": "Copié",
  "Press ⌘C to copy it": "Appuyez sur ⌘C pour la copier",
  "Write tags as an alias": "Écrire les tags sous un alias",
  "Chance of writing a picked tag as one of its aliases instead of its own name, rolled per tag every time an image is visited.":
    "Probabilité d'écrire un tag choisi sous l'un de ses alias plutôt que sous son propre nom, tirée par tag à chaque visite d'une image.",
  "Your library's aliases are the other words for one thing — “cat”, “kitty”, “feline”. Assigning any of them stores the canonical name, so every prompt says the same word and the model learns to answer to that word alone; at generation time the others do less, or nothing.\n\nWith this above 0, each picked tag is sometimes written as one of its aliases instead. The roll happens per tag per visit, so one image seen twice reads differently and the whole vocabulary is spread across the run rather than one alias being chosen per tag and then repeated.\n\nOnly the PROMPT changes. Tag matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all keep using the canonical name — so this cannot skew any of them. A tag with no aliases is always written as itself, and 0 is exactly what every run did before this setting existed.":
    "Les alias de votre bibliothèque sont les autres mots pour une même chose : « cat », « kitty », « feline ». En attribuer un enregistre le nom canonique, donc chaque prompt dit le même mot et le modèle apprend à ne répondre qu'à celui-là ; à la génération, les autres ne font pas grand-chose, voire rien.\n\nAu-dessus de 0, un tag choisi est parfois écrit sous l'un de ses alias. Le tirage a lieu par tag et par visite, si bien qu'une image vue deux fois se lit différemment et que tout le vocabulaire se répartit sur l'entraînement, au lieu de choisir un alias par tag une fois pour toutes.\n\nSeul le PROMPT change. La correspondance des tags, les listes toujours/exclure, l'équilibrage par fréquence, le poids de la perte et les cadres qu'un recadrage doit conserver continuent d'utiliser le nom canonique — cela ne peut donc rien fausser. Un tag sans alias est toujours écrit tel quel, et 0 correspond exactement à ce que faisait chaque entraînement avant cette option.",
  "Whether a tag's rarity is measured within the selected training images, across the whole library, or across the whole library plus what each tag has elsewhere.":
    "Si la rareté d'un tag se mesure au sein des images d'entraînement sélectionnées, sur toute la bibliothèque, ou sur toute la bibliothèque plus ce que chaque tag possède ailleurs.",
  "Rarity is relative to some population, and this picks which one.\n\n“Training data” counts only the images this job selected, so balancing works within the set you are actually training on — usually what you want. “Whole library” counts every item you own, which makes a tag that is common in your dataset but rare overall still count as rare. That is occasionally useful when the training set is a deliberate slice of a much larger, differently balanced collection.\n\n“Whole library + count offsets” adds each tag’s highest meta-tag count — the pictures it has somewhere this library is not, counted per site on the tag’s meta tags (“tumblr 50”, “twitter 100”), of which the largest single figure is used, never the sum, since the sites count overlapping pictures. Nowhere else in the app is that number added to a count, because a total including it would be a claim about somewhere else; for BALANCING it is often the honest one. A tag with four pictures here and forty thousand where they came from is not a rare word, and treating it as rare spends the run teaching the model something it already knows.":
    "La rareté est toujours relative à une population, et c'est elle que l'on choisit ici.\n\n« Données d'entraînement » ne compte que les images sélectionnées par ce job : l'équilibrage agit donc à l'intérieur de l'ensemble sur lequel vous entraînez réellement — le plus souvent ce qu'il faut. « Toute la bibliothèque » compte tout ce que vous possédez, si bien qu'un tag fréquent dans votre jeu de données mais rare globalement compte encore comme rare. C'est utile de temps à autre, quand le jeu d'entraînement est une tranche délibérée d'une collection bien plus vaste et autrement répartie.\n\n« Toute la bibliothèque + effectifs ailleurs » ajoute le plus haut compte par méta-tag de chaque tag : les images qu'il possède là où cette bibliothèque n'est pas, comptées par site sur ses méta-tags (« tumblr 50 », « twitter 100 ») ; c'est le plus grand chiffre isolé qui est retenu, jamais la somme, car les sites comptent des images qui se recoupent. Nulle part ailleurs dans l'app ce nombre n'est ajouté à un comptage, car un total qui l'inclurait serait une affirmation sur ailleurs ; pour l'ÉQUILIBRAGE, c'est souvent le nombre honnête. Un tag avec quatre images ici et quarante mille là d'où elles viennent n'est pas un mot rare, et le traiter comme tel dépense l'entraînement à enseigner au modèle ce qu'il sait déjà.",
  "Caption selection": "Sélection des légendes",
  "Instruction selection": "Sélection des instructions",
  "Start now — pauses the running job and puts this one first":
    "Démarrer maintenant : met en pause le job en cours et place celui-ci en tête",
  "Start now — puts this job first and starts the queue":
    "Démarrer maintenant : place ce job en tête et lance la file",
  "Save as duplicate":
    "Enregistrer comme copie",
  "Batch & seed": "Lot & graine",
  "Device": "Périphérique",
  "Precision & quantization": "Précision & quantification",
  "Memory savers": "Économies de mémoire",
  "Training images": "Images d'entraînement",
  "Length measured in":
    "Durée mesurée en",
  "Steps are a fixed amount of work; epochs are full passes over your images, so the run grows with the dataset.":
    "Les étapes sont une quantité de travail fixe ; les époques sont des passages complets sur vos images, l'entraînement grandit donc avec le jeu de données.",
  "A STEP is one batch pushed through the model and one update of the weights — a fixed amount of work whatever the dataset holds. An EPOCH is one pass over every training image, so the same number means a longer run on a bigger set and the model sees each picture the same number of times either way.\n\nEpochs are usually the easier thing to reason about: “each image about ten times” transfers between datasets, where “3000 steps” does not. The exact step count is worked out when the run starts, because only then is it known how many entries the dataset has — a film contributes its frames, a degraded copy is an extra sample, and an item can contribute one per caption.":
    "Une ÉTAPE, c'est un lot passé dans le modèle et une mise à jour des poids : une quantité de travail fixe, quel que soit le jeu de données. Une ÉPOQUE, c'est un passage sur chaque image d'entraînement ; le même nombre donne donc un entraînement plus long sur un jeu plus grand, et le modèle voit chaque image autant de fois dans les deux cas.\n\nLes époques sont en général plus faciles à raisonner : « chaque image une dizaine de fois » se transpose d'un jeu à l'autre, « 3000 étapes » non. Le nombre exact d'étapes est calculé au démarrage, car ce n'est qu'alors qu'on sait combien d'entrées contient le jeu de données — un film apporte ses images, une copie dégradée est un échantillon de plus, et un élément peut en apporter une par légende.",
  "Epochs":
    "Époques",
  "Full passes over the dataset. The exact step count is worked out when the run starts and shown in its log.":
    "Passages complets sur le jeu de données. Le nombre exact d'étapes est calculé au démarrage et affiché dans le journal.",
  "How many times the run works through every training image. Each pass visits every entry exactly once, in a fresh random order.\n\nWhat counts as an entry is the dataset after it has been built, not the number of pictures you selected: a video contributes one entry per kept frame, a degradation variant adds an extra sample beside the clean picture, and with “every caption” an item contributes one entry per caption. That is why the step count appears when the run starts rather than here.":
    "Combien de fois l'entraînement parcourt toutes les images. Chaque passage visite chaque entrée exactement une fois, dans un nouvel ordre aléatoire.\n\nCe qui compte comme entrée, c'est le jeu de données une fois construit, pas le nombre d'images sélectionnées : une vidéo apporte une entrée par image conservée, une variante de dégradation ajoute un échantillon à côté de l'image propre, et avec « chaque légende » un élément apporte une entrée par légende. C'est pourquoi le nombre d'étapes apparaît au démarrage et pas ici.",
  "Query weight":
    "Poids de la requête",
  "A weight buys":
    "Un poids achète",
  "Whether a heavier query's images are seen more often, or seen the same and counted for more.":
    "Si les images d'une requête plus lourde sont vues plus souvent, ou vues autant et comptent davantage.",
  "Both spend the same ratio; they differ in what they spend it on.\n\nSEEN MORE OFTEN is the classic behaviour: a weight-2 query's pictures get twice the visits, which means they take those visits from the rest — a fixed-length run spends more of itself on them and less on everything else.\n\nCOUNTED FOR MORE gives every picture the same number of visits and multiplies the weighted ones' effect on the weights instead. Nothing loses coverage; the emphasis comes out of the gradient rather than out of the other images' training time. It is the better default when the queries are different KINDS of picture rather than different amounts of importance.":
    "Les deux dépensent le même ratio ; elles diffèrent par ce sur quoi elles le dépensent.\n\nVUES PLUS SOUVENT est le comportement classique : les images d'une requête de poids 2 reçoivent deux fois plus de visites, et ces visites sont prises au reste — un entraînement de durée fixe consacre plus de lui-même à ces images et moins à toutes les autres.\n\nCOMPTENT DAVANTAGE donne à chaque image le même nombre de visites et multiplie à la place l'effet des images pondérées sur les poids. Rien ne perd en couverture ; l'accent vient du gradient plutôt que du temps d'entraînement des autres images. C'est le meilleur choix par défaut quand les requêtes décrivent des TYPES d'images différents plutôt que des degrés d'importance.",
  "Seen more often":
    "Vues plus souvent",
  "Counted for more":
    "Comptent davantage",
  "An item with several captions":
    "Un élément avec plusieurs légendes",
  "Whether every caption is used each pass, or one is drawn per visit.":
    "Si chaque légende est utilisée à chaque passage, ou si l'on en tire une par visite.",
  "Items often carry more than one caption — a short one and a long one, a translation, a machine draft somebody approved.\n\nONE AT RANDOM gives the item a single visit each pass and draws a different caption each time, so the whole set is seen across a long run and an item counts once however many ways it has been described.\n\nEVERY CAPTION gives it one visit per caption, so all of them are used every pass — and an item with ten is therefore seen ten times, which is usually an accident of tooling rather than a claim that the picture matters ten times as much.\n\nEVERY CAPTION, SHARED is that with the accident removed: each caption still gets its visit, and together they carry one item's worth of gradient.":
    "Les éléments portent souvent plus d'une légende : une courte et une longue, une traduction, un brouillon automatique validé par quelqu'un.\n\nUNE AU HASARD donne à l'élément une seule visite par passage et tire une légende différente à chaque fois ; sur un entraînement long, toutes sont vues, et l'élément compte une fois quel que soit le nombre de façons dont il a été décrit.\n\nCHAQUE LÉGENDE lui donne une visite par légende, donc toutes servent à chaque passage — et un élément qui en a dix est alors vu dix fois, ce qui relève en général d'un hasard d'outillage plutôt que d'une intention de lui donner dix fois plus de poids.\n\nCHAQUE LÉGENDE, PARTAGÉE, c'est la même chose sans ce hasard : chaque légende garde sa visite, et ensemble elles portent le gradient d'un seul élément.",
  "One at random each visit":
    "Une au hasard à chaque visite",
  "Every caption, once each":
    "Chaque légende, une fois",
  "Every caption, sharing one item's weight":
    "Chaque légende, partageant le poids d'un élément",
  "Unsupported":
    "Non pris en charge",
  "not available on Apple silicon":
    "indisponible sur Apple silicon",
  "not used on Apple silicon, where the run trains in fp32":
    "non utilisé sur Apple silicon, où l'entraînement se fait en fp32",
  "a full finetune trains the base weights, so there is nothing to quantize":
    "un finetuning complet entraîne les poids de base, il n'y a donc rien à quantifier",
  "only offered for LoRA training":
    "proposé uniquement pour l'entraînement LoRA",
  "too large to finetune on any GPU this app has constants for":
    "trop grand pour un finetuning sur toutes les cartes dont cette app a les constantes",
  "Another picture": "Une autre image",
  "{n} jobs selected. One at a time shows its progress, samples and settings.":
    "{n} tâches sélectionnées. La progression, les images de test et les réglages s'affichent une à la fois.",
  "original":
    "original",
  "Show this at full size":
    "Afficher en taille réelle",
  "Each snapshot is about {size}.":
    "Chaque instantané fait environ {size}.",
  "Cadence measured in":
    "Cadence mesurée en",
  "How often a snapshot is written: after a fixed number of steps, or after a number of full passes over the dataset.":
    "À quelle fréquence un instantané est écrit : après un nombre fixe d'étapes, ou après un nombre de passages complets sur le jeu de données.",
  "How often a round of samples is rendered: after a fixed number of steps, or after a number of full passes over the dataset.": "À quelle fréquence une série d'échantillons est rendue : après un nombre fixe d'étapes, ou après un nombre de passages complets sur le jeu de données.",
  "Rendered after this many full passes. The equivalent step count appears in the job's log when the run starts.": "Rendue après ce nombre de passages complets. Le nombre d'étapes équivalent apparaît dans le journal du job au démarrage.",
  "A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 250 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both. It is the choice the checkpoint cadence and the run’s own length already offer, and setting all three the same way is what makes a sample, its checkpoint and a pass over your pictures line up in the timeline.\n\nHow many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has — a film’s frames, a degraded copy and an item contributing one entry per caption all count.": "Une étape est une quantité de travail fixe et une époque est un passage sur chaque image d'entraînement, si bien que les deux cadences divergent à mesure qu'un jeu de données grandit — « toutes les 250 étapes » représente l'essentiel d'un petit entraînement et une fraction d'un grand, tandis que « chaque époque » veut dire la même chose dans les deux. C'est le choix que la cadence des points de contrôle et la durée de l'entraînement proposent déjà, et régler les trois de la même façon est ce qui aligne un échantillon, son point de contrôle et un passage sur vos images dans la chronologie.\n\nLe nombre d'étapes que prend une époque est calculé au démarrage, car seul le jeu de données construit sait combien d'entrées il contient — les images d'un film, une copie dégradée et un élément apportant une entrée par légende comptent toutes.",
  "Rendered after this many full passes over the dataset. The equivalent step count is printed in the job’s log when the run starts, so a glance there says what the cadence came out as for this particular dataset.\n\nSampling interrupts training while it renders, so on a large dataset one round per epoch may be further apart than you want and on a tiny one it may be a pause every few seconds — the log’s step figure is what tells you which.": "Rendue après ce nombre de passages complets sur le jeu de données. Le nombre d'étapes équivalent est écrit dans le journal du job au démarrage : un coup d'œil suffit pour savoir ce que la cadence donne sur ce jeu de données précis.\n\nL'échantillonnage interrompt l'entraînement pendant le rendu : sur un grand jeu de données, une série par époque peut être plus espacée que souhaité, et sur un tout petit, ce peut être une pause toutes les quelques secondes — le nombre d'étapes du journal vous dit lequel.",
  "Rendered every this many steps, whatever the dataset is. 250–500 is a good rhythm: often enough to catch a concept going wrong, rare enough that the pauses do not dominate the run.": "Rendue toutes les N étapes, quel que soit le jeu de données. 250–500 est un bon rythme : assez fréquent pour repérer un concept qui dérape, assez rare pour que les pauses ne dominent pas l'entraînement.",
  "A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 500 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both.\n\nHow many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has. That is also why the disk estimate below can only be given when the run's length is set in epochs too.":
    "Une étape est une quantité de travail fixe et une époque un passage sur chaque image d'entraînement : les deux cadences divergent donc dès qu'un jeu de données grandit — « toutes les 500 étapes » représente presque tout un petit entraînement et une fraction d'un grand, là où « chaque époque » veut dire la même chose dans les deux.\n\nLe nombre d'étapes d'une époque est calculé au démarrage, car seul le jeu de données construit sait combien d'entrées il contient. C'est pourquoi l'estimation d'espace disque ci-dessous n'est possible que si la durée est elle aussi exprimée en époques.",
  "epochs":
    "époques",
  "Written after this many full passes. The equivalent step count appears in the job's log when the run starts.":
    "Écrit après ce nombre de passages complets. L'équivalent en étapes apparaît dans le journal de la tâche au démarrage.",
  "Every snapshot is a usable model file: the Evaluate tab can generate with any of them, so you can compare one pass against another and keep whichever looks best.\n\nCounted in passes, the cadence follows the dataset: add pictures and the snapshots stay one-per-pass rather than quietly becoming more frequent than a pass. The trainer prints what it works out to in steps, so the timeline and the log still agree about what a checkpoint is.":
    "Chaque instantané est un fichier de modèle utilisable : l'onglet Evaluate peut générer avec n'importe lequel, vous pouvez donc comparer un passage à un autre et garder le meilleur.\n\nComptée en passages, la cadence suit le jeu de données : en ajoutant des images, les instantanés restent à un par passage au lieu de devenir discrètement plus fréquents qu'un passage. L'entraîneur écrit dans le journal ce que cela donne en étapes, pour que la chronologie et le journal restent d'accord sur ce qu'est un checkpoint.",
  "Never upscale":
    "Ne jamais agrandir",
  "Leave out any image smaller than the bucket it would be fitted to, rather than enlarging it.":
    "Écarte les images plus petites que le bucket où elles iraient, au lieu de les agrandir.",
  "Loads the frozen base weights in 8-bit or 4-bit so big models fit in little memory (QLoRA). 8-bit (int8) runs on Apple silicon too; fp8 and 4-bit need an NVIDIA GPU.":
    "Charge les poids de base gelés en 8 ou 4 bits pour que les grands modèles tiennent dans peu de mémoire (QLoRA). Le 8 bits (int8) fonctionne aussi sur Apple Silicon ; fp8 et 4 bits exigent un GPU NVIDIA.",
  "Quantize the text encoder":
    "Quantifier l’encodeur de texte",
  "Applies the same scheme to the text encoder, the other big frozen model. On the largest models it is worth several GB.":
    "Applique le même schéma à l’encodeur de texte, l’autre gros modèle gelé. Sur les plus grands modèles, cela représente plusieurs Go.",
  "cannot be combined with training the text encoder":
    "incompatible avec l’entraînement de l’encodeur de texte",

  // ---- adapter type, layer targeting, optimizers, noise levels,
  // weight averaging and regularization ----
  "Adapter":
    "Adaptateur",
  "Adapter type":
    "Type d'adaptateur",
  "Kronecker factor":
    "Facteur de Kronecker",
  "How each weight is split into LoKr's two parts. Leave empty unless you have a reason not to.":
    "Comment chaque poids est découpé en les deux parties de LoKr. Laisse vide sauf raison contraire.",
  "Only these layers":
    "Uniquement ces couches",
  "all of them":
    "toutes",
  "Comma-separated parts of a layer's name. Leave empty to train every attention layer — which is what you want unless you have a reason not to.":
    "Fragments du nom d'une couche, séparés par des virgules. Laisse vide pour entraîner toutes les couches d'attention — ce que tu veux, sauf raison contraire.",
  "By default the adapter attaches to every attention layer in the image model. This narrows that to the layers whose name contains one of the words you list.\n\nWhy you might: different parts of the network do different jobs. The later ones carry more of what a picture LOOKS like, and the earlier ones more of how it is put together — so training only part of the network is how a style is learned without also disturbing composition and anatomy. It also makes the adapter smaller and each step faster, since there is less to train.\n\nThe names come from the model itself, and the chevron at the end of the field lists the ones worth knowing for the architecture you picked — clicking one adds or removes it, and a tick marks the ones the field already holds. For SD and SDXL they are down_blocks, mid_block and up_blocks, plus attn1 (the picture attending to itself) and attn2 (where the prompt gets in); for the newer transformer models, transformer_blocks and single_transformer_blocks. The field stays free text, because you can be as coarse or as fine as you like: 'up_blocks' takes a whole third of a UNet, 'transformer_blocks.12' takes one block, 'to_k' takes one kind of projection everywhere. The job's page draws a map of the whole model once a run has started.\n\nIf what you type matches no layers at all, the run stops and says so rather than training an adapter attached to nothing — which would otherwise look exactly like a normal run that learned nothing.":
    "Par défaut l'adaptateur s'attache à toutes les couches d'attention du modèle d'image. Ceci restreint aux couches dont le nom contient l'un des mots que tu listes.\n\nPourquoi : différentes parties du réseau font des travaux différents. Les dernières portent davantage l'APPARENCE d'une image, les premières davantage la façon dont elle est construite — n'entraîner qu'une partie du réseau est donc la manière d'apprendre un style sans perturber aussi la composition et l'anatomie. Cela rend également l'adaptateur plus petit et chaque pas plus rapide, puisqu'il y a moins à entraîner.\n\nLes noms viennent du modèle lui-même, et le chevron au bout du champ liste celles qui comptent pour l'architecture choisie — un clic en ajoute une ou l'enlève, et une coche marque celles que le champ contient déjà. Pour SD et SDXL ce sont down_blocks, mid_block et up_blocks, plus attn1 (l'image qui se regarde elle-même) et attn2 (par où le prompt entre) ; pour les modèles transformer plus récents, transformer_blocks et single_transformer_blocks. Le champ reste du texte libre, car vous pouvez être aussi grossier ou aussi fin que vous voulez : « up_blocks » prend tout un tiers d'un UNet, « transformer_blocks.12 » un seul bloc, « to_k » un type de projection partout. La page de la tâche dessine une carte du modèle entier dès qu'une exécution a démarré.\n\nSi ce que tu saisis ne correspond à aucune couche, l'exécution s'arrête et le dit plutôt que d'entraîner un adaptateur attaché à rien — ce qui ressemblerait sinon exactement à une exécution normale n'ayant rien appris.",
  "Except these layers":
    "Sauf ces couches",
  "Comma-separated parts of a layer's name to leave out. Applied after the field above, and it wins.":
    "Fragments du nom d'une couche, séparés par des virgules, à laisser de côté. Appliqué après le champ ci-dessus, et il l'emporte.",
  "The same kind of list, subtracting instead of selecting. A layer whose name matches anything here is left out even if the field above selected it.\n\nIt is the easier way to say 'everything except' — excluding 'down_blocks' is shorter and stays correct if the model gains a block, where listing every other block by hand does not.":
    "Le même genre de liste, mais qui soustrait au lieu de sélectionner. Une couche dont le nom correspond à quoi que ce soit ici est écartée, même si le champ ci-dessus l'avait sélectionnée.\n\nC'est la façon simple de dire « tout sauf » : exclure « down_blocks » est plus court et reste juste si le modèle gagne un bloc, ce que n'obtient pas une énumération manuelle de tous les autres blocs.",
  "Output size: a small fraction of a LoRA of the same rank — usually under a tenth.":
    "Taille du résultat : une petite fraction d'un LoRA de même rang — généralement moins d'un dixième.",
  "Learning rate multiplier":
    "Multiplicateur du taux d'apprentissage",
  "Prodigy works the rate out for itself; this scales what it finds. 1 leaves it alone — lower it if the run overshoots, raise it if it never gets going.":
    "Prodigy détermine le taux tout seul ; ceci met à l'échelle ce qu'il trouve. 1 le laisse tel quel — baisse-le si l'exécution dépasse la cible, augmente-le si elle ne démarre jamais.",
  "The Prodigy optimizer measures how far the weights have moved from where they started and derives a learning rate from that, so the rate is not something you set here — it comes out of the run.\n\nWhat this field does is scale the answer. 1 accepts it as found and is what you want almost always. Below 1 is a brake, worth reaching for if the run overshoots and samples come out burnt; above 1 pushes harder, which is occasionally useful on a very small dataset.\n\nProdigy needs a few hundred steps to work its estimate up from nearly nothing, so early samples in a Prodigy run look untrained even when everything is fine. Judge it from about a fifth of the way in, not from the first sample round.":
    "L'optimiseur Prodigy mesure de combien les poids se sont éloignés de leur point de départ et en déduit un taux d'apprentissage : le taux ne se règle donc pas ici, il sort de l'exécution elle-même.\n\nCe champ ne fait que mettre cette réponse à l'échelle. 1 l'accepte telle quelle et c'est ce que tu veux presque toujours. En dessous de 1 c'est un frein, utile si l'exécution dépasse la cible et que les échantillons sortent cramés ; au-dessus de 1 cela pousse plus fort, ce qui sert parfois sur un très petit jeu de données.\n\nProdigy a besoin de quelques centaines de pas pour faire monter son estimation depuis presque rien : les premiers échantillons d'une exécution Prodigy paraissent donc non entraînés même quand tout va bien. Juge-la à partir d'environ un cinquième du parcours, pas à la première série d'échantillons.",
  "How far the weights move on every update. It is the single most sensitive setting here.\n\nToo high and training diverges: samples turn into over-saturated, high-contrast mush ('deep fried'), often within a few hundred steps. Too low and nothing visibly changes no matter how long you wait. Typical values: 1e-4 for a LoRA, 1e-5 or lower for a full finetune (which touches every weight and needs far gentler updates).\n\nLearning rate and total steps trade off against each other — halving the rate roughly doubles the steps needed. If early samples look burnt, halve it; if they look identical to the baseline after a third of the run, double it.\n\nIf finding this number is the part you would rather not do, the Prodigy optimizer (Memory & speed) works it out for itself.":
    "De combien les poids bougent à chaque mise à jour. C'est le réglage le plus sensible d'ici.\n\nTrop élevé et l'entraînement diverge : les échantillons deviennent une bouillie sursaturée et surcontrastée (« deep fried »), souvent en quelques centaines de pas. Trop bas et rien ne change visiblement, quelle que soit l'attente. Valeurs typiques : 1e-4 pour un LoRA, 1e-5 ou moins pour un finetuning complet (qui touche chaque poids et demande des mises à jour bien plus douces).\n\nLe taux d'apprentissage et le nombre total de pas se compensent : diviser le taux par deux double à peu près les pas nécessaires. Si les premiers échantillons semblent cramés, divise-le par deux ; s'ils restent identiques au point de départ après un tiers de l'exécution, double-le.\n\nSi chercher ce nombre est justement ce que tu préférerais éviter, l'optimiseur Prodigy (Mémoire et vitesse) le détermine tout seul.",
  "Noise levels":
    "Niveaux de bruit",
  "Train on":
    "Entraîner sur",
  "Which stage of denoising to spend the run on. High noise decides a picture's layout, low noise its detail — so this decides what the training is mostly about.":
    "À quelle étape du débruitage consacrer l'exécution. Un bruit élevé décide de la mise en place d'une image, un bruit faible de ses détails — ceci décide donc de ce sur quoi porte surtout l'entraînement.",
  "Every training step takes a picture, adds some amount of noise to it, and asks the model to undo that. How much noise is picked fresh each time — and the two extremes teach completely different things.\n\nAt HIGH noise there is barely a picture left, so all the model can learn is layout: what is where, how big, the overall shape and colour. At LOW noise the composition is already settled and what is left to learn is detail and texture — edges, surfaces, small features.\n\nSo where a run spends its steps decides what it mostly teaches. A style is largely texture; a character's proportions are largely layout.\n\n'The model's own' is what this model family has always done here, and is the right answer unless you have a specific reason: the older models spread their steps evenly, and the newer ones concentrate on the middle, which is what their published recipes do and part of why they train efficiently. 'Evenly' spreads across the whole range. 'Bell curve' is the newer models' behaviour made adjustable, so you can lean it towards layout or towards detail. 'Cosine' leans towards higher noise without abandoning the low end.\n\nChanging this does not make a run better or worse in general — it moves what the run is good at.":
    "Chaque pas d'entraînement prend une image, y ajoute une certaine quantité de bruit et demande au modèle de le défaire. La quantité de bruit est retirée au sort à chaque fois — et les deux extrêmes enseignent des choses complètement différentes.\n\nÀ bruit ÉLEVÉ il ne reste presque plus d'image : tout ce que le modèle peut apprendre est la mise en place — ce qui est où, à quelle taille, la forme et la couleur d'ensemble. À bruit FAIBLE la composition est déjà fixée et ce qui reste à apprendre est le détail et la texture — bords, surfaces, petits éléments.\n\nLà où une exécution dépense ses pas décide donc de ce qu'elle enseigne surtout. Un style est en grande partie de la texture ; les proportions d'un personnage sont en grande partie de la mise en place.\n\n« Celui du modèle » est ce que cette famille de modèles a toujours fait ici, et c'est la bonne réponse sauf raison précise : les modèles anciens répartissent leurs pas uniformément et les récents se concentrent sur le milieu, ce que font leurs recettes publiées et une partie de la raison pour laquelle ils s'entraînent efficacement. « Uniformément » répartit sur toute la plage. « Courbe en cloche » est le comportement des modèles récents rendu réglable, pour l'incliner vers la mise en place ou vers le détail. « Cosinus » penche vers le bruit élevé sans abandonner le bas de la plage.\n\nChanger ceci ne rend pas une exécution meilleure ou pire en général — cela déplace ce en quoi elle est bonne.",
  "The model's own (recommended)":
    "Celui du modèle (recommandé)",
  "Evenly across all levels":
    "Uniformément sur tous les niveaux",
  "A bell curve I can aim":
    "Une courbe en cloche que je vise",
  "Leaning towards layout":
    "Penché vers la mise en place",
  "Aim at":
    "Viser",
  "0 is the middle. Positive leans towards layout and composition, negative towards detail and texture. ±1 is already a strong lean.":
    "0 est le milieu. En positif cela penche vers la mise en place et la composition, en négatif vers le détail et la texture. ±1 est déjà une forte inclinaison.",
  "Where the centre of the bell curve sits along the noise range.\n\n0 puts it in the middle, which is what the newer models do by default and a good place to stay. Move it positive and the run spends more of itself at high noise, learning layout and composition — useful when what you are teaching is a shape or an arrangement. Move it negative and it spends more at low noise, learning detail and texture — useful for a style, a medium, a surface quality.\n\n±0.5 is a noticeable lean and ±1 is a strong one. Beyond ±2 the run largely stops seeing one end of the range at all.":
    "Où se place le centre de la courbe en cloche sur la plage de bruit.\n\n0 le met au milieu, ce que font les modèles récents par défaut et un bon endroit où rester. Déplace-le en positif et l'exécution passe davantage de temps à bruit élevé, apprenant la mise en place et la composition — utile quand ce que tu enseignes est une forme ou une disposition. Déplace-le en négatif et elle passe plus de temps à bruit faible, apprenant le détail et la texture — utile pour un style, un médium, une qualité de surface.\n\n±0,5 est une inclinaison perceptible et ±1 une forte. Au-delà de ±2 l'exécution cesse pratiquement de voir l'une des extrémités de la plage.",
  "Spread":
    "Étalement",
  "How wide the curve is. 1 is the default; smaller concentrates the run on a narrow band around the aim, larger reaches both extremes.":
    "La largeur de la courbe. 1 est la valeur par défaut ; plus petit concentre l'exécution sur une bande étroite autour de la visée, plus grand atteint les deux extrêmes.",
  "The width of the bell curve.\n\n1 is the standard setting. Smaller values concentrate the run on a narrow band around wherever you have aimed it, which sharpens what it teaches at the cost of everything else. Larger values spread it out and reach both extremes more often, which is closer to training evenly.\n\nIf you are unsure, leave it at 1 and move the aim instead — the aim is the setting that changes what the run learns, and this one changes how single-minded it is about it.":
    "La largeur de la courbe en cloche.\n\n1 est le réglage standard. Des valeurs plus petites concentrent l'exécution sur une bande étroite autour de l'endroit visé, ce qui affine ce qu'elle enseigne au détriment de tout le reste. Des valeurs plus grandes l'étalent et atteignent plus souvent les deux extrêmes, ce qui se rapproche d'un entraînement uniforme.\n\nEn cas de doute, laisse-la à 1 et déplace plutôt la visée — la visée est le réglage qui change ce que l'exécution apprend, celui-ci change à quel point elle s'y consacre exclusivement.",
  "Weight averaging":
    "Moyennage des poids",
  "Average the weights":
    "Moyenner les poids",
  "Save a smoothed version of the weights instead of whatever the last step happened to produce. Makes checkpoints more consistent and overtraining slower to bite.":
    "Enregistre une version lissée des poids au lieu de ce que le dernier pas a produit par hasard. Rend les checkpoints plus réguliers et le surentraînement plus lent à mordre.",
  "Every training step moves the weights a little, and each of those moves is noisy — it is worked out from a handful of images, and a different handful would have pulled somewhere slightly different. So the weights at step 1400 are not reliably better than the weights at step 1200; part of the difference is just which pictures came up.\n\nWith this on, the run keeps a second, smoothed copy of the weights alongside the real ones and nudges it a little way towards the current weights after every step. That smoothed copy is what gets saved — as the checkpoints, as the final result, and as what the test samples are rendered from. Training itself is completely unaffected.\n\nWhat you get is a result that depends less on exactly where the run stopped: the quality difference between neighbouring checkpoints shrinks, and a run that goes on too long degrades more gradually, because an average lags behind. What it costs is one extra copy of whatever is being trained — nothing worth thinking about for a LoRA, a second whole model for a full finetune, which the memory estimate below accounts for.\n\nThe early part of a run is handled for you: a fresh average starts out equal to the untrained weights, so the run keeps it short at first and lengthens it as training goes on. Without that, a short run would save an average still holding its own random starting point.":
    "Chaque pas d'entraînement déplace un peu les poids, et chacun de ces déplacements est bruité : il est calculé à partir d'une poignée d'images, et une autre poignée aurait tiré vers un endroit légèrement différent. Les poids du pas 1400 ne sont donc pas fiablement meilleurs que ceux du pas 1200 ; une partie de la différence tient simplement aux images tombées.\n\nAvec ceci activé, l'exécution garde une seconde copie lissée des poids à côté des vrais et la pousse un peu vers les poids actuels après chaque pas. C'est cette copie lissée qui est enregistrée — comme checkpoints, comme résultat final, et comme ce à partir de quoi les échantillons de test sont rendus. L'entraînement lui-même n'est absolument pas affecté.\n\nCe que tu obtiens est un résultat qui dépend moins de l'endroit exact où l'exécution s'est arrêtée : l'écart de qualité entre checkpoints voisins se réduit, et une exécution qui dure trop longtemps se dégrade plus progressivement, parce qu'une moyenne est en retard. Le coût est une copie supplémentaire de ce qui est entraîné — rien qui mérite réflexion pour un LoRA, un second modèle entier pour un finetuning complet, ce dont l'estimation de mémoire ci-dessous tient compte.\n\nLe début de l'exécution est géré pour toi : une moyenne neuve part égale aux poids non entraînés, l'exécution la garde donc courte au début et l'allonge à mesure que l'entraînement avance. Sans cela, une exécution courte enregistrerait une moyenne contenant encore son propre point de départ aléatoire.",
  "Averaging window":
    "Fenêtre de moyennage",
  "How much of the old average is kept each step. 0.999 averages roughly the last 1000 steps; lower follows training more closely, higher smooths harder.":
    "Quelle part de l'ancienne moyenne est conservée à chaque pas. 0,999 moyenne à peu près les 1000 derniers pas ; plus bas suit l'entraînement de plus près, plus haut lisse plus fort.",
  "The fraction of the existing average kept at each step, with the rest taken from the current weights. It decides how long a stretch of training the saved result reflects — roughly 1 ÷ (1 − this value) steps.\n\n0.999 is about the last 1000 steps and is a sensible default for runs of a few thousand. On a short run (say 800 steps) that window is longer than the run itself, so the average never quite catches up — drop to 0.99 (about 100 steps) there. On a very long run you can go higher for a steadier result.\n\nAs a rule of thumb, keep the window well under the total number of steps.":
    "La fraction de la moyenne existante conservée à chaque pas, le reste étant pris sur les poids actuels. Elle décide de la longueur de la tranche d'entraînement que reflète le résultat enregistré — environ 1 ÷ (1 − cette valeur) pas.\n\n0,999 correspond aux 1000 derniers pas environ et est un défaut raisonnable pour des exécutions de quelques milliers de pas. Sur une exécution courte (disons 800 pas) cette fenêtre est plus longue que l'exécution elle-même, la moyenne ne rattrape donc jamais tout à fait — descends alors à 0,99 (environ 100 pas). Sur une exécution très longue tu peux monter pour un résultat plus stable.\n\nRègle empirique : garde la fenêtre nettement en dessous du nombre total de pas.",
  "Mostly a memory choice, except for Prodigy, which works the learning rate out for itself. Adafactor saves the most memory and runs on every GPU; 8-bit AdamW saves less and needs an NVIDIA or AMD card.":
    "Surtout un choix de mémoire, sauf pour Prodigy qui détermine le taux d'apprentissage tout seul. Adafactor économise le plus de mémoire et fonctionne sur toutes les GPU ; AdamW (8 bits) économise moins et exige une carte NVIDIA ou AMD.",
  "The optimizer is what actually turns gradients into weight changes. It does that using running statistics it keeps for every weight being trained — and those statistics are memory, which for a full finetune is usually most of what the run needs.\n\nAdamW is the standard choice and the safest. It keeps two statistics per trained weight, so a full finetune pays for the model roughly three times over: the weights themselves, plus two more of the same size.\n\nAdamW (8-bit) stores those two statistics at one byte each instead of four. It is a smaller saving than it sounds, because the weights and their gradients do not shrink, and it needs an NVIDIA or AMD (ROCm) GPU — elsewhere the run says so and uses plain AdamW.\n\nAdafactor replaces the larger of the two statistics with a per-row and a per-column summary of it, which is a fraction of the size. It saves considerably more than the 8-bit variant and it runs on every GPU, including Apple silicon — where it is the only memory saving available at all, since the 8-bit variant cannot run there. What it costs is a little stability: it usually wants a slightly higher learning rate than AdamW, so if a run learns nothing after a few hundred steps, raise the rate before changing anything else.\n\nProdigy is a different kind of answer. It measures how far the weights have travelled from where they started and works the learning rate out from that as it goes, which removes the one setting here that genuinely has to be found by trial: the right rate depends on the model, the dataset size and what is being taught, so a value that suits one job is wrong for the next. With it selected, the learning rate on the Optimization page becomes a multiplier on what it finds, and 1 means 'as found'. It uses a little more memory than AdamW, and it needs a few hundred steps to work its estimate up — so early samples look untrained even when the run is fine.\n\nFor LoRA training the memory differences are a rounding error, since only the small adapter has optimizer state. Leave it on AdamW for a first run; reach for Prodigy when you are tired of guessing the rate, and for Adafactor when a full finetune will not fit.":
    "L'optimiseur est ce qui transforme réellement les gradients en changements de poids. Il le fait à l'aide de statistiques courantes qu'il conserve pour chaque poids entraîné — et ces statistiques sont de la mémoire, qui pour un finetuning complet représente généralement l'essentiel de ce dont l'exécution a besoin.\n\nAdamW est le choix standard et le plus sûr. Il conserve deux statistiques par poids entraîné : un finetuning complet paie donc le modèle environ trois fois — les poids eux-mêmes, plus deux copies de même taille.\n\nAdamW (8 bits) stocke ces deux statistiques sur un octet chacune au lieu de quatre. L'économie est plus faible qu'il n'y paraît, car les poids et leurs gradients ne rétrécissent pas, et il exige une GPU NVIDIA ou AMD (ROCm) — ailleurs l'exécution le signale et utilise AdamW ordinaire.\n\nAdafactor remplace la plus grande des deux statistiques par un résumé par ligne et un par colonne, ce qui n'en représente qu'une fraction. Il économise nettement plus que la variante 8 bits et fonctionne sur toutes les GPU, y compris Apple silicon — où il est même la seule économie de mémoire disponible, la variante 8 bits ne pouvant pas y tourner. Le coût est un peu de stabilité : il demande généralement un taux d'apprentissage un peu plus élevé qu'AdamW, donc si une exécution n'apprend rien après quelques centaines de pas, augmente le taux avant de changer quoi que ce soit d'autre.\n\nProdigy est une réponse d'une autre nature. Il mesure de combien les poids se sont éloignés de leur point de départ et en déduit le taux d'apprentissage au fil de l'exécution, ce qui supprime le seul réglage d'ici qui doive vraiment se trouver par essais : le bon taux dépend du modèle, de la taille du jeu de données et de ce qui est enseigné, si bien qu'une valeur qui convient à une tâche est fausse pour la suivante. Une fois sélectionné, le taux d'apprentissage de la page Optimisation devient un multiplicateur de ce qu'il trouve, et 1 signifie « tel que trouvé ». Il utilise un peu plus de mémoire qu'AdamW et a besoin de quelques centaines de pas pour faire monter son estimation — les premiers échantillons paraissent donc non entraînés même quand l'exécution va bien.\n\nPour l'entraînement d'un LoRA les différences de mémoire sont une erreur d'arrondi, puisque seul le petit adaptateur possède un état d'optimiseur. Laisse AdamW pour une première exécution ; passe à Prodigy quand tu en as assez de deviner le taux, et à Adafactor quand un finetuning complet ne tient pas.",
  "AdamW (8-bit)":
    "AdamW (8 bits)",
  "Prodigy (finds its own rate)":
    "Prodigy (trouve son propre taux)",
  "Prodigy works the learning rate out for itself, so the rate on the Optimization page becomes a multiplier on what it finds — 1 leaves it alone. It needs a few hundred steps to settle, so early samples will look untrained.":
    "Prodigy détermine le taux d'apprentissage tout seul : le taux de la page Optimisation devient donc un multiplicateur de ce qu'il trouve, et 1 le laisse tel quel. Il lui faut quelques centaines de pas pour se stabiliser, les premiers échantillons paraîtront donc non entraînés.",
  "Regularization":
    "Régularisation",
  "How much reminders count":
    "Poids des images de rappel",
  "1 gives a regularization picture the same say as a training picture, which is the usual setting. Lower makes it a gentler reminder.":
    "1 donne à une image de régularisation le même poids qu'à une image d'entraînement, ce qui est le réglage habituel. Plus bas en fait un rappel plus doux.",
  "Regularization pictures are in the run to hold the model's existing idea of a thing in place while you teach it something new. This is how much each of them counts against a training picture, which counts 1.\n\n1 is the classic setting and a good starting point. Lower it if the run seems reluctant to learn what you are actually training — the reminders are pulling too hard. Raise it if what you are training keeps leaking into everything else of the same kind, which is the problem they exist to solve.\n\nThis is separate from a query's weight, which decides how OFTEN those pictures come up. How often and how much are different questions: a set of reminders is usually wanted often but quietly.":
    "Les images de régularisation sont dans l'exécution pour maintenir en place l'idée que le modèle a déjà d'une chose pendant que tu lui en enseignes une nouvelle. Ceci est le poids de chacune d'elles face à une image d'entraînement, qui compte 1.\n\n1 est le réglage classique et un bon point de départ. Baisse-le si l'exécution semble réticente à apprendre ce que tu entraînes réellement — les rappels tirent trop fort. Augmente-le si ce que tu entraînes déborde sans cesse sur tout le reste du même genre, ce qui est justement le problème qu'ils existent pour résoudre.\n\nC'est indépendant du poids d'une requête, qui décide de la FRÉQUENCE d'apparition de ces images. La fréquence et l'intensité sont deux questions distinctes : on veut généralement un ensemble de rappels souvent, mais discret.",
  "Pictures that remind the model what it already knows, instead of teaching it something new — they stop what you are training from spreading to everything else of the same kind. They never get the trigger word.":
    "Des images qui rappellent au modèle ce qu'il sait déjà, au lieu de lui apprendre quelque chose de nouveau — elles empêchent ce que tu entraînes de déborder sur tout le reste du même genre. Elles ne reçoivent jamais le déclencheur.",
  "These pictures hold the model's existing idea of the subject in place: pick the same KIND of thing you are training, but not the thing itself. You do not need to exclude your training pictures — anything an ordinary query matches stays a training picture. A reminder query that matches only training pictures leaves this pool empty, and the run says so in its log.":
    "Ces images maintiennent en place l'idée que le modèle a déjà du sujet : choisissez le même GENRE de chose que ce que vous entraînez, mais pas la chose elle-même. Inutile d'exclure vos images d'entraînement — tout ce qu'une requête ordinaire trouve reste une image d'entraînement. Une requête de rappel qui ne trouve que des images d'entraînement laisse ce pool vide, et l'exécution le signale dans son journal.",
  "Keep the text encoder on the CPU":
    "Garder l'encodeur de texte sur le processeur",
  "Frees all of its VRAM instead of some. The next batch's prompt is encoded while this one trains, so it costs nothing as long as the processor keeps up with the card.": "Libère toute sa VRAM au lieu d'une partie. Le prompt du lot suivant est encodé pendant que celui-ci s'entraîne, donc cela ne coûte rien tant que le processeur suit la carte.",
  "The row above makes the text encoder smaller; this one takes it off the graphics card altogether. Its weights stay in ordinary system memory and each prompt is turned into an embedding there, so the encoder occupies no VRAM at all — where quantizing it leaves roughly a third of it resident.\n\nMeasured on an RTX 5070 Ti at 4-bit, this takes Chroma from 9.6 GB to 5.3 and FLUX.1 from 11.4 to 7.0, which was enough to train FLUX.2 Klein at a resolution that did not previously fit.\n\nWhat it costs is one pass over the encoder per step, on the processor instead of the graphics card — and the next batch's prompt is encoded while the current one trains, so the card only waits where the processor is slower than a whole step. Measured on a 16-core desktop, T5-XXL takes about 1.3 seconds a prompt: a 1024-pixel step on an RTX 5090 hides that entirely, a 512-pixel step (half a second) does not. It cannot be combined with training the text encoder, which would mean doing that training on the processor.":
    "La ligne au-dessus réduit l'encodeur de texte ; celle-ci le retire complètement de la carte graphique. Ses poids restent dans la mémoire système ordinaire et chaque invite y est convertie en embedding : l'encodeur n'occupe donc aucune VRAM, là où la quantification en laisse environ un tiers.\n\nMesuré sur une RTX 5070 Ti en 4 bits, cela fait passer Chroma de 9,6 Go à 5,3 et FLUX.1 de 11,4 à 7,0 — assez pour entraîner FLUX.2 Klein à une résolution qui ne tenait pas auparavant.\n\nCe que cela coûte, c'est une passe sur l'encodeur par pas, sur le processeur au lieu de la carte graphique — et le prompt du lot suivant est encodé pendant que le lot courant s'entraîne, donc la carte n'attend que là où le processeur est plus lent qu'un pas entier. Mesuré sur un poste à 16 cœurs, T5-XXL prend environ 1,3 seconde par prompt : un pas à 1024 pixels sur une RTX 5090 le masque entièrement, un pas à 512 pixels (une demi-seconde) non. Il ne peut pas se combiner avec l'entraînement de l'encodeur de texte, qui reviendrait à faire cet entraînement sur le processeur.",

  // ---- the METHOD is an adapter, of which LoRA is one kind ----
  "An adapter is a small add-on file layered over the untouched model — fast, low memory, ideal for styles, characters and concepts. Full finetune rewrites the whole model: much more VRAM and data needed, only worth it for broad domain shifts. Which kind of adapter is the next question down.":
    "Un adaptateur est un petit fichier ajouté par-dessus le modèle intact — rapide, peu de mémoire, idéal pour les styles, les personnages et les concepts. Le finetuning complet réécrit tout le modèle : bien plus de VRAM et de données, et cela ne vaut le coup que pour un changement de domaine large. Quel type d'adaptateur est la question suivante, juste en dessous.",
  "An adapter leaves the base model untouched and trains a small add-on (a few dozen MB) that is layered on top at generation time. It is quick, fits ordinary hardware, can be mixed with other adapters and dialled up or down by weight — and it is enough for styles, characters, objects and most concepts. There are two kinds, LoRA and LoKr, and the Adapter section below picks between them; LoRA is the one to start with.\n\nA full finetune rewrites every weight of the model. It produces a multi-gigabyte model of its own, needs far more VRAM, far more images and much lower learning rates, and it can forget things it used to know. Reach for it only when you are moving the model into a genuinely different domain, not to teach it one more subject.":
    "Un adaptateur laisse le modèle de base intact et entraîne un petit ajout (quelques dizaines de Mo) posé par-dessus au moment de la génération. C'est rapide, cela tient sur du matériel ordinaire, cela se mélange avec d'autres adaptateurs et se dose par un poids — et cela suffit pour les styles, les personnages, les objets et la plupart des concepts. Il en existe deux sortes, LoRA et LoKr ; la section Adaptateur ci-dessous choisit entre elles, et LoRA est celle par laquelle commencer.\n\nUn finetuning complet réécrit chaque poids du modèle. Il produit un modèle à lui seul de plusieurs gigaoctets, demande bien plus de VRAM, bien plus d'images et des taux d'apprentissage bien plus bas, et il peut oublier ce qu'il savait. N'y recours que si tu déplaces le modèle vers un domaine réellement différent, pas pour lui apprendre un sujet de plus.",
  "Start from an existing adapter":
    "Partir d'un adaptateur existant",
  "A fresh adapter starts from noise and has to learn your concept from nothing. Starting from an existing one keeps everything it already learned and refines it — the usual reasons are adding new images to a concept you trained before, or nudging one that came out almost right.\n\nWeight sets trained on the same base model are offered — including ones trained on another model built on it — and the new job has to match the one it continues: the same adapter type, the same rank, and the same layer targeting. The trainer stops with a message naming what it found otherwise. Picking a job's finished result continues where it ended; picking an intermediate checkpoint rewinds to that point and continues from there.":
    "Un adaptateur neuf part du bruit et doit apprendre ton concept à partir de rien. Partir d'un adaptateur existant conserve tout ce qu'il a déjà appris et l'affine — les raisons habituelles sont d'ajouter de nouvelles images à un concept déjà entraîné, ou de retoucher un adaptateur presque réussi.\n\nLes jeux de poids entraînés sur le même modèle de base sont proposés — y compris ceux entraînés sur un autre modèle bâti dessus — et la nouvelle tâche doit correspondre à celle qu'elle poursuit : même type d'adaptateur, même rang, même sélection de couches. Sinon l'entraîneur s'arrête avec un message nommant ce qu'il a trouvé. Choisir le résultat terminé d'une tâche reprend là où il s'est arrêté ; choisir un checkpoint intermédiaire rembobine jusqu'à ce point et continue de là.",
  "Pick a finished adapter":
    "Choisir un adaptateur terminé",
  "No finished adapter for this base model yet":
    "Aucun adaptateur terminé pour ce modèle de base",
  "Optional: continue training an existing adapter instead of starting from scratch.":
    "Facultatif : poursuivre l'entraînement d'un adaptateur existant plutôt que partir de zéro.",
  "No full finetune":
    "Pas de finetuning complet",

  // ---- adapter wording: an adapter is LoRA or LoKr ----
  "The standard choice, and the format every other tool understands — a LoRA can be used anywhere.":
    "Le choix standard, et le format que tous les autres outils comprennent — un LoRA s'utilise partout.",
  "An adapter does not rewrite the model — it adds a small 'side channel' to certain layers, and rank is how wide that channel is: how much new information the adapter can hold.\n\nLow ranks (4–8) are plenty for a style or a colour palette and are very hard to overfit. Mid ranks (16–32) suit characters and objects with consistent details. High ranks (64+) mostly grow the file and the overfitting risk without helping, unless you are teaching a genuinely broad new domain.\n\nIt means slightly different things to the two adapter types. For a LoRA it is the hard ceiling on the change: a rank-16 adapter can only ever make a rank-16 change. For a LoKr it bounds only part of the structure, so a LoKr is not confined the way a LoRA is and its file grows far more slowly as you raise it — which is why the size estimate below is a figure for LoRA and a comparison for LoKr.":
    "Un adaptateur ne réécrit pas le modèle : il ajoute un petit « canal latéral » à certaines couches, et le rang est la largeur de ce canal, c'est-à-dire la quantité d'information nouvelle que l'adaptateur peut contenir.\n\nLes rangs faibles (4–8) suffisent largement pour un style ou une palette et sont très difficiles à surapprendre. Les rangs moyens (16–32) conviennent aux personnages et aux objets aux détails constants. Les rangs élevés (64+) ne font guère que grossir le fichier et le risque de surapprentissage, sauf si tu enseignes un domaine réellement nouveau et large.\n\nIl ne signifie pas tout à fait la même chose pour les deux types. Pour un LoRA c'est le plafond dur du changement : un adaptateur de rang 16 ne peut faire qu'un changement de rang 16. Pour un LoKr il ne borne qu'une partie de la structure, un LoKr n'est donc pas enfermé comme un LoRA et son fichier grossit bien plus lentement quand on l'augmente — d'où un chiffre pour LoRA et une comparaison pour LoKr ci-dessous.",
  "The adapter's output is multiplied by alpha ÷ rank before being added to the model, so alpha sets how loudly the adapter speaks at a given capacity. It works the same way for both adapter types.\n\nThe usual convention is alpha = rank, which makes the scale factor 1 and keeps behaviour comparable when you change rank. Setting alpha to half the rank is a common way to soften an adapter that comes out too strong. It interacts with the learning rate — halving alpha has a similar effect to halving the rate — so change one at a time.":
    "La sortie de l'adaptateur est multipliée par alpha ÷ rang avant d'être ajoutée au modèle : alpha décide donc du volume auquel l'adaptateur parle, à capacité donnée. Cela fonctionne pareil pour les deux types d'adaptateur.\n\nLa convention usuelle est alpha = rang, ce qui met le facteur à 1 et garde un comportement comparable quand on change le rang. Mettre alpha à la moitié du rang est une façon courante d'adoucir un adaptateur trop fort. Cela interagit avec le taux d'apprentissage — diviser alpha par deux ressemble à diviser le taux par deux — donc ne change qu'une chose à la fois.",
  "This architecture can only be trained as an adapter (LoRA or LoKr) alongside the frozen model. The \"Full finetune\" method, which rewrites the model's own weights, is not offered for it.":
    "Cette architecture ne peut être entraînée que comme adaptateur (LoRA ou LoKr) à côté du modèle gelé. La méthode « Finetuning complet », qui réécrit les poids propres du modèle, n’est pas proposée pour elle.",
  "No adapters for this base model yet.": "Pas encore d'adaptateur pour ce modèle de base.",
  "No trained adapters yet.": "Pas encore d'adaptateur entraîné.",
  "Which adapter this row applies":
    "Quel adaptateur cette ligne applique",
  "Adapter strength: 1 = as trained, below weakens, above strengthens (can distort past ~1.5).":
    "Force de l'adaptateur : 1 = comme entraîné, en dessous affaiblit, au-dessus renforce (peut distordre au-delà de ~1,5).",
  "Add adapter":
    "Ajouter un adaptateur",
  "Adapters":
    "Adaptateurs",
  "Finetune": "Finetune",
  "Generate with a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.":
    "Générer avec les poids d'un finetune complet à la place de ceux du modèle de base. Les adaptateurs se superposent à ce qui est choisi ici.",
  "none — the base model": "aucun — le modèle de base",
  "loading finetune": "chargement du finetune",
  "Stack trained adapters on the base model, each with its own strength — LoRA or LoKr. An adapter fits the model it was trained on and any other built on the same one.":
    "Empile des adaptateurs entraînés sur le modèle de base, chacun avec sa force — LoRA ou LoKr. Un adaptateur convient au modèle sur lequel il a été entraîné et à tout autre bâti sur le même.",
  "Generated images appear here — try out a trained adapter against its base model.":
    "Les images générées apparaissent ici — essaie un adaptateur entraîné face à son modèle de base.",
  "A much smaller file, and not limited by the rank the way a LoRA is. Whether it can be used outside this app depends on the model — see the ⓘ.":
    "Un fichier bien plus petit, et sans la limite de rang d’une LoRA. Son utilisabilité hors de cette application dépend du modèle — voir le ⓘ.",
  "Both add a small trainable layer over the frozen model; they differ in the shape of change they can express.\n\nA LoRA adds a 'low-rank' change: two thin matrices whose product is added to each targeted weight. Its capacity is exactly its rank — a rank-16 adapter can only ever make a rank-16 change, however long you train it. That is ample for a character, an object, a colour palette. It trains a little faster, it is the format every tool reads, and it carries better between related checkpoints: a LoRA trained on one finetune of a model usually still works on another.\n\nLoKr builds the change as a Kronecker product of two much smaller matrices instead. The saving comes from that structure rather than from throwing rank away, so the change is not confined to a thin slice of the weight while the file stays a small fraction of a LoRA's — under a tenth of the trainable parameters at rank 8. LyCORIS, whose method this is, suggests reaching for it when a LoRA 'does not learn well enough', and it is generally the better fit for styles and broad visual qualities, where a LoRA's rank ceiling is what you meet first. Its own caveats are the mirror image: slightly slower to train, and a very small LoKr transfers less well if you later swap the base model for a different finetune.\n\nWhat each can be USED by differs, and it is the file rather than the method. A LoRA is written in the layout every tool reads. A LoKr cannot be: that layout has a place for two matrices and nowhere to put a Kronecker factor. What it gets instead is a copy named the way ComfyUI names LoKr layers, and that works for the models whose layers ComfyUI addresses that way — FLUX.1, FLUX.1 Kontext and the Qwen-Image releases. On the others (SD 1.5, SDXL, Chroma, FLUX.2, Z-Image) a LoKr stays here: it works in the Evaluate tab and as the starting point of another job, but there is no file to hand over. On those, pick LoRA if the result has to leave this app.":
    "Les deux ajoutent une petite couche entraînable par-dessus le modèle gelé ; elles diffèrent par la forme de changement qu’elles peuvent exprimer.\n\nUne LoRA ajoute un changement « de rang faible » : deux matrices fines dont le produit s’ajoute à chaque poids ciblé. Sa capacité est exactement son rang — un adaptateur de rang 16 ne pourra jamais produire qu’un changement de rang 16, quelle que soit la durée de l’entraînement. C’est largement suffisant pour un personnage, un objet, une palette. Elle s’entraîne un peu plus vite, c’est le format que tous les outils lisent, et elle se transporte mieux entre checkpoints apparentés : une LoRA entraînée sur un finetune d’un modèle fonctionne généralement encore sur un autre.\n\nLoKr construit plutôt le changement comme un produit de Kronecker de deux matrices bien plus petites. L’économie vient de cette structure et non du rang jeté : le changement n’est donc pas confiné à une tranche mince du poids, tandis que le fichier ne représente qu’une fraction de celui d’une LoRA — moins d’un dixième des paramètres entraînables au rang 8. LyCORIS, à qui l’on doit la méthode, conseille d’y recourir quand une LoRA « n’apprend pas assez bien » ; elle convient généralement mieux aux styles et aux qualités visuelles larges, là où l’on bute d’abord sur le plafond de rang d’une LoRA. Ses propres réserves sont l’image inverse : entraînement légèrement plus lent, et une très petite LoKr se transfère moins bien si vous changez ensuite de modèle de base pour un autre finetune.\n\nCe que chacune peut SERVIR À diffère, et cela tient au fichier, pas à la méthode. Une LoRA est écrite dans le format que tous les outils lisent. Une LoKr ne peut pas l’être : ce format a une place pour deux matrices et aucune pour un facteur de Kronecker. Elle reçoit à la place une copie nommée comme ComfyUI nomme les couches LoKr, ce qui fonctionne pour les modèles dont il adresse les couches ainsi — FLUX.1, FLUX.1 Kontext et les versions Qwen-Image. Pour les autres (SD 1.5, SDXL, Chroma, FLUX.2, Z-Image), une LoKr reste ici : elle fonctionne dans l’onglet Évaluer et comme point de départ d’un autre job, mais il n’y a aucun fichier à transmettre. Sur ceux-là, choisissez LoRA si le résultat doit quitter cette application.",
  "LoKr expresses a weight's change as one small matrix combined with another. This number decides where the weight is cut into those two parts.\n\nLeft empty, the split is chosen to make the two parts as close to square as possible, which is where they are SMALLEST. Moving it either way grows the file, and the two directions are not the same thing: a low factor (4–8) pushes the weight into the second part, which is where the adapter's capacity is — that is the LyCORIS recipe for a LoKr that is not learning enough. A factor far above the square split grows the first, dense part instead, which costs size for nothing.\n\nMeasured on a 1280-wide layer at rank 8, against the same layer's LoRA: automatic 0.08x, factor 8 0.13x, factor 4 0.25x, factor 128 0.81x.\n\nThere is rarely a reason to set it. If a LoKr adapter is not learning enough, raise the rank first, then try a low factor.":
    "LoKr exprime le changement d’un poids comme une petite matrice combinée à une autre. Ce nombre décide où le poids est coupé en ces deux parties.\n\nLaissé vide, le découpage est choisi pour rendre les deux parties aussi carrées que possible, et c’est là qu’elles sont les PLUS PETITES. S’en écarter dans un sens ou dans l’autre fait grossir le fichier, et les deux directions ne se valent pas : un facteur bas (4–8) pousse le poids vers la seconde partie, là où se trouve la capacité de l’adaptateur — c’est la recette LyCORIS pour une LoKr qui n’apprend pas assez. Un facteur très au-dessus du découpage carré fait grossir la première partie, dense, ce qui coûte de la taille pour rien.\n\nMesuré sur une couche de largeur 1280 au rang 8, face à la LoRA de la même couche : automatique 0,08x, facteur 8 0,13x, facteur 4 0,25x, facteur 128 0,81x.\n\nIl y a rarement une raison de le régler. Si une LoKr n’apprend pas assez, augmentez d’abord le rang, puis essayez un facteur bas.",
  "Every picture this finds is also matched by a training query, so it contributes nothing and the run will not be regularized. Narrow it to pictures the run is NOT about.":
    "Chaque image trouvée ici est aussi trouvée par une requête d'entraînement : ce pool n'apporte donc rien et l'exécution ne sera pas régularisée. Restreignez-le à des images dont l'exécution ne parle PAS.",
  "val": "val",
  "stable": "stable",
  "validation": "validation",
  "Validate": "Valider",
  "Masked regions": "Régions masquées",
  "Mask out regions tagged": "Masquer les régions taguées",
  "Comma-separated tags whose bounding boxes are largely ignored by the loss — e.g. 'watermark'. The picture still trains; the region inside the boxes stops teaching. Tags without boxes on an image mask nothing there.": "Tags séparés par des virgules dont les boîtes sont largement ignorées par la perte — p. ex. 'watermark'. L'image s'entraîne toujours ; la région dans les boîtes cesse d'enseigner. Un tag sans boîte sur une image n'y masque rien.",
  "Mask out regions of tags marked": "Masquer les régions des tags marqués",
  "Comma-separated META tags. Any tag the library marks with one of these has its boxes masked — so the rule is stated once in the Tags tab rather than listed here.": "Méta-tags séparés par des virgules. Tout tag que la bibliothèque marque ainsi voit ses boîtes masquées — la règle est donc énoncée une fois dans l'onglet Tags plutôt que listée ici.",
  "Masked region weight": "Poids des régions masquées",
  "How much a masked region still counts. 0 hides it from training entirely; 1 is the same as not masking.": "Combien une région masquée compte encore. 0 la retire entièrement de l'entraînement ; 1 revient à ne pas masquer.",
  "Validation": "Validation",
  "Score a validation loss": "Mesurer une perte de validation",
  "A few images are held out of training and re-scored on a fixed seed as the run goes. Falling: still learning. Rising while the training loss falls: memorizing — pick an earlier checkpoint.": "Quelques images sont écartées de l'entraînement et re-notées sur une graine fixe au fil du run. En baisse : il apprend encore. En hausse pendant que la perte d'entraînement baisse : mémorisation — choisir un checkpoint plus ancien.",
  "Validate every": "Valider tous les",
  "Each round costs one forward pass per scored image — a small set every few hundred steps is barely noticeable.": "Chaque tour coûte une passe avant par image notée — un petit lot toutes les quelques centaines d'étapes passe inaperçu.",
  "Held-out images": "Images écartées",
  "Taken OUT of training entirely and scored each round. Capped at half the dataset; 16 is plenty for a LoRA-sized run. 0 turns the held-out series off.": "Retirées entièrement de l'entraînement et notées à chaque tour. Plafonné à la moitié du jeu de données ; 16 suffisent pour un run de taille LoRA. 0 coupe la série.",
  "Stable-loss images": "Images de perte stable",
  "Ordinary TRAINING images re-scored the same fixed way — the training curve without its sampling noise. They stay in training; 0 turns the series off.": "Des images d'ENTRAÎNEMENT ordinaires re-notées de la même façon fixe — la courbe d'entraînement sans son bruit d'échantillonnage. Elles restent à l'entraînement ; 0 coupe la série.",
  "Some pictures are worth training on except for one rectangle: a watermark, a shop’s caption strip, a censor bar. Left alone, the model learns the rectangle along with the picture — a run over watermarked photographs reliably teaches the watermark. Throwing those pictures out costs the dataset; this keeps them and hides the rectangle from training instead.\n\nThe regions come from the boxes already on the tag: draw a box for `watermark` in the annotator (or let the watermark detector’s tag carry one), name the tag here, and every image carrying such a box trains with the loss inside it turned down. Where a subject tag has no drawn box, its detected faces stand in, exactly as they do for crop-aware training. An image whose named tags have no boxes trains completely normally — nothing is masked there.\n\nOnly the LOSS is masked. The pixels still pass through the image encoder, so the cached latents are the ordinary ones shared with unmasked runs, and nothing is re-encoded when this setting changes. The mask lives in latent space, where one cell covers 8×8 pixels rounded outward to whole cells — so it cannot hide anything much thinner than that, and a pixel-accurate outline is not something it can promise. It also cannot conjure what is UNDER the watermark: the model simply receives no signal about that area, from this picture.\n\nPairs naturally with a tag the prompt always includes (Always include under Tag selection): the prompt says the watermark is there, the mask stops the pixels teaching it, and at generation time the model has no reason to produce one unprompted.": "Certaines images méritent l'entraînement à un rectangle près : un filigrane, le bandeau d'une boutique, une barre de censure. Laissé tel quel, le modèle apprend le rectangle avec l'image — un run sur des photos filigranées enseigne le filigrane à coup sûr. Jeter ces images coûte au jeu de données ; ceci les garde et cache le rectangle à l'entraînement.\n\nLes régions viennent des boîtes déjà portées par le tag : dessinez une boîte pour `watermark` dans l'annotateur (ou laissez le tag du détecteur de filigranes en porter une), nommez le tag ici, et chaque image portant une telle boîte s'entraîne avec la perte réduite à l'intérieur. Là où un tag de sujet n'a pas de boîte dessinée, ses visages détectés prennent le relais, exactement comme pour le recadrage conscient des boîtes. Une image dont les tags nommés n'ont pas de boîtes s'entraîne tout à fait normalement — rien n'y est masqué.\n\nSeule la PERTE est masquée. Les pixels passent toujours par l'encodeur d'image, les latents en cache sont donc les ordinaires, partagés avec les runs non masqués, et rien n'est ré-encodé quand ce réglage change. Le masque vit dans l'espace latent, où une cellule couvre 8×8 pixels arrondis vers l'extérieur en cellules entières — il ne peut donc rien cacher de bien plus fin, et un contour au pixel près n'est pas quelque chose qu'il peut promettre. Il ne peut pas non plus deviner ce qu'il y a SOUS le filigrane : le modèle ne reçoit simplement aucun signal sur cette zone, depuis cette image.\n\nSe marie naturellement avec un tag que le prompt inclut toujours (Toujours inclure sous Sélection des tags) : le prompt dit que le filigrane est là, le masque empêche les pixels de l'enseigner, et à la génération le modèle n'a aucune raison d'en produire un sans qu'on le demande.",
  "The same rule, stated once in the library instead of tag by tag here. A meta tag put on the tags whose boxes should never teach — `masked`, say — covers every such tag at once, including ones created after this job was written.\n\nThe list is resolved to tag names when the dataset is built, so the job’s log says how many images actually carried a masked region. A run where that line says zero has a rule pointing at tags nobody drew boxes for.": "La même règle, énoncée une fois dans la bibliothèque au lieu de tag par tag ici. Un méta-tag posé sur les tags dont les boîtes ne doivent jamais enseigner — `masked`, disons — couvre tous ces tags d'un coup, y compris ceux créés après l'écriture de ce job.\n\nLa liste est résolue en noms de tags à la construction du jeu de données, le log du job dit donc combien d'images portaient réellement une région masquée. Un run où cette ligne dit zéro a une règle pointant vers des tags sans boîtes.",
  "What a cell inside a masked box still counts for. 0 hides the region entirely, which is the usual choice for a watermark — there is nothing in it worth a whisper. A small value (0.05–0.2) keeps a faint signal, which can be worth it when the boxes are generous and cover real picture around the thing being hidden.\n\n1 is the unmasked loss, so setting it there is the same as clearing the tag lists. Where an image also trains with an alpha mask, the two multiply: a masked region on a transparent background is doubly not the picture.": "Ce que compte encore une cellule dans une boîte masquée. 0 cache entièrement la région, le choix habituel pour un filigrane — rien n'y vaut un murmure. Une petite valeur (0,05–0,2) garde un signal faible, ce qui peut valoir le coup quand les boîtes sont généreuses et couvrent de la vraie image autour de la chose à cacher.\n\n1 est la perte non masquée, l'y régler revient donc à vider les listes de tags. Quand une image s'entraîne aussi avec un masque alpha, les deux se multiplient : une région masquée sur fond transparent est doublement pas l'image.",
  "The training loss cannot answer the question people ask of it. It is drawn from the pictures being trained on, at a different random noise level every step, so it is noisy by construction — and it keeps falling for as long as the model memorizes, which means it looks healthiest exactly when a run has gone on too long.\n\nThis scores two extra series that can answer it, both with the plain per-sample loss on a fixed seed, so every round asks the model exactly the same questions and the number moves only when the model does. The series appear as their own lines on the loss graph, and each round is a line in the job’s log.\n\nReading it: the validation loss falls while the model generalizes and flattens or turns when it starts memorizing — the turning point is roughly where to stop, and with step snapshots on, the checkpoint to pick. Expect it to sit above the training loss and to move in small amounts; what matters is the direction, not the level. It stays comparable across pauses, resumes and step extensions, because the scored images and the seed never change within a job.": "La perte d'entraînement ne peut pas répondre à la question qu'on lui pose. Elle est tirée des images en cours d'entraînement, à un niveau de bruit aléatoire différent à chaque étape, elle est donc bruitée par construction — et elle continue de baisser tant que le modèle mémorise, elle paraît donc au mieux exactement quand un run a trop duré.\n\nCeci mesure deux séries supplémentaires qui peuvent y répondre, toutes deux avec la perte simple par image sur une graine fixe, si bien que chaque tour pose au modèle exactement les mêmes questions et que le nombre ne bouge que si le modèle bouge. Les séries apparaissent comme des lignes à part sur le graphe de perte, et chaque tour est une ligne dans le log du job.\n\nLecture : la perte de validation baisse tant que le modèle généralise, et s'aplatit ou remonte quand il commence à mémoriser — le point de retournement est à peu près où s'arrêter et, avec les snapshots d'étape, le checkpoint à choisir. Attendez-vous à la voir au-dessus de la perte d'entraînement et bouger par petites quantités ; ce qui compte est la direction, pas le niveau. Elle reste comparable à travers pauses, reprises et rallonges d'étapes, car les images notées et la graine ne changent jamais au sein d'un job.",
  "How often a round runs, in steps. A round costs one forward pass per scored image — no gradients, no optimizer — so a 16-image set is a few seconds; matching the sample or checkpoint cadence keeps the graph, the images and the snapshots telling one story at the same steps.\n\nVery frequent rounds buy little: overfitting announces itself over hundreds of steps, not five.": "La fréquence des tours, en étapes. Un tour coûte une passe avant par image notée — pas de gradients, pas d'optimiseur — un lot de 16 images prend donc quelques secondes ; caler la cadence sur celle des échantillons ou des checkpoints fait raconter la même histoire au graphe, aux images et aux snapshots aux mêmes étapes.\n\nDes tours très fréquents n'apportent presque rien : le surapprentissage s'annonce sur des centaines d'étapes, pas sur cinq.",
  "How many images are set aside for the validation loss. They are taken OUT of training entirely — never visited, in no pool, their captions never seen — because a loss over pictures the model is also memorizing measures nothing. The pick is random but fixed per job, whole images at a time (a picture cannot be half in training), regularization pools are not eligible, and it is capped at half the dataset so the setting can never eat the run it protects.\n\nMore images make a steadier line at a linearly higher cost per round. On a small dataset every held-out image is also a training image lost, which is the real price — 8–16 is usually enough to see the turn, and the job’s log says exactly how many were held out.": "Combien d'images sont mises de côté pour la perte de validation. Elles sortent entièrement de l'entraînement — jamais visitées, dans aucun pool, leurs captions jamais vues — car une perte sur des images que le modèle mémorise en même temps ne mesure rien. Le tirage est aléatoire mais fixe par job, par images entières (une image ne peut pas être à moitié à l'entraînement), les pools de régularisation ne sont pas éligibles, et il est plafonné à la moitié du jeu de données pour que le réglage ne dévore jamais le run qu'il protège.\n\nPlus d'images font une ligne plus stable à un coût par tour linéairement plus élevé. Sur un petit jeu de données, chaque image écartée est aussi une image d'entraînement perdue — c'est le vrai prix ; 8–16 suffisent d'habitude à voir le retournement, et le log du job dit exactement combien ont été écartées.",
  "A second series over ordinary TRAINING images: a fixed slice, re-scored with the same fixed seed each round. Nothing is held out — these stay in training — so it costs no data at all.\n\nWhat it shows is the training curve with the sampling noise removed. The per-step loss jumps around because every step draws different pictures at different noise levels; this line asks the same pictures at the same noise every time, so it is readable where the raw curve is a cloud. Compared against the held-out line it also localizes trouble: both falling is learning, stable falling while held-out rises is memorizing, and neither falling means the run is not learning at all.": "Une seconde série sur des images d'ENTRAÎNEMENT ordinaires : une tranche fixe, re-notée à chaque tour avec la même graine fixe. Rien n'est écarté — elles restent à l'entraînement — cela ne coûte donc aucune donnée.\n\nElle montre la courbe d'entraînement sans le bruit d'échantillonnage. La perte par étape saute parce que chaque étape tire d'autres images à d'autres niveaux de bruit ; cette ligne pose chaque fois les mêmes questions aux mêmes images, et se lit là où la courbe brute est un nuage. Comparée à la ligne écartée, elle localise aussi le problème : les deux qui baissent, il apprend ; la stable qui baisse pendant que l'écartée monte, il mémorise ; aucune qui ne baisse, le run n'apprend rien du tout.",
  "Save the current rules, or load a saved set": "Enregistrer les règles actuelles, ou charger un jeu enregistré",
  "Rule sets": "Jeux de règles",
  "Remember the current rules — name the set in this list afterwards": "Retenir les règles actuelles — nommez le jeu dans cette liste ensuite",
  "Add a rule first": "Ajoutez d’abord une règle",
  "Save current rules": "Enregistrer les règles actuelles",
  "Add this set's rules to the job — rows it already has stay put": "Ajouter les règles de ce jeu au job — les lignes déjà là restent",
  "Value rules": "Règles de valeur",
  "Turn numeric value tags (height:172cm) into words at prompt time. The first matching rule wins — drag rows to reorder.": "Traduit les étiquettes de valeur numériques (height:172cm) en mots au moment du prompt. La première règle qui correspond gagne — glissez les lignes pour réordonner.",
  "namespace, e.g. height": "espace de noms, p. ex. height",
  "Keep the raw tag in the prompt beside the rule's text": "Garder l’étiquette brute dans le prompt à côté du texte de la règle",
  "keep tag": "garder l’étiquette",
  "Remove this rule": "Retirer cette règle",
  "Add rule": "Ajouter une règle",
  "Any tag shaped `<name>:<number><unit>` is a value tag — `people:3`, `height:172cm`, `height:1.72m`, or a ranking’s own `quality:7` — and a rule here turns a range of those numbers into words at prompt time: where `height` is greater than 190cm, write `tall`. A raw `height:172cm` token teaches a text encoder nothing it can read back at generation time; a word does.\n\nA matching tag is replaced by the rule’s text, and a per-rule toggle keeps the raw tag alongside for whoever wants both spellings in the prompt. The metric length and mass families convert, so one rule covers `172cm` and `1.72m` alike; an unknown unit compares only against the same unit, and a plain number only against plain numbers.\n\nRanges may overlap, and the first matching rule wins — the rows are dragged into order, and that order is part of the configuration. A value tag no rule matches passes through the prompt unchanged, so nothing is dropped silently. The rule’s phrase rides the ordinary random pick and dropout like the tag it replaced: prompts sometimes carry it and sometimes do not, which is exactly the variation score-tag conditioning wants.\n\nThe rules are resolved when the dataset is built — the job’s log says how many tags they matched — and a set of rules can be saved and loaded by name, so a house vocabulary is written once and reused across jobs. Loading a set adds its missing rules to the job rather than replacing the rows already there.": "Toute étiquette de la forme `<nom>:<nombre><unité>` est une étiquette de valeur — `people:3`, `height:172cm`, `height:1.72m`, ou le `quality:7` d’un classement — et une règle ici traduit une plage de ces nombres en mots au moment du prompt : là où `height` dépasse 190cm, écrire `tall`. Un jeton brut `height:172cm` n’apprend rien qu’un encodeur de texte puisse relire à la génération ; un mot, si.\n\nUne étiquette qui correspond est remplacée par le texte de la règle, et un interrupteur par règle garde l’étiquette brute à côté pour qui veut les deux graphies dans le prompt. Les familles métriques de longueur et de masse se convertissent, une règle couvre donc `172cm` et `1.72m` de la même façon ; une unité inconnue ne se compare qu’à la même unité, et un nombre nu qu’aux nombres nus.\n\nLes plages peuvent se chevaucher et la première règle qui correspond gagne — les lignes se réordonnent par glissement, et cet ordre fait partie de la configuration. Une étiquette de valeur qu’aucune règle ne touche passe dans le prompt telle quelle : rien n’est écarté en silence. La formulation de la règle suit le tirage aléatoire ordinaire et le dropout comme l’étiquette qu’elle remplace : les prompts la portent parfois et parfois non, exactement la variation que veut le conditionnement par score.\n\nLes règles sont résolues à la construction du jeu de données — le journal du job dit combien d’étiquettes elles ont touchées — et un jeu de règles s’enregistre et se recharge par nom : un vocabulaire maison s’écrit une fois et se réutilise entre jobs. Charger un jeu ajoute les règles manquantes au lieu de remplacer les lignes déjà là.",
  "Write tags as":
    "Écrire les tags comme",
  "Their name":
    "leur nom",
  "Their comment":
    "leur commentaire",
  "Name and comment":
    "nom et commentaire",
  "A tag's comment is the one line beside its name in the Tags tab — the same idea in words a text encoder can read. A tag with no comment is written as its name.":
    "Le commentaire d'un tag est la ligne à côté de son nom dans l'onglet Tags — la même idée en mots qu'un encodeur de texte peut lire. Un tag sans commentaire est écrit par son nom.",
  "A tag's comment is the one line beside its name in the Tags tab — “one girl in the picture” for `1girl`, “from below, looking up at the subject” for `from_below`. A booru vocabulary is compact for the people typing it and opaque to a text encoder; the comment is the same idea in words the encoder can read.\n\n“Their name” is what every run did: the tag as it is spelled. “Their comment” writes the comment in place of the name wherever a picked tag has one, and “Name and comment” writes the name with the comment in brackets after it, so the model learns both spellings of one thing. A tag with no comment is written as its name whatever this says.\n\nOnly the PROMPT changes. Matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all stay keyed on the tag's name, exactly as with aliases — and the comment is read from the library when the dataset is built, so editing a comment later changes the next run, not this one.":
    "Le commentaire d'un tag est la ligne à côté de son nom dans l'onglet Tags — « une fille dans l'image » pour `1girl`, « vu d'en bas, regardant le sujet » pour `from_below`. Un vocabulaire booru est compact pour ceux qui le tapent et opaque pour un encodeur de texte ; le commentaire est la même idée en mots que l'encodeur peut lire.\n\n« Leur nom » est ce que chaque entraînement faisait : le tag tel qu'il s'écrit. « Leur commentaire » écrit le commentaire à la place du nom partout où un tag choisi en a un, et « Nom et commentaire » écrit le nom suivi du commentaire entre parenthèses, pour que le modèle apprenne les deux graphies d'une même chose. Un tag sans commentaire est écrit par son nom quoi qu'il en soit.\n\nSeul le PROMPT change. La correspondance, les listes toujours/exclure, l'équilibrage par fréquence, le poids de la perte et les boîtes qu'un recadrage doit conserver restent tous indexés sur le nom du tag, exactement comme pour les alias — et le commentaire est lu dans la bibliothèque quand le jeu de données est construit, donc modifier un commentaire ensuite change l'entraînement suivant, pas celui-ci.",
  "Remove the selected images?": "Supprimer les images sélectionnées ?",
  "They cannot be recovered.": "Elles ne pourront pas être récupérées.",
  "Delete all {n} results from this session?": "Supprimer les {n} résultats de cette session ?",
  "The generated images go with them.": "Les images générées partent avec.",
  "Its downloaded weights can go with it, or stay in the cache for a later download to find.": "Ses poids téléchargés peuvent partir avec lui, ou rester dans le cache pour qu'un téléchargement ultérieur les retrouve.",
  "Remove and delete weights": "Retirer et supprimer les poids",
  "Remove the training job “{name}”?": "Supprimer la tâche d'entraînement « {name} » ?",
  "Remove {n} training jobs?": "Supprimer {n} tâches d'entraînement ?",
  "Its checkpoints, test samples and trained result are deleted with it — except anything locked, which is kept in the LoRAs list. This cannot be undone.": "Ses points de contrôle, échantillons et résultat entraîné sont supprimés avec elle, et c'est irréversible. Sauf ce qui est verrouillé, qui est conservé dans la liste des LoRA.",
  "Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone.": "Leurs points de contrôle, échantillons et résultats entraînés sont supprimés avec elles, et c'est irréversible. Sauf ce qui est verrouillé, qui est conservé dans la liste des LoRA.",
  "The Train tab": "L'onglet Entraîner",
  "The Evaluate tab": "L'onglet Évaluer",
  "The Models tab": "L'onglet Modèles",
  "Your models": "Vos modèles",
  "Finetunes": "Finetunes",
  "Based on {model}": "Basé sur {model}",
  "A full finetune of {model}": "Un finetune complet de {model}",
  "The built-in release, one of your own models, or a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.": "La version intégrée, l’un de vos propres modèles ou les poids d’un finetune complet à la place de ceux du modèle de base. Les adaptateurs s’empilent sur ce qui est choisi ici.",
};

export default CATALOG;
