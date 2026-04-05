# Signal to Action Dataflow

This document summarizes how data moves through the system described in:

- V1: `signal-to-action-architecture.md`
- V2: `signal-to-action-architecture-v2.md`

It focuses on runtime flow, memory behavior, traceability, and feedback learning.

## 1. What Flows Through the System

The system is a closed loop:

1. user input enters through the conversation thread
2. the Orchestrator decides the next stage
3. specialist agents pull the minimum required context from memory
4. research, segmentation, content, and deployment produce typed records
5. webhook or manual feedback returns engagement data
6. memory is updated so the next cycle starts from accumulated intelligence

```mermaid
flowchart LR
    U["User"]
    UI["Conversation Thread UI"]
    WS["WebSocket / REST API"]
    ORC["Orchestrator"]
    MEM["Memory Manager"]
    RES["Research Subgraph"]
    SEG["Segment / Prospect Agent"]
    GEN["Content Agent"]
    DEP["Deployment Agent"]
    FBK["Feedback Agent"]
    STORE["Persistent Stores"]

    U --> UI
    UI --> WS
    WS --> ORC
    ORC <--> MEM
    ORC --> RES
    ORC --> SEG
    ORC --> GEN
    ORC --> DEP
    ORC --> FBK

    RES --> STORE
    SEG --> STORE
    GEN --> STORE
    DEP --> STORE
    FBK --> STORE

    STORE --> MEM
    MEM --> ORC
    ORC --> WS
    WS --> UI
```

## 2. End-to-End Runtime Dataflow

This is the primary runtime path across the full campaign loop.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Thread UI
    participant API as WS / FastAPI
    participant ORC as Orchestrator
    participant MEM as Memory Manager
    participant RES as Research Subgraph
    participant SEG as Segment Agent
    participant GEN as Content Agent
    participant DEP as Deployment Agent
    participant FBK as Feedback Agent
    participant DB as Session + Intelligence Stores
    participant EXT as External Tools / Providers

    User->>UI: enter message or click UI action
    UI->>API: user_message / ui_action
    API->>DB: load CampaignState
    API->>ORC: invoke graph with current state
    ORC->>MEM: request context bundle
    MEM->>DB: fetch summaries, prior findings, selections
    MEM-->>ORC: stage-scoped context

    alt intent = research
        ORC->>RES: run bounded research
        RES->>EXT: search, extract, news, community
        RES->>DB: persist research_findings
        RES-->>API: briefing + progress events
    else intent = segment
        ORC->>SEG: derive segments / score prospects
        SEG->>EXT: read CSV / CRM / seed list
        SEG->>DB: persist segment + prospect references
        SEG-->>API: ProspectPicker / SegmentSelector
    else intent = generate
        ORC->>GEN: create variants
        GEN->>DB: read source findings + selections
        GEN->>EXT: LLM / image generation
        GEN->>DB: persist content_variants + artifacts
        GEN-->>API: Variant Grid
    else intent = deploy
        ORC->>DEP: send approved variants
        DEP->>DB: read selected variant / prospects / channels
        DEP->>EXT: Resend / Unipile
        DEP->>DB: persist deployment_records
        DEP-->>API: deployment status + confirmation
    else intent = feedback
        ORC->>FBK: process engagement signal
        FBK->>DB: read deployments + findings
        FBK->>DB: write normalized events + results + learning
        FBK-->>API: A/B results + cycle summary
    end

    API->>DB: save updated CampaignState
    API-->>UI: stream tokens, components, progress, results
```

## 3. Core System Data Domains

The system carries several distinct data types. V2 makes the boundaries between them much clearer.

```mermaid
flowchart TD
    subgraph Conversation
        MSG["messages"]
        SUM["conversation_summary"]
        LOG["decision_log"]
    end

    subgraph Research
        RF["research_findings"]
        BR["briefing_summary"]
        GAP["research_gaps"]
    end

    subgraph SegmentAndProspects
        SC["segment_candidates"]
        SS["selected_segment_id"]
        PC["prospect_cards"]
        SP["selected_prospect_ids"]
    end

    subgraph Content
        CR["content_request"]
        CV["content_variants"]
        VA["visual_artifacts"]
        SV["selected_variant_ids"]
    end

    subgraph Deployment
        CH["selected_channels"]
        AB["ab_split_plan"]
        DR["deployment_records"]
    end

    subgraph Feedback
        NFE["normalized_feedback_events"]
        ER["engagement_results"]
        WIN["winning_variant_id"]
    end

    subgraph MemoryRefs
        MR["memory_refs"]
        ERR["error_messages"]
    end
