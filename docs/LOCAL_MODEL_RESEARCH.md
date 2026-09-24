# Local open-model integration research

September 24, 2026

## Recommendation and scope

Gemma 4 E4B, Qwen3.5, Ministral 3, and Phi-4-mini are credible candidates for optional local assistance. Start by comparing **Gemma 4 E4B, Qwen3.5 4B, and Ministral 3 3B Instruct** for bounded extraction, classification, summaries, and drafts. Add Phi-4-mini as a compact text-only baseline, and evaluate the larger Qwen/Ministral variants if smaller models require too many corrections. This is an evaluation order, not a quality ranking. Treat reliable operation on the supported Macs and acceptable task accuracy as adoption gates. This report establishes documented feasibility, not measured performance: no models were installed, no host benchmark was run, and no production integration decision is changed.

Local inference belongs beside cloud model APIs as a built-in inference adapter. It does not itself provide a personal assistant's mailbox access, scheduling, permissions, memory, or computer-control environment. The application's broader integration choices are discussed in [AI_INTEGRATION_RESEARCH.md](AI_INTEGRATION_RESEARCH.md).

## Model candidates

### Google Gemma 4 E4B

Google publishes the instruction-tuned checkpoint `google/gemma-4-E4B-it`. Its card identifies an Apache 2.0 license. E4B means **4.5 billion effective parameters**, with **8 billion including per-layer embeddings**; it is not a conventional 4-billion-total-parameter model. [Google checkpoint](https://huggingface.co/google/gemma-4-E4B-it).

E4B supports a 128K-token context, text/image/audio inputs, and text output. Google documents function calling, configurable thinking, OCR/document understanding, and audio transcription/translation. The card limits audio to 30 seconds and video to 60 seconds at one frame per second. Those are model capabilities, not a promise that every serving package exposes every modality. Google's published E4B results include 25.4 on its 128K eight-needle retrieval evaluation; context capacity should not be mistaken for dependable recall of every fact. The card also acknowledges inaccurate or outdated answers. [Google model card](https://ai.google.dev/gemma/docs/core/model_card_4).

The Apache license permits redistribution subject to its conditions, including license and applicable notices. Shipping weights therefore needs artifact provenance and license handling, even if the runtime download is optional. [Google's published license](https://ai.google.dev/gemma/apache_2).

### Qwen3.5 4B and 9B

Qwen3.5 **4B** and **9B** are Apache 2.0 models with vision encoders, text generation, documented tool use, and 262,144-token native context. Their thinking mode is enabled by default and can be disabled; the application should test the mode explicitly rather than assuming identical latency or output behavior. The 4B/9B sizes refer to their language-model components. [Qwen 4B model card](https://huggingface.co/Qwen/Qwen3.5-4B), [Qwen 9B model card](https://huggingface.co/Qwen/Qwen3.5-9B).

### Ministral 3 Instruct

Ministral 3 **3B Instruct 2512** and **8B Instruct 2512** both accept text and images, generate text, support function calling/JSON output, and use Apache 2.0. They advertise 256K context. The 3B checkpoint comprises a 3.4B language model plus a 0.4B vision encoder; the 8B checkpoint comprises 8.4B plus 0.4B. Use these exact generation-3 models, rather than confusing them with the earlier Ministral 3B/8B releases. [Mistral 3B model card](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512), [Mistral 8B model card](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512).

The 3B model is a compact candidate; the 8B variant is a larger alternative whose quality benefit must justify its resource cost. Neither reviewed package provides direct audio input. Vision support makes image-based workflows possible, but document extraction and photo interpretation still need task-specific evaluation.

### Microsoft Phi-4-mini-instruct

Phi-4-mini-instruct is a **3.8B, text-input/text-output** model under the MIT license, with 128K advertised context and documented function calling. Microsoft identifies constrained compute, bounded latency, and reasoning as intended uses. Its card explicitly notes limited factual capacity and uneven multilingual performance. This is the mini-instruct checkpoint, not the separate Phi-4-multimodal model. [Microsoft model card](https://huggingface.co/microsoft/Phi-4-mini-instruct).

Phi is useful for already parsed email and document text. Scans and photographs require a separate OCR/image-processing stage. Its reasoning benchmarks do not establish faithful lease extraction or correct amounts; calculations remain deterministic.

### Comparable local packages

All reviewed packages below use Q4_K_M quantization. Sizes are **artifact downloads, not total RAM requirements**. Differences in model architecture and packaged components mean parameter counts and download sizes do not establish relative speed or accuracy. Pin the exact artifact digest and runtime version, even when using an explicit tag.

| Candidate | Ollama artifact | Download | Evaluation role |
| --- | --- | --- | --- |
| Gemma 4 E4B | `gemma4:e4b` | 9.6 GB | Initial comparison; multimodal model with runtime-specific modality checks. |
| Qwen3.5 4B | `qwen3.5:4b` | 3.4 GB | Initial compact text/image candidate. |
| Qwen3.5 9B | `qwen3.5:9b` | 6.6 GB | Larger alternative if 4B results are insufficient. |
| Ministral 3 3B Instruct | `ministral-3:3b-instruct-2512-q4_K_M` | 3.0 GB | Initial compact text/image candidate. |
| Ministral 3 8B Instruct | `ministral-3:8b-instruct-2512-q4_K_M` | 6.0 GB | Larger alternative if 3B results are insufficient. |
| Phi-4-mini-instruct | `phi4-mini:3.8b-q4_K_M` | 2.5 GB | Optional text-only baseline. |

Package sources: [Gemma E4B](https://ollama.com/library/gemma4:e4b), [Qwen 4B](https://ollama.com/library/qwen3.5:4b), [Qwen 9B](https://ollama.com/library/qwen3.5:9b), [Ministral tags](https://ollama.com/library/ministral-3/tags), [Phi tags](https://ollama.com/library/phi4-mini/tags).

## Runtime feasibility on Mac

| Route | Evidence and tradeoff | Proposed role |
| --- | --- | --- |
| Ollama | Packages for all shortlisted models are listed above. A local HTTP API separates inference from the application backend. | First integration spike; operator-installed runtime initially. |
| MLX | Google's guide demonstrates text/vision inference and an OpenAI-compatible local server on Apple silicon. Its example uses E2B, so test the exact E4B artifact and endpoint behavior separately. | Alternative if measured Mac performance or packaging justifies another adapter. |
| llama.cpp / GGUF | Google publishes an E4B QAT GGUF checkpoint, with local CPU/Apple-silicon deployment described in its overview. | Alternative for controlled packaging; independently verify the chosen build's feature support. |

Sources: [Google Ollama guide](https://ai.google.dev/gemma/docs/integrations/ollama), [Ollama API](https://docs.ollama.com/api/introduction), [Google MLX guide](https://ai.google.dev/gemma/docs/integrations/mlx), [Google QAT collection](https://huggingface.co/collections/google/gemma-4-qat-q4-0), [Google deployment overview](https://ai.google.dev/gemma/docs/core).

Ollama currently requires macOS 14 or newer; Apple M-series supports CPU/GPU execution, while x86 Mac support is CPU-only. This establishes runtime compatibility, not model-specific latency or memory requirements. [Ollama macOS requirements](https://docs.ollama.com/macos).

Qualify each model/runtime combination independently. Begin with text, add images after testing, and enable direct audio only through a verified route. In particular, Gemma's Ollama introduction emphasizes text/image while its family capability material includes audio; neither establishes the application's end-to-end audio behavior. Do not infer audio support for Qwen or Phi from another model's capabilities. [Gemma package documentation](https://ollama.com/library/gemma4:e4b).

Ollama supports JSON-schema response formatting and tool calls. Schema-constrained generation can improve parsing; it cannot establish that an amount, date, unit identity, or claim is correct. The application must still validate domain rules and evidence. Tool calls are proposed calls for application code to execute, not independent authority to edit records. [Structured outputs](https://docs.ollama.com/capabilities/structured-outputs), [Tool calling](https://docs.ollama.com/capabilities/tool-calling).

## Memory and performance planning

Google estimates E4B static loading memory at 17.9 GB BF16, 8.9 GB SFP8, and 4.5 GB Q4_0. Its table includes a loading allowance but explicitly excludes supporting software and context memory. Quantization formats, runtime handling, and modality components matter: those estimates are not interchangeable with the 9.6 GB Ollama package, nor are either a measured Mac resident-memory requirement. Google's mobile figures refer to a separate LiteRT-LM path. Do not advertise “fits in 4 GB” from the effective parameter count or quantization label. [Google memory planning](https://ai.google.dev/gemma/docs/core).

Ollama's context documentation says larger contexts increase memory use and its defaults vary with available VRAM. Explicitly configure and record the tested context; do not assume an advertised maximum context is allocated or practical. [Ollama context settings](https://docs.ollama.com/context-length).

The following are conservative **E4B evaluation targets**, not vendor minimums or measured compatibility claims. Qualify the smaller candidates separately; their download sizes do not establish total memory requirements:

| Mac memory | Proposed stance |
| --- | --- |
| 8 GB | Do not target the reviewed Ollama E4B package for initial support. Evaluate a smaller model or a separately optimized artifact as a distinct configuration. |
| 16 GB Apple silicon | Trial only: short contexts, one inference request at a time, normal application workload present. Ship support only after memory pressure and response time pass. |
| 24–32 GB Apple silicon | Preferred initial E4B evaluation tier, leaving more room for macOS, app, browser, and inference overhead. |
| Intel Mac | Optional research target; do not promise interactive performance without CPU measurements. |

Start at a bounded 4K–8K context with retrieval/chunking, then increase only when a task needs it. Measure cold start, warm latency, peak total memory, swap, app responsiveness, battery/thermal behavior, cancellation, and idle unloading. Do not infer speed from parameter count, advertised context, or another computer's token rate.

## Benefits and costs for this application

| Benefit | Corresponding tradeoff |
| --- | --- |
| Keep supported inference on the operator's computer | Local logs, caches, backups, and other processes still require deliberate data handling. |
| Continue inference without a model-service connection once artifacts are available | Downloads/updates need connectivity; new email discovery still needs its own connector and service access. |
| Avoid per-request cloud inference charges | Hardware, electricity, setup, disk space, maintenance, and operator review remain costs. |
| Control model version and availability | The app team must qualify upgrades, regressions, runtime failures, and hardware variation. |
| Offer an optional privacy-oriented mode | Smaller/quantized models may miss context or produce weak suggestions; suitability must be measured per workflow. |

These are architecture implications, not a measured total-cost or quality comparison. A single operator managing a small portfolio may make too few requests for token savings alone to justify the setup burden. Privacy, offline operation, and control are stronger reasons to offer the option.

## Preserve a real local boundary

Ollama says locally run prompts remain local, but cloud models process prompts remotely. It supports disabling cloud features via `disable_ollama_cloud` or `OLLAMA_NO_CLOUD=1`, and binds to loopback by default. Its model catalog also contains explicitly cloud-hosted variants. Consequently, a local endpoint or an “Ollama” provider label alone does not establish local inference. [Ollama FAQ](https://docs.ollama.com/faq), [Gemma runtime catalog](https://ollama.com/library/gemma4).

All candidates can use the same local inference adapter, while model-specific prompts, output handling, and capabilities remain explicitly configured. Changing weights must not change record ownership, permissions, or approval rules. Proposed implementation requirements:

- Offer an explicit local mode with a verified local artifact and loopback endpoint; reject cloud-hosted tags such as `:cloud` or `:31b-cloud`. Disable cloud features for the supported setup and test with outbound connectivity unavailable. That setting does not block network access by the operating system or other applications.
- Never silently retry a failed local job through a cloud provider. A cloud retry requires the operator's chosen policy and a clear data-destination disclosure.
- Keep model access behind the application's backend, with bounded inputs, cancellation, timeouts, and resource limits. Avoid exposing the inference service to the network as part of normal setup.
- Preserve the same review, source evidence, pause, and audit rules as cloud inference. Local execution does not make generated claims trustworthy or authorize record writes.
- Show operational status such as “Ready,” “Model loading,” or “Unavailable,” while keeping manual workflows usable.

## Recommended validation

Use a small synthetic property-management evaluation set before deciding support. Include noisy messages, multiple properties in one thread, conflicting dates, partial payments, old-versus-new instructions, and missing information. Require source references and explicit unknown values rather than guessed fields.

Compare the same tasks across the selected local-model shortlist, a manual baseline, and any approved cloud candidate. Measure field accuracy, missed critical facts, unsupported claims, correct property matching, schema validity, review/correction time, and end-to-end latency. Test evidence-free questions and instructions embedded inside documents. For images or audio, maintain separate acceptance criteria and verify preprocessing as well as generation.

The first adoption milestone should be one successful, bounded text workflow with operator review and reliable failure behavior. Defer unrestricted agents, whole-workspace ingestion, automated legal conclusions, and autonomous financial changes. No fine-tuning is necessary to establish this initial feasibility.

## Evidence limitations

This research verifies published model and runtime support. It does not establish performance on the user's Mac, accuracy on actual property documents, parity with cloud models, or a universal minimum RAM requirement. Artifact sizes and runtime features can change; repeat compatibility checks against pinned versions before implementation or release.
