# Translating Media Compost

The UI ships in English, German, Japanese, Simplified Chinese, Korean,
Spanish, Brazilian Portuguese and French. This document is the reference for
anyone (person or model) writing or revising a dictionary: the rules that are
enforced by tests, the conventions that are not, and the glossary that keeps
one term from drifting across some two thousand entries.

## How the catalogs work

A dictionary is one file per language per package —
`frontend/src/app/locales/<lang>.ts` and `frontend/src/train/locales/<lang>.ts`
— exporting a flat object keyed by the **English source text**. A missing
entry falls back to English silently; three suites (two under `npm test`, one
under pytest) make the important failures loud:

- `i18nCatalogs.test.ts` — every language complete (key parity against the
  union), plural entries carrying exactly the categories the locale fires,
  `{placeholders}` intact, no English pasted back.
- `i18nCoverage.test.ts` — every `t()` / `tn()` literal in the source has an
  entry.
- `tests/test_i18n_templates.py` (pytest) — every backend template (history
  summaries, refusal messages) has an entry.

A **plural entry** is keyed by the English `other` form and its value is one
string per CLDR category the language uses:

```ts
"{n} people": { one: "1 Person", other: "{n} Personen" },
```

Japanese, Chinese and Korean have only `other`. French and Brazilian
Portuguese select `one` **for zero as well as one** — so a French `one` form
must keep its `{n}` (`{ one: "{n} personne", other: "{n} personnes" }`);
writing "1 personne" would render "1 personne" for no people at all. The
parity test enforces this.

## Hard rules (test-enforced)

- **Query keywords are never translated.** `INFO:`, `TAG:`, `GROUP:`,
  `GROUPONLY:`, `PLACE:`, `SUBJECT:`, `EVENT:`, `CAPTION:`,
  `INSTRUCTION:`, `LINK:`, `LINKEDBY:`, `TAKEN:`, `VALUE:`, `COLORLIKE:`
  are matched case-sensitively by the search parser; a help text that translates one teaches a search
  that finds nothing.
- `{placeholder}` tokens stay byte-identical — never translated, never
  dropped (except `{n}` in a plural form whose category only ever fires at
  exactly 1 in that locale).
- Edge whitespace matches the key's: some keys are sentence fragments spliced
  around a link in JSX, and their leading space is load-bearing.

## Conventions (reviewed, not enforced)

- **Technical proper nouns stay Latin**: LoRA, VRAM, GPU, FLUX, SDXL,
  Chroma, Qwen, EXIF, phash, WebP, PNG, JPEG, ffmpeg, Hugging Face,
  bitsandbytes, QLoRA, NaN.
- **Tag slugs in examples stay as they are** (`subject:alice`,
  `jpeg_artifacts`): tags are user data, and an example that localizes one
  promises a behavior the app does not have.
- CJK uses its own full-width punctuation（、。「」）consistently; quotes
  become 「…」 (ja), “…” (zh-Hans), following each language's convention.
  German uses „…“; French uses «&nbsp;…&nbsp;» with the usual spacing where
  a sentence quotes something, but plain "…" around user-supplied names is
  also acceptable for chrome brevity.
- The long training help texts (quantization, alpha-mask loss, attention
  slicing) are technical documentation. Translate meaning, not words — and
  keep the measured numbers exactly as written.
- Register: address the user informally where the language distinguishes
  (German „du“, matching the existing catalog), plainly and without
  honorific inflation in Japanese (です/ます register).

## Glossary

The one term per concept, per language. If an entry here conflicts with what
reads well in a specific sentence, the sentence wins — but change the WORD,
not the concept it maps to.