```

## 4. Research Dataflow

V1 already had fan-out / fan-in research. V2 strengthens it by adding bounded branching, more tool classes, and policy-based limits.

```mermaid
flowchart TB
    ORC["Orchestrator"] --> MEM["Memory Manager"]
    MEM --> RCTX["Research Context Bundle"]
    RCTX --> DISP["Research Dispatcher"]

    DISP --> COMP["Competitor Thread"]
    DISP --> AUD["Audience Thread"]
    DISP --> CHAN["Channel Thread"]
    DISP --> MKT["Market Thread"]
    DISP --> ADJ["Adjacent Thread"]
    DISP --> TMP["Temporal Thread"]

    COMP --> TOOLS1["search_web\nextract_page\nlookup_company\nsearch_news"]
    AUD --> TOOLS2["search_community\nsearch_web\nextract_page"]
    CHAN --> TOOLS3["search_web\nsearch_news\nsearch_community"]
    MKT --> TOOLS4["search_news\nlookup_company\nsearch_web"]
    ADJ --> TOOLS5["search_web\nsearch_news"]
    TMP --> TOOLS6["search_news\nlookup_trends"]

    TOOLS1 --> FIND["Thread Findings"]
    TOOLS2 --> FIND
    TOOLS3 --> FIND
    TOOLS4 --> FIND
    TOOLS5 --> FIND
    TOOLS6 --> FIND

    FIND --> SYN["Research Synthesizer"]
    SYN --> BRIEF["Briefing Summary"]
    SYN --> WRITE["Persist research_findings"]
    WRITE --> DB["intelligence_store"]
```

### Bounded branching control

```mermaid
flowchart LR
    Lead["Potential Sub-investigation Lead"]
    Conf{"confidence above threshold?"}
    Allow{"branch type allowed by policy?"}
    Budget{"depth and branch budget left?"}
    Branch["Spawn bounded branch"]
    Skip["Do not branch"]

    Lead --> Conf
    Conf -- no --> Skip
    Conf -- yes --> Allow
    Allow -- no --> Skip
    Allow -- yes --> Budget
    Budget -- no --> Skip
    Budget -- yes --> Branch
```

## 5. Segment and Prospect Flow

This stage is missing in V1 and introduced explicitly in V2.

```mermaid
flowchart TB
    BRIEF["Research Briefing + Findings"]
    SEG["Segment / Prospect Agent"]
    SRC1["CSV Upload"]
    SRC2["CRM Connector"]
    SRC3["Demo Seed List"]
    SRC4["Manual Entry"]
    CANDS["Segment Candidates"]
    SCORE["Prospect Scoring"]
    PICK["Prospect Picker UI"]
    STATE["CampaignState"]

    BRIEF --> SEG
    SRC1 --> SEG
    SRC2 --> SEG
    SRC3 --> SEG
    SRC4 --> SEG

    SEG --> CANDS
    SEG --> SCORE
    CANDS --> STATE
    SCORE --> PICK
    PICK --> STATE
```

### Prospect scoring model

```mermaid
flowchart LR
    Prospect["Prospect Record"]
    Segment["Selected Segment"]
    Findings["Top Findings"]
    Scores["Fit Score\nUrgency Score\nAngle Recommendation\nChannel Recommendation"]
    Cards["Compact Prospect Cards"]

    Prospect --> Scores
    Segment --> Scores
    Findings --> Scores
    Scores --> Cards
