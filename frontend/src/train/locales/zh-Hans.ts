// uses live in the APP catalog; this file holds only train-chunk strings.

import type { Catalog } from "../../shared/i18nCore";

const CATALOG: Catalog = {
  "default":
    "默认",
  "This model's own size. A job set to it follows whichever model it is pointed at.":
    "该模型自身的尺寸。设为它的训练会跟随所指向的模型。",
  "{n} px":
    "{n} px",
  "A run trains at one size at least.":
    "一次训练至少需要一个尺寸。",
  "A run trains at up to five sizes — each one is another pass over the dataset per epoch.":
    "一次训练最多使用五个尺寸——每多一个，每轮就要多遍历一次数据集。",
  "e.g. 704":
    "例如 704",
  "Another size…":
    "其他尺寸…",
  "Pick every size this run should train at. A picture joins each one it is big enough for, so the same picture can be learnt at more than one scale — and each size is another pass over the dataset per epoch.":
    "选择这次训练要使用的所有尺寸。每张图片都会加入它足够大的每个尺寸，因此同一张图片会在多个尺度上被学习；每多一个尺寸，每轮就要多遍历一次数据集。",
  "Left empty both fields use the model's own size — a test sample is not tied to the sizes the run trains at.":
    "两项都留空时使用模型自身的尺寸——测试图不受训练尺寸的限制。",
  "The sizes images are trained at, each given as one number that stands for a pixel budget: 1024 means 'about a megapixel', which every aspect-ratio bucket then spends differently — 1024×1024, or 1216×832, or 832×1216.\n\nMatch them to what the base model was trained on (1024 for SDXL, Chroma and FLUX.2, 512 for SD 1.5); training far above that teaches little and costs a lot, while training below it is a genuine speed and memory lever at the price of fine detail. Cost scales with the area, so 768 is nearly half the work per step that 1024 is. The size the list marks as default is the model's own, and a job set to it follows whichever model it is pointed at.\n\nPicking more than one trains the same pictures at each of them. A model that has only ever seen a subject at 1024 has learnt it together with the canvas it was on: asked for something smaller it tends to answer with a crop or a doubled-up version of the same framing. Several sizes separate what the model learns about the subject from what it learns about the shape of the picture.\n\nEach size is a full family of buckets, and every image joins the ones it is large enough for — which is the other half of what this is for. Under Never upscale a 700-pixel scan is simply left out of a 1024 run; add 512 and it trains there instead of being dropped, while the large pictures keep training at both.\n\nIt is not free. A size is another pass over the dataset in every epoch and another cached latent per picture, and the batches at the largest one decide the peak memory — so adding a size above the others raises what the run needs on the card, and adding ones below mainly makes an epoch longer. Two or three an octave apart (512, 768, 1024) is the usual shape; at most five.":
    "训练图片所用的尺寸，每个都以一个代表像素预算的数字给出：1024 表示“约一百万像素”，各个宽高比分桶会以不同方式分配它——1024×1024、1216×832 或 832×1216。\n\n请与基础模型的训练尺寸保持一致（SDXL、Chroma 和 FLUX.2 为 1024，SD 1.5 为 512）；远高于它训练收效甚微而代价高昂，低于它则是以细节为代价换取速度和显存的实际手段。代价与面积成正比，因此 768 每步的工作量几乎只有 1024 的一半。列表中标记为默认的尺寸就是模型自身的尺寸，设为它的训练会跟随所指向的模型。\n\n选择多个尺寸会用同样的图片在每个尺寸上训练。只在 1024 见过某个主体的模型，是连同它所处的画布一起学会的：要求更小的尺寸时，它往往会给出同一构图的裁切版或重复叠加的版本。多个尺寸能把模型关于主体学到的东西，与它关于画面形状学到的东西分开。\n\n每个尺寸都是一整套分桶，每张图片只加入它足够大的那些——这是此设置的另一半用处。开启“从不放大”时，700 像素的扫描件在 1024 的训练中会被直接排除；加入 512 后它会在那里训练而不是被丢弃，大图则继续在两个尺寸上训练。\n\n这并非没有代价。多一个尺寸，就意味着每轮多遍历一次数据集、每张图片多一份缓存的 latent，而显存峰值由最大尺寸的批次决定——因此加入比其他更大的尺寸会抬高显卡需求，而加入更小的则主要是让每轮变长。通常取两三个相隔一个八度的尺寸（512、768、1024）；最多五个。",
  "An image smaller than its bucket has to be enlarged to train at that size, and enlarging invents detail that was never in the picture: soft edges, smeared texture, the interpolation's own look. Trained on, that is what the model learns the subject looks like.\n\nThis is on by default. Those images are left out while the dataset is built — before anything is encoded, so they cost no time and no cache — and the run says how many it dropped. It is asked per resolution, so a picture too small for the largest size still trains at a smaller one rather than being dropped from the run; turn it off for a small dataset, where a slightly soft picture is usually worth more than no picture.":
    "小于所属分桶的图片必须放大才能在该尺寸上训练，而放大会凭空生成图片中从未有过的细节：柔化的边缘、糊掉的纹理、插值本身的观感。用它训练，模型学到的就是主体长这个样子。\n\n此项默认开启。这些图片会在构建数据集时被排除——在任何编码之前，因此既不花时间也不占缓存——并且训练会说明排除了多少张。判断是按分辨率进行的，所以对最大尺寸来说太小的图片仍会在较小的尺寸上训练，而不是被排除在训练之外；数据集较小时请关闭它，那时稍微糊一点的图片通常也比没有图片好。",
  "New training job": "新建训练任务",
  "Drafts": "草稿",
  "Paused": "已暂停",
  "Completed": "已完成",
  "Failed": "已失败",
  "Full finetune": "完整微调",
  "Loss appears here once training starts.": "训练开始后损失会出现在这里。",
  "Test samples": "测试样张",
  "Select a job to see its progress, samples and settings.": "选择一个任务以查看其进度、样张和设置。",
  "No training jobs yet. Create one to fine-tune a model (LoRA or full) on images selected straight from your library.": "还没有训练任务。创建一个，用直接从媒体库选出的图片微调模型（LoRA 或完整）。",
  "Training environment not set up": "训练环境未配置",
  "Edit training job": "编辑训练任务",
  "Save draft": "保存草稿",
  "Save & queue": "保存并排队",
  "Method": "方式",
  "Hyperparameters": "超参数",
  "Memory & speed": "内存与速度",
  "Canceled before any image was generated": "在生成任何图像前被取消",
  "{done} of {total} images": "{total} 张中的 {done} 张",
  "not generated yet": "尚未生成",
  "Download this LoRA": "下载此 LoRA",
  "NVIDIA only": "仅 NVIDIA",
  "Off (fused kernels)": "关闭（融合内核）",
  "On (save VRAM)": "开启（节省显存）",
  "needs an NVIDIA GPU": "需要 NVIDIA GPU",
  "needs an NVIDIA GPU (Ada or newer)": "需要 NVIDIA GPU（Ada 或更新）",
  "this model has none": "此模型没有",
  "8-bit float (fp8)": "8 位浮点 (fp8)",
  "8-bit (int8)": "8 位 (int8)",
  "FLUX.2 Klein (base, 4B)": "FLUX.2 Klein（基础版，4B）",
  "Images are being generated": "正在生成图像",
  "= 1 image": "= 1 张",
  "= {n} images": { other: "= {n} 张" },
  "Length & learning rate": "长度与学习率",
  "Dataset": "数据集",
  "Add query": "添加查询",
  "Remove query": "移除查询",
  "invalid query": "无效查询",
  "Empty query = every image in the library.": "空查询 = 媒体库的每张图。",
  "Total steps": "总步数",
  "Learning rate": "学习率",
  "Batch size": "批次大小",
  "Gradient accumulation": "梯度累积",
  "Rank": "秩",
  "Train text encoder": "训练文本编码器",
  "Checkpoints": "检查点",
  "Checkpoint every": "检查点间隔",
  "Cache latents": "缓存潜变量",
  "Random crop": "随机裁剪",
  "Resolutions":
    "分辨率",
  "Crops & flips":
    "裁剪与翻转",
  "Max aspect ratio": "最大宽高比",
  "Horizontal flip probability": "水平翻转概率",
  "Trigger word": "触发词",
  "Only captions tagged": "仅含以下标签的说明",
  "Skip captions tagged": "跳过含以下标签的说明",
  "Only instructions tagged": "仅含以下标签的指令",
  "Skip instructions tagged": "跳过含以下标签的指令",
  "Comma-separated meta tags whose instructions are never used. Applied after the include list, so it also removes instructions the list let in.": "逗号分隔的元标签，其指令绝不使用。在包含列表之后应用，因此也会移除列表放进来的指令。",
  "Comma-separated meta tags whose captions are never used. Applied after the include list, so it also removes captions the list let in.": "逗号分隔的元标签，其说明绝不使用。在包含列表之后应用，因此也会移除列表放进来的说明。",
  "Always include": "始终包含",
  "Skip tag groups tagged": "跳过含以下标签的标签组",
  "Comma-separated meta tags naming whole tag groups to ignore: a tag placed only in such a group never reaches a prompt. The tags stay on your items.": "逗号分隔的元标签，指名要整个忽略的标签组：只放在这种组里的标签绝不会进入提示词。标签仍留在条目上。",
  "Min tags per prompt": "每条提示词最少标签",
  "Max tags per prompt": "每条提示词最多标签",
  "Pick probability": "抽取概率",
  "Uniform": "均匀",
  "Balance rare tags": "平衡罕见标签",
  "Frequency measured in": "频率统计范围",
  "Training data": "训练数据",
  "Previous step": "上一步",
  "Next step": "下一步",
  "(empty prompt)": "（空提示词）",
  "Show each step's min/max micro-batch loss": "显示每步的最小/最大微批次损失",
  "Expand graph": "展开图表",
  "Collapse graph": "收起图表",
  "steps/s": "步/秒",
  "Smooth the line (EMA)": "平滑曲线 (EMA)",
  "Whole library": "整个媒体库",
  "Weight loss by tag rarity": "按标签稀有度加权损失",
  "Shuffle tag order": "打乱标签顺序",
  "Caption dropout": "说明丢弃",
  "Generate every": "生成间隔",
  "Negative prompt": "负面提示词",
  "Nothing (trigger word only)": "无（仅触发词）",
  "Every prompt is the trigger word and nothing else, so every selected picture is in the run whatever it carries. Tag and caption selection do not apply.": "每个提示词都只是触发词，因此所选图片无论带有什么内容都会参与训练。标签与描述的筛选不适用。",
  "Every prompt would be EMPTY — with no text at all, there is nothing for the model to bind what it sees to. Set a trigger word below.": "每个提示词都会是空的 — 没有任何文本，模型就没有东西可以把所见内容绑定过去。请在下方设置触发词。",
  "Caption + tags": "说明 + 标签",
  "Pause (saves a checkpoint)": "暂停（保存检查点）",
  "{d} trained": "已训练 {d}",
  "Training started": "训练已开始",
  "Training resumed": "训练已恢复",
  "Training paused": "训练已暂停",
  "Training completed": "训练已完成",
  "Training failed": "训练失败",
  "Training canceled": "训练已取消",
  "Baseline before training": "训练前基准",
  "Checkpoint": "检查点",
  "Download checkpoint": "下载检查点",
  "Delete checkpoint": "删除检查点",
  "Delete this checkpoint from disk?": "从磁盘删除此检查点吗？",
  "Extend steps": "延长步数",
  "Edit steps": "编辑步数",
  "Base model": "基础模型",
  "LoRAs": "LoRA",
  "Edit this model": "编辑此模型",
  "Edit model": "编辑模型",
  "Edit LoRA": "编辑 LoRA",
  "Edit this LoRA": "编辑此 LoRA",
  "Unlock": "解锁",
  "Lock": "锁定",
  "Unlock — deleting the job will take this LoRA with it": "解锁 — 删除任务时这个 LoRA 会一并消失",
  "Lock — keeps this LoRA when the job is deleted": "锁定 — 删除任务时保留这个 LoRA",
  "Lock — protects this checkpoint from deletion, from the keep-last rule, and from the job being deleted": "锁定 — 保护此检查点不被删除、不受保留最近 N 个规则影响，也不随任务删除而消失",
  "Add LoRA": "添加 LoRA",
  "Click to use this value for the next generation": "点击把此值用于下次生成",
  "Output": "输出",
  "Size presets": "尺寸预设",
  "Random seed": "随机种子",
  "A new seed is drawn each time you click Generate; the field below shows the seed used for the last generation.": "每次点击生成都会抽取新种子；下面的字段显示上次生成所用的种子。",
  "Remove this generation and its images?": "移除此次生成及其图像吗？",
  "Open the image in a new tab": "在新标签页中打开图片",
  "Remove the selected images? They cannot be recovered.": "删除所选图片？删除后无法恢复。",
  "Remove the selected images (a generation that is still running stays)": "删除所选图片（仍在运行的生成会保留）",
  "Stop the selected generations (the images they have made are kept)": "停止所选生成（已生成的图片会保留）",
  "Put every setting that made this picture into the form": "把生成这张图片的全部设置填入表单",
  "Use all settings": "使用全部设置",
  "Preview the selected image (Space)": "预览所选图片（空格）",
  "Image {i} of {n}": "第 {i} 张，共 {n} 张",
  "Up next": "接下来",
  "Add to the queue": "加入队列",
  "A training job is running": "有训练任务在运行",
  "Drag to change the queue order": "拖动以改变队列顺序",
  "How the drafts below are ordered":
    "下方草稿的排序方式",
  "Newest first":
    "最新优先",
  "Manual order":
    "手动排序",
  "Drag to reorder — or into Up next to queue the job":
    "拖动可重新排序——拖到“接下来”即可加入队列",
  "Remove every finished job, with its checkpoints and samples":
    "删除所有已完成的作业，连同其检查点和样本",
  "Drag into Up next to queue the job": "拖入“接下来”把任务排队",
  "Drop here to put the job on hold.": "放到这里把任务搁置。",
  "Prepare": "准备",
  "Keep the last": "保留最近",
  "When a new snapshot is written the oldest of these is deleted, so the window never grows. A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk. The resumable checkpoint is kept outside this limit and never counts against it.": "写入新快照时其中最旧的会被删除，窗口因此不会增长。LoRA 快照很小（几十 MB），保留十来个毫无压力；完整微调快照是整个模型的大小，两三个就已经是很多磁盘。可恢复的检查点保留在此限制之外，绝不计入。",
  "Also keep one in": "另外每几个保留一个：",
  "A rolling window at the end of the run. 0 keeps none by recency.": "训练末尾的滚动窗口。0 表示不按新旧保留任何快照。",
  "Kept for good, on top of the window above.": "永久保留，在上面的窗口之外。",
  "A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk.": "LoRA 快照很小（几十 MB），保留十来个毫无压力；完整微调快照是整个模型的大小，两三个就已经是很多磁盘。",
  "in 1 step": "1 步后",
  "in {n} steps": { other: "{n} 步后" },
  "Keep as checkpoint": "保留为检查点",
  "Backward": "反向",
  "warmup": "预热",
  "Settings changed": "设置已更改",
  "Dataset changed": "数据集已更改",
  "{n} items added":
    { other: "新增 {n} 个条目" },
  "{n} items removed":
    { other: "移除 {n} 个条目" },
  "Measured over the last steps of this run": "按此次训练最近的步测得",
  "about {d} left": "约剩 {d}",
  "The images this run trains on, sorted into aspect-ratio buckets": "此次训练所用的图像，按宽高比桶分类",
  "{n} images": { other: "{n} 张图" },
  "{n} from video": { other: "其中 {n} 张来自视频" },
  "{n} buckets": { other: "{n} 个桶" },
  "Training job settings": "训练任务设置",
  "Save as new job": "另存为新任务",
  "Hide system statistics": "隐藏系统统计",
  "Show system statistics": "显示系统统计",
  "loading model": "加载模型中",
  "caching latents": "缓存潜变量中",
  "Degradation": "劣化",
  "Add variant": "添加变体",
  "Remove every variant from this job": "移除此任务的所有变体",
  "Remove this variant": "移除此变体",
  "JPEG re-encode": "JPEG 重编码",
  "Video codec (h264 / h265)": "视频编解码器 (h264 / h265)",
  "Resolution loss": "分辨率损失",
  "JPEG": "JPEG",
  "video codec": "视频编解码器",
  "resolution loss": "分辨率损失",
  "Chroma subsampling": "色度子采样",
  "How much color detail is thrown away. 4:2:0 is what almost every real JPEG uses.": "丢掉多少颜色细节。4:2:0 是几乎所有真实 JPEG 所用的。",
  "Codec": "编解码器",
  "CRF": "CRF",
  "The codec's quality number, counting the other way round: HIGHER is worse. Above about 32 a frame visibly falls apart.": "编解码器的质量数字，方向相反：越高越差。超过约 32 时帧会明显崩坏。",
  "Scale": "缩放",
  "Nearest gives the hard, blocky look of a badly upscaled screenshot; bilinear the soft one.": "最近邻给出劣质放大截图那种硬邦邦的块状感；双线性则是柔和的那种。",
  "Bilinear": "双线性",
  "Bicubic": "双三次",
  "Lanczos": "Lanczos",
  "Passes": "遍数",
  "Visits per clean visit": "每次干净访问的访问数",
  "How often this variant is drawn beside the picture it was made from. 0.25 = one degraded visit per four clean ones.": "此变体在其原图旁被抽中的频率。0.25 = 每四次干净访问一次劣化访问。",
  "Cached variations per picture": "每张图的缓存变化数",
  "How many separately-drawn values each picture gets. 1 already spreads the range across the dataset; more spreads it within one picture, and multiplies the cache.": "每张图获得多少个单独抽取的值。1 已经把范围铺满数据集；更多则在单张图内铺开，并成倍增加缓存。",
  "jpeg_artifacts, low_quality": "jpeg_artifacts, low_quality",
  "Always in this sample's prompt: never dropped by the random tag pick, the tag cap, or caption dropout.": "始终在此样本的提示词中：绝不会被随机标签抽取、标签上限或说明丢弃去掉。",
  "Remove tags if present": "如有则移除标签",
  "masterpiece, absurdres": "masterpiece, absurdres",
  "Which pictures": "哪些图片",
  "Only pictures tagged": "仅含以下标签的图片",
  "Never pictures tagged": "绝不含以下标签的图片",
  "Wins over the line above. Use it to leave pictures alone that are already marked as poor.": "优先于上一行。用它来放过已被标记为低质的图片。",
  "The preview failed": "预览失败",
  "Select an item in the library to preview this on.": "在媒体库中选一个条目来预览。",
  "gentlest": "最轻",
  "harshest": "最重",
  "Variants": "变体",
  "Save the current variants, or load a saved set": "保存当前变体，或加载已保存的组",
  "Save current variants": "保存当前变体",
  "Add a variant first": "请先添加一个变体",
  "Load this set, replacing the variants in this job": "加载此组，替换此任务中的变体",
  "Of every 100 visits to a picture this applies to, {clean} are clean and the rest are degraded: {parts}.": "对适用图片的每 100 次访问中，{clean} 次是干净的，其余是劣化的：{parts}。",
  "A variant with a tag filter applies to fewer pictures than the queries select, so its share is of those.": "带标签过滤的变体适用的图片少于查询选中的，因此其份额是相对那些图片的。",
  "About {n} degraded files will be cached.": "将缓存约 {n} 个劣化文件。",
  "Preset": "预设",
  "Presets": "预设",
  "Preset name": "预设名称",
  "Save these settings as a preset, or load one": "把这些设置保存为预设，或加载一个",
  "Save current settings": "保存当前设置",
  "Start new jobs from this preset": "新任务从此预设开始",
  "Delete this preset": "删除此预设",
  "Cosine": "余弦",
  "Base models": "基础模型",
  "1 result": "1 个结果",
  "{n} results": { other: "{n} 个结果" },
  "Session": "会话",
  "No adapters": "无适配器",
  "Delete all {n} results from this session? The generated images go with them.": "删除此会话的全部 {n} 个结果吗？生成的图像会一并删除。",
  "sampling": "采样中",
  "What does this do?": "这是做什么的？",
  "This model's repository is gated: accept its license on the model page and set a Hugging Face access token, or the download will fail.": "此模型的仓库受限：请在模型页面接受许可并设置 Hugging Face 访问令牌，否则下载会失败。",
  "Click to use this prompt for the next generation": "点击把此提示词用于下次生成",
  "(no prompt)": "（无提示词）",
  "Click to use this negative prompt for the next generation": "点击把此负面提示词用于下次生成",
  "Time so far, including loading the model": "迄今用时，含模型加载",
  "Total time, including loading the model": "总用时，含模型加载",
  "Remove from the queue": "从队列移除",
  "Select to copy": "选中以复制",
  "generation failed": "生成失败",
  "Sampler steps": "采样步数",
  "CFG scale": "CFG 比例",
  "This model isn't downloaded yet, and downloads are switched off": "此模型尚未下载，且下载已关闭",
  "Loss": "损失",
  "LoRA only": "仅 LoRA",
  "Native training resolution of these weights. Leave empty for the architecture's own.": "这些权重的原生训练分辨率。留空则用架构自身的。",
  "Includes 1 model you added.": "包含你添加的 1 个模型。",
  "Includes": "包含",
  "models you added.": "个你添加的模型。",
  "Open this model's page on Hugging Face": "在 Hugging Face 上打开此模型的页面",
  "Remove this model": "移除此模型",
  "Based on": "基于",
  "/path/to/model (diffusers folder or .safetensors)": "/path/to/model (diffusers folder or .safetensors)",
  "owner/repo": "owner/repo",
  "Add model": "添加模型",
  "On disk": "在磁盘上",
  "Path missing": "路径缺失",
  "Continue this download where it stopped": "从停止处继续此下载",
  "Partly downloaded": "部分已下载",
  "Discard partial download": "丢弃部分下载",
  "This path no longer exists": "此路径已不存在",
  "Remove from the list (the file is left alone)": "从列表移除（文件不动）",
  "The base model this LoRA was trained for": "此 LoRA 训练时的基础模型",
  "/path/to/lora.safetensors": "/path/to/lora.safetensors",
  "Download this checkpoint": "下载此检查点",
  "Delete this checkpoint from disk": "从磁盘删除此检查点",
  "Relative sampling probability: a weight-2 query's images are drawn twice as often as a weight-1 query's.": "相对采样概率：权重 2 的查询的图像被抽中的频率是权重 1 的两倍。",
  "Steps": "步数",
  "Text encoder": "文本编码器",
  "trained": "已训练",
  "Prompts": "提示词",
  "Samples": "样张",
  "Training log": "训练日志",
  "No output yet.": "还没有输出。",
  "about {v} of GPU memory": "约 {v} 的 GPU 内存",
  "more than this machine's {m}": "超过本机的 {m}",
  "e.g. watercolor style LoRA": "例如 水彩风格 LoRA",
  "Model-specific": "模型专属",
  "Optimization": "优化",
  "LR schedule": "学习率调度",
  "Constant": "常数",
  "Linear decay": "线性衰减",
  "Constant + warmup": "常数 + 预热",
  "Warmup steps": "预热步数",
  "Ramp the learning rate up over the first N steps. Leave empty for no warmup.": "在最初 N 步内把学习率升上来。不预热则留空。",
  "bf16 is the safe modern default. fp32 doubles memory (automatic fallback on Macs without bf16); avoid fp16 for training.": "bf16 是安全的现代默认值。fp32 内存翻倍（无 bf16 的 Mac 上自动回退）；训练请避免 fp16。",
  "Makes sampling, crops and tag picks reproducible.": "让采样、裁剪和标签抽取可复现。",
  "LoRA": "LoRA",
  "Scales the adapter's effect; the common convention is alpha = rank. Lower alpha = weaker influence at the same rank.": "缩放适配器的效果；常见惯例是 alpha = 秩。同秩下更低的 alpha = 更弱的影响。",
  "Helps the model learn a NEW trigger word, at higher overfitting risk. Guarded: it uses a lower learning rate and stops partway through training.": "帮助模型学习新触发词，过拟合风险更高。有防护：它用更低学习率并在训练中途停止。",
  "Text encoder LR": "文本编码器学习率",
  "Left empty: half the main learning rate.": "留空：主学习率的一半。",
  "Stop TE after": "停止 TE 于",
  "Include the large encoder": "包含大型编码器",
  "T5-XXL, the encoder that reads the whole prompt — most of the memory and most of the effect. Unticked, only the small CLIP-L trains: cheap, and what most FLUX LoRA tools mean by training the text encoder.": "T5-XXL，读取整个提示词的编码器——占用大部分显存，也贡献大部分效果。取消勾选后只训练小型的 CLIP-L：开销很低，也是多数 FLUX LoRA 工具所说的“训练文本编码器”。",
  "of total steps": "（占总步数）",
  "Keep step snapshots": "保留步快照",
  "Save a permanent snapshot every N steps, so the best-looking step can be picked afterwards. Off: only the resumable 'last' checkpoint is kept.": "每 N 步保存永久快照，事后可挑出最好看的一步。关闭：只保留可恢复的 'last' 检查点。",
  "Gradient checkpointing": "梯度检查点",
  "Trades ~25% speed for a large VRAM saving. Recommended for full finetunes and big models.": "用约 25% 速度换取大量显存节省。完整微调和大模型推荐开启。",
  "Attention slicing": "注意力切片",
  "Half-precision master weights": "半精度主权重",
  "Keeps the trained weights and their gradients at 16 bits instead of 32. What the rounding drops is carried to the next update, so the run learns what it would have learned; the cost is one more buffer of the same width.":
    "将训练的权重及其梯度以 16 位而非 32 位保存。取整丢掉的部分会累积到下一次更新，因此训练能学到本该学到的东西；代价是多出一个同样宽度的缓冲区。",
  "only for a full finetune": "仅用于完整微调",
  "nothing to halve at full precision": "全精度下没有可减半的内容",
  "Prodigy cannot be stepped one weight at a time": "Prodigy 无法逐个权重执行",
  "Base model quantization": "基础模型量化",
  "None (full precision)": "无（全精度）",
  "4-bit (NF4)": "4 位 (NF4)",
  "Optimizer": "优化器",
  "Images are sorted into width/height buckets of equal area so nothing gets squashed. This caps how extreme the buckets get (2 = up to 2:1 and 1:2).": "图像被分进面积相等的宽/高桶，因此没有东西被压扁。这限制桶能多极端（2 = 最多 2:1 和 1:2）。",
  "Never flip images whose tags are marked": "标签带有以下元标签的图片不翻转",
  "Comma-separated META tags. Any tag the library marks with one of these switches mirroring off for the pictures carrying that tag — so the rule is stated once in the Tags tab rather than listed here.": "以逗号分隔的元标签。库中被这样标记的任何标签，都会为带有该标签的图片关闭镜像——规则在标签页说一次，而不必在这里逐一列出。",
  "Always include tags marked": "始终包含带有以下元标签的标签",
  "Comma-separated META tags. Any tag the library marks with one of these is never dropped by the random pick — again, only where the image actually has that tag.": "以逗号分隔的元标签。库中被这样标记的任何标签都不会被随机挑选丢弃——同样，仅限图片确实带有该标签时。",
  "Exclude tags marked": "排除带有以下元标签的标签",
  "Comma-separated META tags. Any tag the library marks with one of these is stripped from prompts.": "以逗号分隔的元标签。库中被这样标记的任何标签都会从提示词中移除。",
  "Remove tags marked": "移除带有以下元标签的标签",
  "Comma-separated META tags. Any tag the library marks with one of these comes off this sample.": "以逗号分隔的元标签。库中被这样标记的任何标签都会从这份样本中去掉。",
  "Only pictures whose tags are marked": "仅标签带有以下元标签的图片",
  "Comma-separated META tags — the same rule as the line above, said once in the library rather than tag by tag here.": "以逗号分隔的元标签——与上一行相同的规则，在库中说一次，而不是在这里逐个标签列出。",
  "Never pictures whose tags are marked": "标签带有以下元标签的图片一律不用",
  "Comma-separated META tags. Wins over both lines above.": "以逗号分隔的元标签。优先于上面两行。",
  "The same veto, said once in the library instead of tag by tag here. Any tag the Tags tab marks with one of these meta tags switches mirroring off for every picture carrying that tag.\n\nIt is worth the indirection for the reason a list of names goes stale: “text”, “logo”, “signature”, “left-handed”, a dozen characters with an eyepatch — the list in a job's settings is right the day it is written and wrong the next time somebody adds a tag it should have held. Marking the tags themselves puts the fact where the tag is, so a tag added later carries it into every run automatically, and a job written before that tag existed still does the right thing.\n\nBoth lists apply: a picture is left unmirrored if it carries a tag named above OR a tag marked here.":
    "同一条否决，在库里说一次，而不是在这里逐个标签列出。标签页用这些元标签之一标记的任何标签，都会为带有该标签的每张图片关闭镜像。\n\n这层间接之所以值得，原因与名字列表会过时的原因相同：“text”“logo”“signature”“left-handed”，还有十几个戴眼罩的角色——任务设置里的列表在写下的那天是对的，等到有人添加了本该在其中的标签时就不对了。给标签本身做标记，把事实放在标签所在之处：之后新增的标签会自己把它带进每一次训练，而在该标签出现之前写好的任务依然做对了事。\n\n两份列表都生效：图片只要带有上面点名的标签，或者带有这里标记的标签，就不会被镜像。",
  "The rule above, named by what the library says ABOUT a tag rather than by the tag. Any tag marked with one of these meta tags bypasses the random pick — again only where the image actually has it.\n\nA meta tag put on “watermark”, “signature” and “logo” once means every run treats them that way, including runs written before the third of them existed. The two lists are unioned, so naming a tag here and above is simply the same instruction twice.":
    "上面那条规则，按库对某个标签的说明来指定，而不是按标签本身。凡是被这些元标签之一标记的标签都会跳过随机挑选——同样，仅限图片确实带有该标签时。\n\n给“watermark”“signature”“logo”标记一次元标签，就意味着每一次训练都这样对待它们，包括在第三个出现之前写好的训练。两份列表会合并，所以在这里和上面同时写下某个标签，只是把同一条指令说了两遍。",
  "The same, one level up: any tag the library marks with one of these meta tags is stripped from every prompt.\n\nThis is the one to reach for when the exclusions are a KIND of tag rather than a list of them. Quality ratings, scan notes, the booru's own housekeeping words — mark them “noprompt” in the Tags tab and every run drops them, instead of every job carrying a list that has to grow with the vocabulary.\n\nIt is not the same as a skipped tag GROUP below. This one is about the tag wherever it appears; that one is about a grouping on one item, and a tag placed in an excluded group and also somewhere else survives it.":
    "同样的事情，往上一层：凡是库用这些元标签之一标记的标签，都会从每一条提示词中剔除。\n\n当要排除的是一“类”标签而不是一份标签清单时，就该用它。质量评级、扫描备注、booru 自己的管理用词——在标签页把它们标记为“noprompt”，每一次训练都会丢掉它们，而不必让每个任务各自带一份需要随词汇一起增长的清单。\n\n这与下面跳过的标签“组”不是一回事。这里说的是这个标签出现在任何地方；那里说的是某一项上的分组，而同时放在被排除的组和别处的标签会存活下来。",
  "The list above, named by what the library says about a tag. Any tag marked with one of these meta tags comes off this sample.\n\nWhat it is for is that the claims a degraded copy no longer supports are a CATEGORY, not a list: 'masterpiece', 'absurdres', 'high quality', 'official art' and whatever the next dump adds are all \"a claim about the picture's quality\". Marking them once means every variant of every job drops them, and the same mark can then say something different per method — a 'resolution_claim' mark belongs on a resize variant's list, a 'fidelity_claim' on a JPEG one.":
    "上面那份列表，按库对某个标签的说明来指定。凡是被这些元标签之一标记的标签，都会从这份样本中去掉。\n\n它的用处在于：一份劣化副本不再支撑的说法是一“类”，而不是一份清单。“masterpiece”“absurdres”“high quality”“official art”，以及下一批数据会添加的任何词，都是“关于画面质量的说法”。标记一次，每个任务的每个变体都会丢掉它们；而同一个标记还能按方法说出不同的话——“resolution_claim”标记属于缩放变体的列表，“fidelity_claim”属于 JPEG 变体的列表。",
  "The line above by mark rather than by name: a picture is degraded only if it carries a tag the library marks this way.\n\nChecked against the picture's effective tags, so a tag it only carries by implication counts too. With both lists empty, every picture is fair game.":
    "上面那一行，按标记而不是按名字：只有当图片带有库以这种方式标记的标签时，才会被劣化。\n\n检查针对的是图片的有效标签，因此仅凭蕴含才带有的标签同样算数。两份列表都留空时，每张图片都在范围内。",
  "The veto by mark, and it wins over both lines above exactly as the named list does.\n\nThe pair is what makes a degrading run safe on a mixed library: mark the pictures that are already poor — a 'low_quality' or 'rescan' mark on the tags that say so — and no variant can ever degrade one of them further, however broadly the \"only pictures\" side is drawn.":
    "按标记的否决，并且它优先于上面两行，与按名字的那份列表完全一样。\n\n正是这一对让劣化训练在混杂的库上是安全的：给那些本来就质量不佳的图片做上标记——在说明这一点的标签上打“low_quality”或“rescan”——那么无论“仅限图片”那一侧划得多宽，任何变体都不可能把它们再劣化一次。",
  "Never flip images tagged": "绝不翻转含以下标签的图像",
  "Comma-separated tags that switch mirroring off for the images carrying them, e.g. 'text'. Everything else still flips.": "逗号分隔的标签，带有它们的图像关闭镜像，例如 'text'。其余一切照常翻转。",
  "Use alpha as a loss mask": "把 Alpha 用作损失遮罩",
  "For cut-out images (transparent background): train on the visible pixels and largely ignore the rest. Images without transparency are unaffected.": "针对抠图（透明背景）：用可见像素训练，其余大体忽略。无透明度的图像不受影响。",
  "Background weight": "背景权重",
  "Build prompts from": "提示词构建自",
  "What each training prompt is made of: the item's caption text, its tags, caption followed by tags, or nothing but the trigger word.": "每条训练提示词由什么构成：条目的说明文本、它的标签、说明后接标签，或者只有触发词。",
  "Prepended to every prompt. Use a rare token (e.g. 'ohwx style') you'll later type to invoke the trained concept.": "加在每条提示词开头。用一个之后输入以调用所训练概念的罕见词符（例如 'ohwx style'）。",
  "Each image trains as the RESULT of one of its instructions, with that instruction's reference images as the input. Items carrying no instruction are left out of the run, and tag selection does not apply.": "每张图作为其某条指令的结果来训练，以该指令的参考图为输入。没有指令的条目被排除在训练之外，标签选择不适用。",
  "Tag selection": "标签选择",
  "Tags are re-picked and re-shuffled fresh every time an image is visited.": "图像每次被访问时标签都重新抽取、重新打乱。",
  "Comma-separated tags stripped from prompts (e.g. quality tags or the concept itself when using a trigger word).": "从提示词中剔除的逗号分隔标签（例如质量标签，或使用触发词时的概念本身）。",
  "no limit": "无限制",
  "Lower bound of the random pick. Both limits empty = use all tags.": "随机抽取的下限。两个限制都留空 = 使用全部标签。",
  "Upper bound of the random pick. Picking a random subset each visit teaches tags independently instead of as a fixed clump.": "随机抽取的上限。每次访问抽随机子集能独立教授各标签，而不是一整团。",
  "Whether a tag's rarity is measured within the selected training images or across the whole library.": "标签的稀有度是在选中的训练图像内统计，还是在整个媒体库内。",
  "Skip partially matching tags": "跳过部分匹配的标签",
  "Standard practice: prevents the model from binding concepts to a fixed tag position.": "标准做法：防止模型把概念绑定到固定的标签位置。",
  "Underscores to spaces": "下划线转空格",
  "Tag separator": "标签分隔符",
  "Joins the prompt parts; comma + space is the standard.": "连接提示词各部分；逗号 + 空格是标准。",
  "Generate preview images with the in-training model to watch progress in the job's timeline.": "用训练中的模型生成预览图，在任务时间线上观察进度。",
  "Generate test samples": "生成测试样张",
  "Sample seed": "样张种子",
  "Fixed per prompt so consecutive samples differ only by training progress.": "每条提示词固定，让连续样张只因训练进度而不同。",
  "Test prompts": "测试提示词",
  "negative prompt (optional)": "负面提示词（可选）",
  "Use the shared size for this prompt": "此提示词用共享尺寸",
  "Give this prompt its own size": "给此提示词自己的尺寸",
  "Remove this prompt": "移除此提示词",
  "Add prompt": "添加提示词",
  "Remove every prompt from this job": "移除此任务的所有提示词",
  "Remove all": "全部移除",
  "Save the current prompts, or load a saved set": "保存当前提示词，或加载已保存的集合",
  "Write a prompt first": "请先写一条提示词",
  "Save current prompts": "保存当前提示词",
  "Set name": "集合名称",
  "Load this set into the job": "把此集合加载到任务",
  "Delete this set": "删除此集合",
  "train from scratch": "从零训练",
  "Finished result": "完成结果",
  "Intermediate checkpoint": "中间检查点",
  "Continues": "延续",
  "Train on video frames": "用视频帧训练",
  "Off, a video the queries match is skipped. On, its frames are extracted while the dataset is built, trained on as images, and deleted with the run.": "关闭时，查询匹配的视频会被跳过。开启时，其帧在构建数据集时被提取、作为图像训练，并随训练一起删除。",
  "One frame every": "取帧间隔",
  "Interval unit": "间隔单位",
  "Seconds follows the clock whatever the frame rate; frames counts the file's own frames.": "秒跟随时钟，与帧率无关；帧则数文件自身的帧。",
  "Drop repeated frames": "丢弃重复帧",
  "A shot held for five seconds is one picture, not five. Each kept frame is compared with the ones already kept from the same video.": "定格五秒的镜头是一张图，不是五张。每个保留的帧都与同一视频已保留的帧比较。",
  "Label each block with": "每块的标注",
  "The subjects it is about": "它关于的人物",
  "The tag group's name": "标签组的名称",
  "Between groups": "组间",
  "Group tags by tag group": "按标签组归组标签",
  "Lay the picked tags out one block per tag group instead of one flat list, so what belongs to the same thing in the picture stays together.": "把抽中的标签按标签组一块一块排布而不是一条平列表，让图中属于同一事物的内容待在一起。",
  "Put between blocks. A newline by default, which is what makes them read as separate statements.": "放在块之间。默认是换行，正是它让各块读作独立的陈述。",
  "Includes {n} models you added.": { other: "包含你添加的 {n} 个模型。" },
  // The job list's selection bar.
  "Remove {n} training jobs? Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone.":
    "要删除 {n} 个训练任务吗？它们的检查点、样图和训练结果会一并删除，且无法撤销。（已锁定的内容会保留在 LoRA 列表中。）",
  "Remove the selected jobs — a running job is left alone":
    "删除所选任务 — 正在运行的会保留",
  "Remove the selected jobs, with their checkpoints and samples":
    "删除所选任务，连同检查点和样图",
  // The Models page: adding a model, and removing one.
  "Remove “{name}” from the model list?":
    "要把“{name}”从模型列表中移除吗？",
  "Delete the downloaded weights as well? They can be downloaded again later.":
    "同时删除已下载的权重吗？以后可以重新下载。",
  "Which model these weights are a version of — it decides the engine, the hyperparameters and the memory profile":
    "这些权重是哪个模型的版本 — 它决定引擎、超参数和显存特性",
  "owner/repo, or a path on this machine":
    "owner/repo，或本机上的路径",
  "A Hugging Face repository, or a diffusers folder or .safetensors file on this machine — which one it is is read off what you type.":
    "Hugging Face 仓库，或本机上的 diffusers 文件夹或 .safetensors 文件 — 是哪一种由你输入的内容判断。",
  "Read as a path on this machine":
    "按本机路径读取",
  "Read as a Hugging Face repository":
    "按 Hugging Face 仓库读取",
  "Left unnamed, the model is listed under its repository or path":
    "不填名称时，模型按其仓库或路径显示",
  // The Models page's LoRA lists, grouped by architecture.
  "No LoRAs yet — add a file above, or finish a training job.":
    "还没有 LoRA — 在上面添加文件，或完成一次训练。",
  "These work on any model of this architecture. Each row says which one it was trained for.":
    "它们适用于该架构的任何模型。每行会说明它是为哪个模型训练的。",
  // The Evaluate tab: the LoRA rows, and the results grid.
  "Strength":
    "强度",
  "no image":
    "无图像",
  "Weights": "权重",
  "File": "文件",
  "Trained for": "适用模型",
  "defaults to the file name": "默认使用文件名",
  "Waiting…": "等待中…",
  "Another download is running": "另一个下载正在进行",
  "macOS keeps GPU temperature and power for root only. To see them here, allow this one command without a password, then press Try again:":
    "macOS 仅向 root 提供 GPU 温度和功耗。若要在此显示，请允许这一条命令免密码执行，然后点击“重试”：",
  "Check again — no restart needed once the rule is in":
    "重新检查 — 规则生效后无需重启",
  "Copied": "已复制",
  "Press ⌘C to copy it": "按 ⌘C 复制",
  "Write tags as an alias": "将标签写成别名",
  "Chance of writing a picked tag as one of its aliases instead of its own name, rolled per tag every time an image is visited.":
    "把选中的标签写成它的某个别名而非本名的概率，每次访问图像时按标签重新抽取。",
  "Your library's aliases are the other words for one thing — “cat”, “kitty”, “feline”. Assigning any of them stores the canonical name, so every prompt says the same word and the model learns to answer to that word alone; at generation time the others do less, or nothing.\n\nWith this above 0, each picked tag is sometimes written as one of its aliases instead. The roll happens per tag per visit, so one image seen twice reads differently and the whole vocabulary is spread across the run rather than one alias being chosen per tag and then repeated.\n\nOnly the PROMPT changes. Tag matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all keep using the canonical name — so this cannot skew any of them. A tag with no aliases is always written as itself, and 0 is exactly what every run did before this setting existed.":
    "库中的别名是同一事物的其他说法——“cat”“kitty”“feline”。指定其中任何一个，保存的都是规范名，因此每条提示词都是同一个词，模型也就只学会响应那个词；生成时其余的作用很小，甚至没有。\n\n大于 0 时，被选中的标签有时会写成它的某个别名。抽取按标签、按每次访问进行，所以同一张图片两次出现读起来不同，整套词汇会分散在整个训练里，而不是给每个标签选定一个别名后反复使用。\n\n只有提示词会变。标签匹配、始终/排除列表、频率均衡、损失权重，以及裁剪必须保留的框，全都仍使用规范名——因此这不会造成任何偏差。没有别名的标签始终按原样书写，0 就是这个设置出现之前每次训练的行为。",
  "Whether a tag's rarity is measured within the selected training images, across the whole library, or across the whole library plus what each tag has elsewhere.":
    "标签的稀有度是在所选训练图像内衡量、在整个库中衡量，还是在整个库之外再加上每个标签在别处的数量。",
  "Rarity is relative to some population, and this picks which one.\n\n“Training data” counts only the images this job selected, so balancing works within the set you are actually training on — usually what you want. “Whole library” counts every item you own, which makes a tag that is common in your dataset but rare overall still count as rare. That is occasionally useful when the training set is a deliberate slice of a much larger, differently balanced collection.\n\n“Whole library + count offsets” adds each tag’s highest meta-tag count — the pictures it has somewhere this library is not, counted per site on the tag’s meta tags (“tumblr 50”, “twitter 100”), of which the largest single figure is used, never the sum, since the sites count overlapping pictures. Nowhere else in the app is that number added to a count, because a total including it would be a claim about somewhere else; for BALANCING it is often the honest one. A tag with four pictures here and forty thousand where they came from is not a rare word, and treating it as rare spends the run teaching the model something it already knows.":
    "稀有度总是相对于某个总体而言，这里选择的就是那个总体。\n\n“训练数据”只统计本任务选中的图像，因此均衡是在你真正训练的集合内进行的——通常这就是你想要的。“整个库”统计你拥有的一切，于是在数据集中常见、总体上却少见的标签仍算作稀有。当训练集是从一个大得多、分布也不同的收藏中有意切出的一片时，这偶尔很有用。\n\n“整个库 + 别处的数量”会加上每个标签最高的元标签计数——它在这个库之外拥有的图片，按站点记在标签的元标签上（“tumblr 50”、“twitter 100”）；取其中最大的单个数字，绝不求和，因为各站点统计的图片相互重叠。应用中其他任何地方都不会把这个数字加进计数，因为包含它的总数会变成对别处的断言；但用于均衡时，它往往才是诚实的数字。一个在这里只有四张、在其来源处却有四万张的标签并不是稀有词，把它当作稀有，只会让训练把时间花在教模型它早已知道的东西上。",
  "Caption selection": "描述筛选",
  "Instruction selection": "指令筛选",
  "Start now — pauses the running job and puts this one first":
    "立即开始 — 暂停正在运行的任务，并把这个排到最前",
  "Start now — puts this job first and starts the queue":
    "立即开始 — 把这个任务排到最前并启动队列",
  "Save as duplicate":
    "另存为副本",
  "Batch & seed": "批次与种子",
  "Device": "设备",
  "Precision & quantization": "精度与量化",
  "Memory savers": "节省显存",
  "Training images": "训练图像",
  "Length measured in":
    "训练长度的单位",
  "Steps are a fixed amount of work; epochs are full passes over your images, so the run grows with the dataset.":
    "步数是固定的工作量；轮次是把你的图像完整过一遍，因此数据集越大，训练越长。",
  "A STEP is one batch pushed through the model and one update of the weights — a fixed amount of work whatever the dataset holds. An EPOCH is one pass over every training image, so the same number means a longer run on a bigger set and the model sees each picture the same number of times either way.\n\nEpochs are usually the easier thing to reason about: “each image about ten times” transfers between datasets, where “3000 steps” does not. The exact step count is worked out when the run starts, because only then is it known how many entries the dataset has — a film contributes its frames, a degraded copy is an extra sample, and an item can contribute one per caption.":
    "一个步是把一批图像送过模型并更新一次权重——不论数据集有多大，工作量都是固定的。一个轮次是把每张训练图像都过一遍，所以同样的数字在更大的数据集上意味着更长的训练，而两种方式下模型看到每张图的次数是一样的。\n\n轮次通常更好把握：“每张图大约十次”可以从一个数据集搬到另一个，“3000 步”不行。确切的步数在运行开始时才算出，因为那时才知道数据集有多少条目——一部影片会贡献它的帧，一份劣化副本是额外的样本，一个条目还可能按描述数各贡献一条。",
  "Epochs":
    "轮次",
  "Full passes over the dataset. The exact step count is worked out when the run starts and shown in its log.":
    "把数据集完整过多少遍。确切的步数在运行开始时算出，并显示在日志里。",
  "How many times the run works through every training image. Each pass visits every entry exactly once, in a fresh random order.\n\nWhat counts as an entry is the dataset after it has been built, not the number of pictures you selected: a video contributes one entry per kept frame, a degradation variant adds an extra sample beside the clean picture, and with “every caption” an item contributes one entry per caption. That is why the step count appears when the run starts rather than here.":
    "训练把每张图像完整处理多少遍。每一遍都会把每个条目恰好访问一次，顺序每遍重新随机。\n\n这里说的条目是构建完成后的数据集，而不是你挑选的图片数量：一段视频按保留的每一帧各算一个条目，一个劣化变体会在干净图像之外多出一个样本，选“每条描述”时一个条目会按描述数拆开。这也是步数在运行开始时才显示、而不是显示在这里的原因。",
  "Query weight":
    "查询权重",
  "A weight buys":
    "权重换来的是",
  "Whether a heavier query's images are seen more often, or seen the same and counted for more.":
    "权重更高的查询，其图像是被更频繁地看到，还是看到的次数相同但计入得更多。",
  "Both spend the same ratio; they differ in what they spend it on.\n\nSEEN MORE OFTEN is the classic behaviour: a weight-2 query's pictures get twice the visits, which means they take those visits from the rest — a fixed-length run spends more of itself on them and less on everything else.\n\nCOUNTED FOR MORE gives every picture the same number of visits and multiplies the weighted ones' effect on the weights instead. Nothing loses coverage; the emphasis comes out of the gradient rather than out of the other images' training time. It is the better default when the queries are different KINDS of picture rather than different amounts of importance.":
    "两者花掉的比例相同，区别在于花在哪里。\n\n“更常被看到”是经典做法：权重为 2 的查询，其图像获得双倍的访问次数，而这些次数是从其余图像那里拿来的——长度固定的训练会把更多份额花在它们身上，花在其他一切上的就更少。\n\n“计入得更多”让每张图获得同样的访问次数，转而放大被加权图像对权重更新的影响。没有谁的覆盖被削减；强调来自梯度，而不是别的图像的训练时间。当几个查询代表的是不同“种类”的图像、而不是不同程度的重要性时，这是更合适的默认值。",
  "Seen more often":
    "更常被看到",
  "Counted for more":
    "计入得更多",
  "An item with several captions":
    "有多条描述的条目",
  "Whether every caption is used each pass, or one is drawn per visit.":
    "是每一遍都用上每条描述，还是每次访问抽一条。",
  "Items often carry more than one caption — a short one and a long one, a translation, a machine draft somebody approved.\n\nONE AT RANDOM gives the item a single visit each pass and draws a different caption each time, so the whole set is seen across a long run and an item counts once however many ways it has been described.\n\nEVERY CAPTION gives it one visit per caption, so all of them are used every pass — and an item with ten is therefore seen ten times, which is usually an accident of tooling rather than a claim that the picture matters ten times as much.\n\nEVERY CAPTION, SHARED is that with the accident removed: each caption still gets its visit, and together they carry one item's worth of gradient.":
    "一个条目常常带有不止一条描述——一条短的和一条长的、一段译文、一份有人审核过的机器初稿。\n\n“随机取一条”每一遍只给这个条目一次访问，每次抽到不同的描述；训练一长，所有描述都会被用到，而不管有多少种写法，这个条目都只算一次。\n\n“每条描述各一次”按描述数给它访问，所以每一遍都会用上全部——有十条描述的条目因此被看十次，这通常是工具造成的巧合，而不是在说这张图重要十倍。\n\n“每条描述各一次，共享权重”就是去掉这个巧合：每条描述仍各有一次访问，但它们合起来只承担一个条目份量的梯度。",
  "One at random each visit":
    "每次访问随机取一条",
  "Every caption, once each":
    "每条描述各一次",
  "Every caption, sharing one item's weight":
    "每条描述各一次，共享一个条目的权重",
  "Unsupported":
    "不支持",
  "not available on Apple silicon":
    "在 Apple 芯片上不可用",
  "not used on Apple silicon, where the run trains in fp32":
    "在 Apple 芯片上不会使用，训练将以 fp32 进行",
  "a full finetune trains the base weights, so there is nothing to quantize":
    "完整微调会训练基础权重，因此没有可量化的对象",
  "only offered for LoRA training":
    "仅在 LoRA 训练中提供",
  "too large to finetune on any GPU this app has constants for":
    "太大，无法在本应用有内存数据的任何 GPU 上做完整微调",
  "Another picture": "换一张图片",
  "{n} jobs selected. One at a time shows its progress, samples and settings.":
    "已选择 {n} 个任务。进度、测试图像和设置一次只显示一个。",
  "original":
    "原图",
  "Show this at full size":
    "以完整尺寸查看",
  "Each snapshot is about {size}.":
    "每个快照约 {size}。",
  "Cadence measured in":
    "间隔的单位",
  "How often a snapshot is written: after a fixed number of steps, or after a number of full passes over the dataset.":
    "多久写一次快照：每隔固定的步数，还是每完整过几遍数据集。",
  "How often a round of samples is rendered: after a fixed number of steps, or after a number of full passes over the dataset.": "生成一轮测试样图的频率：每隔固定步数，或每完整遍历数据集若干次。",
  "Rendered after this many full passes. The equivalent step count appears in the job's log when the run starts.": "每完整遍历这么多次后生成。开始运行时，作业日志中会显示对应的步数。",
  "A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 250 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both. It is the choice the checkpoint cadence and the run’s own length already offer, and setting all three the same way is what makes a sample, its checkpoint and a pass over your pictures line up in the timeline.\n\nHow many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has — a film’s frames, a degraded copy and an item contributing one entry per caption all count.": "一步是固定的工作量，一个轮次是把每张训练图片过一遍，因此数据集越大，两种节奏差得越远——「每 250 步」在小规模训练里几乎是全部，在大规模里只是一小部分，而「每个轮次」在两者中含义相同。这和检查点节奏以及训练长度提供的是同一个选择，三者用同一种单位设置时，样图、它的检查点和对图片的一次遍历会在时间线上对齐。\n\n一个轮次有多少步是在开始运行时算出来的，因为只有构建好的数据集才知道它有多少条目——影片的帧、降质副本，以及为每条描述各产生一个条目的项目，都计算在内。",
  "Rendered after this many full passes over the dataset. The equivalent step count is printed in the job’s log when the run starts, so a glance there says what the cadence came out as for this particular dataset.\n\nSampling interrupts training while it renders, so on a large dataset one round per epoch may be further apart than you want and on a tiny one it may be a pause every few seconds — the log’s step figure is what tells you which.": "每完整遍历数据集这么多次后生成。开始时会把对应的步数写进作业日志，看一眼就知道这个节奏在这份数据集上究竟是多少。\n\n生成样图期间训练会暂停，所以在大数据集上每轮次一次可能比你希望的更稀疏，而在很小的数据集上可能每几秒就停一次——日志里的步数会告诉你是哪一种。",
  "Rendered every this many steps, whatever the dataset is. 250–500 is a good rhythm: often enough to catch a concept going wrong, rare enough that the pauses do not dominate the run.": "无论数据集如何，每隔这么多步生成一次。250–500 是不错的节奏：足够频繁，能发现概念跑偏；又足够稀疏，不会让暂停主导整个训练。",
  "A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 500 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both.\n\nHow many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has. That is also why the disk estimate below can only be given when the run's length is set in epochs too.":
    "步是固定的工作量，轮次是把每张训练图像过一遍，所以数据集一变大，两种间隔就会分道扬镳：“每 500 步”在小规模训练里几乎是全部，在大规模训练里只是一小部分，而“每轮”在两者中含义相同。\n\n一轮相当于多少步是在运行开始时算出的，因为只有构建完成的数据集才知道它有多少条目。这也是为什么只有当训练长度同样以轮次给出时，下面的磁盘估算才能给出数字。",
  "epochs":
    "轮",
  "Written after this many full passes. The equivalent step count appears in the job's log when the run starts.":
    "每完整过这么多遍后写入一次。换算成多少步会在运行开始时显示在任务日志里。",
  "Every snapshot is a usable model file: the Evaluate tab can generate with any of them, so you can compare one pass against another and keep whichever looks best.\n\nCounted in passes, the cadence follows the dataset: add pictures and the snapshots stay one-per-pass rather than quietly becoming more frequent than a pass. The trainer prints what it works out to in steps, so the timeline and the log still agree about what a checkpoint is.":
    "每个快照都是可直接使用的模型文件：Evaluate 标签页可以用其中任意一个来生成，于是你可以把一遍和另一遍放在一起比较，留下更好的那个。\n\n按遍数计时，间隔会跟着数据集走：加了图片之后，快照仍是每遍一个，而不会悄悄变得比一遍还频繁。训练器会把换算出的步数写进日志，这样时间线和日志对“什么是检查点”仍然说法一致。",
  "Never upscale":
    "从不放大",
  "Leave out any image smaller than the bucket it would be fitted to, rather than enlarging it.":
    "比目标分桶更小的图像直接排除，而不是放大它们。",
  "Loads the frozen base weights in 8-bit or 4-bit so big models fit in little memory (QLoRA). 8-bit (int8) runs on Apple silicon too; fp8 and 4-bit need an NVIDIA GPU.":
    "以 8 位或 4 位加载冻结的基础权重，让大模型装进较小的内存 (QLoRA)。8 位 (int8) 在 Apple Silicon 上也能运行；fp8 和 4 位需要 NVIDIA GPU。",
  "Quantize the text encoder":
    "量化文本编码器",
  "Applies the same scheme to the text encoder, the other big frozen model. On the largest models it is worth several GB.":
    "对文本编码器——另一个大型冻结模型——应用同样的方案。在最大的模型上可节省数 GB。",
  "cannot be combined with training the text encoder":
    "无法与训练文本编码器同时使用",

  // ---- adapter type, layer targeting, optimizers, noise levels,
  // weight averaging and regularization ----
  "Adapter":
    "适配器",
  "Adapter type":
    "适配器类型",
  "Kronecker factor":
    "克罗内克因子",
  "How each weight is split into LoKr's two parts. Leave empty unless you have a reason not to.":
    "每个权重如何拆成 LoKr 的两个部分。没有特别理由就留空。",
  "Only these layers":
    "仅这些层",
  "all of them":
    "全部",
  "Comma-separated parts of a layer's name. Leave empty to train every attention layer — which is what you want unless you have a reason not to.":
    "层名的片段，用逗号分隔。留空则训练全部注意力层——没有特别理由时这正是你想要的。",
  "By default the adapter attaches to every attention layer in the image model. This narrows that to the layers whose name contains one of the words you list.\n\nWhy you might: different parts of the network do different jobs. The later ones carry more of what a picture LOOKS like, and the earlier ones more of how it is put together — so training only part of the network is how a style is learned without also disturbing composition and anatomy. It also makes the adapter smaller and each step faster, since there is less to train.\n\nThe names come from the model itself, and the chevron at the end of the field lists the ones worth knowing for the architecture you picked — clicking one adds or removes it, and a tick marks the ones the field already holds. For SD and SDXL they are down_blocks, mid_block and up_blocks, plus attn1 (the picture attending to itself) and attn2 (where the prompt gets in); for the newer transformer models, transformer_blocks and single_transformer_blocks. The field stays free text, because you can be as coarse or as fine as you like: 'up_blocks' takes a whole third of a UNet, 'transformer_blocks.12' takes one block, 'to_k' takes one kind of projection everywhere. The job's page draws a map of the whole model once a run has started.\n\nIf what you type matches no layers at all, the run stops and says so rather than training an adapter attached to nothing — which would otherwise look exactly like a normal run that learned nothing.":
    "默认情况下，适配器会挂到图像模型的每一个注意力层上。这里把范围缩小到名字里含有你所列词语之一的那些层。\n\n为什么要这么做：网络的不同部分承担不同的工作。靠后的层更多承载画面“看起来”如何，靠前的层更多承载画面是怎么搭起来的——所以只训练网络的一部分，正是在不扰动构图和人体结构的前提下学到一种画风的办法。要训练的东西少了，适配器也更小，每一步也更快。\n\n这些名字来自模型本身，字段末尾的箭头会列出所选架构中值得知道的那些——点一下即可添加或移除，字段里已有的会带上对勾。SD 和 SDXL 里是 down_blocks、mid_block、up_blocks，外加 attn1（图像关注自身的那一半）和 attn2（提示词进入的地方）；较新的 transformer 模型里则是 transformer_blocks 和 single_transformer_blocks。字段仍然是自由文本，因为你可以写得很粗，也可以很细：“up_blocks”会取走 UNet 的整整三分之一，“transformer_blocks.12”只取一个块，“to_k”取走各处的一种投影。任务页面会在一次运行开始后画出整个模型的分布图。\n\n如果你输入的内容一个层也匹配不到，运行会停下并说明，而不是去训练一个什么都没挂上的适配器——否则它看起来会和一次什么都没学到的正常运行一模一样。",
  "Except these layers":
    "排除这些层",
  "Comma-separated parts of a layer's name to leave out. Applied after the field above, and it wins.":
    "要排除的层名片段，用逗号分隔。在上面那一项之后应用，并以此为准。",
  "The same kind of list, subtracting instead of selecting. A layer whose name matches anything here is left out even if the field above selected it.\n\nIt is the easier way to say 'everything except' — excluding 'down_blocks' is shorter and stays correct if the model gains a block, where listing every other block by hand does not.":
    "同样形式的列表，只是做减法而不是做选择。名字与这里任一项匹配的层会被排除，即使上面那一项已经选中了它。\n\n这是表达“除了……以外全部”的更省事的写法：排除“down_blocks”更短，而且模型日后多出一个块时依然正确，手工列举其余所有块则做不到。",
  "Output size: a small fraction of a LoRA of the same rank — usually under a tenth.":
    "输出大小：同秩 LoRA 的一小部分，通常不到十分之一。",
  "Learning rate multiplier":
    "学习率倍数",
  "Prodigy works the rate out for itself; this scales what it finds. 1 leaves it alone — lower it if the run overshoots, raise it if it never gets going.":
    "Prodigy 会自行推算学习率；这里是对它算出的值的缩放倍数。1 表示照用；跑过头就调低，一直起不来就调高。",
  "The Prodigy optimizer measures how far the weights have moved from where they started and derives a learning rate from that, so the rate is not something you set here — it comes out of the run.\n\nWhat this field does is scale the answer. 1 accepts it as found and is what you want almost always. Below 1 is a brake, worth reaching for if the run overshoots and samples come out burnt; above 1 pushes harder, which is occasionally useful on a very small dataset.\n\nProdigy needs a few hundred steps to work its estimate up from nearly nothing, so early samples in a Prodigy run look untrained even when everything is fine. Judge it from about a fifth of the way in, not from the first sample round.":
    "Prodigy 优化器会测量权重相对起点移动了多远，并据此推导学习率，所以学习率不是在这里设定的——它来自运行本身。\n\n这一项只是对那个结果做缩放。1 表示照单全收，绝大多数情况下这就是你要的。小于 1 相当于刹车，当运行跑过头、样张出现“烧焦”感时值得一试；大于 1 则推得更狠，偶尔在极小的数据集上有用。\n\nProdigy 需要几百步才能把估计值从近乎为零抬起来，所以即便一切正常，Prodigy 运行的早期样张也会显得没训练过。请在大约五分之一进度处再作判断，而不是看第一轮样张。",
  "How far the weights move on every update. It is the single most sensitive setting here.\n\nToo high and training diverges: samples turn into over-saturated, high-contrast mush ('deep fried'), often within a few hundred steps. Too low and nothing visibly changes no matter how long you wait. Typical values: 1e-4 for a LoRA, 1e-5 or lower for a full finetune (which touches every weight and needs far gentler updates).\n\nLearning rate and total steps trade off against each other — halving the rate roughly doubles the steps needed. If early samples look burnt, halve it; if they look identical to the baseline after a third of the run, double it.\n\nIf finding this number is the part you would rather not do, the Prodigy optimizer (Memory & speed) works it out for itself.":
    "每次更新时权重移动的幅度。这是这里最敏感的一个设置。\n\n太高训练会发散：样张变成过饱和、高对比的一团糊（所谓“deep fried”），往往几百步内就出现。太低则无论等多久都看不出变化。典型取值：LoRA 用 1e-4，全量微调用 1e-5 或更低（它会动到每一个权重，需要温和得多的更新）。\n\n学习率和总步数会互相抵消——学习率减半，所需步数大约翻倍。如果早期样张看着烧焦，就减半；如果跑到三分之一还和基线一模一样，就翻倍。\n\n如果你正不想干“找这个数”这件事，Prodigy 优化器（内存与速度）会自行推算它。",
  "Noise levels":
    "噪声强度",
  "Train on":
    "训练在",
  "Which stage of denoising to spend the run on. High noise decides a picture's layout, low noise its detail — so this decides what the training is mostly about.":
    "把这次运行花在去噪的哪个阶段。高噪声决定画面的布局，低噪声决定细节——所以这一项决定训练主要在学什么。",
  "Every training step takes a picture, adds some amount of noise to it, and asks the model to undo that. How much noise is picked fresh each time — and the two extremes teach completely different things.\n\nAt HIGH noise there is barely a picture left, so all the model can learn is layout: what is where, how big, the overall shape and colour. At LOW noise the composition is already settled and what is left to learn is detail and texture — edges, surfaces, small features.\n\nSo where a run spends its steps decides what it mostly teaches. A style is largely texture; a character's proportions are largely layout.\n\n'The model's own' is what this model family has always done here, and is the right answer unless you have a specific reason: the older models spread their steps evenly, and the newer ones concentrate on the middle, which is what their published recipes do and part of why they train efficiently. 'Evenly' spreads across the whole range. 'Bell curve' is the newer models' behaviour made adjustable, so you can lean it towards layout or towards detail. 'Cosine' leans towards higher noise without abandoning the low end.\n\nChanging this does not make a run better or worse in general — it moves what the run is good at.":
    "每一步训练都会取一张图，给它加上一定量的噪声，再让模型把噪声去掉。加多少噪声每次重新抽取——而两个极端教会的东西完全不同。\n\n在高噪声下几乎没剩下什么画面，模型能学到的只有布局：什么在哪里、多大、整体的形状与色彩。在低噪声下构图已经定了，剩下要学的是细节和质感——边缘、表面、细小特征。\n\n因此一次运行把步数花在哪里，就决定了它主要教什么。画风大体上是质感；角色的比例大体上是布局。\n\n“模型自带的”是这一系列模型在这里一贯的做法，除非你有明确理由，否则它就是正确答案：较老的模型把步数均匀铺开，较新的模型集中在中段，这正是它们公开配方的做法，也是它们训练效率高的原因之一。“均匀”会铺满整个范围。“钟形曲线”是把新模型的行为变成可调的，你可以让它偏向布局或偏向细节。“余弦”偏向高噪声，同时不放弃低噪声一端。\n\n改动这一项并不会让运行整体变好或变差——它只是移动了运行擅长的方向。",
  "The model's own (recommended)":
    "模型自带的（推荐）",
  "Evenly across all levels":
    "在所有强度上均匀分布",
  "A bell curve I can aim":
    "可以瞄准的钟形曲线",
  "Leaning towards layout":
    "偏向布局",
  "Aim at":
    "瞄准",
  "0 is the middle. Positive leans towards layout and composition, negative towards detail and texture. ±1 is already a strong lean.":
    "0 是中点。正值偏向布局与构图，负值偏向细节与质感。±1 已经是很强的偏移。",
  "Where the centre of the bell curve sits along the noise range.\n\n0 puts it in the middle, which is what the newer models do by default and a good place to stay. Move it positive and the run spends more of itself at high noise, learning layout and composition — useful when what you are teaching is a shape or an arrangement. Move it negative and it spends more at low noise, learning detail and texture — useful for a style, a medium, a surface quality.\n\n±0.5 is a noticeable lean and ±1 is a strong one. Beyond ±2 the run largely stops seeing one end of the range at all.":
    "钟形曲线的中心落在噪声范围的什么位置。\n\n0 把它放在中间，这是较新模型的默认位置，也是个稳妥的选择。往正向移动，运行会把更多精力花在高噪声上，学习布局与构图——当你要教的是一种形状或一种摆布时很有用。往负向移动，则更多花在低噪声上，学习细节与质感——适合画风、媒材、表面质地。\n\n±0.5 是可以察觉的偏移，±1 已经很强。超过 ±2，运行基本上就完全看不到范围的一端了。",
  "Spread":
    "分布宽度",
  "How wide the curve is. 1 is the default; smaller concentrates the run on a narrow band around the aim, larger reaches both extremes.":
    "曲线的宽度。默认是 1；更小会让运行集中在瞄准点附近的窄带上，更大则能触及两端。",
  "The width of the bell curve.\n\n1 is the standard setting. Smaller values concentrate the run on a narrow band around wherever you have aimed it, which sharpens what it teaches at the cost of everything else. Larger values spread it out and reach both extremes more often, which is closer to training evenly.\n\nIf you are unsure, leave it at 1 and move the aim instead — the aim is the setting that changes what the run learns, and this one changes how single-minded it is about it.":
    "钟形曲线的宽度。\n\n1 是标准设置。更小的值会把运行集中在你瞄准位置附近的窄带上，代价是牺牲其余一切，换来所教内容更锐利。更大的值把它铺开，更常触及两端，更接近均匀训练。\n\n拿不准就保持 1，改动瞄准值即可——瞄准值决定运行学什么，而这一项只决定它有多专一。",
  "Weight averaging":
    "权重平均",
  "Average the weights":
    "对权重取平均",
  "Save a smoothed version of the weights instead of whatever the last step happened to produce. Makes checkpoints more consistent and overtraining slower to bite.":
    "保存一份平滑后的权重，而不是最后一步碰巧产出的那份。让各个检查点更一致，过拟合的影响也来得更慢。",
  "Every training step moves the weights a little, and each of those moves is noisy — it is worked out from a handful of images, and a different handful would have pulled somewhere slightly different. So the weights at step 1400 are not reliably better than the weights at step 1200; part of the difference is just which pictures came up.\n\nWith this on, the run keeps a second, smoothed copy of the weights alongside the real ones and nudges it a little way towards the current weights after every step. That smoothed copy is what gets saved — as the checkpoints, as the final result, and as what the test samples are rendered from. Training itself is completely unaffected.\n\nWhat you get is a result that depends less on exactly where the run stopped: the quality difference between neighbouring checkpoints shrinks, and a run that goes on too long degrades more gradually, because an average lags behind. What it costs is one extra copy of whatever is being trained — nothing worth thinking about for a LoRA, a second whole model for a full finetune, which the memory estimate below accounts for.\n\nThe early part of a run is handled for you: a fresh average starts out equal to the untrained weights, so the run keeps it short at first and lengthens it as training goes on. Without that, a short run would save an average still holding its own random starting point.":
    "每一步训练都会把权重挪动一点，而每一次挪动都是带噪的——它是从一小把图像算出来的，换一把图像就会往稍微不同的方向拉。所以第 1400 步的权重并不可靠地优于第 1200 步的权重；差异中有一部分只是当时碰巧抽到了哪些图。\n\n打开这一项后，运行会在真正的权重旁边再保留一份平滑副本，并在每一步之后把它朝当前权重推一小段。被保存下来的正是这份平滑副本——检查点、最终结果，以及渲染测试样张所用的权重都是它。训练本身完全不受影响。\n\n你得到的是一个不那么依赖“运行恰好停在哪里”的结果：相邻检查点之间的质量差距变小，跑得过久的运行也会更平缓地退化，因为平均值总是落后一拍。代价是多出一份正在训练之物的副本——对 LoRA 而言不值一提，对全量微调则相当于第二个完整模型，下方的内存估算已经把它算进去了。\n\n运行的开头会自动处理好：新建的平均值起初等于未训练的权重，所以运行一开始会让平均窗口很短，随着训练推进再逐渐拉长。没有这一点，短运行保存下来的平均值里还会残留它自己的随机起点。",
  "Averaging window":
    "平均窗口",
  "How much of the old average is kept each step. 0.999 averages roughly the last 1000 steps; lower follows training more closely, higher smooths harder.":
    "每一步保留多少旧的平均值。0.999 大致相当于对最近 1000 步取平均；更低会更紧地跟随训练，更高则平滑得更狠。",
  "The fraction of the existing average kept at each step, with the rest taken from the current weights. It decides how long a stretch of training the saved result reflects — roughly 1 ÷ (1 − this value) steps.\n\n0.999 is about the last 1000 steps and is a sensible default for runs of a few thousand. On a short run (say 800 steps) that window is longer than the run itself, so the average never quite catches up — drop to 0.99 (about 100 steps) there. On a very long run you can go higher for a steadier result.\n\nAs a rule of thumb, keep the window well under the total number of steps.":
    "每一步保留现有平均值的比例，其余部分取自当前权重。它决定保存下来的结果反映了多长一段训练——大约是 1 ÷ (1 − 此值) 步。\n\n0.999 约为最近 1000 步，对几千步的运行是个合理的默认值。在短运行（比如 800 步）里，这个窗口比运行本身还长，平均值始终追不上——那里应降到 0.99（约 100 步）。非常长的运行可以调得更高，以得到更稳的结果。\n\n经验法则：让窗口明显小于总步数。",
  "Mostly a memory choice, except for Prodigy, which works the learning rate out for itself. Adafactor saves the most memory and runs on every GPU; 8-bit AdamW saves less and needs an NVIDIA or AMD card.":
    "基本上是内存上的取舍，Prodigy 除外——它会自行推算学习率。Adafactor 省得最多，且在任何 GPU 上都能跑；AdamW（8 位）省得较少，且需要 NVIDIA 或 AMD 显卡。",
  "The optimizer is what actually turns gradients into weight changes. It does that using running statistics it keeps for every weight being trained — and those statistics are memory, which for a full finetune is usually most of what the run needs.\n\nAdamW is the standard choice and the safest. It keeps two statistics per trained weight, so a full finetune pays for the model roughly three times over: the weights themselves, plus two more of the same size.\n\nAdamW (8-bit) stores those two statistics at one byte each instead of four. It is a smaller saving than it sounds, because the weights and their gradients do not shrink, and it needs an NVIDIA or AMD (ROCm) GPU — elsewhere the run says so and uses plain AdamW.\n\nAdafactor replaces the larger of the two statistics with a per-row and a per-column summary of it, which is a fraction of the size. It saves considerably more than the 8-bit variant and it runs on every GPU, including Apple silicon — where it is the only memory saving available at all, since the 8-bit variant cannot run there. What it costs is a little stability: it usually wants a slightly higher learning rate than AdamW, so if a run learns nothing after a few hundred steps, raise the rate before changing anything else.\n\nProdigy is a different kind of answer. It measures how far the weights have travelled from where they started and works the learning rate out from that as it goes, which removes the one setting here that genuinely has to be found by trial: the right rate depends on the model, the dataset size and what is being taught, so a value that suits one job is wrong for the next. With it selected, the learning rate on the Optimization page becomes a multiplier on what it finds, and 1 means 'as found'. It uses a little more memory than AdamW, and it needs a few hundred steps to work its estimate up — so early samples look untrained even when the run is fine.\n\nFor LoRA training the memory differences are a rounding error, since only the small adapter has optimizer state. Leave it on AdamW for a first run; reach for Prodigy when you are tired of guessing the rate, and for Adafactor when a full finetune will not fit.":
    "优化器是真正把梯度变成权重变化的东西。它靠为每一个被训练的权重维护的运行统计量来完成这件事——而这些统计量就是内存，对全量微调来说通常占了整次运行所需内存的大头。\n\nAdamW 是标准选择，也是最稳妥的。它为每个被训练的权重保留两份统计量，所以全量微调大约要为模型付出三倍的代价：权重本身，加上两份同样大小的统计量。\n\nAdamW（8 位）把这两份统计量从每个 4 字节改为每个 1 字节存储。省下的比听上去要少，因为权重和它们的梯度并不会缩小；而且它需要 NVIDIA 或 AMD（ROCm）GPU——在别的环境里运行会给出提示并改用普通 AdamW。\n\nAdafactor 把两份统计量中较大的那份换成按行和按列的摘要，体积只是原来的一小部分。它比 8 位版本省得多，而且在任何 GPU 上都能跑，包括 Apple silicon——在那里它其实是唯一可用的内存节省手段，因为 8 位版本在那里根本跑不了。代价是稳定性略差：它通常想要比 AdamW 略高一点的学习率，所以如果几百步后运行什么都没学到，先提高学习率，再去改别的。\n\nProdigy 是另一类答案。它测量权重相对起点走了多远，并据此一边跑一边推算学习率，从而免去了这里唯一一个真得靠试出来的设置：合适的学习率取决于模型、数据集大小和所教的内容，所以适合一个任务的值到下一个任务就是错的。选中它之后，优化页面上的学习率会变成对它推算结果的倍数，1 表示“照它算的用”。它比 AdamW 多占一点内存，并且需要几百步把估计值抬起来——所以即使运行一切正常，早期样张也会显得没训练过。\n\n对 LoRA 训练来说，这些内存差别属于舍入误差，因为只有那个小适配器带有优化器状态。第一次运行就留在 AdamW；厌倦了猜学习率时改用 Prodigy；全量微调放不下时改用 Adafactor。",
  "AdamW (8-bit)":
    "AdamW（8 位）",
  "Prodigy (finds its own rate)":
    "Prodigy（自行确定学习率）",
  "Prodigy works the learning rate out for itself, so the rate on the Optimization page becomes a multiplier on what it finds — 1 leaves it alone. It needs a few hundred steps to settle, so early samples will look untrained.":
    "Prodigy 会自行推算学习率，因此优化页面上的学习率会变成对它推算结果的倍数——1 表示照用。它需要几百步才能稳定下来，所以早期样张会显得没训练过。",
  "Regularization":
    "正则化",
  "How much reminders count":
    "提醒图像的权重",
  "1 gives a regularization picture the same say as a training picture, which is the usual setting. Lower makes it a gentler reminder.":
    "1 表示正则化图像与训练图像有同等的分量，这是通常的设置。调低则让它成为更温和的提醒。",
  "Regularization pictures are in the run to hold the model's existing idea of a thing in place while you teach it something new. This is how much each of them counts against a training picture, which counts 1.\n\n1 is the classic setting and a good starting point. Lower it if the run seems reluctant to learn what you are actually training — the reminders are pulling too hard. Raise it if what you are training keeps leaking into everything else of the same kind, which is the problem they exist to solve.\n\nThis is separate from a query's weight, which decides how OFTEN those pictures come up. How often and how much are different questions: a set of reminders is usually wanted often but quietly.":
    "正则化图像出现在这次运行里，是为了在你教模型新东西的同时，把它对某类事物既有的理解按住不动。这里设定的是它们每一张相对于训练图像（计为 1）的分量。\n\n1 是经典设置，也是不错的起点。如果运行似乎不太愿意学你真正想训练的东西，就调低——提醒拉得太用力了。如果你训练的东西不断渗进同类的一切之中，就调高，这正是它们存在要解决的问题。\n\n这与查询的权重是两回事，后者决定这些图像出现得有多“频繁”。频率和分量是不同的问题：一组提醒图像通常希望出现得频繁，但作用要轻。",
  "Pictures that remind the model what it already knows, instead of teaching it something new — they stop what you are training from spreading to everything else of the same kind. They never get the trigger word.":
    "这些图像是在提醒模型它已经知道的东西，而不是教它新东西——它们能阻止你训练的内容扩散到同类的一切之中。它们永远不会带上触发词。",
  "These pictures hold the model's existing idea of the subject in place: pick the same KIND of thing you are training, but not the thing itself. You do not need to exclude your training pictures — anything an ordinary query matches stays a training picture. A reminder query that matches only training pictures leaves this pool empty, and the run says so in its log.":
    "这些图像把模型对该主体既有的理解按住不动：请挑选与你训练对象同“类”但并非该对象本身的图像。你不需要排除自己的训练图像——被普通查询匹配到的图像仍然是训练图像。若提醒查询只匹配到训练图像，这个池子就是空的，运行会在日志里说明。",
  "Keep the text encoder on the CPU":
    "将文本编码器留在 CPU 上",
  "Frees all of its VRAM instead of some. The next batch's prompt is encoded while this one trains, so it costs nothing as long as the processor keeps up with the card.": "释放它的全部显存而不只是一部分。下一批的提示词会在这一批训练时编码，所以只要处理器跟得上显卡，就没有额外开销。",
  "The row above makes the text encoder smaller; this one takes it off the graphics card altogether. Its weights stay in ordinary system memory and each prompt is turned into an embedding there, so the encoder occupies no VRAM at all — where quantizing it leaves roughly a third of it resident.\n\nMeasured on an RTX 5070 Ti at 4-bit, this takes Chroma from 9.6 GB to 5.3 and FLUX.1 from 11.4 to 7.0, which was enough to train FLUX.2 Klein at a resolution that did not previously fit.\n\nWhat it costs is one pass over the encoder per step, on the processor instead of the graphics card — and the next batch's prompt is encoded while the current one trains, so the card only waits where the processor is slower than a whole step. Measured on a 16-core desktop, T5-XXL takes about 1.3 seconds a prompt: a 1024-pixel step on an RTX 5090 hides that entirely, a 512-pixel step (half a second) does not. It cannot be combined with training the text encoder, which would mean doing that training on the processor.":
    "上一行把文本编码器变小，这一行则把它完全移出显卡。权重留在普通系统内存中，每个提示词也在那里转成嵌入，因此编码器完全不占显存—而量化会留下大约三分之一。\n\n在 RTX 5070 Ti 上以 4 位实测：Chroma 从 9.6 GB 降到 5.3，FLUX.1 从 11.4 降到 7.0，足以在之前放不下的分辨率上训练 FLUX.2 Klein。\n\n代价是每一步在处理器而不是显卡上跑一次编码器——下一批的提示词会在当前批训练时编码，所以只有当处理器比整个训练步还慢时显卡才会等待。在 16 核台式机上测得 T5-XXL 每条提示词约需 1.3 秒：RTX 5090 上的 1024 像素训练步能完全掩盖它，512 像素的训练步（半秒）则不能。它不能与训练文本编码器同时使用，因为那意味着要在处理器上进行训练。",

  // ---- the METHOD is an adapter, of which LoRA is one kind ----
  "An adapter is a small add-on file layered over the untouched model — fast, low memory, ideal for styles, characters and concepts. Full finetune rewrites the whole model: much more VRAM and data needed, only worth it for broad domain shifts. Which kind of adapter is the next question down.":
    "适配器是叠加在原封不动的模型之上的一个小附加文件——快、占用内存少，适合画风、角色和概念。全量微调则重写整个模型：需要多得多的显存和数据，只有在大幅切换领域时才值得。用哪种适配器是下面紧接着的一个问题。",
  "An adapter leaves the base model untouched and trains a small add-on (a few dozen MB) that is layered on top at generation time. It is quick, fits ordinary hardware, can be mixed with other adapters and dialled up or down by weight — and it is enough for styles, characters, objects and most concepts. There are two kinds, LoRA and LoKr, and the Adapter section below picks between them; LoRA is the one to start with.\n\nA full finetune rewrites every weight of the model. It produces a multi-gigabyte model of its own, needs far more VRAM, far more images and much lower learning rates, and it can forget things it used to know. Reach for it only when you are moving the model into a genuinely different domain, not to teach it one more subject.":
    "适配器不动基础模型，只训练一个小的附加文件（几十 MB），在生成时叠加上去。它快、能在普通硬件上跑、可以和其他适配器混用、还能按权重调强调弱——对画风、角色、物体和大多数概念来说这就够了。它有两种，LoRA 和 LoKr，由下面的“适配器”一节来选；先从 LoRA 开始。\n\n全量微调会重写模型的每一个权重。它产出一个几个 GB 的独立模型，需要多得多的显存和图片、低得多的学习率，而且可能忘掉它原本会的东西。只有在把模型迁往一个真正不同的领域时才动用它，而不是为了再教它一个题材。",
  "Start from an existing adapter":
    "从现有适配器开始",
  "A fresh adapter starts from noise and has to learn your concept from nothing. Starting from an existing one keeps everything it already learned and refines it — the usual reasons are adding new images to a concept you trained before, or nudging one that came out almost right.\n\nWeight sets trained on the same base model are offered — including ones trained on another model built on it — and the new job has to match the one it continues: the same adapter type, the same rank, and the same layer targeting. The trainer stops with a message naming what it found otherwise. Picking a job's finished result continues where it ended; picking an intermediate checkpoint rewinds to that point and continues from there.":
    "全新的适配器从噪声开始，得从零学会你的概念。从现有的开始则保留它已经学到的一切并继续打磨——常见的理由是给以前训练过的概念补充新图，或者微调一个差一点就对了的适配器。\n\n会列出用同一个基础模型训练出来的权重——也包括用以它为基础的其他模型训练出来的——而且新任务必须和它所继续的那个一致：同样的适配器类型、同样的秩、同样的层选择。否则训练会停下并说明它发现了什么。选一个任务的最终结果，就从它结束的地方继续；选中间的检查点，则回退到那一点再往下走。",
  "Pick a finished adapter":
    "挑选已完成的适配器",
  "No finished adapter for this base model yet":
    "此基础模型还没有已完成的适配器",
  "Optional: continue training an existing adapter instead of starting from scratch.":
    "可选：继续训练现有适配器而不是从零开始。",
  "No full finetune":
    "不支持全量微调",

  // ---- adapter wording: an adapter is LoRA or LoKr ----
  "The standard choice, and the format every other tool understands — a LoRA can be used anywhere.":
    "标准选择，也是其他所有工具都能读懂的格式——LoRA 到哪儿都能用。",
  "An adapter does not rewrite the model — it adds a small 'side channel' to certain layers, and rank is how wide that channel is: how much new information the adapter can hold.\n\nLow ranks (4–8) are plenty for a style or a colour palette and are very hard to overfit. Mid ranks (16–32) suit characters and objects with consistent details. High ranks (64+) mostly grow the file and the overfitting risk without helping, unless you are teaching a genuinely broad new domain.\n\nIt means slightly different things to the two adapter types. For a LoRA it is the hard ceiling on the change: a rank-16 adapter can only ever make a rank-16 change. For a LoKr it bounds only part of the structure, so a LoKr is not confined the way a LoRA is and its file grows far more slowly as you raise it — which is why the size estimate below is a figure for LoRA and a comparison for LoKr.":
    "适配器并不重写模型——它只是给某些层加了一条小“旁路”，而秩就是这条旁路的宽度：适配器能装下多少新信息。\n\n低秩（4–8）用于画风或配色绰绰有余，也很难过拟合。中等（16–32）适合细节稳定的角色和物体。高秩（64+）多半只会把文件和过拟合风险一起撑大而没什么帮助，除非你在教一个真正宽泛的新领域。\n\n它对两种适配器的含义略有不同。对 LoRA 来说，它就是变化的硬上限：秩为 16 的适配器只能做出秩 16 的变化。对 LoKr 来说，它只约束结构的一部分，所以 LoKr 不像 LoRA 那样被框住，调高时文件增长也慢得多——这也是下面的大小提示对 LoRA 给数字、对 LoKr 给比较的原因。",
  "The adapter's output is multiplied by alpha ÷ rank before being added to the model, so alpha sets how loudly the adapter speaks at a given capacity. It works the same way for both adapter types.\n\nThe usual convention is alpha = rank, which makes the scale factor 1 and keeps behaviour comparable when you change rank. Setting alpha to half the rank is a common way to soften an adapter that comes out too strong. It interacts with the learning rate — halving alpha has a similar effect to halving the rate — so change one at a time.":
    "适配器的输出在加到模型上之前会乘以 alpha ÷ 秩，所以在给定容量下，alpha 决定适配器说话有多大声。两种适配器的机制相同。\n\n惯例是 alpha = 秩，这样系数为 1，改秩时行为也便于比较。把 alpha 设为秩的一半，是让过强的适配器变柔和的常见做法。它和学习率相互影响——把 alpha 减半和把学习率减半效果相近——所以一次只改一样。",
  "This architecture can only be trained as an adapter (LoRA or LoKr) alongside the frozen model. The \"Full finetune\" method, which rewrites the model's own weights, is not offered for it.":
    "该架构只能以适配器（LoRA 或 LoKr）的形式在冻结的模型旁训练。 它不提供会重写模型自身权重的“全量微调”方式。",
  "No adapters for this base model yet.": "此基础模型还没有适配器。",
  "No trained adapters yet.": "还没有训练好的适配器。",
  "Which adapter this row applies":
    "这一行应用哪个适配器",
  "Adapter strength: 1 = as trained, below weakens, above strengthens (can distort past ~1.5).":
    "适配器强度：1 = 按训练原样，低则减弱，高则加强（超过约 1.5 可能失真）。",
  "Add adapter":
    "添加适配器",
  "Adapters":
    "适配器",
  "Finetune": "微调",
  "Generate with a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.":
    "用完整微调的权重代替基础模型的权重来生成。适配器会叠加在这里选中的权重之上。",
  "none — the base model": "无 —— 基础模型",
  "loading finetune": "加载微调中",
  "Stack trained adapters on the base model, each with its own strength — LoRA or LoKr. An adapter fits the model it was trained on and any other built on the same one.":
    "把训练好的适配器（LoRA 或 LoKr）叠加在基础模型上，各带自己的强度。适配器适用于训练它的模型，以及任何以同一模型为基础构建的模型。",
  "Generated images appear here — try out a trained adapter against its base model.":
    "生成的图片会出现在这里——拿训练好的适配器和它的基础模型比一比。",
  "A much smaller file, and not limited by the rank the way a LoRA is. Whether it can be used outside this app depends on the model — see the ⓘ.":
    "文件小得多，也不像 LoRA 那样受秩的限制。能否在本应用之外使用取决于模型——请看 ⓘ。",
  "Both add a small trainable layer over the frozen model; they differ in the shape of change they can express.\n\nA LoRA adds a 'low-rank' change: two thin matrices whose product is added to each targeted weight. Its capacity is exactly its rank — a rank-16 adapter can only ever make a rank-16 change, however long you train it. That is ample for a character, an object, a colour palette. It trains a little faster, it is the format every tool reads, and it carries better between related checkpoints: a LoRA trained on one finetune of a model usually still works on another.\n\nLoKr builds the change as a Kronecker product of two much smaller matrices instead. The saving comes from that structure rather than from throwing rank away, so the change is not confined to a thin slice of the weight while the file stays a small fraction of a LoRA's — under a tenth of the trainable parameters at rank 8. LyCORIS, whose method this is, suggests reaching for it when a LoRA 'does not learn well enough', and it is generally the better fit for styles and broad visual qualities, where a LoRA's rank ceiling is what you meet first. Its own caveats are the mirror image: slightly slower to train, and a very small LoKr transfers less well if you later swap the base model for a different finetune.\n\nWhat each can be USED by differs, and it is the file rather than the method. A LoRA is written in the layout every tool reads. A LoKr cannot be: that layout has a place for two matrices and nowhere to put a Kronecker factor. What it gets instead is a copy named the way ComfyUI names LoKr layers, and that works for the models whose layers ComfyUI addresses that way — FLUX.1, FLUX.1 Kontext and the Qwen-Image releases. On the others (SD 1.5, SDXL, Chroma, FLUX.2, Z-Image) a LoKr stays here: it works in the Evaluate tab and as the starting point of another job, but there is no file to hand over. On those, pick LoRA if the result has to leave this app.":
    "两者都是在冻结的模型之上加一层可训练的小结构，区别在于能表达什么形状的变化。\n\nLoRA 加的是「低秩」变化：两个细长矩阵，其乘积被加到每个目标权重上。它的容量恰好就是秩——秩 16 的适配器无论训练多久，也只能做出秩 16 的变化。对一个角色、一个物件、一套配色来说这绰绰有余。它训练略快，是所有工具都能读的格式，而且在同源检查点之间迁移得更好：在某个微调模型上训练的 LoRA，通常在另一个上仍然可用。\n\nLoKr 则把变化构造成两个小得多的矩阵的克罗内克积。省下的体积来自这种结构，而不是丢弃秩，因此变化不会被限制在权重的一薄片上，而文件只有 LoRA 的一小部分——秩 8 时不到可训练参数的十分之一。提出该方法的 LyCORIS 建议：当 LoRA「学得不够好」时改用它；对画风和宽泛的视觉特质，它通常更合适，因为那正是最先撞上 LoRA 秩上限的地方。它自身的代价是镜像的：训练略慢，而且非常小的 LoKr 在你之后把基础模型换成另一个微调版本时更难迁移。\n\n两者能被什么「用起来」并不相同，而这取决于文件，不是方法。LoRA 会以所有工具都能读的格式写出。LoKr 做不到：那个格式只有放两个矩阵的位置，没有放克罗内克因子的地方。它得到的是一份按 ComfyUI 命名 LoKr 层的方式命名的副本，这对 ComfyUI 以这种方式寻址其层的模型有效——FLUX.1、FLUX.1 Kontext 和 Qwen-Image 系列。其余模型（SD 1.5、SDXL、Chroma、FLUX.2、Z-Image）上的 LoKr 只能留在这里：它可以在 Evaluate 标签中使用，也可作为另一个任务的起点，但没有可以交出去的文件。在那些模型上，如果结果需要离开本应用，请选 LoRA。",
  "LoKr expresses a weight's change as one small matrix combined with another. This number decides where the weight is cut into those two parts.\n\nLeft empty, the split is chosen to make the two parts as close to square as possible, which is where they are SMALLEST. Moving it either way grows the file, and the two directions are not the same thing: a low factor (4–8) pushes the weight into the second part, which is where the adapter's capacity is — that is the LyCORIS recipe for a LoKr that is not learning enough. A factor far above the square split grows the first, dense part instead, which costs size for nothing.\n\nMeasured on a 1280-wide layer at rank 8, against the same layer's LoRA: automatic 0.08x, factor 8 0.13x, factor 4 0.25x, factor 128 0.81x.\n\nThere is rarely a reason to set it. If a LoKr adapter is not learning enough, raise the rank first, then try a low factor.":
    "LoKr 把一个权重的变化表示为一个小矩阵与另一个矩阵的组合。这个数字决定权重从哪里切成这两部分。\n\n留空时，切分会让两部分尽可能接近正方形，那里正是两者最小的位置。向任一方向移动都会让文件变大，而两个方向的含义并不相同：较小的因子（4–8）把权重推向第二部分，也就是适配器容量所在之处——这正是 LyCORIS 针对「学不够」的 LoKr 给出的做法。远高于正方切分的因子则会让第一个稠密部分变大，白白付出体积。\n\n在宽度 1280 的层、秩 8 上与同一层的 LoRA 对比实测：自动 0.08 倍，因子 8 为 0.13 倍，因子 4 为 0.25 倍，因子 128 为 0.81 倍。\n\n很少有必要设置它。如果 LoKr 学得不够，先提高秩，再试较小的因子。",
  "Every picture this finds is also matched by a training query, so it contributes nothing and the run will not be regularized. Narrow it to pictures the run is NOT about.":
    "它找到的每一张图都同时被某个训练查询匹配，因此这个池子毫无贡献，本次运行不会被正则化。请把它缩小到本次运行并非针对的图像。",
  "val": "验证",
  "stable": "稳定",
  "validation": "验证",
  "Validate": "验证",
  "Masked regions": "遮罩区域",
  "Mask out regions tagged": "遮罩这些标签的区域",
  "Comma-separated tags whose bounding boxes are largely ignored by the loss — e.g. 'watermark'. The picture still trains; the region inside the boxes stops teaching. Tags without boxes on an image mask nothing there.": "以逗号分隔的标签，其边界框内的损失基本被忽略——例如 'watermark'。图片仍参与训练；只有框内区域不再产生教学信号。没有画框的标签在那张图片上不会遮罩任何东西。",
  "Mask out regions of tags marked": "遮罩被标记标签的区域",
  "Comma-separated META tags. Any tag the library marks with one of these has its boxes masked — so the rule is stated once in the Tags tab rather than listed here.": "以逗号分隔的元标签。库中被这样标记的任何标签，其边界框都会被遮罩——规则在标签页说一次，而不必在这里逐一列出。",
  "Masked region weight": "遮罩区域权重",
  "How much a masked region still counts. 0 hides it from training entirely; 1 is the same as not masking.": "被遮罩的区域还计入多少。0 将它完全从训练中隐去；1 等于不遮罩。",
  "Validation": "验证",
  "Score a validation loss": "计算验证损失",
  "A few images are held out of training and re-scored on a fixed seed as the run goes. Falling: still learning. Rising while the training loss falls: memorizing — pick an earlier checkpoint.": "留出少量图片不参与训练，并在训练过程中用固定种子反复评分。下降：仍在学习。训练损失下降而它上升：开始死记硬背——选择更早的检查点。",
  "Validate every": "验证间隔",
  "Each round costs one forward pass per scored image — a small set every few hundred steps is barely noticeable.": "每轮评分对每张图片只需一次前向传播——每几百步一小组，几乎察觉不到。",
  "Held-out images": "留出图片",
  "Taken OUT of training entirely and scored each round. Capped at half the dataset; 16 is plenty for a LoRA-sized run. 0 turns the held-out series off.": "完全从训练中拿出，每轮评分。上限为数据集的一半；LoRA 规模的训练 16 张就够。0 关闭该曲线。",
  "Stable-loss images": "稳定损失图片",
  "Ordinary TRAINING images re-scored the same fixed way — the training curve without its sampling noise. They stay in training; 0 turns the series off.": "普通的训练图片，用同样固定的方式重新评分——去掉采样噪声的训练曲线。它们仍留在训练中；0 关闭该曲线。",
  "Some pictures are worth training on except for one rectangle: a watermark, a shop’s caption strip, a censor bar. Left alone, the model learns the rectangle along with the picture — a run over watermarked photographs reliably teaches the watermark. Throwing those pictures out costs the dataset; this keeps them and hides the rectangle from training instead.\n\nThe regions come from the boxes already on the tag: draw a box for `watermark` in the annotator (or let the watermark detector’s tag carry one), name the tag here, and every image carrying such a box trains with the loss inside it turned down. Where a subject tag has no drawn box, its detected faces stand in, exactly as they do for crop-aware training. An image whose named tags have no boxes trains completely normally — nothing is masked there.\n\nOnly the LOSS is masked. The pixels still pass through the image encoder, so the cached latents are the ordinary ones shared with unmasked runs, and nothing is re-encoded when this setting changes. The mask lives in latent space, where one cell covers 8×8 pixels rounded outward to whole cells — so it cannot hide anything much thinner than that, and a pixel-accurate outline is not something it can promise. It also cannot conjure what is UNDER the watermark: the model simply receives no signal about that area, from this picture.\n\nPairs naturally with a tag the prompt always includes (Always include under Tag selection): the prompt says the watermark is there, the mask stops the pixels teaching it, and at generation time the model has no reason to produce one unprompted.": "有些图片只差一个矩形就值得训练：水印、商店的文字条、审查条。不管它，模型会连同图片把矩形一起学会——在带水印的照片上训练，必然教会模型水印。丢掉这些图片损失的是数据集；这个设置留下它们，转而把矩形从训练中藏起来。\n\n区域来自标签上已有的框：在标注器里为 `watermark` 画一个框（或让水印检测器的标签带一个），在这里写上该标签，此后每张带这种框的图片，框内的损失都会被调低。人物标签没有手画框时，用检测到的人脸代替，与裁剪感知训练完全相同。被点名的标签没有框的图片完全正常训练——那里什么也不会被遮罩。\n\n被遮罩的只有损失。像素仍会经过图像编码器，所以缓存的潜变量就是未遮罩训练共用的那些，改动这个设置不会触发重新编码。遮罩存在于潜空间，一格覆盖 8×8 像素，并向外取整到整格——所以它藏不住比这细得多的东西，也无法承诺像素级的轮廓。它也变不出水印下面是什么：模型只是从这张图片得不到那块区域的任何信号。\n\n与提示词中总是包含的标签（标签选择下的「总是包含」）天然搭配：提示词说水印在那里，遮罩让像素教不了它，生成时模型也就没有理由无端画出一个来。",
  "The same rule, stated once in the library instead of tag by tag here. A meta tag put on the tags whose boxes should never teach — `masked`, say — covers every such tag at once, including ones created after this job was written.\n\nThe list is resolved to tag names when the dataset is built, so the job’s log says how many images actually carried a masked region. A run where that line says zero has a rule pointing at tags nobody drew boxes for.": "同一条规则，在库里说一次，而不是在这里逐个标签列出。给那些框永远不该教学的标签打上一个元标签——比如 `masked`——就一次覆盖了所有这类标签，包括此作业写好之后才创建的。\n\n列表在构建数据集时解析为标签名，所以作业日志会写明有多少图片真的带有遮罩区域。那一行是零的训练，说明规则指向的标签没人画过框。",
  "What a cell inside a masked box still counts for. 0 hides the region entirely, which is the usual choice for a watermark — there is nothing in it worth a whisper. A small value (0.05–0.2) keeps a faint signal, which can be worth it when the boxes are generous and cover real picture around the thing being hidden.\n\n1 is the unmasked loss, so setting it there is the same as clearing the tag lists. Where an image also trains with an alpha mask, the two multiply: a masked region on a transparent background is doubly not the picture.": "遮罩框内的一格还计入多少。0 完全隐去该区域，对水印这是常见选择——里面没有任何值得留一丝的东西。小值（0.05–0.2）保留微弱信号，当框画得宽、盖住了要隐藏之物周围的真实画面时，这样做是值得的。\n\n1 就是未遮罩的损失，设成 1 等于清空标签列表。当图片同时用透明遮罩训练时，两者相乘：透明背景上的遮罩区域是双重的「不是画面」。",
  "The training loss cannot answer the question people ask of it. It is drawn from the pictures being trained on, at a different random noise level every step, so it is noisy by construction — and it keeps falling for as long as the model memorizes, which means it looks healthiest exactly when a run has gone on too long.\n\nThis scores two extra series that can answer it, both with the plain per-sample loss on a fixed seed, so every round asks the model exactly the same questions and the number moves only when the model does. The series appear as their own lines on the loss graph, and each round is a line in the job’s log.\n\nReading it: the validation loss falls while the model generalizes and flattens or turns when it starts memorizing — the turning point is roughly where to stop, and with step snapshots on, the checkpoint to pick. Expect it to sit above the training loss and to move in small amounts; what matters is the direction, not the level. It stays comparable across pauses, resumes and step extensions, because the scored images and the seed never change within a job.": "训练损失回答不了人们问它的问题。它取自正在训练的图片，每一步都在不同的随机噪声水平上，因此天生充满噪声——而且只要模型在死记硬背它就会一直下降，也就是说训练跑得越久，它反而显得越健康。\n\n这个设置额外计算两条能回答问题的曲线，都用固定种子下的普通逐样本损失，因此每一轮问模型的都是完全相同的问题，数字只在模型变化时才动。曲线以独立的线出现在损失图上，每一轮也是作业日志里的一行。\n\n怎么读：验证损失在模型泛化时下降，在开始死记硬背时变平或掉头——转折点大致就是该停的地方，开了步数快照的话，也是该选的检查点。它通常位于训练损失之上、以小幅移动；重要的是方向，不是高度。参与评分的图片和种子在一个作业内从不改变，所以跨暂停、续跑和加步都保持可比。",
  "How often a round runs, in steps. A round costs one forward pass per scored image — no gradients, no optimizer — so a 16-image set is a few seconds; matching the sample or checkpoint cadence keeps the graph, the images and the snapshots telling one story at the same steps.\n\nVery frequent rounds buy little: overfitting announces itself over hundreds of steps, not five.": "每多少步跑一轮。一轮对每张评分图片只是一次前向传播——没有梯度，没有优化器——16 张的集合只要几秒；对齐测试图或检查点的节奏，能让图表、图片和快照在同样的步数上讲同一个故事。\n\n太频繁的轮次收益甚微：过拟合是在几百步的尺度上显现的，不是五步。",
  "How many images are set aside for the validation loss. They are taken OUT of training entirely — never visited, in no pool, their captions never seen — because a loss over pictures the model is also memorizing measures nothing. The pick is random but fixed per job, whole images at a time (a picture cannot be half in training), regularization pools are not eligible, and it is capped at half the dataset so the setting can never eat the run it protects.\n\nMore images make a steadier line at a linearly higher cost per round. On a small dataset every held-out image is also a training image lost, which is the real price — 8–16 is usually enough to see the turn, and the job’s log says exactly how many were held out.": "为验证损失留出多少张图片。它们完全退出训练——从不被访问、不在任何池里、说明文字也从不被看到——因为对模型同时在死记的图片计算损失，什么也测不出。挑选是随机的，但每个作业固定，按整张图片进行（一张图不能一半在训练里），正则化池不参与，并且上限是数据集的一半，这样这个设置永远吃不掉它要保护的训练。\n\n图片越多曲线越稳，每轮成本按线性增加。数据集小的时候，每留出一张就少一张训练图，这才是真正的代价——看出转折通常 8–16 张就够，实际留出多少，作业日志里写得清清楚楚。",
  "A second series over ordinary TRAINING images: a fixed slice, re-scored with the same fixed seed each round. Nothing is held out — these stay in training — so it costs no data at all.\n\nWhat it shows is the training curve with the sampling noise removed. The per-step loss jumps around because every step draws different pictures at different noise levels; this line asks the same pictures at the same noise every time, so it is readable where the raw curve is a cloud. Compared against the held-out line it also localizes trouble: both falling is learning, stable falling while held-out rises is memorizing, and neither falling means the run is not learning at all.": "针对普通训练图片的第二条曲线：固定的一小部分，每轮用同一个固定种子重新评分。什么也不留出——它们留在训练中——因此不花费任何数据。\n\n它展示的是去掉采样噪声的训练曲线。逐步损失之所以乱跳，是因为每一步抽的是不同的图片、不同的噪声水平；这条线每次都对同样的图片问同样的问题，在原始曲线只是一团云的地方也能读。与留出曲线对照还能定位问题：两条都在降是在学习；稳定线降而留出线升是在死记；都不降说明训练根本没在学。",
  "Save the current rules, or load a saved set": "保存当前规则，或加载已保存的一组",
  "Rule sets": "规则组",
  "Remember the current rules — name the set in this list afterwards": "记住当前规则 — 之后在此列表中为这组命名",
  "Add a rule first": "请先添加一条规则",
  "Save current rules": "保存当前规则",
  "Add this set's rules to the job — rows it already has stay put": "把这组规则加入任务 — 已有的行保持不变",
  "Value rules": "值规则",
  "Turn numeric value tags (height:172cm) into words at prompt time. The first matching rule wins — drag rows to reorder.": "在组建提示词时把数字值标签 (height:172cm) 变成文字。第一条匹配的规则获胜 — 拖动行可排序。",
  "namespace, e.g. height": "命名空间，例如 height",
  "Keep the raw tag in the prompt beside the rule's text": "在提示词中把原始标签保留在规则文字旁边",
  "keep tag": "保留标签",
  "Remove this rule": "移除这条规则",
  "Add rule": "添加规则",
  "Any tag shaped `<name>:<number><unit>` is a value tag — `people:3`, `height:172cm`, `height:1.72m`, or a ranking’s own `quality:7` — and a rule here turns a range of those numbers into words at prompt time: where `height` is greater than 190cm, write `tall`. A raw `height:172cm` token teaches a text encoder nothing it can read back at generation time; a word does.\n\nA matching tag is replaced by the rule’s text, and a per-rule toggle keeps the raw tag alongside for whoever wants both spellings in the prompt. The metric length and mass families convert, so one rule covers `172cm` and `1.72m` alike; an unknown unit compares only against the same unit, and a plain number only against plain numbers.\n\nRanges may overlap, and the first matching rule wins — the rows are dragged into order, and that order is part of the configuration. A value tag no rule matches passes through the prompt unchanged, so nothing is dropped silently. The rule’s phrase rides the ordinary random pick and dropout like the tag it replaced: prompts sometimes carry it and sometimes do not, which is exactly the variation score-tag conditioning wants.\n\nThe rules are resolved when the dataset is built — the job’s log says how many tags they matched — and a set of rules can be saved and loaded by name, so a house vocabulary is written once and reused across jobs. Loading a set adds its missing rules to the job rather than replacing the rows already there.": "任何形如 `<名称>:<数字><单位>` 的标签都是值标签 — `people:3`、`height:172cm`、`height:1.72m`，或者排行自己的 `quality:7` — 这里的规则会在组建提示词时把一段数字范围变成文字: 当 `height` 大于 190cm 时，写成 `tall`。原始的 `height:172cm` 词元教不会文本编码器任何在生成时能读回的东西；一个词可以。\n\n匹配的标签会被规则的文字替换，每条规则的开关可以把原始标签保留在旁边，供想在提示词里同时保留两种写法的人使用。公制长度和质量家族会换算，所以一条规则同样覆盖 `172cm` 和 `1.72m`；未知单位只与相同单位比较，纯数字只与纯数字比较。\n\n范围可以重叠，第一条匹配的规则获胜 — 行可以拖动排序，而顺序是配置的一部分。没有规则匹配的值标签会原样进入提示词，什么都不会被悄悄丢弃。规则的措辞像被替换的标签一样经过普通的随机挑选和 dropout: 提示词有时带它有时不带，这正是评分标签条件化想要的变化。\n\n规则在构建数据集时解析 — 任务日志会说明匹配了多少标签 — 一组规则可以按名字保存和加载，常用词汇写一次就能跨任务复用。加载一组规则会补上缺少的行，而不是替换已有的行。",
  "Write tags as":
    "标签写作",
  "Their name":
    "标签名",
  "Their comment":
    "标签注释",
  "Name and comment":
    "名称加注释",
  "A tag's comment is the one line beside its name in the Tags tab — the same idea in words a text encoder can read. A tag with no comment is written as its name.":
    "标签的注释是“标签”页中名称旁的那一行 — 用文本编码器能读懂的话表达同一个意思。没有注释的标签按名称书写。",
  "A tag's comment is the one line beside its name in the Tags tab — “one girl in the picture” for `1girl`, “from below, looking up at the subject” for `from_below`. A booru vocabulary is compact for the people typing it and opaque to a text encoder; the comment is the same idea in words the encoder can read.\n\n“Their name” is what every run did: the tag as it is spelled. “Their comment” writes the comment in place of the name wherever a picked tag has one, and “Name and comment” writes the name with the comment in brackets after it, so the model learns both spellings of one thing. A tag with no comment is written as its name whatever this says.\n\nOnly the PROMPT changes. Matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all stay keyed on the tag's name, exactly as with aliases — and the comment is read from the library when the dataset is built, so editing a comment later changes the next run, not this one.":
    "标签的注释是“标签”页中名称旁的那一行 — `1girl` 是“画面中有一个女孩”，`from_below` 是“从下方仰视主体”。booru 词汇对输入的人来说简洁，对文本编码器却不透明；注释是同一个意思，用编码器能读懂的话写出来。\n\n“标签名”是以往每次训练的做法：按拼写原样写出标签。“标签注释”在被选中的标签有注释时用注释代替名称，“名称加注释”则在名称后用括号附上注释，让模型学到同一事物的两种说法。没有注释的标签无论如何都按名称书写。\n\n只有提示词会变。匹配、始终包含/排除列表、频率平衡、损失权重以及裁切必须保留的框，全都仍以标签名称为准，与别名的规则完全一样 — 注释是在构建数据集时从库中读取的，所以之后修改注释影响的是下一次训练，而不是这一次。",
  "Remove the selected images?": "删除所选图片？",
  "They cannot be recovered.": "删除后无法恢复。",
  "Its downloaded weights can go with it, or stay in the cache for a later download to find.": "已下载的权重可以一并删除，也可以留在缓存中供以后的下载使用。",
  "Remove and delete weights": "移除并删除权重",
  "Remove the training job “{name}”?": "删除训练任务“{name}”吗？",
  "Remove {n} training jobs?": "删除 {n} 个训练任务吗？",
  "Its checkpoints, test samples and trained result are deleted with it — except anything locked, which is kept in the LoRAs list. This cannot be undone.": "它的检查点、样图和训练结果会一并删除，且无法撤销。（已锁定的内容会保留在 LoRA 列表中。）",
  "Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone.": "它们的检查点、样图和训练结果会一并删除，且无法撤销。（已锁定的内容会保留在 LoRA 列表中。）",
  "The Train tab": "“训练”标签页",
  "The Evaluate tab": "“评估”标签页",
  "The Models tab": "“模型”标签页",
  "Your models": "你的模型",
  "Finetunes": "微调模型",
  "Based on {model}": "基于 {model}",
  "A full finetune of {model}": "{model} 的完整微调",
  "The built-in release, one of your own models, or a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.": "内置版本、你自己的模型之一，或用完整微调的权重替代基础模型的权重。适配器叠加在此处选择的内容之上。",
};

export default CATALOG;
