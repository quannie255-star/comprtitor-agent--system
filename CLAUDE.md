# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AI驱动的竞品分析与Agent协作系统** (AI-Driven Competitive Analysis & Agent Collaboration System)

This project is in its initialization phase — no code has been committed yet.

## Architecture (Planned)

Based on the project name, the system will likely involve:
- **Competitive Analysis Module**: Automated gathering and analysis of competitor data using AI
- **Agent Collaboration Framework**: Multi-agent system for coordinating analysis tasks
- **AI Integration**: LLM-powered analysis and decision-making components

> Update this section as architectural decisions are made and code is written.

## Core Development Workflow: Plan-and-Execute (先规划后执行)

As an AI pair-programming assistant, you MUST strictly follow these rules:

1. **Never generate all code at once.** Always decompose work into minimal, verifiable steps.
2. **Plan Phase**: When receiving a new requirement or module, first output a 【技术方案】(Technical Proposal) and 【任务拆解清单 WBS】(Task Breakdown). Then stop and ask: **"是否同意该计划？"** (Do you agree with this plan?)
3. **Wait for Confirmation**: Do NOT write any substantive business code until the user explicitly replies with **"同意，请执行第 X 步"** (Approved, please execute Step X).
4. **Single-Step Execution**: Execute only ONE minimal verifiable step at a time. After completion, stop generating and explain how to run/test this step locally.
5. **Closed-Loop Verification**: If the user reports an error, prioritize fixing the current step's error first. Only after the fix is verified, ask whether to proceed to the next step.
6. **Context Continuity**: Before executing each step, briefly review the output of the previous step to ensure interface and data structure alignment.

## Development Setup

> Add build, test, and run commands once the tech stack is chosen and dependencies are configured.