```

## 6. Content Generation and Traceability Flow

Content is not generated from raw conversation alone. It is assembled from selected, traceable upstream data.

```mermaid
flowchart LR
    MEM["Memory Manager"] --> BUNDLE["Content Context Bundle"]
    BUNDLE --> GEN["Content Agent"]

    RF["source finding IDs"] --> BUNDLE
    SEG["selected_segment_id"] --> BUNDLE
    PROS["selected_prospect_ids"] --> BUNDLE
    ANG["winning angle memory"] --> BUNDLE
    CH["intended channels"] --> BUNDLE

    GEN --> V1["Variant A"]
    GEN --> V2["Variant B"]
    GEN --> V3["Variant C"]
    GEN --> VIS["Visual Artifact"]

    V1 --> META["Hypothesis\nsuccess metric\nsource IDs"]
    V2 --> META
    V3 --> META

    META --> STORE["content_variants / visual_artifacts"]
```

### Traceability chain

```mermaid
flowchart LR
    F["Research Finding"]
    V["Content Variant"]
    D["Deployment Record"]
    E["Normalized Feedback Event"]
    R["Engagement Result"]
    L["Learning Delta / Intelligence Entry"]

    F --> V
    V --> D
    D --> E
    E --> R
    R --> L
    L -. confidence update .-> F
```

## 7. Deployment Dataflow

Deployment turns generated variants into provider-specific sends while preserving correlation IDs needed for later analysis.

```mermaid
sequenceDiagram
    autonumber
    participant UI as Thread UI
    participant API as FastAPI
    participant ORC as Orchestrator
    participant MEM as Memory Manager
    participant DEP as Deployment Agent
    participant DB as Stores
    participant RESEND as Resend
    participant UNI as Unipile

    UI->>API: Confirm & Deploy
    API->>DB: load current selections
    API->>ORC: deployment intent
    ORC->>MEM: request deployment bundle
    MEM->>DB: fetch variants, prospects, channels, rules
    MEM-->>DEP: deployment context

    alt email
        DEP->>RESEND: send rendered email
        RESEND-->>DEP: provider_message_id
    end

    alt linkedin
        DEP->>UNI: send DM
        UNI-->>DEP: provider_message_id
    end

    DEP->>DB: write deployment_records
    DEP-->>API: DeliveryStatusCard
    API-->>UI: stream confirmation + status
```

### Deployment record structure flow

```mermaid
flowchart TD
    Variant["variant_id"]
    Segment["segment_id"]
    Prospect["prospect_id"]
    Channel["channel"]
    Provider["provider"]
    PM["provider_message_id"]
    Cohort["A/B cohort"]
    Hash["rendered content hash"]
    Record["deployment_record"]

    Variant --> Record
    Segment --> Record
    Prospect --> Record
    Channel --> Record
    Provider --> Record
    PM --> Record
    Cohort --> Record
    Hash --> Record
```

## 8. Feedback Ingestion and Learning Flow

Feedback can arrive from provider webhooks or manual reporting inside the conversation. Both paths should converge into the same normalized event model.

```mermaid
flowchart TB
    WH1["/webhook/resend"]
    WH2["/webhook/unipile"]
    WH3["/webhook/engagement fallback"]
    MAN["Manual feedback in thread"]
    NORM["Normalization Layer"]
    QUAR["Unmatched Event Quarantine"]
    MAP["Correlation to deployment_record"]
    EVT["normalized_feedback_events"]
    AGG["Aggregate by variant / segment / channel"]
    RESULT["engagement_results"]
    LEARN["learning_delta + intelligence_entry"]
    CONF["finding confidence updates"]

    WH1 --> NORM
    WH2 --> NORM
    WH3 --> NORM
    MAN --> NORM

    NORM --> MAP
    MAP -- matched --> EVT
    MAP -- unmatched --> QUAR
    EVT --> AGG
    AGG --> RESULT
    RESULT --> LEARN
    RESULT --> CONF
```

### Feedback update levels

```mermaid
flowchart LR
    Event["Normalized Feedback Event"]
    D1["Deployment-level performance"]
    D2["Variant / Segment / Channel performance"]
    D3["Long-term finding confidence"]

    Event --> D1
    Event --> D2
    Event --> D3
