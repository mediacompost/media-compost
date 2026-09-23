// uses live in the APP catalog; this file holds only train-chunk strings.

import type { Catalog } from "../../shared/i18nCore";

const CATALOG: Catalog = {
  "default":
    "predeterminado",
  "This model's own size. A job set to it follows whichever model it is pointed at.":
    "El tamaño propio de este modelo. Una ejecución puesta en él sigue al modelo al que apunta.",
  "{n} px":
    "{n} px",
  "A run trains at one size at least.":
    "Una ejecución entrena al menos a un tamaño.",
  "A run trains at up to five sizes — each one is another pass over the dataset per epoch.":
    "Una ejecución entrena a cinco tamaños como máximo — cada uno es otra pasada por el conjunto de datos en cada época.",
  "e.g. 704":
    "p. ej. 704",
  "Another size…":
    "Otro tamaño…",
  "Pick every size this run should train at. A picture joins each one it is big enough for, so the same picture can be learnt at more than one scale — and each size is another pass over the dataset per epoch.":
    "Elige cada tamaño al que debe entrenar esta ejecución. Una imagen se suma a cada uno para el que sea lo bastante grande, de modo que la misma imagen se aprende a más de una escala — y cada tamaño es otra pasada por el conjunto de datos en cada época.",
  "Left empty both fields use the model's own size — a test sample is not tied to the sizes the run trains at.":
    "Vacíos, ambos campos usan el tamaño propio del modelo — una imagen de prueba no está atada a los tamaños en que se entrena.",
  "The sizes images are trained at, each given as one number that stands for a pixel budget: 1024 means 'about a megapixel', which every aspect-ratio bucket then spends differently — 1024×1024, or 1216×832, or 832×1216.\n\nMatch them to what the base model was trained on (1024 for SDXL, Chroma and FLUX.2, 512 for SD 1.5); training far above that teaches little and costs a lot, while training below it is a genuine speed and memory lever at the price of fine detail. Cost scales with the area, so 768 is nearly half the work per step that 1024 is. The size the list marks as default is the model's own, and a job set to it follows whichever model it is pointed at.\n\nPicking more than one trains the same pictures at each of them. A model that has only ever seen a subject at 1024 has learnt it together with the canvas it was on: asked for something smaller it tends to answer with a crop or a doubled-up version of the same framing. Several sizes separate what the model learns about the subject from what it learns about the shape of the picture.\n\nEach size is a full family of buckets, and every image joins the ones it is large enough for — which is the other half of what this is for. Under Never upscale a 700-pixel scan is simply left out of a 1024 run; add 512 and it trains there instead of being dropped, while the large pictures keep training at both.\n\nIt is not free. A size is another pass over the dataset in every epoch and another cached latent per picture, and the batches at the largest one decide the peak memory — so adding a size above the others raises what the run needs on the card, and adding ones below mainly makes an epoch longer. Two or three an octave apart (512, 768, 1024) is the usual shape; at most five.":
    "Los tamaños a los que se entrenan las imágenes, cada uno como un número que representa un presupuesto de píxeles: 1024 significa «alrededor de un megapíxel», que cada bucket de relación de aspecto gasta de otro modo — 1024×1024, 1216×832 u 832×1216.\n\nAjústalos a aquello con lo que se entrenó el modelo base (1024 para SDXL, Chroma y FLUX.2, 512 para SD 1.5); entrenar muy por encima enseña poco y cuesta mucho, mientras que entrenar por debajo es una palanca real de velocidad y memoria al precio del detalle fino. El coste escala con el área, así que 768 es casi la mitad de trabajo por paso que 1024. El tamaño que la lista marca como predeterminado es el propio del modelo, y una ejecución puesta en él sigue al modelo al que apunta.\n\nElegir más de uno entrena las mismas imágenes en cada uno. Un modelo que solo ha visto un motivo a 1024 lo ha aprendido junto con el lienzo en el que estaba: si se le pide algo más pequeño, suele responder con un recorte o con una versión duplicada del mismo encuadre. Varios tamaños separan lo que el modelo aprende sobre el motivo de lo que aprende sobre la forma de la imagen.\n\nCada tamaño es una familia completa de buckets, y cada imagen se suma a aquellos para los que es lo bastante grande — la otra mitad de para qué sirve esto. Con «Nunca ampliar», un escaneo de 700 píxeles simplemente queda fuera de una ejecución a 1024; añade 512 y entrenará ahí en vez de descartarse, mientras las imágenes grandes siguen entrenando en ambos.\n\nNo es gratis. Un tamaño es otra pasada por el conjunto de datos en cada época y otro latente en caché por imagen, y los lotes del mayor deciden la memoria máxima — así que añadir un tamaño por encima de los demás eleva lo que la ejecución necesita en la tarjeta, y añadir otros por debajo alarga sobre todo la época. Dos o tres separados por una octava (512, 768, 1024) es la forma habitual; cinco como máximo.",
  "An image smaller than its bucket has to be enlarged to train at that size, and enlarging invents detail that was never in the picture: soft edges, smeared texture, the interpolation's own look. Trained on, that is what the model learns the subject looks like.\n\nThis is on by default. Those images are left out while the dataset is built — before anything is encoded, so they cost no time and no cache — and the run says how many it dropped. It is asked per resolution, so a picture too small for the largest size still trains at a smaller one rather than being dropped from the run; turn it off for a small dataset, where a slightly soft picture is usually worth more than no picture.":
    "Una imagen más pequeña que su bucket tiene que ampliarse para entrenar a ese tamaño, y ampliar inventa detalle que nunca estuvo en la imagen: bordes blandos, textura emborronada, el aspecto propio de la interpolación. Entrenado con eso, es lo que el modelo aprende que el motivo parece.\n\nEstá activado por defecto. Esas imágenes quedan fuera mientras se construye el conjunto de datos — antes de codificar nada, así que no cuestan tiempo ni caché — y la ejecución dice cuántas descartó. Se pregunta por resolución, así que una imagen demasiado pequeña para el tamaño mayor todavía entrena en uno menor en lugar de quedar fuera; desactívalo para un conjunto pequeño, donde una imagen algo blanda suele valer más que ninguna imagen.",
  "New training job": "Nuevo trabajo de entrenamiento",
  "Drafts": "Borradores",
  "Paused": "En pausa",
  "Completed": "Completados",
  "Failed": "Fallidos",
  "Full finetune": "Finetune completo",
  "Loss appears here once training starts.": "La pérdida aparece aquí cuando empiece el entrenamiento.",
  "Test samples": "Muestras de prueba",
  "Select a job to see its progress, samples and settings.": "Selecciona un trabajo para ver su progreso, muestras y ajustes.",
  "No training jobs yet. Create one to fine-tune a model (LoRA or full) on images selected straight from your library.": "Aún no hay trabajos de entrenamiento. Crea uno para afinar un modelo (LoRA o completo) con imágenes seleccionadas directamente de tu biblioteca.",
  "Training environment not set up": "Entorno de entrenamiento sin configurar",
  "Edit training job": "Editar trabajo de entrenamiento",
  "Save draft": "Guardar borrador",
  "Save & queue": "Guardar y poner en cola",
  "Method": "Método",
  "Hyperparameters": "Hiperparámetros",
  "Memory & speed": "Memoria y velocidad",
  "Canceled before any image was generated": "Cancelado antes de generar ninguna imagen",
  "{done} of {total} images": "{done} de {total} imágenes",
  "not generated yet": "aún no generado",
  "Download this LoRA": "Descargar este LoRA",
  "NVIDIA only": "Solo NVIDIA",
  "Off (fused kernels)": "Desactivado (kernels fusionados)",
  "On (save VRAM)": "Activado (ahorra VRAM)",
  "needs an NVIDIA GPU": "necesita una GPU NVIDIA",
  "needs an NVIDIA GPU (Ada or newer)": "necesita una GPU NVIDIA (Ada o más nueva)",
  "this model has none": "este modelo no tiene",
  "8-bit float (fp8)": "float de 8 bits (fp8)",
  "8-bit (int8)": "8 bits (int8)",
  "FLUX.2 Klein (base, 4B)": "FLUX.2 Klein (base, 4B)",
  "Images are being generated": "Se están generando imágenes",
  "= 1 image": "= 1 imagen",
  "= {n} images": { one: "= {n} imagen", other: "= {n} imágenes" },
  "Length & learning rate": "Duración y tasa de aprendizaje",
  "Dataset": "Conjunto de datos",
  "Add query": "Añadir consulta",
  "Remove query": "Quitar consulta",
  "invalid query": "consulta no válida",
  "Empty query = every image in the library.": "Consulta vacía = todas las imágenes de la biblioteca.",
  "Total steps": "Pasos totales",
  "Learning rate": "Tasa de aprendizaje",
  "Batch size": "Tamaño de lote",
  "Gradient accumulation": "Acumulación de gradiente",
  "Rank": "Rango",
  "Train text encoder": "Entrenar el codificador de texto",
  "Checkpoints": "Checkpoints",
  "Checkpoint every": "Checkpoint cada",
  "Cache latents": "Cachear latentes",
  "Random crop": "Recorte aleatorio",
  "Resolutions":
    "Resoluciones",
  "Crops & flips":
    "Recortes y volteo",
  "Max aspect ratio": "Proporción máxima",
  "Horizontal flip probability": "Probabilidad de volteo horizontal",
  "Trigger word": "Palabra desencadenante",
  "Only captions tagged": "Solo descripciones etiquetadas",
  "Skip captions tagged": "Omitir descripciones etiquetadas",
  "Only instructions tagged": "Solo instrucciones etiquetadas",
  "Skip instructions tagged": "Omitir instrucciones etiquetadas",
  "Comma-separated meta tags whose instructions are never used. Applied after the include list, so it also removes instructions the list let in.": "Metaetiquetas separadas por comas cuyas instrucciones nunca se usan. Se aplica tras la lista de inclusión, así que también quita instrucciones que la lista dejó entrar.",
  "Comma-separated meta tags whose captions are never used. Applied after the include list, so it also removes captions the list let in.": "Metaetiquetas separadas por comas cuyas descripciones nunca se usan. Se aplica tras la lista de inclusión, así que también quita descripciones que la lista dejó entrar.",
  "Always include": "Incluir siempre",
  "Skip tag groups tagged": "Omitir grupos de etiquetas etiquetados",
  "Comma-separated meta tags naming whole tag groups to ignore: a tag placed only in such a group never reaches a prompt. The tags stay on your items.": "Metaetiquetas separadas por comas que nombran grupos de etiquetas enteros a ignorar: una etiqueta colocada solo en tal grupo nunca llega a un prompt. Las etiquetas se quedan en tus elementos.",
  "Min tags per prompt": "Etiquetas mínimas por prompt",
  "Max tags per prompt": "Etiquetas máximas por prompt",
  "Pick probability": "Probabilidad de sorteo",
  "Uniform": "Uniforme",
  "Balance rare tags": "Equilibrar etiquetas raras",
  "Frequency measured in": "Frecuencia medida en",
  "Training data": "Datos de entrenamiento",
  "Previous step": "Paso anterior",
  "Next step": "Paso siguiente",
  "(empty prompt)": "(prompt vacío)",
  "Show each step's min/max micro-batch loss": "Mostrar la pérdida mín/máx de micro-lote de cada paso",
  "Expand graph": "Expandir gráfica",
  "Collapse graph": "Plegar gráfica",
  "steps/s": "pasos/s",
  "Smooth the line (EMA)": "Suavizar la línea (EMA)",
  "Whole library": "Biblioteca entera",
  "Weight loss by tag rarity": "Ponderar la pérdida por rareza de etiqueta",
  "Shuffle tag order": "Mezclar el orden de etiquetas",
  "Caption dropout": "Dropout de descripciones",
  "Generate every": "Generar cada",
  "Negative prompt": "Prompt negativo",
  "Nothing (trigger word only)": "Nada (solo la palabra clave)",
  "Every prompt is the trigger word and nothing else, so every selected picture is in the run whatever it carries. Tag and caption selection do not apply.": "Cada prompt es solo la palabra clave, así que todas las imágenes seleccionadas entran en la ejecución, lleven lo que lleven. La selección de etiquetas y descripciones no se aplica.",
  "Every prompt would be EMPTY — with no text at all, there is nothing for the model to bind what it sees to. Set a trigger word below.": "Cada prompt estaría VACÍO: sin texto alguno, el modelo no tiene nada a lo que vincular lo que ve. Define abajo una palabra clave.",
  "Caption + tags": "Descripción + etiquetas",
  "Pause (saves a checkpoint)": "Pausar (guarda un checkpoint)",
  "{d} trained": "{d} entrenado",
  "Training started": "Entrenamiento iniciado",
  "Training resumed": "Entrenamiento reanudado",
  "Training paused": "Entrenamiento en pausa",
  "Training completed": "Entrenamiento completado",
  "Training failed": "Entrenamiento fallido",
  "Training canceled": "Entrenamiento cancelado",
  "Baseline before training": "Referencia antes de entrenar",
  "Checkpoint": "Checkpoint",
  "Download checkpoint": "Descargar checkpoint",
  "Delete checkpoint": "Eliminar checkpoint",
  "Delete this checkpoint from disk?": "¿Eliminar este checkpoint del disco?",
  "Extend steps": "Ampliar pasos",
  "Edit steps": "Editar pasos",
  "Base model": "Modelo base",
  "LoRAs": "LoRA",
  "Edit this model": "Editar este modelo",
  "Edit model": "Editar modelo",
  "Edit LoRA": "Editar LoRA",
  "Edit this LoRA": "Editar este LoRA",
  "Unlock": "Desbloquear",
  "Lock": "Bloquear",
  "Unlock — deleting the job will take this LoRA with it": "Desbloquear: al eliminar el trabajo este LoRA se irá con él",
  "Lock — keeps this LoRA when the job is deleted": "Bloquear: conserva este LoRA cuando se elimine el trabajo",
  "Lock — protects this checkpoint from deletion, from the keep-last rule, and from the job being deleted": "Bloquear: protege este punto de control del borrado, de la regla de conservar los últimos y de la eliminación del trabajo",
  "Add LoRA": "Añadir LoRA",
  "Click to use this value for the next generation": "Clic para usar este valor en la próxima generación",
  "Output": "Salida",
  "Size presets": "Tamaños predefinidos",
  "Random seed": "Semilla aleatoria",
  "A new seed is drawn each time you click Generate; the field below shows the seed used for the last generation.": "Se sortea una semilla nueva cada vez que pulsas Generar; el campo de abajo muestra la semilla usada en la última generación.",
  "Remove this generation and its images?": "¿Quitar esta generación y sus imágenes?",
  "Open the image in a new tab": "Abrir la imagen en una pestaña nueva",
  "Remove the selected images? They cannot be recovered.": "¿Eliminar las imágenes seleccionadas? No se pueden recuperar.",
  "Remove the selected images (a generation that is still running stays)": "Eliminar las imágenes seleccionadas (una generación en curso se conserva)",
  "Stop the selected generations (the images they have made are kept)": "Detener las generaciones seleccionadas (las imágenes ya creadas se conservan)",
  "Put every setting that made this picture into the form": "Poner en el formulario todos los ajustes que generaron esta imagen",
  "Use all settings": "Usar todos los ajustes",
  "Preview the selected image (Space)": "Vista previa de la imagen seleccionada (Espacio)",
  "Image {i} of {n}": "Imagen {i} de {n}",
  "Up next": "A continuación",
  "Add to the queue": "Añadir a la cola",
  "A training job is running": "Hay un trabajo de entrenamiento en marcha",
  "Drag to change the queue order": "Arrastra para cambiar el orden de la cola",
  "How the drafts below are ordered":
    "Cómo se ordenan los borradores de abajo",
  "Newest first":
    "Más recientes primero",
  "Manual order":
    "Orden manual",
  "Drag to reorder — or into Up next to queue the job":
    "Arrastra para reordenar, o hasta A continuación para poner el trabajo en cola",
  "Remove every finished job, with its checkpoints and samples":
    "Eliminar todos los trabajos terminados, con sus puntos de control y muestras",
  "Drag into Up next to queue the job": "Arrastra a A continuación para poner el trabajo en cola",
  "Drop here to put the job on hold.": "Suelta aquí para dejar el trabajo en espera.",
  "Prepare": "Preparar",
  "Keep the last": "Conservar los últimos",
  "When a new snapshot is written the oldest of these is deleted, so the window never grows. A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk. The resumable checkpoint is kept outside this limit and never counts against it.": "Cuando se escribe una instantánea nueva se borra la más antigua de estas, así que la ventana nunca crece. Una instantánea de LoRA es pequeña (decenas de MB) y puedes conservar cómodamente una docena; una instantánea de finetune completo es del tamaño del modelo entero, así que dos o tres ya son mucho disco. El checkpoint reanudable se conserva fuera de este límite y nunca cuenta contra él.",
  "Also keep one in": "Conservar también uno de cada",
  "A rolling window at the end of the run. 0 keeps none by recency.": "Una ventana rodante al final de la ejecución. 0 no conserva ninguno por recencia.",
  "Kept for good, on top of the window above.": "Conservados para siempre, además de la ventana de arriba.",
  "A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk.": "Una instantánea de LoRA es pequeña (decenas de MB) y puedes conservar cómodamente una docena; una instantánea de finetune completo es del tamaño del modelo entero, así que dos o tres ya son mucho disco.",
  "in 1 step": "en 1 paso",
  "in {n} steps": { one: "en {n} paso", other: "en {n} pasos" },
  "Keep as checkpoint": "Conservar como checkpoint",
  "Backward": "Hacia atrás",
  "warmup": "calentamiento",
  "Settings changed": "Ajustes cambiados",
  "Dataset changed": "Conjunto de datos modificado",
  "{n} items added":
    { one: "{n} elemento añadido", other: "{n} elementos añadidos" },
  "{n} items removed":
    { one: "{n} elemento eliminado", other: "{n} elementos eliminados" },
  "Measured over the last steps of this run": "Medido sobre los últimos pasos de esta ejecución",
  "about {d} left": "quedan unos {d}",
  "The images this run trains on, sorted into aspect-ratio buckets": "Las imágenes con las que entrena esta ejecución, ordenadas en cubos de proporción",
  "{n} images": { one: "{n} imagen", other: "{n} imágenes" },
  "{n} from video": { one: "{n} de vídeo", other: "{n} de vídeo" },
  "{n} buckets": { one: "{n} cubo", other: "{n} cubos" },
  "Training job settings": "Ajustes del trabajo de entrenamiento",
  "Save as new job": "Guardar como trabajo nuevo",
  "Hide system statistics": "Ocultar estadísticas del sistema",
  "Show system statistics": "Mostrar estadísticas del sistema",
  "loading model": "cargando modelo",
  "caching latents": "cacheando latentes",
  "Degradation": "Degradación",
  "Add variant": "Añadir variante",
  "Remove every variant from this job": "Quitar todas las variantes de este trabajo",
  "Remove this variant": "Quitar esta variante",
  "JPEG re-encode": "Recodificación JPEG",
  "Video codec (h264 / h265)": "Códec de vídeo (h264 / h265)",
  "Resolution loss": "Pérdida de resolución",
  "JPEG": "JPEG",
  "video codec": "códec de vídeo",
  "resolution loss": "pérdida de resolución",
  "Chroma subsampling": "Submuestreo de croma",
  "How much color detail is thrown away. 4:2:0 is what almost every real JPEG uses.": "Cuánto detalle de color se desecha. 4:2:0 es lo que usa casi todo JPEG real.",
  "Codec": "Códec",
  "CRF": "CRF",
  "The codec's quality number, counting the other way round: HIGHER is worse. Above about 32 a frame visibly falls apart.": "El número de calidad del códec, contando al revés: MÁS ALTO es peor. Por encima de 32 aproximadamente un fotograma se deshace visiblemente.",
  "Scale": "Escala",
  "Nearest gives the hard, blocky look of a badly upscaled screenshot; bilinear the soft one.": "Vecino más cercano da el aspecto duro y cuadriculado de una captura mal reescalada; bilineal el suave.",
  "Bilinear": "Bilineal",
  "Bicubic": "Bicúbico",
  "Lanczos": "Lanczos",
  "Passes": "Pasadas",
  "Visits per clean visit": "Visitas por visita limpia",
  "How often this variant is drawn beside the picture it was made from. 0.25 = one degraded visit per four clean ones.": "Con qué frecuencia se sortea esta variante junto a la imagen de la que se hizo. 0.25 = una visita degradada por cada cuatro limpias.",
  "Cached variations per picture": "Variaciones cacheadas por imagen",
  "How many separately-drawn values each picture gets. 1 already spreads the range across the dataset; more spreads it within one picture, and multiplies the cache.": "Cuántos valores sorteados por separado recibe cada imagen. 1 ya reparte el rango por el conjunto de datos; más lo reparte dentro de una imagen, y multiplica la caché.",
  "jpeg_artifacts, low_quality": "jpeg_artifacts, low_quality",
  "Always in this sample's prompt: never dropped by the random tag pick, the tag cap, or caption dropout.": "Siempre en el prompt de esta muestra: nunca descartadas por el sorteo aleatorio de etiquetas, el tope de etiquetas ni el dropout de descripciones.",
  "Remove tags if present": "Quitar etiquetas si están presentes",
  "masterpiece, absurdres": "masterpiece, absurdres",
  "Which pictures": "Qué imágenes",
  "Only pictures tagged": "Solo imágenes etiquetadas",
  "Never pictures tagged": "Nunca imágenes etiquetadas",
  "Wins over the line above. Use it to leave pictures alone that are already marked as poor.": "Gana a la línea de arriba. Úsalo para dejar en paz imágenes ya marcadas como pobres.",
  "The preview failed": "La vista previa falló",
  "Select an item in the library to preview this on.": "Selecciona un elemento en la biblioteca sobre el que previsualizar esto.",
  "gentlest": "más suave",
  "harshest": "más duro",
  "Variants": "Variantes",
  "Save the current variants, or load a saved set": "Guardar las variantes actuales, o cargar un conjunto guardado",
  "Save current variants": "Guardar variantes actuales",
  "Add a variant first": "Añade primero una variante",
  "Load this set, replacing the variants in this job": "Cargar este conjunto, reemplazando las variantes de este trabajo",
  "Of every 100 visits to a picture this applies to, {clean} are clean and the rest are degraded: {parts}.": "De cada 100 visitas a una imagen a la que esto aplica, {clean} son limpias y el resto degradadas: {parts}.",
  "A variant with a tag filter applies to fewer pictures than the queries select, so its share is of those.": "Una variante con filtro de etiquetas aplica a menos imágenes de las que las consultas seleccionan, así que su parte es de esas.",
  "About {n} degraded files will be cached.": "Se cachearán unos {n} archivos degradados.",
  "Preset": "Predefinido",
  "Presets": "Predefinidos",
  "Preset name": "Nombre del predefinido",
  "Save these settings as a preset, or load one": "Guardar estos ajustes como predefinido, o cargar uno",
  "Save current settings": "Guardar ajustes actuales",
  "Start new jobs from this preset": "Iniciar trabajos nuevos desde este predefinido",
  "Delete this preset": "Eliminar este predefinido",
  "Cosine": "Coseno",
  "Base models": "Modelos base",
  "1 result": "1 resultado",
  "{n} results": { one: "{n} resultado", other: "{n} resultados" },
  "Delete every result in this session": "Eliminar todos los resultados de esta sesión",
  "Delete all {n} results from this session? The generated images go with them.": "¿Eliminar los {n} resultados de esta sesión? Las imágenes generadas se van con ellos.",
  "sampling": "muestreando",
  "What does this do?": "¿Qué hace esto?",
  "This model's repository is gated: accept its license on the model page and set a Hugging Face access token, or the download will fail.": "El repositorio de este modelo está restringido: acepta su licencia en la página del modelo y configura un token de acceso de Hugging Face, o la descarga fallará.",
  "Click to use this prompt for the next generation": "Clic para usar este prompt en la próxima generación",
  "(no prompt)": "(sin prompt)",
  "Click to use this negative prompt for the next generation": "Clic para usar este prompt negativo en la próxima generación",
  "Time so far, including loading the model": "Tiempo hasta ahora, incluida la carga del modelo",
  "Total time, including loading the model": "Tiempo total, incluida la carga del modelo",
  "Remove from the queue": "Quitar de la cola",
  "Select to copy": "Selecciona para copiar",
  "generation failed": "la generación falló",
  "Library tags autocomplete as you type.": "Las etiquetas de la biblioteca se autocompletan al escribir.",
  "Sampler steps": "Pasos del sampler",
  "CFG scale": "Escala CFG",
  "This model isn't downloaded yet, and downloads are switched off": "Este modelo aún no está descargado, y las descargas están desactivadas",
  "Loss": "Pérdida",
  "LoRA only": "Solo LoRA",
  "Native training resolution of these weights. Leave empty for the architecture's own.": "Resolución nativa de entrenamiento de estos pesos. Vacío usa la propia de la arquitectura.",
  "Includes 1 model you added.": "Incluye 1 modelo que añadiste.",
  "Includes": "Incluye",
  "models you added.": "modelos que añadiste.",
  "Open this model's page on Hugging Face": "Abrir la página de este modelo en Hugging Face",
  "Remove this model": "Quitar este modelo",
  "Based on": "Basado en",
  "/path/to/model (diffusers folder or .safetensors)": "/path/to/model (diffusers folder or .safetensors)",
  "owner/repo": "owner/repo",
  "Add model": "Añadir modelo",
  "On disk": "En disco",
  "Path missing": "Ruta ausente",
  "Continue this download where it stopped": "Continuar esta descarga donde se detuvo",
  "Partly downloaded": "Parcialmente descargado",
  "Discard partial download": "Descartar descarga parcial",
  "This path no longer exists": "Esta ruta ya no existe",
  "Remove from the list (the file is left alone)": "Quitar de la lista (el archivo se deja en paz)",
  "The base model this LoRA was trained for": "El modelo base para el que se entrenó este LoRA",
  "/path/to/lora.safetensors": "/path/to/lora.safetensors",
  "Download this checkpoint": "Descargar este checkpoint",
  "Delete this checkpoint from disk": "Eliminar este checkpoint del disco",
  "Relative sampling probability: a weight-2 query's images are drawn twice as often as a weight-1 query's.": "Probabilidad de muestreo relativa: las imágenes de una consulta de peso 2 se sortean el doble de veces que las de una de peso 1.",
  "Steps": "Pasos",
  "Text encoder": "Codificador de texto",
  "trained": "entrenado",
  "Prompts": "Prompts",
  "Samples": "Muestras",
  "Training log": "Registro de entrenamiento",
  "No output yet.": "Aún sin salida.",
  "about {v} of GPU memory": "unos {v} de memoria de GPU",
  "more than this machine's {m}": "más que los {m} de esta máquina",
  "e.g. watercolor style LoRA": "p. ej. LoRA de estilo acuarela",
  "Model-specific": "Específico del modelo",
  "Optimization": "Optimización",
  "LR schedule": "Programación de LR",
  "Constant": "Constante",
  "Linear decay": "Decaimiento lineal",
  "Constant + warmup": "Constante + calentamiento",
  "Warmup steps": "Pasos de calentamiento",
  "Ramp the learning rate up over the first N steps. Leave empty for no warmup.": "Sube la tasa de aprendizaje en rampa durante los primeros N pasos. Vacío = sin calentamiento.",
  "bf16 is the safe modern default. fp32 doubles memory (automatic fallback on Macs without bf16); avoid fp16 for training.": "bf16 es el valor por defecto moderno y seguro. fp32 duplica la memoria (respaldo automático en Macs sin bf16); evita fp16 para entrenar.",
  "Makes sampling, crops and tag picks reproducible.": "Hace reproducibles el muestreo, los recortes y los sorteos de etiquetas.",
  "LoRA": "LoRA",
  "Scales the adapter's effect; the common convention is alpha = rank. Lower alpha = weaker influence at the same rank.": "Escala el efecto del adaptador; la convención común es alpha = rango. Alpha más bajo = influencia más débil al mismo rango.",
  "Helps the model learn a NEW trigger word, at higher overfitting risk. Guarded: it uses a lower learning rate and stops partway through training.": "Ayuda al modelo a aprender una palabra desencadenante NUEVA, con mayor riesgo de sobreajuste. Protegido: usa una tasa de aprendizaje menor y se detiene a mitad del entrenamiento.",
  "Text encoder LR": "LR del codificador de texto",
  "Left empty: half the main learning rate.": "Vacío: la mitad de la tasa principal.",
  "Stop TE after": "Detener el TE tras",
  "Include the large encoder": "Incluir el codificador grande",
  "T5-XXL, the encoder that reads the whole prompt — most of the memory and most of the effect. Unticked, only the small CLIP-L trains: cheap, and what most FLUX LoRA tools mean by training the text encoder.": "T5-XXL, el codificador que lee todo el prompt: la mayor parte de la memoria y del efecto. Desmarcado, solo se entrena el pequeño CLIP-L: barato, y lo que la mayoría de herramientas de LoRA para FLUX entienden por entrenar el codificador de texto.",
  "of total steps": "de los pasos totales",
  "Keep step snapshots": "Conservar instantáneas de paso",
  "Save a permanent snapshot every N steps, so the best-looking step can be picked afterwards. Off: only the resumable 'last' checkpoint is kept.": "Guarda una instantánea permanente cada N pasos, para poder elegir después el paso que mejor se vea. Desactivado: solo se conserva el checkpoint reanudable 'last'.",
  "Gradient checkpointing": "Checkpointing de gradiente",
  "Trades ~25% speed for a large VRAM saving. Recommended for full finetunes and big models.": "Cambia ~25% de velocidad por un gran ahorro de VRAM. Recomendado para finetunes completos y modelos grandes.",
  "Attention slicing": "Troceado de atención",
  "Half-precision master weights": "Pesos maestros en media precisión",
  "Keeps the trained weights and their gradients at 16 bits instead of 32. What the rounding drops is carried to the next update, so the run learns what it would have learned; the cost is one more buffer of the same width.":
    "Guarda los pesos entrenados y sus gradientes en 16 bits en lugar de 32. Lo que el redondeo descarta se arrastra a la siguiente actualización, así que el entrenamiento aprende lo que habría aprendido; el coste es un búfer más del mismo ancho.",
  "only for a full finetune": "solo para un ajuste completo",
  "nothing to halve at full precision": "no hay nada que reducir a la mitad en precisión completa",
  "Prodigy cannot be stepped one weight at a time": "Prodigy no puede ejecutarse peso a peso",
  "Base model quantization": "Cuantización del modelo base",
  "None (full precision)": "Ninguna (precisión completa)",
  "4-bit (NF4)": "4 bits (NF4)",
  "Optimizer": "Optimizador",
  "Images are sorted into width/height buckets of equal area so nothing gets squashed. This caps how extreme the buckets get (2 = up to 2:1 and 1:2).": "Las imágenes se ordenan en cubos de ancho/alto de igual área para que nada se aplaste. Esto limita lo extremos que llegan a ser los cubos (2 = hasta 2:1 y 1:2).",
  "Never flip images whose tags are marked": "Nunca voltear imágenes con etiquetas marcadas",
  "Comma-separated META tags. Any tag the library marks with one of these switches mirroring off for the pictures carrying that tag — so the rule is stated once in the Tags tab rather than listed here.": "Metaetiquetas separadas por comas. Cualquier etiqueta que la biblioteca marque así desactiva el volteo en las imágenes que la llevan, de modo que la regla se enuncia una vez en la pestaña Etiquetas en lugar de listarse aquí.",
  "Always include tags marked": "Incluir siempre las etiquetas marcadas",
  "Comma-separated META tags. Any tag the library marks with one of these is never dropped by the random pick — again, only where the image actually has that tag.": "Metaetiquetas separadas por comas. Cualquier etiqueta que la biblioteca marque así nunca la descarta la selección aleatoria; de nuevo, solo donde la imagen realmente tiene esa etiqueta.",
  "Exclude tags marked": "Excluir las etiquetas marcadas",
  "Comma-separated META tags. Any tag the library marks with one of these is stripped from prompts.": "Metaetiquetas separadas por comas. Cualquier etiqueta que la biblioteca marque así se elimina de los prompts.",
  "Remove tags marked": "Quitar las etiquetas marcadas",
  "Comma-separated META tags. Any tag the library marks with one of these comes off this sample.": "Metaetiquetas separadas por comas. Cualquier etiqueta que la biblioteca marque así se quita de esta muestra.",
  "Only pictures whose tags are marked": "Solo imágenes con etiquetas marcadas",
  "Comma-separated META tags — the same rule as the line above, said once in the library rather than tag by tag here.": "Metaetiquetas separadas por comas: la misma regla que la línea anterior, dicha una vez en la biblioteca en lugar de etiqueta por etiqueta aquí.",
  "Never pictures whose tags are marked": "Nunca imágenes con etiquetas marcadas",
  "Comma-separated META tags. Wins over both lines above.": "Metaetiquetas separadas por comas. Prevalece sobre ambas líneas anteriores.",
  "The same veto, said once in the library instead of tag by tag here. Any tag the Tags tab marks with one of these meta tags switches mirroring off for every picture carrying that tag.\n\nIt is worth the indirection for the reason a list of names goes stale: “text”, “logo”, “signature”, “left-handed”, a dozen characters with an eyepatch — the list in a job's settings is right the day it is written and wrong the next time somebody adds a tag it should have held. Marking the tags themselves puts the fact where the tag is, so a tag added later carries it into every run automatically, and a job written before that tag existed still does the right thing.\n\nBoth lists apply: a picture is left unmirrored if it carries a tag named above OR a tag marked here.":
    "El mismo veto, dicho una vez en la biblioteca en lugar de etiqueta por etiqueta aquí. Cualquier etiqueta que la pestaña Etiquetas marque con una de estas metaetiquetas desactiva el volteo en todas las imágenes que la llevan.\n\nEl rodeo compensa por la razón por la que una lista de nombres se queda obsoleta: «text», «logo», «signature», «left-handed», una docena de personajes con un parche en el ojo — la lista en los ajustes de un trabajo es correcta el día en que se escribe y deja de serlo la próxima vez que alguien añade una etiqueta que debería haber contenido. Marcar las propias etiquetas pone el hecho donde está la etiqueta: una etiqueta añadida después lo lleva sola a cada ejecución, y un trabajo escrito antes de que esa etiqueta existiera sigue haciendo lo correcto.\n\nSe aplican ambas listas: una imagen queda sin voltear si lleva una etiqueta nombrada arriba O una etiqueta marcada aquí.",
  "The rule above, named by what the library says ABOUT a tag rather than by the tag. Any tag marked with one of these meta tags bypasses the random pick — again only where the image actually has it.\n\nA meta tag put on “watermark”, “signature” and “logo” once means every run treats them that way, including runs written before the third of them existed. The two lists are unioned, so naming a tag here and above is simply the same instruction twice.":
    "La regla de arriba, nombrada por lo que la biblioteca dice SOBRE una etiqueta en lugar de por la etiqueta. Cualquier etiqueta marcada con una de estas metaetiquetas se salta la selección aleatoria; de nuevo, solo donde la imagen realmente la tiene.\n\nUna metaetiqueta puesta una vez en «watermark», «signature» y «logo» significa que toda ejecución las trata así, incluidas las escritas antes de que existiera la tercera. Las dos listas se unen, así que nombrar una etiqueta aquí y arriba es simplemente la misma instrucción dos veces.",
  "The same, one level up: any tag the library marks with one of these meta tags is stripped from every prompt.\n\nThis is the one to reach for when the exclusions are a KIND of tag rather than a list of them. Quality ratings, scan notes, the booru's own housekeeping words — mark them “noprompt” in the Tags tab and every run drops them, instead of every job carrying a list that has to grow with the vocabulary.\n\nIt is not the same as a skipped tag GROUP below. This one is about the tag wherever it appears; that one is about a grouping on one item, and a tag placed in an excluded group and also somewhere else survives it.":
    "Lo mismo un nivel más arriba: cualquier etiqueta que la biblioteca marque con una de estas metaetiquetas se elimina de todos los prompts.\n\nEs a lo que hay que recurrir cuando las exclusiones son un TIPO de etiqueta y no una lista de ellas. Valoraciones de calidad, notas de escaneo, las palabras internas de un booru: márcalas como «noprompt» en la pestaña Etiquetas y toda ejecución las descarta, en lugar de que cada trabajo lleve una lista que tenga que crecer con el vocabulario.\n\nNo es lo mismo que un GRUPO de etiquetas omitido más abajo. Esto trata de la etiqueta dondequiera que aparezca; aquello, de una agrupación en un elemento, y una etiqueta puesta en un grupo excluido y también en otro sitio sobrevive.",
  "The list above, named by what the library says about a tag. Any tag marked with one of these meta tags comes off this sample.\n\nWhat it is for is that the claims a degraded copy no longer supports are a CATEGORY, not a list: 'masterpiece', 'absurdres', 'high quality', 'official art' and whatever the next dump adds are all \"a claim about the picture's quality\". Marking them once means every variant of every job drops them, and the same mark can then say something different per method — a 'resolution_claim' mark belongs on a resize variant's list, a 'fidelity_claim' on a JPEG one.":
    "La lista de arriba, nombrada por lo que la biblioteca dice sobre una etiqueta. Cualquier etiqueta marcada con una de estas metaetiquetas se quita de esta muestra.\n\nPara lo que sirve: las afirmaciones que una copia degradada ya no sostiene son una CATEGORÍA, no una lista. «masterpiece», «absurdres», «high quality», «official art» y lo que añada el próximo volcado son todas «una afirmación sobre la calidad de la imagen». Marcarlas una vez hace que toda variante de todo trabajo las descarte, y la misma marca puede decir algo distinto según el método: una marca «resolution_claim» pertenece a la lista de una variante de reescalado, y una «fidelity_claim» a la de una de JPEG.",
  "The line above by mark rather than by name: a picture is degraded only if it carries a tag the library marks this way.\n\nChecked against the picture's effective tags, so a tag it only carries by implication counts too. With both lists empty, every picture is fair game.":
    "La línea de arriba por marca y no por nombre: una imagen se degrada solo si lleva una etiqueta que la biblioteca marca de esta forma.\n\nSe comprueba contra las etiquetas efectivas de la imagen, así que una etiqueta que solo lleva por implicación también cuenta. Con ambas listas vacías, toda imagen es candidata.",
  "The veto by mark, and it wins over both lines above exactly as the named list does.\n\nThe pair is what makes a degrading run safe on a mixed library: mark the pictures that are already poor — a 'low_quality' or 'rescan' mark on the tags that say so — and no variant can ever degrade one of them further, however broadly the \"only pictures\" side is drawn.":
    "El veto por marca, y prevalece sobre las dos líneas de arriba exactamente como lo hace la lista por nombre.\n\nEl par es lo que hace segura una ejecución degradante en una biblioteca mixta: marca las imágenes que ya son pobres — un «low_quality» o «rescan» en las etiquetas que lo dicen — y ninguna variante podrá degradar más una de ellas, por muy amplio que sea el lado de «solo imágenes».",
  "Never flip images tagged": "Nunca voltear imágenes etiquetadas",
  "Comma-separated tags that switch mirroring off for the images carrying them, e.g. 'text'. Everything else still flips.": "Etiquetas separadas por comas que desactivan el reflejo para las imágenes que las llevan, p. ej. 'text'. Todo lo demás sigue volteándose.",
  "Use alpha as a loss mask": "Usar el alfa como máscara de pérdida",
  "For cut-out images (transparent background): train on the visible pixels and largely ignore the rest. Images without transparency are unaffected.": "Para imágenes recortadas (fondo transparente): entrena con los píxeles visibles e ignora en gran medida el resto. Las imágenes sin transparencia no se ven afectadas.",
  "Background weight": "Peso del fondo",
  "Build prompts from": "Construir prompts a partir de",
  "What each training prompt is made of: the item's caption text, its tags, caption followed by tags, or nothing but the trigger word.": "De qué se compone cada prompt de entrenamiento: la descripción del elemento, sus etiquetas, descripción seguida de etiquetas, o nada más que la palabra clave.",
  "Prepended to every prompt. Use a rare token (e.g. 'ohwx style') you'll later type to invoke the trained concept.": "Antepuesto a cada prompt. Usa un token raro (p. ej. 'ohwx style') que escribirás después para invocar el concepto entrenado.",
  "Each image trains as the RESULT of one of its instructions, with that instruction's reference images as the input. Items carrying no instruction are left out of the run, and tag selection does not apply.": "Cada imagen entrena como el RESULTADO de una de sus instrucciones, con las imágenes de referencia de esa instrucción como entrada. Los elementos sin instrucción quedan fuera de la ejecución, y la selección de etiquetas no aplica.",
  "Tag selection": "Selección de etiquetas",
  "Tags are re-picked and re-shuffled fresh every time an image is visited.": "Las etiquetas se re-sortean y re-mezclan de nuevo cada vez que se visita una imagen.",
  "Comma-separated tags stripped from prompts (e.g. quality tags or the concept itself when using a trigger word).": "Etiquetas separadas por comas quitadas de los prompts (p. ej. etiquetas de calidad o el propio concepto cuando se usa una palabra desencadenante).",
  "no limit": "sin límite",
  "Lower bound of the random pick. Both limits empty = use all tags.": "Límite inferior del sorteo aleatorio. Ambos límites vacíos = usar todas las etiquetas.",
  "Upper bound of the random pick. Picking a random subset each visit teaches tags independently instead of as a fixed clump.": "Límite superior del sorteo aleatorio. Elegir un subconjunto aleatorio en cada visita enseña las etiquetas de forma independiente en vez de como un bloque fijo.",
  "Whether a tag's rarity is measured within the selected training images or across the whole library.": "Si la rareza de una etiqueta se mide dentro de las imágenes de entrenamiento seleccionadas o en toda la biblioteca.",
  "Skip partially matching tags": "Omitir etiquetas parcialmente coincidentes",
  "Standard practice: prevents the model from binding concepts to a fixed tag position.": "Práctica estándar: evita que el modelo ate conceptos a una posición fija de etiqueta.",
  "Underscores to spaces": "Guiones bajos a espacios",
  "Tag separator": "Separador de etiquetas",
  "Joins the prompt parts; comma + space is the standard.": "Une las partes del prompt; coma + espacio es el estándar.",
  "Generate preview images with the in-training model to watch progress in the job's timeline.": "Genera imágenes de vista previa con el modelo en entrenamiento para seguir el progreso en la línea de tiempo del trabajo.",
  "Generate test samples": "Generar muestras de prueba",
  "Sample seed": "Semilla de muestras",
  "Fixed per prompt so consecutive samples differ only by training progress.": "Fija por prompt para que las muestras consecutivas difieran solo por el progreso del entrenamiento.",
  "Test prompts": "Prompts de prueba",
  "negative prompt (optional)": "prompt negativo (opcional)",
  "Use the shared size for this prompt": "Usar el tamaño compartido para este prompt",
  "Give this prompt its own size": "Dar a este prompt su propio tamaño",
  "Remove this prompt": "Quitar este prompt",
  "Add prompt": "Añadir prompt",
  "Remove every prompt from this job": "Quitar todos los prompts de este trabajo",
  "Remove all": "Quitar todo",
  "Save the current prompts, or load a saved set": "Guardar los prompts actuales, o cargar un conjunto guardado",
  "Write a prompt first": "Escribe primero un prompt",
  "Save current prompts": "Guardar prompts actuales",
  "Set name": "Nombre del conjunto",
  "Load this set into the job": "Cargar este conjunto en el trabajo",
  "Delete this set": "Eliminar este conjunto",
  "train from scratch": "entrenar desde cero",
  "Finished result": "Resultado final",
  "Intermediate checkpoint": "Checkpoint intermedio",
  "Continues": "Continúa",
  "Train on video frames": "Entrenar con fotogramas de vídeo",
  "Off, a video the queries match is skipped. On, its frames are extracted while the dataset is built, trained on as images, and deleted with the run.": "Desactivado, un vídeo que las consultas encuentren se omite. Activado, sus fotogramas se extraen al construir el conjunto de datos, se entrena con ellos como imágenes, y se borran con la ejecución.",
  "One frame every": "Un fotograma cada",
  "Interval unit": "Unidad del intervalo",
  "Seconds follows the clock whatever the frame rate; frames counts the file's own frames.": "Segundos sigue el reloj sea cual sea la tasa de fotogramas; fotogramas cuenta los del propio archivo.",
  "Drop repeated frames": "Descartar fotogramas repetidos",
  "A shot held for five seconds is one picture, not five. Each kept frame is compared with the ones already kept from the same video.": "Un plano sostenido cinco segundos es una imagen, no cinco. Cada fotograma conservado se compara con los ya conservados del mismo vídeo.",
  "Label each block with": "Etiquetar cada bloque con",
  "The subjects it is about": "Los sujetos de los que trata",
  "The tag group's name": "El nombre del grupo de etiquetas",
  "Between groups": "Entre grupos",
  "Group tags by tag group": "Agrupar etiquetas por grupo de etiquetas",
  "Lay the picked tags out one block per tag group instead of one flat list, so what belongs to the same thing in the picture stays together.": "Dispón las etiquetas elegidas en un bloque por grupo de etiquetas en vez de una lista plana, para que lo que pertenece a la misma cosa de la imagen quede junto.",
  "Put between blocks. A newline by default, which is what makes them read as separate statements.": "Puesto entre bloques. Un salto de línea por defecto, que es lo que hace que se lean como enunciados separados.",
  "Includes {n} models you added.": { one: "Incluye {n} modelo que añadiste.", other: "Incluye {n} modelos que añadiste." },
  // The job list's selection bar.
  "Remove {n} training jobs? Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone.":
    "¿Eliminar {n} trabajos de entrenamiento? Se eliminan con ellos sus puntos de control, muestras y resultados entrenados, y esto no se puede deshacer. Salvo lo que esté bloqueado, que se conserva en la lista de LoRAs.",
  "Remove the selected jobs — a running job is left alone":
    "Eliminar los trabajos seleccionados — uno en ejecución se deja intacto",
  "Remove the selected jobs, with their checkpoints and samples":
    "Eliminar los trabajos seleccionados, con sus puntos de control y muestras",
  // The Models page: adding a model, and removing one.
  "Remove “{name}” from the model list?":
    "¿Quitar «{name}» de la lista de modelos?",
  "Delete the downloaded weights as well? They can be downloaded again later.":
    "¿Borrar también los pesos descargados? Se pueden volver a descargar más tarde.",
  "Which model these weights are a version of — it decides the engine, the hyperparameters and the memory profile":
    "De qué modelo son una versión estos pesos — decide el motor, los hiperparámetros y el perfil de memoria",
  "owner/repo, or a path on this machine":
    "owner/repo, o una ruta en esta máquina",
  "A Hugging Face repository, or a diffusers folder or .safetensors file on this machine — which one it is is read off what you type.":
    "Un repositorio de Hugging Face, o una carpeta diffusers o un archivo .safetensors en esta máquina — cuál de los dos es se deduce de lo que escribas.",
  "Read as a path on this machine":
    "Leído como una ruta en esta máquina",
  "Read as a Hugging Face repository":
    "Leído como un repositorio de Hugging Face",
  "Left unnamed, the model is listed under its repository or path":
    "Sin nombre, el modelo aparece bajo su repositorio o ruta",
  // The Models page's LoRA lists, grouped by architecture.
  "No LoRAs yet — add a file above, or finish a training job.":
    "Aún no hay LoRAs — añade un archivo arriba o termina un entrenamiento.",
  "These work on any model of this architecture. Each row says which one it was trained for.":
    "Funcionan con cualquier modelo de esta arquitectura. Cada fila dice para cuál se entrenó.",
  // The Evaluate tab: the LoRA rows, and the results grid.
  "Strength":
    "Intensidad",
  "no image":
    "sin imagen",
  "Weights": "Pesos",
  "File": "Archivo",
  "Trained for": "Entrenado para",
  "defaults to the file name": "por defecto, el nombre del archivo",
  "Waiting…": "Esperando…",
  "Another download is running": "Hay otra descarga en curso",
  "macOS keeps GPU temperature and power for root only. To see them here, allow this one command without a password, then press Try again:":
    "macOS reserva la temperatura y la potencia de la GPU solo para root. Para verlas aquí, permite este único comando sin contraseña y pulsa «Volver a intentarlo»:",
  "Check again — no restart needed once the rule is in":
    "Volver a comprobar: una vez añadida la regla no hace falta reiniciar",
  "Copied": "Copiado",
  "Press ⌘C to copy it": "Pulsa ⌘C para copiarlo",
  "Write tags as an alias": "Escribir etiquetas como un alias",
  "Chance of writing a picked tag as one of its aliases instead of its own name, rolled per tag every time an image is visited.":
    "Probabilidad de escribir una etiqueta elegida con uno de sus alias en lugar de su propio nombre, sorteada por etiqueta cada vez que se visita una imagen.",
  "Your library's aliases are the other words for one thing — “cat”, “kitty”, “feline”. Assigning any of them stores the canonical name, so every prompt says the same word and the model learns to answer to that word alone; at generation time the others do less, or nothing.\n\nWith this above 0, each picked tag is sometimes written as one of its aliases instead. The roll happens per tag per visit, so one image seen twice reads differently and the whole vocabulary is spread across the run rather than one alias being chosen per tag and then repeated.\n\nOnly the PROMPT changes. Tag matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all keep using the canonical name — so this cannot skew any of them. A tag with no aliases is always written as itself, and 0 is exactly what every run did before this setting existed.":
    "Los alias de tu biblioteca son las otras palabras para una misma cosa: «cat», «kitty», «feline». Al asignar cualquiera de ellos se guarda el nombre canónico, así que todos los prompts dicen la misma palabra y el modelo aprende a responder solo a esa; al generar, las demás hacen poco o nada.\n\nPor encima de 0, cada etiqueta elegida se escribe a veces con uno de sus alias. El sorteo es por etiqueta y por visita, de modo que una imagen vista dos veces se lee distinta y todo el vocabulario se reparte a lo largo del entrenamiento en vez de elegir un alias por etiqueta y repetirlo.\n\nSolo cambia el PROMPT. La coincidencia de etiquetas, las listas de siempre/excluir, el equilibrado por frecuencia, el peso de la pérdida y los recuadros que un recorte debe conservar siguen usando el nombre canónico, así que esto no puede sesgar nada. Una etiqueta sin alias siempre se escribe tal cual, y 0 es exactamente lo que hacía cada entrenamiento antes de que existiera esta opción.",
  "Whether a tag's rarity is measured within the selected training images, across the whole library, or across the whole library plus what each tag has elsewhere.":
    "Si la rareza de una etiqueta se mide dentro de las imágenes de entrenamiento seleccionadas, en toda la biblioteca, o en toda la biblioteca más lo que cada etiqueta tiene en otros sitios.",
  "Rarity is relative to some population, and this picks which one.\n\n“Training data” counts only the images this job selected, so balancing works within the set you are actually training on — usually what you want. “Whole library” counts every item you own, which makes a tag that is common in your dataset but rare overall still count as rare. That is occasionally useful when the training set is a deliberate slice of a much larger, differently balanced collection.\n\n“Whole library + count offsets” adds each tag’s highest meta-tag count — the pictures it has somewhere this library is not, counted per site on the tag’s meta tags (“tumblr 50”, “twitter 100”), of which the largest single figure is used, never the sum, since the sites count overlapping pictures. Nowhere else in the app is that number added to a count, because a total including it would be a claim about somewhere else; for BALANCING it is often the honest one. A tag with four pictures here and forty thousand where they came from is not a rare word, and treating it as rare spends the run teaching the model something it already knows.":
    "La rareza siempre es relativa a una población, y aquí se elige cuál.\n\n«Datos de entrenamiento» cuenta solo las imágenes que este trabajo seleccionó, así que el equilibrado actúa dentro del conjunto con el que realmente entrenas: casi siempre lo que quieres. «Toda la biblioteca» cuenta todo lo que tienes, de modo que una etiqueta frecuente en tu conjunto pero rara en general sigue contando como rara. Es útil de vez en cuando, cuando el conjunto de entrenamiento es una porción deliberada de una colección mucho mayor y distinta.\n\n«Toda la biblioteca + recuentos externos» añade el mayor recuento por metaetiqueta de cada etiqueta: las imágenes que tiene en algún lugar donde esta biblioteca no está, contadas por sitio en sus metaetiquetas («tumblr 50», «twitter 100»); se usa la mayor cifra individual, nunca la suma, porque los sitios cuentan imágenes que se solapan. En ningún otro sitio de la app se suma ese número a un recuento, porque un total que lo incluyera sería una afirmación sobre otro lugar; para EQUILIBRAR suele ser el honesto. Una etiqueta con cuatro imágenes aquí y cuarenta mil de donde vinieron no es una palabra rara, y tratarla como tal gasta el entrenamiento enseñando al modelo algo que ya sabe.",
  "Caption selection": "Selección de descripciones",
  "Instruction selection": "Selección de instrucciones",
  "Start now — pauses the running job and puts this one first":
    "Iniciar ahora: pausa el trabajo en curso y pone este primero",
  "Start now — puts this job first and starts the queue":
    "Iniciar ahora: pone este trabajo primero e inicia la cola",
  "Save as duplicate":
    "Guardar como duplicado",
  "Batch & seed": "Lote y semilla",
  "Device": "Dispositivo",
  "Precision & quantization": "Precisión y cuantización",
  "Memory savers": "Ahorro de memoria",
  "Training images": "Imágenes de entrenamiento",
  "Length measured in":
    "Duración medida en",
  "Steps are a fixed amount of work; epochs are full passes over your images, so the run grows with the dataset.":
    "Los pasos son una cantidad fija de trabajo; las épocas son pasadas completas por tus imágenes, así que el entrenamiento crece con el conjunto.",
  "A STEP is one batch pushed through the model and one update of the weights — a fixed amount of work whatever the dataset holds. An EPOCH is one pass over every training image, so the same number means a longer run on a bigger set and the model sees each picture the same number of times either way.\n\nEpochs are usually the easier thing to reason about: “each image about ten times” transfers between datasets, where “3000 steps” does not. The exact step count is worked out when the run starts, because only then is it known how many entries the dataset has — a film contributes its frames, a degraded copy is an extra sample, and an item can contribute one per caption.":
    "Un PASO es un lote empujado por el modelo y una actualización de los pesos: una cantidad fija de trabajo, tenga lo que tenga el conjunto. Una ÉPOCA es una pasada por cada imagen de entrenamiento, así que el mismo número supone un entrenamiento más largo en un conjunto mayor, y el modelo ve cada imagen las mismas veces en ambos casos.\n\nLas épocas suelen ser más fáciles de razonar: «cada imagen unas diez veces» se traslada entre conjuntos, «3000 pasos» no. El número exacto de pasos se calcula al iniciar el entrenamiento, porque solo entonces se sabe cuántas entradas tiene el conjunto: un vídeo aporta sus fotogramas, una copia degradada es una muestra más, y un elemento puede aportar una entrada por descripción.",
  "Epochs":
    "Épocas",
  "Full passes over the dataset. The exact step count is worked out when the run starts and shown in its log.":
    "Pasadas completas por el conjunto. El número exacto de pasos se calcula al iniciar el entrenamiento y aparece en su registro.",
  "How many times the run works through every training image. Each pass visits every entry exactly once, in a fresh random order.\n\nWhat counts as an entry is the dataset after it has been built, not the number of pictures you selected: a video contributes one entry per kept frame, a degradation variant adds an extra sample beside the clean picture, and with “every caption” an item contributes one entry per caption. That is why the step count appears when the run starts rather than here.":
    "Cuántas veces el entrenamiento recorre todas las imágenes. Cada pasada visita cada entrada exactamente una vez, en un orden aleatorio nuevo.\n\nLo que cuenta como entrada es el conjunto ya construido, no el número de imágenes que seleccionaste: un vídeo aporta una entrada por fotograma conservado, una variante de degradación añade una muestra junto a la imagen limpia, y con «cada descripción» un elemento aporta una entrada por descripción. Por eso el número de pasos aparece al iniciar y no aquí.",
  "Query weight":
    "Peso de la consulta",
  "A weight buys":
    "Un peso compra",
  "Whether a heavier query's images are seen more often, or seen the same and counted for more.":
    "Si las imágenes de una consulta con más peso se ven más a menudo, o se ven igual y cuentan más.",
  "Both spend the same ratio; they differ in what they spend it on.\n\nSEEN MORE OFTEN is the classic behaviour: a weight-2 query's pictures get twice the visits, which means they take those visits from the rest — a fixed-length run spends more of itself on them and less on everything else.\n\nCOUNTED FOR MORE gives every picture the same number of visits and multiplies the weighted ones' effect on the weights instead. Nothing loses coverage; the emphasis comes out of the gradient rather than out of the other images' training time. It is the better default when the queries are different KINDS of picture rather than different amounts of importance.":
    "Ambas gastan la misma proporción; se diferencian en en qué la gastan.\n\nVERLAS MÁS A MENUDO es el comportamiento clásico: las imágenes de una consulta con peso 2 reciben el doble de visitas, y esas visitas se las quitan al resto — un entrenamiento de duración fija gasta más de sí en ellas y menos en todo lo demás.\n\nQUE CUENTEN MÁS da a cada imagen el mismo número de visitas y multiplica en su lugar el efecto de las ponderadas sobre los pesos. Nada pierde cobertura; el énfasis sale del gradiente y no del tiempo de entrenamiento de las demás imágenes. Es la mejor opción por defecto cuando las consultas son TIPOS distintos de imagen y no grados distintos de importancia.",
  "Seen more often":
    "Verlas más a menudo",
  "Counted for more":
    "Que cuenten más",
  "An item with several captions":
    "Un elemento con varias descripciones",
  "Whether every caption is used each pass, or one is drawn per visit.":
    "Si cada descripción se usa en cada pasada, o se saca una por visita.",
  "Items often carry more than one caption — a short one and a long one, a translation, a machine draft somebody approved.\n\nONE AT RANDOM gives the item a single visit each pass and draws a different caption each time, so the whole set is seen across a long run and an item counts once however many ways it has been described.\n\nEVERY CAPTION gives it one visit per caption, so all of them are used every pass — and an item with ten is therefore seen ten times, which is usually an accident of tooling rather than a claim that the picture matters ten times as much.\n\nEVERY CAPTION, SHARED is that with the accident removed: each caption still gets its visit, and together they carry one item's worth of gradient.":
    "Los elementos suelen llevar más de una descripción: una corta y una larga, una traducción, un borrador automático que alguien aprobó.\n\nUNA AL AZAR da al elemento una sola visita por pasada y saca una descripción distinta cada vez, así que a lo largo de un entrenamiento largo se ven todas, y el elemento cuenta una vez por muchas formas en que se le haya descrito.\n\nCADA DESCRIPCIÓN le da una visita por descripción, así que todas se usan en cada pasada — y un elemento con diez se ve entonces diez veces, lo que suele ser un accidente de las herramientas y no una afirmación de que esa imagen importe diez veces más.\n\nCADA DESCRIPCIÓN, COMPARTIENDO es lo mismo sin ese accidente: cada descripción conserva su visita y entre todas llevan el gradiente de un solo elemento.",
  "One at random each visit":
    "Una al azar en cada visita",
  "Every caption, once each":
    "Cada descripción, una vez",
  "Every caption, sharing one item's weight":
    "Cada descripción, compartiendo el peso de un elemento",
  "Unsupported":
    "No compatible",
  "not available on Apple silicon":
    "no disponible en Apple silicon",
  "not used on Apple silicon, where the run trains in fp32":
    "no se usa en Apple silicon, donde el entrenamiento va en fp32",
  "a full finetune trains the base weights, so there is nothing to quantize":
    "un finetuning completo entrena los pesos base, así que no hay nada que cuantizar",
  "only offered for LoRA training":
    "solo se ofrece para el entrenamiento LoRA",
  "too large to finetune on any GPU this app has constants for":
    "demasiado grande para un finetuning en cualquier GPU para la que esta app tiene constantes",
  "Another picture": "Otra imagen",
  "{n} jobs selected. One at a time shows its progress, samples and settings.":
    "{n} trabajos seleccionados. El progreso, las imágenes de prueba y los ajustes se ven de uno en uno.",
  "original":
    "original",
  "Show this at full size":
    "Ver a tamaño completo",
  "Each snapshot is about {size}.":
    "Cada instantánea ocupa unos {size}.",
  "Cadence measured in":
    "Frecuencia medida en",
  "How often a snapshot is written: after a fixed number of steps, or after a number of full passes over the dataset.":
    "Con qué frecuencia se escribe una instantánea: tras un número fijo de pasos, o tras un número de pasadas completas por el conjunto.",
  "How often a round of samples is rendered: after a fixed number of steps, or after a number of full passes over the dataset.": "Con qué frecuencia se genera una ronda de muestras: tras un número fijo de pasos, o tras un número de pasadas completas sobre el conjunto de datos.",
  "Rendered after this many full passes. The equivalent step count appears in the job's log when the run starts.": "Se genera tras este número de pasadas completas. El número de pasos equivalente aparece en el registro del trabajo al arrancar.",
  "A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 250 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both. It is the choice the checkpoint cadence and the run’s own length already offer, and setting all three the same way is what makes a sample, its checkpoint and a pass over your pictures line up in the timeline.\n\nHow many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has — a film’s frames, a degraded copy and an item contributing one entry per caption all count.": "Un paso es una cantidad fija de trabajo y una época es una pasada sobre cada imagen de entrenamiento, así que las dos cadencias se separan a medida que crece el conjunto de datos — «cada 250 pasos» es casi todo un entrenamiento pequeño y una fracción de uno grande, mientras que «cada época» significa lo mismo en ambos. Es la misma elección que ya ofrecen la cadencia de los puntos de control y la duración del entrenamiento, y ajustar las tres igual es lo que alinea una muestra, su punto de control y una pasada sobre tus imágenes en la línea de tiempo.\n\nCuántos pasos dura una época se calcula al arrancar, porque solo el conjunto de datos ya construido sabe cuántas entradas tiene — los fotogramas de un vídeo, una copia degradada y un elemento que aporta una entrada por descripción cuentan todos.",
  "Rendered after this many full passes over the dataset. The equivalent step count is printed in the job’s log when the run starts, so a glance there says what the cadence came out as for this particular dataset.\n\nSampling interrupts training while it renders, so on a large dataset one round per epoch may be further apart than you want and on a tiny one it may be a pause every few seconds — the log’s step figure is what tells you which.": "Se genera tras este número de pasadas completas sobre el conjunto de datos. El número de pasos equivalente se escribe en el registro del trabajo al arrancar, así que un vistazo dice en qué queda la cadencia para este conjunto concreto.\n\nEl muestreo interrumpe el entrenamiento mientras genera, así que en un conjunto grande una ronda por época puede quedar más espaciada de lo que quieres y en uno diminuto puede ser una pausa cada pocos segundos — la cifra de pasos del registro es la que lo dice.",
  "Rendered every this many steps, whatever the dataset is. 250–500 is a good rhythm: often enough to catch a concept going wrong, rare enough that the pauses do not dominate the run.": "Se genera cada tantos pasos, sea cual sea el conjunto de datos. 250–500 es un buen ritmo: lo bastante frecuente para detectar un concepto que se tuerce, lo bastante raro para que las pausas no dominen el entrenamiento.",
  "A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 500 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both.\n\nHow many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has. That is also why the disk estimate below can only be given when the run's length is set in epochs too.":
    "Un paso es una cantidad fija de trabajo y una época es una pasada por cada imagen de entrenamiento, así que las dos frecuencias se separan a medida que crece un conjunto: «cada 500 pasos» es casi todo un entrenamiento pequeño y una fracción de uno grande, mientras que «cada época» significa lo mismo en ambos.\n\nCuántos pasos ocupa una época se calcula al iniciar el entrenamiento, porque solo el conjunto ya construido sabe cuántas entradas tiene. Por eso la estimación de disco de abajo solo puede darse si la duración también está en épocas.",
  "epochs":
    "épocas",
  "Written after this many full passes. The equivalent step count appears in the job's log when the run starts.":
    "Se escribe tras este número de pasadas completas. El equivalente en pasos aparece en el registro del trabajo al iniciar.",
  "Every snapshot is a usable model file: the Evaluate tab can generate with any of them, so you can compare one pass against another and keep whichever looks best.\n\nCounted in passes, the cadence follows the dataset: add pictures and the snapshots stay one-per-pass rather than quietly becoming more frequent than a pass. The trainer prints what it works out to in steps, so the timeline and the log still agree about what a checkpoint is.":
    "Cada instantánea es un archivo de modelo utilizable: la pestaña Evaluate puede generar con cualquiera, así que puedes comparar una pasada con otra y quedarte con la mejor.\n\nContada en pasadas, la frecuencia sigue al conjunto: si añades imágenes, las instantáneas siguen siendo una por pasada en vez de volverse calladamente más frecuentes que una pasada. El entrenador escribe en el registro a cuántos pasos equivale, para que la línea de tiempo y el registro sigan de acuerdo sobre qué es un checkpoint.",
  "Never upscale":
    "Nunca ampliar",
  "Leave out any image smaller than the bucket it would be fitted to, rather than enlarging it.":
    "Deja fuera las imágenes más pequeñas que el bucket al que irían, en vez de ampliarlas.",
  "Loads the frozen base weights in 8-bit or 4-bit so big models fit in little memory (QLoRA). 8-bit (int8) runs on Apple silicon too; fp8 and 4-bit need an NVIDIA GPU.":
    "Carga los pesos base congelados en 8 o 4 bits para que los modelos grandes quepan en poca memoria (QLoRA). 8 bits (int8) también funciona en Apple Silicon; fp8 y 4 bits necesitan una GPU NVIDIA.",
  "Quantize the text encoder":
    "Cuantizar el codificador de texto",
  "Applies the same scheme to the text encoder, the other big frozen model. On the largest models it is worth several GB.":
    "Aplica el mismo esquema al codificador de texto, el otro modelo congelado grande. En los modelos más grandes vale varios GB.",
  "cannot be combined with training the text encoder":
    "no se puede combinar con entrenar el codificador de texto",

  // ---- adapter type, layer targeting, optimizers, noise levels,
  // weight averaging and regularization ----
  "Adapter":
    "Adaptador",
  "Adapter type":
    "Tipo de adaptador",
  "Kronecker factor":
    "Factor de Kronecker",
  "How each weight is split into LoKr's two parts. Leave empty unless you have a reason not to.":
    "Cómo se divide cada peso en las dos partes de LoKr. Déjalo vacío salvo que tengas un motivo para no hacerlo.",
  "Only these layers":
    "Solo estas capas",
  "all of them":
    "todas",
  "Comma-separated parts of a layer's name. Leave empty to train every attention layer — which is what you want unless you have a reason not to.":
    "Partes del nombre de una capa, separadas por comas. Déjalo vacío para entrenar todas las capas de atención, que es lo que quieres salvo que tengas un motivo para no hacerlo.",
  "By default the adapter attaches to every attention layer in the image model. This narrows that to the layers whose name contains one of the words you list.\n\nWhy you might: different parts of the network do different jobs. The later ones carry more of what a picture LOOKS like, and the earlier ones more of how it is put together — so training only part of the network is how a style is learned without also disturbing composition and anatomy. It also makes the adapter smaller and each step faster, since there is less to train.\n\nThe names come from the model itself, and the chevron at the end of the field lists the ones worth knowing for the architecture you picked — clicking one adds or removes it, and a tick marks the ones the field already holds. For SD and SDXL they are down_blocks, mid_block and up_blocks, plus attn1 (the picture attending to itself) and attn2 (where the prompt gets in); for the newer transformer models, transformer_blocks and single_transformer_blocks. The field stays free text, because you can be as coarse or as fine as you like: 'up_blocks' takes a whole third of a UNet, 'transformer_blocks.12' takes one block, 'to_k' takes one kind of projection everywhere. The job's page draws a map of the whole model once a run has started.\n\nIf what you type matches no layers at all, the run stops and says so rather than training an adapter attached to nothing — which would otherwise look exactly like a normal run that learned nothing.":
    "Por defecto el adaptador se engancha a todas las capas de atención del modelo de imagen. Esto lo reduce a las capas cuyo nombre contiene alguna de las palabras que enumeres.\n\nPor qué querrías: distintas partes de la red hacen distintos trabajos. Las últimas cargan más con el ASPECTO de una imagen y las primeras con cómo está montada, así que entrenar solo una parte de la red es la manera de aprender un estilo sin alterar también la composición y la anatomía. Además hace el adaptador más pequeño y cada paso más rápido, porque hay menos que entrenar.\n\nLos nombres vienen del propio modelo, y la flecha al final del campo lista los que conviene conocer para la arquitectura elegida: un clic añade uno o lo quita, y una marca señala los que el campo ya tiene. En SD y SDXL son down_blocks, mid_block y up_blocks, más attn1 (la imagen atendiéndose a sí misma) y attn2 (por donde entra el prompt); en los modelos transformer más nuevos, transformer_blocks y single_transformer_blocks. El campo sigue siendo texto libre, porque puedes ser tan grueso o tan fino como quieras: «up_blocks» se lleva un tercio entero de una UNet, «transformer_blocks.12» un solo bloque, «to_k» un tipo de proyección en todas partes. La página de la tarea dibuja un mapa del modelo entero en cuanto arranca una ejecución.\n\nSi lo que escribes no coincide con ninguna capa, la ejecución se detiene y lo dice en lugar de entrenar un adaptador enganchado a nada, que si no se vería exactamente igual que una ejecución normal que no aprendió nada.",
  "Except these layers":
    "Excepto estas capas",
  "Comma-separated parts of a layer's name to leave out. Applied after the field above, and it wins.":
    "Partes del nombre de una capa, separadas por comas, que se dejan fuera. Se aplica después del campo de arriba y manda sobre él.",
  "The same kind of list, subtracting instead of selecting. A layer whose name matches anything here is left out even if the field above selected it.\n\nIt is the easier way to say 'everything except' — excluding 'down_blocks' is shorter and stays correct if the model gains a block, where listing every other block by hand does not.":
    "La misma clase de lista, restando en vez de seleccionar. Una capa cuyo nombre coincida con algo de aquí queda fuera aunque el campo de arriba la hubiera seleccionado.\n\nEs la forma sencilla de decir «todo excepto»: excluir «down_blocks» es más corto y sigue siendo correcto si el modelo gana un bloque, cosa que enumerar a mano todos los demás bloques no consigue.",
  "Output size: a small fraction of a LoRA of the same rank — usually under a tenth.":
    "Tamaño de salida: una pequeña fracción de un LoRA del mismo rango, normalmente menos de una décima parte.",
  "Learning rate multiplier":
    "Multiplicador de la tasa de aprendizaje",
  "Prodigy works the rate out for itself; this scales what it finds. 1 leaves it alone — lower it if the run overshoots, raise it if it never gets going.":
    "Prodigy calcula la tasa por su cuenta; esto escala lo que encuentra. 1 lo deja tal cual: bájalo si la ejecución se pasa de frenada, súbelo si nunca arranca.",
  "The Prodigy optimizer measures how far the weights have moved from where they started and derives a learning rate from that, so the rate is not something you set here — it comes out of the run.\n\nWhat this field does is scale the answer. 1 accepts it as found and is what you want almost always. Below 1 is a brake, worth reaching for if the run overshoots and samples come out burnt; above 1 pushes harder, which is occasionally useful on a very small dataset.\n\nProdigy needs a few hundred steps to work its estimate up from nearly nothing, so early samples in a Prodigy run look untrained even when everything is fine. Judge it from about a fifth of the way in, not from the first sample round.":
    "El optimizador Prodigy mide cuánto se han alejado los pesos de su punto de partida y deriva de ahí una tasa de aprendizaje, así que la tasa no se fija aquí: sale de la propia ejecución.\n\nLo que hace este campo es escalar esa respuesta. 1 la acepta tal cual y es lo que quieres casi siempre. Por debajo de 1 es un freno, útil si la ejecución se pasa y las muestras salen quemadas; por encima de 1 aprieta más, lo que a veces viene bien con un conjunto de datos muy pequeño.\n\nProdigy necesita unos cientos de pasos para levantar su estimación desde casi nada, así que las primeras muestras de una ejecución con Prodigy parecen sin entrenar aunque todo vaya bien. Júzgala a partir de un quinto del recorrido, no en la primera ronda de muestras.",
  "How far the weights move on every update. It is the single most sensitive setting here.\n\nToo high and training diverges: samples turn into over-saturated, high-contrast mush ('deep fried'), often within a few hundred steps. Too low and nothing visibly changes no matter how long you wait. Typical values: 1e-4 for a LoRA, 1e-5 or lower for a full finetune (which touches every weight and needs far gentler updates).\n\nLearning rate and total steps trade off against each other — halving the rate roughly doubles the steps needed. If early samples look burnt, halve it; if they look identical to the baseline after a third of the run, double it.\n\nIf finding this number is the part you would rather not do, the Prodigy optimizer (Memory & speed) works it out for itself.":
    "Cuánto se mueven los pesos en cada actualización. Es el ajuste más sensible de todos.\n\nDemasiado alto y el entrenamiento diverge: las muestras se convierten en una papilla sobresaturada y de contraste extremo («deep fried»), a menudo en unos pocos cientos de pasos. Demasiado bajo y no cambia nada visible por mucho que esperes. Valores típicos: 1e-4 para un LoRA, 1e-5 o menos para un ajuste completo (que toca todos los pesos y necesita actualizaciones mucho más suaves).\n\nLa tasa de aprendizaje y el total de pasos se compensan entre sí: reducir la tasa a la mitad duplica aproximadamente los pasos necesarios. Si las primeras muestras salen quemadas, divídela por dos; si tras un tercio de la ejecución siguen idénticas al punto de partida, dóblala.\n\nSi buscar este número es justo lo que preferirías no hacer, el optimizador Prodigy (Memoria y velocidad) lo calcula por su cuenta.",
  "Noise levels":
    "Niveles de ruido",
  "Train on":
    "Entrenar en",
  "Which stage of denoising to spend the run on. High noise decides a picture's layout, low noise its detail — so this decides what the training is mostly about.":
    "En qué etapa del proceso de quitar ruido se gasta la ejecución. El ruido alto decide la disposición de una imagen y el bajo su detalle, así que esto decide de qué va sobre todo el entrenamiento.",
  "Every training step takes a picture, adds some amount of noise to it, and asks the model to undo that. How much noise is picked fresh each time — and the two extremes teach completely different things.\n\nAt HIGH noise there is barely a picture left, so all the model can learn is layout: what is where, how big, the overall shape and colour. At LOW noise the composition is already settled and what is left to learn is detail and texture — edges, surfaces, small features.\n\nSo where a run spends its steps decides what it mostly teaches. A style is largely texture; a character's proportions are largely layout.\n\n'The model's own' is what this model family has always done here, and is the right answer unless you have a specific reason: the older models spread their steps evenly, and the newer ones concentrate on the middle, which is what their published recipes do and part of why they train efficiently. 'Evenly' spreads across the whole range. 'Bell curve' is the newer models' behaviour made adjustable, so you can lean it towards layout or towards detail. 'Cosine' leans towards higher noise without abandoning the low end.\n\nChanging this does not make a run better or worse in general — it moves what the run is good at.":
    "Cada paso de entrenamiento toma una imagen, le añade cierta cantidad de ruido y pide al modelo que lo deshaga. Cuánto ruido se sortea de nuevo cada vez, y los dos extremos enseñan cosas completamente distintas.\n\nCon ruido ALTO apenas queda imagen, así que lo único que el modelo puede aprender es la disposición: qué hay dónde, de qué tamaño, la forma y el color generales. Con ruido BAJO la composición ya está resuelta y lo que queda por aprender es detalle y textura: bordes, superficies, rasgos pequeños.\n\nAsí que dónde gasta sus pasos una ejecución decide qué enseña sobre todo. Un estilo es en gran medida textura; las proporciones de un personaje son en gran medida disposición.\n\n«El propio del modelo» es lo que esta familia de modelos ha hecho siempre aquí, y es la respuesta correcta salvo que tengas un motivo concreto: los modelos antiguos reparten sus pasos de forma uniforme y los nuevos se concentran en el centro, que es lo que hacen sus recetas publicadas y parte del porqué de que entrenen con eficiencia. «Uniformemente» reparte por todo el rango. «Campana de Gauss» es el comportamiento de los modelos nuevos hecho ajustable, de modo que puedes inclinarlo hacia la disposición o hacia el detalle. «Coseno» se inclina hacia el ruido alto sin abandonar el extremo bajo.\n\nCambiar esto no hace una ejecución mejor ni peor en general: mueve aquello en lo que la ejecución es buena.",
  "The model's own (recommended)":
    "El propio del modelo (recomendado)",
  "Evenly across all levels":
    "Uniformemente por todos los niveles",
  "A bell curve I can aim":
    "Una campana que puedo apuntar",
  "Leaning towards layout":
    "Inclinado hacia la disposición",
  "Aim at":
    "Apuntar a",
  "0 is the middle. Positive leans towards layout and composition, negative towards detail and texture. ±1 is already a strong lean.":
    "0 es el centro. En positivo se inclina hacia la disposición y la composición; en negativo, hacia el detalle y la textura. ±1 ya es una inclinación fuerte.",
  "Where the centre of the bell curve sits along the noise range.\n\n0 puts it in the middle, which is what the newer models do by default and a good place to stay. Move it positive and the run spends more of itself at high noise, learning layout and composition — useful when what you are teaching is a shape or an arrangement. Move it negative and it spends more at low noise, learning detail and texture — useful for a style, a medium, a surface quality.\n\n±0.5 is a noticeable lean and ±1 is a strong one. Beyond ±2 the run largely stops seeing one end of the range at all.":
    "Dónde se sitúa el centro de la campana a lo largo del rango de ruido.\n\n0 lo pone en el medio, que es lo que hacen por defecto los modelos nuevos y un buen sitio donde quedarse. Muévelo en positivo y la ejecución gasta más de sí misma con ruido alto, aprendiendo disposición y composición: útil cuando lo que enseñas es una forma o una colocación. Muévelo en negativo y gasta más con ruido bajo, aprendiendo detalle y textura: útil para un estilo, un medio, una cualidad de superficie.\n\n±0,5 es una inclinación apreciable y ±1 una fuerte. Más allá de ±2 la ejecución prácticamente deja de ver uno de los extremos del rango.",
  "Spread":
    "Dispersión",
  "How wide the curve is. 1 is the default; smaller concentrates the run on a narrow band around the aim, larger reaches both extremes.":
    "Lo ancha que es la curva. 1 es lo predeterminado; menos concentra la ejecución en una banda estrecha alrededor del punto apuntado, más alcanza ambos extremos.",
  "The width of the bell curve.\n\n1 is the standard setting. Smaller values concentrate the run on a narrow band around wherever you have aimed it, which sharpens what it teaches at the cost of everything else. Larger values spread it out and reach both extremes more often, which is closer to training evenly.\n\nIf you are unsure, leave it at 1 and move the aim instead — the aim is the setting that changes what the run learns, and this one changes how single-minded it is about it.":
    "El ancho de la campana.\n\n1 es el ajuste estándar. Los valores menores concentran la ejecución en una banda estrecha alrededor de donde la hayas apuntado, lo que afina lo que enseña a costa de todo lo demás. Los mayores la reparten y alcanzan ambos extremos más a menudo, lo que se acerca a entrenar de forma uniforme.\n\nSi tienes dudas, déjalo en 1 y mueve el punto apuntado: el punto es el ajuste que cambia lo que la ejecución aprende, y este cambia lo obsesiva que es al respecto.",
  "Weight averaging":
    "Promediado de pesos",
  "Average the weights":
    "Promediar los pesos",
  "Save a smoothed version of the weights instead of whatever the last step happened to produce. Makes checkpoints more consistent and overtraining slower to bite.":
    "Guarda una versión suavizada de los pesos en lugar de lo que haya salido del último paso. Hace los checkpoints más consistentes y que el sobreentrenamiento tarde más en morder.",
  "Every training step moves the weights a little, and each of those moves is noisy — it is worked out from a handful of images, and a different handful would have pulled somewhere slightly different. So the weights at step 1400 are not reliably better than the weights at step 1200; part of the difference is just which pictures came up.\n\nWith this on, the run keeps a second, smoothed copy of the weights alongside the real ones and nudges it a little way towards the current weights after every step. That smoothed copy is what gets saved — as the checkpoints, as the final result, and as what the test samples are rendered from. Training itself is completely unaffected.\n\nWhat you get is a result that depends less on exactly where the run stopped: the quality difference between neighbouring checkpoints shrinks, and a run that goes on too long degrades more gradually, because an average lags behind. What it costs is one extra copy of whatever is being trained — nothing worth thinking about for a LoRA, a second whole model for a full finetune, which the memory estimate below accounts for.\n\nThe early part of a run is handled for you: a fresh average starts out equal to the untrained weights, so the run keeps it short at first and lengthens it as training goes on. Without that, a short run would save an average still holding its own random starting point.":
    "Cada paso de entrenamiento mueve los pesos un poco, y cada uno de esos movimientos es ruidoso: se calcula a partir de un puñado de imágenes, y otro puñado habría tirado hacia un sitio algo distinto. Por eso los pesos del paso 1400 no son fiablemente mejores que los del paso 1200; parte de la diferencia es simplemente qué imágenes salieron.\n\nCon esto activado, la ejecución mantiene una segunda copia suavizada de los pesos junto a los reales y la empuja un poco hacia los pesos actuales después de cada paso. Esa copia suavizada es la que se guarda: como checkpoints, como resultado final y como aquello con lo que se renderizan las muestras de prueba. El entrenamiento en sí no se ve afectado en absoluto.\n\nLo que obtienes es un resultado que depende menos de dónde se paró exactamente la ejecución: la diferencia de calidad entre checkpoints vecinos se reduce, y una ejecución que se alarga de más se degrada de forma más gradual, porque un promedio va por detrás. Cuesta una copia adicional de lo que se esté entrenando: nada digno de pensarlo para un LoRA, un segundo modelo entero para un ajuste completo, cosa que la estimación de memoria de abajo tiene en cuenta.\n\nDel comienzo de la ejecución se encarga la app: un promedio nuevo arranca igual a los pesos sin entrenar, así que la ejecución lo mantiene corto al principio y lo alarga a medida que el entrenamiento avanza. Sin eso, una ejecución corta guardaría un promedio que todavía contendría su propio punto de partida aleatorio.",
  "Averaging window":
    "Ventana de promediado",
  "How much of the old average is kept each step. 0.999 averages roughly the last 1000 steps; lower follows training more closely, higher smooths harder.":
    "Cuánto del promedio anterior se conserva en cada paso. 0,999 promedia aproximadamente los últimos 1000 pasos; menos sigue al entrenamiento más de cerca, más suaviza con más fuerza.",
  "The fraction of the existing average kept at each step, with the rest taken from the current weights. It decides how long a stretch of training the saved result reflects — roughly 1 ÷ (1 − this value) steps.\n\n0.999 is about the last 1000 steps and is a sensible default for runs of a few thousand. On a short run (say 800 steps) that window is longer than the run itself, so the average never quite catches up — drop to 0.99 (about 100 steps) there. On a very long run you can go higher for a steadier result.\n\nAs a rule of thumb, keep the window well under the total number of steps.":
    "La fracción del promedio existente que se conserva en cada paso; el resto sale de los pesos actuales. Decide qué tramo de entrenamiento refleja el resultado guardado: aproximadamente 1 ÷ (1 − este valor) pasos.\n\n0,999 son unos 1000 pasos y es un valor sensato para ejecuciones de unos pocos miles. En una ejecución corta (digamos 800 pasos) esa ventana es más larga que la propia ejecución, así que el promedio nunca llega a alcanzarla: baja ahí a 0,99 (unos 100 pasos). En una ejecución muy larga puedes subir para un resultado más estable.\n\nComo regla general, mantén la ventana bastante por debajo del número total de pasos.",
  "Mostly a memory choice, except for Prodigy, which works the learning rate out for itself. Adafactor saves the most memory and runs on every GPU; 8-bit AdamW saves less and needs an NVIDIA or AMD card.":
    "Sobre todo una decisión de memoria, salvo con Prodigy, que calcula la tasa de aprendizaje por su cuenta. Adafactor es el que más memoria ahorra y funciona en cualquier GPU; AdamW (8 bits) ahorra menos y necesita una tarjeta NVIDIA o AMD.",
  "The optimizer is what actually turns gradients into weight changes. It does that using running statistics it keeps for every weight being trained — and those statistics are memory, which for a full finetune is usually most of what the run needs.\n\nAdamW is the standard choice and the safest. It keeps two statistics per trained weight, so a full finetune pays for the model roughly three times over: the weights themselves, plus two more of the same size.\n\nAdamW (8-bit) stores those two statistics at one byte each instead of four. It is a smaller saving than it sounds, because the weights and their gradients do not shrink, and it needs an NVIDIA or AMD (ROCm) GPU — elsewhere the run says so and uses plain AdamW.\n\nAdafactor replaces the larger of the two statistics with a per-row and a per-column summary of it, which is a fraction of the size. It saves considerably more than the 8-bit variant and it runs on every GPU, including Apple silicon — where it is the only memory saving available at all, since the 8-bit variant cannot run there. What it costs is a little stability: it usually wants a slightly higher learning rate than AdamW, so if a run learns nothing after a few hundred steps, raise the rate before changing anything else.\n\nProdigy is a different kind of answer. It measures how far the weights have travelled from where they started and works the learning rate out from that as it goes, which removes the one setting here that genuinely has to be found by trial: the right rate depends on the model, the dataset size and what is being taught, so a value that suits one job is wrong for the next. With it selected, the learning rate on the Optimization page becomes a multiplier on what it finds, and 1 means 'as found'. It uses a little more memory than AdamW, and it needs a few hundred steps to work its estimate up — so early samples look untrained even when the run is fine.\n\nFor LoRA training the memory differences are a rounding error, since only the small adapter has optimizer state. Leave it on AdamW for a first run; reach for Prodigy when you are tired of guessing the rate, and for Adafactor when a full finetune will not fit.":
    "El optimizador es lo que realmente convierte los gradientes en cambios de peso. Lo hace con estadísticas en curso que mantiene para cada peso entrenado, y esas estadísticas son memoria, que en un ajuste completo suele ser la mayor parte de lo que la ejecución necesita.\n\nAdamW es la opción estándar y la más segura. Mantiene dos estadísticas por peso entrenado, así que un ajuste completo paga el modelo unas tres veces: los pesos en sí, más dos copias del mismo tamaño.\n\nAdamW (8 bits) guarda esas dos estadísticas con un byte cada una en lugar de cuatro. El ahorro es menor de lo que parece, porque los pesos y sus gradientes no encogen, y necesita una GPU NVIDIA o AMD (ROCm): en cualquier otro sitio la ejecución lo dice y usa AdamW normal.\n\nAdafactor sustituye la mayor de las dos estadísticas por un resumen por fila y otro por columna, que ocupa una fracción. Ahorra bastante más que la variante de 8 bits y funciona en cualquier GPU, incluida Apple silicon, donde además es el único ahorro de memoria disponible, ya que la variante de 8 bits no puede ejecutarse ahí. Cuesta algo de estabilidad: suele querer una tasa de aprendizaje algo más alta que AdamW, así que si una ejecución no aprende nada tras unos cientos de pasos, sube la tasa antes de cambiar cualquier otra cosa.\n\nProdigy es otra clase de respuesta. Mide cuánto se han alejado los pesos de su punto de partida y de ahí deduce la tasa de aprendizaje sobre la marcha, lo que elimina el único ajuste de esta página que de verdad hay que encontrar probando: la tasa correcta depende del modelo, del tamaño del conjunto de datos y de lo que se enseñe, así que un valor que va bien en una tarea está mal en la siguiente. Con él seleccionado, la tasa de aprendizaje de la página Optimización pasa a ser un multiplicador de lo que encuentre, y 1 significa «tal cual la encontró». Usa algo más de memoria que AdamW y necesita unos cientos de pasos para levantar su estimación, así que las primeras muestras parecen sin entrenar aunque la ejecución esté bien.\n\nEn el entrenamiento de un LoRA las diferencias de memoria son un error de redondeo, porque solo el pequeño adaptador tiene estado de optimizador. Déjalo en AdamW para una primera ejecución; recurre a Prodigy cuando te canses de adivinar la tasa, y a Adafactor cuando un ajuste completo no quepa.",
  "AdamW (8-bit)":
    "AdamW (8 bits)",
  "Prodigy (finds its own rate)":
    "Prodigy (encuentra su propia tasa)",
  "Prodigy works the learning rate out for itself, so the rate on the Optimization page becomes a multiplier on what it finds — 1 leaves it alone. It needs a few hundred steps to settle, so early samples will look untrained.":
    "Prodigy calcula la tasa de aprendizaje por su cuenta, así que la tasa de la página Optimización pasa a ser un multiplicador de lo que encuentre; 1 la deja tal cual. Necesita unos cientos de pasos para asentarse, de modo que las primeras muestras parecerán sin entrenar.",
  "Regularization":
    "Regularización",
  "How much reminders count":
    "Cuánto cuentan los recordatorios",
  "1 gives a regularization picture the same say as a training picture, which is the usual setting. Lower makes it a gentler reminder.":
    "1 da a una imagen de regularización el mismo peso que a una de entrenamiento, que es el ajuste habitual. Menos la convierte en un recordatorio más suave.",
  "Regularization pictures are in the run to hold the model's existing idea of a thing in place while you teach it something new. This is how much each of them counts against a training picture, which counts 1.\n\n1 is the classic setting and a good starting point. Lower it if the run seems reluctant to learn what you are actually training — the reminders are pulling too hard. Raise it if what you are training keeps leaking into everything else of the same kind, which is the problem they exist to solve.\n\nThis is separate from a query's weight, which decides how OFTEN those pictures come up. How often and how much are different questions: a set of reminders is usually wanted often but quietly.":
    "Las imágenes de regularización están en la ejecución para sujetar la idea que el modelo ya tiene de algo mientras le enseñas algo nuevo. Esto es cuánto cuenta cada una frente a una imagen de entrenamiento, que cuenta 1.\n\n1 es el ajuste clásico y un buen punto de partida. Bájalo si la ejecución parece reacia a aprender lo que de verdad estás entrenando: los recordatorios tiran demasiado. Súbelo si lo que entrenas se filtra una y otra vez en todo lo demás del mismo tipo, que es el problema que existen para resolver.\n\nEsto es independiente del peso de una consulta, que decide CON QUÉ FRECUENCIA aparecen esas imágenes. Con qué frecuencia y cuánto son preguntas distintas: un conjunto de recordatorios suele quererse a menudo, pero discreto.",
  "Pictures that remind the model what it already knows, instead of teaching it something new — they stop what you are training from spreading to everything else of the same kind. They never get the trigger word.":
    "Imágenes que le recuerdan al modelo lo que ya sabe, en vez de enseñarle algo nuevo: impiden que lo que entrenas se extienda a todo lo demás del mismo tipo. Nunca reciben el trigger.",
  "These pictures hold the model's existing idea of the subject in place: pick the same KIND of thing you are training, but not the thing itself. You do not need to exclude your training pictures — anything an ordinary query matches stays a training picture. A reminder query that matches only training pictures leaves this pool empty, and the run says so in its log.":
    "Estas imágenes mantienen en su sitio la idea que el modelo ya tiene del sujeto: elige el mismo TIPO de cosa que estás entrenando, pero no la cosa en sí. No hace falta que excluyas tus imágenes de entrenamiento: lo que encuentre una consulta ordinaria sigue siendo una imagen de entrenamiento. Una consulta de recordatorio que solo encuentre imágenes de entrenamiento deja este conjunto vacío, y la ejecución lo indica en su registro.",
  "Keep the text encoder on the CPU":
    "Mantener el codificador de texto en la CPU",
  "Frees all of its VRAM instead of some. The next batch's prompt is encoded while this one trains, so it costs nothing as long as the processor keeps up with the card.": "Libera toda su VRAM en lugar de solo una parte. El prompt del siguiente lote se codifica mientras este entrena, así que no cuesta nada mientras el procesador siga el ritmo de la tarjeta.",
  "The row above makes the text encoder smaller; this one takes it off the graphics card altogether. Its weights stay in ordinary system memory and each prompt is turned into an embedding there, so the encoder occupies no VRAM at all — where quantizing it leaves roughly a third of it resident.\n\nMeasured on an RTX 5070 Ti at 4-bit, this takes Chroma from 9.6 GB to 5.3 and FLUX.1 from 11.4 to 7.0, which was enough to train FLUX.2 Klein at a resolution that did not previously fit.\n\nWhat it costs is one pass over the encoder per step, on the processor instead of the graphics card — and the next batch's prompt is encoded while the current one trains, so the card only waits where the processor is slower than a whole step. Measured on a 16-core desktop, T5-XXL takes about 1.3 seconds a prompt: a 1024-pixel step on an RTX 5090 hides that entirely, a 512-pixel step (half a second) does not. It cannot be combined with training the text encoder, which would mean doing that training on the processor.":
    "La fila de arriba reduce el codificador de texto; esta lo saca por completo de la tarjeta gráfica. Sus pesos se quedan en la memoria del sistema y cada prompt se convierte allí en un embedding, así que el codificador no ocupa nada de VRAM, mientras que cuantizarlo deja residente alrededor de un tercio.\n\nMedido en una RTX 5070 Ti a 4 bits, Chroma baja de 9,6 GB a 5,3 y FLUX.1 de 11,4 a 7,0 — suficiente para entrenar FLUX.2 Klein a una resolución que antes no cabía.\n\nLo que cuesta es una pasada por el codificador por paso, en el procesador en lugar de la tarjeta gráfica — y el prompt del siguiente lote se codifica mientras el actual entrena, así que la tarjeta solo espera donde el procesador es más lento que un paso entero. Medido en un equipo de 16 núcleos, T5-XXL tarda unos 1,3 segundos por prompt: un paso a 1024 píxeles en una RTX 5090 lo oculta por completo, un paso a 512 píxeles (medio segundo) no. No puede combinarse con el entrenamiento del codificador de texto, que supondría hacer ese entrenamiento en el procesador.",

  // ---- the METHOD is an adapter, of which LoRA is one kind ----
  "An adapter is a small add-on file layered over the untouched model — fast, low memory, ideal for styles, characters and concepts. Full finetune rewrites the whole model: much more VRAM and data needed, only worth it for broad domain shifts. Which kind of adapter is the next question down.":
    "Un adaptador es un pequeño archivo añadido sobre el modelo intacto: rápido, poca memoria, ideal para estilos, personajes y conceptos. El ajuste completo reescribe el modelo entero: hace falta mucha más VRAM y muchos más datos, y solo compensa para cambios amplios de dominio. Qué tipo de adaptador es la siguiente pregunta, más abajo.",
  "An adapter leaves the base model untouched and trains a small add-on (a few dozen MB) that is layered on top at generation time. It is quick, fits ordinary hardware, can be mixed with other adapters and dialled up or down by weight — and it is enough for styles, characters, objects and most concepts. There are two kinds, LoRA and LoKr, and the Adapter section below picks between them; LoRA is the one to start with.\n\nA full finetune rewrites every weight of the model. It produces a multi-gigabyte model of its own, needs far more VRAM, far more images and much lower learning rates, and it can forget things it used to know. Reach for it only when you are moving the model into a genuinely different domain, not to teach it one more subject.":
    "Un adaptador deja el modelo base intacto y entrena un pequeño añadido (unas decenas de MB) que se superpone al generar. Es rápido, cabe en hardware corriente, se puede mezclar con otros adaptadores y subir o bajar por peso, y basta para estilos, personajes, objetos y la mayoría de los conceptos. Hay dos tipos, LoRA y LoKr; la sección Adaptador de más abajo elige entre ellos, y LoRA es el que conviene para empezar.\n\nUn ajuste completo reescribe todos los pesos del modelo. Produce un modelo propio de varios gigabytes, necesita mucha más VRAM, muchas más imágenes y tasas de aprendizaje mucho más bajas, y puede olvidar cosas que sabía. Recurre a él solo cuando estés llevando el modelo a un dominio genuinamente distinto, no para enseñarle un tema más.",
  "Start from an existing adapter":
    "Partir de un adaptador existente",
  "A fresh adapter starts from noise and has to learn your concept from nothing. Starting from an existing one keeps everything it already learned and refines it — the usual reasons are adding new images to a concept you trained before, or nudging one that came out almost right.\n\nWeight sets trained on the same base model are offered — including ones trained on another model built on it — and the new job has to match the one it continues: the same adapter type, the same rank, and the same layer targeting. The trainer stops with a message naming what it found otherwise. Picking a job's finished result continues where it ended; picking an intermediate checkpoint rewinds to that point and continues from there.":
    "Un adaptador nuevo parte del ruido y tiene que aprender tu concepto desde cero. Partir de uno existente conserva todo lo que ya aprendió y lo refina: los motivos habituales son añadir imágenes nuevas a un concepto que ya entrenaste, o retocar uno que salió casi bien.\n\nSe ofrecen los conjuntos de pesos entrenados con el mismo modelo base — incluidos los entrenados con otro modelo construido sobre él — y la nueva tarea tiene que coincidir con la que continúa: el mismo tipo de adaptador, el mismo rango y la misma selección de capas. Si no, el entrenador se detiene con un mensaje que nombra lo que encontró. Elegir el resultado terminado de una tarea continúa donde acabó; elegir un checkpoint intermedio rebobina hasta ese punto y sigue desde ahí.",
  "Pick a finished adapter":
    "Elige un adaptador terminado",
  "No finished adapter for this base model yet":
    "Aún no hay adaptador terminado para este modelo base",
  "Optional: continue training an existing adapter instead of starting from scratch.":
    "Opcional: continuar el entrenamiento de un adaptador existente en vez de empezar desde cero.",
  "No full finetune":
    "Sin ajuste completo",

  // ---- adapter wording: an adapter is LoRA or LoKr ----
  "The standard choice, and the format every other tool understands — a LoRA can be used anywhere.":
    "La opción estándar, y el formato que entiende cualquier otra herramienta: un LoRA se puede usar en todas partes.",
  "An adapter does not rewrite the model — it adds a small 'side channel' to certain layers, and rank is how wide that channel is: how much new information the adapter can hold.\n\nLow ranks (4–8) are plenty for a style or a colour palette and are very hard to overfit. Mid ranks (16–32) suit characters and objects with consistent details. High ranks (64+) mostly grow the file and the overfitting risk without helping, unless you are teaching a genuinely broad new domain.\n\nIt means slightly different things to the two adapter types. For a LoRA it is the hard ceiling on the change: a rank-16 adapter can only ever make a rank-16 change. For a LoKr it bounds only part of the structure, so a LoKr is not confined the way a LoRA is and its file grows far more slowly as you raise it — which is why the size estimate below is a figure for LoRA and a comparison for LoKr.":
    "Un adaptador no reescribe el modelo: añade un pequeño «canal lateral» a ciertas capas, y el rango es lo ancho que es ese canal, es decir cuánta información nueva cabe en el adaptador.\n\nLos rangos bajos (4–8) sobran para un estilo o una paleta de color y son muy difíciles de sobreajustar. Los medios (16–32) van bien con personajes y objetos de detalles constantes. Los altos (64+) casi solo hacen crecer el archivo y el riesgo de sobreajuste sin aportar, salvo que enseñes un dominio nuevo y genuinamente amplio.\n\nSignifica cosas algo distintas para cada tipo de adaptador. En un LoRA es el techo duro del cambio: un adaptador de rango 16 solo puede hacer un cambio de rango 16. En un LoKr acota solo parte de la estructura, así que un LoKr no queda encerrado como un LoRA y su archivo crece mucho más despacio al subirlo — por eso abajo hay una cifra para LoRA y una comparación para LoKr.",
  "The adapter's output is multiplied by alpha ÷ rank before being added to the model, so alpha sets how loudly the adapter speaks at a given capacity. It works the same way for both adapter types.\n\nThe usual convention is alpha = rank, which makes the scale factor 1 and keeps behaviour comparable when you change rank. Setting alpha to half the rank is a common way to soften an adapter that comes out too strong. It interacts with the learning rate — halving alpha has a similar effect to halving the rate — so change one at a time.":
    "La salida del adaptador se multiplica por alfa ÷ rango antes de sumarse al modelo, así que alfa decide lo alto que habla el adaptador con una capacidad dada. Funciona igual en los dos tipos de adaptador.\n\nLo habitual es alfa = rango, lo que deja el factor en 1 y mantiene el comportamiento comparable al cambiar el rango. Poner alfa a la mitad del rango es una forma común de suavizar un adaptador que sale demasiado fuerte. Interactúa con la tasa de aprendizaje —dividir alfa por dos se parece a dividir la tasa por dos—, así que cambia solo una cosa cada vez.",
  "This architecture can only be trained as an adapter (LoRA or LoKr) alongside the frozen model. The \"Full finetune\" method, which rewrites the model's own weights, is not offered for it.":
    "Esta arquitectura solo se puede entrenar como adaptador (LoRA o LoKr) junto al modelo congelado. El método «Ajuste completo», que reescribe los pesos propios del modelo, no se ofrece para ella.",
  "No adapters for this base model yet — an adapter fits the model it was trained on and any other built on the same one.":
    "Aún no hay adaptadores para este modelo base: un adaptador sirve para el modelo con el que se entrenó y para cualquier otro construido sobre el mismo.",
  "No trained adapters yet — finish a training job first. Generating with the plain base model works regardless.":
    "Aún no hay adaptadores entrenados: termina antes una tarea de entrenamiento. Generar con el modelo base a secas funciona igualmente.",
  "Which adapter this row applies":
    "Qué adaptador aplica esta fila",
  "Adapter strength: 1 = as trained, below weakens, above strengthens (can distort past ~1.5).":
    "Intensidad del adaptador: 1 = como se entrenó, por debajo debilita, por encima refuerza (puede distorsionar pasado ~1.5).",
  "Add adapter":
    "Añadir adaptador",
  "Adapters":
    "Adaptadores",
  "Finetune": "Finetune",
  "Generate with a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.":
    "Generar con los pesos de un finetune completo en lugar de los del modelo base. Los adaptadores se apilan sobre lo que se elija aquí.",
  "none — the base model": "ninguno — el modelo base",
  "loading finetune": "cargando finetune",
  "Stack trained adapters on the base model, each with its own strength — LoRA or LoKr. An adapter fits the model it was trained on and any other built on the same one.":
    "Apila adaptadores entrenados sobre el modelo base, cada uno con su propia intensidad — LoRA o LoKr. Un adaptador sirve para el modelo con el que se entrenó y para cualquier otro construido sobre el mismo.",
  "Generated images appear here — try out a trained adapter against its base model.":
    "Las imágenes generadas aparecen aquí: prueba un adaptador entrenado frente a su modelo base.",
  "A much smaller file, and not limited by the rank the way a LoRA is. Whether it can be used outside this app depends on the model — see the ⓘ.":
    "Un archivo mucho más pequeño y sin el límite de rango de una LoRA. Que pueda usarse fuera de esta aplicación depende del modelo: mira el ⓘ.",
  "Both add a small trainable layer over the frozen model; they differ in the shape of change they can express.\n\nA LoRA adds a 'low-rank' change: two thin matrices whose product is added to each targeted weight. Its capacity is exactly its rank — a rank-16 adapter can only ever make a rank-16 change, however long you train it. That is ample for a character, an object, a colour palette. It trains a little faster, it is the format every tool reads, and it carries better between related checkpoints: a LoRA trained on one finetune of a model usually still works on another.\n\nLoKr builds the change as a Kronecker product of two much smaller matrices instead. The saving comes from that structure rather than from throwing rank away, so the change is not confined to a thin slice of the weight while the file stays a small fraction of a LoRA's — under a tenth of the trainable parameters at rank 8. LyCORIS, whose method this is, suggests reaching for it when a LoRA 'does not learn well enough', and it is generally the better fit for styles and broad visual qualities, where a LoRA's rank ceiling is what you meet first. Its own caveats are the mirror image: slightly slower to train, and a very small LoKr transfers less well if you later swap the base model for a different finetune.\n\nWhat each can be USED by differs, and it is the file rather than the method. A LoRA is written in the layout every tool reads. A LoKr cannot be: that layout has a place for two matrices and nowhere to put a Kronecker factor. What it gets instead is a copy named the way ComfyUI names LoKr layers, and that works for the models whose layers ComfyUI addresses that way — FLUX.1, FLUX.1 Kontext and the Qwen-Image releases. On the others (SD 1.5, SDXL, Chroma, FLUX.2, Z-Image) a LoKr stays here: it works in the Evaluate tab and as the starting point of another job, but there is no file to hand over. On those, pick LoRA if the result has to leave this app.":
    "Ambos añaden una pequeña capa entrenable sobre el modelo congelado; se diferencian en la forma de cambio que pueden expresar.\n\nUna LoRA añade un cambio «de rango bajo»: dos matrices delgadas cuyo producto se suma a cada peso afectado. Su capacidad es exactamente su rango: un adaptador de rango 16 solo podrá hacer un cambio de rango 16, por mucho que entrenes. Es de sobra para un personaje, un objeto o una paleta de color. Entrena algo más rápido, es el formato que leen todas las herramientas y viaja mejor entre checkpoints emparentados: una LoRA entrenada sobre un finetune de un modelo suele seguir funcionando en otro.\n\nLoKr construye el cambio como un producto de Kronecker de dos matrices mucho más pequeñas. El ahorro viene de esa estructura y no de tirar rango, así que el cambio no queda confinado a una franja estrecha del peso mientras el archivo es una fracción del de una LoRA: menos de una décima parte de los parámetros entrenables con rango 8. LyCORIS, de donde viene el método, recomienda recurrir a él cuando una LoRA «no aprende lo bastante bien», y suele encajar mejor con estilos y cualidades visuales amplias, donde el techo de rango de una LoRA es lo primero que se encuentra. Sus pegas son la imagen inversa: entrena algo más despacio, y una LoKr muy pequeña se transfiere peor si luego cambias el modelo base por otro finetune.\n\nPara qué puede USARSE cada una difiere, y eso depende del archivo, no del método. Una LoRA se escribe en el formato que leen todas las herramientas. Una LoKr no puede: ese formato tiene sitio para dos matrices y ninguno para un factor de Kronecker. En su lugar recibe una copia nombrada como ComfyUI nombra las capas LoKr, y eso funciona para los modelos cuyas capas direcciona así: FLUX.1, FLUX.1 Kontext y las versiones de Qwen-Image. En los demás (SD 1.5, SDXL, Chroma, FLUX.2, Z-Image) una LoKr se queda aquí: funciona en la pestaña Evaluar y como punto de partida de otro trabajo, pero no hay archivo que entregar. En esos, elige LoRA si el resultado tiene que salir de esta aplicación.",
  "LoKr expresses a weight's change as one small matrix combined with another. This number decides where the weight is cut into those two parts.\n\nLeft empty, the split is chosen to make the two parts as close to square as possible, which is where they are SMALLEST. Moving it either way grows the file, and the two directions are not the same thing: a low factor (4–8) pushes the weight into the second part, which is where the adapter's capacity is — that is the LyCORIS recipe for a LoKr that is not learning enough. A factor far above the square split grows the first, dense part instead, which costs size for nothing.\n\nMeasured on a 1280-wide layer at rank 8, against the same layer's LoRA: automatic 0.08x, factor 8 0.13x, factor 4 0.25x, factor 128 0.81x.\n\nThere is rarely a reason to set it. If a LoKr adapter is not learning enough, raise the rank first, then try a low factor.":
    "LoKr expresa el cambio de un peso como una matriz pequeña combinada con otra. Este número decide dónde se corta el peso en esas dos partes.\n\nEn blanco, el corte se elige para que las dos partes sean lo más cuadradas posible, que es donde son MÁS PEQUEÑAS. Moverlo en cualquier dirección hace crecer el archivo, y las dos direcciones no son lo mismo: un factor bajo (4–8) empuja el peso hacia la segunda parte, que es donde está la capacidad del adaptador; esa es la receta de LyCORIS para una LoKr que no aprende lo suficiente. Un factor muy por encima del corte cuadrado hace crecer la primera parte, densa, lo que cuesta tamaño para nada.\n\nMedido en una capa de 1280 de ancho con rango 8, frente a la LoRA de esa misma capa: automático 0,08x, factor 8 0,13x, factor 4 0,25x, factor 128 0,81x.\n\nRara vez hay motivo para tocarlo. Si una LoKr no aprende lo suficiente, sube primero el rango y luego prueba un factor bajo.",
  "Every picture this finds is also matched by a training query, so it contributes nothing and the run will not be regularized. Narrow it to pictures the run is NOT about.":
    "Todas las imágenes que encuentra las encuentra también una consulta de entrenamiento, así que no aporta nada y la ejecución no se regularizará. Redúcela a imágenes de las que la ejecución NO trata.",
  "val": "val",
  "stable": "estable",
  "validation": "validación",
  "Validate": "Validar",
  "Masked regions": "Regiones enmascaradas",
  "Mask out regions tagged": "Enmascarar regiones etiquetadas",
  "Comma-separated tags whose bounding boxes are largely ignored by the loss — e.g. 'watermark'. The picture still trains; the region inside the boxes stops teaching. Tags without boxes on an image mask nothing there.": "Etiquetas separadas por comas cuyas cajas la pérdida ignora en gran medida — p. ej. 'watermark'. La imagen sigue entrenando; la región dentro de las cajas deja de enseñar. Una etiqueta sin cajas en una imagen no enmascara nada ahí.",
  "Mask out regions of tags marked": "Enmascarar regiones de etiquetas marcadas",
  "Comma-separated META tags. Any tag the library marks with one of these has its boxes masked — so the rule is stated once in the Tags tab rather than listed here.": "Metaetiquetas separadas por comas. Cualquier etiqueta que la biblioteca marque así tiene sus cajas enmascaradas, de modo que la regla se enuncia una vez en la pestaña Etiquetas en lugar de listarse aquí.",
  "Masked region weight": "Peso de las regiones enmascaradas",
  "How much a masked region still counts. 0 hides it from training entirely; 1 is the same as not masking.": "Cuánto cuenta todavía una región enmascarada. 0 la oculta por completo del entrenamiento; 1 es lo mismo que no enmascarar.",
  "Validation": "Validación",
  "Score a validation loss": "Medir una pérdida de validación",
  "A few images are held out of training and re-scored on a fixed seed as the run goes. Falling: still learning. Rising while the training loss falls: memorizing — pick an earlier checkpoint.": "Unas pocas imágenes se apartan del entrenamiento y se vuelven a puntuar con semilla fija a lo largo del run. Bajando: sigue aprendiendo. Subiendo mientras la pérdida de entrenamiento baja: está memorizando — elige un checkpoint anterior.",
  "Validate every": "Validar cada",
  "Each round costs one forward pass per scored image — a small set every few hundred steps is barely noticeable.": "Cada ronda cuesta una pasada hacia delante por imagen puntuada — un conjunto pequeño cada pocos cientos de pasos apenas se nota.",
  "Held-out images": "Imágenes apartadas",
  "Taken OUT of training entirely and scored each round. Capped at half the dataset; 16 is plenty for a LoRA-sized run. 0 turns the held-out series off.": "Sacadas por completo del entrenamiento y puntuadas cada ronda. Con tope en la mitad del conjunto de datos; 16 bastan para un run de tamaño LoRA. 0 apaga la serie.",
  "Stable-loss images": "Imágenes de pérdida estable",
  "Ordinary TRAINING images re-scored the same fixed way — the training curve without its sampling noise. They stay in training; 0 turns the series off.": "Imágenes de ENTRENAMIENTO corrientes re-puntuadas de la misma forma fija — la curva de entrenamiento sin su ruido de muestreo. Siguen en el entrenamiento; 0 apaga la serie.",
  "Some pictures are worth training on except for one rectangle: a watermark, a shop’s caption strip, a censor bar. Left alone, the model learns the rectangle along with the picture — a run over watermarked photographs reliably teaches the watermark. Throwing those pictures out costs the dataset; this keeps them and hides the rectangle from training instead.\n\nThe regions come from the boxes already on the tag: draw a box for `watermark` in the annotator (or let the watermark detector’s tag carry one), name the tag here, and every image carrying such a box trains with the loss inside it turned down. Where a subject tag has no drawn box, its detected faces stand in, exactly as they do for crop-aware training. An image whose named tags have no boxes trains completely normally — nothing is masked there.\n\nOnly the LOSS is masked. The pixels still pass through the image encoder, so the cached latents are the ordinary ones shared with unmasked runs, and nothing is re-encoded when this setting changes. The mask lives in latent space, where one cell covers 8×8 pixels rounded outward to whole cells — so it cannot hide anything much thinner than that, and a pixel-accurate outline is not something it can promise. It also cannot conjure what is UNDER the watermark: the model simply receives no signal about that area, from this picture.\n\nPairs naturally with a tag the prompt always includes (Always include under Tag selection): the prompt says the watermark is there, the mask stops the pixels teaching it, and at generation time the model has no reason to produce one unprompted.": "Algunas imágenes merecen entrenarse salvo por un rectángulo: una marca de agua, la franja de texto de una tienda, una barra de censura. Sin más, el modelo aprende el rectángulo junto con la imagen — un run sobre fotos con marca de agua enseña la marca de agua sin falta. Tirar esas imágenes cuesta conjunto de datos; esto las conserva y en su lugar esconde el rectángulo del entrenamiento.\n\nLas regiones salen de las cajas que la etiqueta ya tiene: dibuja una caja para `watermark` en el anotador (o deja que la etiqueta del detector de marcas de agua lleve una), nombra la etiqueta aquí, y cada imagen con una caja así entrena con la pérdida atenuada dentro. Donde una etiqueta de sujeto no tiene caja dibujada, entran sus caras detectadas, exactamente como en el recorte consciente de cajas. Una imagen cuyas etiquetas nombradas no tienen cajas entrena con total normalidad — ahí no se enmascara nada.\n\nSolo se enmascara la PÉRDIDA. Los píxeles siguen pasando por el codificador de imagen, así que los latentes en caché son los corrientes, compartidos con runs sin máscara, y nada se re-codifica cuando cambia este ajuste. La máscara vive en el espacio latente, donde una celda cubre 8×8 píxeles redondeados hacia fuera a celdas enteras — no puede esconder nada mucho más fino, y un contorno al píxel no es algo que pueda prometer. Tampoco puede inventar lo que hay BAJO la marca de agua: el modelo simplemente no recibe señal de esa zona, desde esta imagen.\n\nCasa de forma natural con una etiqueta que el prompt siempre incluye (Incluir siempre, en Selección de etiquetas): el prompt dice que la marca de agua está ahí, la máscara impide que los píxeles la enseñen, y al generar el modelo no tiene motivo para producir una sin que se la pidan.",
  "The same rule, stated once in the library instead of tag by tag here. A meta tag put on the tags whose boxes should never teach — `masked`, say — covers every such tag at once, including ones created after this job was written.\n\nThe list is resolved to tag names when the dataset is built, so the job’s log says how many images actually carried a masked region. A run where that line says zero has a rule pointing at tags nobody drew boxes for.": "La misma regla, dicha una vez en la biblioteca en lugar de etiqueta por etiqueta aquí. Una metaetiqueta puesta a las etiquetas cuyas cajas nunca deben enseñar — `masked`, por ejemplo — cubre todas esas etiquetas de una vez, incluidas las creadas después de escribir este trabajo.\n\nLa lista se resuelve a nombres de etiqueta al construir el conjunto de datos, así que el log del trabajo dice cuántas imágenes llevaban de verdad una región enmascarada. Un run donde esa línea dice cero tiene una regla apuntando a etiquetas sin cajas dibujadas.",
  "What a cell inside a masked box still counts for. 0 hides the region entirely, which is the usual choice for a watermark — there is nothing in it worth a whisper. A small value (0.05–0.2) keeps a faint signal, which can be worth it when the boxes are generous and cover real picture around the thing being hidden.\n\n1 is the unmasked loss, so setting it there is the same as clearing the tag lists. Where an image also trains with an alpha mask, the two multiply: a masked region on a transparent background is doubly not the picture.": "Cuánto cuenta todavía una celda dentro de una caja enmascarada. 0 oculta la región por completo, la elección habitual para una marca de agua — ahí no hay nada que valga un susurro. Un valor pequeño (0,05–0,2) conserva una señal tenue, lo que puede compensar cuando las cajas son generosas y cubren imagen real alrededor de lo que se esconde.\n\n1 es la pérdida sin máscara, así que ponerlo ahí es lo mismo que vaciar las listas de etiquetas. Si una imagen entrena además con máscara alfa, las dos se multiplican: una región enmascarada sobre fondo transparente es doblemente no-la-imagen.",
  "The training loss cannot answer the question people ask of it. It is drawn from the pictures being trained on, at a different random noise level every step, so it is noisy by construction — and it keeps falling for as long as the model memorizes, which means it looks healthiest exactly when a run has gone on too long.\n\nThis scores two extra series that can answer it, both with the plain per-sample loss on a fixed seed, so every round asks the model exactly the same questions and the number moves only when the model does. The series appear as their own lines on the loss graph, and each round is a line in the job’s log.\n\nReading it: the validation loss falls while the model generalizes and flattens or turns when it starts memorizing — the turning point is roughly where to stop, and with step snapshots on, the checkpoint to pick. Expect it to sit above the training loss and to move in small amounts; what matters is the direction, not the level. It stays comparable across pauses, resumes and step extensions, because the scored images and the seed never change within a job.": "La pérdida de entrenamiento no puede responder la pregunta que se le hace. Se extrae de las imágenes que se están entrenando, cada paso a un nivel de ruido aleatorio distinto, así que es ruidosa por construcción — y sigue bajando mientras el modelo memoriza, con lo que se ve más sana justo cuando un run ha durado de más.\n\nEsto puntúa dos series extra que sí pueden responderla, ambas con la pérdida simple por muestra y semilla fija, de modo que cada ronda hace al modelo exactamente las mismas preguntas y el número solo se mueve cuando el modelo se mueve. Las series aparecen como líneas propias en el gráfico de pérdida, y cada ronda es una línea en el log del trabajo.\n\nCómo leerla: la pérdida de validación baja mientras el modelo generaliza y se aplana o gira cuando empieza a memorizar — el punto de giro es más o menos dónde parar y, con snapshots de paso activados, el checkpoint que elegir. Cuenta con que quede por encima de la pérdida de entrenamiento y se mueva en cantidades pequeñas; lo que importa es la dirección, no el nivel. Sigue siendo comparable a través de pausas, reanudaciones y ampliaciones de pasos, porque las imágenes puntuadas y la semilla no cambian dentro de un trabajo.",
  "How often a round runs, in steps. A round costs one forward pass per scored image — no gradients, no optimizer — so a 16-image set is a few seconds; matching the sample or checkpoint cadence keeps the graph, the images and the snapshots telling one story at the same steps.\n\nVery frequent rounds buy little: overfitting announces itself over hundreds of steps, not five.": "Cada cuántos pasos corre una ronda. Una ronda cuesta una pasada hacia delante por imagen puntuada — sin gradientes, sin optimizador — así que un conjunto de 16 imágenes son unos segundos; igualar la cadencia de las muestras o los checkpoints hace que el gráfico, las imágenes y los snapshots cuenten una sola historia en los mismos pasos.\n\nRondas muy frecuentes aportan poco: el sobreajuste se anuncia a lo largo de cientos de pasos, no de cinco.",
  "How many images are set aside for the validation loss. They are taken OUT of training entirely — never visited, in no pool, their captions never seen — because a loss over pictures the model is also memorizing measures nothing. The pick is random but fixed per job, whole images at a time (a picture cannot be half in training), regularization pools are not eligible, and it is capped at half the dataset so the setting can never eat the run it protects.\n\nMore images make a steadier line at a linearly higher cost per round. On a small dataset every held-out image is also a training image lost, which is the real price — 8–16 is usually enough to see the turn, and the job’s log says exactly how many were held out.": "Cuántas imágenes se apartan para la pérdida de validación. Salen del entrenamiento por completo — nunca visitadas, en ningún pool, sus captions nunca vistas — porque una pérdida sobre imágenes que el modelo también está memorizando no mide nada. La elección es aleatoria pero fija por trabajo, por imágenes enteras (una imagen no puede estar medio en el entrenamiento), los pools de regularización no son elegibles, y tiene tope en la mitad del conjunto de datos para que el ajuste nunca se coma el run que protege.\n\nMás imágenes hacen una línea más estable a un coste por ronda linealmente mayor. En un conjunto pequeño cada imagen apartada es también una imagen de entrenamiento perdida, que es el precio real — 8–16 suelen bastar para ver el giro, y el log del trabajo dice exactamente cuántas se apartaron.",
  "A second series over ordinary TRAINING images: a fixed slice, re-scored with the same fixed seed each round. Nothing is held out — these stay in training — so it costs no data at all.\n\nWhat it shows is the training curve with the sampling noise removed. The per-step loss jumps around because every step draws different pictures at different noise levels; this line asks the same pictures at the same noise every time, so it is readable where the raw curve is a cloud. Compared against the held-out line it also localizes trouble: both falling is learning, stable falling while held-out rises is memorizing, and neither falling means the run is not learning at all.": "Una segunda serie sobre imágenes de ENTRENAMIENTO corrientes: una porción fija, re-puntuada cada ronda con la misma semilla fija. No se aparta nada — estas siguen entrenando — así que no cuesta ningún dato.\n\nLo que muestra es la curva de entrenamiento sin el ruido de muestreo. La pérdida por paso salta porque cada paso saca imágenes distintas a niveles de ruido distintos; esta línea pregunta cada vez lo mismo a las mismas imágenes, y se lee donde la curva cruda es una nube. Comparada con la línea apartada además localiza el problema: si bajan las dos, aprende; si la estable baja mientras la apartada sube, memoriza; si ninguna baja, el run no está aprendiendo nada.",
  "Save the current rules, or load a saved set": "Guardar las reglas actuales o cargar un conjunto guardado",
  "Rule sets": "Conjuntos de reglas",
  "Remember the current rules — name the set in this list afterwards": "Recordar las reglas actuales — nombra el conjunto en esta lista después",
  "Add a rule first": "Añade una regla primero",
  "Save current rules": "Guardar reglas actuales",
  "Add this set's rules to the job — rows it already has stay put": "Añadir las reglas de este conjunto al trabajo — las filas que ya tiene se quedan",
  "Value rules": "Reglas de valor",
  "Turn numeric value tags (height:172cm) into words at prompt time. The first matching rule wins — drag rows to reorder.": "Convierte etiquetas de valor numéricas (height:172cm) en palabras al componer el prompt. Gana la primera regla que coincida — arrastra las filas para reordenar.",
  "namespace, e.g. height": "espacio de nombres, p. ej. height",
  "Keep the raw tag in the prompt beside the rule's text": "Mantener la etiqueta cruda en el prompt junto al texto de la regla",
  "keep tag": "mantener etiqueta",
  "Remove this rule": "Quitar esta regla",
  "Add rule": "Añadir regla",
  "Any tag shaped `<name>:<number><unit>` is a value tag — `people:3`, `height:172cm`, `height:1.72m`, or a ranking’s own `quality:7` — and a rule here turns a range of those numbers into words at prompt time: where `height` is greater than 190cm, write `tall`. A raw `height:172cm` token teaches a text encoder nothing it can read back at generation time; a word does.\n\nA matching tag is replaced by the rule’s text, and a per-rule toggle keeps the raw tag alongside for whoever wants both spellings in the prompt. The metric length and mass families convert, so one rule covers `172cm` and `1.72m` alike; an unknown unit compares only against the same unit, and a plain number only against plain numbers.\n\nRanges may overlap, and the first matching rule wins — the rows are dragged into order, and that order is part of the configuration. A value tag no rule matches passes through the prompt unchanged, so nothing is dropped silently. The rule’s phrase rides the ordinary random pick and dropout like the tag it replaced: prompts sometimes carry it and sometimes do not, which is exactly the variation score-tag conditioning wants.\n\nThe rules are resolved when the dataset is built — the job’s log says how many tags they matched — and a set of rules can be saved and loaded by name, so a house vocabulary is written once and reused across jobs. Loading a set adds its missing rules to the job rather than replacing the rows already there.": "Cualquier etiqueta con la forma `<nombre>:<número><unidad>` es una etiqueta de valor — `people:3`, `height:172cm`, `height:1.72m`, o el `quality:7` de un ranking — y una regla aquí convierte un rango de esos números en palabras al componer el prompt: donde `height` sea mayor que 190cm, escribe `tall`. Un token crudo `height:172cm` no enseña nada que un codificador de texto pueda leer al generar; una palabra sí.\n\nUna etiqueta que coincide se reemplaza por el texto de la regla, y un interruptor por regla mantiene la etiqueta cruda al lado para quien quiera ambas formas en el prompt. Las familias métricas de longitud y masa se convierten, así que una regla cubre `172cm` y `1.72m` por igual; una unidad desconocida solo se compara con la misma unidad, y un número simple solo con números simples.\n\nLos rangos pueden solaparse y gana la primera regla que coincida — las filas se ordenan arrastrando, y ese orden es parte de la configuración. Una etiqueta de valor sin regla pasa al prompt sin cambios: nada se descarta en silencio. La frase de la regla sigue la selección aleatoria y el dropout como la etiqueta que reemplazó: los prompts a veces la llevan y a veces no, exactamente la variación que quiere el condicionamiento por puntuación.\n\nLas reglas se resuelven al construir el conjunto de datos — el registro del trabajo dice cuántas etiquetas coincidieron — y un conjunto de reglas puede guardarse y cargarse por nombre, de modo que un vocabulario propio se escribe una vez y se reutiliza entre trabajos. Cargar un conjunto añade las reglas que faltan en lugar de reemplazar las filas existentes.",
  "Write tags as":
    "Escribir etiquetas como",
  "Their name":
    "su nombre",
  "Their comment":
    "su comentario",
  "Name and comment":
    "nombre y comentario",
  "A tag's comment is the one line beside its name in the Tags tab — the same idea in words a text encoder can read. A tag with no comment is written as its name.":
    "El comentario de una etiqueta es la línea junto a su nombre en la pestaña Etiquetas: la misma idea en palabras que un codificador de texto puede leer. Una etiqueta sin comentario se escribe con su nombre.",
  "A tag's comment is the one line beside its name in the Tags tab — “one girl in the picture” for `1girl`, “from below, looking up at the subject” for `from_below`. A booru vocabulary is compact for the people typing it and opaque to a text encoder; the comment is the same idea in words the encoder can read.\n\n“Their name” is what every run did: the tag as it is spelled. “Their comment” writes the comment in place of the name wherever a picked tag has one, and “Name and comment” writes the name with the comment in brackets after it, so the model learns both spellings of one thing. A tag with no comment is written as its name whatever this says.\n\nOnly the PROMPT changes. Matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all stay keyed on the tag's name, exactly as with aliases — and the comment is read from the library when the dataset is built, so editing a comment later changes the next run, not this one.":
    "El comentario de una etiqueta es la línea junto a su nombre en la pestaña Etiquetas: «una chica en la imagen» para `1girl`, «desde abajo, mirando al sujeto» para `from_below`. Un vocabulario booru es compacto para quien lo escribe y opaco para un codificador de texto; el comentario es la misma idea en palabras que el codificador puede leer.\n\n«Su nombre» es lo que hacía cada entrenamiento: la etiqueta tal como se escribe. «Su comentario» escribe el comentario en lugar del nombre donde una etiqueta elegida tiene uno, y «Nombre y comentario» escribe el nombre con el comentario entre paréntesis, para que el modelo aprenda ambas formas de decir lo mismo. Una etiqueta sin comentario se escribe con su nombre en cualquier caso.\n\nSolo cambia el PROMPT. La coincidencia, las listas de siempre/excluir, el equilibrio por frecuencia, el peso de la pérdida y las cajas que un recorte debe conservar siguen ligados al nombre de la etiqueta, exactamente como con los alias; y el comentario se lee de la biblioteca al construir el conjunto de datos, así que editarlo después cambia el siguiente entrenamiento, no este.",
  "Remove the selected images?": "¿Eliminar las imágenes seleccionadas?",
  "They cannot be recovered.": "No se pueden recuperar.",
  "Delete all {n} results from this session?": "¿Eliminar los {n} resultados de esta sesión?",
  "The generated images go with them.": "Las imágenes generadas se van con ellos.",
  "Its downloaded weights can go with it, or stay in the cache for a later download to find.": "Sus pesos descargados pueden irse con él o quedarse en la caché para que una descarga posterior los encuentre.",
  "Remove and delete weights": "Quitar y eliminar los pesos",
  "Remove the training job “{name}”?": "¿Eliminar el trabajo de entrenamiento “{name}”?",
  "Remove {n} training jobs?": "¿Eliminar {n} trabajos de entrenamiento?",
  "Its checkpoints, test samples and trained result are deleted with it — except anything locked, which is kept in the LoRAs list. This cannot be undone.": "Se eliminan con él sus puntos de control, muestras y resultado entrenado, y esto no se puede deshacer. Salvo lo que esté bloqueado, que se conserva en la lista de LoRAs.",
  "Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone.": "Se eliminan con ellos sus puntos de control, muestras y resultados entrenados, y esto no se puede deshacer. Salvo lo que esté bloqueado, que se conserva en la lista de LoRAs.",
  "The Train tab": "La pestaña Entrenar",
  "The Evaluate tab": "La pestaña Evaluar",
  "The Models tab": "La pestaña Modelos",
  "Your models": "Tus modelos",
  "Finetunes": "Finetunes",
  "Based on {model}": "Basado en {model}",
  "A full finetune of {model}": "Un finetune completo de {model}",
  "The built-in release, one of your own models, or a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.": "La versión integrada, uno de tus propios modelos o los pesos de un finetune completo en lugar de los del modelo base. Los adaptadores se apilan sobre lo que se elija aquí.",
};

export default CATALOG;
