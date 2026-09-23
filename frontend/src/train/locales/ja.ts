// territory like locales/de.ts; see docs/translating.md for conventions.

import type { Catalog } from "../../shared/i18nCore";

const CATALOG: Catalog = {
  "default":
    "既定",
  "This model's own size. A job set to it follows whichever model it is pointed at.":
    "このモデル自身のサイズです。これに設定した実行は、指しているモデルに従います。",
  "{n} px":
    "{n} px",
  "A run trains at one size at least.":
    "実行には少なくとも 1 つのサイズが必要です。",
  "A run trains at up to five sizes — each one is another pass over the dataset per epoch.":
    "1 回の実行で使えるサイズは最大 5 つです。1 つ増えるごとに、エポックごとのデータセット走査が 1 周増えます。",
  "e.g. 704":
    "例: 704",
  "Another size…":
    "別のサイズ…",
  "Pick every size this run should train at. A picture joins each one it is big enough for, so the same picture can be learnt at more than one scale — and each size is another pass over the dataset per epoch.":
    "この実行で学習するサイズをすべて選びます。各画像は十分な大きさがあるサイズすべてに加わるため、同じ画像が複数のスケールで学習されます。サイズが 1 つ増えるごとに、エポックごとのデータセット走査が 1 周増えます。",
  "Left empty both fields use the model's own size — a test sample is not tied to the sizes the run trains at.":
    "両方を空にすると、モデル自身のサイズが使われます。テスト画像は学習サイズに縛られません。",
  "The sizes images are trained at, each given as one number that stands for a pixel budget: 1024 means 'about a megapixel', which every aspect-ratio bucket then spends differently — 1024×1024, or 1216×832, or 832×1216.\n\nMatch them to what the base model was trained on (1024 for SDXL, Chroma and FLUX.2, 512 for SD 1.5); training far above that teaches little and costs a lot, while training below it is a genuine speed and memory lever at the price of fine detail. Cost scales with the area, so 768 is nearly half the work per step that 1024 is. The size the list marks as default is the model's own, and a job set to it follows whichever model it is pointed at.\n\nPicking more than one trains the same pictures at each of them. A model that has only ever seen a subject at 1024 has learnt it together with the canvas it was on: asked for something smaller it tends to answer with a crop or a doubled-up version of the same framing. Several sizes separate what the model learns about the subject from what it learns about the shape of the picture.\n\nEach size is a full family of buckets, and every image joins the ones it is large enough for — which is the other half of what this is for. Under Never upscale a 700-pixel scan is simply left out of a 1024 run; add 512 and it trains there instead of being dropped, while the large pictures keep training at both.\n\nIt is not free. A size is another pass over the dataset in every epoch and another cached latent per picture, and the batches at the largest one decide the peak memory — so adding a size above the others raises what the run needs on the card, and adding ones below mainly makes an epoch longer. Two or three an octave apart (512, 768, 1024) is the usual shape; at most five.":
    "画像を学習させるサイズです。それぞれピクセル予算を表す 1 つの数値で指定します。1024 は「おおよそ 1 メガピクセル」を意味し、各アスペクト比バケットがそれを異なる形で使います — 1024×1024、1216×832、832×1216 など。\n\nベースモデルが学習されたサイズに合わせてください（SDXL、Chroma、FLUX.2 は 1024、SD 1.5 は 512）。それを大きく超えて学習しても得るものは少なくコストはかかり、下回る場合は細部と引き換えに速度とメモリの実質的なレバーになります。コストは面積に比例するので、768 は 1024 に対して 1 ステップあたりほぼ半分の作業量です。リストで既定と記されたサイズはモデル自身のもので、それに設定した実行は指しているモデルに従います。\n\n複数選ぶと、同じ画像をそれぞれのサイズで学習します。1024 でしか被写体を見たことのないモデルは、それが載っていたキャンバスごと覚えています。より小さいものを求めると、同じ構図の切り抜きや二重になった版で答えがちです。複数のサイズは、モデルが被写体について学ぶことと画像の形について学ぶことを切り離します。\n\n各サイズは完全なバケット族であり、各画像は十分な大きさがあるものに加わります — これがもう一方の狙いです。「拡大しない」が有効な場合、700 ピクセルのスキャンは 1024 の実行から単に外れます。512 を加えれば、捨てられる代わりにそちらで学習し、大きな画像は両方で学習し続けます。\n\nただし無料ではありません。サイズが 1 つ増えるごとに、エポックごとのデータセット走査が 1 周増え、画像あたりのキャッシュ済み latent が 1 つ増えます。ピークメモリを決めるのは最大サイズのバッチなので、他より大きいサイズを加えるとカードに必要な容量が増え、小さいサイズを加えると主にエポックが長くなります。1 オクターブ間隔で 2〜3 個（512、768、1024）が一般的で、最大 5 個までです。",
  "An image smaller than its bucket has to be enlarged to train at that size, and enlarging invents detail that was never in the picture: soft edges, smeared texture, the interpolation's own look. Trained on, that is what the model learns the subject looks like.\n\nThis is on by default. Those images are left out while the dataset is built — before anything is encoded, so they cost no time and no cache — and the run says how many it dropped. It is asked per resolution, so a picture too small for the largest size still trains at a smaller one rather than being dropped from the run; turn it off for a small dataset, where a slightly soft picture is usually worth more than no picture.":
    "バケットより小さい画像は、そのサイズで学習するために拡大する必要があります。拡大は元の画像になかったディテールを作り出します。ぼやけた輪郭、にじんだテクスチャ、補間そのものの見た目です。それで学習すると、モデルは被写体がそう見えるものだと覚えます。\n\n既定で有効です。該当する画像はデータセットの構築時に除外され — 何もエンコードされる前なので時間もキャッシュも消費しません — 実行が除外した枚数を報告します。判定は解像度ごとに行われるため、最大サイズには小さすぎる画像も、実行から外れる代わりに小さいサイズで学習します。小さなデータセットではオフにしてください。そこでは少しぼやけた画像でも、画像がないよりたいてい価値があります。",
  "New training job": "新しい学習ジョブ",
  "Drafts": "下書き",
  "Paused": "一時停止中",
  "Completed": "完了",
  "Failed": "失敗",
  "Full finetune": "フルファインチューニング",
  "Loss appears here once training starts.": "学習が始まると損失がここに表示されます。",
  "Test samples": "テストサンプル",
  "Select a job to see its progress, samples and settings.": "ジョブを選択すると進捗、サンプル、設定が表示されます。",
  "No training jobs yet. Create one to fine-tune a model (LoRA or full) on images selected straight from your library.": "学習ジョブはまだありません。作成すると、ライブラリから直接選んだ画像でモデルをファインチューニングできます（LoRA またはフル）。",
  "Training environment not set up": "学習環境が未セットアップです",
  "Edit training job": "学習ジョブを編集",
  "Save draft": "下書きを保存",
  "Save & queue": "保存してキューへ",
  "Method": "方式",
  "Hyperparameters": "ハイパーパラメータ",
  "Memory & speed": "メモリと速度",
  "Canceled before any image was generated": "画像が生成される前にキャンセルされました",
  "{done} of {total} images": "{total} 枚中 {done} 枚",
  "not generated yet": "まだ生成されていません",
  "Download this LoRA": "この LoRA をダウンロード",
  "NVIDIA only": "NVIDIA のみ",
  "Off (fused kernels)": "オフ（融合カーネル）",
  "On (save VRAM)": "オン（VRAM 節約）",
  "needs an NVIDIA GPU": "NVIDIA GPU が必要です",
  "needs an NVIDIA GPU (Ada or newer)": "NVIDIA GPU（Ada 以降）が必要です",
  "this model has none": "このモデルにはありません",
  "8-bit float (fp8)": "8 ビット浮動小数（fp8）",
  "8-bit (int8)": "8 ビット（int8）",
  "FLUX.2 Klein (base, 4B)": "FLUX.2 Klein（ベース、4B）",
  "Images are being generated": "画像を生成中です",
  "= 1 image": "= 1 枚",
  "= {n} images": { other: "= {n} 枚" },
  "Length & learning rate": "長さと学習率",
  "Dataset": "データセット",
  "Add query": "クエリを追加",
  "Remove query": "クエリを削除",
  "invalid query": "無効なクエリ",
  "Empty query = every image in the library.": "空のクエリ = ライブラリのすべての画像。",
  "Total steps": "総ステップ数",
  "Learning rate": "学習率",
  "Batch size": "バッチサイズ",
  "Gradient accumulation": "勾配累積",
  "Rank": "ランク",
  "Train text encoder": "テキストエンコーダーを学習",
  "Checkpoints": "チェックポイント",
  "Checkpoint every": "チェックポイント間隔",
  "Cache latents": "潜在表現をキャッシュ",
  "Random crop": "ランダム切り抜き",
  "Resolutions":
    "解像度",
  "Crops & flips":
    "切り抜きと反転",
  "Max aspect ratio": "最大縦横比",
  "Horizontal flip probability": "左右反転の確率",
  "Trigger word": "トリガーワード",
  "Only captions tagged": "使用するキャプションのメタタグ",
  "Skip captions tagged": "除外するキャプションのメタタグ",
  "Only instructions tagged": "使用する指示のメタタグ",
  "Skip instructions tagged": "除外する指示のメタタグ",
  "Comma-separated meta tags whose instructions are never used. Applied after the include list, so it also removes instructions the list let in.": "その指示を決して使わない、カンマ区切りのメタタグです。包含リストの後に適用されるため、リストが通した指示も取り除きます。",
  "Comma-separated meta tags whose captions are never used. Applied after the include list, so it also removes captions the list let in.": "そのキャプションを決して使わない、カンマ区切りのメタタグです。包含リストの後に適用されるため、リストが通したキャプションも取り除きます。",
  "Always include": "常に含める",
  "Skip tag groups tagged": "除外するタググループのメタタグ",
  "Comma-separated meta tags naming whole tag groups to ignore: a tag placed only in such a group never reaches a prompt. The tags stay on your items.": "無視するタググループ全体を指名する、カンマ区切りのメタタグです。そのようなグループにだけ置かれたタグは決してプロンプトに届きません。タグはアイテムに残ります。",
  "Min tags per prompt": "プロンプトあたり最少タグ数",
  "Max tags per prompt": "プロンプトあたり最大タグ数",
  "Pick probability": "選択確率",
  "Uniform": "一様",
  "Balance rare tags": "希少タグのバランス",
  "Frequency measured in": "頻度の測定対象",
  "Training data": "学習データ",
  "Previous step": "前のステップ",
  "Next step": "次のステップ",
  "(empty prompt)": "（空のプロンプト）",
  "Show each step's min/max micro-batch loss": "各ステップのマイクロバッチ損失の最小/最大を表示",
  "Expand graph": "グラフを展開",
  "Collapse graph": "グラフを折りたたむ",
  "steps/s": "ステップ/秒",
  "Smooth the line (EMA)": "線を平滑化（EMA）",
  "Whole library": "ライブラリ全体",
  "Weight loss by tag rarity": "タグの希少度で損失を重み付け",
  "Shuffle tag order": "タグ順をシャッフル",
  "Caption dropout": "キャプション・ドロップアウト",
  "Generate every": "生成間隔",
  "Negative prompt": "ネガティブプロンプト",
  "Nothing (trigger word only)": "なし（トリガーワードのみ）",
  "Every prompt is the trigger word and nothing else, so every selected picture is in the run whatever it carries. Tag and caption selection do not apply.": "プロンプトはトリガーワードだけになるため、選択された画像は内容にかかわらずすべて学習に含まれます。タグと説明文の選択は適用されません。",
  "Every prompt would be EMPTY — with no text at all, there is nothing for the model to bind what it sees to. Set a trigger word below.": "プロンプトが空になります — テキストがまったくないと、モデルは見たものを結び付ける先を持ちません。下でトリガーワードを設定してください。",
  "Caption + tags": "キャプション + タグ",
  "Pause (saves a checkpoint)": "一時停止（チェックポイントを保存）",
  "{d} trained": "{d} 学習",
  "Training started": "学習を開始",
  "Training resumed": "学習を再開",
  "Training paused": "学習を一時停止",
  "Training completed": "学習が完了",
  "Training failed": "学習が失敗",
  "Training canceled": "学習をキャンセル",
  "Baseline before training": "学習前のベースライン",
  "Checkpoint": "チェックポイント",
  "Download checkpoint": "チェックポイントをダウンロード",
  "Delete checkpoint": "チェックポイントを削除",
  "Delete this checkpoint from disk?": "このチェックポイントをディスクから削除しますか？",
  "Extend steps": "ステップを延長",
  "Edit steps": "ステップを編集",
  "Base model": "ベースモデル",
  "LoRAs": "LoRA",
  "Edit this model": "このモデルを編集",
  "Edit model": "モデルを編集",
  "Edit LoRA": "LoRA を編集",
  "Edit this LoRA": "この LoRA を編集",
  "Unlock": "ロック解除",
  "Lock": "ロック",
  "Unlock — deleting the job will take this LoRA with it": "ロック解除 — ジョブを削除するとこの LoRA も消えます",
  "Lock — keeps this LoRA when the job is deleted": "ロック — ジョブを削除してもこの LoRA を残します",
  "Lock — protects this checkpoint from deletion, from the keep-last rule, and from the job being deleted": "ロック — このチェックポイントを削除・直近 N 件保持ルール・ジョブの削除から守ります",
  "Add LoRA": "LoRA を追加",
  "Click to use this value for the next generation": "クリックでこの値を次の生成に使う",
  "Output": "出力",
  "Size presets": "サイズプリセット",
  "Random seed": "ランダムシード",
  "A new seed is drawn each time you click Generate; the field below shows the seed used for the last generation.": "生成をクリックするたびに新しいシードが引かれます。下のフィールドは前回の生成で使われたシードを示します。",
  "Remove this generation and its images?": "この生成とその画像を削除しますか？",
  "Open the image in a new tab": "画像を新しいタブで開く",
  "Remove the selected images? They cannot be recovered.": "選択した画像を削除しますか？元に戻すことはできません。",
  "Remove the selected images (a generation that is still running stays)": "選択した画像を削除（実行中の生成は残ります）",
  "Stop the selected generations (the images they have made are kept)": "選択した生成を停止（すでに生成された画像は残ります）",
  "Put every setting that made this picture into the form": "この画像を生成したすべての設定をフォームに入れる",
  "Use all settings": "すべての設定を使う",
  "Preview the selected image (Space)": "選択した画像をプレビュー（スペース）",
  "Image {i} of {n}": "画像 {i} / {n}",
  "Up next": "次に実行",
  "Add to the queue": "キューに追加",
  "A training job is running": "学習ジョブが実行中です",
  "Drag to change the queue order": "ドラッグでキューの順序を変更",
  "How the drafts below are ordered":
    "下の下書きの並び順",
  "Newest first":
    "新しい順",
  "Manual order":
    "手動の並び",
  "Drag to reorder — or into Up next to queue the job":
    "ドラッグで並べ替え — 「次に実行」へドラッグするとキューに入ります",
  "Remove every finished job, with its checkpoints and samples":
    "完了したジョブをチェックポイントとサンプルごとすべて削除",
  "Drag into Up next to queue the job": "「次に実行」へドラッグしてジョブをキューに入れる",
  "Drop here to put the job on hold.": "ここにドロップするとジョブは保留になります。",
  "Prepare": "準備",
  "Keep the last": "最新を保持",
  "When a new snapshot is written the oldest of these is deleted, so the window never grows. A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk. The resumable checkpoint is kept outside this limit and never counts against it.": "新しいスナップショットが書かれると、この中で最古のものが削除されるため、ウィンドウが育つことはありません。LoRA のスナップショットは小さく（数十 MB）、1 ダースでも余裕で残せます。フルファインチューニングのスナップショットはモデル全体のサイズなので、2〜3 個で既にかなりのディスクです。再開用チェックポイントはこの上限の外に保持され、数に入りません。",
  "Also keep one in": "加えて保持する間隔",
  "A rolling window at the end of the run. 0 keeps none by recency.": "実行末尾のローリングウィンドウです。0 なら新しさによる保持はありません。",
  "Kept for good, on top of the window above.": "上のウィンドウに加えて、恒久的に保持されます。",
  "A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk.": "LoRA のスナップショットは小さく（数十 MB）、1 ダースでも余裕で残せます。フルファインチューニングのスナップショットはモデル全体のサイズなので、2〜3 個で既にかなりのディスクです。",
  "in 1 step": "あと 1 ステップ",
  "in {n} steps": { other: "あと {n} ステップ" },
  "Keep as checkpoint": "チェックポイントとして保持",
  "Backward": "逆伝播",
  "warmup": "ウォームアップ",
  "Settings changed": "設定を変更",
  "Dataset changed": "データセットが変更されました",
  "{n} items added":
    { other: "{n} 件のアイテムを追加" },
  "{n} items removed":
    { other: "{n} 件のアイテムを削除" },
  "Measured over the last steps of this run": "この実行の直近のステップで測定",
  "about {d} left": "残り約 {d}",
  "The images this run trains on, sorted into aspect-ratio buckets": "この実行が学習する画像、縦横比バケット別",
  "{n} images": { other: "{n} 枚の画像" },
  "{n} from video": { other: "うち動画から {n} 枚" },
  "{n} buckets": { other: "{n} 個のバケット" },
  "Training job settings": "学習ジョブの設定",
  "Save as new job": "新しいジョブとして保存",
  "Hide system statistics": "システム統計を隠す",
  "Show system statistics": "システム統計を表示",
  "loading model": "モデルを読み込み中",
  "caching latents": "潜在表現をキャッシュ中",
  "Degradation": "劣化",
  "Add variant": "バリアントを追加",
  "Remove every variant from this job": "このジョブからすべてのバリアントを削除",
  "Remove this variant": "このバリアントを削除",
  "JPEG re-encode": "JPEG 再エンコード",
  "Video codec (h264 / h265)": "動画コーデック（h264 / h265）",
  "Resolution loss": "解像度損失",
  "JPEG": "JPEG",
  "video codec": "動画コーデック",
  "resolution loss": "解像度損失",
  "Chroma subsampling": "クロマサブサンプリング",
  "How much color detail is thrown away. 4:2:0 is what almost every real JPEG uses.": "どれだけ色のディテールを捨てるかです。4:2:0 は現実のほぼすべての JPEG が使うものです。",
  "Codec": "コーデック",
  "CRF": "CRF",
  "The codec's quality number, counting the other way round: HIGHER is worse. Above about 32 a frame visibly falls apart.": "コーデックの品質値で、数え方は逆向きです。高いほど悪い。32 を超えたあたりでフレームは目に見えて崩れます。",
  "Scale": "スケール",
  "Nearest gives the hard, blocky look of a badly upscaled screenshot; bilinear the soft one.": "ニアレストは下手にアップスケールしたスクリーンショットの硬いブロック状の見た目、バイリニアは柔らかい見た目になります。",
  "Bilinear": "バイリニア",
  "Bicubic": "バイキュービック",
  "Lanczos": "Lanczos",
  "Passes": "パス数",
  "Visits per clean visit": "クリーン訪問あたりの訪問数",
  "How often this variant is drawn beside the picture it was made from. 0.25 = one degraded visit per four clean ones.": "元になった画像の横で、このバリアントがどれくらいの頻度で引かれるかです。0.25 = クリーン 4 回につき劣化 1 回。",
  "Cached variations per picture": "画像あたりのキャッシュされるバリエーション",
  "How many separately-drawn values each picture gets. 1 already spreads the range across the dataset; more spreads it within one picture, and multiplies the cache.": "各画像が個別に引かれる値をいくつ得るかです。1 でも範囲はデータセット全体に広がります。増やすと 1 枚の中に広がり、キャッシュが倍増します。",
  "jpeg_artifacts, low_quality": "jpeg_artifacts, low_quality",
  "Always in this sample's prompt: never dropped by the random tag pick, the tag cap, or caption dropout.": "このサンプルのプロンプトに常に含まれます。ランダムなタグ選択、タグ上限、キャプション・ドロップアウトのどれにも落とされません。",
  "Remove tags if present": "あれば除去するタグ",
  "masterpiece, absurdres": "masterpiece, absurdres",
  "Which pictures": "どの画像",
  "Only pictures tagged": "対象にする画像のタグ",
  "Never pictures tagged": "対象にしない画像のタグ",
  "Wins over the line above. Use it to leave pictures alone that are already marked as poor.": "上の行に勝ちます。すでに低品質と印の付いた画像に手を付けないために使ってください。",
  "The preview failed": "プレビューに失敗しました",
  "Select an item in the library to preview this on.": "これをプレビューするアイテムをライブラリで選択してください。",
  "gentlest": "最も穏やか",
  "harshest": "最も過酷",
  "Variants": "バリアント",
  "Save the current variants, or load a saved set": "現在のバリアントを保存、または保存済みのセットを読み込み",
  "Save current variants": "現在のバリアントを保存",
  "Add a variant first": "先にバリアントを追加してください",
  "Load this set, replacing the variants in this job": "このセットを読み込み、ジョブのバリアントを置き換える",
  "Of every 100 visits to a picture this applies to, {clean} are clean and the rest are degraded: {parts}.": "これが適用される画像への 100 回の訪問のうち、{clean} 回はクリーンで、残りは劣化です: {parts}。",
  "A variant with a tag filter applies to fewer pictures than the queries select, so its share is of those.": "タグフィルター付きのバリアントは、クエリが選ぶより少ない画像に適用されるため、その取り分はそれらの中での話です。",
  "About {n} degraded files will be cached.": "約 {n} 個の劣化ファイルがキャッシュされます。",
  "Preset": "プリセット",
  "Presets": "プリセット",
  "Preset name": "プリセット名",
  "Save these settings as a preset, or load one": "これらの設定をプリセットとして保存、またはひとつ読み込み",
  "Save current settings": "現在の設定を保存",
  "Start new jobs from this preset": "新しいジョブをこのプリセットから始める",
  "Delete this preset": "このプリセットを削除",
  "Cosine": "コサイン",
  "Base models": "ベースモデル",
  "1 result": "1 件の結果",
  "{n} results": { other: "{n} 件の結果" },
  "Session": "セッション",
  "No adapters": "アダプターなし",
  "Delete all {n} results from this session? The generated images go with them.": "このセッションの {n} 件の結果をすべて削除しますか？生成された画像も一緒に消えます。",
  "sampling": "サンプリング",
  "What does this do?": "これは何をする？",
  "This model's repository is gated: accept its license on the model page and set a Hugging Face access token, or the download will fail.": "このモデルのリポジトリはゲート付きです。モデルページでライセンスに同意し、Hugging Face のアクセストークンを設定してください。さもないとダウンロードは失敗します。",
  "Click to use this prompt for the next generation": "クリックでこのプロンプトを次の生成に使う",
  "(no prompt)": "（プロンプトなし）",
  "Click to use this negative prompt for the next generation": "クリックでこのネガティブプロンプトを次の生成に使う",
  "Time so far, including loading the model": "これまでの時間（モデルの読み込み込み）",
  "Total time, including loading the model": "合計時間（モデルの読み込み込み）",
  "Remove from the queue": "キューから削除",
  "Select to copy": "選択してコピー",
  "generation failed": "生成に失敗しました",
  "Sampler steps": "サンプラーステップ",
  "CFG scale": "CFG スケール",
  "This model isn't downloaded yet, and downloads are switched off": "このモデルはまだダウンロードされておらず、ダウンロードはオフになっています",
  "Loss": "損失",
  "LoRA only": "LoRA のみ",
  "Native training resolution of these weights. Leave empty for the architecture's own.": "この重みのネイティブ学習解像度です。空ならアーキテクチャ自身のものを使います。",
  "Includes 1 model you added.": "自分で追加したモデル 1 件を含みます。",
  "Includes": "含む:",
  "models you added.": "自分で追加したモデル。",
  "Open this model's page on Hugging Face": "このモデルのページを Hugging Face で開く",
  "Remove this model": "このモデルを削除",
  "Based on": "ベース",
  "/path/to/model (diffusers folder or .safetensors)": "/path/to/model（diffusers フォルダまたは .safetensors）",
  "owner/repo": "owner/repo",
  "Add model": "モデルを追加",
  "On disk": "ディスク上",
  "Path missing": "パスがありません",
  "Continue this download where it stopped": "止まったところからダウンロードを続ける",
  "Partly downloaded": "一部ダウンロード済み",
  "Discard partial download": "部分ダウンロードを破棄",
  "This path no longer exists": "このパスはもう存在しません",
  "Remove from the list (the file is left alone)": "リストから削除（ファイルには手を付けません）",
  "The base model this LoRA was trained for": "この LoRA の学習対象のベースモデル",
  "/path/to/lora.safetensors": "/path/to/lora.safetensors",
  "Download this checkpoint": "このチェックポイントをダウンロード",
  "Delete this checkpoint from disk": "このチェックポイントをディスクから削除",
  "Relative sampling probability: a weight-2 query's images are drawn twice as often as a weight-1 query's.": "相対的なサンプリング確率です。重み 2 のクエリの画像は、重み 1 のクエリの 2 倍の頻度で引かれます。",
  "Steps": "ステップ",
  "Text encoder": "テキストエンコーダー",
  "trained": "学習済み",
  "Prompts": "プロンプト",
  "Samples": "サンプル",
  "Training log": "学習ログ",
  "No output yet.": "出力はまだありません。",
  "about {v} of GPU memory": "GPU メモリ約 {v}",
  "more than this machine's {m}": "このマシンの {m} を超えています",
  "e.g. watercolor style LoRA": "例: watercolor style LoRA",
  "Model-specific": "モデル固有",
  "Optimization": "最適化",
  "LR schedule": "学習率スケジュール",
  "Constant": "コンスタント",
  "Linear decay": "線形減衰",
  "Constant + warmup": "コンスタント + ウォームアップ",
  "Warmup steps": "ウォームアップステップ",
  "Ramp the learning rate up over the first N steps. Leave empty for no warmup.": "最初の N ステップで学習率を立ち上げます。空ならウォームアップなし。",
  "bf16 is the safe modern default. fp32 doubles memory (automatic fallback on Macs without bf16); avoid fp16 for training.": "bf16 が安全な現代のデフォルトです。fp32 はメモリを倍にします（bf16 のない Mac では自動フォールバック）。学習で fp16 は避けてください。",
  "Makes sampling, crops and tag picks reproducible.": "サンプリング、切り抜き、タグ選択を再現可能にします。",
  "LoRA": "LoRA",
  "Scales the adapter's effect; the common convention is alpha = rank. Lower alpha = weaker influence at the same rank.": "アダプタの効果をスケールします。一般的な慣例は alpha = rank。低いアルファ = 同じランクでより弱い影響。",
  "Helps the model learn a NEW trigger word, at higher overfitting risk. Guarded: it uses a lower learning rate and stops partway through training.": "新しいトリガーワードの学習を助けます。過学習リスクは高めです。防御付き: 低めの学習率を使い、学習の途中で止まります。",
  "Text encoder LR": "テキストエンコーダー LR",
  "Left empty: half the main learning rate.": "空の場合: メイン学習率の半分。",
  "Stop TE after": "TE 停止時点",
  "Include the large encoder": "大きなエンコーダーも含める",
  "T5-XXL, the encoder that reads the whole prompt — most of the memory and most of the effect. Unticked, only the small CLIP-L trains: cheap, and what most FLUX LoRA tools mean by training the text encoder.": "プロンプト全体を読む T5-XXL で、メモリと効果の大部分を占めます。オフにすると小さな CLIP-L だけを学習します。負荷が軽く、多くの FLUX 用 LoRA ツールが「テキストエンコーダーを学習」と呼ぶのはこちらです。",
  "of total steps": "（総ステップ比）",
  "Keep step snapshots": "ステップスナップショットを保持",
  "Save a permanent snapshot every N steps, so the best-looking step can be picked afterwards. Off: only the resumable 'last' checkpoint is kept.": "N ステップごとに恒久的なスナップショットを保存し、後から一番よく見えるステップを選べるようにします。オフ: 再開用の「last」チェックポイントだけが保持されます。",
  "Gradient checkpointing": "勾配チェックポイント",
  "Trades ~25% speed for a large VRAM saving. Recommended for full finetunes and big models.": "約 25% の速度と引き換えに VRAM を大きく節約します。フルファインチューニングと大きなモデルで推奨。",
  "Attention slicing": "アテンションスライス",
  "Half-precision master weights": "半精度のマスター重み",
  "Keeps the trained weights and their gradients at 16 bits instead of 32. What the rounding drops is carried to the next update, so the run learns what it would have learned; the cost is one more buffer of the same width.":
    "学習される重みとその勾配を 32 ビットではなく 16 ビットで保持します。丸めで失われる分は次の更新に繰り越されるため、学習は本来の結果に到達します。代償は同じ幅のバッファーがもう 1 つ必要になることです。",
  "only for a full finetune": "フルファインチューニング専用",
  "nothing to halve at full precision": "完全精度では半分にするものがありません",
  "Prodigy cannot be stepped one weight at a time": "Prodigy は重みごとに実行できません",
  "Base model quantization": "ベースモデルの量子化",
  "None (full precision)": "なし（フル精度）",
  "4-bit (NF4)": "4 ビット（NF4）",
  "Optimizer": "オプティマイザ",
  "Images are sorted into width/height buckets of equal area so nothing gets squashed. This caps how extreme the buckets get (2 = up to 2:1 and 1:2).": "画像は面積の等しい幅/高さのバケットに振り分けられ、何も潰されません。これはバケットがどこまで極端になれるかの上限です（2 = 最大 2:1 と 1:2）。",
  "Never flip images whose tags are marked": "タグに次のメタタグが付く画像は反転しない",
  "Comma-separated META tags. Any tag the library marks with one of these switches mirroring off for the pictures carrying that tag — so the rule is stated once in the Tags tab rather than listed here.": "カンマ区切りのメタタグ。ライブラリがこれで印を付けたタグは、そのタグを持つ画像の反転を無効にします。ルールはここに並べるのではなく、タグタブで一度だけ述べられます。",
  "Always include tags marked": "次のメタタグが付くタグは常に含める",
  "Comma-separated META tags. Any tag the library marks with one of these is never dropped by the random pick — again, only where the image actually has that tag.": "カンマ区切りのメタタグ。ライブラリがこれで印を付けたタグはランダム選択で決して外れません。こちらも、画像が実際にそのタグを持つ場合のみです。",
  "Exclude tags marked": "次のメタタグが付くタグを除外",
  "Comma-separated META tags. Any tag the library marks with one of these is stripped from prompts.": "カンマ区切りのメタタグ。ライブラリがこれで印を付けたタグはプロンプトから取り除かれます。",
  "Remove tags marked": "次のメタタグが付くタグを削除",
  "Comma-separated META tags. Any tag the library marks with one of these comes off this sample.": "カンマ区切りのメタタグ。ライブラリがこれで印を付けたタグはこのサンプルから外れます。",
  "Only pictures whose tags are marked": "タグに次のメタタグが付く画像のみ",
  "Comma-separated META tags — the same rule as the line above, said once in the library rather than tag by tag here.": "カンマ区切りのメタタグ — 上の行と同じルールを、ここでタグごとに並べる代わりにライブラリで一度述べたものです。",
  "Never pictures whose tags are marked": "タグに次のメタタグが付く画像は対象外",
  "Comma-separated META tags. Wins over both lines above.": "カンマ区切りのメタタグ。上の2行より優先されます。",
  "The same veto, said once in the library instead of tag by tag here. Any tag the Tags tab marks with one of these meta tags switches mirroring off for every picture carrying that tag.\n\nIt is worth the indirection for the reason a list of names goes stale: “text”, “logo”, “signature”, “left-handed”, a dozen characters with an eyepatch — the list in a job's settings is right the day it is written and wrong the next time somebody adds a tag it should have held. Marking the tags themselves puts the fact where the tag is, so a tag added later carries it into every run automatically, and a job written before that tag existed still does the right thing.\n\nBoth lists apply: a picture is left unmirrored if it carries a tag named above OR a tag marked here.":
    "同じ拒否を、ここでタグごとに並べる代わりにライブラリで一度だけ述べたものです。タグタブがこれらのメタタグのいずれかで印を付けたタグは、そのタグを持つすべての画像で反転を無効にします。\n\nこの間接性が見合うのは、名前のリストが古びるのと同じ理由からです。「text」「logo」「signature」「left-handed」、眼帯をした十数人のキャラクター — ジョブの設定にあるリストは書いた日には正しく、それに入るべきタグを誰かが追加した次の瞬間には正しくありません。タグ自体に印を付ければ、その事実はタグのある場所に置かれます。後から追加されたタグはひとりでにそれをすべての実行へ持ち込み、そのタグが存在する前に書かれたジョブも正しく振る舞います。\n\n両方のリストが効きます。画像は、上で名指しされたタグ、または ここで印を付けられたタグを持つとき、反転されません。",
  "The rule above, named by what the library says ABOUT a tag rather than by the tag. Any tag marked with one of these meta tags bypasses the random pick — again only where the image actually has it.\n\nA meta tag put on “watermark”, “signature” and “logo” once means every run treats them that way, including runs written before the third of them existed. The two lists are unioned, so naming a tag here and above is simply the same instruction twice.":
    "上のルールを、タグそのものではなく、ライブラリがそのタグについて述べていることで指定したものです。これらのメタタグのいずれかが付いたタグはランダム選択を素通りします — こちらも、画像が実際にそのタグを持つ場合に限ります。\n\n「watermark」「signature」「logo」に一度メタタグを付ければ、すべての実行がそれらをそのように扱います。三つめが存在する前に書かれた実行も含めてです。二つのリストは統合されるので、あるタグをここと上の両方に書くのは、同じ指示を二度書いているだけです。",
  "The same, one level up: any tag the library marks with one of these meta tags is stripped from every prompt.\n\nThis is the one to reach for when the exclusions are a KIND of tag rather than a list of them. Quality ratings, scan notes, the booru's own housekeeping words — mark them “noprompt” in the Tags tab and every run drops them, instead of every job carrying a list that has to grow with the vocabulary.\n\nIt is not the same as a skipped tag GROUP below. This one is about the tag wherever it appears; that one is about a grouping on one item, and a tag placed in an excluded group and also somewhere else survives it.":
    "同じことを一段上で。ライブラリがこれらのメタタグのいずれかで印を付けたタグは、すべてのプロンプトから取り除かれます。\n\n除外がタグの一覧ではなくタグの「種類」であるときに手を伸ばすのがこれです。品質評価、スキャンのメモ、booru 内輪の管理用語 — タグタブでそれらに「noprompt」と印を付ければ、すべての実行がそれらを落とします。語彙とともに伸ばしていかねばならないリストを、ジョブごとに抱える代わりにです。\n\nこれは下にあるタググループのスキップとは違います。こちらは、そのタグがどこに現れようとそれについての話です。あちらは一つの項目上のグルーピングについての話で、除外されたグループとそれ以外の両方に置かれたタグはそれを生き延びます。",
  "The list above, named by what the library says about a tag. Any tag marked with one of these meta tags comes off this sample.\n\nWhat it is for is that the claims a degraded copy no longer supports are a CATEGORY, not a list: 'masterpiece', 'absurdres', 'high quality', 'official art' and whatever the next dump adds are all \"a claim about the picture's quality\". Marking them once means every variant of every job drops them, and the same mark can then say something different per method — a 'resolution_claim' mark belongs on a resize variant's list, a 'fidelity_claim' on a JPEG one.":
    "上のリストを、ライブラリがそのタグについて述べていることで指定したものです。これらのメタタグのいずれかが付いたタグは、このサンプルから外れます。\n\n何のためかというと、劣化コピーがもはや支えられない主張は「一覧」ではなく「カテゴリ」だからです。「masterpiece」「absurdres」「high quality」「official art」、そして次のダンプが加えるものはすべて「画質についての主張」です。一度印を付ければ、すべてのジョブのすべてのバリアントがそれらを落とします。そして同じ印が手法ごとに違うことを言えます —「resolution_claim」の印はリサイズのバリアントのリストに、「fidelity_claim」は JPEG のバリアントのリストに属します。",
  "The line above by mark rather than by name: a picture is degraded only if it carries a tag the library marks this way.\n\nChecked against the picture's effective tags, so a tag it only carries by implication counts too. With both lists empty, every picture is fair game.":
    "上の行を、名前ではなく印で。画像は、ライブラリがこのように印を付けたタグを持つ場合にのみ劣化させられます。\n\n判定は画像の実効タグに対して行われるので、含意によってしか持っていないタグも数に入ります。両方のリストを空のままにすれば、どの画像も対象です。",
  "The veto by mark, and it wins over both lines above exactly as the named list does.\n\nThe pair is what makes a degrading run safe on a mixed library: mark the pictures that are already poor — a 'low_quality' or 'rescan' mark on the tags that say so — and no variant can ever degrade one of them further, however broadly the \"only pictures\" side is drawn.":
    "印による拒否です。名前のリストとまったく同じように、上の二行より優先されます。\n\n混ざったライブラリで劣化の実行を安全にするのは、この組み合わせです。すでに質の低い画像に印を付けておけば —「low_quality」や「rescan」を、そう述べているタグに付けておけば — 「対象の画像」の側をどれほど広く取っても、どのバリアントもそれらをさらに劣化させることはできません。",
  "Never flip images tagged": "反転しない画像のタグ",
  "Comma-separated tags that switch mirroring off for the images carrying them, e.g. 'text'. Everything else still flips.": "それを持つ画像の反転をオフにする、カンマ区切りのタグです。例: 'text'。それ以外は引き続き反転されます。",
  "Use alpha as a loss mask": "アルファを損失マスクとして使う",
  "For cut-out images (transparent background): train on the visible pixels and largely ignore the rest. Images without transparency are unaffected.": "切り抜き画像（透明な背景）用です。見えるピクセルで学習し、残りはほぼ無視します。透明のない画像は影響を受けません。",
  "Background weight": "背景の重み",
  "Build prompts from": "プロンプトの組み立て元",
  "What each training prompt is made of: the item's caption text, its tags, caption followed by tags, or nothing but the trigger word.": "各学習プロンプトの構成：アイテムの説明文、そのタグ、説明文のあとにタグ、またはトリガーワードのみ。",
  "Prepended to every prompt. Use a rare token (e.g. 'ohwx style') you'll later type to invoke the trained concept.": "すべてのプロンプトの先頭に付きます。後で入力して学習した概念を呼び出す、珍しいトークン（例: 'ohwx style'）を使ってください。",
  "Each image trains as the RESULT of one of its instructions, with that instruction's reference images as the input. Items carrying no instruction are left out of the run, and tag selection does not apply.": "各画像は自分の指示のひとつの結果として学習され、その指示の参照画像が入力になります。指示のないアイテムは実行から外れ、タグ選択は適用されません。",
  "Tag selection": "タグ選択",
  "Tags are re-picked and re-shuffled fresh every time an image is visited.": "画像の訪問のたびにタグは新しく選び直され、シャッフルし直されます。",
  "Comma-separated tags stripped from prompts (e.g. quality tags or the concept itself when using a trigger word).": "プロンプトから取り除く、カンマ区切りのタグです（例: 品質タグや、トリガーワード使用時の概念そのもの）。",
  "no limit": "上限なし",
  "Lower bound of the random pick. Both limits empty = use all tags.": "ランダム選択の下限です。両方空 = すべてのタグを使用。",
  "Upper bound of the random pick. Picking a random subset each visit teaches tags independently instead of as a fixed clump.": "ランダム選択の上限です。訪問ごとにランダムなサブセットを選ぶことで、固定のかたまりではなくタグを個別に教えます。",
  "Whether a tag's rarity is measured within the selected training images or across the whole library.": "タグの希少さを、選択した学習画像の中で測るか、ライブラリ全体で測るかです。",
  "Skip partially matching tags": "部分一致するタグをスキップ",
  "Standard practice: prevents the model from binding concepts to a fixed tag position.": "標準的な慣行です。モデルが概念を固定のタグ位置に結び付けるのを防ぎます。",
  "Underscores to spaces": "アンダースコアを空白に",
  "Tag separator": "タグ区切り",
  "Joins the prompt parts; comma + space is the standard.": "プロンプトの部品をつなぎます。カンマ + 空白が標準です。",
  "Generate preview images with the in-training model to watch progress in the job's timeline.": "学習中のモデルでプレビュー画像を生成し、ジョブのタイムラインで進捗を見守ります。",
  "Generate test samples": "テストサンプルを生成",
  "Sample seed": "サンプルシード",
  "Fixed per prompt so consecutive samples differ only by training progress.": "プロンプトごとに固定され、連続するサンプルの違いは学習の進み具合だけになります。",
  "Test prompts": "テストプロンプト",
  "negative prompt (optional)": "ネガティブプロンプト（省略可）",
  "Use the shared size for this prompt": "このプロンプトに共有サイズを使う",
  "Give this prompt its own size": "このプロンプトに専用サイズを与える",
  "Remove this prompt": "このプロンプトを削除",
  "Add prompt": "プロンプトを追加",
  "Remove every prompt from this job": "このジョブからすべてのプロンプトを削除",
  "Remove all": "すべて削除",
  "Save the current prompts, or load a saved set": "現在のプロンプトを保存、または保存済みのセットを読み込み",
  "Write a prompt first": "先にプロンプトを書いてください",
  "Save current prompts": "現在のプロンプトを保存",
  "Set name": "セット名",
  "Load this set into the job": "このセットをジョブに読み込む",
  "Delete this set": "このセットを削除",
  "train from scratch": "ゼロから学習",
  "Finished result": "完成した結果",
  "Intermediate checkpoint": "途中のチェックポイント",
  "Continues": "継続元",
  "Train on video frames": "動画フレームで学習",
  "Off, a video the queries match is skipped. On, its frames are extracted while the dataset is built, trained on as images, and deleted with the run.": "オフの場合、クエリに一致する動画はスキップされます。オンの場合、データセット構築時にフレームが抽出され、画像として学習され、実行と一緒に削除されます。",
  "One frame every": "フレーム間隔",
  "Interval unit": "間隔の単位",
  "Seconds follows the clock whatever the frame rate; frames counts the file's own frames.": "秒はフレームレートに関わらず時計に従い、フレームはファイル自身のフレームを数えます。",
  "Drop repeated frames": "繰り返しフレームを除外",
  "A shot held for five seconds is one picture, not five. Each kept frame is compared with the ones already kept from the same video.": "5 秒続くショットは 1 枚の絵であって 5 枚ではありません。残される各フレームは、同じ動画から既に残されたものと比較されます。",
  "Label each block with": "各ブロックのラベル",
  "The subjects it is about": "それが指す被写体",
  "The tag group's name": "タググループの名前",
  "Between groups": "グループの間",
  "Group tags by tag group": "タグをタググループごとにまとめる",
  "Lay the picked tags out one block per tag group instead of one flat list, so what belongs to the same thing in the picture stays together.": "選ばれたタグを平坦なひとつのリストではなく、タググループごとに 1 ブロックで並べます。絵の中で同じものに属するものが一緒に留まります。",
  "Put between blocks. A newline by default, which is what makes them read as separate statements.": "ブロックの間に置かれます。デフォルトは改行で、それがブロックを別々の文として読めるものにします。",
  "Includes {n} models you added.": { other: "自分で追加したモデル {n} 件を含みます。" },
  // The job list's selection bar.
  "Remove {n} training jobs? Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone.":
    "{n} 件の学習ジョブを削除しますか？チェックポイント、サンプル、学習結果も一緒に削除され、元に戻せません。（ロックされたものは LoRA 一覧に残ります。）",
  "Remove the selected jobs — a running job is left alone":
    "選択したジョブを削除 — 実行中のものはそのまま残ります",
  "Remove the selected jobs, with their checkpoints and samples":
    "選択したジョブを、チェックポイントとサンプルごと削除",
  // The Models page: adding a model, and removing one.
  "Remove “{name}” from the model list?":
    "「{name}」をモデル一覧から外しますか？",
  "Delete the downloaded weights as well? They can be downloaded again later.":
    "ダウンロード済みの重みも削除しますか？あとで再ダウンロードできます。",
  "Which model these weights are a version of — it decides the engine, the hyperparameters and the memory profile":
    "この重みがどのモデルの派生か — エンジン、ハイパーパラメータ、メモリ特性が決まります",
  "owner/repo, or a path on this machine":
    "owner/repo、またはこのマシン上のパス",
  "A Hugging Face repository, or a diffusers folder or .safetensors file on this machine — which one it is is read off what you type.":
    "Hugging Face のリポジトリか、このマシン上の diffusers フォルダーまたは .safetensors ファイル。どちらかは入力内容から判別します。",
  "Read as a path on this machine":
    "このマシン上のパスとして読み取りました",
  "Read as a Hugging Face repository":
    "Hugging Face のリポジトリとして読み取りました",
  "Left unnamed, the model is listed under its repository or path":
    "名前がなければ、リポジトリまたはパスの名前で表示されます",
  // The Models page's LoRA lists, grouped by architecture.
  "No LoRAs yet — add a file above, or finish a training job.":
    "LoRA はまだありません — 上でファイルを追加するか、学習を終わらせてください。",
  "These work on any model of this architecture. Each row says which one it was trained for.":
    "このアーキテクチャのどのモデルでも使えます。各行はどのモデル向けに学習したかを示します。",
  // The Evaluate tab: the LoRA rows, and the results grid.
  "Strength":
    "強さ",
  "no image":
    "画像なし",
  "Weights": "重み",
  "File": "ファイル",
  "Trained for": "対象モデル",
  "defaults to the file name": "既定ではファイル名",
  "Waiting…": "待機中…",
  "Another download is running": "別のダウンロードが実行中です",
  "macOS keeps GPU temperature and power for root only. To see them here, allow this one command without a password, then press Try again:":
    "macOS は GPU の温度と電力を root にのみ公開します。ここで表示するには、このコマンドだけをパスワードなしで許可してから「再試行」を押してください:",
  "Check again — no restart needed once the rule is in":
    "もう一度確認 — ルールを追加すれば再起動は不要です",
  "Copied": "コピーしました",
  "Press ⌘C to copy it": "⌘C でコピーできます",
  "Write tags as an alias": "タグをエイリアスで書く",
  "Chance of writing a picked tag as one of its aliases instead of its own name, rolled per tag every time an image is visited.":
    "選ばれたタグを自身の名前ではなくエイリアスの一つで書く確率。画像を訪れるたびにタグごとに抽選されます。",
  "Your library's aliases are the other words for one thing — “cat”, “kitty”, “feline”. Assigning any of them stores the canonical name, so every prompt says the same word and the model learns to answer to that word alone; at generation time the others do less, or nothing.\n\nWith this above 0, each picked tag is sometimes written as one of its aliases instead. The roll happens per tag per visit, so one image seen twice reads differently and the whole vocabulary is spread across the run rather than one alias being chosen per tag and then repeated.\n\nOnly the PROMPT changes. Tag matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all keep using the canonical name — so this cannot skew any of them. A tag with no aliases is always written as itself, and 0 is exactly what every run did before this setting existed.":
    "ライブラリのエイリアスは同じものを指す別の言葉です（「cat」「kitty」「feline」）。どれを付けても保存されるのは正規名なので、どのプロンプトも同じ語になり、モデルはその語にだけ反応するよう学習します。生成時、他の語はほとんど、あるいはまったく効きません。\n\n0 より大きくすると、選ばれたタグが時々そのエイリアスで書かれます。抽選はタグごと・訪問ごとなので、同じ画像を二度見ても読みが変わり、タグごとに一つのエイリアスを選んで繰り返すのではなく、語彙全体が学習中に行き渡ります。\n\n変わるのはプロンプトだけです。タグの照合、常時／除外リスト、頻度バランス、損失の重み、切り抜きが含めるべきボックスは、すべて正規名を使い続けます。エイリアスのないタグは常にそのまま書かれ、0 はこの設定が存在する前の挙動そのままです。",
  "Whether a tag's rarity is measured within the selected training images, across the whole library, or across the whole library plus what each tag has elsewhere.":
    "タグの希少さを、選ばれた学習画像の中で測るか、ライブラリ全体で測るか、ライブラリ全体に各タグが他所で持つ枚数を足して測るか。",
  "Rarity is relative to some population, and this picks which one.\n\n“Training data” counts only the images this job selected, so balancing works within the set you are actually training on — usually what you want. “Whole library” counts every item you own, which makes a tag that is common in your dataset but rare overall still count as rare. That is occasionally useful when the training set is a deliberate slice of a much larger, differently balanced collection.\n\n“Whole library + count offsets” adds each tag’s highest meta-tag count — the pictures it has somewhere this library is not, counted per site on the tag’s meta tags (“tumblr 50”, “twitter 100”), of which the largest single figure is used, never the sum, since the sites count overlapping pictures. Nowhere else in the app is that number added to a count, because a total including it would be a claim about somewhere else; for BALANCING it is often the honest one. A tag with four pictures here and forty thousand where they came from is not a rare word, and treating it as rare spends the run teaching the model something it already knows.":
    "希少さは常に何らかの母集団に対する相対値であり、ここではその母集団を選びます。\n\n「学習データ」はこのジョブが選んだ画像だけを数えるので、実際に学習する集合の中で均衡が取られます。たいていはこれが目的です。「ライブラリ全体」は所有するすべてを数えるため、データセット内では多くても全体では少ないタグは、やはり希少として扱われます。学習セットが、はるかに大きく分布の異なるコレクションから意図的に切り出した一部である場合に、ときおり役立ちます。\n\n「ライブラリ全体＋他所の枚数」は各タグの最大メタタグ件数——このライブラリの外にある枚数を、タグのメタタグごとにサイト別に数えたもの（「tumblr 50」「twitter 100」）——を加えます。使われるのは最大の単一の数で、合計は使いません。サイト同士は重複する画像を数えているからです。アプリの他のどこでもこの数値が計数に足されることはありません。それを含む合計は、よそについての主張になってしまうからです。しかし均衡調整には、しばしばこちらが誠実な数字です。ここに4枚、由来元に4万枚あるタグは希少語ではなく、それを希少として扱えば、モデルがすでに知っている語を教えることに学習を費やすことになります。",
  "Caption selection": "キャプションの選択",
  "Instruction selection": "指示の選択",
  "Start now — pauses the running job and puts this one first":
    "今すぐ開始 — 実行中のジョブを一時停止し、これを先頭に置きます",
  "Start now — puts this job first and starts the queue":
    "今すぐ開始 — このジョブを先頭に置き、キューを開始します",
  "Save as duplicate":
    "複製として保存",
  "Batch & seed": "バッチとシード",
  "Device": "デバイス",
  "Precision & quantization": "精度と量子化",
  "Memory savers": "メモリ節約",
  "Training images": "学習画像",
  "Length measured in":
    "学習量の単位",
  "Steps are a fixed amount of work; epochs are full passes over your images, so the run grows with the dataset.":
    "ステップは一定の作業量、エポックは画像全体を1周する回数です。データセットが大きいほど学習は長くなります。",
  "A STEP is one batch pushed through the model and one update of the weights — a fixed amount of work whatever the dataset holds. An EPOCH is one pass over every training image, so the same number means a longer run on a bigger set and the model sees each picture the same number of times either way.\n\nEpochs are usually the easier thing to reason about: “each image about ten times” transfers between datasets, where “3000 steps” does not. The exact step count is worked out when the run starts, because only then is it known how many entries the dataset has — a film contributes its frames, a degraded copy is an extra sample, and an item can contribute one per caption.":
    "1ステップとは、1バッチをモデルに通して重みを1回更新することです。データセットの大きさに関係なく作業量は一定です。1エポックとは学習画像すべてを1周することなので、同じ数字でもデータセットが大きいほど学習は長くなり、どちらの場合も各画像を見る回数は同じになります。\n\n多くの場合、エポックのほうが考えやすい単位です。「各画像を10回程度」は別のデータセットにも通用しますが、「3000ステップ」は通用しません。正確なステップ数は実行開始時に計算されます。データセットのエントリ数がそのときにしか分からないためです — 動画はフレームを、劣化コピーは追加のサンプルを、1つの項目は説明ごとに1エントリを提供することがあります。",
  "Epochs":
    "エポック",
  "Full passes over the dataset. The exact step count is worked out when the run starts and shown in its log.":
    "データセットを何周するか。正確なステップ数は実行開始時に計算され、ログに表示されます。",
  "How many times the run works through every training image. Each pass visits every entry exactly once, in a fresh random order.\n\nWhat counts as an entry is the dataset after it has been built, not the number of pictures you selected: a video contributes one entry per kept frame, a degradation variant adds an extra sample beside the clean picture, and with “every caption” an item contributes one entry per caption. That is why the step count appears when the run starts rather than here.":
    "学習が全画像を何回通しで処理するか。1周ごとに各エントリをちょうど1回ずつ、そのつど新しいランダム順で訪問します。\n\nここでいうエントリとは、構築後のデータセットのことで、選択した画像の枚数ではありません。動画は残したフレームごとに1エントリ、劣化バリアントはきれいな画像に加えてもう1サンプル、「すべての説明」を選ぶと1項目が説明ごとに1エントリになります。ステップ数がここではなく実行開始時に表示されるのはそのためです。",
  "Query weight":
    "クエリの重み",
  "A weight buys":
    "重みが買うもの",
  "Whether a heavier query's images are seen more often, or seen the same and counted for more.":
    "重みの大きいクエリの画像を、より多く見せるのか、見る回数は同じで重く数えるのか。",
  "Both spend the same ratio; they differ in what they spend it on.\n\nSEEN MORE OFTEN is the classic behaviour: a weight-2 query's pictures get twice the visits, which means they take those visits from the rest — a fixed-length run spends more of itself on them and less on everything else.\n\nCOUNTED FOR MORE gives every picture the same number of visits and multiplies the weighted ones' effect on the weights instead. Nothing loses coverage; the emphasis comes out of the gradient rather than out of the other images' training time. It is the better default when the queries are different KINDS of picture rather than different amounts of importance.":
    "どちらも同じ比率を費やします。違うのは、それを何に費やすかです。\n\n「より多く見せる」は昔ながらの挙動です。重み2のクエリの画像は訪問回数が2倍になりますが、その分を他の画像から奪います。長さの決まった学習では、その画像により多く、他のすべてにより少なく費やされることになります。\n\n「より重く数える」はどの画像にも同じ回数の訪問を与え、代わりに重み付けされた画像が学習結果に与える影響を大きくします。カバー率はどれも下がらず、強調は他の画像の学習時間ではなく勾配から出てきます。クエリが重要度の違いではなく画像の「種類」の違いを表しているときは、こちらのほうが既定として適切です。",
  "Seen more often":
    "より多く見せる",
  "Counted for more":
    "より重く数える",
  "An item with several captions":
    "説明が複数ある項目",
  "Whether every caption is used each pass, or one is drawn per visit.":
    "1周ごとにすべての説明を使うか、訪問ごとに1つ引くか。",
  "Items often carry more than one caption — a short one and a long one, a translation, a machine draft somebody approved.\n\nONE AT RANDOM gives the item a single visit each pass and draws a different caption each time, so the whole set is seen across a long run and an item counts once however many ways it has been described.\n\nEVERY CAPTION gives it one visit per caption, so all of them are used every pass — and an item with ten is therefore seen ten times, which is usually an accident of tooling rather than a claim that the picture matters ten times as much.\n\nEVERY CAPTION, SHARED is that with the accident removed: each caption still gets its visit, and together they carry one item's worth of gradient.":
    "項目には説明が複数付いていることがよくあります — 短いものと長いもの、翻訳、誰かが承認した機械生成の下書きなど。\n\n「ランダムに1つ」は1周につき訪問を1回だけ与え、毎回違う説明を引きます。長い学習の中ですべてが使われ、いくつの説明があっても項目は1回分として数えられます。\n\n「すべての説明」は説明ごとに1回の訪問を与えるので、1周ごとにすべてが使われます — 説明が10個ある項目は10回見られることになりますが、それはたいていツール側の偶然であって、その画像が10倍重要だという主張ではありません。\n\n「すべての説明（重みを分け合う）」はその偶然を取り除いたものです。各説明はそれぞれの訪問を保ちつつ、全体で項目1つ分の勾配を担います。",
  "One at random each visit":
    "訪問ごとにランダムに1つ",
  "Every caption, once each":
    "すべての説明を1回ずつ",
  "Every caption, sharing one item's weight":
    "すべての説明を1回ずつ、項目1つ分の重みを分け合う",
  "Unsupported":
    "非対応",
  "not available on Apple silicon":
    "Apple シリコンでは利用できません",
  "not used on Apple silicon, where the run trains in fp32":
    "Apple シリコンでは使われず、学習は fp32 で行われます",
  "a full finetune trains the base weights, so there is nothing to quantize":
    "完全な微調整ではベースの重みを学習するため、量子化するものがありません",
  "only offered for LoRA training":
    "LoRA 学習でのみ利用できます",
  "too large to finetune on any GPU this app has constants for":
    "このアプリが数値を持つどの GPU でも微調整するには大きすぎます",
  "Another picture": "別の画像",
  "{n} jobs selected. One at a time shows its progress, samples and settings.":
    "{n} 件のジョブを選択中。進捗・テスト画像・設定は1件ずつ表示されます。",
  "original":
    "オリジナル",
  "Show this at full size":
    "実寸で表示",
  "Each snapshot is about {size}.":
    "スナップショット1つあたり約 {size} です。",
  "Cadence measured in":
    "間隔の単位",
  "How often a snapshot is written: after a fixed number of steps, or after a number of full passes over the dataset.":
    "スナップショットを書き出す頻度。決まったステップ数ごとか、データセットを何周したごとか。",
  "How often a round of samples is rendered: after a fixed number of steps, or after a number of full passes over the dataset.": "テストサンプルを生成する間隔：一定のステップ数ごとか、データセットを何周したかで指定します。",
  "Rendered after this many full passes. The equivalent step count appears in the job's log when the run starts.": "この回数だけデータセットを一周するごとに生成します。相当するステップ数は、実行開始時にジョブのログに表示されます。",
  "A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 250 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both. It is the choice the checkpoint cadence and the run’s own length already offer, and setting all three the same way is what makes a sample, its checkpoint and a pass over your pictures line up in the timeline.\n\nHow many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has — a film’s frames, a degraded copy and an item contributing one entry per caption all count.": "ステップは決まった量の作業で、エポックは全学習画像を一周することなので、データセットが大きくなるほど二つの間隔は離れていきます — 「250 ステップごと」は小さな学習ではほぼ全体、大きな学習では一部にすぎませんが、「1 エポックごと」はどちらでも同じ意味です。チェックポイントの間隔と学習の長さがすでに提供している選択と同じもので、三つを同じ単位に揃えると、サンプル・そのチェックポイント・画像の一周がタイムライン上で揃います。\n\n1 エポックが何ステップかは実行開始時に算出されます。エントリ数を知っているのは、組み立て済みのデータセットだけだからです — 動画のフレーム、劣化コピー、キャプションごとに 1 エントリを出すアイテムも、すべて数に入ります。",
  "Rendered after this many full passes over the dataset. The equivalent step count is printed in the job’s log when the run starts, so a glance there says what the cadence came out as for this particular dataset.\n\nSampling interrupts training while it renders, so on a large dataset one round per epoch may be further apart than you want and on a tiny one it may be a pause every few seconds — the log’s step figure is what tells you which.": "データセットをこの回数だけ一周するごとに生成します。相当するステップ数は開始時にジョブのログへ書き出されるので、そこを見ればこのデータセットでの実際の間隔が分かります。\n\nサンプル生成の間は学習が止まるため、大きなデータセットでは 1 エポックごとでも間隔が空きすぎることがあり、ごく小さなものでは数秒おきの中断になることもあります — どちらかはログのステップ数が教えてくれます。",
  "Rendered every this many steps, whatever the dataset is. 250–500 is a good rhythm: often enough to catch a concept going wrong, rare enough that the pauses do not dominate the run.": "データセットに関係なく、このステップ数ごとに生成します。250〜500 が良いリズムです。概念がおかしくなり始めたのに気づける程度に頻繁で、中断が学習を支配しない程度にまれです。",
  "A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 500 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both.\n\nHow many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has. That is also why the disk estimate below can only be given when the run's length is set in epochs too.":
    "ステップは一定の作業量、エポックは学習画像すべてを1周することなので、データセットが大きくなるほど2つの間隔はずれていきます。「500ステップごと」は小さな学習ではほぼ全体、大きな学習ではごく一部ですが、「毎エポック」はどちらでも同じ意味です。\n\n1エポックが何ステップかは実行開始時に決まります。エントリ数を知っているのは構築後のデータセットだけだからです。下のディスク見積もりが出せるのも、学習の長さをエポックで指定している場合だけです。",
  "epochs":
    "エポック",
  "Written after this many full passes. The equivalent step count appears in the job's log when the run starts.":
    "この回数だけ1周するごとに書き出されます。ステップ換算は実行開始時にジョブのログに表示されます。",
  "Every snapshot is a usable model file: the Evaluate tab can generate with any of them, so you can compare one pass against another and keep whichever looks best.\n\nCounted in passes, the cadence follows the dataset: add pictures and the snapshots stay one-per-pass rather than quietly becoming more frequent than a pass. The trainer prints what it works out to in steps, so the timeline and the log still agree about what a checkpoint is.":
    "スナップショットはどれもそのまま使えるモデルファイルです。Evaluate タブではどれでも生成に使えるので、ある周と別の周を見比べて良いほうを残せます。\n\n周で数えると、間隔はデータセットに追随します。画像を足しても「1周に1つ」のままで、いつのまにか1周より短い間隔になることがありません。ステップ換算はトレーナーがログに書くので、タイムラインとログでチェックポイントの意味がずれません。",
  "Never upscale":
    "拡大しない",
  "Leave out any image smaller than the bucket it would be fitted to, rather than enlarging it.":
    "割り当て先のバケットより小さい画像は、拡大せずに除外します。",
  "Loads the frozen base weights in 8-bit or 4-bit so big models fit in little memory (QLoRA). 8-bit (int8) runs on Apple silicon too; fp8 and 4-bit need an NVIDIA GPU.":
    "凍結されたベースの重みを 8 ビットまたは 4 ビットで読み込み、大きなモデルを少ないメモリに収めます（QLoRA）。8 ビット（int8）は Apple Silicon でも動作します。fp8 と 4 ビットは NVIDIA GPU が必要です。",
  "Quantize the text encoder":
    "テキストエンコーダーを量子化",
  "Applies the same scheme to the text encoder, the other big frozen model. On the largest models it is worth several GB.":
    "同じ方式を、もう一つの大きな凍結モデルであるテキストエンコーダーにも適用します。最大級のモデルでは数 GB の差になります。",
  "cannot be combined with training the text encoder":
    "テキストエンコーダーの学習とは併用できません",

  // ---- adapter type, layer targeting, optimizers, noise levels,
  // weight averaging and regularization ----
  "Adapter":
    "アダプター",
  "Adapter type":
    "アダプターの種類",
  "Kronecker factor":
    "クロネッカー因子",
  "How each weight is split into LoKr's two parts. Leave empty unless you have a reason not to.":
    "各重みを LoKr の2つの部分にどう分けるか。特に理由がなければ空のままにしてください。",
  "Only these layers":
    "この層だけ",
  "all of them":
    "すべて",
  "Comma-separated parts of a layer's name. Leave empty to train every attention layer — which is what you want unless you have a reason not to.":
    "層の名前の一部をカンマ区切りで。空にするとすべての attention 層を学習します。特に理由がなければそれが望ましい設定です。",
  "By default the adapter attaches to every attention layer in the image model. This narrows that to the layers whose name contains one of the words you list.\n\nWhy you might: different parts of the network do different jobs. The later ones carry more of what a picture LOOKS like, and the earlier ones more of how it is put together — so training only part of the network is how a style is learned without also disturbing composition and anatomy. It also makes the adapter smaller and each step faster, since there is less to train.\n\nThe names come from the model itself, and the chevron at the end of the field lists the ones worth knowing for the architecture you picked — clicking one adds or removes it, and a tick marks the ones the field already holds. For SD and SDXL they are down_blocks, mid_block and up_blocks, plus attn1 (the picture attending to itself) and attn2 (where the prompt gets in); for the newer transformer models, transformer_blocks and single_transformer_blocks. The field stays free text, because you can be as coarse or as fine as you like: 'up_blocks' takes a whole third of a UNet, 'transformer_blocks.12' takes one block, 'to_k' takes one kind of projection everywhere. The job's page draws a map of the whole model once a run has started.\n\nIf what you type matches no layers at all, the run stops and says so rather than training an adapter attached to nothing — which would otherwise look exactly like a normal run that learned nothing.":
    "既定では、アダプターは画像モデルのすべての attention 層に取り付けられます。ここでは、名前に指定した語のいずれかを含む層だけに絞り込みます。\n\n絞り込む理由：ネットワークの部分ごとに役割が違います。後ろの層ほど絵の「見え方」を、前の層ほど絵の組み立て方を担っています。つまり一部分だけを学習させることが、構図や人体構造を乱さずに画風を学ばせるやり方です。学習対象が減るぶんアダプターも小さくなり、1ステップも速くなります。\n\n名前はモデル自身から取られ、フィールド右端のシェブロンを押すと選んだアーキテクチャで知っておく価値のあるものが一覧されます — クリックで追加・削除でき、すでにフィールドにあるものにはチェックが付きます。SD と SDXL では down_blocks、mid_block、up_blocks に加えて attn1（画像が自分自身に注意を向ける側）と attn2（プロンプトが入ってくる側）、新しい transformer 系モデルでは transformer_blocks と single_transformer_blocks です。粗くも細かくも指定できるので、フィールドは自由入力のままです —「up_blocks」は UNet の3分の1を丸ごと、「transformer_blocks.12」は1ブロックだけ、「to_k」はあらゆる場所の1種類の射影を取ります。実行が始まればジョブのページがモデル全体の地図を描きます。\n\n入力した内容がどの層にも一致しない場合、実行は停止してその旨を伝えます。何にも取り付いていないアダプターを学習させれば、何も学ばなかった普通の実行とまったく同じに見えてしまうからです。",
  "Except these layers":
    "この層を除く",
  "Comma-separated parts of a layer's name to leave out. Applied after the field above, and it wins.":
    "除外する層の名前の一部をカンマ区切りで。上の項目のあとに適用され、こちらが優先されます。",
  "The same kind of list, subtracting instead of selecting. A layer whose name matches anything here is left out even if the field above selected it.\n\nIt is the easier way to say 'everything except' — excluding 'down_blocks' is shorter and stays correct if the model gains a block, where listing every other block by hand does not.":
    "同じ形式のリストですが、選ぶのではなく差し引きます。ここに一致する名前の層は、上の項目が選んでいても除外されます。\n\n「〜以外すべて」を言うにはこちらが簡単です。「down_blocks」を除外するほうが短くて済み、モデルにブロックが増えても正しいままですが、他のブロックを手で全部並べる書き方はそうなりません。",
  "Output size: a small fraction of a LoRA of the same rank — usually under a tenth.":
    "出力サイズ：同じランクの LoRA のごく一部、通常は10分の1未満です。",
  "Learning rate multiplier":
    "学習率の倍率",
  "Prodigy works the rate out for itself; this scales what it finds. 1 leaves it alone — lower it if the run overshoots, raise it if it never gets going.":
    "Prodigy は学習率を自分で求めます。ここはその結果に掛ける倍率で、1 ならそのまま。行きすぎるなら下げ、いつまでも進まないなら上げてください。",
  "The Prodigy optimizer measures how far the weights have moved from where they started and derives a learning rate from that, so the rate is not something you set here — it comes out of the run.\n\nWhat this field does is scale the answer. 1 accepts it as found and is what you want almost always. Below 1 is a brake, worth reaching for if the run overshoots and samples come out burnt; above 1 pushes harder, which is occasionally useful on a very small dataset.\n\nProdigy needs a few hundred steps to work its estimate up from nearly nothing, so early samples in a Prodigy run look untrained even when everything is fine. Judge it from about a fifth of the way in, not from the first sample round.":
    "Prodigy は、重みが出発点からどれだけ動いたかを測り、そこから学習率を導きます。つまり学習率はここで決めるものではなく、実行そのものから出てきます。\n\nこの項目はその答えに倍率を掛けるだけです。1 は出てきた値をそのまま使うという意味で、ほとんどの場合それが正解です。1 未満はブレーキで、行きすぎてサンプルが焼けたようになるときに使います。1 を超えると強く押し、ごく小さいデータセットでたまに役立ちます。\n\nProdigy は推定値をほぼゼロから育てるのに数百ステップかかります。そのため Prodigy の実行では、順調でも序盤のサンプルは未学習に見えます。最初のサンプル回ではなく、全体の5分の1ほど進んだあたりから判断してください。",
  "How far the weights move on every update. It is the single most sensitive setting here.\n\nToo high and training diverges: samples turn into over-saturated, high-contrast mush ('deep fried'), often within a few hundred steps. Too low and nothing visibly changes no matter how long you wait. Typical values: 1e-4 for a LoRA, 1e-5 or lower for a full finetune (which touches every weight and needs far gentler updates).\n\nLearning rate and total steps trade off against each other — halving the rate roughly doubles the steps needed. If early samples look burnt, halve it; if they look identical to the baseline after a third of the run, double it.\n\nIf finding this number is the part you would rather not do, the Prodigy optimizer (Memory & speed) works it out for itself.":
    "1回の更新で重みがどれだけ動くか。ここで最も敏感な設定です。\n\n高すぎると学習が発散し、サンプルは彩度とコントラストが過剰なぼんやりした絵（いわゆる deep fried）になります。数百ステップで起きることも珍しくありません。低すぎるといくら待っても目に見える変化がありません。目安は LoRA で 1e-4、フルファインチューニングでは 1e-5 以下（すべての重みに触れるため、はるかに穏やかな更新が必要です）。\n\n学習率と総ステップ数は互いに打ち消し合います。学習率を半分にすると必要なステップ数はおよそ2倍です。序盤のサンプルが焼けて見えるなら半分に、実行の3分の1を過ぎても最初と同じに見えるなら2倍にしてください。\n\nこの数値を探す作業を避けたいなら、Prodigy オプティマイザー（メモリと速度）が自分で求めてくれます。",
  "Noise levels":
    "ノイズの強さ",
  "Train on":
    "学習する範囲",
  "Which stage of denoising to spend the run on. High noise decides a picture's layout, low noise its detail — so this decides what the training is mostly about.":
    "ノイズ除去のどの段階に実行を費やすか。ノイズが強い段階は絵の構成を、弱い段階は細部を決めます。つまりここで、学習が主に何についてのものになるかが決まります。",
  "Every training step takes a picture, adds some amount of noise to it, and asks the model to undo that. How much noise is picked fresh each time — and the two extremes teach completely different things.\n\nAt HIGH noise there is barely a picture left, so all the model can learn is layout: what is where, how big, the overall shape and colour. At LOW noise the composition is already settled and what is left to learn is detail and texture — edges, surfaces, small features.\n\nSo where a run spends its steps decides what it mostly teaches. A style is largely texture; a character's proportions are largely layout.\n\n'The model's own' is what this model family has always done here, and is the right answer unless you have a specific reason: the older models spread their steps evenly, and the newer ones concentrate on the middle, which is what their published recipes do and part of why they train efficiently. 'Evenly' spreads across the whole range. 'Bell curve' is the newer models' behaviour made adjustable, so you can lean it towards layout or towards detail. 'Cosine' leans towards higher noise without abandoning the low end.\n\nChanging this does not make a run better or worse in general — it moves what the run is good at.":
    "学習の各ステップは、画像にある量のノイズを加えて、それを元に戻すようモデルに求めます。ノイズの量は毎回引き直され、両極端はまったく違うことを教えます。\n\nノイズが強い段階では絵はほとんど残っていないので、モデルが学べるのは構成だけです。何がどこに、どの大きさで、全体の形と色はどうか。ノイズが弱い段階では構図はすでに決まっていて、残っているのは細部と質感 — 輪郭、表面、細かい特徴です。\n\nつまり実行がステップをどこに費やすかが、主に何を教えるかを決めます。画風はおおむね質感であり、キャラクターのプロポーションはおおむね構成です。\n\n「モデル本来のもの」は、このモデル系列がここで常に行ってきた方法で、特別な理由がなければこれが正解です。古いモデルはステップを均等に散らし、新しいモデルは中央に集中させます。これは公開されているレシピどおりで、これらが効率よく学習する理由の一つでもあります。「均等」は全域に散らします。「ベルカーブ」は新しいモデルの挙動を調整できるようにしたもので、構成寄りにも細部寄りにも傾けられます。「コサイン」は低ノイズ側を捨てずに高ノイズ寄りに傾けます。\n\nこれを変えても実行が一般的に良くなったり悪くなったりするわけではありません。得意になる方向が動くだけです。",
  "The model's own (recommended)":
    "モデル本来のもの（推奨）",
  "Evenly across all levels":
    "すべての強さに均等に",
  "A bell curve I can aim":
    "狙いを定められるベルカーブ",
  "Leaning towards layout":
    "構成寄り",
  "Aim at":
    "狙い",
  "0 is the middle. Positive leans towards layout and composition, negative towards detail and texture. ±1 is already a strong lean.":
    "0 が中央です。正の値は構成と構図寄り、負の値は細部と質感寄りになります。±1 でもう十分に大きな偏りです。",
  "Where the centre of the bell curve sits along the noise range.\n\n0 puts it in the middle, which is what the newer models do by default and a good place to stay. Move it positive and the run spends more of itself at high noise, learning layout and composition — useful when what you are teaching is a shape or an arrangement. Move it negative and it spends more at low noise, learning detail and texture — useful for a style, a medium, a surface quality.\n\n±0.5 is a noticeable lean and ±1 is a strong one. Beyond ±2 the run largely stops seeing one end of the range at all.":
    "ノイズの範囲のどこにベルカーブの中心を置くか。\n\n0 は中央で、新しいモデルの既定の位置であり、そのままにしておくのが無難です。正に動かすと実行は高ノイズ側により多くを費やし、構成と構図を学びます。形や配置を教えたいときに向いています。負に動かすと低ノイズ側に多く費やし、細部と質感を学びます。画風、画材、表面の質を教えたいときに向いています。\n\n±0.5 ではっきりした偏り、±1 で強い偏りです。±2 を超えると、実行は範囲の片端をほとんど見なくなります。",
  "Spread":
    "広がり",
  "How wide the curve is. 1 is the default; smaller concentrates the run on a narrow band around the aim, larger reaches both extremes.":
    "カーブの幅。既定は 1 です。小さくすると狙いの周りの狭い範囲に集中し、大きくすると両端まで届きます。",
  "The width of the bell curve.\n\n1 is the standard setting. Smaller values concentrate the run on a narrow band around wherever you have aimed it, which sharpens what it teaches at the cost of everything else. Larger values spread it out and reach both extremes more often, which is closer to training evenly.\n\nIf you are unsure, leave it at 1 and move the aim instead — the aim is the setting that changes what the run learns, and this one changes how single-minded it is about it.":
    "ベルカーブの幅です。\n\n1 が標準設定です。値を小さくすると、狙いを定めた場所の周りの狭い帯に実行が集中し、他のすべてを犠牲にして教える内容が鋭くなります。値を大きくすると散らばって両端に届く回数が増え、均等な学習に近づきます。\n\n迷ったら 1 のままにして、代わりに狙いを動かしてください。狙いは実行が何を学ぶかを変える設定で、こちらはそれにどれだけ一途になるかを変える設定です。",
  "Weight averaging":
    "重みの平均化",
  "Average the weights":
    "重みを平均化する",
  "Save a smoothed version of the weights instead of whatever the last step happened to produce. Makes checkpoints more consistent and overtraining slower to bite.":
    "最後のステップがたまたま出した重みではなく、なめらかにした重みを保存します。チェックポイント間のばらつきが減り、過学習の影響も遅く出るようになります。",
  "Every training step moves the weights a little, and each of those moves is noisy — it is worked out from a handful of images, and a different handful would have pulled somewhere slightly different. So the weights at step 1400 are not reliably better than the weights at step 1200; part of the difference is just which pictures came up.\n\nWith this on, the run keeps a second, smoothed copy of the weights alongside the real ones and nudges it a little way towards the current weights after every step. That smoothed copy is what gets saved — as the checkpoints, as the final result, and as what the test samples are rendered from. Training itself is completely unaffected.\n\nWhat you get is a result that depends less on exactly where the run stopped: the quality difference between neighbouring checkpoints shrinks, and a run that goes on too long degrades more gradually, because an average lags behind. What it costs is one extra copy of whatever is being trained — nothing worth thinking about for a LoRA, a second whole model for a full finetune, which the memory estimate below accounts for.\n\nThe early part of a run is handled for you: a fresh average starts out equal to the untrained weights, so the run keeps it short at first and lengthens it as training goes on. Without that, a short run would save an average still holding its own random starting point.":
    "学習の各ステップは重みを少しずつ動かしますが、その一つひとつにはばらつきがあります。ひと握りの画像から計算されるので、別の画像が選ばれていれば少し違う方向に引かれていたはずです。ですからステップ 1400 の重みがステップ 1200 の重みより確実に良いとは限りません。違いの一部は、たまたまどの画像が出たかにすぎません。\n\nこれを有効にすると、実行は本物の重みと並んで、なめらかにした2つ目のコピーを保持し、各ステップのあとに現在の重みのほうへ少しだけ寄せます。保存されるのはそのなめらかなコピーです — チェックポイントも、最終結果も、テスト用サンプルを描くのに使われるのもそれです。学習そのものにはまったく影響しません。\n\n得られるのは、実行がどこで止まったかにあまり左右されない結果です。隣り合うチェックポイント間の品質差は縮まり、長すぎる実行の劣化もゆるやかになります。平均は遅れて追いかけるからです。代償は学習対象のコピーを1つ余分に持つことで、LoRA なら気にする必要はなく、フルファインチューニングならモデル1つ分になります（下のメモリ見積もりはそれを含んでいます）。\n\n実行の序盤は自動的に処理されます。新しい平均は未学習の重みと同じ状態から始まるため、実行は最初のうち平均を短く保ち、学習が進むにつれて長くしていきます。これがないと、短い実行では自分のランダムな出発点を含んだままの平均が保存されてしまいます。",
  "Averaging window":
    "平均化の窓",
  "How much of the old average is kept each step. 0.999 averages roughly the last 1000 steps; lower follows training more closely, higher smooths harder.":
    "各ステップで古い平均をどれだけ残すか。0.999 でおよそ直近1000ステップの平均になります。小さいほど学習に近く追従し、大きいほど強くならされます。",
  "The fraction of the existing average kept at each step, with the rest taken from the current weights. It decides how long a stretch of training the saved result reflects — roughly 1 ÷ (1 − this value) steps.\n\n0.999 is about the last 1000 steps and is a sensible default for runs of a few thousand. On a short run (say 800 steps) that window is longer than the run itself, so the average never quite catches up — drop to 0.99 (about 100 steps) there. On a very long run you can go higher for a steadier result.\n\nAs a rule of thumb, keep the window well under the total number of steps.":
    "各ステップで既存の平均を残す割合で、残りは現在の重みから取られます。保存される結果が学習のどれくらいの区間を反映するかを決め、おおよそ 1 ÷ (1 − この値) ステップに相当します。\n\n0.999 は直近1000ステップほどで、数千ステップの実行には妥当な既定値です。短い実行（たとえば800ステップ）ではこの窓が実行そのものより長くなり、平均が追いつききりません。その場合は 0.99（約100ステップ）まで下げてください。非常に長い実行では、より安定した結果のために上げても構いません。\n\n目安として、窓は総ステップ数より十分小さく保ってください。",
  "Mostly a memory choice, except for Prodigy, which works the learning rate out for itself. Adafactor saves the most memory and runs on every GPU; 8-bit AdamW saves less and needs an NVIDIA or AMD card.":
    "基本的にはメモリの選択です（Prodigy だけは学習率を自分で求めます）。Adafactor が最も節約でき、どの GPU でも動きます。AdamW（8ビット）は節約が小さく、NVIDIA か AMD のカードが必要です。",
  "The optimizer is what actually turns gradients into weight changes. It does that using running statistics it keeps for every weight being trained — and those statistics are memory, which for a full finetune is usually most of what the run needs.\n\nAdamW is the standard choice and the safest. It keeps two statistics per trained weight, so a full finetune pays for the model roughly three times over: the weights themselves, plus two more of the same size.\n\nAdamW (8-bit) stores those two statistics at one byte each instead of four. It is a smaller saving than it sounds, because the weights and their gradients do not shrink, and it needs an NVIDIA or AMD (ROCm) GPU — elsewhere the run says so and uses plain AdamW.\n\nAdafactor replaces the larger of the two statistics with a per-row and a per-column summary of it, which is a fraction of the size. It saves considerably more than the 8-bit variant and it runs on every GPU, including Apple silicon — where it is the only memory saving available at all, since the 8-bit variant cannot run there. What it costs is a little stability: it usually wants a slightly higher learning rate than AdamW, so if a run learns nothing after a few hundred steps, raise the rate before changing anything else.\n\nProdigy is a different kind of answer. It measures how far the weights have travelled from where they started and works the learning rate out from that as it goes, which removes the one setting here that genuinely has to be found by trial: the right rate depends on the model, the dataset size and what is being taught, so a value that suits one job is wrong for the next. With it selected, the learning rate on the Optimization page becomes a multiplier on what it finds, and 1 means 'as found'. It uses a little more memory than AdamW, and it needs a few hundred steps to work its estimate up — so early samples look untrained even when the run is fine.\n\nFor LoRA training the memory differences are a rounding error, since only the small adapter has optimizer state. Leave it on AdamW for a first run; reach for Prodigy when you are tired of guessing the rate, and for Adafactor when a full finetune will not fit.":
    "オプティマイザーは、勾配を実際の重みの変化に変えるものです。その際、学習中のすべての重みについて統計を保持し続けます。この統計がメモリであり、フルファインチューニングでは実行に必要なメモリの大半を占めるのが普通です。\n\nAdamW が標準で最も安全な選択です。学習対象の重み1つにつき統計を2つ保持するので、フルファインチューニングはモデル約3つ分を支払うことになります（重みそのものと、同じ大きさの統計2つ）。\n\nAdamW（8ビット）は、その2つの統計を4バイトではなく1バイトずつで保存します。重みと勾配は小さくならないので節約は聞こえるほど大きくなく、NVIDIA か AMD（ROCm）の GPU が必要です。それ以外の環境では実行がその旨を伝え、通常の AdamW を使います。\n\nAdafactor は、2つの統計のうち大きいほうを行ごと・列ごとの要約に置き換えます。大きさはごくわずかです。8ビット版よりかなり多く節約でき、Apple silicon を含むどの GPU でも動きます。Apple silicon では8ビット版が動かないため、これが唯一使えるメモリ節約でもあります。代償は安定性がやや落ちることで、AdamW より少し高い学習率を好む傾向があります。数百ステップ経っても何も学習していないようなら、他を変える前にまず学習率を上げてください。\n\nProdigy はまったく別種の答えです。重みが出発点からどれだけ動いたかを測り、そこから学習率を走らせながら求めます。これにより、ここで唯一「試して見つける」しかなかった設定がなくなります。適切な学習率はモデル、データセットの大きさ、教える内容によって変わるので、あるジョブに合う値は次のジョブでは間違いだからです。これを選ぶと、最適化ページの学習率は求めた値に掛ける倍率になり、1 は「求めたまま」を意味します。AdamW より少しメモリを使い、推定値を育てるのに数百ステップかかるため、実行が順調でも序盤のサンプルは未学習に見えます。\n\nLoRA の学習では、オプティマイザーの状態を持つのは小さなアダプターだけなので、メモリの差は誤差の範囲です。最初の実行は AdamW のままにしておき、学習率を当てるのに疲れたら Prodigy、フルファインチューニングが収まらないなら Adafactor に手を伸ばしてください。",
  "AdamW (8-bit)":
    "AdamW（8ビット）",
  "Prodigy (finds its own rate)":
    "Prodigy（学習率を自分で見つける）",
  "Prodigy works the learning rate out for itself, so the rate on the Optimization page becomes a multiplier on what it finds — 1 leaves it alone. It needs a few hundred steps to settle, so early samples will look untrained.":
    "Prodigy は学習率を自分で求めるため、最適化ページの学習率は求めた値に掛ける倍率になります（1 でそのまま）。落ち着くまでに数百ステップかかるので、序盤のサンプルは未学習に見えます。",
  "Regularization":
    "正則化",
  "How much reminders count":
    "思い出させる画像の重み",
  "1 gives a regularization picture the same say as a training picture, which is the usual setting. Lower makes it a gentler reminder.":
    "1 なら正則化画像は学習画像と同じ重みを持ちます。これが通常の設定です。小さくするとより穏やかな念押しになります。",
  "Regularization pictures are in the run to hold the model's existing idea of a thing in place while you teach it something new. This is how much each of them counts against a training picture, which counts 1.\n\n1 is the classic setting and a good starting point. Lower it if the run seems reluctant to learn what you are actually training — the reminders are pulling too hard. Raise it if what you are training keeps leaking into everything else of the same kind, which is the problem they exist to solve.\n\nThis is separate from a query's weight, which decides how OFTEN those pictures come up. How often and how much are different questions: a set of reminders is usually wanted often but quietly.":
    "正則化画像は、新しいことを教えている間、モデルがすでに持っている「そのもの」の理解をその場に留めておくために実行に入れます。ここは、重み 1 の学習画像に対して1枚あたりどれだけ効くかです。\n\n1 が古典的な設定で、出発点として適しています。実際に学習させたいものをなかなか覚えないようなら下げてください。念押しが強すぎます。学習させているものが同じ種類のもの全体に染み出し続けるなら上げてください。それこそが正則化画像の存在理由です。\n\nこれはクエリの重みとは別物です。クエリの重みは、それらの画像がどれくらい「頻繁に」出てくるかを決めます。頻度と強さは別の問いで、念押しの一群はたいてい頻繁に、しかし控えめに効いてほしいものです。",
  "Pictures that remind the model what it already knows, instead of teaching it something new — they stop what you are training from spreading to everything else of the same kind. They never get the trigger word.":
    "新しいことを教えるのではなく、モデルがすでに知っていることを思い出させる画像です。学習させているものが同じ種類のもの全体に広がるのを防ぎます。トリガーが付くことはありません。",
  "These pictures hold the model's existing idea of the subject in place: pick the same KIND of thing you are training, but not the thing itself. You do not need to exclude your training pictures — anything an ordinary query matches stays a training picture. A reminder query that matches only training pictures leaves this pool empty, and the run says so in its log.":
    "これらの画像は、モデルがすでに持っている被写体の理解をその場に留めます。学習させているものと同じ「種類」でありながら、そのもの自体ではない画像を選んでください。学習画像を除外する必要はありません — 通常のクエリに一致した画像は学習画像のままです。リマインダーのクエリが学習画像しか拾わない場合、このプールは空になり、実行はそれをログに記録します。",
  "Keep the text encoder on the CPU":
    "テキストエンコーダーを CPU に置く",
  "Frees all of its VRAM instead of some. The next batch's prompt is encoded while this one trains, so it costs nothing as long as the processor keeps up with the card.": "VRAM を一部ではなくすべて解放します。次のバッチのプロンプトはこのバッチの学習中にエンコードされるので、プロセッサーがカードに追いつく限りコストはかかりません。",
  "The row above makes the text encoder smaller; this one takes it off the graphics card altogether. Its weights stay in ordinary system memory and each prompt is turned into an embedding there, so the encoder occupies no VRAM at all — where quantizing it leaves roughly a third of it resident.\n\nMeasured on an RTX 5070 Ti at 4-bit, this takes Chroma from 9.6 GB to 5.3 and FLUX.1 from 11.4 to 7.0, which was enough to train FLUX.2 Klein at a resolution that did not previously fit.\n\nWhat it costs is one pass over the encoder per step, on the processor instead of the graphics card — and the next batch's prompt is encoded while the current one trains, so the card only waits where the processor is slower than a whole step. Measured on a 16-core desktop, T5-XXL takes about 1.3 seconds a prompt: a 1024-pixel step on an RTX 5090 hides that entirely, a 512-pixel step (half a second) does not. It cannot be combined with training the text encoder, which would mean doing that training on the processor.":
    "上の行はテキストエンコーダーを小さくしますが、こちらは GPU から完全に外します。重みは通常のシステムメモリに置かれ、プロンプトはそこで埋め込みに変換されるため、VRAM をまったく使いません—量子化では約 3 分の 1 が残ります。\n\nRTX 5070 Ti、4 ビットでの実測では、Chroma が 9.6 GB から 5.3 に、FLUX.1 が 11.4 から 7.0 になり、これまで入らなかった解像度で FLUX.2 Klein を学習できました。\n\n代償はステップごとにエンコーダーを 1 回、グラフィックカードではなくプロセッサーで実行することです。次のバッチのプロンプトは現在のバッチの学習中にエンコードされるため、カードが待つのはプロセッサーがステップ全体より遅い場合だけです。16 コアのデスクトップで計測すると T5-XXL はプロンプトあたり約 1.3 秒かかります。RTX 5090 での 1024 ピクセルのステップはそれを完全に隠せますが、512 ピクセルのステップ（0.5 秒）は隠せません。テキストエンコーダーの学習とは組み合わせられません。それはその学習をプロセッサーで行うことになるからです。",

  // ---- the METHOD is an adapter, of which LoRA is one kind ----
  "An adapter is a small add-on file layered over the untouched model — fast, low memory, ideal for styles, characters and concepts. Full finetune rewrites the whole model: much more VRAM and data needed, only worth it for broad domain shifts. Which kind of adapter is the next question down.":
    "アダプターは、手を加えないモデルの上に重ねる小さな追加ファイルです。速く、メモリも少なく、画風・キャラクター・概念に向いています。フルファインチューニングはモデル全体を書き換えます。VRAM もデータもはるかに多く必要で、大きく領域を変える場合にだけ見合います。どの種類のアダプターかは、すぐ下の項目で決めます。",
  "An adapter leaves the base model untouched and trains a small add-on (a few dozen MB) that is layered on top at generation time. It is quick, fits ordinary hardware, can be mixed with other adapters and dialled up or down by weight — and it is enough for styles, characters, objects and most concepts. There are two kinds, LoRA and LoKr, and the Adapter section below picks between them; LoRA is the one to start with.\n\nA full finetune rewrites every weight of the model. It produces a multi-gigabyte model of its own, needs far more VRAM, far more images and much lower learning rates, and it can forget things it used to know. Reach for it only when you are moving the model into a genuinely different domain, not to teach it one more subject.":
    "アダプターはベースモデルには手を加えず、生成時に上へ重ねる小さな追加ファイル（数十 MB）を学習します。短時間で済み、普通のハードウェアに収まり、他のアダプターと混ぜたり重みで強弱をつけたりでき、画風・キャラクター・物体・たいていの概念にはこれで十分です。種類は LoRA と LoKr の 2 つあり、下のアダプターの項目でどちらかを選びます。まずは LoRA です。\n\nフルファインチューニングはモデルのすべての重みを書き換えます。数ギガバイトのモデルがそれ自体として出来上がり、VRAM も画像もはるかに多く必要で、学習率はずっと低くしなければならず、以前できていたことを忘れることもあります。モデルを本当に別の領域へ移すときにだけ使ってください。題材をもう一つ覚えさせるためではありません。",
  "Start from an existing adapter":
    "既存のアダプターから開始",
  "A fresh adapter starts from noise and has to learn your concept from nothing. Starting from an existing one keeps everything it already learned and refines it — the usual reasons are adding new images to a concept you trained before, or nudging one that came out almost right.\n\nWeight sets trained on the same base model are offered — including ones trained on another model built on it — and the new job has to match the one it continues: the same adapter type, the same rank, and the same layer targeting. The trainer stops with a message naming what it found otherwise. Picking a job's finished result continues where it ended; picking an intermediate checkpoint rewinds to that point and continues from there.":
    "新しいアダプターはノイズから始まり、あなたの概念をゼロから学ばなければなりません。既存のものから始めれば、学習済みの内容をすべて保ったまま磨き込めます。よくある理由は、以前学習した概念に画像を足したいときと、ほぼ良い出来のものを少し直したいときです。\n\n提示されるのは同じベースモデルで学習された重み（それを土台にした別のモデルで学習したものを含む）で、さらに新しいジョブは続ける相手と一致していなければなりません — 同じアダプターの種類、同じランク、同じ層の絞り込みです。合わない場合、トレーナーは見つけた内容を示して停止します。ジョブの完成結果を選べば終わったところから続き、途中のチェックポイントを選べばその時点まで巻き戻ってそこから続きます。",
  "Pick a finished adapter":
    "完成したアダプターを選択",
  "No finished adapter for this base model yet":
    "このベースモデルの完成したアダプターはまだありません",
  "Optional: continue training an existing adapter instead of starting from scratch.":
    "省略可: ゼロから始める代わりに、既存のアダプターの学習を続けます。",
  "No full finetune":
    "フルファインチューニング不可",

  // ---- adapter wording: an adapter is LoRA or LoKr ----
  "The standard choice, and the format every other tool understands — a LoRA can be used anywhere.":
    "標準の選択肢で、他のあらゆるツールが理解できる形式です。LoRA はどこでも使えます。",
  "An adapter does not rewrite the model — it adds a small 'side channel' to certain layers, and rank is how wide that channel is: how much new information the adapter can hold.\n\nLow ranks (4–8) are plenty for a style or a colour palette and are very hard to overfit. Mid ranks (16–32) suit characters and objects with consistent details. High ranks (64+) mostly grow the file and the overfitting risk without helping, unless you are teaching a genuinely broad new domain.\n\nIt means slightly different things to the two adapter types. For a LoRA it is the hard ceiling on the change: a rank-16 adapter can only ever make a rank-16 change. For a LoKr it bounds only part of the structure, so a LoKr is not confined the way a LoRA is and its file grows far more slowly as you raise it — which is why the size estimate below is a figure for LoRA and a comparison for LoKr.":
    "アダプターはモデルを書き換えるのではなく、特定の層に小さな「側路」を足します。ランクはその幅、つまりアダプターがどれだけ新しい情報を持てるかです。\n\n低いランク（4–8）は画風や配色には十分で、過学習もほとんど起きません。中くらい（16–32）は細部が一貫したキャラクターや物体に向きます。高いランク（64+）は、本当に広い新領域を教えるのでなければ、たいていファイルと過学習の危険を増やすだけです。\n\n2 種類のアダプターで意味が少し違います。LoRA ではこれが変化の上限そのもので、ランク 16 のアダプターはランク 16 の変化しか作れません。LoKr では構造の一部を制限するだけなので、LoRA のように閉じ込められることはなく、上げてもファイルの増え方はずっと緩やかです。下の欄が LoRA には数値、LoKr には比較になっているのはそのためです。",
  "The adapter's output is multiplied by alpha ÷ rank before being added to the model, so alpha sets how loudly the adapter speaks at a given capacity. It works the same way for both adapter types.\n\nThe usual convention is alpha = rank, which makes the scale factor 1 and keeps behaviour comparable when you change rank. Setting alpha to half the rank is a common way to soften an adapter that comes out too strong. It interacts with the learning rate — halving alpha has a similar effect to halving the rate — so change one at a time.":
    "アダプターの出力はモデルに足される前に alpha ÷ ランク が掛けられます。つまり alpha は、与えられた容量のもとでアダプターがどれだけ大きな声で話すかを決めます。2 種類のアダプターで同じように働きます。\n\n慣習は alpha = ランクで、係数が 1 になり、ランクを変えても挙動を比べやすくなります。alpha をランクの半分にするのは、効きすぎるアダプターを和らげるよくあるやり方です。学習率と相互作用するので（alpha を半分にするのは学習率を半分にするのと似た効果です）、変えるのは一度に一つにしてください。",
  "This architecture can only be trained as an adapter (LoRA or LoKr) alongside the frozen model. The \"Full finetune\" method, which rewrites the model's own weights, is not offered for it.":
    "このアーキテクチャは、凍結したモデルの横に置くアダプター（LoRA または LoKr）としてしか学習できません。 モデル自身の重みを書き換える「フルファインチューニング」は選べません。",
  "No adapters for this base model yet.": "このベースモデル用のアダプターはまだありません。",
  "No trained adapters yet.": "学習済みのアダプターはまだありません。",
  "Which adapter this row applies":
    "この行が適用するアダプター",
  "Adapter strength: 1 = as trained, below weakens, above strengthens (can distort past ~1.5).":
    "アダプターの強度: 1 = 学習どおり、下は弱め、上は強め（約 1.5 を超えると歪むことがあります）。",
  "Add adapter":
    "アダプターを追加",
  "Adapters":
    "アダプター",
  "Finetune": "ファインチューン",
  "Generate with a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.":
    "ベースモデルの重みの代わりに、フルファインチューンの重みで生成します。アダプターはここで選んだものの上に重なります。",
  "none — the base model": "なし — ベースモデル",
  "loading finetune": "ファインチューンを読み込み中",
  "Stack trained adapters on the base model, each with its own strength — LoRA or LoKr. An adapter fits the model it was trained on and any other built on the same one.":
    "学習済みのアダプター（LoRA でも LoKr でも）をそれぞれの強度でベースモデルに重ねます。アダプターは学習に使ったモデルと、同じモデルを土台にした他のモデルに適用できます。",
  "Generated images appear here — try out a trained adapter against its base model.":
    "生成された画像はここに表示されます。学習したアダプターをベースモデルと見比べてみてください。",
  "A much smaller file, and not limited by the rank the way a LoRA is. Whether it can be used outside this app depends on the model — see the ⓘ.":
    "ファイルははるかに小さく、LoRA のようにランクで頭打ちになりません。このアプリの外で使えるかはモデル次第です——ⓘ を参照してください。",
  "Both add a small trainable layer over the frozen model; they differ in the shape of change they can express.\n\nA LoRA adds a 'low-rank' change: two thin matrices whose product is added to each targeted weight. Its capacity is exactly its rank — a rank-16 adapter can only ever make a rank-16 change, however long you train it. That is ample for a character, an object, a colour palette. It trains a little faster, it is the format every tool reads, and it carries better between related checkpoints: a LoRA trained on one finetune of a model usually still works on another.\n\nLoKr builds the change as a Kronecker product of two much smaller matrices instead. The saving comes from that structure rather than from throwing rank away, so the change is not confined to a thin slice of the weight while the file stays a small fraction of a LoRA's — under a tenth of the trainable parameters at rank 8. LyCORIS, whose method this is, suggests reaching for it when a LoRA 'does not learn well enough', and it is generally the better fit for styles and broad visual qualities, where a LoRA's rank ceiling is what you meet first. Its own caveats are the mirror image: slightly slower to train, and a very small LoKr transfers less well if you later swap the base model for a different finetune.\n\nWhat each can be USED by differs, and it is the file rather than the method. A LoRA is written in the layout every tool reads. A LoKr cannot be: that layout has a place for two matrices and nowhere to put a Kronecker factor. What it gets instead is a copy named the way ComfyUI names LoKr layers, and that works for the models whose layers ComfyUI addresses that way — FLUX.1, FLUX.1 Kontext and the Qwen-Image releases. On the others (SD 1.5, SDXL, Chroma, FLUX.2, Z-Image) a LoKr stays here: it works in the Evaluate tab and as the starting point of another job, but there is no file to hand over. On those, pick LoRA if the result has to leave this app.":
    "どちらも凍結したモデルの上に小さな学習可能な層を足すもので、違いは「どんな形の変化を表現できるか」です。\n\nLoRA は「低ランク」の変化を足します。細い行列 2 つの積を、対象の重みそれぞれに加算します。その容量はランクそのもので、ランク 16 のアダプターはどれだけ学習してもランク 16 の変化しか作れません。キャラクター、物体、配色にはこれで十分です。学習はやや速く、どのツールも読める形式で、近い系統のチェックポイント間でも移りやすい——ある派生モデルで学習した LoRA は、たいてい別の派生モデルでも動きます。\n\nLoKr は代わりに、ずっと小さい行列 2 つのクロネッカー積として変化を組み立てます。節約はランクを捨てることではなく、この構造から来ます。つまり変化は重みの薄い一片に閉じ込められず、それでいてファイルは LoRA のごく一部——ランク 8 で学習可能パラメーターの 10 分の 1 未満です。この手法の出どころである LyCORIS は、LoRA が「うまく学べていない」ときに使うことを勧めており、LoRA のランクの上限に先にぶつかるような画風や広い視覚的性質には概してこちらが向きます。裏返しの注意点もあります。学習はやや遅く、非常に小さい LoKr は後でベースモデルを別の派生モデルに替えると転用しにくくなります。\n\nそれぞれが何に「使えるか」は異なり、それは手法ではなくファイルの問題です。LoRA はどのツールも読める形式で書き出されます。LoKr はそれができません——その形式には行列 2 つ分の場所しかなく、クロネッカー因子を置く場所がないからです。代わりに、ComfyUI が LoKr の層を呼ぶ名前で付けたコピーが書き出され、ComfyUI がそのように層を指すモデル——FLUX.1、FLUX.1 Kontext、Qwen-Image 系——では使えます。それ以外 (SD 1.5、SDXL、Chroma、FLUX.2、Z-Image) では LoKr はここにとどまります。Evaluate タブと次のジョブの出発点としては使えますが、渡せるファイルはありません。その場合、結果を持ち出すなら LoRA を選んでください。",
  "LoKr expresses a weight's change as one small matrix combined with another. This number decides where the weight is cut into those two parts.\n\nLeft empty, the split is chosen to make the two parts as close to square as possible, which is where they are SMALLEST. Moving it either way grows the file, and the two directions are not the same thing: a low factor (4–8) pushes the weight into the second part, which is where the adapter's capacity is — that is the LyCORIS recipe for a LoKr that is not learning enough. A factor far above the square split grows the first, dense part instead, which costs size for nothing.\n\nMeasured on a 1280-wide layer at rank 8, against the same layer's LoRA: automatic 0.08x, factor 8 0.13x, factor 4 0.25x, factor 128 0.81x.\n\nThere is rarely a reason to set it. If a LoKr adapter is not learning enough, raise the rank first, then try a low factor.":
    "LoKr は重みの変化を、小さな行列ともう一つの行列の組み合わせとして表します。この数値は、重みをその 2 つにどこで切り分けるかを決めます。\n\n空のままなら、2 つがなるべく正方形に近くなるように切り分けられ、そこが最も小さくなる点です。どちらへ動かしてもファイルは大きくなりますが、2 つの方向は同じ意味ではありません。小さい係数 (4–8) は重みを 2 つ目——アダプターの容量がある側——へ寄せます。これは学習が足りない LoKr に対する LyCORIS の処方です。正方形の切り分けよりずっと大きい係数は、代わりに 1 つ目の密な部分を大きくし、サイズだけ食って得るものがありません。\n\n幅 1280 の層・ランク 8 で、同じ層の LoRA と比較して測定: 自動 0.08 倍、係数 8 は 0.13 倍、係数 4 は 0.25 倍、係数 128 は 0.81 倍。\n\n設定する理由はめったにありません。LoKr の学習が足りないときは、まずランクを上げ、それから低い係数を試してください。",
  "Every picture this finds is also matched by a training query, so it contributes nothing and the run will not be regularized. Narrow it to pictures the run is NOT about.":
    "これが見つける画像はすべて学習クエリにも一致するため、このプールは何も寄与せず、実行は正則化されません。この実行の対象では「ない」画像に絞り込んでください。",
  "val": "検証",
  "stable": "安定",
  "validation": "検証",
  "Validate": "検証",
  "Masked regions": "マスク領域",
  "Mask out regions tagged": "領域をマスクするタグ",
  "Comma-separated tags whose bounding boxes are largely ignored by the loss — e.g. 'watermark'. The picture still trains; the region inside the boxes stops teaching. Tags without boxes on an image mask nothing there.": "カンマ区切りのタグ。その境界ボックス内は損失からほぼ無視されます — 例: 'watermark'。画像自体は学習を続け、ボックス内の領域だけが教えなくなります。ボックスのないタグは、その画像では何もマスクしません。",
  "Mask out regions of tags marked": "マークされたタグの領域をマスク",
  "Comma-separated META tags. Any tag the library marks with one of these has its boxes masked — so the rule is stated once in the Tags tab rather than listed here.": "カンマ区切りのメタタグ。ライブラリがこれで印を付けたタグは、そのボックスがマスクされます。ルールはここに並べるのではなく、タグタブで一度だけ述べられます。",
  "Masked region weight": "マスク領域の重み",
  "How much a masked region still counts. 0 hides it from training entirely; 1 is the same as not masking.": "マスクされた領域がまだどれだけ数えられるか。0 は学習から完全に隠し、1 はマスクしないのと同じです。",
  "Validation": "検証",
  "Score a validation loss": "検証損失を測定",
  "A few images are held out of training and re-scored on a fixed seed as the run goes. Falling: still learning. Rising while the training loss falls: memorizing — pick an earlier checkpoint.": "少数の画像を学習から取り置き、固定シードで定期的に採点し直します。下がっている: まだ学習中。学習損失が下がる中で上がっている: 暗記の始まり — 早めのチェックポイントを選んでください。",
  "Validate every": "検証間隔",
  "Each round costs one forward pass per scored image — a small set every few hundred steps is barely noticeable.": "1 回の採点は画像ごとに順伝播 1 回だけ — 数百ステップごとの小さなセットならほとんど気になりません。",
  "Held-out images": "ホールドアウト画像",
  "Taken OUT of training entirely and scored each round. Capped at half the dataset; 16 is plenty for a LoRA-sized run. 0 turns the held-out series off.": "学習から完全に外し、毎回採点します。データセットの半分が上限。LoRA 規模の学習なら 16 で十分です。0 でこの系列を無効にします。",
  "Stable-loss images": "安定損失の画像",
  "Ordinary TRAINING images re-scored the same fixed way — the training curve without its sampling noise. They stay in training; 0 turns the series off.": "普通の学習画像を同じ固定の方法で採点し直したもの — サンプリングのノイズを除いた学習曲線です。これらは学習に残ります。0 で系列を無効にします。",
  "Some pictures are worth training on except for one rectangle: a watermark, a shop’s caption strip, a censor bar. Left alone, the model learns the rectangle along with the picture — a run over watermarked photographs reliably teaches the watermark. Throwing those pictures out costs the dataset; this keeps them and hides the rectangle from training instead.\n\nThe regions come from the boxes already on the tag: draw a box for `watermark` in the annotator (or let the watermark detector’s tag carry one), name the tag here, and every image carrying such a box trains with the loss inside it turned down. Where a subject tag has no drawn box, its detected faces stand in, exactly as they do for crop-aware training. An image whose named tags have no boxes trains completely normally — nothing is masked there.\n\nOnly the LOSS is masked. The pixels still pass through the image encoder, so the cached latents are the ordinary ones shared with unmasked runs, and nothing is re-encoded when this setting changes. The mask lives in latent space, where one cell covers 8×8 pixels rounded outward to whole cells — so it cannot hide anything much thinner than that, and a pixel-accurate outline is not something it can promise. It also cannot conjure what is UNDER the watermark: the model simply receives no signal about that area, from this picture.\n\nPairs naturally with a tag the prompt always includes (Always include under Tag selection): the prompt says the watermark is there, the mask stops the pixels teaching it, and at generation time the model has no reason to produce one unprompted.": "透かし、店のキャプション帯、検閲バーなど、ひとつの長方形さえなければ学習に値する画像があります。放っておくと、モデルは画像と一緒にその長方形も学びます — 透かし入り写真での学習は確実に透かしを教えます。そうした画像を捨てればデータセットが痩せます。この設定は画像を残し、代わりに長方形を学習から隠します。\n\n領域はタグに既にあるボックスから来ます。アノテーターで `watermark` にボックスを描き（あるいは透かし検出器のタグに持たせ）、そのタグをここに書けば、そのボックスを持つすべての画像はボックス内の損失を下げて学習します。人物タグに描かれたボックスがない場合は、検出された顔が代わりになります — 切り抜きを意識した学習と全く同じです。名指ししたタグにボックスがない画像は完全に普通に学習し、そこでは何もマスクされません。\n\nマスクされるのは損失だけです。ピクセルは画像エンコーダーを通り続けるので、キャッシュされた潜在表現はマスクなしの学習と共有される普通のもので、この設定を変えても再エンコードは起きません。マスクは潜在空間にあり、1 セルが 8×8 ピクセルを覆い、外側へセル単位に丸められます — それよりずっと細いものは隠せず、ピクセル精度の輪郭は約束できません。透かしの下に何があるかを作り出すこともできません。モデルはこの画像から、その領域について単に信号を受け取らないだけです。\n\nプロンプトに常に含めるタグ（タグ選択の「常に含める」）と自然に組み合わさります。プロンプトは透かしがあると言い、マスクはピクセルがそれを教えるのを止め、生成時にモデルが頼まれもせず透かしを描く理由はなくなります。",
  "The same rule, stated once in the library instead of tag by tag here. A meta tag put on the tags whose boxes should never teach — `masked`, say — covers every such tag at once, including ones created after this job was written.\n\nThe list is resolved to tag names when the dataset is built, so the job’s log says how many images actually carried a masked region. A run where that line says zero has a rule pointing at tags nobody drew boxes for.": "同じルールを、ここでタグごとに書く代わりにライブラリで一度だけ述べます。ボックスに教えさせないタグに付けたメタタグ — 例えば `masked` — は、この仕事を書いた後に作られたタグも含め、該当するすべてのタグを一度に覆います。\n\nリストはデータセット構築時にタグ名へ解決されるので、ジョブのログに実際にマスク領域を持っていた画像の数が出ます。その行がゼロなら、誰もボックスを描いていないタグを指すルールです。",
  "What a cell inside a masked box still counts for. 0 hides the region entirely, which is the usual choice for a watermark — there is nothing in it worth a whisper. A small value (0.05–0.2) keeps a faint signal, which can be worth it when the boxes are generous and cover real picture around the thing being hidden.\n\n1 is the unmasked loss, so setting it there is the same as clearing the tag lists. Where an image also trains with an alpha mask, the two multiply: a masked region on a transparent background is doubly not the picture.": "マスクされたボックス内のセルがまだどれだけ数えられるか。0 は領域を完全に隠します — 透かしには普通これで、ささやきほどの価値もありません。小さな値（0.05〜0.2）はかすかな信号を残します。ボックスが大きめで、隠したいものの周りの本当の絵まで覆っているときには価値があります。\n\n1 はマスクなしの損失なので、そこに設定するのはタグのリストを空にするのと同じです。画像がアルファマスクでも学習する場合、二つは掛け合わされます。透明な背景の上のマスク領域は、二重に「絵ではない」からです。",
  "The training loss cannot answer the question people ask of it. It is drawn from the pictures being trained on, at a different random noise level every step, so it is noisy by construction — and it keeps falling for as long as the model memorizes, which means it looks healthiest exactly when a run has gone on too long.\n\nThis scores two extra series that can answer it, both with the plain per-sample loss on a fixed seed, so every round asks the model exactly the same questions and the number moves only when the model does. The series appear as their own lines on the loss graph, and each round is a line in the job’s log.\n\nReading it: the validation loss falls while the model generalizes and flattens or turns when it starts memorizing — the turning point is roughly where to stop, and with step snapshots on, the checkpoint to pick. Expect it to sit above the training loss and to move in small amounts; what matters is the direction, not the level. It stays comparable across pauses, resumes and step extensions, because the scored images and the seed never change within a job.": "学習損失は、人がそれに尋ねる問いに答えられません。学習中の画像から、毎ステップ違うランダムなノイズ水準で引かれるため、構造的にノイズだらけです — そしてモデルが暗記する限り下がり続けるので、走らせすぎた学習ほど健全に見えます。\n\nこの設定は、それに答えられる二つの系列を採点します。どちらも固定シードでの素の損失なので、毎回モデルに全く同じ問いを投げ、数字はモデルが動いたときにだけ動きます。系列は損失グラフに独自の線として現れ、各回はジョブのログに 1 行になります。\n\n読み方: 検証損失はモデルが汎化する間は下がり、暗記が始まると平らになるか転じます — その転換点がだいたい止めどきで、ステップスナップショットがあれば選ぶべきチェックポイントです。学習損失より上に位置し、小さな量で動くのが普通です。大事なのは方向で、水準ではありません。採点する画像とシードはジョブ内で変わらないので、一時停止・再開・ステップ延長をまたいでも比較できます。",
  "How often a round runs, in steps. A round costs one forward pass per scored image — no gradients, no optimizer — so a 16-image set is a few seconds; matching the sample or checkpoint cadence keeps the graph, the images and the snapshots telling one story at the same steps.\n\nVery frequent rounds buy little: overfitting announces itself over hundreds of steps, not five.": "何ステップごとに採点するか。1 回は採点画像ごとに順伝播 1 回 — 勾配も最適化もなし — なので 16 枚のセットは数秒です。サンプルやチェックポイントの周期に合わせると、グラフと画像とスナップショットが同じステップで一つの物語を語ります。\n\n頻繁すぎる採点は得るものがほとんどありません。過学習は数百ステップかけて現れるもので、5 ステップでは現れません。",
  "How many images are set aside for the validation loss. They are taken OUT of training entirely — never visited, in no pool, their captions never seen — because a loss over pictures the model is also memorizing measures nothing. The pick is random but fixed per job, whole images at a time (a picture cannot be half in training), regularization pools are not eligible, and it is capped at half the dataset so the setting can never eat the run it protects.\n\nMore images make a steadier line at a linearly higher cost per round. On a small dataset every held-out image is also a training image lost, which is the real price — 8–16 is usually enough to see the turn, and the job’s log says exactly how many were held out.": "検証損失のために何枚を取り置くか。これらは学習から完全に外れます — 一度も訪問されず、どのプールにも入らず、キャプションも見られません。モデルが同時に暗記している画像での損失は何も測らないからです。選択はランダムですがジョブごとに固定で、常に画像単位（画像は半分だけ学習には入れません）、正則化プールは対象外、そして設定が守るはずの学習を食い尽くさないよう、データセットの半分が上限です。\n\n枚数を増やすと線は安定しますが、1 回のコストは線形に増えます。小さなデータセットでは取り置いた 1 枚は失われた学習画像 1 枚でもあり、それが本当の代償です — 転換を見るには 8〜16 枚で普通は十分で、実際に何枚取り置いたかはジョブのログに出ます。",
  "A second series over ordinary TRAINING images: a fixed slice, re-scored with the same fixed seed each round. Nothing is held out — these stay in training — so it costs no data at all.\n\nWhat it shows is the training curve with the sampling noise removed. The per-step loss jumps around because every step draws different pictures at different noise levels; this line asks the same pictures at the same noise every time, so it is readable where the raw curve is a cloud. Compared against the held-out line it also localizes trouble: both falling is learning, stable falling while held-out rises is memorizing, and neither falling means the run is not learning at all.": "普通の学習画像に対する第二の系列です。固定した一部を、毎回同じ固定シードで採点し直します。何も取り置かれず — これらは学習に残ります — データは一切失われません。\n\n見えるのは、サンプリングノイズを除いた学習曲線です。ステップごとの損失が跳ねるのは、毎ステップ違う画像を違うノイズ水準で引くからです。この線は毎回同じ画像に同じ問いを投げるので、生の曲線が雲にしか見えないところでも読めます。ホールドアウト線と比べれば問題の場所も分かります。両方下がるなら学習中、安定線が下がるのにホールドアウト線が上がるなら暗記、どちらも下がらないなら学習は何も進んでいません。",
  "Save the current rules, or load a saved set": "現在のルールを保存、または保存済みのセットを読み込む",
  "Rule sets": "ルールセット",
  "Remember the current rules — name the set in this list afterwards": "現在のルールを記憶 — その後この一覧でセットに名前を付けます",
  "Add a rule first": "先にルールを追加してください",
  "Save current rules": "現在のルールを保存",
  "Add this set's rules to the job — rows it already has stay put": "このセットのルールをジョブに追加 — すでにある行はそのまま",
  "Value rules": "値ルール",
  "Turn numeric value tags (height:172cm) into words at prompt time. The first matching rule wins — drag rows to reorder.": "数値の値タグ (height:172cm) をプロンプト作成時に言葉へ変えます。最初に一致したルールが勝ちます — 行はドラッグで並べ替え。",
  "namespace, e.g. height": "名前空間、例: height",
  "Keep the raw tag in the prompt beside the rule's text": "生のタグをルールのテキストと並べてプロンプトに残す",
  "keep tag": "タグを残す",
  "Remove this rule": "このルールを削除",
  "Add rule": "ルールを追加",
  "Any tag shaped `<name>:<number><unit>` is a value tag — `people:3`, `height:172cm`, `height:1.72m`, or a ranking’s own `quality:7` — and a rule here turns a range of those numbers into words at prompt time: where `height` is greater than 190cm, write `tall`. A raw `height:172cm` token teaches a text encoder nothing it can read back at generation time; a word does.\n\nA matching tag is replaced by the rule’s text, and a per-rule toggle keeps the raw tag alongside for whoever wants both spellings in the prompt. The metric length and mass families convert, so one rule covers `172cm` and `1.72m` alike; an unknown unit compares only against the same unit, and a plain number only against plain numbers.\n\nRanges may overlap, and the first matching rule wins — the rows are dragged into order, and that order is part of the configuration. A value tag no rule matches passes through the prompt unchanged, so nothing is dropped silently. The rule’s phrase rides the ordinary random pick and dropout like the tag it replaced: prompts sometimes carry it and sometimes do not, which is exactly the variation score-tag conditioning wants.\n\nThe rules are resolved when the dataset is built — the job’s log says how many tags they matched — and a set of rules can be saved and loaded by name, so a house vocabulary is written once and reused across jobs. Loading a set adds its missing rules to the job rather than replacing the rows already there.": "`<名前>:<数値><単位>` の形のタグは値タグです — `people:3`、`height:172cm`、`height:1.72m`、ランキング自身の `quality:7` も同様 — そしてここのルールは、プロンプト作成時にその数値の範囲を言葉に変えます: `height` が 190cm より大きいところでは `tall` と書く、というように。生の `height:172cm` トークンはテキストエンコーダーが生成時に読み返せるものを何も教えません。言葉なら教えられます。\n\n一致したタグはルールのテキストに置き換えられ、ルールごとのスイッチで生のタグを併記することもできます。メートル法の長さと質量の系は換算されるため、1 つのルールが `172cm` と `1.72m` を同じように扱います。未知の単位は同じ単位としか比較されず、単位のない数は単位のない数としか比較されません。\n\n範囲は重なっても構いません。最初に一致したルールが勝ちます — 行はドラッグで並べ替えられ、その順序は設定の一部です。どのルールにも一致しない値タグはそのままプロンプトに残り、何も黙って捨てられません。ルールの語句は置き換えたタグと同じく通常のランダム選択とドロップアウトに従います: プロンプトに載ることも載らないこともあり、それこそがスコアタグ条件付けに必要な揺らぎです。\n\nルールはデータセット構築時に解決され — ジョブのログが何個のタグに一致したかを伝えます — ルールのセットは名前を付けて保存・読み込みでき、決まりの語彙を一度書けばジョブをまたいで使い回せます。セットの読み込みは既存の行を置き換えず、足りないルールを追加します。",
  "Write tags as":
    "タグの書き方",
  "Their name":
    "名前",
  "Their comment":
    "コメント",
  "Name and comment":
    "名前とコメント",
  "A tag's comment is the one line beside its name in the Tags tab — the same idea in words a text encoder can read. A tag with no comment is written as its name.":
    "タグのコメントは、タグタブで名前の横にある一行です — テキストエンコーダーが読める言葉で書いた同じ意味です。コメントのないタグは名前で書かれます。",
  "A tag's comment is the one line beside its name in the Tags tab — “one girl in the picture” for `1girl`, “from below, looking up at the subject” for `from_below`. A booru vocabulary is compact for the people typing it and opaque to a text encoder; the comment is the same idea in words the encoder can read.\n\n“Their name” is what every run did: the tag as it is spelled. “Their comment” writes the comment in place of the name wherever a picked tag has one, and “Name and comment” writes the name with the comment in brackets after it, so the model learns both spellings of one thing. A tag with no comment is written as its name whatever this says.\n\nOnly the PROMPT changes. Matching, the always/exclude lists, frequency balancing, the loss weight and the boxes a crop has to keep all stay keyed on the tag's name, exactly as with aliases — and the comment is read from the library when the dataset is built, so editing a comment later changes the next run, not this one.":
    "タグのコメントは、タグタブで名前の横にある一行です — `1girl` なら「画像に女の子が一人」、`from_below` なら「下から被写体を見上げる」。booru の語彙は入力する人には簡潔でも、テキストエンコーダーには不透明です。コメントは同じ意味を、エンコーダーが読める言葉で言い直したものです。\n\n「名前」はこれまでのすべての実行と同じ、綴りどおりのタグです。「コメント」は、選ばれたタグにコメントがあれば名前の代わりにコメントを書き、「名前とコメント」は名前の後ろに括弧でコメントを添えて、一つのものの両方の言い方をモデルに学ばせます。コメントのないタグは、どの設定でも名前で書かれます。\n\n変わるのはプロンプトだけです。マッチング、常に含める／除外のリスト、頻度による均衡、損失の重み、切り抜きが収めるべきボックスは、エイリアスの場合と同様、すべてタグの名前を基準にしたままです — コメントはデータセット構築時にライブラリから読まれるので、後でコメントを編集しても影響するのは次の実行で、この実行ではありません。",
  "Remove the selected images?": "選択した画像を削除しますか？",
  "They cannot be recovered.": "元に戻すことはできません。",
  "Its downloaded weights can go with it, or stay in the cache for a later download to find.": "ダウンロード済みの重みも一緒に削除するか、後のダウンロードが見つけられるようキャッシュに残すか選べます。",
  "Remove and delete weights": "削除して重みも消す",
  "Remove the training job “{name}”?": "学習ジョブ「{name}」を削除しますか？",
  "Remove {n} training jobs?": "{n} 件の学習ジョブを削除しますか？",
  "Its checkpoints, test samples and trained result are deleted with it — except anything locked, which is kept in the LoRAs list. This cannot be undone.": "チェックポイント、サンプル、学習結果も一緒に削除され、元に戻せません。（ロックされたものは LoRA 一覧に残ります。）",
  "Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone.": "チェックポイント、サンプル、学習結果も一緒に削除され、元に戻せません。（ロックされたものは LoRA 一覧に残ります。）",
  "The Train tab": "トレーニングタブ",
  "The Evaluate tab": "評価タブ",
  "The Models tab": "モデルタブ",
  "Your models": "自分のモデル",
  "Finetunes": "ファインチューン",
  "Based on {model}": "{model} をベースにしています",
  "A full finetune of {model}": "{model} の完全なファインチューン",
  "The built-in release, one of your own models, or a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.": "組み込みのリリース、自分のモデル、または基本モデルの重みの代わりに使う完全なファインチューンの重み。アダプターはここで選んだものの上に重ねられます。",
};

export default CATALOG;
