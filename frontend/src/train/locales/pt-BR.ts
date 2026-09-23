// uses live in the APP catalog; this file holds only train-chunk strings.

import type { Catalog } from "../../shared/i18nCore";

const CATALOG: Catalog = {
  "default":
    "padrão",
  "This model's own size. A job set to it follows whichever model it is pointed at.":
    "O tamanho do próprio modelo. Uma execução definida nele segue o modelo para o qual aponta.",
  "{n} px":
    "{n} px",
  "A run trains at one size at least.":
    "Uma execução treina em pelo menos um tamanho.",
  "A run trains at up to five sizes — each one is another pass over the dataset per epoch.":
    "Uma execução treina em no máximo cinco tamanhos — cada um é mais uma passagem pelo conjunto de dados por época.",
  "e.g. 704":
    "ex.: 704",
  "Another size…":
    "Outro tamanho…",
  "Pick every size this run should train at. A picture joins each one it is big enough for, so the same picture can be learnt at more than one scale — and each size is another pass over the dataset per epoch.":
    "Escolha cada tamanho em que esta execução deve treinar. Uma imagem entra em todo tamanho para o qual seja grande o bastante, então a mesma imagem é aprendida em mais de uma escala — e cada tamanho é mais uma passagem pelo conjunto de dados por época.",
  "Left empty both fields use the model's own size — a test sample is not tied to the sizes the run trains at.":
    "Vazios, os dois campos usam o tamanho do próprio modelo — uma imagem de teste não está presa aos tamanhos em que a execução treina.",
  "The sizes images are trained at, each given as one number that stands for a pixel budget: 1024 means 'about a megapixel', which every aspect-ratio bucket then spends differently — 1024×1024, or 1216×832, or 832×1216.\n\nMatch them to what the base model was trained on (1024 for SDXL, Chroma and FLUX.2, 512 for SD 1.5); training far above that teaches little and costs a lot, while training below it is a genuine speed and memory lever at the price of fine detail. Cost scales with the area, so 768 is nearly half the work per step that 1024 is. The size the list marks as default is the model's own, and a job set to it follows whichever model it is pointed at.\n\nPicking more than one trains the same pictures at each of them. A model that has only ever seen a subject at 1024 has learnt it together with the canvas it was on: asked for something smaller it tends to answer with a crop or a doubled-up version of the same framing. Several sizes separate what the model learns about the subject from what it learns about the shape of the picture.\n\nEach size is a full family of buckets, and every image joins the ones it is large enough for — which is the other half of what this is for. Under Never upscale a 700-pixel scan is simply left out of a 1024 run; add 512 and it trains there instead of being dropped, while the large pictures keep training at both.\n\nIt is not free. A size is another pass over the dataset in every epoch and another cached latent per picture, and the batches at the largest one decide the peak memory — so adding a size above the others raises what the run needs on the card, and adding ones below mainly makes an epoch longer. Two or three an octave apart (512, 768, 1024) is the usual shape; at most five.":
    "Os tamanhos em que as imagens são treinadas, cada um dado como um número que representa um orçamento de pixels: 1024 significa 'cerca de um megapixel', que cada bucket de proporção gasta de um jeito diferente — 1024×1024, ou 1216×832, ou 832×1216.\n\nCombine-os com aquilo em que o modelo base foi treinado (1024 para SDXL, Chroma e FLUX.2, 512 para SD 1.5); treinar muito acima disso ensina pouco e custa caro, enquanto treinar abaixo é uma alavanca real de velocidade e memória ao preço do detalhe fino. O custo escala com a área, então 768 é quase metade do trabalho por passo que 1024. O tamanho que a lista marca como padrão é o do próprio modelo, e uma execução definida nele segue o modelo para o qual aponta.\n\nEscolher mais de um treina as mesmas imagens em cada um deles. Um modelo que só viu um motivo em 1024 o aprendeu junto com a tela em que ele estava: se você pedir algo menor, ele costuma responder com um recorte ou uma versão duplicada do mesmo enquadramento. Vários tamanhos separam o que o modelo aprende sobre o motivo do que ele aprende sobre a forma da imagem.\n\nCada tamanho é uma família completa de buckets, e cada imagem entra naquelas para as quais é grande o bastante — a outra metade do propósito disto. Com 'Nunca ampliar', uma digitalização de 700 pixels simplesmente fica de fora de uma execução em 1024; acrescente 512 e ela treina ali em vez de ser descartada, enquanto as imagens grandes seguem treinando em ambos.\n\nNão sai de graça. Um tamanho é mais uma passagem pelo conjunto de dados a cada época e mais um latente em cache por imagem, e os lotes do maior decidem o pico de memória — então acrescentar um tamanho acima dos outros aumenta o que a execução exige da placa, e acrescentar outros abaixo alonga principalmente a época. Dois ou três a uma oitava de distância (512, 768, 1024) é a forma usual; no máximo cinco.",
  "An image smaller than its bucket has to be enlarged to train at that size, and enlarging invents detail that was never in the picture: soft edges, smeared texture, the interpolation's own look. Trained on, that is what the model learns the subject looks like.\n\nThis is on by default. Those images are left out while the dataset is built — before anything is encoded, so they cost no time and no cache — and the run says how many it dropped. It is asked per resolution, so a picture too small for the largest size still trains at a smaller one rather than being dropped from the run; turn it off for a small dataset, where a slightly soft picture is usually worth more than no picture.":
    "Uma imagem menor que o seu bucket precisa ser ampliada para treinar naquele tamanho, e ampliar inventa detalhe que nunca esteve na imagem: bordas moles, textura borrada, a cara da própria interpolação. Treinado nisso, é o que o modelo aprende que o motivo parece.\n\nIsto vem ligado. Essas imagens ficam de fora enquanto o conjunto de dados é construído — antes de qualquer codificação, então não custam tempo nem cache — e a execução diz quantas descartou. É perguntado por resolução, então uma imagem pequena demais para o maior tamanho ainda treina em um menor em vez de sair da execução; desligue para um conjunto pequeno, onde uma imagem um pouco mole costuma valer mais que imagem nenhuma.",
  "New training job": "Novo trabalho de treinamento",
  "Drafts": "Rascunhos",
  "Paused": "Pausados",
  "Completed": "Concluídos",
  "Failed": "Falharam",
  "Full finetune": "Finetune completo",
  "Loss appears here once training starts.": "A perda aparece aqui quando o treinamento começar.",
  "Test samples": "Amostras de teste",
  "Select a job to see its progress, samples and settings.": "Selecione um trabalho para ver seu progresso, amostras e configurações.",
  "No training jobs yet. Create one to fine-tune a model (LoRA or full) on images selected straight from your library.": "Ainda sem trabalhos de treinamento. Crie um para afinar um modelo (LoRA ou completo) com imagens selecionadas direto da sua biblioteca.",
  "Training environment not set up": "Ambiente de treinamento não configurado",
  "Edit training job": "Editar trabalho de treinamento",
  "Save draft": "Salvar rascunho",
  "Save & queue": "Salvar e enfileirar",
  "Method": "Método",
  "Hyperparameters": "Hiperparâmetros",
  "Memory & speed": "Memória e velocidade",
  "Canceled before any image was generated": "Cancelado antes de gerar qualquer imagem",
  "{done} of {total} images": "{done} de {total} imagens",
  "not generated yet": "ainda não gerado",
  "Download this LoRA": "Baixar este LoRA",
  "NVIDIA only": "Só NVIDIA",
  "Off (fused kernels)": "Desativado (kernels fundidos)",
  "On (save VRAM)": "Ativado (economiza VRAM)",
  "needs an NVIDIA GPU": "precisa de uma GPU NVIDIA",
  "needs an NVIDIA GPU (Ada or newer)": "precisa de uma GPU NVIDIA (Ada ou mais nova)",
  "this model has none": "este modelo não tem",
  "8-bit float (fp8)": "float de 8 bits (fp8)",
  "8-bit (int8)": "8 bits (int8)",
  "FLUX.2 Klein (base, 4B)": "FLUX.2 Klein (base, 4B)",
  "Images are being generated": "As imagens estão sendo geradas",
  "= 1 image": "= 1 imagem",
  "= {n} images": { one: "= {n} imagem", other: "= {n} imagens" },
  "Length & learning rate": "Duração e taxa de aprendizado",
  "Dataset": "Conjunto de dados",
  "Add query": "Adicionar consulta",
  "Remove query": "Remover consulta",
  "invalid query": "consulta inválida",
  "Empty query = every image in the library.": "Consulta vazia = todas as imagens da biblioteca.",
  "Total steps": "Passos totais",
  "Learning rate": "Taxa de aprendizado",
  "Batch size": "Tamanho do lote",
  "Gradient accumulation": "Acumulação de gradiente",
  "Rank": "Rank",
  "Train text encoder": "Treinar o codificador de texto",
  "Checkpoints": "Checkpoints",
  "Checkpoint every": "Checkpoint a cada",
  "Cache latents": "Cachear latentes",
  "Random crop": "Recorte aleatório",
  "Resolutions":
    "Resoluções",
  "Crops & flips":
    "Cortes e espelhamento",
  "Max aspect ratio": "Proporção máxima",
  "Horizontal flip probability": "Probabilidade de espelhamento horizontal",
  "Trigger word": "Palavra-gatilho",
  "Only captions tagged": "Só legendas marcadas",
  "Skip captions tagged": "Pular legendas marcadas",
  "Only instructions tagged": "Só instruções marcadas",
  "Skip instructions tagged": "Pular instruções marcadas",
  "Comma-separated meta tags whose instructions are never used. Applied after the include list, so it also removes instructions the list let in.": "Meta tags separadas por vírgulas cujas instruções nunca são usadas. Aplicado depois da lista de inclusão, então também remove instruções que a lista deixou entrar.",
  "Comma-separated meta tags whose captions are never used. Applied after the include list, so it also removes captions the list let in.": "Meta tags separadas por vírgulas cujas legendas nunca são usadas. Aplicado depois da lista de inclusão, então também remove legendas que a lista deixou entrar.",
  "Always include": "Sempre incluir",
  "Skip tag groups tagged": "Pular grupos de tags marcados",
  "Comma-separated meta tags naming whole tag groups to ignore: a tag placed only in such a group never reaches a prompt. The tags stay on your items.": "Meta tags separadas por vírgulas nomeando grupos de tags inteiros a ignorar: uma tag colocada só em tal grupo nunca chega a um prompt. As tags ficam nos seus itens.",
  "Min tags per prompt": "Mínimo de tags por prompt",
  "Max tags per prompt": "Máximo de tags por prompt",
  "Pick probability": "Probabilidade de sorteio",
  "Uniform": "Uniforme",
  "Balance rare tags": "Equilibrar tags raras",
  "Frequency measured in": "Frequência medida em",
  "Training data": "Dados de treinamento",
  "Previous step": "Passo anterior",
  "Next step": "Próximo passo",
  "(empty prompt)": "(prompt vazio)",
  "Show each step's min/max micro-batch loss": "Mostrar a perda mín/máx de micro-lote de cada passo",
  "Expand graph": "Expandir gráfico",
  "Collapse graph": "Recolher gráfico",
  "steps/s": "passos/s",
  "Smooth the line (EMA)": "Suavizar a linha (EMA)",
  "Whole library": "Biblioteca inteira",
  "Weight loss by tag rarity": "Ponderar a perda pela raridade da tag",
  "Shuffle tag order": "Embaralhar a ordem das tags",
  "Caption dropout": "Dropout de legendas",
  "Generate every": "Gerar a cada",
  "Negative prompt": "Prompt negativo",
  "Nothing (trigger word only)": "Nada (apenas a palavra-gatilho)",
  "Every prompt is the trigger word and nothing else, so every selected picture is in the run whatever it carries. Tag and caption selection do not apply.": "Cada prompt é apenas a palavra-gatilho, então toda imagem selecionada entra no treino, seja lá o que ela carregue. A seleção de tags e legendas não se aplica.",
  "Every prompt would be EMPTY — with no text at all, there is nothing for the model to bind what it sees to. Set a trigger word below.": "Cada prompt ficaria VAZIO — sem texto algum, o modelo não tem a que ligar o que vê. Defina uma palavra-gatilho abaixo.",
  "Caption + tags": "Legenda + tags",
  "Pause (saves a checkpoint)": "Pausar (salva um checkpoint)",
  "{d} trained": "{d} treinado",
  "Training started": "Treinamento iniciado",
  "Training resumed": "Treinamento retomado",
  "Training paused": "Treinamento pausado",
  "Training completed": "Treinamento concluído",
  "Training failed": "Treinamento falhou",
  "Training canceled": "Treinamento cancelado",
  "Baseline before training": "Referência antes do treinamento",
  "Checkpoint": "Checkpoint",
  "Download checkpoint": "Baixar checkpoint",
  "Delete checkpoint": "Excluir checkpoint",
  "Delete this checkpoint from disk?": "Excluir este checkpoint do disco?",
  "Extend steps": "Ampliar passos",
  "Edit steps": "Editar passos",
  "Base model": "Modelo base",
  "LoRAs": "LoRAs",
  "Edit this model": "Editar este modelo",
  "Edit model": "Editar modelo",
  "Edit LoRA": "Editar LoRA",
  "Edit this LoRA": "Editar este LoRA",
  "Unlock": "Desbloquear",
  "Lock": "Bloquear",
  "Unlock — deleting the job will take this LoRA with it": "Desbloquear — excluir o trabalho levará este LoRA junto",
  "Lock — keeps this LoRA when the job is deleted": "Bloquear — mantém este LoRA quando o trabalho for excluído",
  "Lock — protects this checkpoint from deletion, from the keep-last rule, and from the job being deleted": "Bloquear — protege este checkpoint da exclusão, da regra de manter os últimos e da exclusão do trabalho",
  "Add LoRA": "Adicionar LoRA",
  "Click to use this value for the next generation": "Clique para usar este valor na próxima geração",
  "Output": "Saída",
  "Size presets": "Tamanhos predefinidos",
  "Random seed": "Semente aleatória",
  "A new seed is drawn each time you click Generate; the field below shows the seed used for the last generation.": "Uma semente nova é sorteada cada vez que você clica em Gerar; o campo abaixo mostra a semente usada na última geração.",
  "Remove this generation and its images?": "Remover esta geração e suas imagens?",
  "Open the image in a new tab": "Abrir a imagem em uma nova aba",
  "Remove the selected images? They cannot be recovered.": "Remover as imagens selecionadas? Elas não podem ser recuperadas.",
  "Remove the selected images (a generation that is still running stays)": "Remover as imagens selecionadas (uma geração ainda em andamento permanece)",
  "Stop the selected generations (the images they have made are kept)": "Parar as gerações selecionadas (as imagens já criadas são mantidas)",
  "Put every setting that made this picture into the form": "Colocar no formulário todas as configurações que geraram esta imagem",
  "Use all settings": "Usar todas as configurações",
  "Preview the selected image (Space)": "Visualizar a imagem selecionada (Espaço)",
  "Image {i} of {n}": "Imagem {i} de {n}",
  "Up next": "A seguir",
  "Add to the queue": "Adicionar à fila",
  "A training job is running": "Há um trabalho de treinamento em execução",
  "Drag to change the queue order": "Arraste para mudar a ordem da fila",
  "How the drafts below are ordered":
    "Como os rascunhos abaixo são ordenados",
  "Newest first":
    "Mais recentes primeiro",
  "Manual order":
    "Ordem manual",
  "Drag to reorder — or into Up next to queue the job":
    "Arraste para reordenar — ou para A seguir para enfileirar o trabalho",
  "Remove every finished job, with its checkpoints and samples":
    "Remover todos os trabalhos concluídos, com seus checkpoints e amostras",
  "Drag into Up next to queue the job": "Arraste para A seguir para enfileirar o trabalho",
  "Drop here to put the job on hold.": "Solte aqui para deixar o trabalho em espera.",
  "Prepare": "Preparar",
  "Keep the last": "Manter os últimos",
  "When a new snapshot is written the oldest of these is deleted, so the window never grows. A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk. The resumable checkpoint is kept outside this limit and never counts against it.": "Quando um instantâneo novo é gravado, o mais antigo destes é apagado, então a janela nunca cresce. Um instantâneo de LoRA é pequeno (dezenas de MB) e você pode manter tranquilamente uma dúzia; um instantâneo de finetune completo é do tamanho do modelo inteiro, então dois ou três já são muito disco. O checkpoint retomável é mantido fora deste limite e nunca conta contra ele.",
  "Also keep one in": "Manter também um a cada",
  "A rolling window at the end of the run. 0 keeps none by recency.": "Uma janela rotativa no fim da execução. 0 não mantém nenhum por recência.",
  "Kept for good, on top of the window above.": "Mantidos para sempre, além da janela acima.",
  "A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk.": "Um instantâneo de LoRA é pequeno (dezenas de MB) e você pode manter tranquilamente uma dúzia; um instantâneo de finetune completo é do tamanho do modelo inteiro, então dois ou três já são muito disco.",
  "in 1 step": "em 1 passo",
  "in {n} steps": { one: "em {n} passo", other: "em {n} passos" },
  "Keep as checkpoint": "Manter como checkpoint",
  "Backward": "Para trás",
  "warmup": "aquecimento",
  "Settings changed": "Configurações alteradas",
  "Dataset changed": "Conjunto de dados alterado",
  "{n} items added":
    { one: "{n} item adicionado", other: "{n} itens adicionados" },
  "{n} items removed":
    { one: "{n} item removido", other: "{n} itens removidos" },
  "Measured over the last steps of this run": "Medido nos últimos passos desta execução",
  "about {d} left": "faltam cerca de {d}",
  "The images this run trains on, sorted into aspect-ratio buckets": "As imagens com que esta execução treina, ordenadas em buckets de proporção",
  "{n} images": { one: "{n} imagem", other: "{n} imagens" },
  "{n} from video": { one: "{n} de vídeo", other: "{n} de vídeo" },
  "{n} buckets": { one: "{n} bucket", other: "{n} buckets" },
  "Training job settings": "Configurações do trabalho de treinamento",
  "Save as new job": "Salvar como novo trabalho",
  "Hide system statistics": "Ocultar estatísticas do sistema",
  "Show system statistics": "Mostrar estatísticas do sistema",
  "loading model": "carregando modelo",
  "caching latents": "cacheando latentes",
  "Degradation": "Degradação",
  "Add variant": "Adicionar variante",
  "Remove every variant from this job": "Remover todas as variantes deste trabalho",
  "Remove this variant": "Remover esta variante",
  "JPEG re-encode": "Recodificação JPEG",
  "Video codec (h264 / h265)": "Codec de vídeo (h264 / h265)",
  "Resolution loss": "Perda de resolução",
  "JPEG": "JPEG",
  "video codec": "codec de vídeo",
  "resolution loss": "perda de resolução",
  "Chroma subsampling": "Subamostragem de croma",
  "How much color detail is thrown away. 4:2:0 is what almost every real JPEG uses.": "Quanto detalhe de cor é jogado fora. 4:2:0 é o que quase todo JPEG real usa.",
  "Codec": "Codec",
  "CRF": "CRF",
  "The codec's quality number, counting the other way round: HIGHER is worse. Above about 32 a frame visibly falls apart.": "O número de qualidade do codec, contando ao contrário: MAIS ALTO é pior. Acima de cerca de 32 um quadro se desfaz visivelmente.",
  "Scale": "Escala",
  "Nearest gives the hard, blocky look of a badly upscaled screenshot; bilinear the soft one.": "Vizinho mais próximo dá o visual duro e quadriculado de uma captura mal ampliada; bilinear, o suave.",
  "Bilinear": "Bilinear",
  "Bicubic": "Bicúbico",
  "Lanczos": "Lanczos",
  "Passes": "Passagens",
  "Visits per clean visit": "Visitas por visita limpa",
  "How often this variant is drawn beside the picture it was made from. 0.25 = one degraded visit per four clean ones.": "Com que frequência esta variante é sorteada ao lado da imagem da qual foi feita. 0.25 = uma visita degradada a cada quatro limpas.",
  "Cached variations per picture": "Variações em cache por imagem",
  "How many separately-drawn values each picture gets. 1 already spreads the range across the dataset; more spreads it within one picture, and multiplies the cache.": "Quantos valores sorteados separadamente cada imagem recebe. 1 já espalha a faixa pelo conjunto de dados; mais a espalha dentro de uma imagem, e multiplica o cache.",
  "jpeg_artifacts, low_quality": "jpeg_artifacts, low_quality",
  "Always in this sample's prompt: never dropped by the random tag pick, the tag cap, or caption dropout.": "Sempre no prompt desta amostra: nunca descartadas pelo sorteio aleatório de tags, pelo teto de tags nem pelo dropout de legendas.",
  "Remove tags if present": "Remover tags se presentes",
  "masterpiece, absurdres": "masterpiece, absurdres",
  "Which pictures": "Quais imagens",
  "Only pictures tagged": "Só imagens marcadas",
  "Never pictures tagged": "Nunca imagens marcadas",
  "Wins over the line above. Use it to leave pictures alone that are already marked as poor.": "Ganha da linha acima. Use para deixar em paz imagens já marcadas como ruins.",
  "The preview failed": "A pré-visualização falhou",
  "Select an item in the library to preview this on.": "Selecione um item na biblioteca sobre o qual pré-visualizar isto.",
  "gentlest": "mais suave",
  "harshest": "mais duro",
  "Variants": "Variantes",
  "Save the current variants, or load a saved set": "Salvar as variantes atuais, ou carregar um conjunto salvo",
  "Save current variants": "Salvar variantes atuais",
  "Add a variant first": "Adicione primeiro uma variante",
  "Load this set, replacing the variants in this job": "Carregar este conjunto, substituindo as variantes deste trabalho",
  "Of every 100 visits to a picture this applies to, {clean} are clean and the rest are degraded: {parts}.": "De cada 100 visitas a uma imagem à qual isto se aplica, {clean} são limpas e o resto degradadas: {parts}.",
  "A variant with a tag filter applies to fewer pictures than the queries select, so its share is of those.": "Uma variante com filtro de tags se aplica a menos imagens do que as consultas selecionam, então sua parte é dessas.",
  "About {n} degraded files will be cached.": "Cerca de {n} arquivos degradados serão armazenados em cache.",
  "Preset": "Preset",
  "Presets": "Presets",
  "Preset name": "Nome do preset",
  "Save these settings as a preset, or load one": "Salvar estas configurações como preset, ou carregar um",
  "Save current settings": "Salvar configurações atuais",
  "Start new jobs from this preset": "Iniciar novos trabalhos a partir deste preset",
  "Delete this preset": "Excluir este preset",
  "Cosine": "Cosseno",
  "Base models": "Modelos base",
  "1 result": "1 resultado",
  "{n} results": { one: "{n} resultado", other: "{n} resultados" },
  "Delete every result in this session": "Excluir todos os resultados desta sessão",
  "Delete all {n} results from this session? The generated images go with them.": "Excluir os {n} resultados desta sessão? As imagens geradas vão com eles.",
  "sampling": "amostrando",
  "What does this do?": "O que isto faz?",
  "This model's repository is gated: accept its license on the model page and set a Hugging Face access token, or the download will fail.": "O repositório deste modelo é restrito: aceite a licença na página do modelo e defina um token de acesso do Hugging Face, ou o download vai falhar.",
  "Click to use this prompt for the next generation": "Clique para usar este prompt na próxima geração",
  "(no prompt)": "(sem prompt)",
  "Click to use this negative prompt for the next generation": "Clique para usar este prompt negativo na próxima geração",
  "Time so far, including loading the model": "Tempo até agora, incluindo o carregamento do modelo",
  "Total time, including loading the model": "Tempo total, incluindo o carregamento do modelo",
  "Remove from the queue": "Remover da fila",
  "Select to copy": "Selecione para copiar",
  "generation failed": "a geração falhou",
  "Sampler steps": "Passos do sampler",
  "CFG scale": "Escala CFG",
  "This model isn't downloaded yet, and downloads are switched off": "Este modelo ainda não foi baixado, e os downloads estão desativados",
  "Loss": "Perda",
  "LoRA only": "Só LoRA",
  "Native training resolution of these weights. Leave empty for the architecture's own.": "Resolução nativa de treinamento destes pesos. Vazio usa a própria da arquitetura.",
  "Includes 1 model you added.": "Inclui 1 modelo que você adicionou.",
  "Includes": "Inclui",
  "models you added.": "modelos que você adicionou.",
  "Open this model's page on Hugging Face": "Abrir a página deste modelo no Hugging Face",
  "Remove this model": "Remover este modelo",
  "Based on": "Baseado em",
  "/path/to/model (diffusers folder or .safetensors)": "/path/to/model (diffusers folder or .safetensors)",
  "owner/repo": "owner/repo",
  "Add model": "Adicionar modelo",
  "On disk": "Em disco",
  "Path missing": "Caminho ausente",
  "Continue this download where it stopped": "Continuar este download de onde parou",
  "Partly downloaded": "Parcialmente baixado",
  "Discard partial download": "Descartar download parcial",
  "This path no longer exists": "Este caminho não existe mais",
  "Remove from the list (the file is left alone)": "Remover da lista (o arquivo fica em paz)",
  "The base model this LoRA was trained for": "O modelo base para o qual este LoRA foi treinado",
  "/path/to/lora.safetensors": "/path/to/lora.safetensors",
  "Download this checkpoint": "Baixar este checkpoint",
  "Delete this checkpoint from disk": "Excluir este checkpoint do disco",
  "Relative sampling probability: a weight-2 query's images are drawn twice as often as a weight-1 query's.": "Probabilidade de amostragem relativa: as imagens de uma consulta de peso 2 são sorteadas duas vezes mais que as de uma de peso 1.",
  "Steps": "Passos",
  "Text encoder": "Codificador de texto",
  "trained": "treinado",
  "Prompts": "Prompts",
  "Samples": "Amostras",
  "Training log": "Registro de treinamento",
  "No output yet.": "Ainda sem saída.",
  "about {v} of GPU memory": "cerca de {v} de memória de GPU",
  "more than this machine's {m}": "mais que os {m} desta máquina",
  "e.g. watercolor style LoRA": "p. ex. LoRA de estilo aquarela",
  "Model-specific": "Específico do modelo",
  "Optimization": "Otimização",
  "LR schedule": "Cronograma de LR",
  "Constant": "Constante",
  "Linear decay": "Decaimento linear",
  "Constant + warmup": "Constante + aquecimento",
  "Warmup steps": "Passos de aquecimento",
  "Ramp the learning rate up over the first N steps. Leave empty for no warmup.": "Sobe a taxa de aprendizado em rampa nos primeiros N passos. Vazio = sem aquecimento.",
  "bf16 is the safe modern default. fp32 doubles memory (automatic fallback on Macs without bf16); avoid fp16 for training.": "bf16 é o padrão moderno e seguro. fp32 dobra a memória (reserva automática em Macs sem bf16); evite fp16 para treinar.",
  "Makes sampling, crops and tag picks reproducible.": "Torna amostragem, recortes e sorteios de tags reproduzíveis.",
  "LoRA": "LoRA",
  "Scales the adapter's effect; the common convention is alpha = rank. Lower alpha = weaker influence at the same rank.": "Escala o efeito do adaptador; a convenção comum é alpha = rank. Alpha mais baixo = influência mais fraca no mesmo rank.",
  "Helps the model learn a NEW trigger word, at higher overfitting risk. Guarded: it uses a lower learning rate and stops partway through training.": "Ajuda o modelo a aprender uma palavra-gatilho NOVA, com maior risco de sobreajuste. Protegido: usa uma taxa de aprendizado menor e para no meio do treinamento.",
  "Text encoder LR": "LR do codificador de texto",
  "Left empty: half the main learning rate.": "Vazio: metade da taxa principal.",
  "Stop TE after": "Parar o TE após",
  "Include the large encoder": "Incluir o codificador grande",
  "T5-XXL, the encoder that reads the whole prompt — most of the memory and most of the effect. Unticked, only the small CLIP-L trains: cheap, and what most FLUX LoRA tools mean by training the text encoder.": "T5-XXL, o codificador que lê o prompt inteiro — a maior parte da memória e do efeito. Desmarcado, só o pequeno CLIP-L treina: barato, e o que a maioria das ferramentas de LoRA para FLUX chama de treinar o codificador de texto.",
  "of total steps": "dos passos totais",
  "Keep step snapshots": "Manter instantâneos de passo",
  "Save a permanent snapshot every N steps, so the best-looking step can be picked afterwards. Off: only the resumable 'last' checkpoint is kept.": "Salva um instantâneo permanente a cada N passos, para o passo mais bonito poder ser escolhido depois. Desativado: só o checkpoint retomável 'last' é mantido.",
  "Gradient checkpointing": "Checkpointing de gradiente",
  "Trades ~25% speed for a large VRAM saving. Recommended for full finetunes and big models.": "Troca ~25% de velocidade por uma grande economia de VRAM. Recomendado para finetunes completos e modelos grandes.",
  "Attention slicing": "Fatiamento de atenção",
  "Half-precision master weights": "Pesos mestres em meia precisão",
  "Keeps the trained weights and their gradients at 16 bits instead of 32. What the rounding drops is carried to the next update, so the run learns what it would have learned; the cost is one more buffer of the same width.":
    "Mantém os pesos treinados e seus gradientes em 16 bits em vez de 32. O que o arredondamento descarta é levado para a próxima atualização, então o treino aprende o que teria aprendido; o custo é mais um buffer da mesma largura.",
  "only for a full finetune": "apenas para um finetuning completo",
  "nothing to halve at full precision": "nada a reduzir pela metade em precisão total",
  "Prodigy cannot be stepped one weight at a time": "o Prodigy não pode ser executado peso a peso",
  "Base model quantization": "Quantização do modelo base",
  "None (full precision)": "Nenhuma (precisão completa)",
  "4-bit (NF4)": "4 bits (NF4)",
  "Optimizer": "Otimizador",
  "Images are sorted into width/height buckets of equal area so nothing gets squashed. This caps how extreme the buckets get (2 = up to 2:1 and 1:2).": "As imagens são ordenadas em buckets de largura/altura de igual área para nada ser amassado. Isto limita o quão extremos os buckets ficam (2 = até 2:1 e 1:2).",
  "Never flip images whose tags are marked": "Nunca espelhar imagens cujas tags estejam marcadas",
  "Comma-separated META tags. Any tag the library marks with one of these switches mirroring off for the pictures carrying that tag — so the rule is stated once in the Tags tab rather than listed here.": "Meta tags separadas por vírgulas. Qualquer tag que a biblioteca marque assim desliga o espelhamento nas imagens que a carregam — a regra fica dita uma vez na aba Tags em vez de listada aqui.",
  "Always include tags marked": "Sempre incluir tags marcadas",
  "Comma-separated META tags. Any tag the library marks with one of these is never dropped by the random pick — again, only where the image actually has that tag.": "Meta tags separadas por vírgulas. Qualquer tag que a biblioteca marque assim nunca é descartada pelo sorteio — de novo, só onde a imagem realmente tem essa tag.",
  "Exclude tags marked": "Excluir tags marcadas",
  "Comma-separated META tags. Any tag the library marks with one of these is stripped from prompts.": "Meta tags separadas por vírgulas. Qualquer tag que a biblioteca marque assim é retirada dos prompts.",
  "Remove tags marked": "Remover tags marcadas",
  "Comma-separated META tags. Any tag the library marks with one of these comes off this sample.": "Meta tags separadas por vírgulas. Qualquer tag que a biblioteca marque assim sai desta amostra.",
  "Only pictures whose tags are marked": "Somente imagens cujas tags estejam marcadas",
  "Comma-separated META tags — the same rule as the line above, said once in the library rather than tag by tag here.": "Meta tags separadas por vírgulas — a mesma regra da linha acima, dita uma vez na biblioteca em vez de tag por tag aqui.",
  "Never pictures whose tags are marked": "Nunca imagens cujas tags estejam marcadas",
  "Comma-separated META tags. Wins over both lines above.": "Meta tags separadas por vírgulas. Prevalece sobre as duas linhas acima.",
  "The same veto, said once in the library instead of tag by tag here. Any tag the Tags tab marks with one of these meta tags switches mirroring off for every picture carrying that tag.\n\nIt is worth the indirection for the reason a list of names goes stale: “text”, “logo”, “signature”, “left-handed”, a dozen characters with an eyepatch — the list in a job's settings is right the day it is written and wrong the next time somebody adds a tag it should have held. Marking the tags themselves puts the fact where the tag is, so a tag added later carries it into every run automatically, and a job written before that tag existed still does the right thing.\n\nBoth lists apply: a picture is left unmirrored if it carries a tag named above OR a tag marked here.":
    "O mesmo veto, dito uma vez na biblioteca em vez de tag por tag aqui. Qualquer tag que a aba Tags marque com uma destas meta tags desliga o espelhamento em toda imagem que a carrega.\n\nO rodeio compensa pelo motivo que faz uma lista de nomes envelhecer: “text”, “logo”, “signature”, “left-handed”, uma dúzia de personagens com tapa-olho — a lista nas configurações de um trabalho está certa no dia em que é escrita e errada assim que alguém adiciona uma tag que ela deveria conter. Marcar as próprias tags põe o fato onde a tag está: uma tag adicionada depois o leva sozinha para toda execução, e um trabalho escrito antes de essa tag existir continua fazendo o certo.\n\nAs duas listas valem: uma imagem fica sem espelhar se carrega uma tag nomeada acima OU uma tag marcada aqui.",
  "The rule above, named by what the library says ABOUT a tag rather than by the tag. Any tag marked with one of these meta tags bypasses the random pick — again only where the image actually has it.\n\nA meta tag put on “watermark”, “signature” and “logo” once means every run treats them that way, including runs written before the third of them existed. The two lists are unioned, so naming a tag here and above is simply the same instruction twice.":
    "A regra acima, nomeada pelo que a biblioteca diz SOBRE uma tag em vez de pela tag. Qualquer tag marcada com uma destas meta tags escapa do sorteio — de novo, só onde a imagem realmente a tem.\n\nUma meta tag posta uma vez em “watermark”, “signature” e “logo” significa que toda execução as trata assim, inclusive as escritas antes de a terceira existir. As duas listas são unidas, então nomear uma tag aqui e acima é simplesmente a mesma instrução duas vezes.",
  "The same, one level up: any tag the library marks with one of these meta tags is stripped from every prompt.\n\nThis is the one to reach for when the exclusions are a KIND of tag rather than a list of them. Quality ratings, scan notes, the booru's own housekeeping words — mark them “noprompt” in the Tags tab and every run drops them, instead of every job carrying a list that has to grow with the vocabulary.\n\nIt is not the same as a skipped tag GROUP below. This one is about the tag wherever it appears; that one is about a grouping on one item, and a tag placed in an excluded group and also somewhere else survives it.":
    "O mesmo um nível acima: qualquer tag que a biblioteca marque com uma destas meta tags é retirada de todos os prompts.\n\nÉ o que se usa quando as exclusões são um TIPO de tag e não uma lista delas. Notas de qualidade, observações de digitalização, as palavras internas de um booru — marque-as como “noprompt” na aba Tags e toda execução as descarta, em vez de cada trabalho carregar uma lista que precisa crescer junto com o vocabulário.\n\nNão é o mesmo que um GRUPO de tags ignorado mais abaixo. Isto é sobre a tag onde quer que ela apareça; aquilo é sobre um agrupamento em um item, e uma tag posta em um grupo excluído e também em outro lugar sobrevive a ele.",
  "The list above, named by what the library says about a tag. Any tag marked with one of these meta tags comes off this sample.\n\nWhat it is for is that the claims a degraded copy no longer supports are a CATEGORY, not a list: 'masterpiece', 'absurdres', 'high quality', 'official art' and whatever the next dump adds are all \"a claim about the picture's quality\". Marking them once means every variant of every job drops them, and the same mark can then say something different per method — a 'resolution_claim' mark belongs on a resize variant's list, a 'fidelity_claim' on a JPEG one.":
    "A lista acima, nomeada pelo que a biblioteca diz sobre uma tag. Qualquer tag marcada com uma destas meta tags sai desta amostra.\n\nPara que serve: as afirmações que uma cópia degradada não sustenta mais são uma CATEGORIA, não uma lista. “masterpiece”, “absurdres”, “high quality”, “official art” e o que o próximo dump acrescentar são todas “uma afirmação sobre a qualidade da imagem”. Marcá-las uma vez faz com que toda variante de todo trabalho as descarte, e a mesma marca pode então dizer algo diferente por método — uma marca “resolution_claim” pertence à lista de uma variante de redimensionamento, uma “fidelity_claim” à de uma variante JPEG.",
  "The line above by mark rather than by name: a picture is degraded only if it carries a tag the library marks this way.\n\nChecked against the picture's effective tags, so a tag it only carries by implication counts too. With both lists empty, every picture is fair game.":
    "A linha acima por marca em vez de por nome: uma imagem só é degradada se carrega uma tag que a biblioteca marca assim.\n\nA verificação é feita contra as tags efetivas da imagem, então uma tag que ela só carrega por implicação também conta. Com as duas listas vazias, toda imagem está valendo.",
  "The veto by mark, and it wins over both lines above exactly as the named list does.\n\nThe pair is what makes a degrading run safe on a mixed library: mark the pictures that are already poor — a 'low_quality' or 'rescan' mark on the tags that say so — and no variant can ever degrade one of them further, however broadly the \"only pictures\" side is drawn.":
    "O veto por marca, e ele prevalece sobre as duas linhas acima exatamente como a lista por nome faz.\n\nO par é o que torna segura uma execução degradante numa biblioteca misturada: marque as imagens que já são ruins — um “low_quality” ou “rescan” nas tags que dizem isso — e nenhuma variante poderá degradar mais uma delas, por mais amplo que seja o lado “somente imagens”.",
  "Never flip images tagged": "Nunca espelhar imagens marcadas",
  "Comma-separated tags that switch mirroring off for the images carrying them, e.g. 'text'. Everything else still flips.": "Tags separadas por vírgulas que desligam o espelhamento para as imagens que as carregam, p. ex. 'text'. Todo o resto continua espelhando.",
  "Use alpha as a loss mask": "Usar o alfa como máscara de perda",
  "For cut-out images (transparent background): train on the visible pixels and largely ignore the rest. Images without transparency are unaffected.": "Para imagens recortadas (fundo transparente): treina com os pixels visíveis e ignora em grande parte o resto. Imagens sem transparência não são afetadas.",
  "Background weight": "Peso do fundo",
  "Build prompts from": "Montar prompts a partir de",
  "What each training prompt is made of: the item's caption text, its tags, caption followed by tags, or nothing but the trigger word.": "Do que cada prompt de treino é feito: a legenda do item, suas tags, legenda seguida das tags, ou nada além da palavra-gatilho.",
  "Prepended to every prompt. Use a rare token (e.g. 'ohwx style') you'll later type to invoke the trained concept.": "Anteposto a cada prompt. Use um token raro (p. ex. 'ohwx style') que você digitará depois para invocar o conceito treinado.",
  "Each image trains as the RESULT of one of its instructions, with that instruction's reference images as the input. Items carrying no instruction are left out of the run, and tag selection does not apply.": "Cada imagem treina como o RESULTADO de uma de suas instruções, com as imagens de referência dessa instrução como entrada. Itens sem instrução ficam fora da execução, e a seleção de tags não se aplica.",
  "Tag selection": "Seleção de tags",
  "Tags are re-picked and re-shuffled fresh every time an image is visited.": "As tags são re-sorteadas e re-embaralhadas de novo cada vez que uma imagem é visitada.",
  "Comma-separated tags stripped from prompts (e.g. quality tags or the concept itself when using a trigger word).": "Tags separadas por vírgulas retiradas dos prompts (p. ex. tags de qualidade ou o próprio conceito ao usar uma palavra-gatilho).",
  "no limit": "sem limite",
  "Lower bound of the random pick. Both limits empty = use all tags.": "Limite inferior do sorteio aleatório. Ambos os limites vazios = usar todas as tags.",
  "Upper bound of the random pick. Picking a random subset each visit teaches tags independently instead of as a fixed clump.": "Limite superior do sorteio aleatório. Escolher um subconjunto aleatório a cada visita ensina as tags de forma independente em vez de como um bloco fixo.",
  "Whether a tag's rarity is measured within the selected training images or across the whole library.": "Se a raridade de uma tag é medida dentro das imagens de treinamento selecionadas ou na biblioteca inteira.",
  "Skip partially matching tags": "Pular tags parcialmente coincidentes",
  "Standard practice: prevents the model from binding concepts to a fixed tag position.": "Prática padrão: impede o modelo de amarrar conceitos a uma posição fixa de tag.",
  "Underscores to spaces": "Sublinhados para espaços",
  "Tag separator": "Separador de tags",
  "Joins the prompt parts; comma + space is the standard.": "Une as partes do prompt; vírgula + espaço é o padrão.",
  "Generate preview images with the in-training model to watch progress in the job's timeline.": "Gera imagens de prévia com o modelo em treinamento para acompanhar o progresso na linha do tempo do trabalho.",
  "Generate test samples": "Gerar amostras de teste",
  "Sample seed": "Semente das amostras",
  "Fixed per prompt so consecutive samples differ only by training progress.": "Fixa por prompt para que amostras consecutivas difiram só pelo progresso do treinamento.",
  "Test prompts": "Prompts de teste",
  "negative prompt (optional)": "prompt negativo (opcional)",
  "Use the shared size for this prompt": "Usar o tamanho compartilhado para este prompt",
  "Give this prompt its own size": "Dar a este prompt seu próprio tamanho",
  "Remove this prompt": "Remover este prompt",
  "Add prompt": "Adicionar prompt",
  "Remove every prompt from this job": "Remover todos os prompts deste trabalho",
  "Remove all": "Remover tudo",
  "Save the current prompts, or load a saved set": "Salvar os prompts atuais, ou carregar um conjunto salvo",
  "Write a prompt first": "Escreva um prompt primeiro",
  "Save current prompts": "Salvar prompts atuais",
  "Set name": "Nome do conjunto",
  "Load this set into the job": "Carregar este conjunto no trabalho",
  "Delete this set": "Excluir este conjunto",
  "train from scratch": "treinar do zero",
  "Finished result": "Resultado concluído",
  "Intermediate checkpoint": "Checkpoint intermediário",
  "Continues": "Continua",
  "Train on video frames": "Treinar com quadros de vídeo",
  "Off, a video the queries match is skipped. On, its frames are extracted while the dataset is built, trained on as images, and deleted with the run.": "Desativado, um vídeo que as consultas encontram é pulado. Ativado, seus quadros são extraídos enquanto o conjunto é construído, treinados como imagens, e excluídos com a execução.",
  "One frame every": "Um quadro a cada",
  "Interval unit": "Unidade do intervalo",
  "Seconds follows the clock whatever the frame rate; frames counts the file's own frames.": "Segundos segue o relógio seja qual for a taxa de quadros; quadros conta os do próprio arquivo.",
  "Drop repeated frames": "Descartar quadros repetidos",
  "A shot held for five seconds is one picture, not five. Each kept frame is compared with the ones already kept from the same video.": "Um plano segurado por cinco segundos é uma imagem, não cinco. Cada quadro mantido é comparado com os já mantidos do mesmo vídeo.",
  "Label each block with": "Rotular cada bloco com",
  "The subjects it is about": "Os sujeitos de que ele trata",
  "The tag group's name": "O nome do grupo de tags",
  "Between groups": "Entre grupos",
  "Group tags by tag group": "Agrupar tags por grupo de tags",
  "Lay the picked tags out one block per tag group instead of one flat list, so what belongs to the same thing in the picture stays together.": "Dispõe as tags escolhidas em um bloco por grupo de tags em vez de uma lista plana, para que o que pertence à mesma coisa na imagem fique junto.",
  "Put between blocks. A newline by default, which is what makes them read as separate statements.": "Posto entre os blocos. Uma quebra de linha por padrão, que é o que os faz se lerem como afirmações separadas.",
  "Includes {n} models you added.": { one: "Inclui {n} modelo que você adicionou.", other: "Inclui {n} modelos que você adicionou." },
  // The job list's selection bar.
  "Remove {n} training jobs? Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone.":
    "Remover {n} trabalhos de treinamento? Seus checkpoints, amostras e resultados treinados são removidos junto, e isso não pode ser desfeito. Exceto o que estiver bloqueado, que fica na lista de LoRAs.",
  "Remove the selected jobs — a running job is left alone":
    "Remover os trabalhos selecionados — um em execução fica intacto",
  "Remove the selected jobs, with their checkpoints and samples":
    "Remover os trabalhos selecionados, com seus checkpoints e amostras",
  // The Models page: adding a model, and removing one.
  "Remove “{name}” from the model list?":
    "Remover “{name}” da lista de modelos?",
  "Delete the downloaded weights as well? They can be downloaded again later.":
    "Apagar também os pesos baixados? Eles podem ser baixados de novo depois.",
  "Which model these weights are a version of — it decides the engine, the hyperparameters and the memory profile":
    "De qual modelo estes pesos são uma versão — isso decide o motor, os hiperparâmetros e o perfil de memória",
  "owner/repo, or a path on this machine":
    "owner/repo, ou um caminho nesta máquina",
  "A Hugging Face repository, or a diffusers folder or .safetensors file on this machine — which one it is is read off what you type.":
    "Um repositório do Hugging Face, ou uma pasta diffusers ou arquivo .safetensors nesta máquina — qual dos dois é lido do que você digita.",
  "Read as a path on this machine":
    "Lido como um caminho nesta máquina",
  "Read as a Hugging Face repository":
    "Lido como um repositório do Hugging Face",
  "Left unnamed, the model is listed under its repository or path":
    "Sem nome, o modelo aparece sob seu repositório ou caminho",
  // The Models page's LoRA lists, grouped by architecture.
  "No LoRAs yet — add a file above, or finish a training job.":
    "Ainda não há LoRAs — adicione um arquivo acima ou conclua um treinamento.",
  "These work on any model of this architecture. Each row says which one it was trained for.":
    "Funcionam com qualquer modelo desta arquitetura. Cada linha diz para qual foi treinado.",
  // The Evaluate tab: the LoRA rows, and the results grid.
  "Strength":
    "Intensidade",
  "no image":
    "sem imagem",
  "Weights": "Pesos",
  "File": "Arquivo",
  "Trained for": "Treinada para",
  "defaults to the file name": "por padrão, o nome do arquivo",
  "Waiting…": "Aguardando…",
  "Another download is running": "Outro download está em andamento",
  "macOS keeps GPU temperature and power for root only. To see them here, allow this one command without a password, then press Try again:":
    "O macOS reserva a temperatura e a potência da GPU apenas para o root. Para vê-las aqui, permita este único comando sem senha e clique em “Tentar de novo”:",
  "Check again — no restart needed once the rule is in":
    "Verificar de novo — com a regra no lugar, não é preciso reiniciar",
  "Copied": "Copiado",
  "Press ⌘C to copy it": "Pressione ⌘C para copiar",
  "Write tags as an alias": "Escrever tags como um alias",
  "Chance of writing a picked tag as one of its aliases instead of its own name, rolled per tag every time an image is visited.":
    "Probabilidade de escrever uma tag escolhida com um de seus aliases em vez do próprio nome, sorteada por tag sempre que uma imagem é visitada.",
  "Your library's aliases are the other words for one thing — “cat”, “kitty”, “feline”. Assigning any of them stores the canonical name, so every prompt says the same word and the model learns to answer to that word alone; at generation time the others do less, or nothing.\n\nWith this above 0, each picked tag is sometimes written as one of its aliases instead. The roll happens per tag per visit, so one image seen twice reads differently and the whole vocabulary is spread across the run rather than one alias being chosen per tag and then repeated.\n\nOnly the PROMPT changes. Tag matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all keep using the canonical name — so this cannot skew any of them. A tag with no aliases is always written as itself, and 0 is exactly what every run did before this setting existed.":
    "Os aliases da sua biblioteca são as outras palavras para a mesma coisa — “cat”, “kitty”, “feline”. Atribuir qualquer um deles grava o nome canônico, então todos os prompts dizem a mesma palavra e o modelo aprende a responder só a ela; na geração, as outras fazem pouco ou nada.\n\nAcima de 0, cada tag escolhida às vezes é escrita com um de seus aliases. O sorteio é por tag e por visita, de modo que uma imagem vista duas vezes é lida de forma diferente e todo o vocabulário se espalha pelo treino, em vez de escolher um alias por tag e repeti-lo.\n\nSó o PROMPT muda. A correspondência de tags, as listas sempre/excluir, o balanceamento por frequência, o peso da perda e as caixas que um recorte precisa manter continuam usando o nome canônico — portanto isso não distorce nada. Uma tag sem aliases é sempre escrita como ela mesma, e 0 é exatamente o que todo treino fazia antes desta opção existir.",
  "Whether a tag's rarity is measured within the selected training images, across the whole library, or across the whole library plus what each tag has elsewhere.":
    "Se a raridade de uma tag é medida dentro das imagens de treino selecionadas, em toda a biblioteca, ou em toda a biblioteca mais o que cada tag tem em outros lugares.",
  "Rarity is relative to some population, and this picks which one.\n\n“Training data” counts only the images this job selected, so balancing works within the set you are actually training on — usually what you want. “Whole library” counts every item you own, which makes a tag that is common in your dataset but rare overall still count as rare. That is occasionally useful when the training set is a deliberate slice of a much larger, differently balanced collection.\n\n“Whole library + count offsets” adds each tag’s highest meta-tag count — the pictures it has somewhere this library is not, counted per site on the tag’s meta tags (“tumblr 50”, “twitter 100”), of which the largest single figure is used, never the sum, since the sites count overlapping pictures. Nowhere else in the app is that number added to a count, because a total including it would be a claim about somewhere else; for BALANCING it is often the honest one. A tag with four pictures here and forty thousand where they came from is not a rare word, and treating it as rare spends the run teaching the model something it already knows.":
    "Raridade é sempre relativa a uma população, e é ela que se escolhe aqui.\n\n“Dados de treino” conta apenas as imagens que este trabalho selecionou, então o balanceamento age dentro do conjunto com que você realmente treina — quase sempre o que se quer. “Biblioteca inteira” conta tudo o que você tem, de modo que uma tag comum no seu conjunto mas rara no geral continua contando como rara. Isso é útil de vez em quando, quando o conjunto de treino é uma fatia deliberada de uma coleção bem maior e diferentemente distribuída.\n\n“Biblioteca inteira + acervos externos” soma a maior contagem por metatag de cada tag — as imagens que ela tem em algum lugar onde esta biblioteca não está, contadas por site nas metatags da tag (“tumblr 50”, “twitter 100”); usa-se o maior número isolado, nunca a soma, porque os sites contam imagens que se sobrepõem. Em nenhum outro ponto do app esse número é somado a uma contagem, porque um total que o incluísse seria uma afirmação sobre outro lugar; para BALANCEAR, ele costuma ser o honesto. Uma tag com quatro imagens aqui e quarenta mil de onde vieram não é uma palavra rara, e tratá-la como rara gasta o treino ensinando ao modelo algo que ele já sabe.",
  "Caption selection": "Seleção de legendas",
  "Instruction selection": "Seleção de instruções",
  "Start now — pauses the running job and puts this one first":
    "Iniciar agora — pausa o trabalho em execução e coloca este à frente",
  "Start now — puts this job first and starts the queue":
    "Iniciar agora — coloca este trabalho à frente e inicia a fila",
  "Save as duplicate":
    "Salvar como duplicata",
  "Batch & seed": "Lote e semente",
  "Device": "Dispositivo",
  "Precision & quantization": "Precisão e quantização",
  "Memory savers": "Economia de memória",
  "Training images": "Imagens de treino",
  "Length measured in":
    "Duração medida em",
  "Steps are a fixed amount of work; epochs are full passes over your images, so the run grows with the dataset.":
    "Passos são uma quantidade fixa de trabalho; épocas são passagens completas pelas suas imagens, então o treino cresce com o conjunto.",
  "A STEP is one batch pushed through the model and one update of the weights — a fixed amount of work whatever the dataset holds. An EPOCH is one pass over every training image, so the same number means a longer run on a bigger set and the model sees each picture the same number of times either way.\n\nEpochs are usually the easier thing to reason about: “each image about ten times” transfers between datasets, where “3000 steps” does not. The exact step count is worked out when the run starts, because only then is it known how many entries the dataset has — a film contributes its frames, a degraded copy is an extra sample, and an item can contribute one per caption.":
    "Um PASSO é um lote empurrado pelo modelo e uma atualização dos pesos — uma quantidade fixa de trabalho, seja qual for o conjunto. Uma ÉPOCA é uma passagem por cada imagem de treino, então o mesmo número significa um treino mais longo num conjunto maior, e o modelo vê cada imagem o mesmo tanto de vezes nos dois casos.\n\nÉpocas costumam ser mais fáceis de raciocinar: “cada imagem umas dez vezes” se transfere entre conjuntos, “3000 passos” não. O número exato de passos é calculado ao iniciar o treino, porque só então se sabe quantas entradas o conjunto tem — um vídeo contribui com seus quadros, uma cópia degradada é uma amostra a mais, e um item pode contribuir com uma entrada por legenda.",
  "Epochs":
    "Épocas",
  "Full passes over the dataset. The exact step count is worked out when the run starts and shown in its log.":
    "Passagens completas pelo conjunto. O número exato de passos é calculado ao iniciar e aparece no log.",
  "How many times the run works through every training image. Each pass visits every entry exactly once, in a fresh random order.\n\nWhat counts as an entry is the dataset after it has been built, not the number of pictures you selected: a video contributes one entry per kept frame, a degradation variant adds an extra sample beside the clean picture, and with “every caption” an item contributes one entry per caption. That is why the step count appears when the run starts rather than here.":
    "Quantas vezes o treino percorre todas as imagens. Cada passagem visita cada entrada exatamente uma vez, numa ordem aleatória nova.\n\nO que conta como entrada é o conjunto já montado, não o número de imagens que você selecionou: um vídeo contribui com uma entrada por quadro mantido, uma variante de degradação acrescenta uma amostra ao lado da imagem limpa, e com “cada legenda” um item contribui com uma entrada por legenda. Por isso o número de passos aparece ao iniciar, e não aqui.",
  "Query weight":
    "Peso da consulta",
  "A weight buys":
    "Um peso compra",
  "Whether a heavier query's images are seen more often, or seen the same and counted for more.":
    "Se as imagens de uma consulta mais pesada são vistas com mais frequência, ou vistas igual e contam mais.",
  "Both spend the same ratio; they differ in what they spend it on.\n\nSEEN MORE OFTEN is the classic behaviour: a weight-2 query's pictures get twice the visits, which means they take those visits from the rest — a fixed-length run spends more of itself on them and less on everything else.\n\nCOUNTED FOR MORE gives every picture the same number of visits and multiplies the weighted ones' effect on the weights instead. Nothing loses coverage; the emphasis comes out of the gradient rather than out of the other images' training time. It is the better default when the queries are different KINDS of picture rather than different amounts of importance.":
    "As duas gastam a mesma proporção; a diferença é em quê.\n\nVISTAS COM MAIS FREQUÊNCIA é o comportamento clássico: as imagens de uma consulta com peso 2 recebem o dobro de visitas, e essas visitas saem do resto — um treino de duração fixa gasta mais de si nelas e menos em todo o restante.\n\nCONTAM MAIS dá a cada imagem o mesmo número de visitas e, em vez disso, multiplica o efeito das ponderadas sobre os pesos. Nada perde cobertura; a ênfase sai do gradiente e não do tempo de treino das outras imagens. É o padrão melhor quando as consultas são TIPOS diferentes de imagem, e não graus diferentes de importância.",
  "Seen more often":
    "Vistas com mais frequência",
  "Counted for more":
    "Contam mais",
  "An item with several captions":
    "Um item com várias legendas",
  "Whether every caption is used each pass, or one is drawn per visit.":
    "Se cada legenda é usada em cada passagem, ou se uma é sorteada por visita.",
  "Items often carry more than one caption — a short one and a long one, a translation, a machine draft somebody approved.\n\nONE AT RANDOM gives the item a single visit each pass and draws a different caption each time, so the whole set is seen across a long run and an item counts once however many ways it has been described.\n\nEVERY CAPTION gives it one visit per caption, so all of them are used every pass — and an item with ten is therefore seen ten times, which is usually an accident of tooling rather than a claim that the picture matters ten times as much.\n\nEVERY CAPTION, SHARED is that with the accident removed: each caption still gets its visit, and together they carry one item's worth of gradient.":
    "Itens costumam ter mais de uma legenda — uma curta e uma longa, uma tradução, um rascunho automático que alguém aprovou.\n\nUMA AO ACASO dá ao item uma única visita por passagem e sorteia uma legenda diferente a cada vez, então ao longo de um treino comprido todas são vistas, e o item conta uma vez por mais formas que tenha sido descrito.\n\nCADA LEGENDA dá a ele uma visita por legenda, então todas são usadas em cada passagem — e um item com dez é visto dez vezes, o que costuma ser um acaso das ferramentas e não uma afirmação de que aquela imagem importa dez vezes mais.\n\nCADA LEGENDA, DIVIDINDO é isso sem o acaso: cada legenda mantém sua visita, e juntas carregam o gradiente de um único item.",
  "One at random each visit":
    "Uma ao acaso a cada visita",
  "Every caption, once each":
    "Cada legenda, uma vez",
  "Every caption, sharing one item's weight":
    "Cada legenda, dividindo o peso de um item",
  "Unsupported":
    "Não suportado",
  "not available on Apple silicon":
    "indisponível no Apple silicon",
  "not used on Apple silicon, where the run trains in fp32":
    "não é usado no Apple silicon, onde o treino roda em fp32",
  "a full finetune trains the base weights, so there is nothing to quantize":
    "um finetuning completo treina os pesos base, então não há o que quantizar",
  "only offered for LoRA training":
    "oferecido apenas no treino LoRA",
  "too large to finetune on any GPU this app has constants for":
    "grande demais para finetuning em qualquer GPU para a qual este app tem constantes",
  "Another picture": "Outra imagem",
  "{n} jobs selected. One at a time shows its progress, samples and settings.":
    "{n} trabalhos selecionados. O progresso, as imagens de teste e as configurações aparecem um de cada vez.",
  "original":
    "original",
  "Show this at full size":
    "Ver em tamanho real",
  "Each snapshot is about {size}.":
    "Cada instantâneo ocupa cerca de {size}.",
  "Cadence measured in":
    "Frequência medida em",
  "How often a snapshot is written: after a fixed number of steps, or after a number of full passes over the dataset.":
    "Com que frequência um instantâneo é gravado: após um número fixo de passos, ou após um número de passagens completas pelo conjunto.",
  "How often a round of samples is rendered: after a fixed number of steps, or after a number of full passes over the dataset.": "Com que frequência uma rodada de amostras é gerada: a cada número fixo de passos, ou a cada tantas passagens completas pelo conjunto de dados.",
  "Rendered after this many full passes. The equivalent step count appears in the job's log when the run starts.": "Gerada após esta quantidade de passagens completas. A contagem de passos equivalente aparece no log do job quando a execução começa.",
  "A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 250 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both. It is the choice the checkpoint cadence and the run’s own length already offer, and setting all three the same way is what makes a sample, its checkpoint and a pass over your pictures line up in the timeline.\n\nHow many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has — a film’s frames, a degraded copy and an item contributing one entry per caption all count.": "Um passo é uma quantidade fixa de trabalho e uma época é uma passagem por todas as imagens de treino, então as duas cadências se afastam conforme o conjunto de dados cresce — “a cada 250 passos” é quase toda uma execução pequena e uma fração de uma grande, enquanto “a cada época” significa o mesmo nas duas. É a mesma escolha que a cadência dos checkpoints e a duração da execução já oferecem, e ajustar as três do mesmo jeito é o que alinha uma amostra, seu checkpoint e uma passagem pelas suas imagens na linha do tempo.\n\nQuantos passos uma época leva é calculado quando a execução começa, porque só o conjunto de dados já montado sabe quantas entradas tem — os quadros de um vídeo, uma cópia degradada e um item que rende uma entrada por legenda contam todos.",
  "Rendered after this many full passes over the dataset. The equivalent step count is printed in the job’s log when the run starts, so a glance there says what the cadence came out as for this particular dataset.\n\nSampling interrupts training while it renders, so on a large dataset one round per epoch may be further apart than you want and on a tiny one it may be a pause every few seconds — the log’s step figure is what tells you which.": "Gerada após esta quantidade de passagens completas pelo conjunto de dados. A contagem de passos equivalente é escrita no log do job na largada, então uma olhada ali diz no que a cadência dá para este conjunto específico.\n\nA amostragem interrompe o treino enquanto renderiza, então num conjunto grande uma rodada por época pode ficar mais espaçada do que você quer e num minúsculo pode ser uma pausa a cada poucos segundos — o número de passos no log é o que diz qual dos dois.",
  "Rendered every this many steps, whatever the dataset is. 250–500 is a good rhythm: often enough to catch a concept going wrong, rare enough that the pauses do not dominate the run.": "Gerada a cada tantos passos, seja qual for o conjunto de dados. 250–500 é um bom ritmo: frequente o bastante para pegar um conceito saindo dos trilhos, raro o bastante para as pausas não dominarem a execução.",
  "A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 500 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both.\n\nHow many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has. That is also why the disk estimate below can only be given when the run's length is set in epochs too.":
    "Um passo é uma quantidade fixa de trabalho e uma época é uma passagem por cada imagem de treino, então as duas frequências se afastam conforme o conjunto cresce: “a cada 500 passos” é quase todo um treino pequeno e uma fração de um grande, enquanto “a cada época” significa o mesmo nos dois.\n\nQuantos passos uma época leva é calculado ao iniciar o treino, porque só o conjunto já montado sabe quantas entradas tem. É por isso que a estimativa de disco abaixo só pode ser dada quando a duração também está em épocas.",
  "epochs":
    "épocas",
  "Written after this many full passes. The equivalent step count appears in the job's log when the run starts.":
    "Gravado após esta quantidade de passagens completas. O equivalente em passos aparece no log do trabalho ao iniciar.",
  "Every snapshot is a usable model file: the Evaluate tab can generate with any of them, so you can compare one pass against another and keep whichever looks best.\n\nCounted in passes, the cadence follows the dataset: add pictures and the snapshots stay one-per-pass rather than quietly becoming more frequent than a pass. The trainer prints what it works out to in steps, so the timeline and the log still agree about what a checkpoint is.":
    "Cada instantâneo é um arquivo de modelo utilizável: a aba Evaluate pode gerar com qualquer um deles, então você pode comparar uma passagem com outra e ficar com a melhor.\n\nContada em passagens, a frequência acompanha o conjunto: ao acrescentar imagens, os instantâneos continuam sendo um por passagem em vez de ficarem silenciosamente mais frequentes do que uma passagem. O treinador escreve no log a que isso equivale em passos, para que a linha do tempo e o log continuem de acordo sobre o que é um checkpoint.",
  "Never upscale":
    "Nunca ampliar",
  "Leave out any image smaller than the bucket it would be fitted to, rather than enlarging it.":
    "Deixa de fora as imagens menores que o bucket em que cairiam, em vez de ampliá-las.",
  "Loads the frozen base weights in 8-bit or 4-bit so big models fit in little memory (QLoRA). 8-bit (int8) runs on Apple silicon too; fp8 and 4-bit need an NVIDIA GPU.":
    "Carrega os pesos base congelados em 8 ou 4 bits para que modelos grandes caibam em pouca memória (QLoRA). 8 bits (int8) também funciona no Apple Silicon; fp8 e 4 bits precisam de uma GPU NVIDIA.",
  "Quantize the text encoder":
    "Quantizar o codificador de texto",
  "Applies the same scheme to the text encoder, the other big frozen model. On the largest models it is worth several GB.":
    "Aplica o mesmo esquema ao codificador de texto, o outro grande modelo congelado. Nos modelos maiores vale vários GB.",
  "cannot be combined with training the text encoder":
    "não pode ser combinado com treinar o codificador de texto",

  // ---- adapter type, layer targeting, optimizers, noise levels,
  // weight averaging and regularization ----
  "Adapter":
    "Adaptador",
  "Adapter type":
    "Tipo de adaptador",
  "Kronecker factor":
    "Fator de Kronecker",
  "How each weight is split into LoKr's two parts. Leave empty unless you have a reason not to.":
    "Como cada peso é dividido nas duas partes do LoKr. Deixe vazio a menos que tenha um motivo para não deixar.",
  "Only these layers":
    "Apenas estas camadas",
  "all of them":
    "todas",
  "Comma-separated parts of a layer's name. Leave empty to train every attention layer — which is what you want unless you have a reason not to.":
    "Partes do nome de uma camada, separadas por vírgulas. Deixe vazio para treinar todas as camadas de atenção — que é o que você quer, a menos que tenha um motivo para não querer.",
  "By default the adapter attaches to every attention layer in the image model. This narrows that to the layers whose name contains one of the words you list.\n\nWhy you might: different parts of the network do different jobs. The later ones carry more of what a picture LOOKS like, and the earlier ones more of how it is put together — so training only part of the network is how a style is learned without also disturbing composition and anatomy. It also makes the adapter smaller and each step faster, since there is less to train.\n\nThe names come from the model itself, and the chevron at the end of the field lists the ones worth knowing for the architecture you picked — clicking one adds or removes it, and a tick marks the ones the field already holds. For SD and SDXL they are down_blocks, mid_block and up_blocks, plus attn1 (the picture attending to itself) and attn2 (where the prompt gets in); for the newer transformer models, transformer_blocks and single_transformer_blocks. The field stays free text, because you can be as coarse or as fine as you like: 'up_blocks' takes a whole third of a UNet, 'transformer_blocks.12' takes one block, 'to_k' takes one kind of projection everywhere. The job's page draws a map of the whole model once a run has started.\n\nIf what you type matches no layers at all, the run stops and says so rather than training an adapter attached to nothing — which would otherwise look exactly like a normal run that learned nothing.":
    "Por padrão o adaptador se prende a todas as camadas de atenção do modelo de imagem. Isto restringe às camadas cujo nome contém alguma das palavras que você listar.\n\nPor que você faria isso: partes diferentes da rede fazem trabalhos diferentes. As mais tardias carregam mais a APARÊNCIA de uma imagem, e as mais iniciais mais o modo como ela é montada — então treinar só parte da rede é como se aprende um estilo sem também mexer na composição e na anatomia. Além disso deixa o adaptador menor e cada passo mais rápido, porque há menos a treinar.\n\nOs nomes vêm do próprio modelo, e a seta no fim do campo lista os que valem a pena conhecer para a arquitetura escolhida — um clique adiciona ou remove, e um tique marca os que o campo já tem. Em SD e SDXL são down_blocks, mid_block e up_blocks, mais attn1 (a imagem atendendo a si mesma) e attn2 (por onde o prompt entra); nos modelos transformer mais novos, transformer_blocks e single_transformer_blocks. O campo continua sendo texto livre, porque você pode ser tão grosseiro ou tão fino quanto quiser: “up_blocks” leva um terço inteiro de uma UNet, “transformer_blocks.12” um único bloco, “to_k” um tipo de projeção em toda parte. A página da tarefa desenha um mapa do modelo inteiro assim que uma execução começa.\n\nSe o que você digitar não bater com camada nenhuma, a execução para e avisa, em vez de treinar um adaptador preso a nada — o que de outro modo pareceria exatamente uma execução normal que não aprendeu nada.",
  "Except these layers":
    "Exceto estas camadas",
  "Comma-separated parts of a layer's name to leave out. Applied after the field above, and it wins.":
    "Partes do nome de uma camada, separadas por vírgulas, a deixar de fora. Aplicado depois do campo acima, e prevalece sobre ele.",
  "The same kind of list, subtracting instead of selecting. A layer whose name matches anything here is left out even if the field above selected it.\n\nIt is the easier way to say 'everything except' — excluding 'down_blocks' is shorter and stays correct if the model gains a block, where listing every other block by hand does not.":
    "O mesmo tipo de lista, subtraindo em vez de selecionar. Uma camada cujo nome bata com qualquer coisa daqui fica de fora, mesmo que o campo acima a tenha selecionado.\n\nÉ o jeito fácil de dizer “tudo menos”: excluir “down_blocks” é mais curto e continua certo se o modelo ganhar um bloco, o que listar à mão todos os outros blocos não continua.",
  "Output size: a small fraction of a LoRA of the same rank — usually under a tenth.":
    "Tamanho do resultado: uma pequena fração de um LoRA do mesmo rank — normalmente menos de um décimo.",
  "Learning rate multiplier":
    "Multiplicador da taxa de aprendizado",
  "Prodigy works the rate out for itself; this scales what it finds. 1 leaves it alone — lower it if the run overshoots, raise it if it never gets going.":
    "O Prodigy calcula a taxa sozinho; isto escala o que ele encontra. 1 deixa como está — abaixe se a execução passar do ponto, aumente se ela nunca engrenar.",
  "The Prodigy optimizer measures how far the weights have moved from where they started and derives a learning rate from that, so the rate is not something you set here — it comes out of the run.\n\nWhat this field does is scale the answer. 1 accepts it as found and is what you want almost always. Below 1 is a brake, worth reaching for if the run overshoots and samples come out burnt; above 1 pushes harder, which is occasionally useful on a very small dataset.\n\nProdigy needs a few hundred steps to work its estimate up from nearly nothing, so early samples in a Prodigy run look untrained even when everything is fine. Judge it from about a fifth of the way in, not from the first sample round.":
    "O otimizador Prodigy mede o quanto os pesos se afastaram do ponto de partida e deriva daí uma taxa de aprendizado, então a taxa não é algo que se define aqui: ela sai da própria execução.\n\nO que este campo faz é escalar essa resposta. 1 aceita como encontrada e é o que você quer quase sempre. Abaixo de 1 é um freio, útil se a execução passa do ponto e as amostras saem queimadas; acima de 1 empurra mais forte, o que às vezes ajuda com um conjunto de dados muito pequeno.\n\nO Prodigy precisa de algumas centenas de passos para levantar sua estimativa quase do zero, então as primeiras amostras de uma execução com Prodigy parecem não treinadas mesmo quando tudo está bem. Avalie a partir de cerca de um quinto do caminho, não na primeira rodada de amostras.",
  "How far the weights move on every update. It is the single most sensitive setting here.\n\nToo high and training diverges: samples turn into over-saturated, high-contrast mush ('deep fried'), often within a few hundred steps. Too low and nothing visibly changes no matter how long you wait. Typical values: 1e-4 for a LoRA, 1e-5 or lower for a full finetune (which touches every weight and needs far gentler updates).\n\nLearning rate and total steps trade off against each other — halving the rate roughly doubles the steps needed. If early samples look burnt, halve it; if they look identical to the baseline after a third of the run, double it.\n\nIf finding this number is the part you would rather not do, the Prodigy optimizer (Memory & speed) works it out for itself.":
    "O quanto os pesos se movem a cada atualização. É o ajuste mais sensível daqui.\n\nAlto demais e o treinamento diverge: as amostras viram uma papa supersaturada e de contraste extremo (“deep fried”), muitas vezes em poucas centenas de passos. Baixo demais e nada muda visivelmente, por mais que você espere. Valores típicos: 1e-4 para um LoRA, 1e-5 ou menos para um finetune completo (que toca todos os pesos e precisa de atualizações bem mais suaves).\n\nTaxa de aprendizado e total de passos se compensam: reduzir a taxa pela metade mais ou menos dobra os passos necessários. Se as primeiras amostras parecem queimadas, corte pela metade; se depois de um terço da execução continuam idênticas à linha de base, dobre.\n\nSe procurar esse número é justamente o que você preferia não fazer, o otimizador Prodigy (Memória e velocidade) o calcula sozinho.",
  "Noise levels":
    "Níveis de ruído",
  "Train on":
    "Treinar em",
  "Which stage of denoising to spend the run on. High noise decides a picture's layout, low noise its detail — so this decides what the training is mostly about.":
    "Em que etapa da remoção de ruído gastar a execução. Ruído alto decide o arranjo de uma imagem, ruído baixo o detalhe dela — então isto decide sobre o que o treinamento é principalmente.",
  "Every training step takes a picture, adds some amount of noise to it, and asks the model to undo that. How much noise is picked fresh each time — and the two extremes teach completely different things.\n\nAt HIGH noise there is barely a picture left, so all the model can learn is layout: what is where, how big, the overall shape and colour. At LOW noise the composition is already settled and what is left to learn is detail and texture — edges, surfaces, small features.\n\nSo where a run spends its steps decides what it mostly teaches. A style is largely texture; a character's proportions are largely layout.\n\n'The model's own' is what this model family has always done here, and is the right answer unless you have a specific reason: the older models spread their steps evenly, and the newer ones concentrate on the middle, which is what their published recipes do and part of why they train efficiently. 'Evenly' spreads across the whole range. 'Bell curve' is the newer models' behaviour made adjustable, so you can lean it towards layout or towards detail. 'Cosine' leans towards higher noise without abandoning the low end.\n\nChanging this does not make a run better or worse in general — it moves what the run is good at.":
    "Cada passo de treinamento pega uma imagem, acrescenta certa quantidade de ruído e pede ao modelo que desfaça isso. Quanto ruído é sorteado de novo a cada vez — e os dois extremos ensinam coisas completamente diferentes.\n\nCom ruído ALTO quase não sobra imagem, então tudo o que o modelo consegue aprender é o arranjo: o que está onde, de que tamanho, a forma e a cor gerais. Com ruído BAIXO a composição já está resolvida e o que resta aprender é detalhe e textura — bordas, superfícies, elementos pequenos.\n\nEntão onde uma execução gasta seus passos decide o que ela ensina principalmente. Um estilo é em grande parte textura; as proporções de um personagem são em grande parte arranjo.\n\n“O próprio do modelo” é o que esta família de modelos sempre fez aqui, e é a resposta certa a menos que você tenha um motivo específico: os modelos mais antigos distribuem os passos uniformemente e os mais novos se concentram no meio, que é o que suas receitas publicadas fazem e parte do motivo de treinarem com eficiência. “Uniformemente” distribui por toda a faixa. “Curva em sino” é o comportamento dos modelos novos tornado ajustável, para inclinar rumo ao arranjo ou ao detalhe. “Cosseno” inclina para ruído mais alto sem abandonar a ponta baixa.\n\nMudar isto não deixa uma execução melhor ou pior em geral — muda aquilo em que ela fica boa.",
  "The model's own (recommended)":
    "O próprio do modelo (recomendado)",
  "Evenly across all levels":
    "Uniformemente por todos os níveis",
  "A bell curve I can aim":
    "Uma curva em sino que eu miro",
  "Leaning towards layout":
    "Inclinado para o arranjo",
  "Aim at":
    "Mirar em",
  "0 is the middle. Positive leans towards layout and composition, negative towards detail and texture. ±1 is already a strong lean.":
    "0 é o meio. Positivo inclina para arranjo e composição; negativo, para detalhe e textura. ±1 já é uma inclinação forte.",
  "Where the centre of the bell curve sits along the noise range.\n\n0 puts it in the middle, which is what the newer models do by default and a good place to stay. Move it positive and the run spends more of itself at high noise, learning layout and composition — useful when what you are teaching is a shape or an arrangement. Move it negative and it spends more at low noise, learning detail and texture — useful for a style, a medium, a surface quality.\n\n±0.5 is a noticeable lean and ±1 is a strong one. Beyond ±2 the run largely stops seeing one end of the range at all.":
    "Onde fica o centro da curva em sino ao longo da faixa de ruído.\n\n0 põe no meio, que é o que os modelos novos fazem por padrão e um bom lugar para ficar. Mova para o positivo e a execução gasta mais de si com ruído alto, aprendendo arranjo e composição — útil quando o que você ensina é uma forma ou uma disposição. Mova para o negativo e ela gasta mais com ruído baixo, aprendendo detalhe e textura — útil para um estilo, um meio, uma qualidade de superfície.\n\n±0,5 é uma inclinação perceptível e ±1 é forte. Além de ±2 a execução praticamente deixa de ver uma das pontas da faixa.",
  "Spread":
    "Dispersão",
  "How wide the curve is. 1 is the default; smaller concentrates the run on a narrow band around the aim, larger reaches both extremes.":
    "A largura da curva. 1 é o padrão; menor concentra a execução numa faixa estreita em torno da mira, maior alcança os dois extremos.",
  "The width of the bell curve.\n\n1 is the standard setting. Smaller values concentrate the run on a narrow band around wherever you have aimed it, which sharpens what it teaches at the cost of everything else. Larger values spread it out and reach both extremes more often, which is closer to training evenly.\n\nIf you are unsure, leave it at 1 and move the aim instead — the aim is the setting that changes what the run learns, and this one changes how single-minded it is about it.":
    "A largura da curva em sino.\n\n1 é o ajuste padrão. Valores menores concentram a execução numa faixa estreita em torno de onde você mirou, o que afia o que ela ensina à custa de todo o resto. Valores maiores a espalham e alcançam os dois extremos com mais frequência, o que se aproxima de treinar uniformemente.\n\nNa dúvida, deixe em 1 e mova a mira: a mira é o ajuste que muda o que a execução aprende, e este muda o quanto ela é obstinada nisso.",
  "Weight averaging":
    "Média dos pesos",
  "Average the weights":
    "Tirar a média dos pesos",
  "Save a smoothed version of the weights instead of whatever the last step happened to produce. Makes checkpoints more consistent and overtraining slower to bite.":
    "Salva uma versão suavizada dos pesos em vez do que o último passo por acaso produziu. Deixa os checkpoints mais consistentes e o overtraining mais lento para morder.",
  "Every training step moves the weights a little, and each of those moves is noisy — it is worked out from a handful of images, and a different handful would have pulled somewhere slightly different. So the weights at step 1400 are not reliably better than the weights at step 1200; part of the difference is just which pictures came up.\n\nWith this on, the run keeps a second, smoothed copy of the weights alongside the real ones and nudges it a little way towards the current weights after every step. That smoothed copy is what gets saved — as the checkpoints, as the final result, and as what the test samples are rendered from. Training itself is completely unaffected.\n\nWhat you get is a result that depends less on exactly where the run stopped: the quality difference between neighbouring checkpoints shrinks, and a run that goes on too long degrades more gradually, because an average lags behind. What it costs is one extra copy of whatever is being trained — nothing worth thinking about for a LoRA, a second whole model for a full finetune, which the memory estimate below accounts for.\n\nThe early part of a run is handled for you: a fresh average starts out equal to the untrained weights, so the run keeps it short at first and lengthens it as training goes on. Without that, a short run would save an average still holding its own random starting point.":
    "Cada passo de treinamento move os pesos um pouco, e cada um desses movimentos é ruidoso: ele é calculado a partir de um punhado de imagens, e um punhado diferente teria puxado para um lugar um pouco distinto. Por isso os pesos do passo 1400 não são confiavelmente melhores que os do passo 1200; parte da diferença é simplesmente quais imagens saíram.\n\nCom isto ligado, a execução mantém uma segunda cópia suavizada dos pesos ao lado dos reais e a empurra um pouco na direção dos pesos atuais depois de cada passo. É essa cópia suavizada que é salva — como checkpoints, como resultado final e como aquilo a partir do que as amostras de teste são renderizadas. O treinamento em si não é afetado em nada.\n\nO que você ganha é um resultado que depende menos de onde exatamente a execução parou: a diferença de qualidade entre checkpoints vizinhos encolhe, e uma execução que se estende demais se degrada mais gradualmente, porque uma média fica para trás. O custo é uma cópia extra do que estiver sendo treinado — nada que mereça preocupação num LoRA, um segundo modelo inteiro num finetune completo, o que a estimativa de memória abaixo já leva em conta.\n\nO começo da execução é resolvido para você: uma média nova parte igual aos pesos não treinados, então a execução a mantém curta no início e a alonga conforme o treinamento avança. Sem isso, uma execução curta salvaria uma média que ainda guardaria seu próprio ponto de partida aleatório.",
  "Averaging window":
    "Janela da média",
  "How much of the old average is kept each step. 0.999 averages roughly the last 1000 steps; lower follows training more closely, higher smooths harder.":
    "Quanto da média antiga é mantido a cada passo. 0,999 faz a média de cerca dos últimos 1000 passos; menor acompanha o treinamento mais de perto, maior suaviza mais forte.",
  "The fraction of the existing average kept at each step, with the rest taken from the current weights. It decides how long a stretch of training the saved result reflects — roughly 1 ÷ (1 − this value) steps.\n\n0.999 is about the last 1000 steps and is a sensible default for runs of a few thousand. On a short run (say 800 steps) that window is longer than the run itself, so the average never quite catches up — drop to 0.99 (about 100 steps) there. On a very long run you can go higher for a steadier result.\n\nAs a rule of thumb, keep the window well under the total number of steps.":
    "A fração da média existente mantida a cada passo, com o resto vindo dos pesos atuais. Ela decide que trecho do treinamento o resultado salvo reflete — mais ou menos 1 ÷ (1 − este valor) passos.\n\n0,999 são cerca dos últimos 1000 passos e é um padrão sensato para execuções de alguns milhares. Numa execução curta (digamos 800 passos) essa janela é maior que a própria execução, então a média nunca alcança de fato — caia ali para 0,99 (cerca de 100 passos). Numa execução muito longa dá para subir, para um resultado mais estável.\n\nComo regra de bolso, mantenha a janela bem abaixo do número total de passos.",
  "Mostly a memory choice, except for Prodigy, which works the learning rate out for itself. Adafactor saves the most memory and runs on every GPU; 8-bit AdamW saves less and needs an NVIDIA or AMD card.":
    "Sobretudo uma escolha de memória, exceto pelo Prodigy, que calcula a taxa de aprendizado sozinho. O Adafactor economiza mais memória e roda em qualquer GPU; o AdamW (8 bits) economiza menos e exige uma placa NVIDIA ou AMD.",
  "The optimizer is what actually turns gradients into weight changes. It does that using running statistics it keeps for every weight being trained — and those statistics are memory, which for a full finetune is usually most of what the run needs.\n\nAdamW is the standard choice and the safest. It keeps two statistics per trained weight, so a full finetune pays for the model roughly three times over: the weights themselves, plus two more of the same size.\n\nAdamW (8-bit) stores those two statistics at one byte each instead of four. It is a smaller saving than it sounds, because the weights and their gradients do not shrink, and it needs an NVIDIA or AMD (ROCm) GPU — elsewhere the run says so and uses plain AdamW.\n\nAdafactor replaces the larger of the two statistics with a per-row and a per-column summary of it, which is a fraction of the size. It saves considerably more than the 8-bit variant and it runs on every GPU, including Apple silicon — where it is the only memory saving available at all, since the 8-bit variant cannot run there. What it costs is a little stability: it usually wants a slightly higher learning rate than AdamW, so if a run learns nothing after a few hundred steps, raise the rate before changing anything else.\n\nProdigy is a different kind of answer. It measures how far the weights have travelled from where they started and works the learning rate out from that as it goes, which removes the one setting here that genuinely has to be found by trial: the right rate depends on the model, the dataset size and what is being taught, so a value that suits one job is wrong for the next. With it selected, the learning rate on the Optimization page becomes a multiplier on what it finds, and 1 means 'as found'. It uses a little more memory than AdamW, and it needs a few hundred steps to work its estimate up — so early samples look untrained even when the run is fine.\n\nFor LoRA training the memory differences are a rounding error, since only the small adapter has optimizer state. Leave it on AdamW for a first run; reach for Prodigy when you are tired of guessing the rate, and for Adafactor when a full finetune will not fit.":
    "O otimizador é o que de fato transforma gradientes em mudanças de peso. Ele faz isso com estatísticas correntes que mantém para cada peso treinado — e essas estatísticas são memória, que num finetune completo costuma ser a maior parte do que a execução precisa.\n\nO AdamW é a escolha padrão e a mais segura. Ele mantém duas estatísticas por peso treinado, então um finetune completo paga o modelo umas três vezes: os pesos em si, mais duas cópias do mesmo tamanho.\n\nO AdamW (8 bits) guarda essas duas estatísticas com um byte cada em vez de quatro. A economia é menor do que parece, porque os pesos e seus gradientes não encolhem, e exige uma GPU NVIDIA ou AMD (ROCm) — em outros lugares a execução avisa e usa o AdamW comum.\n\nO Adafactor substitui a maior das duas estatísticas por um resumo por linha e outro por coluna, o que ocupa uma fração. Economiza bem mais que a variante de 8 bits e roda em qualquer GPU, inclusive Apple silicon — onde é, aliás, a única economia de memória disponível, já que a variante de 8 bits não roda lá. O custo é um pouco de estabilidade: ele costuma querer uma taxa de aprendizado um pouco mais alta que o AdamW, então se uma execução não aprende nada depois de algumas centenas de passos, aumente a taxa antes de mudar qualquer outra coisa.\n\nO Prodigy é um tipo diferente de resposta. Ele mede o quanto os pesos se afastaram do ponto de partida e deriva daí a taxa de aprendizado ao longo do caminho, o que elimina o único ajuste daqui que realmente precisa ser achado por tentativa: a taxa certa depende do modelo, do tamanho do conjunto de dados e do que está sendo ensinado, então um valor que serve para uma tarefa está errado na seguinte. Com ele selecionado, a taxa de aprendizado da página Otimização vira um multiplicador do que ele encontrar, e 1 significa “como encontrado”. Usa um pouco mais de memória que o AdamW e precisa de algumas centenas de passos para levantar sua estimativa — por isso as primeiras amostras parecem não treinadas mesmo quando a execução está bem.\n\nNo treinamento de LoRA as diferenças de memória são erro de arredondamento, já que só o pequeno adaptador tem estado de otimizador. Deixe no AdamW numa primeira execução; recorra ao Prodigy quando cansar de adivinhar a taxa, e ao Adafactor quando um finetune completo não couber.",
  "AdamW (8-bit)":
    "AdamW (8 bits)",
  "Prodigy (finds its own rate)":
    "Prodigy (acha a própria taxa)",
  "Prodigy works the learning rate out for itself, so the rate on the Optimization page becomes a multiplier on what it finds — 1 leaves it alone. It needs a few hundred steps to settle, so early samples will look untrained.":
    "O Prodigy calcula a taxa de aprendizado sozinho, então a taxa da página Otimização vira um multiplicador do que ele encontrar — 1 deixa como está. Ele precisa de algumas centenas de passos para assentar, então as primeiras amostras vão parecer não treinadas.",
  "Regularization":
    "Regularização",
  "How much reminders count":
    "Quanto os lembretes contam",
  "1 gives a regularization picture the same say as a training picture, which is the usual setting. Lower makes it a gentler reminder.":
    "1 dá a uma imagem de regularização o mesmo peso de uma imagem de treinamento, que é o ajuste usual. Menor a torna um lembrete mais suave.",
  "Regularization pictures are in the run to hold the model's existing idea of a thing in place while you teach it something new. This is how much each of them counts against a training picture, which counts 1.\n\n1 is the classic setting and a good starting point. Lower it if the run seems reluctant to learn what you are actually training — the reminders are pulling too hard. Raise it if what you are training keeps leaking into everything else of the same kind, which is the problem they exist to solve.\n\nThis is separate from a query's weight, which decides how OFTEN those pictures come up. How often and how much are different questions: a set of reminders is usually wanted often but quietly.":
    "Imagens de regularização estão na execução para segurar no lugar a ideia que o modelo já tem de uma coisa enquanto você lhe ensina algo novo. Isto é quanto cada uma delas conta diante de uma imagem de treinamento, que conta 1.\n\n1 é o ajuste clássico e um bom ponto de partida. Abaixe se a execução parecer relutante em aprender o que você está de fato treinando — os lembretes estão puxando forte demais. Aumente se o que você treina fica vazando para tudo o mais do mesmo tipo, que é exatamente o problema que eles existem para resolver.\n\nIsto é independente do peso de uma consulta, que decide COM QUE FREQUÊNCIA essas imagens aparecem. Frequência e intensidade são perguntas diferentes: um conjunto de lembretes normalmente se quer frequente, mas discreto.",
  "Pictures that remind the model what it already knows, instead of teaching it something new — they stop what you are training from spreading to everything else of the same kind. They never get the trigger word.":
    "Imagens que lembram ao modelo o que ele já sabe, em vez de lhe ensinar algo novo — elas impedem que o que você treina se espalhe para tudo o mais do mesmo tipo. Elas nunca recebem o trigger.",
  "These pictures hold the model's existing idea of the subject in place: pick the same KIND of thing you are training, but not the thing itself. You do not need to exclude your training pictures — anything an ordinary query matches stays a training picture. A reminder query that matches only training pictures leaves this pool empty, and the run says so in its log.":
    "Estas imagens seguram no lugar a ideia que o modelo já tem do assunto: escolha o mesmo TIPO de coisa que você está treinando, mas não a coisa em si. Você não precisa excluir suas imagens de treino — o que uma consulta comum encontrar continua sendo imagem de treino. Uma consulta de lembrete que só encontre imagens de treino deixa este conjunto vazio, e a execução avisa no log.",
  "Keep the text encoder on the CPU":
    "Manter o codificador de texto na CPU",
  "Frees all of its VRAM instead of some. The next batch's prompt is encoded while this one trains, so it costs nothing as long as the processor keeps up with the card.": "Libera toda a sua VRAM em vez de só uma parte. O prompt do próximo lote é codificado enquanto este treina, então não custa nada enquanto o processador acompanhar a placa.",
  "The row above makes the text encoder smaller; this one takes it off the graphics card altogether. Its weights stay in ordinary system memory and each prompt is turned into an embedding there, so the encoder occupies no VRAM at all — where quantizing it leaves roughly a third of it resident.\n\nMeasured on an RTX 5070 Ti at 4-bit, this takes Chroma from 9.6 GB to 5.3 and FLUX.1 from 11.4 to 7.0, which was enough to train FLUX.2 Klein at a resolution that did not previously fit.\n\nWhat it costs is one pass over the encoder per step, on the processor instead of the graphics card — and the next batch's prompt is encoded while the current one trains, so the card only waits where the processor is slower than a whole step. Measured on a 16-core desktop, T5-XXL takes about 1.3 seconds a prompt: a 1024-pixel step on an RTX 5090 hides that entirely, a 512-pixel step (half a second) does not. It cannot be combined with training the text encoder, which would mean doing that training on the processor.":
    "A linha acima deixa o codificador de texto menor; esta o tira de vez da placa de vídeo. Os pesos ficam na memória comum do sistema e cada prompt vira um embedding ali, de modo que o codificador não ocupa VRAM alguma — enquanto quantizá-lo deixa cerca de um terço residente.\n\nMedido numa RTX 5070 Ti em 4 bits, o Chroma cai de 9,6 GB para 5,3 e o FLUX.1 de 11,4 para 7,0 — o bastante para treinar o FLUX.2 Klein numa resolução que antes não cabia.\n\nO custo é uma passagem pelo codificador por passo, no processador em vez da placa de vídeo — e o prompt do próximo lote é codificado enquanto o atual treina, então a placa só espera onde o processador é mais lento que um passo inteiro. Medido num desktop de 16 núcleos, o T5-XXL leva cerca de 1,3 segundo por prompt: um passo a 1024 pixels numa RTX 5090 esconde isso por completo, um passo a 512 pixels (meio segundo) não. Não pode ser combinado com o treino do codificador de texto, que significaria fazer esse treino no processador.",

  // ---- the METHOD is an adapter, of which LoRA is one kind ----
  "An adapter is a small add-on file layered over the untouched model — fast, low memory, ideal for styles, characters and concepts. Full finetune rewrites the whole model: much more VRAM and data needed, only worth it for broad domain shifts. Which kind of adapter is the next question down.":
    "Um adaptador é um pequeno arquivo acrescentado sobre o modelo intocado — rápido, pouca memória, ideal para estilos, personagens e conceitos. O finetune completo reescreve o modelo inteiro: precisa de muito mais VRAM e muito mais dados, e só compensa para mudanças amplas de domínio. Qual tipo de adaptador é a próxima pergunta, logo abaixo.",
  "An adapter leaves the base model untouched and trains a small add-on (a few dozen MB) that is layered on top at generation time. It is quick, fits ordinary hardware, can be mixed with other adapters and dialled up or down by weight — and it is enough for styles, characters, objects and most concepts. There are two kinds, LoRA and LoKr, and the Adapter section below picks between them; LoRA is the one to start with.\n\nA full finetune rewrites every weight of the model. It produces a multi-gigabyte model of its own, needs far more VRAM, far more images and much lower learning rates, and it can forget things it used to know. Reach for it only when you are moving the model into a genuinely different domain, not to teach it one more subject.":
    "Um adaptador deixa o modelo base intocado e treina um pequeno acréscimo (algumas dezenas de MB) que é sobreposto na hora de gerar. É rápido, cabe em hardware comum, dá para misturar com outros adaptadores e ajustar a força por peso — e basta para estilos, personagens, objetos e a maioria dos conceitos. Há dois tipos, LoRA e LoKr; a seção Adaptador abaixo escolhe entre eles, e LoRA é o de começar.\n\nUm finetune completo reescreve todos os pesos do modelo. Produz um modelo próprio de vários gigabytes, precisa de muito mais VRAM, muito mais imagens e taxas de aprendizado bem menores, e pode esquecer coisas que sabia. Recorra a ele só quando estiver levando o modelo para um domínio genuinamente diferente, não para lhe ensinar mais um assunto.",
  "Start from an existing adapter":
    "Partir de um adaptador existente",
  "A fresh adapter starts from noise and has to learn your concept from nothing. Starting from an existing one keeps everything it already learned and refines it — the usual reasons are adding new images to a concept you trained before, or nudging one that came out almost right.\n\nWeight sets trained on the same base model are offered — including ones trained on another model built on it — and the new job has to match the one it continues: the same adapter type, the same rank, and the same layer targeting. The trainer stops with a message naming what it found otherwise. Picking a job's finished result continues where it ended; picking an intermediate checkpoint rewinds to that point and continues from there.":
    "Um adaptador novo parte do ruído e tem que aprender seu conceito do zero. Partir de um existente mantém tudo o que ele já aprendeu e o refina — os motivos usuais são acrescentar imagens novas a um conceito já treinado, ou ajustar um que saiu quase certo.\n\nSão oferecidos conjuntos de pesos treinados com o mesmo modelo base — inclusive os treinados com outro modelo construído sobre ele — e a nova tarefa precisa bater com a que ela continua: mesmo tipo de adaptador, mesmo rank e mesma seleção de camadas. Caso contrário o treinador para com uma mensagem dizendo o que encontrou. Escolher o resultado concluído de uma tarefa continua de onde ele parou; escolher um checkpoint intermediário rebobina até aquele ponto e segue dali.",
  "Pick a finished adapter":
    "Escolha um adaptador concluído",
  "No finished adapter for this base model yet":
    "Ainda não há adaptador concluído para este modelo base",
  "Optional: continue training an existing adapter instead of starting from scratch.":
    "Opcional: continuar o treinamento de um adaptador existente em vez de começar do zero.",
  "No full finetune":
    "Sem finetune completo",

  // ---- adapter wording: an adapter is LoRA or LoKr ----
  "The standard choice, and the format every other tool understands — a LoRA can be used anywhere.":
    "A escolha padrão, e o formato que qualquer outra ferramenta entende — um LoRA pode ser usado em qualquer lugar.",
  "An adapter does not rewrite the model — it adds a small 'side channel' to certain layers, and rank is how wide that channel is: how much new information the adapter can hold.\n\nLow ranks (4–8) are plenty for a style or a colour palette and are very hard to overfit. Mid ranks (16–32) suit characters and objects with consistent details. High ranks (64+) mostly grow the file and the overfitting risk without helping, unless you are teaching a genuinely broad new domain.\n\nIt means slightly different things to the two adapter types. For a LoRA it is the hard ceiling on the change: a rank-16 adapter can only ever make a rank-16 change. For a LoKr it bounds only part of the structure, so a LoKr is not confined the way a LoRA is and its file grows far more slowly as you raise it — which is why the size estimate below is a figure for LoRA and a comparison for LoKr.":
    "Um adaptador não reescreve o modelo — ele acrescenta um pequeno “canal lateral” a certas camadas, e o rank é a largura desse canal: quanta informação nova o adaptador consegue guardar.\n\nRanks baixos (4–8) bastam para um estilo ou uma paleta e são bem difíceis de sofrer overfitting. Médios (16–32) combinam com personagens e objetos de detalhes constantes. Altos (64+) quase só aumentam o arquivo e o risco de overfitting sem ajudar, a menos que você esteja ensinando um domínio novo e realmente amplo.\n\nEle significa coisas um pouco diferentes para cada tipo. Num LoRA é o teto rígido da mudança: um adaptador de rank 16 só consegue fazer uma mudança de rank 16. Num LoKr ele limita só parte da estrutura, então um LoKr não fica preso como um LoRA e seu arquivo cresce bem mais devagar quando você o aumenta — por isso abaixo há um número para LoRA e uma comparação para LoKr.",
  "The adapter's output is multiplied by alpha ÷ rank before being added to the model, so alpha sets how loudly the adapter speaks at a given capacity. It works the same way for both adapter types.\n\nThe usual convention is alpha = rank, which makes the scale factor 1 and keeps behaviour comparable when you change rank. Setting alpha to half the rank is a common way to soften an adapter that comes out too strong. It interacts with the learning rate — halving alpha has a similar effect to halving the rate — so change one at a time.":
    "A saída do adaptador é multiplicada por alfa ÷ rank antes de ser somada ao modelo, então alfa decide o quão alto o adaptador fala numa dada capacidade. Funciona igual nos dois tipos de adaptador.\n\nO usual é alfa = rank, o que deixa o fator em 1 e mantém o comportamento comparável quando você muda o rank. Pôr alfa na metade do rank é um jeito comum de suavizar um adaptador que saiu forte demais. Interage com a taxa de aprendizado — reduzir alfa pela metade tem efeito parecido com reduzir a taxa pela metade — então mude uma coisa de cada vez.",
  "This architecture can only be trained as an adapter (LoRA or LoKr) alongside the frozen model. The \"Full finetune\" method, which rewrites the model's own weights, is not offered for it.":
    "Esta arquitetura só pode ser treinada como adaptador (LoRA ou LoKr) ao lado do modelo congelado. O método “Finetune completo”, que reescreve os pesos do próprio modelo, não é oferecido para ela.",
  "No adapters for this base model yet.": "Ainda não há adaptadores para este modelo base.",
  "No trained adapters yet.": "Ainda não há adaptadores treinados.",
  "Which adapter this row applies":
    "Qual adaptador esta linha aplica",
  "Adapter strength: 1 = as trained, below weakens, above strengthens (can distort past ~1.5).":
    "Intensidade do adaptador: 1 = como treinado, abaixo enfraquece, acima fortalece (pode distorcer além de ~1.5).",
  "Add adapter":
    "Adicionar adaptador",
  "Adapters":
    "Adaptadores",
  "Finetune": "Finetune",
  "Generate with a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.":
    "Gerar com os pesos de um finetune completo no lugar dos do modelo base. Os adaptadores se empilham sobre o que for escolhido aqui.",
  "none — the base model": "nenhum — o modelo base",
  "loading finetune": "carregando finetune",
  "Stack trained adapters on the base model, each with its own strength — LoRA or LoKr. An adapter fits the model it was trained on and any other built on the same one.":
    "Empilhe adaptadores treinados sobre o modelo base, cada um com sua própria intensidade — LoRA ou LoKr. Um adaptador serve para o modelo em que foi treinado e para qualquer outro construído sobre o mesmo.",
  "Generated images appear here — try out a trained adapter against its base model.":
    "As imagens geradas aparecem aqui — experimente um adaptador treinado contra o modelo base dele.",
  "A much smaller file, and not limited by the rank the way a LoRA is. Whether it can be used outside this app depends on the model — see the ⓘ.":
    "Um arquivo bem menor e sem o limite de rank de uma LoRA. Se dá para usar fora deste app depende do modelo — veja o ⓘ.",
  "Both add a small trainable layer over the frozen model; they differ in the shape of change they can express.\n\nA LoRA adds a 'low-rank' change: two thin matrices whose product is added to each targeted weight. Its capacity is exactly its rank — a rank-16 adapter can only ever make a rank-16 change, however long you train it. That is ample for a character, an object, a colour palette. It trains a little faster, it is the format every tool reads, and it carries better between related checkpoints: a LoRA trained on one finetune of a model usually still works on another.\n\nLoKr builds the change as a Kronecker product of two much smaller matrices instead. The saving comes from that structure rather than from throwing rank away, so the change is not confined to a thin slice of the weight while the file stays a small fraction of a LoRA's — under a tenth of the trainable parameters at rank 8. LyCORIS, whose method this is, suggests reaching for it when a LoRA 'does not learn well enough', and it is generally the better fit for styles and broad visual qualities, where a LoRA's rank ceiling is what you meet first. Its own caveats are the mirror image: slightly slower to train, and a very small LoKr transfers less well if you later swap the base model for a different finetune.\n\nWhat each can be USED by differs, and it is the file rather than the method. A LoRA is written in the layout every tool reads. A LoKr cannot be: that layout has a place for two matrices and nowhere to put a Kronecker factor. What it gets instead is a copy named the way ComfyUI names LoKr layers, and that works for the models whose layers ComfyUI addresses that way — FLUX.1, FLUX.1 Kontext and the Qwen-Image releases. On the others (SD 1.5, SDXL, Chroma, FLUX.2, Z-Image) a LoKr stays here: it works in the Evaluate tab and as the starting point of another job, but there is no file to hand over. On those, pick LoRA if the result has to leave this app.":
    "Os dois acrescentam uma pequena camada treinável sobre o modelo congelado; diferem na forma de mudança que conseguem expressar.\n\nUma LoRA acrescenta uma mudança de «posto baixo»: duas matrizes finas cujo produto é somado a cada peso alvo. Sua capacidade é exatamente o rank — um adaptador de rank 16 só consegue fazer uma mudança de rank 16, por mais que você treine. Isso é de sobra para um personagem, um objeto, uma paleta de cores. Treina um pouco mais rápido, é o formato que toda ferramenta lê e viaja melhor entre checkpoints aparentados: uma LoRA treinada num finetune de um modelo costuma continuar funcionando em outro.\n\nJá a LoKr constrói a mudança como um produto de Kronecker de duas matrizes bem menores. A economia vem dessa estrutura, e não de jogar rank fora, então a mudança não fica presa a uma fatia estreita do peso enquanto o arquivo é uma fração do de uma LoRA — menos de um décimo dos parâmetros treináveis no rank 8. O LyCORIS, de onde vem o método, sugere recorrer a ela quando uma LoRA «não aprende bem o bastante», e ela costuma servir melhor para estilos e qualidades visuais amplas, onde o teto de rank da LoRA aparece primeiro. As ressalvas são a imagem espelhada: treina um pouco mais devagar, e uma LoKr muito pequena se transfere pior se depois você trocar o modelo base por outro finetune.\n\nPara que cada uma pode SERVIR difere, e isso é questão do arquivo, não do método. Uma LoRA é escrita no formato que toda ferramenta lê. Uma LoKr não pode ser: esse formato tem lugar para duas matrizes e nenhum para um fator de Kronecker. Em vez disso ela ganha uma cópia nomeada como o ComfyUI nomeia camadas LoKr, e isso funciona para os modelos cujas camadas ele endereça assim — FLUX.1, FLUX.1 Kontext e as versões Qwen-Image. Nos demais (SD 1.5, SDXL, Chroma, FLUX.2, Z-Image) uma LoKr fica por aqui: funciona na aba Avaliar e como ponto de partida de outro trabalho, mas não há arquivo para entregar. Nesses, escolha LoRA se o resultado precisar sair deste app.",
  "LoKr expresses a weight's change as one small matrix combined with another. This number decides where the weight is cut into those two parts.\n\nLeft empty, the split is chosen to make the two parts as close to square as possible, which is where they are SMALLEST. Moving it either way grows the file, and the two directions are not the same thing: a low factor (4–8) pushes the weight into the second part, which is where the adapter's capacity is — that is the LyCORIS recipe for a LoKr that is not learning enough. A factor far above the square split grows the first, dense part instead, which costs size for nothing.\n\nMeasured on a 1280-wide layer at rank 8, against the same layer's LoRA: automatic 0.08x, factor 8 0.13x, factor 4 0.25x, factor 128 0.81x.\n\nThere is rarely a reason to set it. If a LoKr adapter is not learning enough, raise the rank first, then try a low factor.":
    "A LoKr expressa a mudança de um peso como uma matriz pequena combinada com outra. Este número decide onde o peso é cortado nessas duas partes.\n\nEm branco, o corte é escolhido para deixar as duas partes o mais quadradas possível, que é onde ficam MENORES. Mexer para qualquer lado aumenta o arquivo, e as duas direções não são a mesma coisa: um fator baixo (4–8) empurra o peso para a segunda parte, onde está a capacidade do adaptador — essa é a receita do LyCORIS para uma LoKr que não está aprendendo o bastante. Um fator muito acima do corte quadrado faz crescer a primeira parte, densa, o que custa tamanho à toa.\n\nMedido numa camada de 1280 de largura no rank 8, contra a LoRA da mesma camada: automático 0,08x, fator 8 0,13x, fator 4 0,25x, fator 128 0,81x.\n\nRaramente há motivo para definir isso. Se uma LoKr não estiver aprendendo o bastante, aumente primeiro o rank e depois tente um fator baixo.",
  "Every picture this finds is also matched by a training query, so it contributes nothing and the run will not be regularized. Narrow it to pictures the run is NOT about.":
    "Toda imagem que isto encontra também é encontrada por uma consulta de treino, então este conjunto não contribui em nada e a execução não será regularizada. Restrinja-o a imagens de que a execução NÃO trata.",
  "val": "val",
  "stable": "estável",
  "validation": "validação",
  "Validate": "Validar",
  "Masked regions": "Regiões mascaradas",
  "Mask out regions tagged": "Mascarar regiões com as tags",
  "Comma-separated tags whose bounding boxes are largely ignored by the loss — e.g. 'watermark'. The picture still trains; the region inside the boxes stops teaching. Tags without boxes on an image mask nothing there.": "Tags separadas por vírgulas cujas caixas são em grande parte ignoradas pela perda — p. ex. 'watermark'. A imagem continua treinando; a região dentro das caixas deixa de ensinar. Tags sem caixas numa imagem não mascaram nada ali.",
  "Mask out regions of tags marked": "Mascarar regiões de tags marcadas",
  "Comma-separated META tags. Any tag the library marks with one of these has its boxes masked — so the rule is stated once in the Tags tab rather than listed here.": "Meta tags separadas por vírgulas. Qualquer tag que a biblioteca marque assim tem suas caixas mascaradas — a regra fica dita uma vez na aba Tags em vez de listada aqui.",
  "Masked region weight": "Peso das regiões mascaradas",
  "How much a masked region still counts. 0 hides it from training entirely; 1 is the same as not masking.": "Quanto uma região mascarada ainda conta. 0 a esconde por completo do treinamento; 1 é o mesmo que não mascarar.",
  "Validation": "Validação",
  "Score a validation loss": "Medir uma perda de validação",
  "A few images are held out of training and re-scored on a fixed seed as the run goes. Falling: still learning. Rising while the training loss falls: memorizing — pick an earlier checkpoint.": "Algumas imagens são reservadas fora do treinamento e reavaliadas com semente fixa ao longo do run. Caindo: ainda aprendendo. Subindo enquanto a perda de treinamento cai: memorizando — escolha um checkpoint anterior.",
  "Validate every": "Validar a cada",
  "Each round costs one forward pass per scored image — a small set every few hundred steps is barely noticeable.": "Cada rodada custa uma passada direta por imagem avaliada — um conjunto pequeno a cada poucas centenas de passos quase não se nota.",
  "Held-out images": "Imagens reservadas",
  "Taken OUT of training entirely and scored each round. Capped at half the dataset; 16 is plenty for a LoRA-sized run. 0 turns the held-out series off.": "Tiradas por completo do treinamento e avaliadas a cada rodada. Limitado à metade do conjunto de dados; 16 bastam para um run do tamanho de um LoRA. 0 desliga a série.",
  "Stable-loss images": "Imagens de perda estável",
  "Ordinary TRAINING images re-scored the same fixed way — the training curve without its sampling noise. They stay in training; 0 turns the series off.": "Imagens de TREINAMENTO comuns reavaliadas do mesmo jeito fixo — a curva de treinamento sem o ruído de amostragem. Elas continuam no treinamento; 0 desliga a série.",
  "Some pictures are worth training on except for one rectangle: a watermark, a shop’s caption strip, a censor bar. Left alone, the model learns the rectangle along with the picture — a run over watermarked photographs reliably teaches the watermark. Throwing those pictures out costs the dataset; this keeps them and hides the rectangle from training instead.\n\nThe regions come from the boxes already on the tag: draw a box for `watermark` in the annotator (or let the watermark detector’s tag carry one), name the tag here, and every image carrying such a box trains with the loss inside it turned down. Where a subject tag has no drawn box, its detected faces stand in, exactly as they do for crop-aware training. An image whose named tags have no boxes trains completely normally — nothing is masked there.\n\nOnly the LOSS is masked. The pixels still pass through the image encoder, so the cached latents are the ordinary ones shared with unmasked runs, and nothing is re-encoded when this setting changes. The mask lives in latent space, where one cell covers 8×8 pixels rounded outward to whole cells — so it cannot hide anything much thinner than that, and a pixel-accurate outline is not something it can promise. It also cannot conjure what is UNDER the watermark: the model simply receives no signal about that area, from this picture.\n\nPairs naturally with a tag the prompt always includes (Always include under Tag selection): the prompt says the watermark is there, the mask stops the pixels teaching it, and at generation time the model has no reason to produce one unprompted.": "Algumas imagens valem o treinamento exceto por um retângulo: uma marca d'água, a faixa de texto de uma loja, uma barra de censura. Sem tratamento, o modelo aprende o retângulo junto com a imagem — um run sobre fotos com marca d'água ensina a marca d'água sem falta. Jogar essas imagens fora custa o conjunto de dados; isto as mantém e, em vez disso, esconde o retângulo do treinamento.\n\nAs regiões vêm das caixas que a tag já tem: desenhe uma caixa para `watermark` no anotador (ou deixe a tag do detector de marca d'água carregar uma), nomeie a tag aqui, e toda imagem com uma caixa dessas treina com a perda reduzida ali dentro. Onde uma tag de pessoa não tem caixa desenhada, os rostos detectados entram no lugar, exatamente como no corte ciente das caixas. Uma imagem cujas tags nomeadas não têm caixas treina de forma totalmente normal — nada é mascarado ali.\n\nSó a PERDA é mascarada. Os pixels ainda passam pelo codificador de imagem, então os latentes em cache são os comuns, compartilhados com runs sem máscara, e nada é recodificado quando este ajuste muda. A máscara vive no espaço latente, onde uma célula cobre 8×8 pixels arredondados para fora em células inteiras — ela não consegue esconder nada muito mais fino que isso, e um contorno preciso ao pixel não é algo que possa prometer. Também não consegue inventar o que há SOB a marca d'água: o modelo simplesmente não recebe sinal daquela área, a partir desta imagem.\n\nCombina naturalmente com uma tag que o prompt sempre inclui (Sempre incluir, em Seleção de tags): o prompt diz que a marca d'água está lá, a máscara impede os pixels de ensiná-la, e na geração o modelo não tem motivo para produzir uma sem que peçam.",
  "The same rule, stated once in the library instead of tag by tag here. A meta tag put on the tags whose boxes should never teach — `masked`, say — covers every such tag at once, including ones created after this job was written.\n\nThe list is resolved to tag names when the dataset is built, so the job’s log says how many images actually carried a masked region. A run where that line says zero has a rule pointing at tags nobody drew boxes for.": "A mesma regra, dita uma vez na biblioteca em vez de tag por tag aqui. Uma meta tag posta nas tags cujas caixas nunca devem ensinar — `masked`, digamos — cobre todas essas tags de uma vez, inclusive as criadas depois deste trabalho ser escrito.\n\nA lista é resolvida em nomes de tag quando o conjunto de dados é montado, então o log do trabalho diz quantas imagens de fato carregavam uma região mascarada. Um run em que essa linha diz zero tem uma regra apontando para tags em que ninguém desenhou caixas.",
  "What a cell inside a masked box still counts for. 0 hides the region entirely, which is the usual choice for a watermark — there is nothing in it worth a whisper. A small value (0.05–0.2) keeps a faint signal, which can be worth it when the boxes are generous and cover real picture around the thing being hidden.\n\n1 is the unmasked loss, so setting it there is the same as clearing the tag lists. Where an image also trains with an alpha mask, the two multiply: a masked region on a transparent background is doubly not the picture.": "Quanto uma célula dentro de uma caixa mascarada ainda conta. 0 esconde a região por inteiro, a escolha usual para uma marca d'água — não há nada nela que valha um sussurro. Um valor pequeno (0,05–0,2) mantém um sinal fraco, o que pode compensar quando as caixas são generosas e cobrem imagem de verdade em volta do que se esconde.\n\n1 é a perda sem máscara, então deixá-lo ali é o mesmo que esvaziar as listas de tags. Quando uma imagem também treina com máscara alfa, as duas se multiplicam: uma região mascarada sobre fundo transparente é duplamente não-a-imagem.",
  "The training loss cannot answer the question people ask of it. It is drawn from the pictures being trained on, at a different random noise level every step, so it is noisy by construction — and it keeps falling for as long as the model memorizes, which means it looks healthiest exactly when a run has gone on too long.\n\nThis scores two extra series that can answer it, both with the plain per-sample loss on a fixed seed, so every round asks the model exactly the same questions and the number moves only when the model does. The series appear as their own lines on the loss graph, and each round is a line in the job’s log.\n\nReading it: the validation loss falls while the model generalizes and flattens or turns when it starts memorizing — the turning point is roughly where to stop, and with step snapshots on, the checkpoint to pick. Expect it to sit above the training loss and to move in small amounts; what matters is the direction, not the level. It stays comparable across pauses, resumes and step extensions, because the scored images and the seed never change within a job.": "A perda de treinamento não consegue responder a pergunta que fazem a ela. Ela é tirada das imagens em treinamento, a cada passo num nível de ruído aleatório diferente, então é ruidosa por construção — e continua caindo enquanto o modelo memoriza, ou seja, parece mais saudável exatamente quando um run passou do ponto.\n\nIsto avalia duas séries extras que conseguem responder, ambas com a perda simples por amostra numa semente fixa, de modo que cada rodada faz ao modelo exatamente as mesmas perguntas e o número só se move quando o modelo se move. As séries aparecem como linhas próprias no gráfico de perda, e cada rodada é uma linha no log do trabalho.\n\nComo ler: a perda de validação cai enquanto o modelo generaliza e achata ou vira quando ele começa a memorizar — o ponto de virada é mais ou menos onde parar e, com snapshots de passo ligados, o checkpoint a escolher. Espere vê-la acima da perda de treinamento e se movendo em quantidades pequenas; o que importa é a direção, não o nível. Ela permanece comparável através de pausas, retomadas e extensões de passos, porque as imagens avaliadas e a semente nunca mudam dentro de um trabalho.",
  "How often a round runs, in steps. A round costs one forward pass per scored image — no gradients, no optimizer — so a 16-image set is a few seconds; matching the sample or checkpoint cadence keeps the graph, the images and the snapshots telling one story at the same steps.\n\nVery frequent rounds buy little: overfitting announces itself over hundreds of steps, not five.": "De quantos em quantos passos uma rodada roda. Uma rodada custa uma passada direta por imagem avaliada — sem gradientes, sem otimizador — então um conjunto de 16 imagens leva poucos segundos; casar a cadência com a das amostras ou dos checkpoints faz o gráfico, as imagens e os snapshots contarem uma história só nos mesmos passos.\n\nRodadas muito frequentes rendem pouco: o sobreajuste se anuncia ao longo de centenas de passos, não de cinco.",
  "How many images are set aside for the validation loss. They are taken OUT of training entirely — never visited, in no pool, their captions never seen — because a loss over pictures the model is also memorizing measures nothing. The pick is random but fixed per job, whole images at a time (a picture cannot be half in training), regularization pools are not eligible, and it is capped at half the dataset so the setting can never eat the run it protects.\n\nMore images make a steadier line at a linearly higher cost per round. On a small dataset every held-out image is also a training image lost, which is the real price — 8–16 is usually enough to see the turn, and the job’s log says exactly how many were held out.": "Quantas imagens são reservadas para a perda de validação. Elas saem por completo do treinamento — nunca visitadas, em nenhum pool, suas legendas nunca vistas — porque uma perda sobre imagens que o modelo também está memorizando não mede nada. O sorteio é aleatório mas fixo por trabalho, por imagens inteiras (uma imagem não pode estar meio no treinamento), pools de regularização não são elegíveis, e há um teto na metade do conjunto de dados para que o ajuste nunca devore o run que protege.\n\nMais imagens fazem uma linha mais firme a um custo por rodada linearmente maior. Num conjunto pequeno, cada imagem reservada é também uma imagem de treinamento perdida, que é o preço real — 8–16 costumam bastar para ver a virada, e o log do trabalho diz exatamente quantas foram reservadas.",
  "A second series over ordinary TRAINING images: a fixed slice, re-scored with the same fixed seed each round. Nothing is held out — these stay in training — so it costs no data at all.\n\nWhat it shows is the training curve with the sampling noise removed. The per-step loss jumps around because every step draws different pictures at different noise levels; this line asks the same pictures at the same noise every time, so it is readable where the raw curve is a cloud. Compared against the held-out line it also localizes trouble: both falling is learning, stable falling while held-out rises is memorizing, and neither falling means the run is not learning at all.": "Uma segunda série sobre imagens de TREINAMENTO comuns: uma fatia fixa, reavaliada a cada rodada com a mesma semente fixa. Nada é reservado — elas continuam treinando — então não custa dado nenhum.\n\nO que ela mostra é a curva de treinamento sem o ruído de amostragem. A perda por passo pula porque cada passo sorteia imagens diferentes em níveis de ruído diferentes; esta linha faz sempre as mesmas perguntas às mesmas imagens, e dá para ler onde a curva crua é uma nuvem. Comparada com a linha reservada, ela ainda localiza o problema: as duas caindo é aprendizado, a estável caindo enquanto a reservada sobe é memorização, e nenhuma caindo significa que o run não está aprendendo nada.",
  "Save the current rules, or load a saved set": "Salvar as regras atuais ou carregar um conjunto salvo",
  "Rule sets": "Conjuntos de regras",
  "Remember the current rules — name the set in this list afterwards": "Lembrar as regras atuais — nomeie o conjunto nesta lista depois",
  "Add a rule first": "Adicione uma regra primeiro",
  "Save current rules": "Salvar regras atuais",
  "Add this set's rules to the job — rows it already has stay put": "Adicionar as regras deste conjunto ao trabalho — as linhas já presentes ficam",
  "Value rules": "Regras de valor",
  "Turn numeric value tags (height:172cm) into words at prompt time. The first matching rule wins — drag rows to reorder.": "Transforma tags de valor numéricas (height:172cm) em palavras na hora do prompt. A primeira regra que casar vence — arraste as linhas para reordenar.",
  "namespace, e.g. height": "namespace, p. ex. height",
  "Keep the raw tag in the prompt beside the rule's text": "Manter a tag crua no prompt ao lado do texto da regra",
  "keep tag": "manter tag",
  "Remove this rule": "Remover esta regra",
  "Add rule": "Adicionar regra",
  "Any tag shaped `<name>:<number><unit>` is a value tag — `people:3`, `height:172cm`, `height:1.72m`, or a ranking’s own `quality:7` — and a rule here turns a range of those numbers into words at prompt time: where `height` is greater than 190cm, write `tall`. A raw `height:172cm` token teaches a text encoder nothing it can read back at generation time; a word does.\n\nA matching tag is replaced by the rule’s text, and a per-rule toggle keeps the raw tag alongside for whoever wants both spellings in the prompt. The metric length and mass families convert, so one rule covers `172cm` and `1.72m` alike; an unknown unit compares only against the same unit, and a plain number only against plain numbers.\n\nRanges may overlap, and the first matching rule wins — the rows are dragged into order, and that order is part of the configuration. A value tag no rule matches passes through the prompt unchanged, so nothing is dropped silently. The rule’s phrase rides the ordinary random pick and dropout like the tag it replaced: prompts sometimes carry it and sometimes do not, which is exactly the variation score-tag conditioning wants.\n\nThe rules are resolved when the dataset is built — the job’s log says how many tags they matched — and a set of rules can be saved and loaded by name, so a house vocabulary is written once and reused across jobs. Loading a set adds its missing rules to the job rather than replacing the rows already there.": "Qualquer tag no formato `<nome>:<número><unidade>` é uma tag de valor — `people:3`, `height:172cm`, `height:1.72m`, ou o próprio `quality:7` de um ranking — e uma regra aqui transforma uma faixa desses números em palavras na hora do prompt: onde `height` for maior que 190cm, escreva `tall`. Um token cru `height:172cm` não ensina nada que um codificador de texto possa ler de volta na geração; uma palavra ensina.\n\nUma tag que casa é substituída pelo texto da regra, e um interruptor por regra mantém a tag crua ao lado para quem quiser as duas grafias no prompt. As famílias métricas de comprimento e massa se convertem, então uma regra cobre `172cm` e `1.72m` igualmente; uma unidade desconhecida só se compara com a mesma unidade, e um número puro só com números puros.\n\nAs faixas podem se sobrepor, e a primeira regra que casar vence — as linhas são arrastadas para reordenar, e essa ordem faz parte da configuração. Uma tag de valor que nenhuma regra alcança passa pelo prompt inalterada: nada é descartado em silêncio. A frase da regra segue o sorteio aleatório e o dropout como a tag que substituiu: os prompts às vezes a carregam e às vezes não, exatamente a variação que o condicionamento por pontuação quer.\n\nAs regras são resolvidas na construção do conjunto de dados — o log do trabalho diz quantas tags elas casaram — e um conjunto de regras pode ser salvo e carregado por nome, então um vocabulário da casa é escrito uma vez e reutilizado entre trabalhos. Carregar um conjunto adiciona as regras que faltam em vez de substituir as linhas já presentes.",
  "Write tags as":
    "Escrever tags como",
  "Their name":
    "seu nome",
  "Their comment":
    "seu comentário",
  "Name and comment":
    "nome e comentário",
  "A tag's comment is the one line beside its name in the Tags tab — the same idea in words a text encoder can read. A tag with no comment is written as its name.":
    "O comentário de uma tag é a linha ao lado do nome na aba Tags — a mesma ideia em palavras que um codificador de texto consegue ler. Uma tag sem comentário é escrita pelo nome.",
  "A tag's comment is the one line beside its name in the Tags tab — “one girl in the picture” for `1girl`, “from below, looking up at the subject” for `from_below`. A booru vocabulary is compact for the people typing it and opaque to a text encoder; the comment is the same idea in words the encoder can read.\n\n“Their name” is what every run did: the tag as it is spelled. “Their comment” writes the comment in place of the name wherever a picked tag has one, and “Name and comment” writes the name with the comment in brackets after it, so the model learns both spellings of one thing. A tag with no comment is written as its name whatever this says.\n\nOnly the PROMPT changes. Matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all stay keyed on the tag's name, exactly as with aliases — and the comment is read from the library when the dataset is built, so editing a comment later changes the next run, not this one.":
    "O comentário de uma tag é a linha ao lado do nome na aba Tags — “uma garota na imagem” para `1girl`, “de baixo, olhando para o sujeito” para `from_below`. Um vocabulário booru é compacto para quem digita e opaco para um codificador de texto; o comentário é a mesma ideia em palavras que o codificador consegue ler.\n\n“Seu nome” é o que todo treino fazia: a tag como se escreve. “Seu comentário” escreve o comentário no lugar do nome onde uma tag escolhida tem um, e “Nome e comentário” escreve o nome com o comentário entre parênteses, para o modelo aprender as duas grafias de uma coisa. Uma tag sem comentário é escrita pelo nome de qualquer forma.\n\nSó o PROMPT muda. A correspondência, as listas sempre/excluir, o balanceamento por frequência, o peso da perda e as caixas que um recorte precisa manter continuam presos ao nome da tag, exatamente como com aliases — e o comentário é lido da biblioteca quando o conjunto de dados é montado, então editar um comentário depois muda o próximo treino, não este.",
  "Remove the selected images?": "Remover as imagens selecionadas?",
  "They cannot be recovered.": "Elas não podem ser recuperadas.",
  "Delete all {n} results from this session?": "Excluir os {n} resultados desta sessão?",
  "The generated images go with them.": "As imagens geradas vão com eles.",
  "Its downloaded weights can go with it, or stay in the cache for a later download to find.": "Seus pesos baixados podem ir junto, ou ficar no cache para um download posterior encontrar.",
  "Remove and delete weights": "Remover e excluir os pesos",
  "Remove the training job “{name}”?": "Remover o trabalho de treinamento “{name}”?",
  "Remove {n} training jobs?": "Remover {n} trabalhos de treinamento?",
  "Its checkpoints, test samples and trained result are deleted with it — except anything locked, which is kept in the LoRAs list. This cannot be undone.": "Seus checkpoints, amostras e resultado treinado são removidos junto, e isso não pode ser desfeito. Exceto o que estiver bloqueado, que fica na lista de LoRAs.",
  "Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone.": "Seus checkpoints, amostras e resultados treinados são removidos junto, e isso não pode ser desfeito. Exceto o que estiver bloqueado, que fica na lista de LoRAs.",
  "The Train tab": "A aba Treinar",
  "The Evaluate tab": "A aba Avaliar",
  "The Models tab": "A aba Modelos",
  "Your models": "Seus modelos",
  "Finetunes": "Finetunes",
  "Based on {model}": "Baseado em {model}",
  "A full finetune of {model}": "Um finetune completo de {model}",
  "The built-in release, one of your own models, or a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.": "A versão integrada, um dos seus próprios modelos ou os pesos de um finetune completo no lugar dos do modelo base. Os adaptadores se empilham sobre o que for escolhido aqui.",
};

export default CATALOG;