```

## 9. Memory Management Model

V2 introduces a proper Memory Manager and explicitly separates memory layers. This is one of the main architectural improvements over V1.

```mermaid
flowchart TB
    subgraph WorkingMemory["Working Memory"]
        WM1["latest user message"]
        WM2["current UI action"]
        WM3["active stage snapshot"]
        WM4["recent turns"]
        WM5["task summary"]
    end

    subgraph SessionMemory["Session Memory"]
        SM1["CampaignState"]
        SM2["conversation transcript"]
        SM3["conversation_summary"]
        SM4["decision_log"]
        SM5["selected entities"]
        SM6["stage outputs"]
    end

    subgraph IntelligenceMemory["Intelligence Memory"]
        IM1["research_findings"]
        IM2["content_variants"]
        IM3["deployment_records"]
        IM4["engagement_results"]
        IM5["intelligence_entries"]
        IM6["performance history"]
    end

    subgraph ToolMemory["Tool Memory"]
        TM1["search cache"]
        TM2["page extracts"]
        TM3["competitor snapshots"]
        TM4["event dedupe ledger"]
    end
```

### Memory manager read/write behavior

```mermaid
flowchart LR
    ORC["Orchestrator / Specialist Agent"]
    MEM["Memory Manager"]
    WM["Working Memory"]
    SM["campaign_sessions"]
    IM["intelligence_store"]
    TM["tool_cache"]

    ORC --> MEM
    MEM --> WM
    MEM --> SM
    MEM --> IM
    MEM --> TM

    WM --> MEM
    SM --> MEM
    IM --> MEM
    TM --> MEM

    MEM --> ORC
```

## 10. Context Bundle Construction

The key memory behavior is not “store everything in prompt”. It is “retrieve only what this stage needs”.

```mermaid
flowchart TB
    Agent["Requested Agent"]
    MEM["Memory Manager"]
    TH["task_header"]
    ST["current_stage_state"]
    IN["latest_user_intent"]
    RM["recent_messages"]
    CS["relevant_cycle_summary"]
    LF["top_long_term_findings"]
    SE["selected_entities"]
    TR["tool_results_needed_for_this_call"]
    Bundle["Context Bundle"]

    Agent --> MEM
    MEM --> TH
    MEM --> ST
    MEM --> IN
    MEM --> RM
    MEM --> CS
    MEM --> LF
    MEM --> SE
    MEM --> TR

    TH --> Bundle
    ST --> Bundle
    IN --> Bundle
    RM --> Bundle
    CS --> Bundle
    LF --> Bundle
    SE --> Bundle
    TR --> Bundle
```

### Agent-specific budget policy

```mermaid
flowchart TD
    O["Orchestrator\n8-12 turns + stage summary + intent history"]
    R["Research Thread\ntask brief + prior intelligence + thread-specific context"]
    S["Research Synthesis\nmerged summaries, not raw extracts by default"]
    P["Segment / Prospect\nsegment criteria + prospect summaries + top findings"]
    C["Content\nbriefing summary + source findings + segment + winning angle memory"]
    D["Deployment\nselected variant + selected prospects + channel rules"]
    F["Feedback\ndeployment records + normalized metrics + source refs"]
```

## 11. Summarization and Prompt Load Reduction

When the conversation grows, the system reduces prompt load while preserving the raw source of truth in storage.

```mermaid
flowchart LR
    Transcript["Raw Transcript in Storage"]
    Threshold{"conversation exceeds threshold?"}
    Summary["conversation_summary"]
    Decisions["decision_log"]
    Verbatim["Keep verbatim:\nlatest turns\nunresolved clarifications\napprovals\nfinal selections"]
    Prompt["Future Prompt Payload"]

    Transcript --> Threshold
    Threshold -- no --> Prompt
    Threshold -- yes --> Summary
    Threshold -- yes --> Decisions
    Threshold -- yes --> Verbatim

    Summary --> Prompt
    Decisions --> Prompt
    Verbatim --> Prompt
