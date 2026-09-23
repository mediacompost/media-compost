// uses live in the APP catalog; this file holds only train-chunk strings.

import type { Catalog } from "../../shared/i18nCore";

const CATALOG: Catalog = {
  "default":
    "기본값",
  "This model's own size. A job set to it follows whichever model it is pointed at.":
    "이 모델 자체의 크기입니다. 여기에 맞춘 실행은 가리키는 모델을 따라갑니다.",
  "{n} px":
    "{n} px",
  "A run trains at one size at least.":
    "실행에는 최소한 하나의 크기가 필요합니다.",
  "A run trains at up to five sizes — each one is another pass over the dataset per epoch.":
    "한 번의 실행은 최대 다섯 개의 크기까지 사용합니다. 크기 하나마다 에폭당 데이터셋을 한 번 더 돕니다.",
  "e.g. 704":
    "예: 704",
  "Another size…":
    "다른 크기…",
  "Pick every size this run should train at. A picture joins each one it is big enough for, so the same picture can be learnt at more than one scale — and each size is another pass over the dataset per epoch.":
    "이 실행이 학습할 크기를 모두 고릅니다. 사진은 충분히 큰 크기마다 함께 들어가므로 같은 사진을 여러 배율에서 배우게 되며, 크기 하나마다 에폭당 데이터셋을 한 번 더 돕니다.",
  "Left empty both fields use the model's own size — a test sample is not tied to the sizes the run trains at.":
    "두 칸을 비워 두면 모델 자체의 크기를 사용합니다. 테스트 이미지는 학습 크기에 묶이지 않습니다.",
  "The sizes images are trained at, each given as one number that stands for a pixel budget: 1024 means 'about a megapixel', which every aspect-ratio bucket then spends differently — 1024×1024, or 1216×832, or 832×1216.\n\nMatch them to what the base model was trained on (1024 for SDXL, Chroma and FLUX.2, 512 for SD 1.5); training far above that teaches little and costs a lot, while training below it is a genuine speed and memory lever at the price of fine detail. Cost scales with the area, so 768 is nearly half the work per step that 1024 is. The size the list marks as default is the model's own, and a job set to it follows whichever model it is pointed at.\n\nPicking more than one trains the same pictures at each of them. A model that has only ever seen a subject at 1024 has learnt it together with the canvas it was on: asked for something smaller it tends to answer with a crop or a doubled-up version of the same framing. Several sizes separate what the model learns about the subject from what it learns about the shape of the picture.\n\nEach size is a full family of buckets, and every image joins the ones it is large enough for — which is the other half of what this is for. Under Never upscale a 700-pixel scan is simply left out of a 1024 run; add 512 and it trains there instead of being dropped, while the large pictures keep training at both.\n\nIt is not free. A size is another pass over the dataset in every epoch and another cached latent per picture, and the batches at the largest one decide the peak memory — so adding a size above the others raises what the run needs on the card, and adding ones below mainly makes an epoch longer. Two or three an octave apart (512, 768, 1024) is the usual shape; at most five.":
    "이미지를 학습할 크기들이며, 각각 픽셀 예산을 나타내는 하나의 숫자로 지정합니다. 1024는 '약 1메가픽셀'을 뜻하고, 각 화면비 버킷이 그것을 서로 다르게 씁니다 — 1024×1024, 1216×832, 832×1216 등입니다.\n\n베이스 모델이 학습된 크기에 맞추세요(SDXL, Chroma, FLUX.2는 1024, SD 1.5는 512). 그보다 훨씬 크게 학습하면 얻는 것은 적고 비용은 크며, 낮추면 세밀한 묘사를 대가로 속도와 메모리에서 실질적인 이득이 있습니다. 비용은 면적에 비례하므로 768은 1024에 비해 한 스텝당 거의 절반의 작업량입니다. 목록에서 기본값으로 표시된 크기는 모델 자체의 크기이며, 여기에 맞춘 실행은 가리키는 모델을 따라갑니다.\n\n여러 개를 고르면 같은 사진을 각 크기에서 학습합니다. 1024에서만 피사체를 본 모델은 그것이 놓였던 캔버스까지 함께 익힙니다. 더 작은 것을 요청하면 같은 구도를 잘라낸 그림이나 두 번 겹친 그림으로 답하기 쉽습니다. 여러 크기는 모델이 피사체에 대해 배우는 것과 그림의 모양에 대해 배우는 것을 분리합니다.\n\n각 크기는 완전한 버킷 묶음이고, 모든 이미지는 자신이 충분히 큰 크기에 들어갑니다 — 이것이 이 설정의 나머지 절반입니다. '확대하지 않기'가 켜져 있으면 700픽셀 스캔은 1024 실행에서 그냥 빠집니다. 512를 더하면 버려지는 대신 거기서 학습하고, 큰 사진들은 두 크기 모두에서 계속 학습합니다.\n\n공짜는 아닙니다. 크기 하나는 에폭마다 데이터셋을 한 번 더 도는 것이고 사진마다 캐시된 latent가 하나 더 생기며, 최대 메모리는 가장 큰 크기의 배치가 정합니다. 그래서 다른 것들보다 큰 크기를 더하면 카드에 필요한 용량이 늘고, 더 작은 크기를 더하면 주로 에폭이 길어집니다. 한 옥타브 간격으로 두세 개(512, 768, 1024)가 보통이며 최대 다섯 개입니다.",
  "An image smaller than its bucket has to be enlarged to train at that size, and enlarging invents detail that was never in the picture: soft edges, smeared texture, the interpolation's own look. Trained on, that is what the model learns the subject looks like.\n\nThis is on by default. Those images are left out while the dataset is built — before anything is encoded, so they cost no time and no cache — and the run says how many it dropped. It is asked per resolution, so a picture too small for the largest size still trains at a smaller one rather than being dropped from the run; turn it off for a small dataset, where a slightly soft picture is usually worth more than no picture.":
    "버킷보다 작은 이미지는 그 크기에서 학습하려면 확대해야 하고, 확대는 원본에 없던 디테일을 만들어냅니다. 흐릿한 가장자리, 뭉개진 질감, 보간 자체의 생김새입니다. 그것으로 학습하면 모델은 피사체가 그렇게 생겼다고 배웁니다.\n\n기본으로 켜져 있습니다. 해당 이미지는 데이터셋을 만드는 동안 제외되며 — 무엇도 인코딩되기 전이라 시간도 캐시도 들지 않습니다 — 실행이 몇 장을 제외했는지 알려줍니다. 해상도마다 따로 묻기 때문에, 가장 큰 크기에는 너무 작은 사진도 실행에서 빠지는 대신 더 작은 크기에서 학습합니다. 작은 데이터셋에서는 끄세요. 거기서는 조금 흐린 사진이 아예 없는 것보다 대개 낫습니다.",
  "New training job": "새 학습 작업",
  "Drafts": "초안",
  "Paused": "일시 정지됨",
  "Completed": "완료됨",
  "Failed": "실패함",
  "Full finetune": "전체 파인튜닝",
  "Loss appears here once training starts.": "학습이 시작되면 손실이 여기에 나타납니다.",
  "Test samples": "테스트 샘플",
  "Select a job to see its progress, samples and settings.": "작업을 선택하면 진행 상황, 샘플, 설정을 볼 수 있습니다.",
  "No training jobs yet. Create one to fine-tune a model (LoRA or full) on images selected straight from your library.": "아직 학습 작업이 없습니다. 라이브러리에서 바로 선택한 이미지로 모델을 파인튜닝(LoRA 또는 전체)하려면 하나 만드세요.",
  "Training environment not set up": "학습 환경이 설정되지 않음",
  "Edit training job": "학습 작업 편집",
  "Save draft": "초안 저장",
  "Save & queue": "저장하고 대기열에 추가",
  "Method": "방식",
  "Hyperparameters": "하이퍼파라미터",
  "Memory & speed": "메모리 및 속도",
  "Canceled before any image was generated": "이미지가 생성되기 전에 취소됨",
  "{done} of {total} images": "{total}장 중 {done}장",
  "not generated yet": "아직 생성되지 않음",
  "Download this LoRA": "이 LoRA 다운로드",
  "NVIDIA only": "NVIDIA 전용",
  "Off (fused kernels)": "꺼짐 (융합 커널)",
  "On (save VRAM)": "켜짐 (VRAM 절약)",
  "needs an NVIDIA GPU": "NVIDIA GPU 필요",
  "needs an NVIDIA GPU (Ada or newer)": "NVIDIA GPU 필요 (Ada 이상)",
  "this model has none": "이 모델에는 없음",
  "8-bit float (fp8)": "8비트 부동소수점 (fp8)",
  "8-bit (int8)": "8비트 (int8)",
  "FLUX.2 Klein (base, 4B)": "FLUX.2 Klein (베이스, 4B)",
  "Images are being generated": "이미지 생성 중",
  "= 1 image": "= 1장",
  "= {n} images": { other: "= {n}장" },
  "Length & learning rate": "길이 및 학습률",
  "Dataset": "데이터셋",
  "Add query": "쿼리 추가",
  "Remove query": "쿼리 제거",
  "invalid query": "잘못된 쿼리",
  "Empty query = every image in the library.": "빈 쿼리 = 라이브러리의 모든 이미지.",
  "Total steps": "총 스텝",
  "Learning rate": "학습률",
  "Batch size": "배치 크기",
  "Gradient accumulation": "그레이디언트 누적",
  "Rank": "랭크",
  "Train text encoder": "텍스트 인코더 학습",
  "Checkpoints": "체크포인트",
  "Checkpoint every": "체크포인트 주기",
  "Cache latents": "잠재값 캐시",
  "Random crop": "무작위 자르기",
  "Resolutions":
    "해상도",
  "Crops & flips":
    "자르기 및 뒤집기",
  "Max aspect ratio": "최대 종횡비",
  "Horizontal flip probability": "좌우 반전 확률",
  "Trigger word": "트리거 단어",
  "Only captions tagged": "다음 태그의 캡션만",
  "Skip captions tagged": "다음 태그의 캡션 제외",
  "Only instructions tagged": "다음 태그의 지시문만",
  "Skip instructions tagged": "다음 태그의 지시문 제외",
  "Comma-separated meta tags whose instructions are never used. Applied after the include list, so it also removes instructions the list let in.": "지시문이 절대 사용되지 않을 쉼표 구분 메타 태그. 포함 목록 뒤에 적용되므로 목록이 들여보낸 지시문도 제거합니다.",
  "Comma-separated meta tags whose captions are never used. Applied after the include list, so it also removes captions the list let in.": "캡션이 절대 사용되지 않을 쉼표 구분 메타 태그. 포함 목록 뒤에 적용되므로 목록이 들여보낸 캡션도 제거합니다.",
  "Always include": "항상 포함",
  "Skip tag groups tagged": "다음 태그의 태그 그룹 제외",
  "Comma-separated meta tags naming whole tag groups to ignore: a tag placed only in such a group never reaches a prompt. The tags stay on your items.": "무시할 태그 그룹 전체를 지명하는 쉼표 구분 메타 태그: 그런 그룹에만 놓인 태그는 프롬프트에 절대 닿지 않습니다. 태그는 항목에 남습니다.",
  "Min tags per prompt": "프롬프트당 최소 태그",
  "Max tags per prompt": "프롬프트당 최대 태그",
  "Pick probability": "추첨 확률",
  "Uniform": "균등",
  "Balance rare tags": "희귀 태그 균형",
  "Frequency measured in": "빈도 측정 기준",
  "Training data": "학습 데이터",
  "Previous step": "이전 스텝",
  "Next step": "다음 스텝",
  "(empty prompt)": "(빈 프롬프트)",
  "Show each step's min/max micro-batch loss": "각 스텝의 최소/최대 마이크로 배치 손실 표시",
  "Expand graph": "그래프 펼치기",
  "Collapse graph": "그래프 접기",
  "steps/s": "스텝/초",
  "Smooth the line (EMA)": "선 부드럽게 (EMA)",
  "Whole library": "라이브러리 전체",
  "Weight loss by tag rarity": "태그 희귀도로 손실 가중",
  "Shuffle tag order": "태그 순서 섞기",
  "Caption dropout": "캡션 드롭아웃",
  "Generate every": "생성 주기",
  "Negative prompt": "부정 프롬프트",
  "Nothing (trigger word only)": "없음 (트리거 단어만)",
  "Every prompt is the trigger word and nothing else, so every selected picture is in the run whatever it carries. Tag and caption selection do not apply.": "모든 프롬프트가 트리거 단어뿐이므로, 선택된 사진은 무엇을 담고 있든 모두 학습에 포함됩니다. 태그와 캡션 선택은 적용되지 않습니다.",
  "Every prompt would be EMPTY — with no text at all, there is nothing for the model to bind what it sees to. Set a trigger word below.": "모든 프롬프트가 비게 됩니다 — 텍스트가 전혀 없으면 모델이 본 것을 연결할 대상이 없습니다. 아래에서 트리거 단어를 설정하세요.",
  "Caption + tags": "캡션 + 태그",
  "Pause (saves a checkpoint)": "일시 정지 (체크포인트 저장)",
  "{d} trained": "{d} 학습됨",
  "Training started": "학습 시작됨",
  "Training resumed": "학습 재개됨",
  "Training paused": "학습 일시 정지됨",
  "Training completed": "학습 완료됨",
  "Training failed": "학습 실패함",
  "Training canceled": "학습 취소됨",
  "Baseline before training": "학습 전 기준선",
  "Checkpoint": "체크포인트",
  "Download checkpoint": "체크포인트 다운로드",
  "Delete checkpoint": "체크포인트 삭제",
  "Delete this checkpoint from disk?": "이 체크포인트를 디스크에서 삭제할까요?",
  "Extend steps": "스텝 연장",
  "Edit steps": "스텝 편집",
  "Base model": "베이스 모델",
  "LoRAs": "LoRA",
  "Edit this model": "이 모델 편집",
  "Edit model": "모델 편집",
  "Edit LoRA": "LoRA 편집",
  "Edit this LoRA": "이 LoRA 편집",
  "Unlock": "잠금 해제",
  "Lock": "잠금",
  "Unlock — deleting the job will take this LoRA with it": "잠금 해제 — 작업을 삭제하면 이 LoRA도 함께 사라집니다",
  "Lock — keeps this LoRA when the job is deleted": "잠금 — 작업을 삭제해도 이 LoRA를 남깁니다",
  "Lock — protects this checkpoint from deletion, from the keep-last rule, and from the job being deleted": "잠금 — 이 체크포인트를 삭제, 최근 N개 유지 규칙, 작업 삭제로부터 보호합니다",
  "Add LoRA": "LoRA 추가",
  "Click to use this value for the next generation": "클릭하여 이 값을 다음 생성에 사용",
  "Output": "출력",
  "Size presets": "크기 프리셋",
  "Random seed": "무작위 시드",
  "A new seed is drawn each time you click Generate; the field below shows the seed used for the last generation.": "생성을 클릭할 때마다 새 시드가 추첨됩니다. 아래 필드는 마지막 생성에 쓰인 시드를 보여 줍니다.",
  "Remove this generation and its images?": "이 생성과 그 이미지를 제거할까요?",
  "Open the image in a new tab": "이미지를 새 탭에서 열기",
  "Remove the selected images? They cannot be recovered.": "선택한 이미지를 삭제할까요? 복구할 수 없습니다.",
  "Remove the selected images (a generation that is still running stays)": "선택한 이미지 삭제 (아직 실행 중인 생성은 남습니다)",
  "Stop the selected generations (the images they have made are kept)": "선택한 생성 중지 (이미 만든 이미지는 남습니다)",
  "Put every setting that made this picture into the form": "이 이미지를 만든 모든 설정을 양식에 넣기",
  "Use all settings": "모든 설정 사용",
  "Preview the selected image (Space)": "선택한 이미지 미리 보기 (스페이스)",
  "Image {i} of {n}": "이미지 {i} / {n}",
  "Up next": "다음 차례",
  "Add to the queue": "대기열에 추가",
  "A training job is running": "학습 작업이 실행 중입니다",
  "Drag to change the queue order": "드래그로 대기열 순서 변경",
  "How the drafts below are ordered":
    "아래 초안의 정렬 방식",
  "Newest first":
    "최신순",
  "Manual order":
    "수동 정렬",
  "Drag to reorder — or into Up next to queue the job":
    "드래그하여 순서 변경 — 또는 다음 실행으로 끌어 큐에 추가",
  "Remove every finished job, with its checkpoints and samples":
    "완료된 작업을 체크포인트와 샘플까지 모두 삭제",
  "Drag into Up next to queue the job": "다음 차례로 드래그하여 작업을 대기열에 추가",
  "Drop here to put the job on hold.": "여기에 놓으면 작업이 보류됩니다.",
  "Prepare": "준비",
  "Keep the last": "최근 유지",
  "When a new snapshot is written the oldest of these is deleted, so the window never grows. A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk. The resumable checkpoint is kept outside this limit and never counts against it.": "새 스냅숏이 기록되면 이 중 가장 오래된 것이 삭제되어 윈도가 커지지 않습니다. LoRA 스냅숏은 작아서(수십 MB) 열두어 개도 무리 없이 유지할 수 있습니다. 전체 파인튜닝 스냅숏은 모델 전체 크기이므로 두세 개도 이미 많은 디스크입니다. 재개 가능한 체크포인트는 이 한도 밖에 유지되며 절대 포함되지 않습니다.",
  "Also keep one in": "추가로 하나씩 유지:",
  "A rolling window at the end of the run. 0 keeps none by recency.": "실행 끝의 순환 윈도. 0이면 최신순으로는 아무것도 유지하지 않습니다.",
  "Kept for good, on top of the window above.": "위의 윈도에 더해 영구히 유지됩니다.",
  "A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk.": "LoRA 스냅숏은 작아서(수십 MB) 열두어 개도 무리 없이 유지할 수 있습니다. 전체 파인튜닝 스냅숏은 모델 전체 크기이므로 두세 개도 이미 많은 디스크입니다.",
  "in 1 step": "1 스텝 후",
  "in {n} steps": { other: "{n} 스텝 후" },
  "Keep as checkpoint": "체크포인트로 유지",
  "Backward": "역전파",
  "warmup": "웜업",
  "Settings changed": "설정 변경됨",
  "Dataset changed": "데이터셋 변경됨",
  "{n} items added":
    { other: "{n}개 항목 추가됨" },
  "{n} items removed":
    { other: "{n}개 항목 제거됨" },
  "Measured over the last steps of this run": "이 실행의 최근 스텝에서 측정됨",
  "about {d} left": "약 {d} 남음",
  "The images this run trains on, sorted into aspect-ratio buckets": "이 실행이 학습하는 이미지, 종횡비 버킷으로 분류됨",
  "{n} images": { other: "{n}장" },
  "{n} from video": { other: "영상에서 {n}장" },
  "{n} buckets": { other: "{n}개 버킷" },
  "Training job settings": "학습 작업 설정",
  "Save as new job": "새 작업으로 저장",
  "Hide system statistics": "시스템 통계 숨기기",
  "Show system statistics": "시스템 통계 표시",
  "loading model": "모델 로드 중",
  "caching latents": "잠재값 캐시 중",
  "Degradation": "열화",
  "Add variant": "변형 추가",
  "Remove every variant from this job": "이 작업의 모든 변형 제거",
  "Remove this variant": "이 변형 제거",
  "JPEG re-encode": "JPEG 재인코딩",
  "Video codec (h264 / h265)": "비디오 코덱 (h264 / h265)",
  "Resolution loss": "해상도 손실",
  "JPEG": "JPEG",
  "video codec": "비디오 코덱",
  "resolution loss": "해상도 손실",
  "Chroma subsampling": "크로마 서브샘플링",
  "How much color detail is thrown away. 4:2:0 is what almost every real JPEG uses.": "얼마나 많은 색 디테일이 버려지는지입니다. 4:2:0은 거의 모든 실제 JPEG가 쓰는 것입니다.",
  "Codec": "코덱",
  "CRF": "CRF",
  "The codec's quality number, counting the other way round: HIGHER is worse. Above about 32 a frame visibly falls apart.": "코덱의 품질 숫자로, 반대로 셉니다: 높을수록 나쁩니다. 약 32를 넘으면 프레임이 눈에 띄게 무너집니다.",
  "Scale": "스케일",
  "Nearest gives the hard, blocky look of a badly upscaled screenshot; bilinear the soft one.": "최근접은 잘못 업스케일된 스크린숏의 딱딱하고 각진 모습을, 이중 선형은 부드러운 모습을 줍니다.",
  "Bilinear": "이중 선형",
  "Bicubic": "이중 삼차",
  "Lanczos": "Lanczos",
  "Passes": "패스",
  "Visits per clean visit": "깨끗한 방문당 방문 수",
  "How often this variant is drawn beside the picture it was made from. 0.25 = one degraded visit per four clean ones.": "이 변형이 원본 그림 옆에서 얼마나 자주 추첨되는지입니다. 0.25 = 깨끗한 방문 넷당 열화 방문 하나.",
  "Cached variations per picture": "그림당 캐시 변형 수",
  "How many separately-drawn values each picture gets. 1 already spreads the range across the dataset; more spreads it within one picture, and multiplies the cache.": "각 그림이 별도로 추첨된 값을 몇 개 받는지입니다. 1로도 범위가 데이터셋 전체에 퍼집니다. 더 많으면 한 그림 안에서 퍼지고 캐시가 배가됩니다.",
  "jpeg_artifacts, low_quality": "jpeg_artifacts, low_quality",
  "Always in this sample's prompt: never dropped by the random tag pick, the tag cap, or caption dropout.": "항상 이 샘플의 프롬프트에 있습니다: 무작위 태그 추첨, 태그 상한, 캡션 드롭아웃에 절대 빠지지 않습니다.",
  "Remove tags if present": "있으면 태그 제거",
  "masterpiece, absurdres": "masterpiece, absurdres",
  "Which pictures": "어느 그림",
  "Only pictures tagged": "다음 태그의 그림만",
  "Never pictures tagged": "다음 태그의 그림 제외",
  "Wins over the line above. Use it to leave pictures alone that are already marked as poor.": "위 줄보다 우선합니다. 이미 저품질로 표시된 그림을 건드리지 않을 때 쓰세요.",
  "The preview failed": "미리보기 실패",
  "Select an item in the library to preview this on.": "이것을 미리 볼 항목을 라이브러리에서 선택하세요.",
  "gentlest": "가장 약함",
  "harshest": "가장 강함",
  "Variants": "변형",
  "Save the current variants, or load a saved set": "현재 변형을 저장하거나 저장된 세트를 로드",
  "Save current variants": "현재 변형 저장",
  "Add a variant first": "먼저 변형을 추가하세요",
  "Load this set, replacing the variants in this job": "이 세트를 로드하여 이 작업의 변형을 교체",
  "Of every 100 visits to a picture this applies to, {clean} are clean and the rest are degraded: {parts}.": "이것이 적용되는 그림에 대한 방문 100회 중 {clean}회는 깨끗하고 나머지는 열화됩니다: {parts}.",
  "A variant with a tag filter applies to fewer pictures than the queries select, so its share is of those.": "태그 필터가 있는 변형은 쿼리가 선택한 것보다 적은 그림에 적용되므로, 그 몫은 그것들에 대한 것입니다.",
  "About {n} degraded files will be cached.": "약 {n}개의 열화 파일이 캐시됩니다.",
  "Preset": "프리셋",
  "Presets": "프리셋",
  "Preset name": "프리셋 이름",
  "Save these settings as a preset, or load one": "이 설정을 프리셋으로 저장하거나 하나를 로드",
  "Save current settings": "현재 설정 저장",
  "Start new jobs from this preset": "이 프리셋에서 새 작업 시작",
  "Delete this preset": "이 프리셋 삭제",
  "Cosine": "코사인",
  "Base models": "베이스 모델",
  "1 result": "결과 1개",
  "{n} results": { other: "결과 {n}개" },
  "Delete every result in this session": "이 세션의 모든 결과 삭제",
  "Delete all {n} results from this session? The generated images go with them.": "이 세션의 결과 {n}개를 모두 삭제할까요? 생성된 이미지도 함께 삭제됩니다.",
  "sampling": "샘플링 중",
  "What does this do?": "이것은 무엇을 하나요?",
  "This model's repository is gated: accept its license on the model page and set a Hugging Face access token, or the download will fail.": "이 모델의 저장소는 제한되어 있습니다: 모델 페이지에서 라이선스를 수락하고 Hugging Face 액세스 토큰을 설정하세요. 아니면 다운로드가 실패합니다.",
  "Click to use this prompt for the next generation": "클릭하여 이 프롬프트를 다음 생성에 사용",
  "(no prompt)": "(프롬프트 없음)",
  "Click to use this negative prompt for the next generation": "클릭하여 이 부정 프롬프트를 다음 생성에 사용",
  "Time so far, including loading the model": "모델 로드를 포함한 현재까지의 시간",
  "Total time, including loading the model": "모델 로드를 포함한 총 시간",
  "Remove from the queue": "대기열에서 제거",
  "Select to copy": "선택하여 복사",
  "generation failed": "생성 실패",
  "Sampler steps": "샘플러 스텝",
  "CFG scale": "CFG 스케일",
  "This model isn't downloaded yet, and downloads are switched off": "이 모델은 아직 다운로드되지 않았고, 다운로드가 꺼져 있습니다",
  "Loss": "손실",
  "LoRA only": "LoRA 전용",
  "Native training resolution of these weights. Leave empty for the architecture's own.": "이 가중치의 네이티브 학습 해상도. 비우면 아키텍처 고유값을 씁니다.",
  "Includes 1 model you added.": "추가한 모델 1개 포함.",
  "Includes": "포함:",
  "models you added.": "개의 추가한 모델.",
  "Open this model's page on Hugging Face": "Hugging Face에서 이 모델의 페이지 열기",
  "Remove this model": "이 모델 제거",
  "Based on": "기반",
  "/path/to/model (diffusers folder or .safetensors)": "/path/to/model (diffusers folder or .safetensors)",
  "owner/repo": "owner/repo",
  "Add model": "모델 추가",
  "On disk": "디스크에 있음",
  "Path missing": "경로 없음",
  "Continue this download where it stopped": "이 다운로드를 멈춘 곳에서 계속",
  "Partly downloaded": "일부 다운로드됨",
  "Discard partial download": "부분 다운로드 버리기",
  "This path no longer exists": "이 경로는 더 이상 존재하지 않습니다",
  "Remove from the list (the file is left alone)": "목록에서 제거 (파일은 건드리지 않음)",
  "The base model this LoRA was trained for": "이 LoRA가 학습된 베이스 모델",
  "/path/to/lora.safetensors": "/path/to/lora.safetensors",
  "Download this checkpoint": "이 체크포인트 다운로드",
  "Delete this checkpoint from disk": "이 체크포인트를 디스크에서 삭제",
  "Relative sampling probability: a weight-2 query's images are drawn twice as often as a weight-1 query's.": "상대적 샘플링 확률: 가중치 2인 쿼리의 이미지는 가중치 1인 쿼리보다 두 배 자주 추첨됩니다.",
  "Steps": "스텝",
  "Text encoder": "텍스트 인코더",
  "trained": "학습됨",
  "Prompts": "프롬프트",
  "Samples": "샘플",
  "Training log": "학습 로그",
  "No output yet.": "아직 출력이 없습니다.",
  "about {v} of GPU memory": "GPU 메모리 약 {v}",
  "more than this machine's {m}": "이 머신의 {m}보다 많음",
  "e.g. watercolor style LoRA": "예: 수채화 스타일 LoRA",
  "Model-specific": "모델별",
  "Optimization": "최적화",
  "LR schedule": "LR 스케줄",
  "Constant": "상수",
  "Linear decay": "선형 감쇠",
  "Constant + warmup": "상수 + 웜업",
  "Warmup steps": "웜업 스텝",
  "Ramp the learning rate up over the first N steps. Leave empty for no warmup.": "처음 N 스텝 동안 학습률을 램프로 올립니다. 웜업이 없으면 비워 두세요.",
  "bf16 is the safe modern default. fp32 doubles memory (automatic fallback on Macs without bf16); avoid fp16 for training.": "bf16이 안전한 현대 기본값입니다. fp32는 메모리를 두 배로 씁니다 (bf16 없는 Mac에서 자동 대체). 학습에는 fp16을 피하세요.",
  "Makes sampling, crops and tag picks reproducible.": "샘플링, 자르기, 태그 추첨을 재현 가능하게 만듭니다.",
  "LoRA": "LoRA",
  "Scales the adapter's effect; the common convention is alpha = rank. Lower alpha = weaker influence at the same rank.": "어댑터의 효과를 스케일합니다. 통상의 관례는 alpha = 랭크. 같은 랭크에서 alpha가 낮으면 영향이 약해집니다.",
  "Helps the model learn a NEW trigger word, at higher overfitting risk. Guarded: it uses a lower learning rate and stops partway through training.": "모델이 새 트리거 단어를 배우게 돕지만 과적합 위험이 높아집니다. 방어됨: 더 낮은 학습률을 쓰고 학습 도중에 멈춥니다.",
  "Text encoder LR": "텍스트 인코더 LR",
  "Left empty: half the main learning rate.": "비우면: 주 학습률의 절반.",
  "Stop TE after": "TE 중지 시점",
  "Include the large encoder": "큰 인코더 포함",
  "T5-XXL, the encoder that reads the whole prompt — most of the memory and most of the effect. Unticked, only the small CLIP-L trains: cheap, and what most FLUX LoRA tools mean by training the text encoder.": "프롬프트 전체를 읽는 T5-XXL로, 메모리와 효과의 대부분을 차지합니다. 끄면 작은 CLIP-L만 학습합니다. 비용이 적고, 대부분의 FLUX LoRA 도구가 말하는 텍스트 인코더 학습이 바로 이것입니다.",
  "of total steps": "(총 스텝 대비)",
  "Keep step snapshots": "스텝 스냅숏 유지",
  "Save a permanent snapshot every N steps, so the best-looking step can be picked afterwards. Off: only the resumable 'last' checkpoint is kept.": "N 스텝마다 영구 스냅숏을 저장하여 나중에 가장 좋아 보이는 스텝을 고를 수 있게 합니다. 꺼짐: 재개 가능한 'last' 체크포인트만 유지됩니다.",
  "Gradient checkpointing": "그레이디언트 체크포인팅",
  "Trades ~25% speed for a large VRAM saving. Recommended for full finetunes and big models.": "~25%의 속도를 큰 VRAM 절약과 맞바꿉니다. 전체 파인튜닝과 대형 모델에 권장.",
  "Attention slicing": "어텐션 슬라이싱",
  "Half-precision master weights": "절반 정밀도 마스터 가중치",
  "Keeps the trained weights and their gradients at 16 bits instead of 32. What the rounding drops is carried to the next update, so the run learns what it would have learned; the cost is one more buffer of the same width.":
    "학습되는 가중치와 그 기울기를 32비트 대신 16비트로 유지합니다. 반올림에서 떨어져 나간 값은 다음 업데이트로 이월되므로 학습은 원래 도달했을 결과에 이릅니다. 대가는 같은 폭의 버퍼가 하나 더 필요하다는 점입니다.",
  "only for a full finetune": "전체 파인튜닝 전용",
  "nothing to halve at full precision": "전체 정밀도에서는 절반으로 줄일 것이 없습니다",
  "Prodigy cannot be stepped one weight at a time": "Prodigy는 가중치별로 실행할 수 없습니다",
  "Base model quantization": "베이스 모델 양자화",
  "None (full precision)": "없음 (전체 정밀도)",
  "4-bit (NF4)": "4비트 (NF4)",
  "Optimizer": "옵티마이저",
  "Images are sorted into width/height buckets of equal area so nothing gets squashed. This caps how extreme the buckets get (2 = up to 2:1 and 1:2).": "이미지는 면적이 같은 가로/세로 버킷으로 분류되어 아무것도 뭉개지지 않습니다. 이것은 버킷이 얼마나 극단적일 수 있는지를 제한합니다 (2 = 최대 2:1과 1:2).",
  "Never flip images whose tags are marked": "태그에 다음 메타 태그가 있는 이미지는 뒤집지 않음",
  "Comma-separated META tags. Any tag the library marks with one of these switches mirroring off for the pictures carrying that tag — so the rule is stated once in the Tags tab rather than listed here.": "쉼표로 구분한 메타 태그. 라이브러리가 이렇게 표시한 태그는 그 태그를 가진 사진의 미러링을 끕니다. 규칙을 여기에 나열하는 대신 태그 탭에서 한 번만 밝히는 것입니다.",
  "Always include tags marked": "다음 메타 태그가 있는 태그는 항상 포함",
  "Comma-separated META tags. Any tag the library marks with one of these is never dropped by the random pick — again, only where the image actually has that tag.": "쉼표로 구분한 메타 태그. 라이브러리가 이렇게 표시한 태그는 무작위 선택에서 절대 빠지지 않습니다. 역시 이미지가 실제로 그 태그를 가진 경우에만 해당합니다.",
  "Exclude tags marked": "다음 메타 태그가 있는 태그 제외",
  "Comma-separated META tags. Any tag the library marks with one of these is stripped from prompts.": "쉼표로 구분한 메타 태그. 라이브러리가 이렇게 표시한 태그는 프롬프트에서 제거됩니다.",
  "Remove tags marked": "다음 메타 태그가 있는 태그 제거",
  "Comma-separated META tags. Any tag the library marks with one of these comes off this sample.": "쉼표로 구분한 메타 태그. 라이브러리가 이렇게 표시한 태그는 이 샘플에서 빠집니다.",
  "Only pictures whose tags are marked": "태그에 다음 메타 태그가 있는 사진만",
  "Comma-separated META tags — the same rule as the line above, said once in the library rather than tag by tag here.": "쉼표로 구분한 메타 태그 — 위 줄과 같은 규칙을, 여기서 태그마다 나열하는 대신 라이브러리에서 한 번 밝힌 것입니다.",
  "Never pictures whose tags are marked": "태그에 다음 메타 태그가 있는 사진은 제외",
  "Comma-separated META tags. Wins over both lines above.": "쉼표로 구분한 메타 태그. 위의 두 줄보다 우선합니다.",
  "The same veto, said once in the library instead of tag by tag here. Any tag the Tags tab marks with one of these meta tags switches mirroring off for every picture carrying that tag.\n\nIt is worth the indirection for the reason a list of names goes stale: “text”, “logo”, “signature”, “left-handed”, a dozen characters with an eyepatch — the list in a job's settings is right the day it is written and wrong the next time somebody adds a tag it should have held. Marking the tags themselves puts the fact where the tag is, so a tag added later carries it into every run automatically, and a job written before that tag existed still does the right thing.\n\nBoth lists apply: a picture is left unmirrored if it carries a tag named above OR a tag marked here.":
    "같은 거부를 여기서 태그마다 나열하는 대신 라이브러리에서 한 번만 밝힌 것입니다. 태그 탭이 이 메타 태그 중 하나로 표시한 태그는, 그 태그를 가진 모든 사진의 미러링을 끕니다.\n\n이 우회가 값어치를 하는 이유는 이름 목록이 낡는 이유와 같습니다. “text”, “logo”, “signature”, “left-handed”, 안대를 한 열댓 명의 캐릭터 — 작업 설정 속 목록은 쓰는 날에는 맞고, 거기에 들어갔어야 할 태그를 누군가 추가하는 순간부터 틀립니다. 태그 자체에 표시하면 그 사실이 태그가 있는 자리에 놓입니다. 나중에 추가된 태그가 스스로 모든 실행에 그것을 가져가고, 그 태그가 생기기 전에 쓰인 작업도 여전히 옳게 동작합니다.\n\n두 목록이 모두 적용됩니다. 사진은 위에서 이름을 든 태그 또는 여기서 표시된 태그를 가지면 뒤집히지 않습니다.",
  "The rule above, named by what the library says ABOUT a tag rather than by the tag. Any tag marked with one of these meta tags bypasses the random pick — again only where the image actually has it.\n\nA meta tag put on “watermark”, “signature” and “logo” once means every run treats them that way, including runs written before the third of them existed. The two lists are unioned, so naming a tag here and above is simply the same instruction twice.":
    "위의 규칙을, 태그 자체가 아니라 라이브러리가 그 태그에 대해 말하는 바로 지정한 것입니다. 이 메타 태그 중 하나가 붙은 태그는 무작위 선택을 건너뜁니다 — 역시 이미지가 실제로 그 태그를 가진 경우에만 해당합니다.\n\n“watermark”, “signature”, “logo”에 메타 태그를 한 번 붙이면 모든 실행이 그것들을 그렇게 다룹니다. 셋째 것이 생기기 전에 쓰인 실행도 포함됩니다. 두 목록은 합쳐지므로, 어떤 태그를 여기와 위에 모두 적는 것은 같은 지시를 두 번 하는 것일 뿐입니다.",
  "The same, one level up: any tag the library marks with one of these meta tags is stripped from every prompt.\n\nThis is the one to reach for when the exclusions are a KIND of tag rather than a list of them. Quality ratings, scan notes, the booru's own housekeeping words — mark them “noprompt” in the Tags tab and every run drops them, instead of every job carrying a list that has to grow with the vocabulary.\n\nIt is not the same as a skipped tag GROUP below. This one is about the tag wherever it appears; that one is about a grouping on one item, and a tag placed in an excluded group and also somewhere else survives it.":
    "같은 것을 한 단계 위에서. 라이브러리가 이 메타 태그 중 하나로 표시한 태그는 모든 프롬프트에서 제거됩니다.\n\n제외 대상이 태그의 목록이 아니라 태그의 “종류”일 때 손을 뻗을 것이 이것입니다. 품질 등급, 스캔 메모, booru 자체의 관리용 단어 — 태그 탭에서 “noprompt”로 표시해 두면 모든 실행이 그것들을 버립니다. 어휘와 함께 늘려 가야 하는 목록을 작업마다 지니는 대신에 말이죠.\n\n이는 아래의 건너뛴 태그 그룹과 같지 않습니다. 이쪽은 그 태그가 어디에 나타나든 그 태그에 대한 이야기이고, 저쪽은 한 항목의 묶음에 대한 이야기이며, 제외된 그룹과 다른 곳에 함께 놓인 태그는 그것을 살아남습니다.",
  "The list above, named by what the library says about a tag. Any tag marked with one of these meta tags comes off this sample.\n\nWhat it is for is that the claims a degraded copy no longer supports are a CATEGORY, not a list: 'masterpiece', 'absurdres', 'high quality', 'official art' and whatever the next dump adds are all \"a claim about the picture's quality\". Marking them once means every variant of every job drops them, and the same mark can then say something different per method — a 'resolution_claim' mark belongs on a resize variant's list, a 'fidelity_claim' on a JPEG one.":
    "위의 목록을, 라이브러리가 그 태그에 대해 말하는 바로 지정한 것입니다. 이 메타 태그 중 하나가 붙은 태그는 이 샘플에서 빠집니다.\n\n무엇을 위한 것이냐면, 열화된 사본이 더는 뒷받침하지 못하는 주장은 목록이 아니라 “범주”이기 때문입니다. “masterpiece”, “absurdres”, “high quality”, “official art”, 그리고 다음 덤프가 더할 무엇이든 모두 “그림의 품질에 대한 주장”입니다. 한 번 표시해 두면 모든 작업의 모든 변형이 그것들을 버리고, 같은 표시가 방법마다 다른 말을 할 수도 있습니다 — “resolution_claim” 표시는 크기 조정 변형의 목록에, “fidelity_claim”은 JPEG 변형의 목록에 속합니다.",
  "The line above by mark rather than by name: a picture is degraded only if it carries a tag the library marks this way.\n\nChecked against the picture's effective tags, so a tag it only carries by implication counts too. With both lists empty, every picture is fair game.":
    "위 줄을 이름이 아니라 표시로. 사진은 라이브러리가 이렇게 표시한 태그를 가질 때에만 열화됩니다.\n\n사진의 실효 태그에 대해 검사하므로, 함의로만 지닌 태그도 셈에 듭니다. 두 목록을 모두 비워 두면 모든 사진이 대상입니다.",
  "The veto by mark, and it wins over both lines above exactly as the named list does.\n\nThe pair is what makes a degrading run safe on a mixed library: mark the pictures that are already poor — a 'low_quality' or 'rescan' mark on the tags that say so — and no variant can ever degrade one of them further, however broadly the \"only pictures\" side is drawn.":
    "표시에 의한 거부이며, 이름 목록이 그러하듯 위의 두 줄보다 우선합니다.\n\n섞인 라이브러리에서 열화 실행을 안전하게 만드는 것이 바로 이 쌍입니다. 이미 품질이 낮은 사진들에 표시해 두면 — 그렇다고 말하는 태그에 “low_quality”나 “rescan”을 붙여 두면 — “대상 사진” 쪽을 아무리 넓게 잡아도 어떤 변형도 그것들을 더 열화시킬 수 없습니다.",
  "Never flip images tagged": "다음 태그의 이미지는 반전 금지",
  "Comma-separated tags that switch mirroring off for the images carrying them, e.g. 'text'. Everything else still flips.": "이를 가진 이미지의 반전을 끄는 쉼표 구분 태그. 예: 'text'. 나머지는 여전히 반전됩니다.",
  "Use alpha as a loss mask": "알파를 손실 마스크로 사용",
  "For cut-out images (transparent background): train on the visible pixels and largely ignore the rest. Images without transparency are unaffected.": "오려낸 이미지(투명 배경)용: 보이는 픽셀로 학습하고 나머지는 대부분 무시합니다. 투명도 없는 이미지는 영향받지 않습니다.",
  "Background weight": "배경 가중치",
  "Build prompts from": "프롬프트 구성 요소",
  "What each training prompt is made of: the item's caption text, its tags, caption followed by tags, or nothing but the trigger word.": "각 학습 프롬프트의 구성: 항목의 캡션, 태그, 캡션 다음에 태그, 또는 트리거 단어만.",
  "Prepended to every prompt. Use a rare token (e.g. 'ohwx style') you'll later type to invoke the trained concept.": "모든 프롬프트 앞에 붙습니다. 나중에 학습된 콘셉트를 불러낼 때 입력할 드문 토큰(예: 'ohwx style')을 쓰세요.",
  "Each image trains as the RESULT of one of its instructions, with that instruction's reference images as the input. Items carrying no instruction are left out of the run, and tag selection does not apply.": "각 이미지는 자기 지시문 중 하나의 결과물로서, 그 지시문의 참조 이미지를 입력으로 학습합니다. 지시문 없는 항목은 실행에서 빠지고, 태그 선택은 적용되지 않습니다.",
  "Tag selection": "태그 선택",
  "Tags are re-picked and re-shuffled fresh every time an image is visited.": "이미지가 방문될 때마다 태그가 새로 추첨되고 새로 섞입니다.",
  "Comma-separated tags stripped from prompts (e.g. quality tags or the concept itself when using a trigger word).": "프롬프트에서 제거되는 쉼표 구분 태그 (예: 품질 태그, 또는 트리거 단어를 쓸 때 콘셉트 자체).",
  "no limit": "제한 없음",
  "Lower bound of the random pick. Both limits empty = use all tags.": "무작위 추첨의 하한. 두 한도 모두 비우면 = 모든 태그 사용.",
  "Upper bound of the random pick. Picking a random subset each visit teaches tags independently instead of as a fixed clump.": "무작위 추첨의 상한. 방문마다 무작위 부분집합을 뽑으면 태그가 고정 덩어리가 아니라 독립적으로 학습됩니다.",
  "Whether a tag's rarity is measured within the selected training images or across the whole library.": "태그의 희귀함을 선택된 학습 이미지 안에서 잴지 라이브러리 전체에서 잴지입니다.",
  "Skip partially matching tags": "부분 일치 태그 건너뛰기",
  "Standard practice: prevents the model from binding concepts to a fixed tag position.": "표준 관행: 모델이 콘셉트를 고정 태그 위치에 묶는 것을 방지합니다.",
  "Underscores to spaces": "밑줄을 공백으로",
  "Tag separator": "태그 구분자",
  "Joins the prompt parts; comma + space is the standard.": "프롬프트 부분들을 잇습니다. 쉼표 + 공백이 표준입니다.",
  "Generate preview images with the in-training model to watch progress in the job's timeline.": "학습 중인 모델로 미리보기 이미지를 생성하여 작업 타임라인에서 진행을 지켜봅니다.",
  "Generate test samples": "테스트 샘플 생성",
  "Sample seed": "샘플 시드",
  "Fixed per prompt so consecutive samples differ only by training progress.": "프롬프트별로 고정되어 연속 샘플이 학습 진행에서만 달라집니다.",
  "Test prompts": "테스트 프롬프트",
  "negative prompt (optional)": "부정 프롬프트 (선택)",
  "Use the shared size for this prompt": "이 프롬프트에 공유 크기 사용",
  "Give this prompt its own size": "이 프롬프트에 자체 크기 부여",
  "Remove this prompt": "이 프롬프트 제거",
  "Add prompt": "프롬프트 추가",
  "Remove every prompt from this job": "이 작업의 모든 프롬프트 제거",
  "Remove all": "모두 제거",
  "Save the current prompts, or load a saved set": "현재 프롬프트를 저장하거나 저장된 세트를 로드",
  "Write a prompt first": "먼저 프롬프트를 쓰세요",
  "Save current prompts": "현재 프롬프트 저장",
  "Set name": "세트 이름",
  "Load this set into the job": "이 세트를 작업에 로드",
  "Delete this set": "이 세트 삭제",
  "train from scratch": "처음부터 학습",
  "Finished result": "완료 결과",
  "Intermediate checkpoint": "중간 체크포인트",
  "Continues": "계속함:",
  "Train on video frames": "동영상 프레임으로 학습",
  "Off, a video the queries match is skipped. On, its frames are extracted while the dataset is built, trained on as images, and deleted with the run.": "꺼짐이면 쿼리가 찾은 동영상은 건너뜁니다. 켜짐이면 데이터셋 구축 중 프레임이 추출되어 이미지로 학습되고 실행과 함께 삭제됩니다.",
  "One frame every": "프레임 간격",
  "Interval unit": "간격 단위",
  "Seconds follows the clock whatever the frame rate; frames counts the file's own frames.": "초는 프레임 레이트와 무관하게 시계를 따르고, 프레임은 파일 자체의 프레임을 셉니다.",
  "Drop repeated frames": "반복 프레임 버리기",
  "A shot held for five seconds is one picture, not five. Each kept frame is compared with the ones already kept from the same video.": "5초 동안 정지된 숏은 다섯 장이 아니라 한 장의 그림입니다. 유지되는 각 프레임은 같은 동영상에서 이미 유지된 것들과 비교됩니다.",
  "Label each block with": "각 블록의 라벨:",
  "The subjects it is about": "다루는 인물",
  "The tag group's name": "태그 그룹의 이름",
  "Between groups": "그룹 사이",
  "Group tags by tag group": "태그를 태그 그룹별로 묶기",
  "Lay the picked tags out one block per tag group instead of one flat list, so what belongs to the same thing in the picture stays together.": "뽑힌 태그를 하나의 평평한 목록 대신 태그 그룹당 한 블록으로 배치하여, 그림 속 같은 것에 속하는 것이 함께 있게 합니다.",
  "Put between blocks. A newline by default, which is what makes them read as separate statements.": "블록 사이에 놓입니다. 기본은 줄바꿈이며, 그것이 블록들을 별개의 문장으로 읽히게 합니다.",
  "Includes {n} models you added.": { other: "추가한 모델 {n}개 포함." },
  // The job list's selection bar.
  "Remove {n} training jobs? Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone.":
    "학습 작업 {n}개를 삭제할까요? 체크포인트, 샘플, 학습 결과도 함께 삭제되며 되돌릴 수 없습니다. 잠긴 항목은 LoRA 목록에 남습니다.",
  "Remove the selected jobs — a running job is left alone":
    "선택한 작업 삭제 — 실행 중인 작업은 그대로 둡니다",
  "Remove the selected jobs, with their checkpoints and samples":
    "선택한 작업을 체크포인트와 샘플까지 삭제",
  // The Models page: adding a model, and removing one.
  "Remove “{name}” from the model list?":
    "“{name}”을(를) 모델 목록에서 제거할까요?",
  "Delete the downloaded weights as well? They can be downloaded again later.":
    "내려받은 가중치도 삭제할까요? 나중에 다시 내려받을 수 있습니다.",
  "Which model these weights are a version of — it decides the engine, the hyperparameters and the memory profile":
    "이 가중치가 어떤 모델의 버전인지 — 엔진, 하이퍼파라미터, 메모리 특성이 여기서 정해집니다",
  "owner/repo, or a path on this machine":
    "owner/repo 또는 이 컴퓨터의 경로",
  "A Hugging Face repository, or a diffusers folder or .safetensors file on this machine — which one it is is read off what you type.":
    "Hugging Face 저장소이거나, 이 컴퓨터의 diffusers 폴더 또는 .safetensors 파일입니다. 둘 중 무엇인지는 입력한 내용에서 읽어냅니다.",
  "Read as a path on this machine":
    "이 컴퓨터의 경로로 읽었습니다",
  "Read as a Hugging Face repository":
    "Hugging Face 저장소로 읽었습니다",
  "Left unnamed, the model is listed under its repository or path":
    "이름이 없으면 저장소나 경로 이름으로 표시됩니다",
  // The Models page's LoRA lists, grouped by architecture.
  "No LoRAs yet — add a file above, or finish a training job.":
    "아직 LoRA가 없습니다 — 위에서 파일을 추가하거나 학습을 완료하세요.",
  "These work on any model of this architecture. Each row says which one it was trained for.":
    "이 아키텍처의 어떤 모델에서도 동작합니다. 각 행은 어떤 모델용으로 학습했는지 알려줍니다.",
  // The Evaluate tab: the LoRA rows, and the results grid.
  "Strength":
    "강도",
  "no image":
    "이미지 없음",
  "Weights": "가중치",
  "File": "파일",
  "Trained for": "학습 대상",
  "defaults to the file name": "기본값은 파일 이름",
  "Waiting…": "대기 중…",
  "Another download is running": "다른 다운로드가 실행 중입니다",
  "macOS keeps GPU temperature and power for root only. To see them here, allow this one command without a password, then press Try again:":
    "macOS는 GPU 온도와 전력을 root에게만 제공합니다. 여기에 표시하려면 이 명령 하나만 비밀번호 없이 허용한 뒤 ‘다시 시도’를 누르세요:",
  "Check again — no restart needed once the rule is in":
    "다시 확인 — 규칙을 추가했다면 재시작할 필요가 없습니다",
  "Copied": "복사됨",
  "Press ⌘C to copy it": "⌘C를 누르면 복사됩니다",
  "Write tags as an alias": "태그를 별칭으로 쓰기",
  "Chance of writing a picked tag as one of its aliases instead of its own name, rolled per tag every time an image is visited.":
    "선택된 태그를 원래 이름 대신 별칭 중 하나로 쓸 확률. 이미지를 방문할 때마다 태그마다 새로 뽑습니다.",
  "Your library's aliases are the other words for one thing — “cat”, “kitty”, “feline”. Assigning any of them stores the canonical name, so every prompt says the same word and the model learns to answer to that word alone; at generation time the others do less, or nothing.\n\nWith this above 0, each picked tag is sometimes written as one of its aliases instead. The roll happens per tag per visit, so one image seen twice reads differently and the whole vocabulary is spread across the run rather than one alias being chosen per tag and then repeated.\n\nOnly the PROMPT changes. Tag matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all keep using the canonical name — so this cannot skew any of them. A tag with no aliases is always written as itself, and 0 is exactly what every run did before this setting existed.":
    "라이브러리의 별칭은 같은 것을 가리키는 다른 낱말입니다 — “cat”, “kitty”, “feline”. 어느 것을 붙여도 저장되는 것은 표준 이름이라, 모든 프롬프트가 같은 낱말을 말하고 모델은 그 낱말에만 반응하도록 배웁니다. 생성할 때 나머지는 거의, 또는 전혀 듣지 않습니다.\n\n0보다 크면 선택된 태그가 때때로 별칭으로 쓰입니다. 추첨은 태그마다, 방문마다 이루어지므로 같은 이미지를 두 번 봐도 다르게 읽히고, 태그마다 별칭 하나를 골라 되풀이하는 대신 어휘 전체가 학습 전반에 퍼집니다.\n\n바뀌는 것은 프롬프트뿐입니다. 태그 매칭, 항상/제외 목록, 빈도 균형, 손실 가중치, 크롭이 담아야 할 상자는 모두 표준 이름을 그대로 씁니다. 별칭이 없는 태그는 언제나 그대로 쓰이며, 0은 이 설정이 생기기 전 모든 학습이 하던 그대로입니다.",
  "Whether a tag's rarity is measured within the selected training images, across the whole library, or across the whole library plus what each tag has elsewhere.":
    "태그의 희소성을 선택된 학습 이미지 안에서 잴지, 라이브러리 전체에서 잴지, 아니면 라이브러리 전체에 각 태그가 다른 곳에 가진 수를 더해서 잴지.",
  "Rarity is relative to some population, and this picks which one.\n\n“Training data” counts only the images this job selected, so balancing works within the set you are actually training on — usually what you want. “Whole library” counts every item you own, which makes a tag that is common in your dataset but rare overall still count as rare. That is occasionally useful when the training set is a deliberate slice of a much larger, differently balanced collection.\n\n“Whole library + count offsets” adds each tag’s highest meta-tag count — the pictures it has somewhere this library is not, counted per site on the tag’s meta tags (“tumblr 50”, “twitter 100”), of which the largest single figure is used, never the sum, since the sites count overlapping pictures. Nowhere else in the app is that number added to a count, because a total including it would be a claim about somewhere else; for BALANCING it is often the honest one. A tag with four pictures here and forty thousand where they came from is not a rare word, and treating it as rare spends the run teaching the model something it already knows.":
    "희소성은 언제나 어떤 모집단에 대한 상대값이며, 여기서 그 모집단을 고릅니다.\n\n“학습 데이터”는 이 작업이 선택한 이미지만 셉니다. 따라서 균형 조정은 실제로 학습하는 집합 안에서 이루어지며, 보통은 이것이 원하는 바입니다. “라이브러리 전체”는 가진 모든 것을 세므로, 데이터셋에서는 흔하지만 전체적으로는 드문 태그가 여전히 드문 것으로 취급됩니다. 학습 세트가 훨씬 크고 분포가 다른 컬렉션에서 의도적으로 잘라낸 조각일 때 가끔 쓸모가 있습니다.\n\n“라이브러리 전체 + 외부 보유량”은 각 태그의 최대 메타 태그 카운트 — 이 라이브러리 밖에 있는 이미지 수를 태그의 메타 태그별, 사이트별로 센 것(“tumblr 50”, “twitter 100”) — 을 더합니다. 합계가 아니라 가장 큰 단일 수치를 쓰는데, 사이트들끼리 겹치는 이미지를 세기 때문입니다. 앱의 다른 어디에서도 이 숫자를 집계에 더하지 않습니다. 그것을 포함한 합계는 다른 곳에 대한 주장이 되기 때문입니다. 하지만 균형 조정에는 그쪽이 정직한 숫자인 경우가 많습니다. 여기 네 장, 출처에 사만 장인 태그는 드문 낱말이 아니며, 드물게 취급하면 모델이 이미 아는 낱말을 가르치는 데 학습을 쓰게 됩니다.",
  "Caption selection": "캡션 선택",
  "Instruction selection": "지시 선택",
  "Start now — pauses the running job and puts this one first":
    "지금 시작 — 실행 중인 작업을 일시정지하고 이 작업을 맨 앞에 둡니다",
  "Start now — puts this job first and starts the queue":
    "지금 시작 — 이 작업을 맨 앞에 두고 대기열을 시작합니다",
  "Save as duplicate":
    "사본으로 저장",
  "Batch & seed": "배치 및 시드",
  "Device": "장치",
  "Precision & quantization": "정밀도 및 양자화",
  "Memory savers": "메모리 절약",
  "Training images": "학습 이미지",
  "Length measured in":
    "학습량 단위",
  "Steps are a fixed amount of work; epochs are full passes over your images, so the run grows with the dataset.":
    "스텝은 고정된 작업량이고 에포크는 이미지 전체를 한 번 도는 것이라, 데이터셋이 커지면 학습도 길어집니다.",
  "A STEP is one batch pushed through the model and one update of the weights — a fixed amount of work whatever the dataset holds. An EPOCH is one pass over every training image, so the same number means a longer run on a bigger set and the model sees each picture the same number of times either way.\n\nEpochs are usually the easier thing to reason about: “each image about ten times” transfers between datasets, where “3000 steps” does not. The exact step count is worked out when the run starts, because only then is it known how many entries the dataset has — a film contributes its frames, a degraded copy is an extra sample, and an item can contribute one per caption.":
    "1스텝은 배치 하나를 모델에 통과시키고 가중치를 한 번 갱신하는 것으로, 데이터셋 크기와 상관없이 작업량이 일정합니다. 1에포크는 모든 학습 이미지를 한 번 도는 것이라, 같은 숫자라도 데이터셋이 크면 학습이 길어지고 어느 쪽이든 각 이미지를 보는 횟수는 같습니다.\n\n보통은 에포크가 가늠하기 쉽습니다. \"이미지마다 열 번쯤\"은 다른 데이터셋에도 옮겨가지만 \"3000스텝\"은 그렇지 않습니다. 정확한 스텝 수는 실행이 시작될 때 계산됩니다. 그때서야 데이터셋의 항목 수를 알 수 있기 때문입니다 — 영상은 프레임을, 열화 사본은 추가 샘플을, 한 항목은 설명마다 하나씩 항목을 더할 수 있습니다.",
  "Epochs":
    "에포크",
  "Full passes over the dataset. The exact step count is worked out when the run starts and shown in its log.":
    "데이터셋을 몇 번 도는지. 정확한 스텝 수는 실행이 시작될 때 계산되어 로그에 표시됩니다.",
  "How many times the run works through every training image. Each pass visits every entry exactly once, in a fresh random order.\n\nWhat counts as an entry is the dataset after it has been built, not the number of pictures you selected: a video contributes one entry per kept frame, a degradation variant adds an extra sample beside the clean picture, and with “every caption” an item contributes one entry per caption. That is why the step count appears when the run starts rather than here.":
    "학습이 모든 이미지를 몇 번이나 훑는지. 한 번 돌 때마다 각 항목을 정확히 한 번씩, 매번 새로 섞은 순서로 방문합니다.\n\n여기서 항목이란 완성된 데이터셋을 말하며, 선택한 이미지 수가 아닙니다. 영상은 남긴 프레임마다 한 항목, 열화 변형은 깨끗한 이미지 옆에 샘플 하나를 더하고, \"모든 설명\"을 고르면 한 항목이 설명마다 하나씩 생깁니다. 스텝 수가 여기가 아니라 실행 시작 때 나오는 이유입니다.",
  "Query weight":
    "쿼리 가중치",
  "A weight buys":
    "가중치가 사는 것",
  "Whether a heavier query's images are seen more often, or seen the same and counted for more.":
    "가중치가 큰 쿼리의 이미지를 더 자주 볼지, 같은 횟수로 보되 더 크게 반영할지.",
  "Both spend the same ratio; they differ in what they spend it on.\n\nSEEN MORE OFTEN is the classic behaviour: a weight-2 query's pictures get twice the visits, which means they take those visits from the rest — a fixed-length run spends more of itself on them and less on everything else.\n\nCOUNTED FOR MORE gives every picture the same number of visits and multiplies the weighted ones' effect on the weights instead. Nothing loses coverage; the emphasis comes out of the gradient rather than out of the other images' training time. It is the better default when the queries are different KINDS of picture rather than different amounts of importance.":
    "둘 다 같은 비율을 쓰지만, 그 비율을 어디에 쓰느냐가 다릅니다.\n\n\"더 자주 보기\"는 전통적인 동작입니다. 가중치 2인 쿼리의 이미지는 방문 횟수가 두 배가 되고, 그만큼을 나머지에서 가져옵니다. 길이가 정해진 학습에서는 그 이미지에 더 많이, 다른 모든 것에 더 적게 쓰게 됩니다.\n\n\"더 크게 반영\"은 모든 이미지에 같은 횟수의 방문을 주고, 대신 가중된 이미지가 가중치에 미치는 영향을 키웁니다. 어떤 것도 커버리지를 잃지 않고, 강조는 다른 이미지의 학습 시간이 아니라 그래디언트에서 나옵니다. 쿼리가 중요도의 차이가 아니라 이미지의 \"종류\" 차이를 나타낼 때 더 나은 기본값입니다.",
  "Seen more often":
    "더 자주 보기",
  "Counted for more":
    "더 크게 반영",
  "An item with several captions":
    "설명이 여러 개인 항목",
  "Whether every caption is used each pass, or one is drawn per visit.":
    "한 번 돌 때 모든 설명을 쓸지, 방문마다 하나를 뽑을지.",
  "Items often carry more than one caption — a short one and a long one, a translation, a machine draft somebody approved.\n\nONE AT RANDOM gives the item a single visit each pass and draws a different caption each time, so the whole set is seen across a long run and an item counts once however many ways it has been described.\n\nEVERY CAPTION gives it one visit per caption, so all of them are used every pass — and an item with ten is therefore seen ten times, which is usually an accident of tooling rather than a claim that the picture matters ten times as much.\n\nEVERY CAPTION, SHARED is that with the accident removed: each caption still gets its visit, and together they carry one item's worth of gradient.":
    "항목에는 설명이 여러 개 붙어 있는 경우가 많습니다 — 짧은 것과 긴 것, 번역, 누군가 승인한 기계 초안 등.\n\n\"무작위로 하나\"는 한 바퀴에 방문을 한 번만 주고 매번 다른 설명을 뽑습니다. 학습이 길어지면 전부 쓰이게 되고, 설명이 몇 개든 항목은 한 번으로 셉니다.\n\n\"모든 설명\"은 설명마다 방문을 한 번씩 주므로 한 바퀴에 전부 쓰입니다 — 설명이 열 개인 항목은 열 번 보이게 되는데, 이는 보통 도구 사정에 따른 우연이지 그 그림이 열 배 중요하다는 뜻이 아닙니다.\n\n\"모든 설명, 가중치 나눠서\"는 그 우연을 없앤 것입니다. 각 설명은 자기 방문을 유지하되, 다 합쳐서 항목 하나 몫의 그래디언트를 담당합니다.",
  "One at random each visit":
    "방문마다 무작위로 하나",
  "Every caption, once each":
    "모든 설명을 한 번씩",
  "Every caption, sharing one item's weight":
    "모든 설명을 한 번씩, 항목 하나의 가중치를 나눠서",
  "Unsupported":
    "지원 안 함",
  "not available on Apple silicon":
    "Apple 실리콘에서는 사용할 수 없습니다",
  "not used on Apple silicon, where the run trains in fp32":
    "Apple 실리콘에서는 쓰이지 않고 학습이 fp32로 진행됩니다",
  "a full finetune trains the base weights, so there is nothing to quantize":
    "완전 미세조정은 기본 가중치를 학습하므로 양자화할 대상이 없습니다",
  "only offered for LoRA training":
    "LoRA 학습에서만 제공됩니다",
  "too large to finetune on any GPU this app has constants for":
    "이 앱이 수치를 가진 어떤 GPU로도 미세조정하기엔 너무 큽니다",
  "Another picture": "다른 이미지",
  "{n} jobs selected. One at a time shows its progress, samples and settings.":
    "작업 {n}개 선택됨. 진행 상황과 테스트 이미지, 설정은 한 번에 하나씩 표시됩니다.",
  "original":
    "원본",
  "Show this at full size":
    "원래 크기로 보기",
  "Each snapshot is about {size}.":
    "스냅숏 하나가 약 {size}입니다.",
  "Cadence measured in":
    "주기 단위",
  "How often a snapshot is written: after a fixed number of steps, or after a number of full passes over the dataset.":
    "스냅숏을 쓰는 빈도. 정해진 스텝 수마다, 또는 데이터셋을 몇 번 돌 때마다.",
  "How often a round of samples is rendered: after a fixed number of steps, or after a number of full passes over the dataset.": "테스트 샘플을 생성하는 주기: 고정된 스텝 수마다, 또는 데이터셋을 몇 번 도는지로.",
  "Rendered after this many full passes. The equivalent step count appears in the job's log when the run starts.": "이만큼 전체를 돌 때마다 생성됩니다. 해당하는 스텝 수는 실행이 시작될 때 작업 로그에 표시됩니다.",
  "A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 250 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both. It is the choice the checkpoint cadence and the run’s own length already offer, and setting all three the same way is what makes a sample, its checkpoint and a pass over your pictures line up in the timeline.\n\nHow many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has — a film’s frames, a degraded copy and an item contributing one entry per caption all count.": "스텝은 정해진 양의 작업이고 에폭은 모든 학습 이미지를 한 번 도는 것이므로, 데이터셋이 커질수록 두 주기는 벌어집니다 — 「250 스텝마다」는 작은 실행에서는 거의 전부이고 큰 실행에서는 일부지만, 「에폭마다」는 둘 다에서 같은 뜻입니다. 체크포인트 주기와 실행 길이가 이미 제공하는 것과 같은 선택이며, 셋을 같은 단위로 맞추면 샘플과 그 체크포인트, 그리고 사진을 한 번 도는 일이 타임라인에서 나란히 놓입니다.\n\n한 에폭이 몇 스텝인지는 실행이 시작될 때 계산됩니다. 항목이 몇 개인지는 완성된 데이터셋만 알기 때문입니다 — 영상의 프레임, 열화 사본, 캡션마다 항목 하나를 내는 아이템이 모두 셈에 들어갑니다.",
  "Rendered after this many full passes over the dataset. The equivalent step count is printed in the job’s log when the run starts, so a glance there says what the cadence came out as for this particular dataset.\n\nSampling interrupts training while it renders, so on a large dataset one round per epoch may be further apart than you want and on a tiny one it may be a pause every few seconds — the log’s step figure is what tells you which.": "데이터셋을 이만큼 완전히 돌 때마다 생성됩니다. 해당하는 스텝 수는 시작할 때 작업 로그에 적히므로, 이 데이터셋에서 주기가 실제로 어떻게 되는지 한눈에 알 수 있습니다.\n\n샘플을 만드는 동안 학습이 멈추므로, 큰 데이터셋에서는 에폭마다 한 번도 원하는 것보다 뜸할 수 있고 아주 작은 데이터셋에서는 몇 초마다 멈출 수도 있습니다 — 어느 쪽인지는 로그의 스텝 수가 알려줍니다.",
  "Rendered every this many steps, whatever the dataset is. 250–500 is a good rhythm: often enough to catch a concept going wrong, rare enough that the pauses do not dominate the run.": "데이터셋과 무관하게 이 스텝 수마다 생성됩니다. 250~500이 좋은 리듬입니다. 개념이 어긋나는 것을 알아챌 만큼 잦고, 중단이 실행을 지배하지 않을 만큼 드뭅니다.",
  "A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 500 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both.\n\nHow many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has. That is also why the disk estimate below can only be given when the run's length is set in epochs too.":
    "스텝은 고정된 작업량이고 에포크는 모든 학습 이미지를 한 번 도는 것이라, 데이터셋이 커질수록 두 주기는 벌어집니다. \"500스텝마다\"는 작은 학습에서는 거의 전부이고 큰 학습에서는 일부지만, \"매 에포크\"는 어느 쪽에서도 같은 뜻입니다.\n\n한 에포크가 몇 스텝인지는 실행이 시작될 때 정해집니다. 항목 수를 아는 것은 완성된 데이터셋뿐이기 때문입니다. 아래 디스크 추정치도 학습 길이를 에포크로 정했을 때만 나올 수 있습니다.",
  "epochs":
    "에포크",
  "Written after this many full passes. The equivalent step count appears in the job's log when the run starts.":
    "이만큼 전체를 돌 때마다 기록됩니다. 스텝으로 환산한 값은 실행이 시작될 때 작업 로그에 표시됩니다.",
  "Every snapshot is a usable model file: the Evaluate tab can generate with any of them, so you can compare one pass against another and keep whichever looks best.\n\nCounted in passes, the cadence follows the dataset: add pictures and the snapshots stay one-per-pass rather than quietly becoming more frequent than a pass. The trainer prints what it works out to in steps, so the timeline and the log still agree about what a checkpoint is.":
    "스냅숏은 모두 그대로 쓸 수 있는 모델 파일입니다. Evaluate 탭에서 어느 것으로든 생성할 수 있으니, 한 바퀴와 다른 바퀴를 견줘 보고 더 나은 쪽을 남기면 됩니다.\n\n바퀴 수로 세면 주기가 데이터셋을 따라갑니다. 이미지를 더해도 한 바퀴에 하나가 유지되고, 소리 없이 한 바퀴보다 잦아지지 않습니다. 스텝으로 환산한 값은 트레이너가 로그에 적으므로 타임라인과 로그가 체크포인트를 두고 어긋나지 않습니다.",
  "Never upscale":
    "확대하지 않기",
  "Leave out any image smaller than the bucket it would be fitted to, rather than enlarging it.":
    "배정될 버킷보다 작은 이미지는 확대하지 않고 제외합니다.",
  "Loads the frozen base weights in 8-bit or 4-bit so big models fit in little memory (QLoRA). 8-bit (int8) runs on Apple silicon too; fp8 and 4-bit need an NVIDIA GPU.":
    "동결된 베이스 가중치를 8비트나 4비트로 로드하여 큰 모델이 적은 메모리에 들어가게 합니다 (QLoRA). 8비트(int8)는 Apple Silicon에서도 동작합니다. fp8과 4비트는 NVIDIA GPU가 필요합니다.",
  "Quantize the text encoder":
    "텍스트 인코더 양자화",
  "Applies the same scheme to the text encoder, the other big frozen model. On the largest models it is worth several GB.":
    "같은 방식을 또 하나의 큰 동결 모델인 텍스트 인코더에도 적용합니다. 가장 큰 모델에서는 수 GB에 해당합니다.",
  "cannot be combined with training the text encoder":
    "텍스트 인코더 학습과 함께 사용할 수 없습니다",

  // ---- adapter type, layer targeting, optimizers, noise levels,
  // weight averaging and regularization ----
  "Adapter":
    "어댑터",
  "Adapter type":
    "어댑터 종류",
  "Kronecker factor":
    "크로네커 인자",
  "How each weight is split into LoKr's two parts. Leave empty unless you have a reason not to.":
    "각 가중치를 LoKr의 두 부분으로 어떻게 나눌지. 특별한 이유가 없다면 비워 두세요.",
  "Only these layers":
    "이 레이어만",
  "all of them":
    "전부",
  "Comma-separated parts of a layer's name. Leave empty to train every attention layer — which is what you want unless you have a reason not to.":
    "레이어 이름의 일부를 쉼표로 구분해 입력합니다. 비워 두면 모든 어텐션 레이어를 학습하며, 특별한 이유가 없다면 그게 맞습니다.",
  "By default the adapter attaches to every attention layer in the image model. This narrows that to the layers whose name contains one of the words you list.\n\nWhy you might: different parts of the network do different jobs. The later ones carry more of what a picture LOOKS like, and the earlier ones more of how it is put together — so training only part of the network is how a style is learned without also disturbing composition and anatomy. It also makes the adapter smaller and each step faster, since there is less to train.\n\nThe names come from the model itself, and the chevron at the end of the field lists the ones worth knowing for the architecture you picked — clicking one adds or removes it, and a tick marks the ones the field already holds. For SD and SDXL they are down_blocks, mid_block and up_blocks, plus attn1 (the picture attending to itself) and attn2 (where the prompt gets in); for the newer transformer models, transformer_blocks and single_transformer_blocks. The field stays free text, because you can be as coarse or as fine as you like: 'up_blocks' takes a whole third of a UNet, 'transformer_blocks.12' takes one block, 'to_k' takes one kind of projection everywhere. The job's page draws a map of the whole model once a run has started.\n\nIf what you type matches no layers at all, the run stops and says so rather than training an adapter attached to nothing — which would otherwise look exactly like a normal run that learned nothing.":
    "기본적으로 어댑터는 이미지 모델의 모든 어텐션 레이어에 붙습니다. 여기서는 이름에 나열한 단어 중 하나가 들어간 레이어로 범위를 좁힙니다.\n\n왜 그럴 수 있는가: 신경망의 부분마다 하는 일이 다릅니다. 뒤쪽 레이어는 그림이 어떻게 '보이는지'를 더 많이 담고, 앞쪽 레이어는 그림이 어떻게 짜여 있는지를 더 많이 담습니다. 그래서 신경망의 일부만 학습시키는 것이, 구도와 인체 구조를 흔들지 않으면서 화풍을 배우게 하는 방법입니다. 학습할 것이 줄어드니 어댑터도 작아지고 한 스텝도 빨라집니다.\n\n이름은 모델 자체에서 나오며, 필드 끝의 화살표를 누르면 선택한 아키텍처에서 알아둘 만한 것들이 나열됩니다 — 클릭하면 추가되거나 빠지고, 필드에 이미 있는 것에는 체크가 붙습니다. SD와 SDXL에서는 down_blocks, mid_block, up_blocks에 더해 attn1(이미지가 자기 자신을 보는 쪽)과 attn2(프롬프트가 들어오는 쪽)이고, 더 새로운 transformer 계열 모델에서는 transformer_blocks와 single_transformer_blocks입니다. 거칠게도 세밀하게도 지정할 수 있으므로 필드는 자유 입력으로 남아 있습니다. 'up_blocks'는 UNet의 3분의 1을 통째로, 'transformer_blocks.12'는 한 블록만, 'to_k'는 모든 곳의 한 종류 투영을 가져갑니다. 실행이 시작되면 작업 페이지가 모델 전체의 지도를 그려 줍니다.\n\n입력한 내용이 어떤 레이어와도 맞지 않으면, 실행은 아무것도 붙지 않은 어댑터를 학습하는 대신 멈추고 그 사실을 알립니다. 그러지 않으면 아무것도 배우지 못한 평범한 실행과 똑같아 보이기 때문입니다.",
  "Except these layers":
    "이 레이어는 제외",
  "Comma-separated parts of a layer's name to leave out. Applied after the field above, and it wins.":
    "제외할 레이어 이름의 일부를 쉼표로 구분해 입력합니다. 위 항목 다음에 적용되며 이쪽이 우선합니다.",
  "The same kind of list, subtracting instead of selecting. A layer whose name matches anything here is left out even if the field above selected it.\n\nIt is the easier way to say 'everything except' — excluding 'down_blocks' is shorter and stays correct if the model gains a block, where listing every other block by hand does not.":
    "같은 형식의 목록이지만 고르는 대신 빼냅니다. 여기에 걸리는 이름의 레이어는 위 항목이 골랐더라도 제외됩니다.\n\n'~을 뺀 전부'를 말하는 더 쉬운 방법입니다. 'down_blocks'를 제외하는 편이 짧고, 모델에 블록이 하나 늘어도 계속 맞습니다. 나머지 블록을 손으로 전부 나열하는 방식은 그렇지 않습니다.",
  "Output size: a small fraction of a LoRA of the same rank — usually under a tenth.":
    "결과물 크기: 같은 랭크 LoRA의 아주 일부 — 보통 10분의 1 미만입니다.",
  "Learning rate multiplier":
    "학습률 배수",
  "Prodigy works the rate out for itself; this scales what it finds. 1 leaves it alone — lower it if the run overshoots, raise it if it never gets going.":
    "Prodigy는 학습률을 스스로 구합니다. 여기는 그 결과에 곱하는 배수로, 1이면 그대로 씁니다. 과하게 나가면 낮추고, 도무지 시작되지 않으면 올리세요.",
  "The Prodigy optimizer measures how far the weights have moved from where they started and derives a learning rate from that, so the rate is not something you set here — it comes out of the run.\n\nWhat this field does is scale the answer. 1 accepts it as found and is what you want almost always. Below 1 is a brake, worth reaching for if the run overshoots and samples come out burnt; above 1 pushes harder, which is occasionally useful on a very small dataset.\n\nProdigy needs a few hundred steps to work its estimate up from nearly nothing, so early samples in a Prodigy run look untrained even when everything is fine. Judge it from about a fifth of the way in, not from the first sample round.":
    "Prodigy 옵티마이저는 가중치가 출발점에서 얼마나 멀어졌는지 재고 거기서 학습률을 끌어냅니다. 즉 학습률은 여기서 정하는 값이 아니라 실행 자체에서 나옵니다.\n\n이 항목이 하는 일은 그 답에 배수를 곱하는 것뿐입니다. 1은 구해진 값을 그대로 받아들이는 뜻이고, 거의 항상 그게 맞습니다. 1보다 작으면 브레이크로, 실행이 과하게 나가 샘플이 타 버린 듯 나올 때 써 볼 만합니다. 1보다 크면 더 세게 미는데, 아주 작은 데이터셋에서 가끔 쓸모가 있습니다.\n\nProdigy는 추정값을 거의 0에서부터 끌어올리는 데 수백 스텝이 필요합니다. 그래서 Prodigy 실행에서는 모든 것이 정상이어도 초반 샘플이 학습되지 않은 것처럼 보입니다. 첫 샘플 회차가 아니라 대략 5분의 1쯤 진행된 지점부터 판단하세요.",
  "How far the weights move on every update. It is the single most sensitive setting here.\n\nToo high and training diverges: samples turn into over-saturated, high-contrast mush ('deep fried'), often within a few hundred steps. Too low and nothing visibly changes no matter how long you wait. Typical values: 1e-4 for a LoRA, 1e-5 or lower for a full finetune (which touches every weight and needs far gentler updates).\n\nLearning rate and total steps trade off against each other — halving the rate roughly doubles the steps needed. If early samples look burnt, halve it; if they look identical to the baseline after a third of the run, double it.\n\nIf finding this number is the part you would rather not do, the Prodigy optimizer (Memory & speed) works it out for itself.":
    "업데이트마다 가중치가 얼마나 움직이는지입니다. 여기서 가장 민감한 설정입니다.\n\n너무 높으면 학습이 발산합니다. 샘플이 채도와 대비가 과한 죽처럼 되고('deep fried'), 수백 스텝 안에 그렇게 되는 일도 흔합니다. 너무 낮으면 아무리 기다려도 눈에 띄는 변화가 없습니다. 통상값: LoRA는 1e-4, 전체 파인튜닝은 1e-5 이하(모든 가중치를 건드리므로 훨씬 부드러운 업데이트가 필요합니다).\n\n학습률과 총 스텝 수는 서로 상쇄됩니다. 학습률을 반으로 줄이면 필요한 스텝 수는 대략 두 배가 됩니다. 초반 샘플이 타 보이면 반으로 줄이고, 실행의 3분의 1이 지나도 처음과 똑같아 보이면 두 배로 올리세요.\n\n이 숫자를 찾는 일이 바로 피하고 싶은 부분이라면, Prodigy 옵티마이저(메모리와 속도)가 스스로 구해 줍니다.",
  "Noise levels":
    "노이즈 강도",
  "Train on":
    "학습 구간",
  "Which stage of denoising to spend the run on. High noise decides a picture's layout, low noise its detail — so this decides what the training is mostly about.":
    "노이즈 제거의 어느 단계에 실행을 쓸지. 노이즈가 강한 쪽은 그림의 배치를, 약한 쪽은 디테일을 정합니다. 즉 이 설정이 학습이 주로 무엇에 관한 것인지를 정합니다.",
  "Every training step takes a picture, adds some amount of noise to it, and asks the model to undo that. How much noise is picked fresh each time — and the two extremes teach completely different things.\n\nAt HIGH noise there is barely a picture left, so all the model can learn is layout: what is where, how big, the overall shape and colour. At LOW noise the composition is already settled and what is left to learn is detail and texture — edges, surfaces, small features.\n\nSo where a run spends its steps decides what it mostly teaches. A style is largely texture; a character's proportions are largely layout.\n\n'The model's own' is what this model family has always done here, and is the right answer unless you have a specific reason: the older models spread their steps evenly, and the newer ones concentrate on the middle, which is what their published recipes do and part of why they train efficiently. 'Evenly' spreads across the whole range. 'Bell curve' is the newer models' behaviour made adjustable, so you can lean it towards layout or towards detail. 'Cosine' leans towards higher noise without abandoning the low end.\n\nChanging this does not make a run better or worse in general — it moves what the run is good at.":
    "학습의 매 스텝은 그림 한 장에 일정량의 노이즈를 더하고, 모델에게 그것을 되돌리라고 요구합니다. 노이즈의 양은 매번 새로 뽑히며, 두 극단은 완전히 다른 것을 가르칩니다.\n\n노이즈가 강한 쪽에서는 그림이 거의 남아 있지 않으므로 모델이 배울 수 있는 것은 배치뿐입니다. 무엇이 어디에, 얼마나 크게, 전체적인 형태와 색은 어떤지. 노이즈가 약한 쪽에서는 구도가 이미 정해져 있고 남은 것은 디테일과 질감 — 가장자리, 표면, 작은 요소들입니다.\n\n그래서 실행이 스텝을 어디에 쓰느냐가 주로 무엇을 가르치는지를 정합니다. 화풍은 대체로 질감이고, 캐릭터의 비율은 대체로 배치입니다.\n\n'모델 고유의 방식'은 이 모델 계열이 여기서 늘 해 온 방식이며, 특별한 이유가 없다면 이것이 정답입니다. 오래된 모델들은 스텝을 고르게 흩고, 새 모델들은 가운데에 집중합니다. 공개된 레시피가 그렇게 하며, 그것이 이들이 효율적으로 학습하는 이유의 일부이기도 합니다. '고르게'는 전체 범위에 흩습니다. '종 모양 곡선'은 새 모델의 동작을 조절 가능하게 만든 것으로, 배치 쪽이나 디테일 쪽으로 기울일 수 있습니다. '코사인'은 낮은 쪽을 버리지 않으면서 높은 노이즈 쪽으로 기웁니다.\n\n이 설정을 바꾼다고 실행이 전반적으로 좋아지거나 나빠지지는 않습니다. 실행이 잘하게 되는 방향이 옮겨질 뿐입니다.",
  "The model's own (recommended)":
    "모델 고유의 방식 (권장)",
  "Evenly across all levels":
    "모든 강도에 고르게",
  "A bell curve I can aim":
    "겨냥할 수 있는 종 모양 곡선",
  "Leaning towards layout":
    "배치 쪽으로 기울이기",
  "Aim at":
    "겨냥",
  "0 is the middle. Positive leans towards layout and composition, negative towards detail and texture. ±1 is already a strong lean.":
    "0이 가운데입니다. 양수는 배치와 구도 쪽으로, 음수는 디테일과 질감 쪽으로 기웁니다. ±1이면 이미 강한 기울기입니다.",
  "Where the centre of the bell curve sits along the noise range.\n\n0 puts it in the middle, which is what the newer models do by default and a good place to stay. Move it positive and the run spends more of itself at high noise, learning layout and composition — useful when what you are teaching is a shape or an arrangement. Move it negative and it spends more at low noise, learning detail and texture — useful for a style, a medium, a surface quality.\n\n±0.5 is a noticeable lean and ±1 is a strong one. Beyond ±2 the run largely stops seeing one end of the range at all.":
    "노이즈 범위에서 종 모양 곡선의 중심이 어디에 놓이는지입니다.\n\n0은 가운데이며, 새 모델들의 기본 위치이자 그대로 두기 좋은 자리입니다. 양수로 옮기면 실행이 높은 노이즈 쪽에 더 많은 시간을 쓰며 배치와 구도를 배웁니다. 형태나 배열을 가르칠 때 유용합니다. 음수로 옮기면 낮은 노이즈 쪽에 더 많이 쓰며 디테일과 질감을 배웁니다. 화풍, 매체, 표면의 질을 가르칠 때 유용합니다.\n\n±0.5는 눈에 띄는 기울기이고 ±1은 강한 기울기입니다. ±2를 넘어가면 실행이 범위의 한쪽 끝을 사실상 전혀 보지 않게 됩니다.",
  "Spread":
    "퍼짐",
  "How wide the curve is. 1 is the default; smaller concentrates the run on a narrow band around the aim, larger reaches both extremes.":
    "곡선의 너비입니다. 기본값은 1이며, 작을수록 겨냥한 지점 주변의 좁은 구간에 집중하고, 클수록 양쪽 끝까지 닿습니다.",
  "The width of the bell curve.\n\n1 is the standard setting. Smaller values concentrate the run on a narrow band around wherever you have aimed it, which sharpens what it teaches at the cost of everything else. Larger values spread it out and reach both extremes more often, which is closer to training evenly.\n\nIf you are unsure, leave it at 1 and move the aim instead — the aim is the setting that changes what the run learns, and this one changes how single-minded it is about it.":
    "종 모양 곡선의 너비입니다.\n\n1이 표준 설정입니다. 값이 작을수록 겨냥한 지점 주변의 좁은 구간에 실행이 집중되어, 나머지 전부를 대가로 가르치는 내용이 날카로워집니다. 값이 클수록 넓게 퍼져 양쪽 끝에 더 자주 닿으며, 고르게 학습하는 쪽에 가까워집니다.\n\n확신이 서지 않으면 1로 두고 대신 겨냥 값을 옮기세요. 겨냥은 실행이 무엇을 배우는지를 바꾸는 설정이고, 이 값은 그 일에 얼마나 외곬인지를 바꾸는 설정입니다.",
  "Weight averaging":
    "가중치 평균",
  "Average the weights":
    "가중치를 평균 내기",
  "Save a smoothed version of the weights instead of whatever the last step happened to produce. Makes checkpoints more consistent and overtraining slower to bite.":
    "마지막 스텝이 우연히 내놓은 가중치 대신, 매끄럽게 다듬은 가중치를 저장합니다. 체크포인트가 더 고르게 나오고 과학습의 영향도 더 늦게 나타납니다.",
  "Every training step moves the weights a little, and each of those moves is noisy — it is worked out from a handful of images, and a different handful would have pulled somewhere slightly different. So the weights at step 1400 are not reliably better than the weights at step 1200; part of the difference is just which pictures came up.\n\nWith this on, the run keeps a second, smoothed copy of the weights alongside the real ones and nudges it a little way towards the current weights after every step. That smoothed copy is what gets saved — as the checkpoints, as the final result, and as what the test samples are rendered from. Training itself is completely unaffected.\n\nWhat you get is a result that depends less on exactly where the run stopped: the quality difference between neighbouring checkpoints shrinks, and a run that goes on too long degrades more gradually, because an average lags behind. What it costs is one extra copy of whatever is being trained — nothing worth thinking about for a LoRA, a second whole model for a full finetune, which the memory estimate below accounts for.\n\nThe early part of a run is handled for you: a fresh average starts out equal to the untrained weights, so the run keeps it short at first and lengthens it as training goes on. Without that, a short run would save an average still holding its own random starting point.":
    "학습의 매 스텝은 가중치를 조금씩 움직이는데, 그 움직임 하나하나에는 잡음이 섞여 있습니다. 한 줌의 이미지에서 계산된 것이라, 다른 한 줌이었다면 조금 다른 쪽으로 당겼을 것입니다. 그래서 1400 스텝의 가중치가 1200 스텝의 가중치보다 확실히 낫다고 할 수 없습니다. 차이의 일부는 그저 어떤 그림이 뽑혔느냐일 뿐입니다.\n\n이 옵션을 켜면 실행은 진짜 가중치 옆에 매끄럽게 다듬은 두 번째 사본을 유지하고, 매 스텝 뒤에 그것을 현재 가중치 쪽으로 조금씩 밀어 줍니다. 저장되는 것은 바로 그 사본입니다 — 체크포인트도, 최종 결과물도, 테스트 샘플을 그리는 데 쓰이는 것도 그것입니다. 학습 자체는 전혀 영향을 받지 않습니다.\n\n얻는 것은 실행이 정확히 어디서 멈췄는지에 덜 좌우되는 결과입니다. 이웃한 체크포인트 사이의 품질 차이가 줄고, 너무 오래 이어진 실행도 더 완만하게 나빠집니다. 평균은 뒤늦게 따라오기 때문입니다. 대가는 학습 대상의 사본 하나가 더 필요하다는 점인데, LoRA라면 신경 쓸 것 없고 전체 파인튜닝이라면 모델 하나가 더 필요합니다. 아래의 메모리 추정치는 이를 반영합니다.\n\n실행 초반은 알아서 처리됩니다. 새 평균은 학습되지 않은 가중치와 같은 상태에서 시작하므로, 실행은 처음에는 평균 구간을 짧게 유지하고 학습이 진행될수록 늘려 갑니다. 그러지 않으면 짧은 실행은 자기 자신의 무작위 출발점을 여전히 품은 평균을 저장하게 됩니다.",
  "Averaging window":
    "평균 구간",
  "How much of the old average is kept each step. 0.999 averages roughly the last 1000 steps; lower follows training more closely, higher smooths harder.":
    "매 스텝에서 이전 평균을 얼마나 남길지. 0.999면 대략 최근 1000 스텝의 평균이 됩니다. 낮을수록 학습을 더 바짝 따라가고, 높을수록 더 강하게 다듬습니다.",
  "The fraction of the existing average kept at each step, with the rest taken from the current weights. It decides how long a stretch of training the saved result reflects — roughly 1 ÷ (1 − this value) steps.\n\n0.999 is about the last 1000 steps and is a sensible default for runs of a few thousand. On a short run (say 800 steps) that window is longer than the run itself, so the average never quite catches up — drop to 0.99 (about 100 steps) there. On a very long run you can go higher for a steadier result.\n\nAs a rule of thumb, keep the window well under the total number of steps.":
    "매 스텝에서 기존 평균을 남기는 비율이며, 나머지는 현재 가중치에서 가져옵니다. 저장되는 결과가 학습의 어느 정도 구간을 반영하는지를 정하며, 대략 1 ÷ (1 − 이 값) 스텝에 해당합니다.\n\n0.999는 최근 1000 스텝 정도이고, 수천 스텝짜리 실행에는 합리적인 기본값입니다. 짧은 실행(예를 들어 800 스텝)에서는 이 구간이 실행보다 길어서 평균이 끝내 따라잡지 못합니다. 그런 경우 0.99(약 100 스텝)로 낮추세요. 아주 긴 실행에서는 더 안정적인 결과를 위해 올려도 됩니다.\n\n경험칙으로, 구간은 총 스텝 수보다 충분히 작게 유지하세요.",
  "Mostly a memory choice, except for Prodigy, which works the learning rate out for itself. Adafactor saves the most memory and runs on every GPU; 8-bit AdamW saves less and needs an NVIDIA or AMD card.":
    "대체로 메모리에 관한 선택입니다. 다만 Prodigy는 학습률을 스스로 구합니다. Adafactor가 메모리를 가장 많이 아끼고 모든 GPU에서 돌아갑니다. AdamW(8비트)는 덜 아끼며 NVIDIA나 AMD 카드가 필요합니다.",
  "The optimizer is what actually turns gradients into weight changes. It does that using running statistics it keeps for every weight being trained — and those statistics are memory, which for a full finetune is usually most of what the run needs.\n\nAdamW is the standard choice and the safest. It keeps two statistics per trained weight, so a full finetune pays for the model roughly three times over: the weights themselves, plus two more of the same size.\n\nAdamW (8-bit) stores those two statistics at one byte each instead of four. It is a smaller saving than it sounds, because the weights and their gradients do not shrink, and it needs an NVIDIA or AMD (ROCm) GPU — elsewhere the run says so and uses plain AdamW.\n\nAdafactor replaces the larger of the two statistics with a per-row and a per-column summary of it, which is a fraction of the size. It saves considerably more than the 8-bit variant and it runs on every GPU, including Apple silicon — where it is the only memory saving available at all, since the 8-bit variant cannot run there. What it costs is a little stability: it usually wants a slightly higher learning rate than AdamW, so if a run learns nothing after a few hundred steps, raise the rate before changing anything else.\n\nProdigy is a different kind of answer. It measures how far the weights have travelled from where they started and works the learning rate out from that as it goes, which removes the one setting here that genuinely has to be found by trial: the right rate depends on the model, the dataset size and what is being taught, so a value that suits one job is wrong for the next. With it selected, the learning rate on the Optimization page becomes a multiplier on what it finds, and 1 means 'as found'. It uses a little more memory than AdamW, and it needs a few hundred steps to work its estimate up — so early samples look untrained even when the run is fine.\n\nFor LoRA training the memory differences are a rounding error, since only the small adapter has optimizer state. Leave it on AdamW for a first run; reach for Prodigy when you are tired of guessing the rate, and for Adafactor when a full finetune will not fit.":
    "옵티마이저는 그래디언트를 실제 가중치 변화로 바꾸는 장치입니다. 그러기 위해 학습 중인 모든 가중치마다 통계를 계속 들고 있는데, 그 통계가 곧 메모리이고 전체 파인튜닝에서는 대개 실행에 필요한 메모리의 대부분을 차지합니다.\n\nAdamW가 표준이자 가장 안전한 선택입니다. 학습되는 가중치마다 통계를 두 개 유지하므로, 전체 파인튜닝은 모델 값을 대략 세 번 치르는 셈입니다. 가중치 자체에 더해 같은 크기의 통계 두 벌이죠.\n\nAdamW(8비트)는 그 두 통계를 4바이트가 아니라 1바이트씩으로 저장합니다. 가중치와 그래디언트는 줄지 않으므로 절약은 들리는 것보다 작고, NVIDIA나 AMD(ROCm) GPU가 필요합니다. 그 밖의 환경에서는 실행이 그 사실을 알리고 일반 AdamW를 씁니다.\n\nAdafactor는 두 통계 중 큰 쪽을 행별·열별 요약으로 대체하며, 크기는 아주 일부에 불과합니다. 8비트 방식보다 훨씬 많이 아끼고 Apple silicon을 포함한 모든 GPU에서 돌아갑니다. Apple silicon에서는 8비트 방식이 아예 돌아가지 않으므로 사실상 유일하게 쓸 수 있는 메모리 절약 수단이기도 합니다. 대가는 안정성이 조금 떨어진다는 점입니다. 보통 AdamW보다 조금 높은 학습률을 원하므로, 수백 스텝이 지나도 아무것도 배우지 못한다면 다른 것을 바꾸기 전에 학습률부터 올리세요.\n\nProdigy는 종류가 다른 답입니다. 가중치가 출발점에서 얼마나 멀어졌는지 재고 거기서 학습률을 진행하면서 구해 내는데, 그 덕분에 여기서 유일하게 시행착오로 찾아야 했던 설정이 사라집니다. 적절한 학습률은 모델, 데이터셋 크기, 가르치는 내용에 달려 있어서 한 작업에 맞는 값이 다음 작업에서는 틀리기 때문입니다. 이것을 고르면 최적화 페이지의 학습률은 구해진 값에 곱하는 배수가 되고, 1은 '구해진 그대로'를 뜻합니다. AdamW보다 메모리를 조금 더 쓰고, 추정값을 끌어올리는 데 수백 스텝이 필요해서 실행이 정상이어도 초반 샘플은 학습되지 않은 것처럼 보입니다.\n\nLoRA 학습에서는 옵티마이저 상태를 가지는 것이 작은 어댑터뿐이라 메모리 차이는 반올림 오차 수준입니다. 첫 실행은 AdamW로 두세요. 학습률 맞히기에 지쳤다면 Prodigy를, 전체 파인튜닝이 들어가지 않으면 Adafactor를 꺼내면 됩니다.",
  "AdamW (8-bit)":
    "AdamW(8비트)",
  "Prodigy (finds its own rate)":
    "Prodigy (학습률을 스스로 찾음)",
  "Prodigy works the learning rate out for itself, so the rate on the Optimization page becomes a multiplier on what it finds — 1 leaves it alone. It needs a few hundred steps to settle, so early samples will look untrained.":
    "Prodigy는 학습률을 스스로 구하므로, 최적화 페이지의 학습률은 그 결과에 곱하는 배수가 됩니다(1이면 그대로). 자리를 잡는 데 수백 스텝이 걸려서 초반 샘플은 학습되지 않은 것처럼 보입니다.",
  "Regularization":
    "정규화",
  "How much reminders count":
    "상기용 이미지의 비중",
  "1 gives a regularization picture the same say as a training picture, which is the usual setting. Lower makes it a gentler reminder.":
    "1이면 정규화 이미지가 학습 이미지와 같은 비중을 가지며, 이것이 통상적인 설정입니다. 낮추면 더 부드러운 상기 역할이 됩니다.",
  "Regularization pictures are in the run to hold the model's existing idea of a thing in place while you teach it something new. This is how much each of them counts against a training picture, which counts 1.\n\n1 is the classic setting and a good starting point. Lower it if the run seems reluctant to learn what you are actually training — the reminders are pulling too hard. Raise it if what you are training keeps leaking into everything else of the same kind, which is the problem they exist to solve.\n\nThis is separate from a query's weight, which decides how OFTEN those pictures come up. How often and how much are different questions: a set of reminders is usually wanted often but quietly.":
    "정규화 이미지는 새로운 것을 가르치는 동안 모델이 이미 가지고 있는 개념을 제자리에 붙들어 두기 위해 실행에 들어갑니다. 여기서 정하는 것은, 비중이 1인 학습 이미지에 대해 그 이미지 한 장이 얼마나 세게 작용하는가입니다.\n\n1이 고전적인 설정이자 좋은 출발점입니다. 실제로 학습시키려는 것을 좀처럼 배우지 못하는 듯하면 낮추세요. 상기용 이미지가 너무 세게 당기고 있는 것입니다. 학습시키는 것이 같은 종류의 다른 모든 것으로 계속 번진다면 올리세요. 바로 그 문제를 풀기 위해 존재하는 것이니까요.\n\n이것은 쿼리의 가중치와는 별개입니다. 가중치는 그 이미지들이 얼마나 '자주' 나오는지를 정합니다. 얼마나 자주와 얼마나 세게는 다른 질문입니다. 상기용 이미지 묶음은 보통 자주, 그러나 조용히 작용하기를 바랍니다.",
  "Pictures that remind the model what it already knows, instead of teaching it something new — they stop what you are training from spreading to everything else of the same kind. They never get the trigger word.":
    "새로운 것을 가르치는 대신 모델이 이미 아는 것을 상기시키는 이미지입니다. 학습시키는 내용이 같은 종류의 다른 모든 것으로 번지는 것을 막아 줍니다. 트리거가 붙는 일은 없습니다.",
  "These pictures hold the model's existing idea of the subject in place: pick the same KIND of thing you are training, but not the thing itself. You do not need to exclude your training pictures — anything an ordinary query matches stays a training picture. A reminder query that matches only training pictures leaves this pool empty, and the run says so in its log.":
    "이 이미지들은 모델이 이미 가지고 있는 대상에 대한 이해를 붙잡아 둡니다. 학습시키는 것과 같은 '종류'이지만 그 대상 자체는 아닌 이미지를 고르세요. 학습 이미지를 제외할 필요는 없습니다 — 일반 쿼리에 걸린 이미지는 그대로 학습 이미지입니다. 리마인더 쿼리가 학습 이미지만 찾으면 이 풀은 비게 되며, 실행이 로그에 그렇게 알립니다.",
  "Keep the text encoder on the CPU":
    "텍스트 인코더를 CPU에 두기",
  "Frees all of its VRAM instead of some. The next batch's prompt is encoded while this one trains, so it costs nothing as long as the processor keeps up with the card.": "VRAM 일부가 아니라 전부를 비웁니다. 다음 배치의 프롬프트는 현재 배치가 학습되는 동안 인코딩되므로, 프로세서가 카드를 따라가는 한 비용이 들지 않습니다.",
  "The row above makes the text encoder smaller; this one takes it off the graphics card altogether. Its weights stay in ordinary system memory and each prompt is turned into an embedding there, so the encoder occupies no VRAM at all — where quantizing it leaves roughly a third of it resident.\n\nMeasured on an RTX 5070 Ti at 4-bit, this takes Chroma from 9.6 GB to 5.3 and FLUX.1 from 11.4 to 7.0, which was enough to train FLUX.2 Klein at a resolution that did not previously fit.\n\nWhat it costs is one pass over the encoder per step, on the processor instead of the graphics card — and the next batch's prompt is encoded while the current one trains, so the card only waits where the processor is slower than a whole step. Measured on a 16-core desktop, T5-XXL takes about 1.3 seconds a prompt: a 1024-pixel step on an RTX 5090 hides that entirely, a 512-pixel step (half a second) does not. It cannot be combined with training the text encoder, which would mean doing that training on the processor.":
    "위의 항목은 텍스트 인코더를 작게 만들고, 이 항목은 그래픽 카드에서 아예 내립니다. 가중치는 일반 시스템 메모리에 남고 프롬프트도 거기서 임베딩으로 바뀌므로, 인코더가 VRAM을 전혀 쓰지 않습니다—양자화는 약 3분의 1을 남깁니다.\n\nRTX 5070 Ti, 4비트에서 측정한 결과 Chroma는 9.6 GB에서 5.3으로, FLUX.1은 11.4에서 7.0으로 줄어들었고, 이전에는 들어가지 않던 해상도로 FLUX.2 Klein을 학습할 수 있었습니다.\n\n대가는 스텝마다 인코더를 그래픽카드가 아닌 프로세서에서 한 번 통과시키는 것입니다. 다음 배치의 프롬프트는 현재 배치가 학습되는 동안 인코딩되므로, 카드는 프로세서가 스텝 전체보다 느릴 때만 기다립니다. 16코어 데스크톱에서 측정하면 T5-XXL은 프롬프트당 약 1.3초가 걸립니다. RTX 5090에서 1024픽셀 스텝은 이를 완전히 감추지만 512픽셀 스텝(0.5초)은 그렇지 못합니다. 텍스트 인코더 학습과는 함께 쓸 수 없습니다. 그 학습을 프로세서에서 해야 하기 때문입니다.",

  // ---- the METHOD is an adapter, of which LoRA is one kind ----
  "An adapter is a small add-on file layered over the untouched model — fast, low memory, ideal for styles, characters and concepts. Full finetune rewrites the whole model: much more VRAM and data needed, only worth it for broad domain shifts. Which kind of adapter is the next question down.":
    "어댑터는 손대지 않은 모델 위에 얹는 작은 추가 파일입니다. 빠르고 메모리를 적게 쓰며 화풍, 캐릭터, 개념에 알맞습니다. 전체 파인튜닝은 모델 전체를 다시 씁니다. VRAM과 데이터가 훨씬 많이 필요하고, 영역 자체를 크게 옮길 때만 값어치를 합니다. 어떤 종류의 어댑터인지는 바로 아래 항목에서 정합니다.",
  "An adapter leaves the base model untouched and trains a small add-on (a few dozen MB) that is layered on top at generation time. It is quick, fits ordinary hardware, can be mixed with other adapters and dialled up or down by weight — and it is enough for styles, characters, objects and most concepts. There are two kinds, LoRA and LoKr, and the Adapter section below picks between them; LoRA is the one to start with.\n\nA full finetune rewrites every weight of the model. It produces a multi-gigabyte model of its own, needs far more VRAM, far more images and much lower learning rates, and it can forget things it used to know. Reach for it only when you are moving the model into a genuinely different domain, not to teach it one more subject.":
    "어댑터는 베이스 모델을 그대로 두고, 생성할 때 그 위에 얹는 작은 추가 파일(수십 MB)을 학습합니다. 빠르고 평범한 하드웨어에도 들어가며, 다른 어댑터와 섞거나 가중치로 세기를 조절할 수 있고, 화풍·캐릭터·사물과 대부분의 개념에는 이것으로 충분합니다. 종류는 LoRA와 LoKr 두 가지이며 아래 어댑터 섹션에서 고릅니다. 처음에는 LoRA를 쓰세요.\n\n전체 파인튜닝은 모델의 모든 가중치를 다시 씁니다. 수 기가바이트짜리 모델이 따로 만들어지고, VRAM도 이미지도 훨씬 많이 필요하며 학습률은 훨씬 낮아야 하고, 알던 것을 잊어버리기도 합니다. 모델을 정말로 다른 영역으로 옮길 때만 쓰세요. 소재를 하나 더 가르치려고 쓸 것은 아닙니다.",
  "Start from an existing adapter":
    "기존 어댑터에서 시작",
  "A fresh adapter starts from noise and has to learn your concept from nothing. Starting from an existing one keeps everything it already learned and refines it — the usual reasons are adding new images to a concept you trained before, or nudging one that came out almost right.\n\nWeight sets trained on the same base model are offered — including ones trained on another model built on it — and the new job has to match the one it continues: the same adapter type, the same rank, and the same layer targeting. The trainer stops with a message naming what it found otherwise. Picking a job's finished result continues where it ended; picking an intermediate checkpoint rewinds to that point and continues from there.":
    "새 어댑터는 노이즈에서 시작해 개념을 맨바닥부터 배워야 합니다. 기존 어댑터에서 시작하면 이미 배운 것을 모두 유지한 채 다듬을 수 있습니다. 흔한 이유는 전에 학습한 개념에 이미지를 더하거나, 거의 잘 나온 것을 조금 손보는 경우입니다.\n\n같은 베이스 모델로 학습된 가중치가 제시되며 — 그 모델을 바탕으로 만든 다른 모델로 학습한 것도 포함됩니다 — 새 작업은 이어받을 대상과 맞아야 합니다. 같은 어댑터 종류, 같은 랭크, 같은 레이어 지정이어야 하죠. 그렇지 않으면 트레이너가 무엇을 찾았는지 알리고 멈춥니다. 작업의 완료 결과를 고르면 끝난 지점에서 이어지고, 중간 체크포인트를 고르면 그 지점으로 되감아 거기서부터 이어집니다.",
  "Pick a finished adapter":
    "완료된 어댑터 선택",
  "No finished adapter for this base model yet":
    "이 베이스 모델의 완료된 어댑터가 아직 없습니다",
  "Optional: continue training an existing adapter instead of starting from scratch.":
    "선택: 처음부터 시작하는 대신 기존 어댑터의 학습을 계속합니다.",
  "No full finetune":
    "전체 파인튜닝 불가",

  // ---- adapter wording: an adapter is LoRA or LoKr ----
  "The standard choice, and the format every other tool understands — a LoRA can be used anywhere.":
    "표준 선택이며 다른 모든 도구가 이해하는 형식입니다. LoRA는 어디서나 쓸 수 있습니다.",
  "An adapter does not rewrite the model — it adds a small 'side channel' to certain layers, and rank is how wide that channel is: how much new information the adapter can hold.\n\nLow ranks (4–8) are plenty for a style or a colour palette and are very hard to overfit. Mid ranks (16–32) suit characters and objects with consistent details. High ranks (64+) mostly grow the file and the overfitting risk without helping, unless you are teaching a genuinely broad new domain.\n\nIt means slightly different things to the two adapter types. For a LoRA it is the hard ceiling on the change: a rank-16 adapter can only ever make a rank-16 change. For a LoKr it bounds only part of the structure, so a LoKr is not confined the way a LoRA is and its file grows far more slowly as you raise it — which is why the size estimate below is a figure for LoRA and a comparison for LoKr.":
    "어댑터는 모델을 다시 쓰지 않습니다. 특정 레이어에 작은 '옆길'을 덧붙일 뿐이고, 랭크는 그 길의 너비 — 즉 어댑터가 담을 수 있는 새 정보의 양입니다.\n\n낮은 랭크(4–8)는 화풍이나 색 팔레트에 충분하고 과적합도 거의 없습니다. 중간(16–32)은 세부가 일정한 캐릭터와 사물에 알맞습니다. 높은 랭크(64+)는 정말 넓은 새 영역을 가르치는 게 아니라면 대개 파일 크기와 과적합 위험만 키웁니다.\n\n두 어댑터 종류에서 뜻이 조금 다릅니다. LoRA에서는 변화의 단단한 상한이라 랭크 16짜리는 랭크 16의 변화만 만들 수 있습니다. LoKr에서는 구조의 일부만 제한하므로 LoRA처럼 갇히지 않고, 올려도 파일이 훨씬 천천히 커집니다. 아래 크기 안내가 LoRA는 수치, LoKr은 비교인 이유입니다.",
  "The adapter's output is multiplied by alpha ÷ rank before being added to the model, so alpha sets how loudly the adapter speaks at a given capacity. It works the same way for both adapter types.\n\nThe usual convention is alpha = rank, which makes the scale factor 1 and keeps behaviour comparable when you change rank. Setting alpha to half the rank is a common way to soften an adapter that comes out too strong. It interacts with the learning rate — halving alpha has a similar effect to halving the rate — so change one at a time.":
    "어댑터의 출력은 모델에 더해지기 전에 alpha ÷ 랭크가 곱해집니다. 즉 alpha는 주어진 용량에서 어댑터가 얼마나 크게 말하는지를 정합니다. 두 어댑터 종류에서 똑같이 작동합니다.\n\n관행은 alpha = 랭크이며, 그러면 계수가 1이 되어 랭크를 바꿔도 동작을 비교하기 쉽습니다. alpha를 랭크의 절반으로 두는 것은 너무 센 어댑터를 누그러뜨리는 흔한 방법입니다. 학습률과 서로 영향을 주므로(alpha를 반으로 줄이는 것은 학습률을 반으로 줄이는 것과 비슷합니다) 한 번에 하나씩만 바꾸세요.",
  "This architecture can only be trained as an adapter (LoRA or LoKr) alongside the frozen model. The \"Full finetune\" method, which rewrites the model's own weights, is not offered for it.":
    "이 아키텍처는 얼어 있는 모델 옆에 두는 어댑터(LoRA 또는 LoKr)로만 학습할 수 있습니다. 모델 자체의 가중치를 다시 쓰는 ‘전체 파인튜닝’ 방식은 제공되지 않습니다.",
  "No adapters for this base model yet.": "이 기본 모델용 어댑터가 아직 없습니다.",
  "No trained adapters yet.": "학습된 어댑터가 아직 없습니다.",
  "Which adapter this row applies":
    "이 행이 적용하는 어댑터",
  "Adapter strength: 1 = as trained, below weakens, above strengthens (can distort past ~1.5).":
    "어댑터 강도: 1 = 학습된 그대로, 아래는 약화, 위는 강화 (~1.5를 넘으면 왜곡될 수 있음).",
  "Add adapter":
    "어댑터 추가",
  "Adapters":
    "어댑터",
  "Finetune": "파인튜닝",
  "Generate with a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.":
    "베이스 모델의 가중치 대신 전체 파인튜닝의 가중치로 생성합니다. 어댑터는 여기서 고른 것 위에 쌓입니다.",
  "none — the base model": "없음 — 베이스 모델",
  "loading finetune": "파인튜닝 로드 중",
  "Stack trained adapters on the base model, each with its own strength — LoRA or LoKr. An adapter fits the model it was trained on and any other built on the same one.":
    "학습된 어댑터를 각자 강도와 함께 베이스 모델 위에 쌓습니다 — LoRA든 LoKr든. 어댑터는 학습에 사용한 모델과 같은 모델을 바탕으로 만든 다른 모델에도 맞습니다.",
  "Generated images appear here — try out a trained adapter against its base model.":
    "생성된 이미지가 여기에 나타납니다. 학습한 어댑터를 베이스 모델과 견주어 보세요.",
  "A much smaller file, and not limited by the rank the way a LoRA is. Whether it can be used outside this app depends on the model — see the ⓘ.":
    "파일이 훨씬 작고 LoRA처럼 랭크에 묶이지도 않습니다. 이 앱 밖에서 쓸 수 있는지는 모델에 따라 다릅니다 — ⓘ를 보세요.",
  "Both add a small trainable layer over the frozen model; they differ in the shape of change they can express.\n\nA LoRA adds a 'low-rank' change: two thin matrices whose product is added to each targeted weight. Its capacity is exactly its rank — a rank-16 adapter can only ever make a rank-16 change, however long you train it. That is ample for a character, an object, a colour palette. It trains a little faster, it is the format every tool reads, and it carries better between related checkpoints: a LoRA trained on one finetune of a model usually still works on another.\n\nLoKr builds the change as a Kronecker product of two much smaller matrices instead. The saving comes from that structure rather than from throwing rank away, so the change is not confined to a thin slice of the weight while the file stays a small fraction of a LoRA's — under a tenth of the trainable parameters at rank 8. LyCORIS, whose method this is, suggests reaching for it when a LoRA 'does not learn well enough', and it is generally the better fit for styles and broad visual qualities, where a LoRA's rank ceiling is what you meet first. Its own caveats are the mirror image: slightly slower to train, and a very small LoKr transfers less well if you later swap the base model for a different finetune.\n\nWhat each can be USED by differs, and it is the file rather than the method. A LoRA is written in the layout every tool reads. A LoKr cannot be: that layout has a place for two matrices and nowhere to put a Kronecker factor. What it gets instead is a copy named the way ComfyUI names LoKr layers, and that works for the models whose layers ComfyUI addresses that way — FLUX.1, FLUX.1 Kontext and the Qwen-Image releases. On the others (SD 1.5, SDXL, Chroma, FLUX.2, Z-Image) a LoKr stays here: it works in the Evaluate tab and as the starting point of another job, but there is no file to hand over. On those, pick LoRA if the result has to leave this app.":
    "둘 다 고정된 모델 위에 작은 학습 가능 계층을 얹습니다. 차이는 어떤 형태의 변화를 표현할 수 있는가입니다.\n\nLoRA는 ‘저랭크’ 변화를 더합니다. 얇은 행렬 두 개의 곱을 대상 가중치마다 더하는 방식입니다. 용량은 정확히 랭크만큼이어서, 랭크 16 어댑터는 아무리 오래 학습해도 랭크 16짜리 변화만 만들 수 있습니다. 캐릭터, 사물, 색 팔레트에는 충분합니다. 학습이 조금 더 빠르고, 모든 도구가 읽는 형식이며, 친척뻘 체크포인트 사이에서도 잘 옮겨 갑니다. 어떤 파인튜닝에서 학습한 LoRA가 대개 다른 파인튜닝에서도 작동합니다.\n\nLoKr는 대신 훨씬 작은 행렬 두 개의 크로네커 곱으로 변화를 구성합니다. 절약은 랭크를 버려서가 아니라 그 구조에서 나오므로, 변화가 가중치의 얇은 조각에 갇히지 않으면서도 파일은 LoRA의 일부에 그칩니다. 랭크 8에서 학습 파라미터의 10분의 1 미만입니다. 이 방식을 만든 LyCORIS는 LoRA가 ‘충분히 학습하지 못할 때’ 써 보라고 권하며, LoRA의 랭크 한계에 먼저 부딪히는 화풍이나 폭넓은 시각적 성질에 대체로 더 맞습니다. 반대편의 단점도 있습니다. 학습이 조금 느리고, 아주 작은 LoKr는 나중에 베이스 모델을 다른 파인튜닝으로 바꾸면 잘 옮겨 가지 않습니다.\n\n각각을 어디에 쓸 수 있는지는 다르며, 그것은 방식이 아니라 파일의 문제입니다. LoRA는 모든 도구가 읽는 형식으로 저장됩니다. LoKr는 그럴 수 없습니다. 그 형식에는 행렬 두 개 자리는 있어도 크로네커 인자를 둘 자리가 없기 때문입니다. 대신 ComfyUI가 LoKr 계층을 부르는 방식으로 이름을 붙인 사본이 저장되며, ComfyUI가 그렇게 계층을 지칭하는 모델 — FLUX.1, FLUX.1 Kontext, Qwen-Image 계열 — 에서는 그대로 쓸 수 있습니다. 나머지(SD 1.5, SDXL, Chroma, FLUX.2, Z-Image)에서는 LoKr가 여기에 머뭅니다. Evaluate 탭과 다른 작업의 출발점으로는 쓸 수 있지만 건네줄 파일은 없습니다. 그런 모델에서는 결과물을 밖으로 내보내야 한다면 LoRA를 고르세요.",
  "LoKr expresses a weight's change as one small matrix combined with another. This number decides where the weight is cut into those two parts.\n\nLeft empty, the split is chosen to make the two parts as close to square as possible, which is where they are SMALLEST. Moving it either way grows the file, and the two directions are not the same thing: a low factor (4–8) pushes the weight into the second part, which is where the adapter's capacity is — that is the LyCORIS recipe for a LoKr that is not learning enough. A factor far above the square split grows the first, dense part instead, which costs size for nothing.\n\nMeasured on a 1280-wide layer at rank 8, against the same layer's LoRA: automatic 0.08x, factor 8 0.13x, factor 4 0.25x, factor 128 0.81x.\n\nThere is rarely a reason to set it. If a LoKr adapter is not learning enough, raise the rank first, then try a low factor.":
    "LoKr는 가중치의 변화를 작은 행렬 하나와 또 다른 행렬의 조합으로 표현합니다. 이 숫자는 가중치를 그 두 부분으로 어디서 자를지 정합니다.\n\n비워 두면 두 부분이 최대한 정사각형에 가깝도록 자르며, 그 지점이 가장 작습니다. 어느 쪽으로 움직여도 파일은 커지는데, 두 방향의 의미는 다릅니다. 낮은 인자(4–8)는 가중치를 두 번째 부분, 즉 어댑터의 용량이 있는 쪽으로 밀어 줍니다. 충분히 학습하지 못하는 LoKr에 대한 LyCORIS의 처방이 바로 이것입니다. 정사각 분할보다 훨씬 큰 인자는 대신 촘촘한 첫 번째 부분을 키워, 크기만 쓰고 얻는 것이 없습니다.\n\n너비 1280 계층, 랭크 8에서 같은 계층의 LoRA와 비교해 측정: 자동 0.08배, 인자 8은 0.13배, 인자 4는 0.25배, 인자 128은 0.81배.\n\n굳이 설정할 이유는 드뭅니다. LoKr가 충분히 학습하지 못하면 먼저 랭크를 올리고, 그다음 낮은 인자를 시도하세요.",
  "Every picture this finds is also matched by a training query, so it contributes nothing and the run will not be regularized. Narrow it to pictures the run is NOT about.":
    "여기서 찾는 이미지는 모두 학습 쿼리에도 걸리므로 이 풀은 아무것도 기여하지 않고, 실행은 정규화되지 않습니다. 이 실행의 대상이 '아닌' 이미지로 좁히세요.",
  "val": "검증",
  "stable": "안정",
  "validation": "검증",
  "Validate": "검증",
  "Masked regions": "마스크 영역",
  "Mask out regions tagged": "영역을 마스크할 태그",
  "Comma-separated tags whose bounding boxes are largely ignored by the loss — e.g. 'watermark'. The picture still trains; the region inside the boxes stops teaching. Tags without boxes on an image mask nothing there.": "쉼표로 구분한 태그. 그 경계 박스 안은 손실에서 거의 무시됩니다 — 예: 'watermark'. 사진 자체는 계속 학습하고, 박스 안의 영역만 가르치기를 멈춥니다. 박스가 없는 태그는 그 사진에서 아무것도 마스크하지 않습니다.",
  "Mask out regions of tags marked": "표시된 태그의 영역 마스크",
  "Comma-separated META tags. Any tag the library marks with one of these has its boxes masked — so the rule is stated once in the Tags tab rather than listed here.": "쉼표로 구분한 메타 태그. 라이브러리가 이렇게 표시한 태그는 박스가 마스크됩니다. 규칙을 여기에 나열하는 대신 태그 탭에서 한 번만 밝히는 것입니다.",
  "Masked region weight": "마스크 영역 가중치",
  "How much a masked region still counts. 0 hides it from training entirely; 1 is the same as not masking.": "마스크된 영역이 아직 얼마나 반영되는지. 0은 학습에서 완전히 숨기고, 1은 마스크하지 않는 것과 같습니다.",
  "Validation": "검증",
  "Score a validation loss": "검증 손실 측정",
  "A few images are held out of training and re-scored on a fixed seed as the run goes. Falling: still learning. Rising while the training loss falls: memorizing — pick an earlier checkpoint.": "몇 장의 이미지를 학습에서 빼 두고 고정 시드로 주기적으로 다시 채점합니다. 내려가면 아직 배우는 중. 학습 손실이 내려가는데 올라가면 암기 중 — 더 이른 체크포인트를 고르세요.",
  "Validate every": "검증 주기",
  "Each round costs one forward pass per scored image — a small set every few hundred steps is barely noticeable.": "한 라운드는 채점 이미지당 순전파 한 번입니다 — 몇백 스텝마다 작은 세트라면 거의 티가 나지 않습니다.",
  "Held-out images": "홀드아웃 이미지",
  "Taken OUT of training entirely and scored each round. Capped at half the dataset; 16 is plenty for a LoRA-sized run. 0 turns the held-out series off.": "학습에서 완전히 빼고 매 라운드 채점합니다. 데이터셋의 절반이 상한이며, LoRA 규모라면 16장이면 충분합니다. 0은 이 계열을 끕니다.",
  "Stable-loss images": "안정 손실 이미지",
  "Ordinary TRAINING images re-scored the same fixed way — the training curve without its sampling noise. They stay in training; 0 turns the series off.": "보통의 학습 이미지를 같은 고정 방식으로 다시 채점한 것 — 샘플링 노이즈를 걷어낸 학습 곡선입니다. 이들은 학습에 남습니다. 0은 계열을 끕니다.",
  "Some pictures are worth training on except for one rectangle: a watermark, a shop’s caption strip, a censor bar. Left alone, the model learns the rectangle along with the picture — a run over watermarked photographs reliably teaches the watermark. Throwing those pictures out costs the dataset; this keeps them and hides the rectangle from training instead.\n\nThe regions come from the boxes already on the tag: draw a box for `watermark` in the annotator (or let the watermark detector’s tag carry one), name the tag here, and every image carrying such a box trains with the loss inside it turned down. Where a subject tag has no drawn box, its detected faces stand in, exactly as they do for crop-aware training. An image whose named tags have no boxes trains completely normally — nothing is masked there.\n\nOnly the LOSS is masked. The pixels still pass through the image encoder, so the cached latents are the ordinary ones shared with unmasked runs, and nothing is re-encoded when this setting changes. The mask lives in latent space, where one cell covers 8×8 pixels rounded outward to whole cells — so it cannot hide anything much thinner than that, and a pixel-accurate outline is not something it can promise. It also cannot conjure what is UNDER the watermark: the model simply receives no signal about that area, from this picture.\n\nPairs naturally with a tag the prompt always includes (Always include under Tag selection): the prompt says the watermark is there, the mask stops the pixels teaching it, and at generation time the model has no reason to produce one unprompted.": "어떤 사진은 직사각형 하나만 빼면 학습할 가치가 있습니다. 워터마크, 상점의 캡션 띠, 검열 바 같은 것들입니다. 그대로 두면 모델은 사진과 함께 그 직사각형을 배웁니다 — 워터마크 사진으로 돌린 학습은 어김없이 워터마크를 가르칩니다. 그 사진들을 버리면 데이터셋이 줄어듭니다. 이 설정은 사진을 지키고 대신 직사각형을 학습에서 숨깁니다.\n\n영역은 태그에 이미 있는 박스에서 옵니다. 어노테이터에서 `watermark`에 박스를 그리거나(워터마크 감지기의 태그가 하나 갖게 하거나) 그 태그를 여기에 적으면, 그런 박스를 가진 모든 이미지는 박스 안의 손실을 낮춰 학습합니다. 인물 태그에 그린 박스가 없으면 감지된 얼굴이 대신합니다 — 크롭 인식 학습과 정확히 같은 방식입니다. 지목한 태그에 박스가 없는 이미지는 완전히 평범하게 학습하며, 거기서는 아무것도 마스크되지 않습니다.\n\n마스크되는 것은 손실뿐입니다. 픽셀은 여전히 이미지 인코더를 지나가므로, 캐시된 잠재 표현은 마스크 없는 학습과 공유되는 보통의 것이고, 이 설정을 바꿔도 다시 인코딩되지 않습니다. 마스크는 잠재 공간에 있고, 한 셀이 8×8픽셀을 덮으며 바깥쪽으로 셀 단위로 반올림됩니다 — 그보다 훨씬 가는 것은 숨길 수 없고, 픽셀 단위 윤곽은 약속할 수 없습니다. 워터마크 아래 무엇이 있는지 만들어 내지도 못합니다. 모델은 이 사진에서 그 영역에 대한 신호를 그냥 받지 않을 뿐입니다.\n\n프롬프트에 항상 들어가는 태그(태그 선택의 '항상 포함')와 자연스럽게 짝을 이룹니다. 프롬프트는 워터마크가 있다고 말하고, 마스크는 픽셀이 그것을 가르치지 못하게 막으며, 생성할 때 모델은 시키지도 않은 워터마크를 그릴 이유가 없어집니다.",
  "The same rule, stated once in the library instead of tag by tag here. A meta tag put on the tags whose boxes should never teach — `masked`, say — covers every such tag at once, including ones created after this job was written.\n\nThe list is resolved to tag names when the dataset is built, so the job’s log says how many images actually carried a masked region. A run where that line says zero has a rule pointing at tags nobody drew boxes for.": "같은 규칙을 여기서 태그 하나하나 적는 대신 라이브러리에서 한 번만 말합니다. 박스가 가르치면 안 되는 태그들에 메타 태그 — 예컨대 `masked` — 를 붙이면, 이 작업을 만든 뒤 생긴 태그까지 그런 태그 전부를 한 번에 덮습니다.\n\n목록은 데이터셋을 만들 때 태그 이름으로 풀리므로, 작업 로그에 실제로 마스크 영역을 가진 이미지 수가 적힙니다. 그 줄이 0이라면, 아무도 박스를 그리지 않은 태그를 가리키는 규칙입니다.",
  "What a cell inside a masked box still counts for. 0 hides the region entirely, which is the usual choice for a watermark — there is nothing in it worth a whisper. A small value (0.05–0.2) keeps a faint signal, which can be worth it when the boxes are generous and cover real picture around the thing being hidden.\n\n1 is the unmasked loss, so setting it there is the same as clearing the tag lists. Where an image also trains with an alpha mask, the two multiply: a masked region on a transparent background is doubly not the picture.": "마스크된 박스 안 셀이 아직 얼마나 반영되는지. 0은 영역을 완전히 숨깁니다 — 워터마크라면 보통 이 선택이고, 속삭임만큼의 가치도 없습니다. 작은 값(0.05–0.2)은 희미한 신호를 남기며, 박스가 넉넉해서 숨기려는 것 주변의 진짜 그림까지 덮을 때 가치가 있습니다.\n\n1은 마스크 없는 손실이므로, 거기에 두는 것은 태그 목록을 비우는 것과 같습니다. 이미지가 알파 마스크로도 학습하면 둘은 곱해집니다. 투명한 배경 위의 마스크 영역은 이중으로 '그림이 아니기' 때문입니다.",
  "The training loss cannot answer the question people ask of it. It is drawn from the pictures being trained on, at a different random noise level every step, so it is noisy by construction — and it keeps falling for as long as the model memorizes, which means it looks healthiest exactly when a run has gone on too long.\n\nThis scores two extra series that can answer it, both with the plain per-sample loss on a fixed seed, so every round asks the model exactly the same questions and the number moves only when the model does. The series appear as their own lines on the loss graph, and each round is a line in the job’s log.\n\nReading it: the validation loss falls while the model generalizes and flattens or turns when it starts memorizing — the turning point is roughly where to stop, and with step snapshots on, the checkpoint to pick. Expect it to sit above the training loss and to move in small amounts; what matters is the direction, not the level. It stays comparable across pauses, resumes and step extensions, because the scored images and the seed never change within a job.": "학습 손실은 사람들이 묻는 질문에 답하지 못합니다. 학습 중인 사진에서, 매 스텝 다른 무작위 노이즈 수준으로 뽑히기에 태생적으로 노이즈가 많고 — 모델이 암기하는 동안에도 계속 내려가므로, 너무 오래 돌린 학습일수록 가장 건강해 보입니다.\n\n이 설정은 그 질문에 답할 수 있는 두 계열을 추가로 채점합니다. 둘 다 고정 시드에서 가중치 없는 손실이라, 매 라운드 모델에게 정확히 같은 질문을 던지고 숫자는 모델이 움직일 때만 움직입니다. 계열은 손실 그래프에 별도의 선으로 나타나고, 각 라운드는 작업 로그의 한 줄이 됩니다.\n\n읽는 법: 검증 손실은 모델이 일반화하는 동안 내려가고, 암기가 시작되면 평평해지거나 방향을 바꿉니다 — 그 전환점이 대략 멈출 지점이고, 스텝 스냅샷이 켜져 있다면 고를 체크포인트입니다. 학습 손실보다 위에 있고 작은 폭으로 움직이는 것이 정상이며, 중요한 것은 방향이지 수준이 아닙니다. 채점 이미지와 시드는 작업 안에서 바뀌지 않으므로, 일시정지·재개·스텝 연장을 거쳐도 비교할 수 있습니다.",
  "How often a round runs, in steps. A round costs one forward pass per scored image — no gradients, no optimizer — so a 16-image set is a few seconds; matching the sample or checkpoint cadence keeps the graph, the images and the snapshots telling one story at the same steps.\n\nVery frequent rounds buy little: overfitting announces itself over hundreds of steps, not five.": "몇 스텝마다 한 라운드를 돌릴지. 한 라운드는 채점 이미지당 순전파 한 번 — 기울기도 옵티마이저도 없음 — 이라 16장 세트는 몇 초면 끝납니다. 샘플이나 체크포인트 주기에 맞추면 그래프, 이미지, 스냅샷이 같은 스텝에서 하나의 이야기를 들려줍니다.\n\n아주 잦은 라운드는 얻는 게 거의 없습니다. 과적합은 다섯 스텝이 아니라 수백 스텝에 걸쳐 모습을 드러냅니다.",
  "How many images are set aside for the validation loss. They are taken OUT of training entirely — never visited, in no pool, their captions never seen — because a loss over pictures the model is also memorizing measures nothing. The pick is random but fixed per job, whole images at a time (a picture cannot be half in training), regularization pools are not eligible, and it is capped at half the dataset so the setting can never eat the run it protects.\n\nMore images make a steadier line at a linearly higher cost per round. On a small dataset every held-out image is also a training image lost, which is the real price — 8–16 is usually enough to see the turn, and the job’s log says exactly how many were held out.": "검증 손실을 위해 몇 장을 빼 둘지. 이들은 학습에서 완전히 빠집니다 — 한 번도 방문되지 않고, 어떤 풀에도 없고, 캡션도 보이지 않습니다. 모델이 동시에 암기 중인 사진에 대한 손실은 아무것도 재지 못하기 때문입니다. 선택은 무작위지만 작업마다 고정이고, 항상 이미지 단위이며(사진이 반만 학습에 있을 수는 없습니다), 정규화 풀은 대상이 아니고, 설정이 지켜야 할 학습을 먹어치우지 않도록 데이터셋의 절반이 상한입니다.\n\n이미지가 많을수록 선은 안정되지만 라운드당 비용이 선형으로 늘어납니다. 작은 데이터셋에서는 빼 둔 한 장이 잃어버린 학습 이미지 한 장이기도 하며, 그것이 진짜 대가입니다 — 전환을 보는 데는 보통 8–16장이면 충분하고, 몇 장을 뺐는지는 작업 로그에 정확히 적힙니다.",
  "A second series over ordinary TRAINING images: a fixed slice, re-scored with the same fixed seed each round. Nothing is held out — these stay in training — so it costs no data at all.\n\nWhat it shows is the training curve with the sampling noise removed. The per-step loss jumps around because every step draws different pictures at different noise levels; this line asks the same pictures at the same noise every time, so it is readable where the raw curve is a cloud. Compared against the held-out line it also localizes trouble: both falling is learning, stable falling while held-out rises is memorizing, and neither falling means the run is not learning at all.": "보통의 학습 이미지에 대한 두 번째 계열입니다. 고정된 일부를 매 라운드 같은 고정 시드로 다시 채점합니다. 아무것도 빼 두지 않으므로 — 이들은 학습에 남습니다 — 데이터 비용이 전혀 없습니다.\n\n보여주는 것은 샘플링 노이즈를 걷어낸 학습 곡선입니다. 스텝별 손실이 요동치는 것은 매 스텝 다른 사진을 다른 노이즈 수준에서 뽑기 때문입니다. 이 선은 매번 같은 사진에 같은 질문을 던지므로, 날것의 곡선이 구름일 때도 읽힙니다. 홀드아웃 선과 비교하면 문제의 위치도 짚어 줍니다. 둘 다 내려가면 배우는 중, 안정 선은 내려가는데 홀드아웃 선이 올라가면 암기 중, 어느 쪽도 내려가지 않으면 학습이 전혀 되지 않는 것입니다.",
  "Save the current rules, or load a saved set": "현재 규칙을 저장하거나 저장된 세트를 불러오기",
  "Rule sets": "규칙 세트",
  "Remember the current rules — name the set in this list afterwards": "현재 규칙을 기억 — 이후 이 목록에서 세트 이름을 지정하세요",
  "Add a rule first": "먼저 규칙을 추가하세요",
  "Save current rules": "현재 규칙 저장",
  "Add this set's rules to the job — rows it already has stay put": "이 세트의 규칙을 작업에 추가 — 이미 있는 행은 그대로 둡니다",
  "Value rules": "값 규칙",
  "Turn numeric value tags (height:172cm) into words at prompt time. The first matching rule wins — drag rows to reorder.": "숫자 값 태그(height:172cm)를 프롬프트 작성 시 단어로 바꿉니다. 처음 일치한 규칙이 이깁니다 — 행을 드래그해 순서를 바꾸세요.",
  "namespace, e.g. height": "네임스페이스, 예: height",
  "Keep the raw tag in the prompt beside the rule's text": "원시 태그를 규칙의 텍스트 옆에 프롬프트에 유지",
  "keep tag": "태그 유지",
  "Remove this rule": "이 규칙 제거",
  "Add rule": "규칙 추가",
  "Any tag shaped `<name>:<number><unit>` is a value tag — `people:3`, `height:172cm`, `height:1.72m`, or a ranking’s own `quality:7` — and a rule here turns a range of those numbers into words at prompt time: where `height` is greater than 190cm, write `tall`. A raw `height:172cm` token teaches a text encoder nothing it can read back at generation time; a word does.\n\nA matching tag is replaced by the rule’s text, and a per-rule toggle keeps the raw tag alongside for whoever wants both spellings in the prompt. The metric length and mass families convert, so one rule covers `172cm` and `1.72m` alike; an unknown unit compares only against the same unit, and a plain number only against plain numbers.\n\nRanges may overlap, and the first matching rule wins — the rows are dragged into order, and that order is part of the configuration. A value tag no rule matches passes through the prompt unchanged, so nothing is dropped silently. The rule’s phrase rides the ordinary random pick and dropout like the tag it replaced: prompts sometimes carry it and sometimes do not, which is exactly the variation score-tag conditioning wants.\n\nThe rules are resolved when the dataset is built — the job’s log says how many tags they matched — and a set of rules can be saved and loaded by name, so a house vocabulary is written once and reused across jobs. Loading a set adds its missing rules to the job rather than replacing the rows already there.": "`<이름>:<숫자><단위>` 형태의 태그는 값 태그입니다 — `people:3`, `height:172cm`, `height:1.72m`, 랭킹 자신의 `quality:7`도 마찬가지 — 그리고 여기의 규칙은 프롬프트 작성 시 그 숫자 범위를 단어로 바꿉니다: `height`가 190cm보다 크면 `tall`이라고 쓰는 식입니다. 원시 `height:172cm` 토큰은 텍스트 인코더가 생성 시 읽어낼 수 있는 것을 가르치지 못하지만, 단어는 가르칩니다.\n\n일치하는 태그는 규칙의 텍스트로 대체되며, 규칙별 스위치로 원시 태그를 옆에 함께 둘 수도 있습니다. 미터법 길이와 질량 계열은 환산되므로 하나의 규칙이 `172cm`와 `1.72m`를 똑같이 다룹니다. 알 수 없는 단위는 같은 단위끼리만, 단위 없는 숫자는 단위 없는 숫자끼리만 비교됩니다.\n\n범위는 겹쳐도 되고, 처음 일치한 규칙이 이깁니다 — 행은 드래그로 순서를 바꾸며 그 순서는 설정의 일부입니다. 어떤 규칙에도 맞지 않는 값 태그는 그대로 프롬프트에 남아, 아무것도 조용히 버려지지 않습니다. 규칙의 문구는 대체한 태그처럼 평범한 무작위 선택과 드롭아웃을 따릅니다: 프롬프트에 실릴 때도 아닐 때도 있으며, 그것이 점수 태그 조건화가 원하는 변주입니다.\n\n규칙은 데이터셋을 만들 때 해석되고 — 작업 로그가 몇 개의 태그와 일치했는지 알려줍니다 — 규칙 세트는 이름으로 저장하고 불러올 수 있어, 정해 둔 어휘를 한 번 적어 여러 작업에 재사용합니다. 세트를 불러오면 기존 행을 대체하지 않고 없는 규칙만 추가됩니다.",
  "Write tags as":
    "태그 표기",
  "Their name":
    "이름",
  "Their comment":
    "코멘트",
  "Name and comment":
    "이름과 코멘트",
  "A tag's comment is the one line beside its name in the Tags tab — the same idea in words a text encoder can read. A tag with no comment is written as its name.":
    "태그의 코멘트는 태그 탭에서 이름 옆에 있는 한 줄입니다 — 텍스트 인코더가 읽을 수 있는 말로 쓴 같은 뜻입니다. 코멘트가 없는 태그는 이름으로 씁니다.",
  "A tag's comment is the one line beside its name in the Tags tab — “one girl in the picture” for `1girl`, “from below, looking up at the subject” for `from_below`. A booru vocabulary is compact for the people typing it and opaque to a text encoder; the comment is the same idea in words the encoder can read.\n\n“Their name” is what every run did: the tag as it is spelled. “Their comment” writes the comment in place of the name wherever a picked tag has one, and “Name and comment” writes the name with the comment in brackets after it, so the model learns both spellings of one thing. A tag with no comment is written as its name whatever this says.\n\nOnly the PROMPT changes. Matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all stay keyed on the tag's name, exactly as with aliases — and the comment is read from the library when the dataset is built, so editing a comment later changes the next run, not this one.":
    "태그의 코멘트는 태그 탭에서 이름 옆에 있는 한 줄입니다 — `1girl`은 “그림 속 여자 한 명”, `from_below`는 “아래에서 피사체를 올려다봄”. booru 어휘는 입력하는 사람에게는 간결하지만 텍스트 인코더에게는 불투명합니다. 코멘트는 같은 뜻을 인코더가 읽을 수 있는 말로 옮긴 것입니다.\n\n“이름”은 지금까지 모든 실행이 하던 것, 즉 쓰인 그대로의 태그입니다. “코멘트”는 선택된 태그에 코멘트가 있으면 이름 대신 코멘트를 쓰고, “이름과 코멘트”는 이름 뒤에 괄호로 코멘트를 붙여 모델이 한 가지를 두 가지 표기로 배우게 합니다. 코멘트가 없는 태그는 어떤 설정에서도 이름으로 씁니다.\n\n바뀌는 것은 프롬프트뿐입니다. 매칭, 항상/제외 목록, 빈도 균형, 손실 가중치, 크롭이 담아야 할 상자는 별칭의 경우와 똑같이 모두 태그 이름 기준으로 유지됩니다 — 코멘트는 데이터셋을 만들 때 라이브러리에서 읽으므로, 나중에 코멘트를 바꾸면 이 실행이 아닌 다음 실행이 달라집니다.",
  "Remove the selected images?": "선택한 이미지를 삭제할까요?",
  "They cannot be recovered.": "복구할 수 없습니다.",
  "Delete all {n} results from this session?": "이 세션의 결과 {n}개를 모두 삭제할까요?",
  "The generated images go with them.": "생성된 이미지도 함께 삭제됩니다.",
  "Its downloaded weights can go with it, or stay in the cache for a later download to find.": "다운로드한 가중치를 함께 지우거나, 나중의 다운로드가 찾을 수 있도록 캐시에 남길 수 있습니다.",
  "Remove and delete weights": "제거하고 가중치 삭제",
  "Remove the training job “{name}”?": "학습 작업 “{name}”을(를) 삭제할까요?",
  "Remove {n} training jobs?": "학습 작업 {n}개를 삭제할까요?",
  "Its checkpoints, test samples and trained result are deleted with it — except anything locked, which is kept in the LoRAs list. This cannot be undone.": "체크포인트, 샘플, 학습 결과도 함께 삭제되며 되돌릴 수 없습니다. 잠긴 항목은 LoRA 목록에 남습니다.",
  "Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone.": "체크포인트, 샘플, 학습 결과도 함께 삭제되며 되돌릴 수 없습니다. 잠긴 항목은 LoRA 목록에 남습니다.",
  "The Train tab": "훈련 탭",
  "The Evaluate tab": "평가 탭",
  "The Models tab": "모델 탭",
  "Your models": "내 모델",
  "Finetunes": "파인튜닝",
  "Based on {model}": "{model} 기반",
  "A full finetune of {model}": "{model}의 전체 파인튜닝",
  "The built-in release, one of your own models, or a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.": "기본 제공 릴리스, 내 모델 중 하나, 또는 기본 모델의 가중치 대신 쓸 전체 파인튜닝의 가중치입니다. 어댑터는 여기서 고른 것 위에 쌓입니다.",
};

export default CATALOG;