| English | de | ja | zh-Hans | ko | es | pt-BR | fr |
|---|---|---|---|---|---|---|---|
| item | Objekt | アイテム | 项目 | 항목 | elemento | item | élément |
| tag | Tag | タグ | 标签 | 태그 | etiqueta | tag | tag |
| meta tag | Meta-Tag | メタタグ | 元标签 | 메타 태그 | metaetiqueta | metatag | méta-tag |
| group | Gruppe | グループ | 分组 | 그룹 | grupo | grupo | groupe |
| tag group | Tag-Gruppe | タググループ | 标签组 | 태그 그룹 | grupo de etiquetas | grupo de tags | groupe de tags |
| sequence | Sequenz | シーケンス | 序列 | 시퀀스 | secuencia | sequência | séquence |
| subject | Subjekt | 被写体 | 主体 | 인물 | sujeto | sujeito | sujet |
| place | Ort | 場所 | 地点 | 장소 | lugar | lugar | lieu |
| event | Ereignis | イベント | 事件 | 이벤트 | evento | evento | événement |
| caption | Caption | キャプション | 说明文字 | 캡션 | descripción | legenda | légende |
| instruction | Anweisung | 指示 | 指令 | 지시 | instrucción | instrução | instruction |
| face | Gesicht | 顔 | 人脸 | 얼굴 | cara | rosto | visage |
| cluster | Cluster | クラスタ | 聚类 | 클러스터 | grupo (de caras) | cluster | groupe (de visages) |
| appearance | Auftreten | 登場 | 出现 | 등장 | aparición | aparição | apparition |
| library | Bibliothek | ライブラリ | 库 | 라이브러리 | biblioteca | biblioteca | bibliothèque |
| import | Import / importieren | インポート | 导入 | 가져오기 | importar | importar | importer |
| export | Export / exportieren | エクスポート | 导出 | 내보내기 | exportar | exportar | exporter |
| trash | Papierkorb | ゴミ箱 | 回收站 | 휴지통 | papelera | lixeira | corbeille |
| history | Verlauf | 履歴 | 历史 | 기록 | historial | histórico | historique |
| revert / undo | rückgängig machen | 元に戻す | 撤销 | 되돌리기 | deshacer | desfazer | annuler |
| alias | Alias | エイリアス | 别名 | 별칭 | alias | alias | alias |
| implication / implies | Implikation / impliziert | 含意 / を含意する | 蕴含 | 함의 | implicación / implica | implicação / implica | implication / implique |
| pending | ausstehend | 保留中 | 待定 | 대기 중 | pendiente | pendente | en attente |
| still (from a film) | Standbild | スチル | 静帧 | 스틸 | fotograma | quadro | image fixe |
| panel (comic) | Panel | コマ | 分格 | 컷 | viñeta | quadro (de quadrinhos) | case |
| bounding box | Rahmen | ボックス | 边界框 | 박스 | recuadro | caixa | cadre |
| source file | Quelldatei | ソースファイル | 源文件 | 원본 파일 | archivo de origen | arquivo de origem | fichier source |
| artifact | Artefakt | アーティファクト | 生成文件 | 아티팩트 | artefacto | artefato | artefact |
| thumbnail | Vorschaubild | サムネイル | 缩略图 | 섬네일 | miniatura | miniatura | miniature |
| duplicate | Duplikat | 重複 | 重复项 | 중복 | duplicado | duplicata | doublon |
| training job | Trainingsauftrag | 学習ジョブ | 训练任务 | 학습 작업 | tarea de entrenamiento | tarefa de treinamento | tâche d'entraînement |
| checkpoint | Checkpoint | チェックポイント | 检查点 | 체크포인트 | checkpoint | checkpoint | checkpoint |
| step (training) | Schritt | ステップ | 步 | 스텝 | paso | passo | pas |
| dataset | Datensatz | データセット | 数据集 | 데이터셋 | conjunto de datos | dataset | jeu de données |
| bucket (aspect) | Bucket | バケット | 分桶 | 버킷 | bucket | bucket | bucket |
| latent | Latent | 潜在表現 | 潜变量 | 잠재 표현 | latente | latente | latent |
| prompt | Prompt | プロンプト | 提示词 | 프롬프트 | prompt | prompt | prompt |
| trigger (word) | Trigger | トリガー | 触发词 | 트리거 | trigger | trigger | déclencheur |
| sample (image) | Testbild | サンプル | 样张 | 샘플 | muestra | amostra | échantillon |
| queue | Warteschlange | キュー | 队列 | 대기열 | cola | fila | file d'attente |
| base model | Basismodell | ベースモデル | 基础模型 | 기본 모델 | modelo base | modelo base | modèle de base |
| text encoder | Text-Encoder | テキストエンコーダー | 文本编码器 | 텍스트 인코더 | codificador de texto | codificador de texto | encodeur de texte |
| learning rate | Lernrate | 学習率 | 学习率 | 학습률 | tasa de aprendizaje | taxa de aprendizado | taux d'apprentissage |
| batch size | Batch-Größe | バッチサイズ | 批大小 | 배치 크기 | tamaño de batch | tamanho do batch | taille de batch |
| gradient checkpointing | Gradient-Checkpointing | 勾配チェックポイント | 梯度检查点 | 그래디언트 체크포인팅 | gradient checkpointing | gradient checkpointing | gradient checkpointing |
| full finetune | Komplett-Finetune | フルファインチューニング | 全量微调 | 전체 파인튜닝 | ajuste completo | finetune completo | finetuning complet |
| weights (model) | Gewichte | 重み | 权重 | 가중치 | pesos | pesos | poids |
| download | Download / herunterladen | ダウンロード | 下载 | 다운로드 | descargar | baixar | télécharger |
| settings | Einstellungen | 設定 | 设置 | 설정 | ajustes | configurações | réglages |
| search | Suche | 検索 | 搜索 | 검색 | búsqueda | busca | recherche |
| filter | Filter | フィルター | 筛选 | 필터 | filtro | filtro | filtre |
| sort | Sortierung | 並べ替え | 排序 | 정렬 | orden | ordenação | tri |
| annotate | annotieren | アノテーション | 标注 | 주석 달기 | anotar | anotar | annoter |
| capture date (taken) | Aufnahmedatum | 撮影日 | 拍摄日期 | 촬영일 | fecha de captura | data de captura | date de prise de vue |
| hidden | ausgeblendet | 非表示 | 已隐藏 | 숨김 | oculto | oculto | masqué |
| dismissed (suggestion) | verworfen | 却下 | 已忽略 | 무시됨 | descartado | descartado | écarté |
| guess / suggested | Vorschlag / vorgeschlagen | 推定 | 建议 | 추정 | sugerencia | sugestão | suggestion |
| named / unnamed | benannt / unbenannt | 命名済み / 未命名 | 已命名 / 未命名 | 이름 있음 / 없음 | con nombre / sin nombre | nomeado / sem nome | nommé / sans nom |

Two German choices are deliberate and carried over from the existing catalog:
**Objekt** for item (not „Element“) and **Caption** untranslated (the term of
art in dataset work). Follow the same spirit elsewhere: where the dataset /
AI-art community in a language has settled on a loanword, use the loanword.

## Date formats

CJK month names come from `Intl` as 「3月」, which reads badly inside the
default `D MMM YYYY` pattern ("9 3月 2026"). The Settings → Language & Region
date-format dropdown offers `YYYY/MM/DD`; CJK users should pick it. The
default is deliberately not language-dependent (it is a per-user setting with
one server-side default).
