---
description: Use these instructions when working on the Signal-to-Action system, including agents, orchestration, memory management, UI integration, or data pipelines.
applyTo: "**/*.{ts,tsx,js,py,go,sql,json,yml,yaml}"
---

# Project Context — Signal to Action System

This repository implements a **closed-loop multi-agent growth intelligence system**.

The system transforms:
User Input → Research → Segmentation → Content → Deployment → Feedback → Learning

It operates as a **stateful orchestration system**, not a stateless API.

Key architectural components:
- LangGraph-based orchestration
- Multi-agent pipeline (Orchestrator, Research, Segment, Content, Deployment, Feedback)
- Memory Manager with layered memory
- Persistent stores (campaign_sessions, intelligence_store, tool_cache)
- WebSocket-driven UI with ephemeral components
- Strict traceability across the full lifecycle

Reference:
- :contentReference[oaicite:0]{index=0}
- :contentReference[oaicite:1]{index=1}
- :contentReference[oaicite:2]{index=2}

---

# Core Engineering Principles

## 1. This is a STATEFUL SYSTEM (not CRUD APIs)

- Every operation must read and update `CampaignState`
- Never write isolated logic that ignores system state
- All flows must preserve continuity across cycles

## 2. Traceability is REQUIRED (not optional)

Every entity must be linkable:

ResearchFinding → ContentVariant → DeploymentRecord → FeedbackEvent → Learning

- NEVER generate content without `source_finding_ids`
- NEVER store feedback without linking to `deployment_record_id`
- ALWAYS maintain IDs across transformations

## 3. Memory is Layered — Respect It

You MUST use correct memory layers:

- Working Memory → current execution only
- Session Memory → campaign state
- Intelligence Memory → long-term learning
- Tool Memory → cached external data

DO NOT:
- Dump entire datasets into prompts
- Pass full objects when IDs + summaries suffice

ALWAYS:
- Use **context bundles** per agent
- Retrieve only relevant data

---

# Agent Architecture Rules

## Orchestrator

- ONLY classifies intent and routes
- NEVER performs business logic
- MUST return structured output (no free text)

## Research Agent

- Uses bounded branching (controlled exploration)
- MUST produce structured `ResearchFinding`
- MUST include:
  - evidence
  - source_url
  - confidence
  - audience_language

## Segment / Prospect Agent

- Converts research → actionable audience
- MUST output scored prospects
- NEVER mix segmentation logic with content generation

## Content Agent

- MUST reference research findings
- MUST generate hypothesis-driven variants
- Variants must differ in STRATEGY (not wording)

## Deployment Agent

- MUST create `DeploymentRecord` per send
- MUST store provider IDs
- MUST support A/B cohort tracking

## Feedback Agent

- MUST normalize all events
- MUST update confidence scores
- MUST generate learning output

---

# Data & Schema Rules

## CampaignState is the SINGLE SOURCE OF TRUTH

- Never introduce parallel state systems
- Always update state immutably or predictably
- Avoid hidden side effects

## IDs over Objects

Prefer:
- `variant_id`, `finding_id`, `prospect_id`

Avoid:
- passing full objects in prompts or events

## Strong Typing Required

- Use TypedDict / Pydantic / interfaces
- Validate all inputs and outputs
- Never allow loosely structured data

---

# Context & Prompt Rules

## NEVER do this:
- Pass full conversation history blindly
- Include entire datasets in prompts
- Mix unrelated context

## ALWAYS do this:
- Build **context bundles**
- Include:
  - task_header
  - relevant findings
  - selected entities
  - recent decisions

This is critical for performance and correctness.

---

# UI + Backend Interaction Rules

## UI is ACTION-DRIVEN (not display-only)

- Every UI component must map to a backend action
- Use structured `ui_action` events
- Avoid free-text UI interactions when actions are deterministic

## Ephemeral UI Principles

- UI components are transient representations of state
- State lives in backend, NOT UI
- UI sends minimal payload (IDs, not objects)

---

# Feedback & Learning Rules

## Feedback must be normalized

All inputs (webhook/manual) → same structure:
- provider_message_id
- variant_id
- event_type
- timestamp

## Learning must be incremental

- Update confidence gradually (no binary jumps)
- Store reasoning for updates
- Preserve historical performance

---

# Reliability & Failure Handling

## System must degrade gracefully

If something fails:
- Continue with partial results
- Do NOT crash full flow

Examples:
- Research thread fails → continue with others
- Deployment fails → retry subset
- Feedback mismatch → quarantine event

## NEVER block entire pipeline

---

# Performance Constraints

- Minimize token usage (context discipline)
- Use caching for external calls
- Avoid redundant DB reads
- Prefer summaries over raw data

---

# Code Quality Expectations

- Production-grade, maintainable code only
- Clear naming aligned with domain:
  - CampaignState
  - ResearchFinding
  - DeploymentRecord
- No placeholder or mock logic unless explicitly requested
- Follow separation of concerns strictly

---

# When Generating Code

You MUST:

- Respect the multi-agent architecture
- Integrate with existing state and memory systems
- Maintain traceability
- Use typed schemas
- Consider failure cases

You MUST NOT:

- Build isolated utilities that ignore system design
- Hardcode flows that bypass orchestrator
- Skip ID linkage between entities

---

# Mental Model

This system is:

- NOT a chatbot
- NOT a simple pipeline
- NOT stateless

This system IS:

- A **closed-loop intelligence engine**
- A **state machine with memory**
- A **learning system that improves per cycle**

Always code with that model in mind.