```

### UI-assisted memory reduction

```mermaid
flowchart TB
    UI["UI Action"]
    IDOnly["store IDs + short labels"]
    Heavy["keep heavy payload in structured state"]
    Prompt["next prompt stays compact"]

    UI --> IDOnly
    UI --> Heavy
    IDOnly --> Prompt
    Heavy --> Prompt
```

Examples:

- selecting a variant stores `variant_id`, not the full comparison card
- selecting prospects stores references, not full table data in chat history
- running next cycle passes `next_cycle_brief`, not the whole results widget

## 12. Persistence Layout

The main persistent data stores and their responsibilities are:

```mermaid
flowchart TB
    subgraph SessionStore["campaign_sessions"]
        CS1["CampaignState"]
        CS2["conversation_summary"]
        CS3["decision_log"]
        CS4["active selections"]
    end

    subgraph IntelStore["intelligence_store"]
        IS1["research_findings"]
        IS2["content_variants"]
        IS3["visual_artifacts"]
        IS4["deployment_records"]
        IS5["engagement_results"]
        IS6["intelligence_entries"]
    end

    subgraph CacheStore["tool_cache"]
        TC1["search results TTL cache"]
        TC2["page extract cache"]
        TC3["normalized snapshots"]
        TC4["event dedupe ledger"]
    end

    subgraph RecoveryStore["recovery / quarantine"]
        RQ1["failed_threads markers"]
        RQ2["unmatched webhook events"]
        RQ3["degraded context flags"]
    end
```

## 13. Failure-Aware Dataflow

The architecture is designed to keep the loop moving even when parts fail.

```mermaid
flowchart TD
    Start["Runtime Operation"]
    RF{"research thread failed?"}
    MF{"memory read / summary failed?"}
    DF{"deployment provider failed?"}
    CF{"feedback correlation failed?"}

    Partial["continue with partial findings"]
    Local["use local session cache / degraded context"]
    Retry["show retry or resend UI"]
    Quarantine["store unmatched event for retry correlation"]
    Continue["continue overall campaign loop"]

    Start --> RF
    RF -- yes --> Partial --> Continue
    RF -- no --> MF
    MF -- yes --> Local --> Continue
    MF -- no --> DF
    DF -- yes --> Retry --> Continue
    DF -- no --> CF
    CF -- yes --> Quarantine --> Continue
    CF -- no --> Continue
```

## 14. Best Single-Screen Summary

If you need one compact view, this is the most representative dataflow for the whole system.

```mermaid
flowchart LR
    U["User / Operator"]
    UI["Thread UI + Interactive Cards"]
    API["WS / FastAPI"]
    ORC["Orchestrator"]
    MEM["Memory Manager"]
    RES["Research"]
    SEG["Segment / Prospects"]
    GEN["Content"]
    DEP["Deployment"]
    FBK["Feedback"]

    SESS[("campaign_sessions")]
    INTEL[("intelligence_store")]
    CACHE[("tool_cache")]

    EXT1["Search / Extract / News / Community"]
    EXT2["CSV / CRM"]
    EXT3["Gemini / Imagen"]
    EXT4["Resend / Unipile"]

    U --> UI --> API --> ORC
    ORC <--> MEM

    MEM <--> SESS
    MEM <--> INTEL
    MEM <--> CACHE

    ORC --> RES --> EXT1
    ORC --> SEG --> EXT2
    ORC --> GEN --> EXT3
    ORC --> DEP --> EXT4
    ORC --> FBK

    RES --> INTEL
    SEG --> SESS
    GEN --> INTEL
    DEP --> INTEL
    FBK --> INTEL
    FBK --> SESS

    API --> UI
```

## 15. Key Architectural Takeaways from V1 to V2

- V1 defines the closed-loop architecture clearly, especially research, generation, deployment, and feedback.
- V2 makes memory explicit instead of relying too much on large-context prompting.
- V2 adds the missing operational stage between research and deployment: segment and prospect handling.
- V2 also hardens traceability by introducing normalized feedback events, provider correlation, and a first-class Memory Manager.
- The most important dataflow idea is that prompts carry curated summaries and references, while the heavy payloads stay in structured state and persistent stores.
